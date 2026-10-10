# -*- coding: utf-8 -*-

"""``schtasks.exe`` とTask Scheduler XMLの小さな境界層。"""

from __future__ import annotations

import csv
import getpass
import io
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from xml.etree import ElementTree as ET

from ..models.config_model import ScheduleConfig
from .models import ScheduleServiceError


TASK_XML_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", TASK_XML_NAMESPACE)


def _tag(name: str) -> str:
    return f"{{{TASK_XML_NAMESPACE}}}{name}"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class TaskQueryResult:
    exists: bool
    running: bool = False
    xml: Optional[str] = None
    raw_details: str = ""
    next_run: Optional[datetime] = None
    last_run: Optional[datetime] = None
    last_result: Optional[int] = None
    enabled: Optional[bool] = None


def build_task_xml(
    config: ScheduleConfig,
    command: str | Path,
    arguments: Sequence[str] | str,
    *,
    now: Optional[datetime] = None,
    user_id: Optional[str] = None,
    working_directory: Optional[str | Path] = None,
) -> str:
    """daily/weekly/monthlyをネイティブCalendarTriggerへ変換する。"""

    if not config.is_supported:
        raise ScheduleServiceError(
            f"未対応のスケジュール方式です: {config.interval}",
            "SCHEDULE_UNSUPPORTED",
        )
    current = now or datetime.now().astimezone()
    hour, minute = (int(part) for part in config.time.split(":"))
    start = current.replace(hour=hour, minute=minute, second=0, microsecond=0)

    task = ET.Element(_tag("Task"), {"version": "1.4"})
    registration = ET.SubElement(task, _tag("RegistrationInfo"))
    ET.SubElement(registration, _tag("Date")).text = current.isoformat(timespec="seconds")
    ET.SubElement(registration, _tag("Author")).text = "ippi-down"
    ET.SubElement(registration, _tag("Description")).text = (
        "ippi-down の登録済み検索条件を使用して文書を定期取得します。"
    )

    triggers = ET.SubElement(task, _tag("Triggers"))
    calendar = ET.SubElement(triggers, _tag("CalendarTrigger"))
    # オフセットを付けると端末設定との組合せで時刻が変わるため、Task Scheduler
    # がローカル時刻として解釈する形式に固定する。
    ET.SubElement(calendar, _tag("StartBoundary")).text = start.strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    ET.SubElement(calendar, _tag("Enabled")).text = "true"
    if config.interval == "daily":
        schedule = ET.SubElement(calendar, _tag("ScheduleByDay"))
        ET.SubElement(schedule, _tag("DaysInterval")).text = "1"
    elif config.interval == "weekly":
        schedule = ET.SubElement(calendar, _tag("ScheduleByWeek"))
        ET.SubElement(schedule, _tag("WeeksInterval")).text = "1"
        days = ET.SubElement(schedule, _tag("DaysOfWeek"))
        ET.SubElement(days, _tag(config.weekday.capitalize()))
    else:
        schedule = ET.SubElement(calendar, _tag("ScheduleByMonth"))
        days = ET.SubElement(schedule, _tag("DaysOfMonth"))
        ET.SubElement(days, _tag("Day")).text = str(config.day_of_month)
        months = ET.SubElement(schedule, _tag("Months"))
        for month in (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ):
            ET.SubElement(months, _tag(month))

    principals = ET.SubElement(task, _tag("Principals"))
    principal = ET.SubElement(principals, _tag("Principal"), {"id": "Author"})
    account = user_id or _current_user_id()
    if account:
        ET.SubElement(principal, _tag("UserId")).text = account
    ET.SubElement(principal, _tag("LogonType")).text = "InteractiveToken"
    ET.SubElement(principal, _tag("RunLevel")).text = "LeastPrivilege"

    settings = ET.SubElement(task, _tag("Settings"))
    ET.SubElement(settings, _tag("MultipleInstancesPolicy")).text = "IgnoreNew"
    ET.SubElement(settings, _tag("DisallowStartIfOnBatteries")).text = "false"
    ET.SubElement(settings, _tag("StopIfGoingOnBatteries")).text = "false"
    ET.SubElement(settings, _tag("AllowHardTerminate")).text = "true"
    ET.SubElement(settings, _tag("StartWhenAvailable")).text = _bool_text(
        config.start_when_available
    )
    ET.SubElement(settings, _tag("RunOnlyIfNetworkAvailable")).text = "true"
    ET.SubElement(settings, _tag("AllowStartOnDemand")).text = "true"
    ET.SubElement(settings, _tag("Enabled")).text = "true"
    ET.SubElement(settings, _tag("Hidden")).text = "false"
    ET.SubElement(settings, _tag("RunOnlyIfIdle")).text = "false"
    ET.SubElement(settings, _tag("WakeToRun")).text = _bool_text(config.wake_to_run)
    # 最大2時間のキュー待機と最大2時間の処理時間を合わせたタスク上限。
    ET.SubElement(settings, _tag("ExecutionTimeLimit")).text = "PT4H"
    ET.SubElement(settings, _tag("Priority")).text = "7"

    actions = ET.SubElement(task, _tag("Actions"), {"Context": "Author"})
    execute = ET.SubElement(actions, _tag("Exec"))
    ET.SubElement(execute, _tag("Command")).text = str(command)
    argument_text = arguments if isinstance(arguments, str) else quote_windows_arguments(arguments)
    ET.SubElement(execute, _tag("Arguments")).text = argument_text
    if working_directory:
        ET.SubElement(execute, _tag("WorkingDirectory")).text = str(working_directory)

    body = ET.tostring(task, encoding="unicode", short_empty_elements=True)
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + body


def quote_windows_arguments(arguments: Sequence[str]) -> str:
    """CreateProcessと同じ規則で引数列を作る。"""

    return subprocess.list2cmdline([str(value) for value in arguments])


def task_definition_signature(xml_text: str) -> tuple[Any, ...]:
    """Task Schedulerが追記する管理情報を除外して定義を比較する。"""

    try:
        root = ET.fromstring(xml_text.lstrip("\ufeff\n\r "))
    except ET.ParseError as exc:
        raise ScheduleServiceError(
            "Windowsタスクの定義XMLを解析できません",
            "TASK_XML_INVALID",
        ) from exc

    def value(path: str, default: str = "") -> str:
        node = root.find(path, {"t": TASK_XML_NAMESPACE})
        return (node.text or default).strip() if node is not None else default

    trigger = root.find("t:Triggers/t:CalendarTrigger", {"t": TASK_XML_NAMESPACE})
    trigger_signature: tuple[Any, ...] = ()
    if trigger is not None:
        # Query結果にはRandomDelayなどの既定要素が追記されることがある。
        # XML全体ではなく、実行日時を決めるCalendarTriggerだけを比較する。
        boundary = (trigger.findtext(_tag("StartBoundary")) or "").strip()
        time_text = boundary.split("T", 1)[-1][:8] if "T" in boundary else boundary
        enabled = (trigger.findtext(_tag("Enabled")) or "true").strip().lower()

        daily = trigger.find(_tag("ScheduleByDay"))
        weekly = trigger.find(_tag("ScheduleByWeek"))
        monthly = trigger.find(_tag("ScheduleByMonth"))
        if daily is not None:
            recurrence: tuple[Any, ...] = (
                "daily",
                (daily.findtext(_tag("DaysInterval")) or "1").strip(),
            )
        elif weekly is not None:
            days = weekly.find(_tag("DaysOfWeek"))
            day_names = tuple(
                sorted(_local_name(child.tag) for child in list(days or ()))
            )
            recurrence = (
                "weekly",
                (weekly.findtext(_tag("WeeksInterval")) or "1").strip(),
                day_names,
            )
        elif monthly is not None:
            days = monthly.find(_tag("DaysOfMonth"))
            day_values = tuple(
                sorted(
                    (child.text or "").strip()
                    for child in list(days or ())
                    if _local_name(child.tag) == "Day"
                )
            )
            months = monthly.find(_tag("Months"))
            month_names = tuple(
                sorted(_local_name(child.tag) for child in list(months or ()))
            )
            recurrence = ("monthly", day_values, month_names)
        else:
            recurrence = ("unknown",)
        trigger_signature = (time_text, enabled, recurrence)
    return (
        trigger_signature,
        value("t:Settings/t:MultipleInstancesPolicy"),
        value("t:Settings/t:StartWhenAvailable"),
        value("t:Settings/t:RunOnlyIfNetworkAvailable"),
        value("t:Settings/t:WakeToRun", "false"),
        value("t:Settings/t:ExecutionTimeLimit"),
        value("t:Settings/t:Enabled", "true").lower(),
        value("t:Principals/t:Principal/t:LogonType"),
        value("t:Principals/t:Principal/t:RunLevel", "LeastPrivilege"),
        value("t:Actions/t:Exec/t:Command"),
        value("t:Actions/t:Exec/t:Arguments"),
        value("t:Actions/t:Exec/t:WorkingDirectory"),
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def task_definitions_match(actual: str, expected: str) -> bool:
    try:
        return task_definition_signature(actual) == task_definition_signature(expected)
    except ScheduleServiceError:
        return False


class SchtasksClient:
    """コマンド実行を注入可能にしたschtasks.exeクライアント。"""

    def __init__(
        self,
        runner: Optional[Callable[..., Any]] = None,
        *,
        executable: Optional[str | Path] = None,
        powershell_executable: Optional[str | Path] = None,
        folder_runner: Optional[Callable[..., Any]] = None,
        timeout_seconds: int = 30,
        query_cache_seconds: Optional[float] = None,
        xml_cache_seconds: Optional[float] = None,
        list_cache_seconds: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        runner_is_injected = runner is not None
        folder_runner_is_injected = folder_runner is not None
        self.runner = runner or subprocess.run
        self.folder_runner = folder_runner or self.runner
        self.executable = (
            str(executable)
            if executable is not None
            else (
                "schtasks.exe"
                if runner_is_injected
                else _trusted_windows_program("schtasks.exe")
            )
        )
        self.powershell_executable = (
            str(powershell_executable)
            if powershell_executable is not None
            else (
                "powershell.exe"
                if runner_is_injected or folder_runner_is_injected
                else _trusted_windows_program(
                    "powershell.exe",
                    "WindowsPowerShell",
                    "v1.0",
                )
            )
        )
        self.timeout_seconds = timeout_seconds
        self._clock = clock
        self._query_cache_seconds = max(
            0.0,
            float(
                query_cache_seconds
                if query_cache_seconds is not None
                else (0.0 if runner_is_injected else 1.0)
            ),
        )
        self._xml_cache_seconds = max(
            0.0,
            float(
                xml_cache_seconds
                if xml_cache_seconds is not None
                # 実行定義XMLはGUI起動時に検証し、以後はアプリ自身の
                # 登録変更かverbose照会でaction/enabled差分を検出した時だけ
                # 再取得する。通常pollごとの設定数分のprocess起動を避ける。
                else (0.0 if runner_is_injected else float("inf"))
            ),
        )
        self._list_cache_seconds = max(
            0.0,
            float(
                list_cache_seconds
                if list_cache_seconds is not None
                else (0.0 if runner_is_injected else 1.0)
            ),
        )
        self._cache_lock = threading.RLock()
        self._query_cache: dict[str, tuple[float, TaskQueryResult]] = {}
        self._xml_cache: dict[str, tuple[float, str]] = {}
        self._task_name_cache: Optional[tuple[float, tuple[str, ...]]] = None

    def _invalidate_query_cache(self, task_name: str) -> None:
        key = _normalise_task_name(task_name).casefold()
        with self._cache_lock:
            self._query_cache.pop(key, None)
            self._xml_cache.pop(key, None)
            self._task_name_cache = None

    def create_or_update(self, task_name: str, xml_text: str) -> None:
        temporary_path: Optional[Path] = None
        try:
            self.ensure_task_folder(task_name)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-16",
                newline="\r\n",
                suffix=".xml",
                prefix="ippi-down-task-",
                delete=False,
            ) as stream:
                # PythonがUTF-16 BOMを付けるため、本文側の宣言と一致する。
                stream.write(xml_text)
                temporary_path = Path(stream.name)
            result = self._execute(
                ["/Create", "/TN", task_name, "/XML", str(temporary_path), "/F"]
            )
            self._require_success(result, "TASK_REGISTER_FAILED", "Windowsタスクを登録できません")
            self._invalidate_query_cache(task_name)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    register_task = create_or_update

    def ensure_task_folder(self, task_name: str) -> None:
        """schtasksでは作れない親フォルダーをWindows標準COMで用意する。"""

        folder_path = _task_parent_folder(task_name)
        if folder_path is None:
            return
        # task_nameはアプリ側で生成するが、PowerShellへ渡す境界でも固定文字種に
        # 制限する。shellは介さず、単一引用符も許可しない。
        if not re.fullmatch(r"\\[A-Za-z0-9_.-]+(?:\\[A-Za-z0-9_.-]+)*", folder_path):
            raise ScheduleServiceError(
                f"Windowsタスクのフォルダー名が不正です: {folder_path}",
                "TASK_FOLDER_INVALID",
            )
        quoted_folder = folder_path.replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop';"
            "$service=New-Object -ComObject 'Schedule.Service';"
            "$service.Connect();"
            "$current=$service.GetFolder('\\');"
            f"$path='{quoted_folder}';"
            "foreach($part in $path.Trim('\\').Split('\\')){"
            "try{$current=$current.GetFolder($part)}"
            "catch{$current=$current.CreateFolder($part)}}"
        )
        result = self._execute_program(
            self.folder_runner,
            self.powershell_executable,
            ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            missing_code="POWERSHELL_NOT_FOUND",
            missing_message="Windowsタスクのフォルダー作成に必要なPowerShellが見つかりません",
        )
        self._require_success(
            result,
            "TASK_FOLDER_CREATE_FAILED",
            f"Windowsタスクのフォルダーを作成できません: {folder_path}",
        )

    def delete(self, task_name: str, *, missing_ok: bool = False) -> bool:
        result = self._execute(["/Delete", "/TN", task_name, "/F"])
        if result.returncode == 0:
            self._invalidate_query_cache(task_name)
            return True
        if missing_ok and _looks_missing(result):
            self._invalidate_query_cache(task_name)
            return False
        self._require_success(result, "TASK_DELETE_FAILED", "Windowsタスクを削除できません")
        return False

    delete_task = delete

    def set_enabled(self, task_name: str, enabled: bool) -> bool:
        """既存タスクの有効状態だけを変更する。"""

        switch = "/Enable" if enabled else "/Disable"
        result = self._execute(["/Change", "/TN", task_name, switch])
        self._require_success(
            result,
            "TASK_ENABLE_FAILED" if enabled else "TASK_DISABLE_FAILED",
            (
                "Windowsタスクを有効化できません"
                if enabled
                else "Windowsタスクを無効化できません"
            ),
        )
        self._invalidate_query_cache(task_name)
        return True

    def enable(self, task_name: str) -> bool:
        return self.set_enabled(task_name, True)

    def disable(self, task_name: str) -> bool:
        return self.set_enabled(task_name, False)

    def run(self, task_name: str) -> bool:
        result = self._execute(["/Run", "/TN", task_name])
        self._require_success(result, "TASK_RUN_FAILED", "Windowsタスクを開始できません")
        key = _normalise_task_name(task_name).casefold()
        with self._cache_lock:
            self._query_cache.pop(key, None)
        return True

    run_task = run

    def query(self, task_name: str) -> TaskQueryResult:
        key = _normalise_task_name(task_name).casefold()
        now = self._clock()
        with self._cache_lock:
            cached_query = self._query_cache.get(key)
            if (
                cached_query is not None
                and self._query_cache_seconds > 0
                and now - cached_query[0] <= self._query_cache_seconds
            ):
                return cached_query[1]
            cached_xml = self._xml_cache.get(key)
            xml_text = (
                cached_xml[1]
                if cached_xml is not None
                and self._xml_cache_seconds > 0
                and now - cached_xml[0] <= self._xml_cache_seconds
                else None
            )

        if xml_text is None:
            xml_result = self._execute(["/Query", "/TN", task_name, "/XML"])
            if xml_result.returncode != 0:
                if _looks_missing(xml_result):
                    result = TaskQueryResult(exists=False)
                    with self._cache_lock:
                        self._query_cache[key] = (now, result)
                        self._xml_cache.pop(key, None)
                    return result
                self._require_success(
                    xml_result,
                    "TASK_QUERY_FAILED",
                    "Windowsタスクを照会できません",
                )
            xml_text = xml_result.stdout
            with self._cache_lock:
                self._xml_cache[key] = (now, xml_text)

        detail_result = self._execute(["/Query", "/TN", task_name, "/V", "/FO", "CSV"])
        if detail_result.returncode != 0 and _looks_missing(detail_result):
            result = TaskQueryResult(exists=False)
            self._invalidate_query_cache(task_name)
            with self._cache_lock:
                self._query_cache[key] = (now, result)
            return result
        self._require_success(
            detail_result,
            "TASK_QUERY_DETAILS_FAILED",
            "Windowsタスクの実行状態を照会できません",
        )
        details = detail_result.stdout
        parsed = _parse_task_details(details)
        result = TaskQueryResult(
            exists=True,
            running=bool(parsed.get("running", _details_indicate_running(details))),
            xml=xml_text,
            raw_details=details,
            next_run=parsed.get("next_run"),
            last_run=parsed.get("last_run"),
            last_result=parsed.get("last_result"),
            enabled=_task_xml_enabled(xml_text),
        )
        with self._cache_lock:
            self._query_cache[key] = (now, result)
        return result

    query_task = query

    def query_many(
        self,
        task_names: Iterable[str],
    ) -> dict[str, TaskQueryResult]:
        """複数タスクの実行状態を1回のCSV照会で取得する。

        Task Schedulerの定義XMLはタスク単位にしか照会できないため、それだけを
        長めのキャッシュで再利用する。通常の定期更新では設定数にかかわらず
        ``schtasks /Query /V /FO CSV`` は1回だけ実行される。
        """

        names = tuple(dict.fromkeys(str(value) for value in task_names))
        if not names:
            return {}

        now = self._clock()
        results: dict[str, TaskQueryResult] = {}
        pending: list[str] = []
        with self._cache_lock:
            for task_name in names:
                key = _normalise_task_name(task_name).casefold()
                cached_query = self._query_cache.get(key)
                if (
                    cached_query is not None
                    and self._query_cache_seconds > 0
                    and now - cached_query[0] <= self._query_cache_seconds
                ):
                    results[task_name] = cached_query[1]
                else:
                    pending.append(task_name)
        if not pending:
            return results

        detail_result = self._execute(["/Query", "/V", "/FO", "CSV"])
        if detail_result.returncode != 0:
            if _looks_missing(detail_result):
                for task_name in pending:
                    result = TaskQueryResult(exists=False)
                    self._cache_query_result(task_name, now, result, clear_xml=True)
                    results[task_name] = result
                return results
            self._require_success(
                detail_result,
                "TASK_QUERY_DETAILS_FAILED",
                "Windowsタスクの実行状態を一括照会できません",
            )

        detail_rows = _parse_task_detail_rows(detail_result.stdout)
        if not detail_rows and detail_result.stdout.strip():
            # 未知の端末言語やschtasksの形式差で一括CSVを安全に
            # 解釈できない場合は、従来の個別照会へフォールバックする。
            for task_name in pending:
                results[task_name] = self.query(task_name)
            return results

        for task_name in pending:
            key = _normalise_task_name(task_name).casefold()
            row = detail_rows.get(key)
            if row is None:
                # 一覧取得とこの判定の間で削除された場合も欠落として
                # 扱う。外部タスクは次回更新で自然に反映される。
                result = TaskQueryResult(exists=False)
                self._cache_query_result(task_name, now, result, clear_xml=True)
                results[task_name] = result
                continue

            parsed, raw_details = row
            xml_text = self._get_cached_xml(key, now)
            if xml_text is not None and _task_details_require_xml_refresh(
                parsed, xml_text
            ):
                with self._cache_lock:
                    self._xml_cache.pop(key, None)
                xml_text = None
            if xml_text is None:
                xml_result = self._execute(["/Query", "/TN", task_name, "/XML"])
                if xml_result.returncode != 0:
                    if _looks_missing(xml_result):
                        result = TaskQueryResult(exists=False)
                        self._cache_query_result(
                            task_name,
                            now,
                            result,
                            clear_xml=True,
                        )
                        results[task_name] = result
                        continue
                    self._require_success(
                        xml_result,
                        "TASK_QUERY_FAILED",
                        "Windowsタスクを照会できません",
                    )
                xml_text = xml_result.stdout
                with self._cache_lock:
                    self._xml_cache[key] = (now, xml_text)

            result = TaskQueryResult(
                exists=True,
                running=bool(parsed.get("running", False)),
                xml=xml_text,
                raw_details=raw_details,
                next_run=parsed.get("next_run"),
                last_run=parsed.get("last_run"),
                last_result=parsed.get("last_result"),
                enabled=_task_xml_enabled(xml_text),
            )
            self._cache_query_result(task_name, now, result)
            results[task_name] = result
        return results

    def _get_cached_xml(self, key: str, now: float) -> Optional[str]:
        with self._cache_lock:
            cached_xml = self._xml_cache.get(key)
            if (
                cached_xml is not None
                and self._xml_cache_seconds > 0
                and now - cached_xml[0] <= self._xml_cache_seconds
            ):
                return cached_xml[1]
        return None

    def _cache_query_result(
        self,
        task_name: str,
        now: float,
        result: TaskQueryResult,
        *,
        clear_xml: bool = False,
    ) -> None:
        key = _normalise_task_name(task_name).casefold()
        with self._cache_lock:
            self._query_cache[key] = (now, result)
            if clear_xml:
                self._xml_cache.pop(key, None)

    def list_task_names(self, task_name_prefix: str) -> tuple[str, ...]:
        """指定prefixと安全なschedule-id suffixを持つタスクだけ列挙する。

        ``schtasks /Query`` は端末言語によって列名が変わるため、``/NH`` の
        CSV先頭列（タスク名）だけを使用する。削除や登録は一切行わない。
        """

        prefix = _normalise_task_name(task_name_prefix)
        if not re.fullmatch(
            r"\\ippi-down\\Download-[A-Za-z0-9_-]+",
            prefix,
            flags=re.IGNORECASE,
        ):
            raise ScheduleServiceError(
                f"Windowsタスクの検索prefixが不正です: {task_name_prefix}",
                "TASK_PREFIX_INVALID",
            )
        now = self._clock()
        use_cached_names = False
        with self._cache_lock:
            cached_names = self._task_name_cache
            if (
                cached_names is not None
                and self._list_cache_seconds > 0
                and now - cached_names[0] <= self._list_cache_seconds
            ):
                candidates = list(cached_names[1])
                use_cached_names = True
            else:
                candidates = []
        if not use_cached_names:
            result = self._execute(["/Query", "/FO", "CSV", "/NH"])
            self._require_success(
                result,
                "TASK_QUERY_FAILED",
                "Windowsタスクの一覧を照会できません",
            )
            try:
                rows = csv.reader(io.StringIO(result.stdout.lstrip("\ufeff")))
                candidates = [row[0] for row in rows if row]
            except (csv.Error, IndexError) as exc:
                raise ScheduleServiceError(
                    "Windowsタスクの一覧を解析できません",
                    "TASK_QUERY_DETAILS_INVALID",
                ) from exc
            with self._cache_lock:
                self._task_name_cache = (now, tuple(candidates))

        prefix_folded = prefix.casefold()
        matched: dict[str, str] = {}
        for raw_name in candidates:
            candidate = _normalise_task_name(raw_name)
            candidate_folded = candidate.casefold()
            if candidate_folded == prefix_folded:
                matched.setdefault(candidate_folded, candidate)
                continue
            separator = prefix + "-"
            if not candidate_folded.startswith(separator.casefold()):
                continue
            schedule_id = candidate[len(separator) :]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", schedule_id):
                continue
            matched.setdefault(candidate_folded, candidate)
        return tuple(sorted(matched.values(), key=str.casefold))

    list_names = list_task_names

    def exists(self, task_name: str) -> bool:
        return self.query(task_name).exists

    def _execute(self, arguments: Sequence[str]) -> CommandResult:
        return self._execute_program(
            self.runner,
            self.executable,
            arguments,
            missing_code="SCHTASKS_NOT_FOUND",
            missing_message="schtasks.exe が見つかりません",
        )

    def _execute_program(
        self,
        runner: Callable[..., Any],
        executable: Optional[str],
        arguments: Sequence[str],
        *,
        missing_code: str,
        missing_message: str,
    ) -> CommandResult:
        if not executable:
            raise ScheduleServiceError(
                missing_message,
                missing_code,
            )
        command = [executable, *arguments]
        try:
            try:
                raw = runner(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                    creationflags=_hidden_window_creation_flags(),
                )
            except TypeError:
                # 単純なfake runnerは引数列だけ受け取れるようにする。
                raw = runner(command)
        except FileNotFoundError as exc:
            raise ScheduleServiceError(
                missing_message,
                missing_code,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ScheduleServiceError(
                "Windowsタスクの操作がタイムアウトしました",
                "TASK_COMMAND_TIMEOUT",
            ) from exc
        return _coerce_command_result(raw)

    @staticmethod
    def _require_success(result: CommandResult, code: str, message: str) -> None:
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout).strip()
        if detail:
            message = f"{message}: {detail}"
        raise ScheduleServiceError(message, code)


# 分かりやすい正式名と、テスト・旧コード向けの名称を両方公開する。
WindowsTaskScheduler = SchtasksClient
TaskSchedulerClient = SchtasksClient


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _current_user_id() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    user = getpass.getuser().strip()
    return f"{domain}\\{user}" if domain and user else user


def _hidden_window_creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _windows_system_directory() -> Optional[Path]:
    """GetSystemDirectoryWだけを正本としてWindows system directoryを得る。"""

    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_system_directory = kernel32.GetSystemDirectoryW
        get_system_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        get_system_directory.restype = wintypes.UINT
        size = 260
        for _attempt in range(2):
            buffer = ctypes.create_unicode_buffer(size)
            length = int(get_system_directory(buffer, size))
            if not length:
                return None
            if length < size:
                directory = Path(buffer.value).resolve(strict=False)
                return directory if directory.is_absolute() else None
            size = min(length + 1, 32768)
        return None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _trusted_windows_program(
    executable_name: str,
    *relative_parts: str,
) -> Optional[str]:
    """PATH検索せずSystem32配下のWindows標準programを解決する。"""

    if os.name != "nt":
        return executable_name
    system_directory = _windows_system_directory()
    if system_directory is None:
        return None
    candidate = system_directory.joinpath(*relative_parts, executable_name)
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(system_directory)
    except (OSError, RuntimeError, ValueError):
        return None
    return str(resolved)


def _coerce_command_result(raw: Any) -> CommandResult:
    if isinstance(raw, CommandResult):
        return raw
    if isinstance(raw, tuple):
        values = list(raw) + ["", ""]
        return CommandResult(int(values[0]), str(values[1]), str(values[2]))
    if isinstance(raw, int):
        return CommandResult(raw)
    return CommandResult(
        int(getattr(raw, "returncode", 0)),
        str(getattr(raw, "stdout", "") or ""),
        str(getattr(raw, "stderr", "") or ""),
    )


def _looks_missing(result: CommandResult) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    tokens = (
        "cannot find",
        "not exist",
        "not found",
        "見つかりません",
        "見つけることができません",
        "存在しません",
    )
    return any(token in text for token in tokens)


def _task_parent_folder(task_name: str) -> Optional[str]:
    normalized = str(task_name).replace("/", "\\").strip()
    parts = [part for part in normalized.split("\\") if part]
    if len(parts) <= 1:
        return None
    return "\\" + "\\".join(parts[:-1])


def _normalise_task_name(task_name: str) -> str:
    """Task Schedulerの区切りを統一し、末尾separatorを除く。"""

    parts = [
        part.strip()
        for part in str(task_name or "").strip().replace("/", "\\").split("\\")
        if part.strip()
    ]
    return "\\" + "\\".join(parts) if parts else "\\"


def _details_indicate_running(details: str) -> bool:
    lowered = details.lower()
    if any(token in lowered for token in ("running", "実行中")):
        return True
    # CSVを解析できる場合も全セルを確認する（カンマを含むタスク名に対応）。
    try:
        rows = list(csv.reader(io.StringIO(details)))
    except csv.Error:
        return False
    return any(
        cell.strip().lower() in {"running", "実行中"}
        for row in rows
        for cell in row
    )


def _parse_task_details(details: str) -> dict[str, Any]:
    """英語・日本語のschtasks CSVから安定して必要項目だけを抽出する。"""

    try:
        rows = list(csv.reader(io.StringIO(details.lstrip("\ufeff"))))
    except csv.Error:
        return {"running": _details_indicate_running(details)}
    if len(rows) < 2:
        return {"running": _details_indicate_running(details)}
    headers = [_normalise_detail_header(value) for value in rows[0]]
    values = rows[-1]
    fields = {
        header: values[index].strip()
        for index, header in enumerate(headers)
        if header and index < len(values)
    }

    def first(*names: str) -> str:
        for name in names:
            value = fields.get(_normalise_detail_header(name), "")
            if value:
                return value
        return ""

    status = first("Status", "状態")
    task_to_run = first("Task To Run", "実行するタスク")
    scheduled_state = first(
        "Scheduled Task State",
        "スケジュールされたタスクの状態",
    )
    enabled: Optional[bool] = None
    normalized_state = scheduled_state.strip().lower()
    if normalized_state in {"enabled", "有効"}:
        enabled = True
    elif normalized_state in {"disabled", "無効"}:
        enabled = False
    last_result = _parse_task_result(
        first("Last Result", "前回の結果", "前回実行結果")
    )
    last_run = _parse_task_datetime(
        first("Last Run Time", "前回の実行時刻", "前回実行時刻")
    )
    if last_result == 0x41303:
        # 未実行タスクに対してschtasksが返す1999/11/30は実行履歴ではない。
        last_run = None
    return {
        "running": status.strip().lower() in {"running", "実行中"},
        "next_run": _parse_task_datetime(
            first("Next Run Time", "次回の実行時刻", "次回実行時刻")
        ),
        "last_run": last_run,
        "last_result": last_result,
        "task_to_run": task_to_run,
        "enabled": enabled,
    }


def _parse_task_detail_rows(
    details: str,
) -> dict[str, tuple[dict[str, Any], str]]:
    """Verbose CSVをタスク名ごとの詳細に分解する。

    ``schtasks /Query /V /FO CSV`` は端末言語でヘッダーが変わる。
    現在正式対応する日本語と英語のタスク名列だけを識別し、
    不明な形式は呼び出し側で個別照会へ戻せるよう空結果にする。
    """

    try:
        rows = list(csv.reader(io.StringIO(details.lstrip("\ufeff"))))
    except csv.Error:
        return {}
    if len(rows) < 2:
        return {}
    headers = rows[0]
    normalized_headers = [_normalise_detail_header(value) for value in headers]
    task_name_index: Optional[int] = None
    for index, header in enumerate(normalized_headers):
        if header in {
            _normalise_detail_header("TaskName"),
            _normalise_detail_header("タスク名"),
        }:
            task_name_index = index
            break
    if task_name_index is None:
        return {}

    parsed_rows: dict[str, tuple[dict[str, Any], str]] = {}
    for row in rows[1:]:
        if task_name_index >= len(row):
            continue
        raw_name = row[task_name_index].strip()
        if not raw_name:
            continue
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(headers)
        writer.writerow(row)
        raw_details = stream.getvalue()
        key = _normalise_task_name(raw_name).casefold()
        parsed_rows[key] = (_parse_task_details(raw_details), raw_details)
    return parsed_rows


def _normalise_detail_header(value: str) -> str:
    return "".join(str(value).strip().lower().split())


def _normalise_task_action(value: str) -> str:
    """schtasks CSVとXMLのactionをWindows向けに比較可能にする。"""

    return " ".join(str(value or "").replace('"', "").split()).casefold()


def _task_xml_action(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text.lstrip("\ufeff\n\r "))
    except ET.ParseError:
        return ""
    command = root.findtext(
        "t:Actions/t:Exec/t:Command",
        default="",
        namespaces={"t": TASK_XML_NAMESPACE},
    )
    arguments = root.findtext(
        "t:Actions/t:Exec/t:Arguments",
        default="",
        namespaces={"t": TASK_XML_NAMESPACE},
    )
    return _normalise_task_action(f"{command} {arguments}")


def _task_details_require_xml_refresh(
    parsed_details: Mapping[str, Any],
    xml_text: str,
) -> bool:
    """verbose照会で重要定義の外部変更を検出した場合だけXMLを再取得する。"""

    action = _normalise_task_action(
        str(parsed_details.get("task_to_run") or "")
    )
    if action:
        cached_action = _task_xml_action(xml_text)
        if not cached_action or action != cached_action:
            return True
    enabled = parsed_details.get("enabled")
    cached_enabled = _task_xml_enabled(xml_text)
    return (
        isinstance(enabled, bool)
        and cached_enabled is not None
        and enabled != cached_enabled
    )


def _parse_task_datetime(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text or text.lower() in {"n/a", "never", "なし", "該当なし"}:
        return None
    for pattern in (
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
    ):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=timezone(timedelta(hours=9), name="Asia/Tokyo"))
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=9), name="Asia/Tokyo"))
    return parsed


def _parse_task_result(value: str) -> Optional[int]:
    text = str(value or "").strip().lower()
    if not text or text in {"n/a", "never", "なし", "該当なし"}:
        return None
    match = re.search(r"0x[0-9a-f]+|[-+]?\d+", text)
    if match is None:
        return None
    try:
        return int(match.group(0), 0)
    except ValueError:
        return None


def _task_xml_enabled(xml_text: str) -> Optional[bool]:
    try:
        root = ET.fromstring(xml_text.lstrip("\ufeff\n\r "))
    except ET.ParseError:
        return None
    settings = root.findtext(
        "t:Settings/t:Enabled", default="true", namespaces={"t": TASK_XML_NAMESPACE}
    )
    trigger = root.findtext(
        "t:Triggers/t:CalendarTrigger/t:Enabled",
        default="true",
        namespaces={"t": TASK_XML_NAMESPACE},
    )
    return settings.strip().lower() == "true" and trigger.strip().lower() == "true"
