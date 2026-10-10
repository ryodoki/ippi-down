# -*- coding: utf-8 -*-

"""Windowsタスク登録・照会を一貫して扱うサービス。"""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config.config_manager import ConfigManager
from ..config.config_validator import ConfigValidator
from ..models.config_model import AppConfig, ScheduleConfig
from ..utils.path_utils import (
    get_base_path,
    get_logs_path,
    resolve_verified_local_path,
)
from ..app.run_guard import DOWNLOAD_RUN_GUARD, make_schedule_run_guard
from .ledger import ScheduleRunLedger
from .models import (
    DEFAULT_SCHEDULE_ID,
    ExternalScheduleImportCandidate,
    InstallationRelocationPreview,
    InstallationRelocationResult,
    ScheduleCapabilities,
    ScheduleDefinition,
    ScheduleImportPlan,
    ScheduleMigrationResult,
    ScheduleOrigin,
    ScheduleRegistration,
    ScheduleRegistrationStatus,
    ScheduleRegistry,
    ScheduleRegistrySnapshot,
    ScheduleServiceError,
    ScheduleState,
    ScheduledProfile,
    ScheduledRunRecord,
)
from .installation import (
    INSTALLATION_LOCATION_FILENAME,
    INSTALLATION_RELOCATION_JOURNAL_FILENAME,
    InstallationLocationStore,
    InstallationRelocationJournalStore,
    paths_equal,
    rebase_internal_path,
)
from .profile import (
    ScheduleProfileStore,
    calculate_condition_fingerprint,
)
from .registration import (
    DEFAULT_SCHEDULE_NAME,
    REGISTRATION_SCHEMA_VERSION,
    ScheduleRegistrationStore,
    make_storage_folder,
    next_storage_key,
    validate_schedule_id,
)
from .task_scheduler import (
    SchtasksClient,
    TaskQueryResult,
    build_task_xml,
    task_definitions_match,
)

def japan_timezone():
    """tzdata未同梱のWindowsでもJSTを扱えるtimezoneを返す。"""

    try:
        return ZoneInfo("Asia/Tokyo")
    except ZoneInfoNotFoundError:
        # 日本には現在DSTがないため、固定+09:00は次回日時計算に等価。
        return timezone(timedelta(hours=9), name="Asia/Tokyo")


def calculate_next_run(
    config: ScheduleConfig,
    now: Optional[datetime] = None,
) -> datetime:
    """指定日時より後の、正しい次回実行日時をAsia/Tokyoで返す。"""

    if not config.is_supported:
        raise ScheduleServiceError(
            f"未対応のスケジュール方式です: {config.interval}",
            "SCHEDULE_UNSUPPORTED",
        )
    timezone_info = japan_timezone()
    current = now or datetime.now(timezone_info)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone_info)
    else:
        current = current.astimezone(timezone_info)
    hour, minute = (int(value) for value in config.time.split(":"))

    if config.interval == "daily":
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate

    if config.interval == "weekly":
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        days_ahead = (weekdays[config.weekday] - current.weekday()) % 7
        candidate = (current + timedelta(days=days_ahead)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= current:
            candidate += timedelta(days=7)
        return candidate

    candidate = current.replace(
        day=config.day_of_month,
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    if candidate <= current:
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        candidate = candidate.replace(year=year, month=month)
    return candidate


next_run_time = calculate_next_run

_MIGRATION_JOURNAL_SCHEMA_VERSION = 1
_MIGRATION_JOURNAL_FILENAME = "schedule-migration-journal.json"
_MIGRATION_PHASES = {
    "PREPARED",
    "TARGET_STAGED",
    "OLD_DISABLED",
    "TARGET_APPLIED",
    "SOURCE_MIGRATED",
    "CLEANUP_PENDING",
    "ROLLBACK_FAILED",
}


@dataclass(frozen=True)
class _ExternalImportInspection:
    """移行プレビューと実行の間で再検証する内部情報。"""

    candidate: ExternalScheduleImportCandidate
    config: Optional[AppConfig] = None
    entry: Optional[dict[str, Any]] = None


class _SingleScheduleServiceBase:
    """既存ヘルパーとv1互換実装を保持する内部基底クラス。"""

    def __init__(
        self,
        *,
        config_dir: Optional[str | Path] = None,
        logs_dir: Optional[str | Path] = None,
        install_id: Optional[str] = None,
        task_client: Optional[SchtasksClient] = None,
        profile_store: Optional[ScheduleProfileStore] = None,
        ledger: Optional[ScheduleRunLedger] = None,
        executable: Optional[str | Path] = None,
        script_path: Optional[str | Path] = None,
        app_root: Optional[str | Path] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
        validator: Optional[ConfigValidator] = None,
        python_runner: Optional[Callable[..., Any]] = None,
        install_id_path: Optional[str | Path] = None,
        task_namespace_id: Optional[str] = None,
        task_namespace_id_path: Optional[str | Path] = None,
        coordination_id: Optional[str] = None,
        coordination_id_path: Optional[str | Path] = None,
        registration_store: Optional[ScheduleRegistrationStore] = None,
        installation_location_path: Optional[str | Path] = None,
        queue_status_provider: Optional[Callable[[str], Any]] = None,
        queue_ticket_provider: Optional[Callable[[], Iterable[Any]]] = None,
    ) -> None:
        self.app_root = Path(app_root or get_base_path()).resolve(strict=False)
        self.config_dir = Path(config_dir or self.app_root / "config").resolve(strict=False)
        self.logs_dir = Path(logs_dir or get_logs_path().parent).resolve(strict=False)
        explicit_namespace = task_namespace_id or install_id
        self._task_namespace_id = (
            self._validate_install_id(explicit_namespace)
            if explicit_namespace
            else None
        )
        self._coordination_id = (
            self._validate_install_id(coordination_id)
            if coordination_id
            else (self._validate_install_id(install_id) if install_id else None)
        )
        self._task_namespace_id_path = Path(
            task_namespace_id_path
            or self.config_dir / "schedule-instance-id"
        ).resolve(strict=False)
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        default_coordination_id_path = (
            Path(local_app_data) / "ippi-down" / "install-id"
            if os.name == "nt" and local_app_data
            else self.config_dir / "coordination-id"
        )
        self._coordination_id_path = Path(
            coordination_id_path
            or install_id_path
            or default_coordination_id_path
        ).resolve(strict=False)
        self.registration_path = self.config_dir / "schedule-registration.json"
        self.registration_store = registration_store or ScheduleRegistrationStore(
            self.registration_path
        )
        self.installation_location_path = Path(
            installation_location_path
            or self.config_dir / INSTALLATION_LOCATION_FILENAME
        ).resolve(strict=False)
        self.installation_location_store = InstallationLocationStore(
            self.installation_location_path
        )
        self.installation_relocation_journal_path = (
            self.config_dir / INSTALLATION_RELOCATION_JOURNAL_FILENAME
        ).resolve(strict=False)
        self.installation_relocation_journal_store = (
            InstallationRelocationJournalStore(
                self.installation_relocation_journal_path
            )
        )
        self.task_client = task_client or SchtasksClient()
        self.profile_store = profile_store or ScheduleProfileStore(
            self.config_dir / "schedule-profiles"
        )
        self.ledger = ledger or ScheduleRunLedger(self.logs_dir / "schedule-runs.jsonl")
        self.executable = Path(executable).resolve(strict=False) if executable else None
        self.script_path = (
            Path(script_path).resolve(strict=False)
            if script_path
            else (self.app_root / "src" / "main.py").resolve(strict=False)
        )
        self.now_provider = now_provider or (lambda: datetime.now(japan_timezone()))
        self.validator = validator or ConfigValidator()
        self.python_runner = python_runner or subprocess.run
        self.queue_status_provider = (
            queue_status_provider
            if queue_status_provider is not None
            else self._default_queue_status
        )
        self.queue_ticket_provider = (
            queue_ticket_provider
            if queue_ticket_provider is not None
            else self._default_queue_tickets
        )
        self._lock = threading.RLock()

    @property
    def install_id(self) -> str:
        """旧API互換。Windowsタスク用の配置単位namespaceを返す。"""

        return self.task_namespace_id

    @property
    def task_namespace_id(self) -> str:
        with self._lock:
            if self._task_namespace_id is None:
                self._task_namespace_id = self._load_or_create_task_namespace_id()
            return self._task_namespace_id

    @property
    def coordination_id(self) -> str:
        """ユーザー内のFIFO dispatcherが共有する識別子を返す。"""

        with self._lock:
            if self._coordination_id is None:
                self._coordination_id = self._load_or_create_coordination_id()
            return self._coordination_id

    @property
    def task_name(self) -> str:
        return self.task_name_for(DEFAULT_SCHEDULE_ID)

    def task_name_for(self, schedule_id: str) -> str:
        """論理スケジュールごとの安定したWindowsタスク名を返す。"""

        identifier = validate_schedule_id(schedule_id)
        base = f"\\ippi-down\\Download-{self.task_namespace_id}"
        return base if identifier == DEFAULT_SCHEDULE_ID else f"{base}-{identifier}"

    @staticmethod
    def _path_text_equal(left: object, right: object) -> bool:
        if left in {None, ""} or right in {None, ""}:
            return left in {None, ""} and right in {None, ""}
        try:
            return paths_equal(str(left), str(right))
        except (OSError, RuntimeError, ValueError):
            return False

    @classmethod
    def _arguments_equal(
        cls,
        recorded: Iterable[object],
        expected: Iterable[object],
    ) -> bool:
        old_values = tuple(str(value) for value in recorded)
        new_values = tuple(str(value) for value in expected)
        if len(old_values) != len(new_values):
            return False
        for old, new in zip(old_values, new_values):
            old_path = Path(old).expanduser()
            new_path = Path(new).expanduser()
            if old_path.is_absolute() or new_path.is_absolute():
                if not cls._path_text_equal(old, new):
                    return False
            elif old != new:
                return False
        return True

    def _current_action_changes(
        self,
        schedule_id: str,
        entry: Mapping[str, Any],
        profile: ScheduledProfile,
    ) -> tuple[tuple[str, str, str], ...]:
        """台帳の配置依存値と現在配置から導いた値の差分を返す。"""

        command, arguments, working_directory = self._resolve_action(
            profile.path,
            schedule_id,
        )
        changes: list[tuple[str, str, str]] = []
        recorded_snapshot = str(entry.get("snapshot_path") or "")
        if not self._path_text_equal(recorded_snapshot, profile.path):
            changes.append(("snapshot_path", recorded_snapshot, str(profile.path)))
        recorded_command = str(entry.get("command") or "")
        if not self._path_text_equal(recorded_command, command):
            changes.append(("command", recorded_command, str(command)))
        recorded_arguments = tuple(entry.get("arguments", ()) or ())
        if not self._arguments_equal(recorded_arguments, arguments):
            changes.append(
                (
                    "arguments",
                    " ".join(str(value) for value in recorded_arguments),
                    " ".join(str(value) for value in arguments),
                )
            )
        recorded_working = str(entry.get("working_directory") or "")
        expected_working = str(working_directory or "")
        if not self._path_text_equal(recorded_working, expected_working):
            changes.append(
                ("working_directory", recorded_working, expected_working)
            )
        return tuple(changes)

    @staticmethod
    def _entry_app_root(entry: Mapping[str, Any]) -> Optional[Path]:
        """旧台帳から、その登録が作成された配置ルートを推定する。"""

        working = str(entry.get("working_directory") or "").strip()
        if working:
            path = Path(working).expanduser()
            if path.is_absolute():
                return path.resolve(strict=False)
        command = Path(str(entry.get("command") or "")).expanduser()
        if not command.is_absolute():
            return None
        command = command.resolve(strict=False)
        if command.stem.casefold() in {"python", "pythonw"}:
            parents = command.parents
            if len(parents) >= 3 and parents[1].name.casefold() == ".venv":
                return parents[2]
        return command.parent

    def _entry_is_known_relocation(
        self,
        entry: Mapping[str, Any],
        profile: ScheduledProfile,
    ) -> bool:
        """snapshot差分が改ざんではなく配置全体の移動と証明できるか。"""

        old_root = self._entry_app_root(entry)
        if old_root is None or paths_equal(old_root, self.app_root):
            return False
        try:
            relative_profile = profile.path.resolve(strict=False).relative_to(
                self.app_root
            )
        except ValueError:
            return False
        recorded = str(entry.get("snapshot_path") or "")
        return bool(recorded) and paths_equal(
            recorded,
            old_root / relative_profile,
        )

    @staticmethod
    def _rebase_config_paths(
        config: AppConfig,
        old_root: Path,
        new_root: Path,
    ) -> tuple[tuple[str, str, str], ...]:
        changes: list[tuple[str, str, str]] = []
        for field, owner, attribute in (
            ("save_paths.local", config.save_paths, "local"),
            ("logging.file", config.logging, "file"),
        ):
            old_value = str(getattr(owner, attribute) or "")
            new_value = rebase_internal_path(old_value, old_root, new_root)
            if new_value is None or new_value == old_value:
                continue
            setattr(owner, attribute, new_value)
            changes.append((field, old_value, new_value))
        return tuple(changes)

    @staticmethod
    def _default_path_root_candidates(config: AppConfig) -> tuple[Path, ...]:
        """既定の保存先・ログから、配置ルートらしい絶対パスを抽出する。"""

        candidates: list[Path] = []
        save_path = Path(str(config.save_paths.local or "")).expanduser()
        if save_path.is_absolute() and save_path.name.casefold() == "downloads":
            candidates.append(save_path.parent.resolve(strict=False))

        log_path = Path(str(config.logging.file or "")).expanduser()
        if (
            log_path.is_absolute()
            and log_path.name.casefold() == "app.log"
            and log_path.parent.name.casefold() == "logs"
        ):
            candidates.append(log_path.parent.parent.resolve(strict=False))

        unique: list[Path] = []
        for candidate in candidates:
            if not any(paths_equal(candidate, item) for item in unique):
                unique.append(candidate)
        return tuple(unique)

    def _is_matching_installation_root(self, candidate: Path) -> bool:
        """外部データ置場を旧配置と誤認しないよう、配置IDと起動物を照合する。"""

        candidate = candidate.resolve(strict=False)
        if paths_equal(candidate, self.app_root) or not candidate.is_dir():
            return False
        namespace_path = candidate / "config" / "schedule-instance-id"
        try:
            namespace = namespace_path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if namespace != self.task_namespace_id:
            return False
        return (candidate / "ippi-down.exe").is_file() or (
            candidate / "src" / "main.py"
        ).is_file()

    def _add_path_derived_roots(
        self,
        candidates: list[Path],
        config: AppConfig,
    ) -> None:
        """同じ配置IDを持つ旧アプリだけをbootstrap候補へ追加する。"""

        for candidate in self._default_path_root_candidates(config):
            if not self._is_matching_installation_root(candidate):
                continue
            if not any(paths_equal(candidate, item) for item in candidates):
                candidates.append(candidate)

    def _registered_config_from_entry(
        self,
        entry: Mapping[str, Any],
    ) -> Optional[AppConfig]:
        """transactionを入れ子にせず、台帳entryの封印済み設定を読む。"""

        snapshot_id = self._snapshot_id(entry)
        if not snapshot_id:
            return None
        snapshot = self.profile_store.read(snapshot_id)
        try:
            return ConfigManager(
                str(self.profile_store.path_for(snapshot_id))
            )._dict_to_config(snapshot)
        except (TypeError, ValueError) as exc:
            raise ScheduleServiceError(
                f"登録済み検索条件の形式が不正です: {exc}",
                "PROFILE_INVALID",
            ) from exc

    def _recorded_installation_root(
        self,
        document: Mapping[str, Any],
        config: Optional[AppConfig] = None,
    ) -> tuple[Optional[Path], str]:
        """markerを優先し、台帳と封印済み設定をbootstrapに使う。"""

        try:
            relocation_journal = self.installation_relocation_journal_store.read()
            location = self.installation_location_store.read()
        except ScheduleServiceError as exc:
            return None, f"[{exc.reason_code}] {exc}"
        if relocation_journal is not None:
            if relocation_journal.task_namespace_id != self.task_namespace_id:
                return None, (
                    "[INSTALLATION_ID_MISMATCH] 配置移行の回復記録と"
                    "定期実行の配置IDが一致しません"
                )
            if not paths_equal(relocation_journal.current_root, self.app_root):
                return None, (
                    "[INSTALLATION_RELOCATION_JOURNAL_CONFLICT] 配置移行の"
                    "回復先と現在位置が一致しません"
                )
            return relocation_journal.old_root, ""
        if location is not None:
            if location.task_namespace_id != self.task_namespace_id:
                return None, (
                    "[INSTALLATION_ID_MISMATCH] 配置場所の管理情報と"
                    "定期実行の配置IDが一致しません"
                )
            if location.status == "retired":
                return None, (
                    "[INSTALLATION_RETIRED] この配置は移行済みのため起動できません。"
                    f"現在の配置: {location.moved_to or '-'}"
                )
            if not paths_equal(location.app_root, self.app_root):
                return location.app_root, ""

        candidates: list[Path] = []
        for entry in document.get("registrations", {}).values():
            if not isinstance(entry, Mapping) or self._entry_migrated_out(entry):
                continue
            root = self._entry_app_root(entry)
            if root is not None and not paths_equal(root, self.app_root):
                if not any(paths_equal(root, item) for item in candidates):
                    candidates.append(root)
        if config is not None:
            self._add_path_derived_roots(candidates, config)
        for entry in document.get("registrations", {}).values():
            if not isinstance(entry, Mapping) or self._entry_migrated_out(entry):
                continue
            try:
                registered_config = self._registered_config_from_entry(entry)
            except ScheduleServiceError:
                # preview本体で同じsnapshotを読み、具体的な整合性エラーを返す。
                continue
            if registered_config is not None:
                self._add_path_derived_roots(candidates, registered_config)
        if len(candidates) > 1:
            return None, (
                "[INSTALLATION_ROOT_AMBIGUOUS] 定期実行台帳に複数の旧配置"
                "パスがあるため、自動的に付け替えられません"
            )
        return (candidates[0] if candidates else self.app_root), ""

    def create_profile(
        self,
        config: AppConfig,
        *,
        schedule_id: str = DEFAULT_SCHEDULE_ID,
        display_name: str = "",
    ) -> ScheduledProfile:
        self._validate_app_config(config)
        return self.profile_store.create(
            config,
            schedule_id=validate_schedule_id(schedule_id),
            display_name=display_name,
            created_at=self._now(),
        )

    def register(self, config: AppConfig) -> ScheduleRegistrationStatus:
        """現在の設定を固定し、タスクを更新する。

        新規タスク登録に失敗した場合は新しいプロファイルだけを破棄し、以前の
        タスク、登録メタデータ、スナップショットを維持する。
        """

        with self._lock:
            self._validate_app_config(config)
            if not config.schedule.enabled:
                raise ScheduleServiceError(
                    "定期実行を有効にしてから登録してください",
                    "SCHEDULE_DISABLED",
                )
            if not config.schedule.uses_windows_task_scheduler:
                raise ScheduleServiceError(
                    "旧プロセス内スケジュールは使用できません。Windowsタスクへ移行してください",
                    "LEGACY_SCHEDULE_MIGRATION_REQUIRED",
                )

            previous_metadata = self._read_registration()
            previous_task = self._safe_query()
            profile = self.profile_store.create(config, created_at=self._now())
            task_updated = False
            try:
                command, arguments, working_directory = self._resolve_action(profile.path)
                xml_text = build_task_xml(
                    config.schedule,
                    command,
                    arguments,
                    now=self._now(),
                    working_directory=working_directory,
                )
                self.task_client.create_or_update(self.task_name, xml_text)
                task_updated = True
                metadata = {
                    "schema_version": REGISTRATION_SCHEMA_VERSION,
                    "task_name": self.task_name,
                    "profile_id": profile.profile_id,
                    "profile_path": str(profile.path),
                    "profile_fingerprint": profile.fingerprint,
                    "registered_at": self._now().isoformat(),
                    "schedule": asdict(config.schedule),
                    "command": str(command),
                    "arguments": list(arguments),
                    "working_directory": str(working_directory or ""),
                }
                self._write_registration(metadata)
            except Exception as exc:
                if task_updated:
                    self._restore_previous_task(previous_task, previous_metadata)
                try:
                    self.profile_store.delete(profile)
                except ScheduleServiceError:
                    pass
                if isinstance(exc, ScheduleServiceError):
                    raise
                raise ScheduleServiceError(
                    f"Windowsタスクを登録できません: {exc}",
                    "TASK_REGISTER_FAILED",
                ) from exc

            config.schedule.active_profile_id = profile.profile_id
            return ScheduleRegistrationStatus(
                state=ScheduleState.REGISTERED,
                registered=True,
                next_run=calculate_next_run(config.schedule, self._now()),
                task_name=self.task_name,
                profile_id=profile.profile_id,
                profile_fingerprint=profile.fingerprint,
            )

    update = register
    register_or_update = register

    def unregister(self, config: Optional[AppConfig] = None) -> bool:
        """タスク削除成功後にだけ登録状態を消す。"""

        with self._lock:
            try:
                self.task_client.delete(self.task_name, missing_ok=True)
            except TypeError:
                # 最小fake clientとの互換性。
                self.task_client.delete(self.task_name)
            try:
                self.registration_path.unlink(missing_ok=True)
            except OSError as exc:
                raise ScheduleServiceError(
                    "Windowsタスクは削除されましたが、登録情報を消去できません",
                    "REGISTRATION_METADATA_DELETE_FAILED",
                ) from exc
            if config is not None:
                config.schedule.enabled = False
                config.schedule.active_profile_id = None
            return True

    delete = unregister
    remove = unregister

    def run_now(self) -> bool:
        metadata = self._read_registration()
        if metadata is None:
            raise ScheduleServiceError(
                "定期実行が登録されていません",
                "TASK_NOT_REGISTERED",
            )
        return bool(self.task_client.run(self.task_name))

    run = run_now

    def capture_registration_state(self) -> dict[str, Any]:
        """設定保存失敗時に完全復元できる、プロセス内だけのバックアップ。"""

        with self._lock:
            metadata = self._read_registration()
            task_name = (
                str(metadata.get("task_name")) if metadata else self.task_name
            )
            try:
                task = self.task_client.query(task_name)
            except Exception as exc:
                raise ScheduleServiceError(
                    f"更新前のWindowsタスクを退避できません: {exc}",
                    "REGISTRATION_BACKUP_FAILED",
                ) from exc
            return {
                "metadata": deepcopy(metadata),
                "task": task,
                "task_name": task_name,
            }

    def restore_registration_state(self, state: Mapping[str, Any]) -> None:
        """``capture_registration_state``のタスクと管理情報を厳密に戻す。"""

        with self._lock:
            if not isinstance(state, Mapping):
                raise ScheduleServiceError(
                    "定期実行の退避情報が不正です",
                    "REGISTRATION_BACKUP_INVALID",
                )
            previous_metadata = state.get("metadata")
            previous_task = state.get("task")
            task_name = str(state.get("task_name") or self.task_name)
            try:
                current_metadata = self._read_registration()
            except ScheduleServiceError:
                current_metadata = None
            current_profile_id = (
                str(current_metadata.get("profile_id", ""))
                if current_metadata
                else ""
            )
            previous_profile_id = (
                str(previous_metadata.get("profile_id", ""))
                if isinstance(previous_metadata, Mapping)
                else ""
            )
            try:
                if (
                    isinstance(previous_task, TaskQueryResult)
                    and previous_task.exists
                    and previous_task.xml
                ):
                    self.task_client.create_or_update(task_name, previous_task.xml)
                elif isinstance(previous_metadata, Mapping):
                    schedule = self._schedule_from_metadata(previous_metadata)
                    xml_text = build_task_xml(
                        schedule,
                        str(previous_metadata.get("command", "")),
                        [
                            str(value)
                            for value in previous_metadata.get("arguments", [])
                        ],
                        now=self._now(),
                        working_directory=(
                            str(previous_metadata.get("working_directory", ""))
                            or None
                        ),
                    )
                    self.task_client.create_or_update(task_name, xml_text)
                else:
                    try:
                        self.task_client.delete(task_name, missing_ok=True)
                    except TypeError:
                        self.task_client.delete(task_name)

                if isinstance(previous_metadata, Mapping):
                    self._write_registration(dict(previous_metadata))
                else:
                    self.registration_path.unlink(missing_ok=True)
            except Exception as exc:
                if isinstance(exc, ScheduleServiceError):
                    raise ScheduleServiceError(
                        f"以前の定期実行登録を復元できません: {exc}",
                        "REGISTRATION_ROLLBACK_FAILED",
                    ) from exc
                raise ScheduleServiceError(
                    f"以前の定期実行登録を復元できません: {exc}",
                    "REGISTRATION_ROLLBACK_FAILED",
                ) from exc

            if current_profile_id and current_profile_id != previous_profile_id:
                try:
                    self.profile_store.delete(current_profile_id)
                except ScheduleServiceError:
                    # タスクとmetadataは既に復元済み。孤立profileの後処理だけで
                    # 正常な旧登録を失敗扱いにしない。
                    pass

    def get_registered_config(self) -> Optional[AppConfig]:
        """現在登録済みの不変スナップショットをAppConfigとして返す。"""

        with self._lock:
            metadata = self._read_registration()
            if metadata is None:
                return None
            profile_id = str(metadata.get("profile_id", ""))
            document = self.profile_store.read(profile_id)
            try:
                return ConfigManager(str(self.profile_store.path_for(profile_id)))._dict_to_config(
                    document
                )
            except (TypeError, ValueError) as exc:
                raise ScheduleServiceError(
                    f"登録済み検索条件の形式が不正です: {exc}",
                    "PROFILE_INVALID",
                ) from exc

    def get_status(
        self,
        config: Optional[AppConfig] = None,
        *,
        current_config: Optional[AppConfig] = None,
    ) -> ScheduleRegistrationStatus:
        """外部状態の欠落を例外にせず、GUI表示可能な状態へ変換する。"""

        effective_config = current_config or config
        try:
            metadata = self._read_registration()
            task_name = (
                str(metadata.get("task_name"))
                if metadata
                else self.task_name
            )
        except ScheduleServiceError as exc:
            return self._repair_status(
                r"\ippi-down\Download-unknown",
                exc.reason_code,
                str(exc),
                None,
            )

        try:
            query = self.task_client.query(task_name)
        except ScheduleServiceError as exc:
            return self._repair_status(task_name, exc.reason_code, str(exc), metadata)
        except Exception as exc:
            return self._repair_status(
                task_name, "TASK_QUERY_FAILED", f"Windowsタスクを照会できません: {exc}", metadata
            )

        if not query.exists:
            if metadata is None and (effective_config is None or not effective_config.schedule.enabled):
                return ScheduleRegistrationStatus(
                    state=ScheduleState.DISABLED, task_name=task_name
                )
            return self._repair_status(
                task_name,
                "TASK_NOT_FOUND",
                "登録済みのWindowsタスクが見つかりません。定期実行設定を保存し直してください",
                metadata,
            )
        if metadata is None:
            return self._repair_status(
                task_name,
                "REGISTRATION_METADATA_MISSING",
                "Windowsタスクの登録情報が見つかりません。定期実行設定を保存し直してください",
                None,
            )

        profile_id = str(metadata.get("profile_id", ""))
        try:
            profile = self.profile_store.get(profile_id)
        except ScheduleServiceError as exc:
            return self._repair_status(task_name, exc.reason_code, str(exc), metadata)

        command = Path(str(metadata.get("command", "")))
        if not command.is_file():
            return self._repair_status(
                task_name,
                "EXECUTABLE_NOT_FOUND",
                f"定期実行に登録された実行ファイルが見つかりません: {command}",
                metadata,
            )
        working_directory = str(metadata.get("working_directory", "")) or None
        if working_directory and not Path(working_directory).is_dir():
            return self._repair_status(
                task_name,
                "WORKING_DIRECTORY_NOT_FOUND",
                f"定期実行の作業フォルダーが見つかりません: {working_directory}",
                metadata,
                profile=profile,
            )
        if command.stem.lower() in {"python", "pythonw"}:
            try:
                self._validate_source_python(command)
            except ScheduleServiceError as exc:
                return self._repair_status(
                    task_name,
                    exc.reason_code,
                    str(exc),
                    metadata,
                    profile=profile,
                )
            arguments = [str(value) for value in metadata.get("arguments", [])]
            if not arguments or not Path(arguments[0]).is_file():
                return self._repair_status(
                    task_name,
                    "SCRIPT_NOT_FOUND",
                    "定期実行の起動スクリプトが見つかりません",
                    metadata,
                    profile=profile,
                )
        try:
            schedule = self._schedule_from_metadata(metadata)
            expected_xml = build_task_xml(
                schedule,
                command,
                [str(value) for value in metadata.get("arguments", [])],
                now=self._now(),
                working_directory=working_directory,
            )
        except ScheduleServiceError as exc:
            return self._repair_status(task_name, exc.reason_code, str(exc), metadata, profile=profile)
        except (TypeError, ValueError) as exc:
            return self._repair_status(
                task_name,
                "REGISTRATION_METADATA_INVALID",
                f"登録済みスケジュールの形式が不正です: {exc}",
                metadata,
                profile=profile,
            )
        if query.enabled is False:
            return self._repair_status(
                task_name,
                "TASK_DISABLED_EXTERNALLY",
                "Windowsタスクが無効化されています。定期実行設定を保存し直してください",
                metadata,
                profile=profile,
                definition_mismatch=True,
            )
        if not query.xml or not task_definitions_match(query.xml, expected_xml):
            return self._repair_status(
                task_name,
                "TASK_DEFINITION_MISMATCH",
                "Windowsタスクの定義が登録内容と一致しません。定期実行設定を保存し直してください",
                metadata,
                profile=profile,
                definition_mismatch=True,
            )

        # 登録更新直後に、旧プロファイルの失敗を新しい登録の前回結果として
        # 表示しない。
        latest = self.ledger.latest(profile.profile_id)
        fingerprint_changed = (
            effective_config is not None
            and not self.profile_store.matches_config(profile, effective_config)
        )
        schedule_changed = (
            effective_config is not None
            and self._schedule_comparison_key(effective_config.schedule)
            != self._schedule_comparison_key(schedule)
        )
        definition_mismatch = fingerprint_changed or schedule_changed
        task_failure = self._task_result_is_failure(query.last_result)
        task_failure_is_latest = task_failure and self._task_result_is_newer(
            query.last_run, latest
        )
        if query.running:
            state = ScheduleState.RUNNING
        elif definition_mismatch:
            state = ScheduleState.UPDATE_REQUIRED
        elif task_failure_is_latest:
            state = ScheduleState.LAST_FAILED
        elif latest is not None and latest.exit_code != 0:
            state = ScheduleState.LAST_FAILED
        else:
            state = ScheduleState.REGISTERED

        last_result = latest.result if latest else None
        reason_code = None
        if task_failure_is_latest:
            last_result = "failed"
            reason_code = f"TASK_EXIT_CODE_{query.last_result}"

        return ScheduleRegistrationStatus(
            state=state,
            registered=True,
            running=query.running,
            next_run=query.next_run or calculate_next_run(schedule, self._now()),
            last_run=query.last_run
            or ((latest.finished_at or latest.started_at) if latest else None),
            last_result=last_result,
            definition_mismatch=definition_mismatch,
            reason_code=reason_code,
            task_name=task_name,
            profile_id=profile.profile_id,
            profile_fingerprint=profile.fingerprint,
            new_count=latest.new_count if latest else 0,
            saved_count=latest.saved_count if latest else 0,
            existing_count=latest.existing_count if latest else 0,
            failed_count=latest.failed_count if latest else 0,
            task_exit_code=query.last_result,
        )

    # base末尾に残るv1 private実装よりこちらを優先する。
    def _read_registration(
        self,
        schedule_id: str = DEFAULT_SCHEDULE_ID,
    ) -> Optional[dict[str, Any]]:
        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            entry = document["registrations"].get(identifier)
            if entry is None:
                return None
            result = deepcopy(dict(entry))
            result["schema_version"] = REGISTRATION_SCHEMA_VERSION
            result["profile_id"] = self._snapshot_id(entry)
            result["profile_path"] = str(entry.get("snapshot_path") or "")
            result["profile_fingerprint"] = self._snapshot_fingerprint(entry)
            return result

    def _write_registration(self, metadata: dict[str, Any]) -> None:
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            revision = int(document.get("revision", 0) or 0)
            entry = deepcopy(dict(metadata))
            entry.pop("schema_version", None)
            entry.setdefault("schedule_id", DEFAULT_SCHEDULE_ID)
            entry.setdefault("name", DEFAULT_SCHEDULE_NAME)
            entry.setdefault("enabled", True)
            if "snapshot_id" not in entry and entry.get("profile_id"):
                entry["snapshot_id"] = entry["profile_id"]
            if "snapshot_path" not in entry and entry.get("profile_path"):
                entry["snapshot_path"] = entry["profile_path"]
            if "snapshot_fingerprint" not in entry and entry.get("profile_fingerprint"):
                entry["snapshot_fingerprint"] = entry["profile_fingerprint"]
            document["registrations"][DEFAULT_SCHEDULE_ID] = entry
            self.registration_store.write_unlocked(
                document,
                expected_revision=revision,
            )

    def _safe_query(self) -> Optional[TaskQueryResult]:
        return self._safe_query_for(self.task_name)

    @classmethod
    def _snapshot_ids_for_entry(
        cls,
        metadata: Optional[Mapping[str, Any]],
    ) -> set[str]:
        if not metadata:
            return set()
        result = {
            str(value)
            for value in metadata.get("retained_snapshot_ids", [])
            if value
        }
        active = cls._snapshot_id(metadata)
        if active:
            result.add(active)
        return result

    def _save_disabled_schedule(
        self,
        schedule_id: str,
        config: AppConfig,
        *,
        name: Optional[str],
        expected_revision: Optional[int],
        preserve_storage_identity: bool = False,
    ) -> ScheduleRegistrationStatus:
        registry = self.registration_store.read_unlocked()
        self._require_revision(registry, expected_revision)
        previous_metadata = deepcopy(
            registry["registrations"].get(schedule_id)
        )
        task_name = str(
            (previous_metadata or {}).get("task_name")
            or self.task_name_for(schedule_id)
        )
        previous_task = self._safe_query_for(task_name)
        display_name = self._schedule_name(name, previous_metadata, schedule_id)
        self._ensure_unique_name(
            registry,
            display_name,
            exclude_schedule_id=schedule_id,
        )
        snapshot_id = uuid.uuid4().hex
        snapshot_config = deepcopy(config)
        if preserve_storage_identity:
            self._validate_preserved_storage_identity(
                snapshot_config,
                registry,
                schedule_id,
            )
        else:
            self._prepare_schedule_storage(
                snapshot_config,
                registry,
                display_name,
                previous_metadata,
            )
        self._validate_app_config(snapshot_config)
        snapshot_config.schedule.enabled = False
        snapshot_config.schedule.active_profile_id = snapshot_id
        profile = self.profile_store.create(
            snapshot_config,
            snapshot_id=snapshot_id,
            schedule_id=schedule_id,
            display_name=display_name,
            created_at=self._now(),
        )
        task_changed = False
        try:
            command, arguments, working_directory = self._resolve_action(
                profile.path,
                schedule_id,
            )
            try:
                self.task_client.delete(task_name, missing_ok=True)
            except TypeError:
                self.task_client.delete(task_name)
            task_changed = bool(previous_task and previous_task.exists)
            metadata = self._make_entry(
                schedule_id,
                display_name,
                False,
                task_name,
                profile,
                snapshot_config.schedule,
                command,
                arguments,
                working_directory,
                storage_key=snapshot_config.save_paths.schedule_storage_key,
                storage_folder=snapshot_config.save_paths.schedule_storage_folder,
                previous_metadata=previous_metadata,
            )
            self._put_registration(
                schedule_id,
                metadata,
                expected_revision=int(registry.get("revision", 0) or 0),
            )
            if previous_task is not None and not previous_task.running:
                self.cleanup_retained_snapshots(schedule_id=schedule_id)
        except Exception as exc:
            rollback_error: Optional[Exception] = None
            if task_changed:
                try:
                    self._restore_task(
                        task_name,
                        previous_task,
                        previous_metadata,
                        strict=True,
                    )
                except Exception as restore_exc:
                    rollback_error = restore_exc
            try:
                self.profile_store.delete(profile)
            except ScheduleServiceError:
                pass
            if rollback_error is not None:
                raise ScheduleServiceError(
                    "以前のWindowsタスクを復元できません。定期実行を修復してください",
                    "REGISTRATION_ROLLBACK_FAILED",
                ) from rollback_error
            if isinstance(exc, ScheduleServiceError):
                raise
            raise ScheduleServiceError(
                f"無効な定期実行設定を保存できません: {exc}",
                "REGISTRATION_METADATA_WRITE_FAILED",
            ) from exc
        config.schedule.active_profile_id = profile.snapshot_id
        config.save_paths = deepcopy(snapshot_config.save_paths)
        current_entries = self.registration_store.read_unlocked()["registrations"]
        status = ScheduleRegistrationStatus(
            state=ScheduleState.DISABLED,
            registered=False,
            enabled=False,
            task_name=task_name,
            schedule_id=schedule_id,
            name=display_name,
            profile_id=profile.snapshot_id,
            snapshot_id=profile.snapshot_id,
            profile_fingerprint=profile.fingerprint,
            storage_key=snapshot_config.save_paths.schedule_storage_key,
            storage_folder=snapshot_config.save_paths.schedule_storage_folder,
        )
        return self._decorate_condition_status(
            status,
            schedule_id,
            current_entries.get(schedule_id),
            current_entries,
        )

    def _apply_existing_registration(
        self,
        schedule_id: str,
        *,
        enabled: bool,
        expected_revision: Optional[int],
        force: bool = False,
    ) -> ScheduleRegistrationStatus:
        del force  # 呼出し意図をAPIに残し、常に外部定義を再適用する。
        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            self._require_revision(document, expected_revision)
            entry = deepcopy(document["registrations"].get(identifier))
            if entry is None:
                raise ScheduleServiceError(
                    "対象の定期実行が見つかりません",
                    "SCHEDULE_NOT_FOUND",
                )
            previous_metadata = deepcopy(entry)
            snapshot_id = self._snapshot_id(entry)
            profile = self.profile_store.get(snapshot_id)
            schedule = self._schedule_from_metadata(entry)
            schedule_values = asdict(schedule)
            schedule_values["enabled"] = enabled
            schedule_values["active_profile_id"] = snapshot_id
            try:
                # disabled時に許容された未完成入力を、有効化時には必ず
                # ScheduleConfigの同じ規則で再検証する。
                schedule = ScheduleConfig(**schedule_values)
            except (TypeError, ValueError) as exc:
                raise ScheduleServiceError(
                    f"定期実行設定が不正なため有効化できません: {exc}",
                    "CONFIG_INVALID",
                ) from exc
            task_name = str(entry.get("task_name") or self.task_name_for(identifier))
            previous_task = self._safe_query_for(task_name)
            task_changed = False
            try:
                command, arguments, working_directory = self._resolve_action(
                    profile.path,
                    identifier,
                )
                if enabled:
                    xml_text = build_task_xml(
                        schedule,
                        command,
                        arguments,
                        now=self._now(),
                        working_directory=working_directory,
                    )
                    self.task_client.create_or_update(task_name, xml_text)
                    task_changed = True
                else:
                    try:
                        self.task_client.delete(task_name, missing_ok=True)
                    except TypeError:
                        self.task_client.delete(task_name)
                    task_changed = bool(previous_task and previous_task.exists)
                entry.update(
                    {
                        "enabled": enabled,
                        "owner_instance_id": self.task_namespace_id,
                        "lifecycle_state": (
                            "ACTIVE" if enabled else "DISABLED"
                        ),
                        "snapshot_path": str(profile.path),
                        "snapshot_fingerprint": profile.fingerprint,
                        "condition_fingerprint": calculate_condition_fingerprint(
                            self.profile_store.read(profile.snapshot_id)
                        ),
                        "schedule": asdict(schedule),
                        "command": str(command),
                        "arguments": list(arguments),
                        "working_directory": str(working_directory or ""),
                        "updated_at": self._now().isoformat(),
                        "created_at": str(
                            entry.get("created_at")
                            or entry.get("registered_at")
                            or self._now().isoformat()
                        ),
                    }
                )
                self._put_registration(
                    identifier,
                    entry,
                    expected_revision=int(document.get("revision", 0) or 0),
                )
            except Exception as exc:
                rollback_error: Optional[Exception] = None
                if task_changed:
                    try:
                        self._restore_task(
                            task_name,
                            previous_task,
                            previous_metadata,
                            strict=True,
                        )
                    except Exception as restore_exc:
                        rollback_error = restore_exc
                if rollback_error is not None:
                    raise ScheduleServiceError(
                        "以前のWindowsタスクを復元できません。定期実行を修復してください",
                        "REGISTRATION_ROLLBACK_FAILED",
                    ) from rollback_error
                raise exc
            if not enabled:
                current_entries = self.registration_store.read_unlocked()[
                    "registrations"
                ]
                status = ScheduleRegistrationStatus(
                    state=ScheduleState.DISABLED,
                    registered=False,
                    enabled=False,
                    task_name=task_name,
                    schedule_id=identifier,
                    name=str(entry.get("name") or DEFAULT_SCHEDULE_NAME),
                    profile_id=snapshot_id,
                    snapshot_id=snapshot_id,
                    profile_fingerprint=profile.fingerprint,
                    storage_key=str(entry.get("storage_key") or ""),
                    storage_folder=str(entry.get("storage_folder") or ""),
                )
                return self._decorate_condition_status(
                    status,
                    identifier,
                    current_entries.get(identifier),
                    current_entries,
                )
            return self.get_schedule_status(identifier)

    def _make_entry(
        self,
        schedule_id: str,
        name: str,
        enabled: bool,
        task_name: str,
        profile: ScheduledProfile,
        schedule: ScheduleConfig,
        command: Path,
        arguments: list[str],
        working_directory: Optional[Path],
        *,
        storage_key: str = "",
        storage_folder: str = "",
        previous_metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        timestamp = self._now().isoformat()
        retained_snapshot_ids = self._snapshot_ids_for_entry(previous_metadata)
        retained_snapshot_ids.discard(profile.snapshot_id)
        return {
            "schedule_id": schedule_id,
            "name": name,
            "enabled": enabled,
            "owner_instance_id": self.task_namespace_id,
            "lifecycle_state": "ACTIVE" if enabled else "DISABLED",
            "task_name": task_name,
            "snapshot_id": profile.snapshot_id,
            "snapshot_path": str(profile.path),
            "snapshot_fingerprint": profile.fingerprint,
            "condition_fingerprint": calculate_condition_fingerprint(
                self.profile_store.read(profile.snapshot_id)
            ),
            "storage_key": str(storage_key or ""),
            "storage_folder": str(storage_folder or ""),
            "registered_at": timestamp,
            "created_at": str(
                (previous_metadata or {}).get("created_at")
                or (previous_metadata or {}).get("registered_at")
                or timestamp
            ),
            "updated_at": timestamp,
            "retained_snapshot_ids": sorted(retained_snapshot_ids),
            "schedule": asdict(schedule),
            "command": str(command),
            "arguments": list(arguments),
            "working_directory": str(working_directory or ""),
        }

    def _registration_from_entry(
        self,
        entry: Mapping[str, Any],
    ) -> ScheduleDefinition:
        schedule_id = validate_schedule_id(str(entry.get("schedule_id") or ""))
        snapshot_id = self._snapshot_id(entry)
        if not snapshot_id:
            raise ScheduleServiceError(
                "定期実行登録にスナップショットIDがありません",
                "REGISTRATION_METADATA_INVALID",
            )
        def parse_timestamp(key: str) -> Optional[datetime]:
            if not entry.get(key):
                return None
            try:
                return datetime.fromisoformat(str(entry[key]))
            except ValueError as exc:
                raise ScheduleServiceError(
                    f"定期実行の{key}が不正です",
                    "REGISTRATION_METADATA_INVALID",
                ) from exc

        registered_at = parse_timestamp("registered_at")
        working = str(entry.get("working_directory") or "")
        return ScheduleRegistration(
            schedule_id=schedule_id,
            name=str(entry.get("name") or DEFAULT_SCHEDULE_NAME),
            enabled=bool(entry.get("enabled", True)),
            task_name=str(entry.get("task_name") or self.task_name_for(schedule_id)),
            snapshot_id=snapshot_id,
            snapshot_path=Path(str(entry.get("snapshot_path") or "")),
            snapshot_fingerprint=self._snapshot_fingerprint(entry),
            registered_at=registered_at,
            schedule=self._schedule_from_metadata(entry),
            command=Path(str(entry.get("command") or "")),
            arguments=tuple(str(value) for value in entry.get("arguments", [])),
            working_directory=Path(working) if working else None,
            created_at=parse_timestamp("created_at") or registered_at,
            updated_at=parse_timestamp("updated_at") or registered_at,
            condition_fingerprint=str(entry.get("condition_fingerprint") or ""),
            storage_key=str(entry.get("storage_key") or ""),
            storage_folder=str(entry.get("storage_folder") or ""),
        )

    def _repair_status_for(
        self,
        schedule_id: str,
        task_name: str,
        reason_code: str,
        reason: str,
        metadata: Optional[Mapping[str, Any]],
        *,
        profile: Optional[ScheduledProfile] = None,
        definition_mismatch: bool = False,
    ) -> ScheduleRegistrationStatus:
        snapshot_id = profile.snapshot_id if profile else self._snapshot_id(metadata)
        return ScheduleRegistrationStatus(
            state=ScheduleState.REPAIR_REQUIRED,
            registered=reason_code not in {"TASK_NOT_FOUND", "TASK_NOT_REGISTERED"},
            enabled=bool(metadata.get("enabled", True)) if metadata else False,
            definition_mismatch=definition_mismatch,
            repair_reason=reason,
            reason_code=reason_code,
            task_name=task_name,
            schedule_id=schedule_id,
            name=str(metadata.get("name") or DEFAULT_SCHEDULE_NAME)
            if metadata
            else "",
            profile_id=snapshot_id or None,
            snapshot_id=snapshot_id or None,
            profile_fingerprint=(
                profile.fingerprint
                if profile
                else self._snapshot_fingerprint(metadata) or None
            ),
            storage_key=str((metadata or {}).get("storage_key") or ""),
            storage_folder=str((metadata or {}).get("storage_folder") or ""),
        )

    def _external_task_status(
        self,
        schedule_id: str,
        task_name: str,
        query: TaskQueryResult,
        *,
        reason_code: str,
        reason: str,
        external_id: str = "",
        importable: bool = False,
        display_name: str = "",
    ) -> ScheduleRegistrationStatus:
        """台帳外taskを一括・個別照会で同じ分類へ正規化する。"""

        row_id = external_id or schedule_id
        return ScheduleRegistrationStatus(
            state=ScheduleState.EXTERNAL,
            registered=True,
            running=query.running,
            enabled=query.enabled is not False,
            next_run=query.next_run,
            last_run=query.last_run,
            last_result=(
                "failed"
                if self._task_result_is_failure(query.last_result)
                else ("success" if query.last_result == 0 else None)
            ),
            repair_reason=reason,
            reason_code=reason_code,
            task_name=task_name,
            task_exit_code=query.last_result,
            schedule_id=row_id,
            source_schedule_id=schedule_id,
            external_id=row_id,
            name=display_name or self._orphan_schedule_name(schedule_id),
            origin=ScheduleOrigin.EXTERNAL_TASK,
            capabilities=ScheduleCapabilities.external(
                importable=importable and not query.running,
                removable=not query.running,
            ),
        )

    def _put_registration(
        self,
        schedule_id: str,
        metadata: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> None:
        """対象1件のみを書き、defaultでは旧テスト用hookも維持する。"""

        if schedule_id == DEFAULT_SCHEDULE_ID:
            # GUIの既存rollbackテストが差し替える境界を残す。revisionは
            # 呼出し直前に同じtransaction内で検査済み。
            self._write_registration(dict(metadata))
            return
        document = self.registration_store.read_unlocked()
        self._require_revision(document, expected_revision)
        document["registrations"][schedule_id] = dict(metadata)
        self.registration_store.write_unlocked(
            document,
            expected_revision=expected_revision,
        )

    def _read_registration(
        self,
        schedule_id: str = DEFAULT_SCHEDULE_ID,
    ) -> Optional[dict[str, Any]]:
        """v1 private API互換。返却値には旧profileキーも投影する。"""

        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            entry = document["registrations"].get(identifier)
            if entry is None:
                return None
            result = deepcopy(dict(entry))
            result["schema_version"] = REGISTRATION_SCHEMA_VERSION
            result["profile_id"] = self._snapshot_id(entry)
            result["profile_path"] = str(entry.get("snapshot_path") or "")
            result["profile_fingerprint"] = self._snapshot_fingerprint(entry)
            return result

    def _write_registration(self, metadata: dict[str, Any]) -> None:
        """default entryを書き換えるv1 private API互換境界。"""

        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            revision = int(document.get("revision", 0) or 0)
            entry = deepcopy(dict(metadata))
            entry.pop("schema_version", None)
            entry.setdefault("schedule_id", DEFAULT_SCHEDULE_ID)
            entry.setdefault("name", DEFAULT_SCHEDULE_NAME)
            entry.setdefault("enabled", True)
            if "snapshot_id" not in entry and entry.get("profile_id"):
                entry["snapshot_id"] = entry["profile_id"]
            if "snapshot_path" not in entry and entry.get("profile_path"):
                entry["snapshot_path"] = entry["profile_path"]
            if "snapshot_fingerprint" not in entry and entry.get("profile_fingerprint"):
                entry["snapshot_fingerprint"] = entry["profile_fingerprint"]
            document["registrations"][DEFAULT_SCHEDULE_ID] = entry
            self.registration_store.write_unlocked(
                document,
                expected_revision=revision,
            )

    @staticmethod
    def _snapshot_id(metadata: Optional[Mapping[str, Any]]) -> str:
        if not metadata:
            return ""
        return str(metadata.get("snapshot_id") or metadata.get("profile_id") or "")

    @staticmethod
    def _snapshot_fingerprint(metadata: Optional[Mapping[str, Any]]) -> str:
        if not metadata:
            return ""
        return str(
            metadata.get("snapshot_fingerprint")
            or metadata.get("profile_fingerprint")
            or ""
        )

    @staticmethod
    def _require_revision(
        registry: Mapping[str, Any],
        expected_revision: Optional[int],
    ) -> None:
        if expected_revision is None:
            return
        actual = int(registry.get("revision", 0) or 0)
        if actual != int(expected_revision):
            raise ScheduleServiceError(
                "定期実行の登録情報が別の画面またはプロセスで更新されました",
                "REGISTRATION_CONFLICT",
            )

    @staticmethod
    def _schedule_name(
        requested: Optional[str],
        previous: Optional[Mapping[str, Any]],
        schedule_id: str,
    ) -> str:
        value = str(
            requested
            if requested is not None
            else (previous or {}).get("name")
            or (DEFAULT_SCHEDULE_NAME if schedule_id == DEFAULT_SCHEDULE_ID else schedule_id)
        ).strip()
        if not value or len(value) > 80:
            raise ScheduleServiceError(
                "定期実行名は1文字から80文字で指定してください",
                "SCHEDULE_NAME_INVALID",
            )
        return value

    def _prepare_schedule_storage(
        self,
        snapshot_config: AppConfig,
        registry: Mapping[str, Any],
        display_name: str,
        previous_metadata: Optional[Mapping[str, Any]],
    ) -> None:
        """新規だけを現行版へ採番し、既存の保存場所は不変に保つ。"""

        save_paths = snapshot_config.save_paths
        try:
            requested_layout = int(save_paths.layout_version)
        except (TypeError, ValueError) as exc:
            raise ScheduleServiceError(
                "定期実行の保存レイアウトが不正です",
                "PROFILE_INVALID",
            ) from exc
        if previous_metadata is not None:
            previous_key = str(previous_metadata.get("storage_key") or "")
            previous_folder = str(previous_metadata.get("storage_folder") or "")
            if bool(previous_key) != bool(previous_folder):
                raise ScheduleServiceError(
                    "定期実行の固定保存情報が一致しません",
                    "REGISTRATION_METADATA_INVALID",
                )
            if previous_key:
                previous_layout = 3
                previous_snapshot_id = self._snapshot_id(previous_metadata)
                if previous_snapshot_id:
                    previous_document = self.profile_store.read(
                        previous_snapshot_id
                    )
                    raw_save_paths = previous_document.get("save_paths")
                    if isinstance(raw_save_paths, Mapping):
                        try:
                            previous_layout = int(
                                raw_save_paths.get("layout_version", 3) or 3
                            )
                        except (TypeError, ValueError) as exc:
                            raise ScheduleServiceError(
                                "定期実行の保存レイアウトが不正です",
                                "PROFILE_INVALID",
                            ) from exc
                        snapshot_key = str(
                            raw_save_paths.get("schedule_storage_key") or ""
                        )
                        snapshot_folder = str(
                            raw_save_paths.get("schedule_storage_folder") or ""
                        )
                        if (snapshot_key, snapshot_folder) != (
                            previous_key,
                            previous_folder,
                        ):
                            raise ScheduleServiceError(
                                "登録台帳とスナップショットの固定保存情報が一致しません",
                                "REGISTRATION_METADATA_INVALID",
                            )
                # 通常編集は旧版を維持し、明示されたv4への更新だけ許可する。
                save_paths.layout_version = max(
                    previous_layout,
                    requested_layout,
                )
                save_paths.schedule_storage_key = previous_key
                save_paths.schedule_storage_folder = previous_folder
                return

            # layout_versionが存在しない旧snapshotは、名称変更・更新時にも
            # 従来のlocal直下を維持する。
            previous_snapshot_id = self._snapshot_id(previous_metadata)
            if previous_snapshot_id:
                previous_document = self.profile_store.read(previous_snapshot_id)
                raw_save_paths = previous_document.get("save_paths")
                if isinstance(raw_save_paths, Mapping):
                    if "layout_version" not in raw_save_paths:
                        save_paths.local = str(
                            raw_save_paths.get("local") or save_paths.local
                        )
                        save_paths.layout_version = 2
                        save_paths.schedule_storage_key = ""
                        save_paths.schedule_storage_folder = ""
                        return
                    try:
                        previous_layout = int(
                            raw_save_paths.get("layout_version", 2) or 2
                        )
                    except (TypeError, ValueError) as exc:
                        raise ScheduleServiceError(
                            "定期実行の保存レイアウトが不正です",
                            "PROFILE_INVALID",
                        ) from exc
                    if previous_layout < 3:
                        save_paths.local = str(
                            raw_save_paths.get("local") or save_paths.local
                        )
                        save_paths.layout_version = 2
                        save_paths.schedule_storage_key = ""
                        save_paths.schedule_storage_folder = ""
                        return
                    snapshot_key = str(
                        raw_save_paths.get("schedule_storage_key") or ""
                    )
                    snapshot_folder = str(
                        raw_save_paths.get("schedule_storage_folder") or ""
                    )
                    if bool(snapshot_key) != bool(snapshot_folder):
                        raise ScheduleServiceError(
                            "定期実行スナップショットの固定保存情報が一致しません",
                            "PROFILE_INVALID",
                        )
                    if snapshot_key:
                        save_paths.layout_version = max(
                            previous_layout,
                            requested_layout,
                        )
                        save_paths.schedule_storage_key = snapshot_key
                        save_paths.schedule_storage_folder = snapshot_folder
                        return

        storage_key = next_storage_key(registry)
        save_paths.layout_version = (
            requested_layout if requested_layout >= 3 else 4
        )
        save_paths.schedule_storage_key = storage_key
        save_paths.schedule_storage_folder = make_storage_folder(
            storage_key,
            display_name,
        )

    @staticmethod
    def _validate_preserved_storage_identity(
        snapshot_config: AppConfig,
        registry: Mapping[str, Any],
        schedule_id: str,
    ) -> None:
        """移行時の固定保存先を再採番せず、衝突だけを拒否する。"""

        key = str(snapshot_config.save_paths.schedule_storage_key or "")
        folder = str(snapshot_config.save_paths.schedule_storage_folder or "")
        if bool(key) != bool(folder):
            raise ScheduleServiceError(
                "旧定期実行の固定保存情報が一致しません",
                "EXTERNAL_STORAGE_INVALID",
            )
        if not key:
            return
        for other_id, entry in registry.get("registrations", {}).items():
            if other_id == schedule_id or not isinstance(entry, Mapping):
                continue
            if str(entry.get("storage_key") or "") == key:
                raise ScheduleServiceError(
                    "旧定期実行の固定保存キーを現在配置が既に使用しています",
                    "EXTERNAL_STORAGE_CONFLICT",
                )

    @staticmethod
    def _ensure_unique_name(
        registry: Mapping[str, Any],
        name: str,
        *,
        exclude_schedule_id: Optional[str] = None,
    ) -> None:
        wanted = "".join(name.split()).casefold()
        for schedule_id, entry in registry.get("registrations", {}).items():
            if schedule_id == exclude_schedule_id or not isinstance(entry, Mapping):
                continue
            existing = "".join(
                str(entry.get("name") or DEFAULT_SCHEDULE_NAME).split()
            ).casefold()
            if existing == wanted:
                raise ScheduleServiceError(
                    "同じ名前の定期実行が既に存在します",
                    "SCHEDULE_NAME_DUPLICATE",
                )

    @staticmethod
    def _ensure_unique_schedule_id(
        registry: Mapping[str, Any],
        schedule_id: str,
    ) -> None:
        wanted = schedule_id.casefold()
        for existing_id in registry.get("registrations", {}):
            if existing_id != schedule_id and str(existing_id).casefold() == wanted:
                raise ScheduleServiceError(
                    "大文字小文字だけが異なるスケジュールIDは使用できません",
                    "SCHEDULE_ALREADY_EXISTS",
                )

    def _safe_query_for(self, task_name: str) -> Optional[TaskQueryResult]:
        try:
            return self.task_client.query(task_name)
        except Exception:
            return None

    @staticmethod
    def _default_queue_status(schedule_id: str) -> Any:
        """既定のユーザー単位FIFOキューから1設定の待機状態を取得する。"""

        # scheduler層のimportだけでLocalAppDataへ触れないよう、状態照会時まで
        # run_queueの初期化を遅延する。テストや組込み側はproviderを注入できる。
        from ..app.run_queue import status_for

        return status_for(schedule_id)

    @staticmethod
    def _default_queue_tickets() -> Iterable[Any]:
        """保留snapshot保護のため、永続FIFO ticketを一括照会する。"""

        from ..app.run_queue import get_default_run_queue

        return get_default_run_queue().list_queue()

    def _queued_snapshot_ids(self) -> Optional[set[str]]:
        """待機・実行中ticketが参照するsnapshot IDを返す。

        照会に失敗した場合は ``None`` を返し、呼出側が回収を延期する。
        """

        try:
            tickets = self.queue_ticket_provider()
            result: set[str] = set()
            for ticket in tickets:
                state = self._queue_status_value(ticket, "state", "queued")
                if str(state).lower() not in {
                    "queued",
                    "running",
                    "retry_waiting",
                }:
                    continue
                snapshot_id = str(
                    self._queue_status_value(ticket, "snapshot_id", "") or ""
                )
                if snapshot_id:
                    result.add(snapshot_id)
            return result
        except Exception:
            return None

    @staticmethod
    def _queue_status_value(
        value: object,
        name: str,
        default: object = None,
    ) -> object:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    def _decorate_queue_status(
        self,
        status: ScheduleRegistrationStatus,
        schedule_id: str,
    ) -> ScheduleRegistrationStatus:
        """FIFO待機情報を付与し、照会失敗時は元の状態をそのまま返す。"""

        try:
            queue_status = self.queue_status_provider(schedule_id)
            if queue_status is None:
                return status
            waiting = bool(
                self._queue_status_value(queue_status, "waiting", False)
            )
            queue_running = bool(
                self._queue_status_value(queue_status, "running", False)
            )
            retry_waiting = bool(
                self._queue_status_value(
                    queue_status, "retry_waiting", False
                )
            )
            position_value = self._queue_status_value(
                queue_status, "position", None
            )
            total_value = self._queue_status_value(
                queue_status, "total_waiting", 0
            )
            position = (
                int(position_value) if position_value is not None else None
            )
            total = max(0, int(total_value or 0))
        except Exception:
            # キューの診断障害でWindowsタスクや修復状態を失わせない。
            return status

        status.queued = waiting
        status.queue_waiting = waiting
        status.retry_waiting = retry_waiting
        status.queue_position = position if waiting else None
        status.queue_total = total
        status.running = status.running or queue_running
        if retry_waiting and status.state != ScheduleState.REPAIR_REQUIRED:
            status.state = ScheduleState.RETRY_WAITING
        elif queue_running and status.state != ScheduleState.REPAIR_REQUIRED:
            # enqueue元のWindowsタスクprocessが終了済みでも、別設定の
            # dispatcher内でこのticketを処理中なら実行中が真実。
            status.state = ScheduleState.RUNNING
        elif waiting and status.state != ScheduleState.REPAIR_REQUIRED:
            # Task Scheduler上はFIFO待機中のprocessもrunningになる。
            # 永続ticketの待機状態の方が具体的なので、修復状態以外では優先する。
            status.state = ScheduleState.QUEUED
        return status

    def _restore_task(
        self,
        task_name: str,
        previous_task: Optional[TaskQueryResult],
        previous_metadata: Optional[Mapping[str, Any]],
        *,
        strict: bool = False,
    ) -> None:
        try:
            if previous_task is not None and previous_task.exists and previous_task.xml:
                self.task_client.create_or_update(task_name, previous_task.xml)
                return
            if previous_metadata is not None and bool(
                previous_metadata.get("enabled", True)
            ):
                schedule = self._schedule_from_metadata(previous_metadata)
                xml_text = build_task_xml(
                    schedule,
                    str(previous_metadata.get("command", "")),
                    [
                        str(value)
                        for value in previous_metadata.get("arguments", [])
                    ],
                    now=self._now(),
                    working_directory=(
                        str(previous_metadata.get("working_directory", "")) or None
                    ),
                )
                self.task_client.create_or_update(task_name, xml_text)
                return
            try:
                self.task_client.delete(task_name, missing_ok=True)
            except TypeError:
                self.task_client.delete(task_name)
        except Exception:
            if strict:
                raise

    # 既存コードが参照する内部名もdefaultへ向ける。
    def _safe_query(self) -> Optional[TaskQueryResult]:
        return self._safe_query_for(self.task_name)

    status = get_status

    def history(self, limit: int = 20) -> list[ScheduledRunRecord]:
        return self.ledger.recent(limit)

    get_history = history

    def next_run(
        self, config: ScheduleConfig, now: Optional[datetime] = None
    ) -> datetime:
        return calculate_next_run(config, now or self._now())

    get_next_run_time = next_run

    def _validate_app_config(self, config: AppConfig) -> None:
        valid, errors = self.validator.validate_config(config)
        if not valid:
            raise ScheduleServiceError(
                "設定が不正です: " + "、".join(errors),
                "CONFIG_INVALID",
            )

    def _resolve_action(
        self,
        profile_path: Path,
        schedule_id: str = DEFAULT_SCHEDULE_ID,
    ) -> tuple[Path, list[str], Optional[Path]]:
        frozen = bool(getattr(sys, "frozen", False))
        if self.executable is not None:
            command = self.executable
            looks_like_python = command.stem.lower() in {"python", "pythonw"}
            frozen = not looks_like_python
        elif frozen:
            command = Path(sys.executable).resolve(strict=False)
        else:
            command = (self.app_root / ".venv" / "Scripts" / "pythonw.exe").resolve(
                strict=False
            )

        if not command.is_file():
            raise ScheduleServiceError(
                f"定期実行に使用する実行ファイルが見つかりません: {command}",
                "EXECUTABLE_NOT_FOUND",
            )
        lowered = str(command).lower()
        if not frozen and any(token in lowered for token in ("conda", "miniconda", "anaconda")):
            raise ScheduleServiceError(
                "Conda環境は定期実行に使用できません。プロジェクトの.venvを作成してください",
                "CONDA_ENVIRONMENT_NOT_SUPPORTED",
            )
        if frozen:
            return (
                command,
                [
                    "--scheduled-run",
                    "--schedule-id",
                    validate_schedule_id(schedule_id),
                    "--config",
                    str(profile_path),
                ],
                command.parent,
            )
        self._validate_source_python(command)
        if not self.script_path.is_file():
            raise ScheduleServiceError(
                f"定期実行の起動スクリプトが見つかりません: {self.script_path}",
                "SCRIPT_NOT_FOUND",
            )
        return (
            command,
            [
                str(self.script_path),
                "--scheduled-run",
                "--schedule-id",
                validate_schedule_id(schedule_id),
                "--config",
                str(profile_path),
            ],
            self.app_root,
        )

    def _validate_source_python(self, pythonw_path: Path) -> None:
        """移動済み・Conda由来・非3.11の壊れたvenvを登録前に拒否する。"""
        python_path = pythonw_path.with_name("python.exe")
        if not python_path.is_file():
            raise ScheduleServiceError(
                f"仮想環境のPythonが見つかりません: {python_path}",
                "PYTHON_ENVIRONMENT_INVALID",
            )
        validation = (
            "import struct,sys;"
            "values=(sys.executable,sys.base_prefix,sys.prefix);"
            "ok=sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64 "
            "and all('conda' not in str(v).lower() for v in values);"
            "raise SystemExit(0 if ok else 1)"
        )
        try:
            result = self.python_runner(
                [str(python_path), "-c", validation],
                cwd=str(self.app_root),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScheduleServiceError(
                f"プロジェクトの.venvを検証できません: {exc}",
                "PYTHON_ENVIRONMENT_INVALID",
            ) from exc
        if int(getattr(result, "returncode", 1)) != 0:
            detail = str(
                getattr(result, "stderr", "")
                or getattr(result, "stdout", "")
                or ""
            ).replace("\r", " ").replace("\n", " ")[-500:]
            message = (
                "プロジェクトの.venvはPython 3.11 x64の非Conda環境として"
                "実行できません。scripts\\setup.ps1で再作成してください"
            )
            if detail:
                message += f": {detail}"
            raise ScheduleServiceError(
                message,
                "PYTHON_ENVIRONMENT_INVALID",
            )

    def _safe_query(self) -> Optional[TaskQueryResult]:
        try:
            return self.task_client.query(self.task_name)
        except Exception:
            return None

    def _restore_previous_task(
        self,
        previous_task: Optional[TaskQueryResult],
        previous_metadata: Optional[dict[str, Any]],
    ) -> None:
        try:
            if previous_task is not None and previous_task.exists and previous_task.xml:
                self.task_client.create_or_update(self.task_name, previous_task.xml)
            elif previous_metadata is not None:
                schedule = self._schedule_from_metadata(previous_metadata)
                old_xml = build_task_xml(
                    schedule,
                    str(previous_metadata.get("command", "")),
                    [str(value) for value in previous_metadata.get("arguments", [])],
                    now=self._now(),
                    working_directory=(
                        str(previous_metadata.get("working_directory", "")) or None
                    ),
                )
                self.task_client.create_or_update(self.task_name, old_xml)
            elif previous_metadata is None:
                try:
                    self.task_client.delete(self.task_name, missing_ok=True)
                except TypeError:
                    self.task_client.delete(self.task_name)
        except Exception:
            # 元例外を優先する。次回状態照会で要修復として検出される。
            return

    def _repair_status(
        self,
        task_name: str,
        reason_code: str,
        reason: str,
        metadata: Optional[Mapping[str, Any]],
        *,
        profile: Optional[ScheduledProfile] = None,
        definition_mismatch: bool = False,
    ) -> ScheduleRegistrationStatus:
        return ScheduleRegistrationStatus(
            state=ScheduleState.REPAIR_REQUIRED,
            registered=reason_code not in {"TASK_NOT_FOUND", "TASK_NOT_REGISTERED"},
            definition_mismatch=definition_mismatch,
            repair_reason=reason,
            reason_code=reason_code,
            task_name=task_name,
            profile_id=(profile.profile_id if profile else str(metadata.get("profile_id", "")))
            if metadata
            else None,
            profile_fingerprint=(
                profile.fingerprint
                if profile
                else str(metadata.get("profile_fingerprint", "")) if metadata else None
            ),
        )

    def _schedule_from_metadata(self, metadata: Mapping[str, Any]) -> ScheduleConfig:
        raw = metadata.get("schedule", {})
        if not isinstance(raw, Mapping):
            raise ScheduleServiceError(
                "登録済みスケジュールの形式が不正です",
                "REGISTRATION_METADATA_INVALID",
            )
        allowed = {item.name for item in fields(ScheduleConfig)}
        values = {key: value for key, value in raw.items() if key in allowed}
        try:
            return ScheduleConfig(**values)
        except (TypeError, ValueError) as exc:
            raise ScheduleServiceError(
                f"登録済みスケジュールの形式が不正です: {exc}",
                "REGISTRATION_METADATA_INVALID",
            ) from exc

    @staticmethod
    def _task_result_is_failure(result: Optional[int]) -> bool:
        # 0x41300=ready、0x41301=running、0x41303=未実行。これらは
        # プロセスの失敗終了コードではない。
        return result is not None and result not in {0, 0x41300, 0x41301, 0x41303}

    @staticmethod
    def _task_result_is_newer(
        task_last_run: Optional[datetime],
        latest: Optional[ScheduledRunRecord],
    ) -> bool:
        if latest is None or task_last_run is None:
            return True
        ledger_time = latest.finished_at or latest.started_at
        if ledger_time is None:
            return True
        try:
            return task_last_run > ledger_time
        except TypeError:
            # 古い履歴にtimezoneがない場合は壁時計として比較する。
            return task_last_run.replace(tzinfo=None) > ledger_time.replace(tzinfo=None)

    @staticmethod
    def _schedule_comparison_key(config: ScheduleConfig) -> tuple[Any, ...]:
        return (
            config.enabled,
            config.backend,
            config.timezone,
            config.interval,
            config.time,
            config.weekday if config.interval == "weekly" else None,
            config.day_of_month if config.interval == "monthly" else None,
            config.start_when_available,
            config.wake_to_run,
            config.retry_count,
            config.retry_interval_minutes,
            config.notification_policy,
        )

    def _read_registration(self) -> Optional[dict[str, Any]]:
        if not self.registration_path.exists():
            return None
        try:
            data = json.loads(self.registration_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleServiceError(
                "定期実行の登録情報が壊れています",
                "REGISTRATION_METADATA_INVALID",
            ) from exc
        if not isinstance(data, dict) or data.get("schema_version") != REGISTRATION_SCHEMA_VERSION:
            raise ScheduleServiceError(
                "未対応の定期実行登録情報です",
                "REGISTRATION_METADATA_INVALID",
            )
        return data

    def _write_registration(self, metadata: dict[str, Any]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                suffix=".tmp",
                prefix=".schedule-registration-",
                dir=self.config_dir,
                delete=False,
            ) as stream:
                json.dump(metadata, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.registration_path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ScheduleServiceError(
                "定期実行の登録情報を保存できません",
                "REGISTRATION_METADATA_WRITE_FAILED",
            ) from exc

    def _load_or_create_task_namespace_id(self) -> str:
        """配置単位のtask namespaceを既存台帳から安全に継承する。"""

        try:
            if self._task_namespace_id_path.exists():
                return self._validate_install_id(
                    self._task_namespace_id_path.read_text(encoding="utf-8").strip()
                )
            inherited = self._namespace_from_existing_registry()
            legacy_path = self.config_dir / "install-id"
            if inherited is None and legacy_path.is_file():
                inherited = self._validate_install_id(
                    legacy_path.read_text(encoding="utf-8").strip()
                )
                if self._coordination_id is None:
                    self._coordination_id = self._write_identifier_once(
                        self._coordination_id_path,
                        inherited,
                    )
            namespace_id = inherited or uuid.uuid4().hex[:12]
            return self._write_identifier_once(
                self._task_namespace_id_path,
                namespace_id,
            )
        except (OSError, ValueError, ScheduleServiceError) as exc:
            if isinstance(exc, ScheduleServiceError):
                raise
            raise ScheduleServiceError(
                "定期実行の配置識別子を読み書きできません",
                "TASK_NAMESPACE_ID_ERROR",
            ) from exc

    def _load_or_create_coordination_id(self) -> str:
        """従来のユーザー単位IDをFIFO coordination用として維持する。"""

        try:
            if self._coordination_id_path.exists():
                return self._validate_install_id(
                    self._coordination_id_path.read_text(encoding="utf-8").strip()
                )
            return self._write_identifier_once(
                self._coordination_id_path,
                uuid.uuid4().hex[:12],
            )
        except (OSError, ValueError, ScheduleServiceError) as exc:
            if isinstance(exc, ScheduleServiceError):
                raise
            raise ScheduleServiceError(
                "定期実行の調整識別子を読み書きできません",
                "COORDINATION_ID_ERROR",
            ) from exc

    def _namespace_from_existing_registry(self) -> Optional[str]:
        """既存entryのtask名が同じnamespaceなら、そのIDを引き継ぐ。"""

        if not self.registration_path.is_file():
            return None
        try:
            document = self.registration_store.read()
        except ScheduleServiceError:
            # 壊れた旧台帳の診断対象を見失わないよう、従来のユーザーIDを
            # その配置だけに固定してから修復画面へ渡す。
            return self.coordination_id
        namespaces: set[str] = set()
        for schedule_id, entry in document.get("registrations", {}).items():
            if not isinstance(entry, Mapping):
                continue
            task_name = str(entry.get("task_name") or "")
            namespace = self._namespace_from_task_name(task_name, str(schedule_id))
            if namespace:
                namespaces.add(namespace)
        if len(namespaces) > 1:
            raise ScheduleServiceError(
                "既存の定期実行台帳に複数のtask namespaceが混在しています",
                "TASK_NAMESPACE_CONFLICT",
            )
        return next(iter(namespaces), None)

    @staticmethod
    def _namespace_from_task_name(task_name: str, schedule_id: str) -> Optional[str]:
        prefix = r"\ippi-down\Download-"
        if not task_name.casefold().startswith(prefix.casefold()):
            return None
        suffix = task_name[len(prefix) :]
        if schedule_id != DEFAULT_SCHEDULE_ID:
            marker = f"-{schedule_id}"
            if not suffix.casefold().endswith(marker.casefold()):
                return None
            suffix = suffix[: -len(marker)]
        try:
            return _SingleScheduleServiceBase._validate_install_id(suffix)
        except ValueError:
            return None

    def _write_identifier_once(self, path: Path, identifier: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open(
                "x", encoding="utf-8", newline="\n"
            ) as stream:
                stream.write(identifier + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return identifier
        except FileExistsError:
            # 別プロセスが作成直後でflush前の短い窓だけ待ち、必ず先に
            # 作成されたIDを採用する。
            for _ in range(10):
                try:
                    value = path.read_text(
                        encoding="utf-8"
                    ).strip()
                    if value:
                        return self._validate_install_id(value)
                except OSError:
                    pass
                time.sleep(0.02)
            raise ScheduleServiceError(
                "定期実行の識別子を読み込めません",
                "INSTALL_ID_INVALID",
            )

    @staticmethod
    def _validate_install_id(value: Optional[str]) -> str:
        candidate = str(value or "")
        if not candidate or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in candidate
        ):
            raise ValueError(f"不正なinstall-idです: {candidate}")
        return candidate

    def _now(self) -> datetime:
        value = self.now_provider()
        timezone_info = japan_timezone()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone_info)
        return value.astimezone(timezone_info)


class ScheduleService(_SingleScheduleServiceBase):
    """複数の論理スケジュールを独立して管理するv2サービス。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._protected_snapshot_ids: set[str] = set()
        self.migration_journal_path = (
            self.config_dir / _MIGRATION_JOURNAL_FILENAME
        )
        self.migration_recovery_warning: Optional[str] = None
        self.migration_recovery_reason_code: Optional[str] = None
        self._recover_migration_journal()

    def register(self, config: AppConfig) -> ScheduleRegistrationStatus:
        """既存呼出しをdefaultスケジュールへ委譲する。"""

        return self.register_schedule(DEFAULT_SCHEDULE_ID, config)

    update = register
    register_or_update = register

    def register_schedule(
        self,
        schedule_id: str,
        config: AppConfig,
        *,
        name: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> ScheduleRegistrationStatus:
        """1件だけを新しい不変snapshotへ切り替え、タスクを更新する。"""

        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            if not config.schedule.enabled:
                raise ScheduleServiceError(
                    "定期実行を有効にしてから登録してください",
                    "SCHEDULE_DISABLED",
                )
            if not config.schedule.uses_windows_task_scheduler:
                raise ScheduleServiceError(
                    "旧プロセス内スケジュールは使用できません。Windowsタスクへ移行してください",
                    "LEGACY_SCHEDULE_MIGRATION_REQUIRED",
                )

            registry = self.registration_store.read_unlocked()
            self._require_revision(registry, expected_revision)
            self._ensure_unique_schedule_id(registry, identifier)
            previous_metadata = deepcopy(
                registry["registrations"].get(identifier)
            )
            task_name = str(
                (previous_metadata or {}).get("task_name")
                or self.task_name_for(identifier)
            )
            previous_task = self._safe_query_for(task_name)
            display_name = self._schedule_name(
                name,
                previous_metadata,
                identifier,
            )
            self._ensure_unique_name(
                registry,
                display_name,
                exclude_schedule_id=identifier,
            )
            snapshot_id = uuid.uuid4().hex
            snapshot_config = deepcopy(config)
            self._prepare_schedule_storage(
                snapshot_config,
                registry,
                display_name,
                previous_metadata,
            )
            self._validate_app_config(snapshot_config)
            snapshot_config.schedule.active_profile_id = snapshot_id
            profile = self.profile_store.create(
                snapshot_config,
                snapshot_id=snapshot_id,
                schedule_id=identifier,
                display_name=display_name,
                created_at=self._now(),
            )
            task_updated = False
            try:
                command, arguments, working_directory = self._resolve_action(
                    profile.path,
                    identifier,
                )
                xml_text = build_task_xml(
                    snapshot_config.schedule,
                    command,
                    arguments,
                    now=self._now(),
                    working_directory=working_directory,
                )
                self.task_client.create_or_update(task_name, xml_text)
                task_updated = True
                metadata = self._make_entry(
                    identifier,
                    display_name,
                    True,
                    task_name,
                    profile,
                    snapshot_config.schedule,
                    command,
                    arguments,
                    working_directory,
                    storage_key=snapshot_config.save_paths.schedule_storage_key,
                    storage_folder=snapshot_config.save_paths.schedule_storage_folder,
                    previous_metadata=previous_metadata,
                )
                self._put_registration(
                    identifier,
                    metadata,
                    expected_revision=int(registry.get("revision", 0) or 0),
                )
                if previous_task is not None and not previous_task.running:
                    self.cleanup_retained_snapshots(schedule_id=identifier)
            except Exception as exc:
                rollback_error: Optional[Exception] = None
                if task_updated:
                    try:
                        self._restore_task(
                            task_name,
                            previous_task,
                            previous_metadata,
                            strict=True,
                        )
                    except Exception as restore_exc:
                        rollback_error = restore_exc
                if rollback_error is None:
                    try:
                        self.profile_store.delete(profile)
                    except ScheduleServiceError:
                        pass
                if rollback_error is not None:
                    # 新taskが新snapshotを参照したままの可能性があるため、
                    # snapshotを残して要修復から復旧できるようにする。
                    raise ScheduleServiceError(
                        "以前のWindowsタスクを復元できません。定期実行を修復してください",
                        "REGISTRATION_ROLLBACK_FAILED",
                    ) from rollback_error
                if isinstance(exc, ScheduleServiceError):
                    raise
                raise ScheduleServiceError(
                    f"Windowsタスクを登録できません: {exc}",
                    "TASK_REGISTER_FAILED",
                ) from exc

            config.schedule.active_profile_id = profile.snapshot_id
            config.save_paths = deepcopy(snapshot_config.save_paths)
            current_entries = self.registration_store.read_unlocked()[
                "registrations"
            ]
            status = ScheduleRegistrationStatus(
                state=ScheduleState.REGISTERED,
                registered=True,
                enabled=True,
                next_run=calculate_next_run(config.schedule, self._now()),
                task_name=task_name,
                schedule_id=identifier,
                name=display_name,
                profile_id=profile.snapshot_id,
                snapshot_id=profile.snapshot_id,
                profile_fingerprint=profile.fingerprint,
                storage_key=snapshot_config.save_paths.schedule_storage_key,
                storage_folder=snapshot_config.save_paths.schedule_storage_folder,
            )
            return self._decorate_condition_status(
                status,
                identifier,
                current_entries.get(identifier),
                current_entries,
            )

    def create_schedule(
        self,
        config_or_name: AppConfig | str,
        config: Optional[AppConfig] = None,
        *,
        schedule_id: Optional[str] = None,
        name: Optional[str] = None,
        expected_revision: Optional[int] = None,
        preserve_storage_identity: bool = False,
    ) -> ScheduleRegistrationStatus:
        if isinstance(config_or_name, str):
            if config is None:
                raise TypeError("create_schedule(name, config)にはconfigが必要です")
            resolved_name = name or config_or_name
            resolved_config = config
        else:
            if config is not None:
                raise TypeError("configは重複して指定できません")
            resolved_name = name
            resolved_config = config_or_name
        identifier = validate_schedule_id(schedule_id or uuid.uuid4().hex[:12])
        with self._lock, self.registration_store.transaction():
            registry = self.registration_store.read_unlocked()
            self._require_revision(registry, expected_revision)
            if identifier in registry["registrations"]:
                raise ScheduleServiceError(
                    f"同じスケジュールIDが既に存在します: {identifier}",
                    "SCHEDULE_ALREADY_EXISTS",
                )
            if resolved_config.schedule.enabled:
                return self.register_schedule(
                    identifier,
                    resolved_config,
                    name=resolved_name,
                    expected_revision=int(registry.get("revision", 0) or 0),
                )
            return self._save_disabled_schedule(
                identifier,
                resolved_config,
                name=resolved_name,
                expected_revision=int(registry.get("revision", 0) or 0),
                preserve_storage_identity=preserve_storage_identity,
            )

    def update_schedule(
        self,
        schedule_id: str,
        config: AppConfig,
        *,
        name: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> ScheduleRegistrationStatus:
        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            registry = self.registration_store.read_unlocked()
            self._require_revision(registry, expected_revision)
            if identifier not in registry["registrations"]:
                raise ScheduleServiceError(
                    "更新対象の定期実行が見つかりません",
                    "SCHEDULE_NOT_FOUND",
                )
            revision = int(registry.get("revision", 0) or 0)
            if config.schedule.enabled:
                return self.register_schedule(
                    identifier,
                    config,
                    name=name,
                    expected_revision=revision,
                )
            return self._save_disabled_schedule(
                identifier,
                config,
                name=name,
                expected_revision=revision,
            )

    def duplicate_schedule(
        self,
        source_schedule_id: str,
        name: Optional[str] = None,
        *,
        schedule_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> ScheduleRegistrationStatus:
        source = self.get_schedule(source_schedule_id)
        if source is None:
            raise ScheduleServiceError(
                "複製元の定期実行が見つかりません",
                "SCHEDULE_NOT_FOUND",
            )
        config = self.get_registered_config(source.schedule_id)
        if config is None:
            raise ScheduleServiceError(
                "複製元の検索条件が見つかりません",
                "PROFILE_NOT_FOUND",
            )
        # 複製直後に2つのタスクが同時起動しないよう、必ず無効で作る。
        config.schedule.enabled = False
        config.schedule.active_profile_id = None
        config.save_paths.schedule_storage_key = ""
        config.save_paths.schedule_storage_folder = ""
        return self.create_schedule(
            config,
            schedule_id=schedule_id,
            name=name or f"{source.name} のコピー",
            expected_revision=expected_revision,
        )

    def list_schedules(self) -> list[ScheduleRegistration]:
        registry = self.get_registry()
        return sorted(
            registry.registrations.values(),
            key=lambda item: (item.name.casefold(), item.schedule_id),
        )

    def migrate_storage_layout_v4(self) -> dict[str, object]:
        """管理中のv3定期実行を、1件ずつ原子的にv4へ移行する。

        各更新は既存のsnapshot・Windowsタスクrollbackを利用する。失敗した
        登録は旧snapshotを維持し、呼出側が未移行として表示できるよう返す。
        """

        migrated: list[str] = []
        unchanged: list[str] = []
        failed: dict[str, str] = {}
        for registration in self.list_schedules():
            schedule_id = registration.schedule_id
            try:
                config = self.get_registered_config(schedule_id)
                if config is None:
                    raise ScheduleServiceError(
                        "定期実行スナップショットが見つかりません",
                        "PROFILE_NOT_FOUND",
                    )
                layout_version = int(config.save_paths.layout_version)
                if layout_version != 3:
                    unchanged.append(schedule_id)
                    continue
                config.save_paths.layout_version = 4
                revision = self.get_registry().revision
                self.update_schedule(
                    schedule_id,
                    config,
                    name=registration.name,
                    expected_revision=revision,
                )
                migrated.append(schedule_id)
            except Exception as exc:
                code = str(getattr(exc, "reason_code", "") or "")
                failed[schedule_id] = (
                    f"[{code}] {exc}" if code else str(exc)
                )
        return {
            "migrated": tuple(migrated),
            "unchanged": tuple(unchanged),
            "failed": failed,
        }

    def get_registry(self) -> ScheduleRegistry:
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            registrations = {
                schedule_id: self._registration_from_entry(entry)
                for schedule_id, entry in document["registrations"].items()
                if not self._entry_migrated_out(entry)
            }
            return ScheduleRegistry(
                revision=int(document.get("revision", 0) or 0),
                registrations=registrations,
            )

    def preview_installation_relocation(
        self,
        config: Optional[AppConfig] = None,
    ) -> InstallationRelocationPreview:
        """現在配置へ付け替える値を、外部状態を変更せず列挙する。"""

        current_root = self.app_root
        with self._lock, self.registration_store.transaction():
            try:
                document = self.registration_store.read_unlocked()
                old_root, blocked = self._recorded_installation_root(
                    document,
                    config,
                )
                if blocked:
                    return InstallationRelocationPreview(
                        required=True,
                        current_root=current_root,
                        reason_code="INSTALLATION_RELOCATION_BLOCKED",
                        message="配置変更を安全に確定できません",
                        blocked_reason=blocked,
                    )
                if old_root is None:
                    return InstallationRelocationPreview(
                        required=True,
                        current_root=current_root,
                        reason_code="INSTALLATION_RELOCATION_BLOCKED",
                        message="旧配置を特定できません",
                        blocked_reason="旧配置を特定できません",
                    )

                config_changes: tuple[tuple[str, str, str], ...] = ()
                if config is not None and not paths_equal(old_root, current_root):
                    draft = deepcopy(config)
                    config_changes = self._rebase_config_paths(
                        draft,
                        old_root,
                        current_root,
                    )

                schedule_changes: list[tuple[str, str, str, str]] = []
                affected: list[str] = []
                for schedule_id, raw_entry in document.get(
                    "registrations", {}
                ).items():
                    if not isinstance(raw_entry, Mapping) or self._entry_migrated_out(
                        raw_entry
                    ):
                        continue
                    entry = dict(raw_entry)
                    snapshot_id = self._snapshot_id(entry)
                    profile = self.profile_store.get(snapshot_id)
                    action_changes = self._current_action_changes(
                        schedule_id,
                        entry,
                        profile,
                    )
                    profile_changes: tuple[tuple[str, str, str], ...] = ()
                    if not paths_equal(old_root, current_root):
                        registered_config = self.get_registered_config(schedule_id)
                        if registered_config is None:
                            raise ScheduleServiceError(
                                "定期実行スナップショットが見つかりません",
                                "PROFILE_NOT_FOUND",
                            )
                        profile_changes = self._rebase_config_paths(
                            registered_config,
                            old_root,
                            current_root,
                        )
                    for field, old_value, new_value in (
                        *action_changes,
                        *profile_changes,
                    ):
                        schedule_changes.append(
                            (schedule_id, field, old_value, new_value)
                        )
                    if action_changes or profile_changes:
                        affected.append(schedule_id)
            except ScheduleServiceError as exc:
                return InstallationRelocationPreview(
                    required=True,
                    current_root=current_root,
                    reason_code=exc.reason_code,
                    message="配置変更を検証できません",
                    blocked_reason=str(exc),
                )

        required = (
            not paths_equal(old_root, current_root)
            or bool(config_changes)
            or bool(schedule_changes)
        )
        return InstallationRelocationPreview(
            required=required,
            old_root=old_root if required else None,
            current_root=current_root,
            affected_schedule_ids=tuple(dict.fromkeys(affected)),
            config_changes=config_changes,
            schedule_changes=tuple(schedule_changes),
            reason_code=(
                "INSTALLATION_PATH_CHANGED"
                if required
                else "INSTALLATION_CURRENT"
            ),
            message=(
                "配置フォルダーの変更を検出しました"
                if required
                else "現在の配置場所は確認済みです"
            ),
        )

    def confirm_current_installation(self) -> InstallationRelocationResult:
        """変更がない新規配置へ現在ルートを記録する。"""

        preview = self.preview_installation_relocation()
        if preview.required:
            return InstallationRelocationResult(
                success=False,
                preview=preview,
                reason_code=preview.reason_code,
                message=preview.blocked_reason or preview.message,
            )
        try:
            self.installation_location_store.write(
                self.task_namespace_id,
                self.app_root,
            )
        except ScheduleServiceError as exc:
            return InstallationRelocationResult(
                success=False,
                preview=preview,
                reason_code=exc.reason_code,
                message=str(exc),
            )
        return InstallationRelocationResult(
            success=True,
            preview=preview,
            message="現在の配置場所を確認しました",
        )

    @staticmethod
    def _atomic_restore_file(path: Path, payload: Optional[bytes]) -> None:
        """移行失敗時に設定ファイルだけを原子的に元へ戻す。"""

        path = path.resolve(strict=False)
        if payload is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".tmp",
                prefix=".installation-config-rollback-",
                dir=path.parent,
                delete=False,
            ) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _archive_relocation_snapshots(
        self,
        states: Iterable[ScheduleRegistrySnapshot],
    ) -> None:
        """移行前snapshotを通常の世代回収対象から外して保持する。"""

        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            revision = int(document.get("revision", 0) or 0)
            changed = False
            for state in states:
                old_id = self._snapshot_id(state.metadata)
                entry = document["registrations"].get(state.schedule_id)
                if not old_id or not isinstance(entry, dict):
                    continue
                current_id = self._snapshot_id(entry)
                if current_id == old_id:
                    continue
                retained = [
                    str(value)
                    for value in entry.get("retained_snapshot_ids", [])
                    if str(value) and str(value) != old_id
                ]
                archived = [
                    str(value)
                    for value in entry.get(
                        "relocation_archived_snapshot_ids", []
                    )
                    if str(value)
                ]
                if old_id not in archived:
                    archived.append(old_id)
                entry["retained_snapshot_ids"] = retained
                entry["relocation_archived_snapshot_ids"] = sorted(archived)
                changed = True
            if changed:
                self.registration_store.write_unlocked(
                    document,
                    expected_revision=revision,
                )

    def _archive_interrupted_relocation_snapshots(self, old_root: Path) -> None:
        """中断前に生成済みのentryから旧snapshotを回収対象外へ移す。"""

        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            revision = int(document.get("revision", 0) or 0)
            changed = False
            for entry in document.get("registrations", {}).values():
                if not isinstance(entry, dict):
                    continue
                retained = [
                    str(value)
                    for value in entry.get("retained_snapshot_ids", [])
                    if str(value)
                ]
                archived = [
                    str(value)
                    for value in entry.get(
                        "relocation_archived_snapshot_ids", []
                    )
                    if str(value)
                ]
                kept: list[str] = []
                for snapshot_id in retained:
                    try:
                        snapshot = self.profile_store.read(snapshot_id)
                        snapshot_config = ConfigManager(
                            str(self.profile_store.path_for(snapshot_id))
                        )._dict_to_config(snapshot)
                    except Exception:
                        kept.append(snapshot_id)
                        continue
                    path_belongs_to_old_root = any(
                        rebase_internal_path(value, old_root, self.app_root)
                        is not None
                        for value in (
                            snapshot_config.save_paths.local,
                            snapshot_config.logging.file,
                        )
                    )
                    if path_belongs_to_old_root:
                        if snapshot_id not in archived:
                            archived.append(snapshot_id)
                        changed = True
                    else:
                        kept.append(snapshot_id)
                if kept != retained:
                    entry["retained_snapshot_ids"] = kept
                if archived != list(
                    entry.get("relocation_archived_snapshot_ids", [])
                ):
                    entry["relocation_archived_snapshot_ids"] = sorted(archived)
            if changed:
                self.registration_store.write_unlocked(
                    document,
                    expected_revision=revision,
                )

    def _registration_state_is_current(
        self,
        state: ScheduleRegistrySnapshot,
    ) -> bool:
        """内側の更新処理が既にrollback済みなら二重復元を避ける。"""

        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            current = document["registrations"].get(state.schedule_id)
            if current != state.metadata:
                return False
        try:
            task_name = str(
                (state.metadata or {}).get("task_name")
                or self.task_name_for(state.schedule_id)
            )
            query = self.task_client.query(task_name)
        except Exception:
            return False
        previous = state.task
        if previous is None:
            return not query.exists
        return (
            bool(query.exists) == bool(getattr(previous, "exists", False))
            and bool(query.running) == bool(getattr(previous, "running", False))
            and query.xml == getattr(previous, "xml", None)
            and query.enabled == getattr(previous, "enabled", None)
        )

    def apply_installation_relocation(
        self,
        config: AppConfig,
        config_manager: Optional[ConfigManager] = None,
    ) -> InstallationRelocationResult:
        """確認済みの配置移行を設定・snapshot・タスクへ一括適用する。"""

        preview = self.preview_installation_relocation(config)
        if preview.blocked_reason:
            return InstallationRelocationResult(
                success=False,
                preview=preview,
                reason_code=preview.reason_code,
                message=preview.blocked_reason,
            )
        if not preview.required:
            confirmed = self.confirm_current_installation()
            return InstallationRelocationResult(
                success=confirmed.success,
                preview=preview,
                reason_code=confirmed.reason_code,
                message=confirmed.message,
                config=deepcopy(config),
            )
        if preview.old_root is None:
            return InstallationRelocationResult(
                success=False,
                preview=preview,
                reason_code="INSTALLATION_ROOT_UNKNOWN",
                message="旧配置を特定できないため付け替えできません",
            )
        if preview.config_changes and config_manager is None:
            return InstallationRelocationResult(
                success=False,
                preview=preview,
                reason_code="CONFIG_MANAGER_REQUIRED",
                message="一般設定を安全に保存する機能を利用できません",
            )
        if self.migration_journal_path.exists():
            return InstallationRelocationResult(
                success=False,
                preview=preview,
                reason_code="MIGRATION_RECOVERY_PENDING",
                message="別の定期実行移行の復旧が完了していません",
            )

        try:
            tickets = tuple(self.queue_ticket_provider())
        except Exception as exc:
            return InstallationRelocationResult(
                success=False,
                preview=preview,
                reason_code="INSTALLATION_QUEUE_CHECK_FAILED",
                message=f"実行待ち状態を確認できません: {exc}",
            )
        for ticket in tickets:
            state = str(
                self._queue_status_value(ticket, "state", "") or ""
            ).casefold()
            if state in {"queued", "running", "retry_waiting"}:
                return InstallationRelocationResult(
                    success=False,
                    preview=preview,
                    reason_code="INSTALLATION_RELOCATION_BUSY",
                    message="定期実行が実行中または順番待ちです",
                )

        with DOWNLOAD_RUN_GUARD.try_acquire() as globally_idle:
            if not globally_idle:
                return InstallationRelocationResult(
                    success=False,
                    preview=preview,
                    reason_code="INSTALLATION_RELOCATION_BUSY",
                    message="ダウンロード処理中のため配置を変更できません",
                )

            refreshed = self.preview_installation_relocation(config)
            if refreshed != preview:
                return InstallationRelocationResult(
                    success=False,
                    preview=refreshed,
                    reason_code="INSTALLATION_RELOCATION_CONFLICT",
                    message="確認後に配置または定期実行情報が変更されました",
                )

            registrations = {
                item.schedule_id: item for item in self.list_schedules()
            }
            for schedule_id in preview.affected_schedule_ids:
                registration = registrations.get(schedule_id)
                if registration is None:
                    continue
                query = self._safe_query_for(registration.task_name)
                if query is None:
                    return InstallationRelocationResult(
                        success=False,
                        preview=preview,
                        reason_code="TASK_QUERY_FAILED",
                        message="Windowsタスクの実行状態を確認できません",
                    )
                if query.running:
                    return InstallationRelocationResult(
                        success=False,
                        preview=preview,
                        reason_code="INSTALLATION_RELOCATION_BUSY",
                        message=f"定期実行中の設定があります: {registration.name}",
                    )

            relocated_config = deepcopy(config)
            self._rebase_config_paths(
                relocated_config,
                preview.old_root,
                self.app_root,
            )
            config_path = (
                Path(config_manager.config_path).resolve(strict=False)
                if config_manager is not None
                else None
            )
            original_config_payload = (
                config_path.read_bytes()
                if config_path is not None and config_path.exists()
                else None
            )
            current_location_payload = (
                self.installation_location_path.read_bytes()
                if self.installation_location_path.exists()
                else None
            )
            old_location_store: Optional[InstallationLocationStore] = None
            old_location_path: Optional[Path] = None
            old_location_payload: Optional[bytes] = None
            if (
                not paths_equal(preview.old_root, self.app_root)
                and preview.old_root.exists()
            ):
                try:
                    config_suffix = self.config_dir.relative_to(self.app_root)
                except ValueError:
                    config_suffix = None
                if config_suffix is not None:
                    old_location_path = (
                        preview.old_root
                        / config_suffix
                        / INSTALLATION_LOCATION_FILENAME
                    ).resolve(strict=False)
                    old_location_store = InstallationLocationStore(
                        old_location_path
                    )
                    if old_location_path.exists():
                        old_location_payload = old_location_path.read_bytes()
            states: list[ScheduleRegistrySnapshot] = []
            config_write_attempted = False
            old_location_write_attempted = False
            current_location_write_attempted = False
            relocation_journal_active = False
            relocation_journal_preexisting = False
            try:
                existing_journal = self.installation_relocation_journal_store.read()
                if existing_journal is not None and (
                    existing_journal.task_namespace_id != self.task_namespace_id
                    or not paths_equal(existing_journal.old_root, preview.old_root)
                    or not paths_equal(existing_journal.current_root, self.app_root)
                ):
                    raise ScheduleServiceError(
                        "別の配置移行の回復記録が残っています",
                        "INSTALLATION_RELOCATION_JOURNAL_CONFLICT",
                    )
                relocation_journal_preexisting = existing_journal is not None
                if existing_journal is None:
                    self.installation_relocation_journal_store.write(
                        self.task_namespace_id,
                        preview.old_root,
                        self.app_root,
                    )
                relocation_journal_active = True
                for schedule_id in preview.affected_schedule_ids:
                    registration = registrations.get(schedule_id)
                    if registration is None:
                        continue
                    state = self.capture_registration_state(schedule_id)
                    states.append(state)
                    registered_config = self.get_registered_config(schedule_id)
                    if registered_config is None:
                        raise ScheduleServiceError(
                            "定期実行スナップショットが見つかりません",
                            "PROFILE_NOT_FOUND",
                        )
                    path_changes = self._rebase_config_paths(
                        registered_config,
                        preview.old_root,
                        self.app_root,
                    )
                    revision = self.get_registry().revision
                    if path_changes:
                        self.update_schedule(
                            schedule_id,
                            registered_config,
                            name=registration.name,
                            expected_revision=revision,
                        )
                    elif registration.enabled:
                        self.repair_schedule(
                            schedule_id,
                            expected_revision=revision,
                        )
                    else:
                        self.disable_schedule(
                            schedule_id,
                            expected_revision=revision,
                        )

                if preview.config_changes:
                    assert config_manager is not None
                    config_write_attempted = True
                    if not config_manager.save_config(relocated_config):
                        raise ScheduleServiceError(
                            "一般設定を保存できません",
                            "CONFIG_SAVE_FAILED",
                        )
                self._archive_relocation_snapshots(states)
                self._archive_interrupted_relocation_snapshots(
                    preview.old_root
                )
                if old_location_store is not None:
                    old_location_write_attempted = True
                    old_location_store.write_retired(
                        self.task_namespace_id,
                        preview.old_root,
                        self.app_root,
                    )
                current_location_write_attempted = True
                self.installation_location_store.write(
                    self.task_namespace_id,
                    self.app_root,
                )
                self.installation_relocation_journal_store.delete()
                relocation_journal_active = False
            except Exception as exc:
                rollback_errors: list[str] = []
                for state in reversed(states):
                    try:
                        if self._registration_state_is_current(state):
                            self.release_registration_state(state)
                            continue
                        self.restore_registration_state(
                            state,
                            expected_revision=self.get_registry().revision,
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(str(rollback_exc))
                if config_write_attempted and config_path is not None:
                    try:
                        self._atomic_restore_file(
                            config_path,
                            original_config_payload,
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(str(rollback_exc))
                if old_location_write_attempted and old_location_path is not None:
                    try:
                        self._atomic_restore_file(
                            old_location_path,
                            old_location_payload,
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(str(rollback_exc))
                if current_location_write_attempted:
                    try:
                        self._atomic_restore_file(
                            self.installation_location_path,
                            current_location_payload,
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(str(rollback_exc))
                if (
                    relocation_journal_active
                    and not relocation_journal_preexisting
                    and not rollback_errors
                ):
                    try:
                        self.installation_relocation_journal_store.delete()
                        relocation_journal_active = False
                    except Exception as rollback_exc:
                        rollback_errors.append(str(rollback_exc))
                code = str(
                    getattr(exc, "reason_code", "")
                    or "INSTALLATION_RELOCATION_FAILED"
                )
                if rollback_errors:
                    code = "INSTALLATION_RELOCATION_ROLLBACK_FAILED"
                return InstallationRelocationResult(
                    success=False,
                    preview=preview,
                    migrated_schedule_ids=tuple(
                        state.schedule_id for state in states
                    ),
                    reason_code=code,
                    message=(
                        f"{exc}"
                        + (
                            " / 復元失敗: " + "、".join(rollback_errors)
                            if rollback_errors
                            else ""
                        )
                    ),
                )

            for state in states:
                try:
                    self.release_registration_state(state)
                except ScheduleServiceError:
                    # 移行本体は完了済み。旧snapshotの回収は行わず保持する。
                    pass
            config.save_paths = deepcopy(relocated_config.save_paths)
            config.logging = deepcopy(relocated_config.logging)
            return InstallationRelocationResult(
                success=True,
                preview=preview,
                migrated_schedule_ids=tuple(
                    state.schedule_id for state in states
                ),
                message="配置フォルダーを現在の場所へ付け替えました",
                config=relocated_config,
            )

    def get_schedule(self, schedule_id: str) -> Optional[ScheduleRegistration]:
        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            entry = document["registrations"].get(identifier)
            if entry is not None and self._entry_migrated_out(entry):
                return None
            return self._registration_from_entry(entry) if entry else None

    def unregister(self, config: Optional[AppConfig] = None) -> bool:
        return self.delete_schedule(DEFAULT_SCHEDULE_ID, config=config)

    delete = unregister
    remove = unregister

    def delete_schedule(
        self,
        schedule_id: str,
        *,
        config: Optional[AppConfig] = None,
        expected_revision: Optional[int] = None,
    ) -> bool:
        """タスク削除後、対象entryだけをregistryから除去する。"""

        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            self._require_revision(document, expected_revision)
            entry = deepcopy(document["registrations"].get(identifier))
            task_name = str(
                (entry or {}).get("task_name") or self.task_name_for(identifier)
            )
            previous_task = self._safe_query_for(task_name)
            try:
                try:
                    self.task_client.delete(task_name, missing_ok=True)
                except TypeError:
                    self.task_client.delete(task_name)
                if entry is not None:
                    document["registrations"].pop(identifier, None)
                    retained = document.setdefault("retained_snapshots", [])
                    for snapshot_id in sorted(self._snapshot_ids_for_entry(entry)):
                        retained.append(
                            {
                                "schedule_id": identifier,
                                "snapshot_id": snapshot_id,
                                "display_name": str(entry.get("name") or ""),
                                "task_name": task_name,
                                "retained_at": self._now().isoformat(),
                                "reason": (
                                    "task_running"
                                    if previous_task is not None and previous_task.running
                                    else "rollback_window"
                                ),
                            }
                        )
                    self.registration_store.write_unlocked(
                        document,
                        expected_revision=int(document.get("revision", 0) or 0),
                    )
            except Exception as exc:
                if previous_task is not None and previous_task.exists:
                    try:
                        self._restore_task(
                            task_name,
                            previous_task,
                            entry,
                            strict=True,
                        )
                    except Exception as restore_exc:
                        raise ScheduleServiceError(
                            "削除前のWindowsタスクを復元できません。定期実行を修復してください",
                            "REGISTRATION_ROLLBACK_FAILED",
                        ) from restore_exc
                if isinstance(exc, ScheduleServiceError):
                    raise
                raise ScheduleServiceError(
                    f"定期実行を削除できません: {exc}",
                    "TASK_DELETE_FAILED",
                ) from exc
            if (
                entry is not None
                and previous_task is not None
                and not previous_task.running
            ):
                self.cleanup_retained_snapshots(schedule_id=identifier)
            if config is not None:
                config.schedule.enabled = False
                config.schedule.active_profile_id = None
            return entry is not None or bool(previous_task and previous_task.exists)

    def set_enabled(
        self,
        schedule_id: str,
        enabled: bool,
        *,
        expected_revision: Optional[int] = None,
    ) -> ScheduleRegistrationStatus:
        if not isinstance(enabled, bool):
            raise ScheduleServiceError(
                "有効状態は真偽値で指定してください",
                "SCHEDULE_ENABLED_INVALID",
            )
        return (
            self.enable_schedule(schedule_id, expected_revision=expected_revision)
            if enabled
            else self.disable_schedule(schedule_id, expected_revision=expected_revision)
        )

    def enable_schedule(
        self,
        schedule_id: str,
        *,
        expected_revision: Optional[int] = None,
    ) -> ScheduleRegistrationStatus:
        return self._apply_existing_registration(
            schedule_id,
            enabled=True,
            expected_revision=expected_revision,
        )

    def disable_schedule(
        self,
        schedule_id: str,
        *,
        expected_revision: Optional[int] = None,
    ) -> ScheduleRegistrationStatus:
        return self._apply_existing_registration(
            schedule_id,
            enabled=False,
            expected_revision=expected_revision,
        )

    def repair_schedule(
        self,
        schedule_id: str,
        *,
        expected_revision: Optional[int] = None,
    ) -> ScheduleRegistrationStatus:
        """既存snapshotを維持し、実行パスとタスク定義だけを再生成する。"""

        registration = self.get_schedule(schedule_id)
        if registration is None:
            raise ScheduleServiceError(
                "修復対象の定期実行が見つかりません",
                "SCHEDULE_NOT_FOUND",
            )
        if not registration.enabled:
            raise ScheduleServiceError(
                "無効な定期実行は修復できません。有効化してください",
                "SCHEDULE_DISABLED",
            )
        return self._apply_existing_registration(
            schedule_id,
            enabled=True,
            expected_revision=expected_revision,
            force=True,
        )

    def run_now(self, schedule_id: str = DEFAULT_SCHEDULE_ID) -> bool:
        return self.run_schedule_now(schedule_id)

    run = run_now

    def run_schedule_now(self, schedule_id: str) -> bool:
        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            entry = document["registrations"].get(identifier)
            if entry is None:
                raise ScheduleServiceError(
                    "定期実行が登録されていません",
                    "TASK_NOT_REGISTERED",
                )
            if not bool(entry.get("enabled", True)):
                raise ScheduleServiceError(
                    "無効な定期実行は開始できません",
                    "SCHEDULE_DISABLED",
                )
            return bool(self.task_client.run(str(entry["task_name"])))

    def capture_registration_state(
        self,
        schedule_id: str = DEFAULT_SCHEDULE_ID,
    ) -> ScheduleRegistrySnapshot:
        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            metadata = deepcopy(document["registrations"].get(identifier))
            task_name = str(
                (metadata or {}).get("task_name") or self.task_name_for(identifier)
            )
            try:
                task = self.task_client.query(task_name)
            except Exception as exc:
                raise ScheduleServiceError(
                    f"更新前のWindowsタスクを退避できません: {exc}",
                    "REGISTRATION_BACKUP_FAILED",
                ) from exc
            registration = (
                self._registration_from_entry(metadata) if metadata else None
            )
            if metadata:
                self._protected_snapshot_ids.update(
                    self._snapshot_ids_for_entry(metadata)
                )
            return ScheduleRegistrySnapshot(
                revision=int(document.get("revision", 0) or 0),
                schedule_id=identifier,
                registration=registration,
                metadata=metadata,
                task=task,
            )

    def restore_registration_state(
        self,
        state: Mapping[str, Any] | ScheduleRegistrySnapshot,
        *,
        expected_revision: Optional[int] = None,
    ) -> None:
        """他のschedule entryを保持したまま、退避した1件だけを戻す。"""

        if isinstance(state, ScheduleRegistrySnapshot):
            identifier = validate_schedule_id(state.schedule_id)
            previous_metadata = deepcopy(state.metadata)
            previous_task = state.task
            captured_revision = state.revision
        elif isinstance(state, Mapping):
            identifier = validate_schedule_id(
                str(state.get("schedule_id") or DEFAULT_SCHEDULE_ID)
            )
            previous_metadata = deepcopy(
                state.get("metadata")
                if isinstance(state.get("metadata"), Mapping)
                else None
            )
            previous_task = state.get("task")
            captured_revision = int(state.get("revision", 0) or 0)
        else:
            raise ScheduleServiceError(
                "定期実行の退避情報が不正です",
                "REGISTRATION_BACKUP_INVALID",
            )

        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            current_revision = int(document.get("revision", 0) or 0)
            if expected_revision is not None:
                self._require_revision(document, expected_revision)
            elif current_revision not in {captured_revision, captured_revision + 1}:
                raise ScheduleServiceError(
                    "退避後に別の定期実行設定が更新されたため復元できません",
                    "REGISTRATION_CONFLICT",
                )
            current_metadata = deepcopy(
                document["registrations"].get(identifier)
            )
            task_name = str(
                (previous_metadata or current_metadata or {}).get("task_name")
                or self.task_name_for(identifier)
            )
            current_snapshot_id = self._snapshot_id(current_metadata)
            previous_snapshot_id = self._snapshot_id(previous_metadata)
            try:
                self._restore_task(
                    task_name,
                    previous_task,
                    previous_metadata,
                    strict=True,
                )
                if previous_metadata is None:
                    document["registrations"].pop(identifier, None)
                else:
                    document["registrations"][identifier] = previous_metadata
                if previous_metadata is None and not document["registrations"]:
                    self.registration_path.unlink(missing_ok=True)
                else:
                    self.registration_store.write_unlocked(
                        document,
                        expected_revision=current_revision,
                    )
            except Exception as exc:
                if isinstance(exc, ScheduleServiceError):
                    raise ScheduleServiceError(
                        f"以前の定期実行登録を復元できません: {exc}",
                        "REGISTRATION_ROLLBACK_FAILED",
                    ) from exc
                raise ScheduleServiceError(
                    f"以前の定期実行登録を復元できません: {exc}",
                    "REGISTRATION_ROLLBACK_FAILED",
                ) from exc
            if current_snapshot_id and current_snapshot_id != previous_snapshot_id:
                try:
                    self.profile_store.delete(current_snapshot_id)
                except ScheduleServiceError:
                    pass
            self._protected_snapshot_ids.difference_update(
                self._snapshot_ids_for_entry(previous_metadata)
            )

    def release_registration_state(
        self,
        state: Mapping[str, Any] | ScheduleRegistrySnapshot,
    ) -> None:
        """設定保存成功後にrollback保護を解き、不要snapshotを回収する。"""

        metadata: Optional[Mapping[str, Any]]
        if isinstance(state, ScheduleRegistrySnapshot):
            metadata = state.metadata
        elif isinstance(state, Mapping):
            value = state.get("metadata")
            metadata = value if isinstance(value, Mapping) else None
        else:
            raise ScheduleServiceError(
                "定期実行の退避情報が不正です",
                "REGISTRATION_BACKUP_INVALID",
            )
        self._protected_snapshot_ids.difference_update(
            self._snapshot_ids_for_entry(metadata)
        )
        self.cleanup_retained_snapshots()

    def get_registered_config(
        self,
        schedule_id: str = DEFAULT_SCHEDULE_ID,
    ) -> Optional[AppConfig]:
        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            entry = document["registrations"].get(identifier)
            if entry is None:
                return None
            snapshot_id = self._snapshot_id(entry)
            snapshot = self.profile_store.read(snapshot_id)
            try:
                config = ConfigManager(
                    str(self.profile_store.path_for(snapshot_id))
                )._dict_to_config(snapshot)
                schedule = self._schedule_from_metadata(entry)
            except (TypeError, ValueError) as exc:
                raise ScheduleServiceError(
                    f"登録済み検索条件の形式が不正です: {exc}",
                    "PROFILE_INVALID",
                ) from exc
            schedule.enabled = bool(entry.get("enabled", True))
            schedule.active_profile_id = snapshot_id
            config.schedule = schedule
            return config

    def get_status(
        self,
        schedule_id_or_config: str | AppConfig | None = None,
        config: Optional[AppConfig] = None,
        *,
        current_config: Optional[AppConfig] = None,
    ) -> ScheduleRegistrationStatus:
        if isinstance(schedule_id_or_config, AppConfig):
            if config is not None:
                raise TypeError("AppConfigを重複して指定できません")
            identifier = DEFAULT_SCHEDULE_ID
            resolved_config = schedule_id_or_config
        elif schedule_id_or_config is None:
            identifier = DEFAULT_SCHEDULE_ID
            resolved_config = config
        else:
            identifier = validate_schedule_id(schedule_id_or_config)
            resolved_config = config
        return self.get_schedule_status(
            identifier,
            config=resolved_config,
            current_config=current_config,
        )

    status = get_status

    def get_schedule_status(
        self,
        schedule_id: str,
        config: Optional[AppConfig] = None,
        *,
        current_config: Optional[AppConfig] = None,
    ) -> ScheduleRegistrationStatus:
        identifier = validate_schedule_id(schedule_id)
        effective_config = current_config or config
        try:
            with self._lock, self.registration_store.transaction():
                document = self.registration_store.read_unlocked()
                entry = deepcopy(document["registrations"].get(identifier))
                if entry is not None and self._entry_migrated_out(entry):
                    entry = None
        except ScheduleServiceError as exc:
            return self._decorate_queue_status(
                self._repair_status_for(
                    identifier,
                    self.task_name_for(identifier),
                    exc.reason_code,
                    str(exc),
                    None,
                ),
                identifier,
            )
        task_name = str(
            (entry or {}).get("task_name") or self.task_name_for(identifier)
        )
        try:
            query = self.task_client.query(task_name)
        except ScheduleServiceError as exc:
            return self._decorate_queue_status(
                self._repair_status_for(
                    identifier,
                    task_name,
                    exc.reason_code,
                    str(exc),
                    entry,
                ),
                identifier,
            )
        except Exception as exc:
            return self._decorate_queue_status(
                self._repair_status_for(
                    identifier,
                    task_name,
                    "TASK_QUERY_FAILED",
                    f"Windowsタスクを照会できません: {exc}",
                    entry,
                ),
                identifier,
            )
        status = self._status_from_entry(
            identifier,
            entry,
            query,
            effective_config,
        )
        self._decorate_condition_status(
            status,
            identifier,
            entry,
            document.get("registrations", {}),
        )
        self._decorate_queue_status(status, identifier)
        if not query.running and self._has_retained_snapshots(document):
            try:
                self.cleanup_retained_snapshots()
            except (OSError, ScheduleServiceError):
                # 状態表示は回収失敗より優先する。保留情報は次回照会へ残る。
                pass
        return status

    def get_statuses(
        self,
        current_configs: Optional[Mapping[str, AppConfig]] = None,
    ) -> dict[str, ScheduleRegistrationStatus]:
        """registryを1回読み、一括照会境界から全状態を返す。"""

        try:
            with self._lock, self.registration_store.transaction():
                document = self.registration_store.read_unlocked()
                entries = {
                    schedule_id: deepcopy(entry)
                    for schedule_id, entry in document["registrations"].items()
                    if not self._entry_migrated_out(entry)
                }
        except ScheduleServiceError:
            raise
        task_names = {
            schedule_id: str(
                entry.get("task_name") or self.task_name_for(schedule_id)
            )
            for schedule_id, entry in entries.items()
        }
        orphan_task_names = self._discover_orphan_task_names(
            entries,
            task_names,
        )
        coordination_task_names = self._discover_coordination_task_names(
            entries,
            task_names,
        )
        query_task_names = tuple(
            dict.fromkeys(
                [
                    *task_names.values(),
                    *orphan_task_names.values(),
                    *(value[1] for value in coordination_task_names.values()),
                ]
            )
        )
        queries: dict[str, TaskQueryResult | Exception] = {}
        query_many = getattr(self.task_client, "query_many", None)
        if callable(query_many):
            try:
                batch = query_many(query_task_names)
                queries.update(batch)
            except Exception:
                # 1件の照会失敗で他スケジュールの状態を失わない。
                queries.clear()
        for task_name in query_task_names:
            if task_name in queries:
                continue
            try:
                queries[task_name] = self.task_client.query(task_name)
            except Exception as exc:
                queries[task_name] = exc

        latest_records = self.ledger.latest_many(entries.keys())
        statuses: dict[str, ScheduleRegistrationStatus] = {}
        for schedule_id, entry in entries.items():
            task_name = task_names[schedule_id]
            query = queries[task_name]
            if isinstance(query, Exception):
                code = (
                    query.reason_code
                    if isinstance(query, ScheduleServiceError)
                    else "TASK_QUERY_FAILED"
                )
                status = self._repair_status_for(
                    schedule_id,
                    task_name,
                    code,
                    str(query),
                    entry,
                )
                statuses[schedule_id] = self._decorate_condition_status(
                    status,
                    schedule_id,
                    entry,
                    entries,
                )
                continue
            current = (
                current_configs.get(schedule_id)
                if current_configs is not None
                else None
            )
            status = self._status_from_entry(
                schedule_id,
                entry,
                query,
                current,
                latest_records=latest_records,
            )
            statuses[schedule_id] = self._decorate_condition_status(
                status,
                schedule_id,
                entry,
                entries,
            )
        for schedule_id, task_name in orphan_task_names.items():
            query = queries.get(task_name)
            if isinstance(query, Exception):
                code = (
                    query.reason_code
                    if isinstance(query, ScheduleServiceError)
                    else "TASK_QUERY_FAILED"
                )
                statuses[schedule_id] = ScheduleRegistrationStatus(
                    state=ScheduleState.EXTERNAL,
                    registered=True,
                    enabled=False,
                    repair_reason=(
                        "登録台帳にないWindowsタスクの詳細を照会できません: "
                        f"{query}"
                    ),
                    reason_code=code,
                    task_name=task_name,
                    schedule_id=schedule_id,
                    source_schedule_id=schedule_id,
                    external_id=schedule_id,
                    name=self._orphan_schedule_name(schedule_id),
                    origin=ScheduleOrigin.EXTERNAL_TASK,
                    capabilities=ScheduleCapabilities(),
                )
                continue
            if query is None or not query.exists:
                # 一覧取得後に削除されたタスクは、次回更新で自然に消える。
                continue
            statuses[schedule_id] = self._external_task_status(
                schedule_id,
                task_name,
                query,
                reason_code="EXTERNAL_TASK_NOT_IMPORTABLE",
                reason=(
                    "Windowsタスクは存在しますが、対応する登録台帳がありません。"
                    "旧設定フォルダーを指定できない純粋な孤児タスクは"
                    "自動で取り込めません"
                ),
            )
        for external_id, (source_schedule_id, task_name) in coordination_task_names.items():
            query = queries.get(task_name)
            if isinstance(query, Exception):
                statuses[external_id] = ScheduleRegistrationStatus(
                    state=ScheduleState.EXTERNAL,
                    registered=True,
                    repair_reason=str(query),
                    reason_code="TASK_QUERY_FAILED",
                    task_name=task_name,
                    schedule_id=external_id,
                    source_schedule_id=source_schedule_id,
                    external_id=external_id,
                    name=self._orphan_schedule_name(source_schedule_id),
                    origin=ScheduleOrigin.EXTERNAL_TASK,
                    capabilities=ScheduleCapabilities(),
                )
                continue
            if query is None or not query.exists:
                continue
            statuses[external_id] = self._external_task_status(
                source_schedule_id,
                task_name,
                query,
                external_id=external_id,
                reason_code="EXTERNAL_TASK_NOT_IMPORTABLE",
                reason=(
                    "別配置から登録されたWindowsタスクです。"
                    "取り込むには元のconfigフォルダーを指定してください"
                ),
            )
        for schedule_id, status in statuses.items():
            self._decorate_queue_status(status, schedule_id)
        if self._has_retained_snapshots(document):
            try:
                self.cleanup_retained_snapshots()
            except (OSError, ScheduleServiceError):
                pass
        return statuses

    def _discover_orphan_task_names(
        self,
        entries: Mapping[str, Mapping[str, Any]],
        registered_task_names: Mapping[str, str],
    ) -> dict[str, str]:
        """stable install-id配下の台帳外タスクを読み取り専用で見つける。"""

        list_names = getattr(self.task_client, "list_task_names", None)
        if not callable(list_names):
            # 旧fake/clientとの後方互換。通常のSchtasksClientは対応する。
            return {}
        base_name = self.task_name_for(DEFAULT_SCHEDULE_ID)
        try:
            discovered = tuple(list_names(base_name) or ())
        except (OSError, ScheduleServiceError, TypeError, ValueError):
            # 通常の登録状態照会を、補助的な孤児検出の失敗で失わない。
            return {}
        known_names = {
            str(task_name).casefold()
            for task_name in registered_task_names.values()
        }
        known_ids = {str(schedule_id).casefold() for schedule_id in entries}
        result: dict[str, str] = {}
        base_folded = base_name.casefold()
        separator = base_name + "-"
        separator_folded = separator.casefold()
        for task_name_value in discovered:
            task_name = str(task_name_value)
            folded = task_name.casefold()
            if folded in known_names:
                continue
            if folded == base_folded:
                schedule_id = DEFAULT_SCHEDULE_ID
            elif folded.startswith(separator_folded):
                schedule_id = task_name[len(separator) :]
                try:
                    schedule_id = validate_schedule_id(schedule_id)
                except ScheduleServiceError:
                    continue
            else:
                continue
            if schedule_id.casefold() in known_ids:
                continue
            result.setdefault(schedule_id, task_name)
        return result

    def _discover_coordination_task_names(
        self,
        entries: Mapping[str, Mapping[str, Any]],
        registered_task_names: Mapping[str, str],
    ) -> dict[str, tuple[str, str]]:
        """旧ユーザー共通namespaceのtaskを別配置候補として列挙する。"""

        if self.coordination_id == self.task_namespace_id:
            return {}
        list_names = getattr(self.task_client, "list_task_names", None)
        if not callable(list_names):
            return {}
        base_name = rf"\ippi-down\Download-{self.coordination_id}"
        try:
            discovered = tuple(list_names(base_name) or ())
        except (OSError, ScheduleServiceError, TypeError, ValueError):
            return {}
        known_names = {
            str(task_name).casefold() for task_name in registered_task_names.values()
        }
        known_ids = {str(schedule_id).casefold() for schedule_id in entries}
        result: dict[str, tuple[str, str]] = {}
        separator = base_name + "-"
        for task_name_value in discovered:
            task_name = str(task_name_value)
            if task_name.casefold() in known_names:
                continue
            if task_name.casefold() == base_name.casefold():
                source_schedule_id = DEFAULT_SCHEDULE_ID
            elif task_name.casefold().startswith(separator.casefold()):
                source_schedule_id = task_name[len(separator) :]
                try:
                    source_schedule_id = validate_schedule_id(source_schedule_id)
                except ScheduleServiceError:
                    continue
            else:
                continue
            if source_schedule_id.casefold() in known_ids:
                # 同じ論理IDを現在配置が既に管理している場合は、誤操作を
                # 防ぐため外部行としても公開しない。
                continue
            external_id = self._external_id(task_name)
            result[external_id] = (source_schedule_id, task_name)
        return result

    @staticmethod
    def _external_id(task_name: str) -> str:
        digest = hashlib.sha256(task_name.casefold().encode("utf-8")).hexdigest()
        return f"external-{digest[:12]}"

    @staticmethod
    def _orphan_schedule_name(schedule_id: str) -> str:
        if schedule_id == DEFAULT_SCHEDULE_ID:
            return "台帳が見つからない既存の定期実行"
        return f"台帳が見つからない定期実行 ({schedule_id})"

    @staticmethod
    def _entry_migrated_out(entry: Mapping[str, Any]) -> bool:
        return (
            str(entry.get("migration_status") or "").upper() == "MIGRATED_OUT"
            or str(entry.get("lifecycle_state") or "").upper()
            == "MIGRATED_OUT"
        )

    def preview_external_imports(
        self,
        source_config_dir: str | Path,
    ) -> tuple[ExternalScheduleImportCandidate, ...]:
        """選択された旧 ``config`` フォルダーを変更せず移行候補を返す。

        Windowsタスクだけの孤児から検索条件を推測しない。候補にするのは、
        v1/v2台帳と改ざん検証に成功したsealed snapshotの組だけである。
        """

        source_dir = self._resolve_external_config_dir(source_config_dir)
        document = self._read_external_registry_document(source_dir)
        current = self.registration_store.read()
        inspections = self._inspect_external_document(
            source_dir,
            document,
            current.get("registrations", {}),
        )
        return tuple(item.candidate for item in inspections)

    def list_external_schedule_candidates(
        self,
        source_config_dir: Optional[str | Path] = None,
    ) -> tuple[ExternalScheduleImportCandidate, ...]:
        """旧config候補、または台帳のない純粋な外部タスクを列挙する。"""

        if source_config_dir is not None:
            return self.preview_external_imports(source_config_dir)
        candidates: list[ExternalScheduleImportCandidate] = []
        for status in self.get_statuses().values():
            if status.origin is not ScheduleOrigin.EXTERNAL:
                continue
            candidates.append(
                ExternalScheduleImportCandidate(
                    external_id=status.external_id or status.schedule_id,
                    source_schedule_id=(
                        status.source_schedule_id or status.schedule_id
                    ),
                    display_name=status.name,
                    task_name=status.task_name,
                    importable=False,
                    reason_code=(
                        status.reason_code or "EXTERNAL_TASK_NOT_IMPORTABLE"
                    ),
                    reason=(
                        status.repair_reason
                        or "対応する旧台帳と検索条件がないため取り込めません"
                    ),
                    running=status.running,
                    origin=ScheduleOrigin.EXTERNAL,
                )
            )
        return tuple(candidates)

    def inspect_external_schedule(
        self,
        external_id: str,
        source_config_dir: Optional[str | Path] = None,
    ) -> ExternalScheduleImportCandidate:
        """外部IDを再解決し、古い画面応答をそのまま信用せず返す。"""

        candidates = self.list_external_schedule_candidates(source_config_dir)
        for candidate in candidates:
            if candidate.external_id == str(external_id):
                return candidate
        raise ScheduleServiceError(
            "指定された外部定期実行が見つかりません",
            "EXTERNAL_IMPORT_NOT_FOUND",
        )

    def plan_external_import(
        self,
        external_id: str,
        source_config_dir: str | Path,
        *,
        target_name: Optional[str] = None,
    ) -> ScheduleImportPlan:
        """GUI確認画面へ、変更を伴わない移行計画を返す。"""

        candidate = self.inspect_external_schedule(
            external_id,
            source_config_dir,
        )
        if not candidate.importable:
            raise ScheduleServiceError(candidate.reason, candidate.reason_code)
        if candidate.requires_target_name and not str(target_name or "").strip():
            raise ScheduleServiceError(
                "同じ名前の設定があるため、取り込み先の名前を指定してください",
                "EXTERNAL_TARGET_NAME_REQUIRED",
            )
        name = str(target_name or candidate.display_name).strip()
        current = self.registration_store.read()
        try:
            name = self._schedule_name(
                name,
                None,
                candidate.source_schedule_id,
            )
            self._ensure_unique_name(current, name)
        except ScheduleServiceError as exc:
            raise ScheduleServiceError(
                str(exc),
                "EXTERNAL_TARGET_NAME_CONFLICT"
                if exc.reason_code == "SCHEDULE_NAME_DUPLICATE"
                else "EXTERNAL_TARGET_NAME_INVALID",
            ) from exc
        return ScheduleImportPlan(
            candidate=candidate,
            target_schedule_id=candidate.source_schedule_id,
            target_name=name,
            target_enabled=candidate.enabled,
            effective_save_path=candidate.effective_save_path,
        )

    def import_external_schedule(
        self,
        external_id: str,
        source_config_dir: str | Path,
        *,
        expected_revision: Optional[int] = None,
        target_name: Optional[str] = None,
    ) -> ScheduleMigrationResult:
        """検証済み旧設定を現在配置へ無効状態で取り込む。

        旧Windowsタスクは、旧台帳を ``MIGRATED_OUT`` にできた後でだけ
        削除する。途中失敗時は現在台帳、旧台帳、旧タスクを復元する。
        """

        source_dir = self._resolve_external_config_dir(source_config_dir)
        source_path = source_dir / "schedule-registration.json"
        source_store = ScheduleRegistrationStore(source_path)
        with source_store.transaction():
            source_document = self._read_external_registry_document(source_dir)
            current_document = self.registration_store.read()
            self._require_revision(current_document, expected_revision)
            inspections = self._inspect_external_document(
                source_dir,
                source_document,
                current_document.get("registrations", {}),
            )
            inspection = next(
                (
                    item
                    for item in inspections
                    if item.candidate.external_id == str(external_id)
                ),
                None,
            )
            if inspection is None:
                raise ScheduleServiceError(
                    "指定された移行候補が見つかりません",
                    "EXTERNAL_IMPORT_NOT_FOUND",
                )
            candidate = inspection.candidate
            if not candidate.importable or inspection.config is None:
                raise ScheduleServiceError(
                    candidate.reason or "この旧設定は取り込めません",
                    candidate.reason_code or "EXTERNAL_IMPORT_NOT_ALLOWED",
                )
            if candidate.source_revision != int(
                source_document.get("revision", 0) or 0
            ):
                raise ScheduleServiceError(
                    "旧定期実行の登録情報が確認後に更新されました",
                    "EXTERNAL_SOURCE_CONFLICT",
                )

            schedule_id = candidate.source_schedule_id
            if candidate.requires_target_name and not str(target_name or "").strip():
                raise ScheduleServiceError(
                    "同じ名前の設定があるため、取り込み先の名前を指定してください",
                    "EXTERNAL_TARGET_NAME_REQUIRED",
                )
            imported_name = str(target_name or candidate.display_name).strip()
            try:
                imported_name = self._schedule_name(
                    imported_name,
                    None,
                    schedule_id,
                )
                self._ensure_unique_name(current_document, imported_name)
            except ScheduleServiceError as exc:
                raise ScheduleServiceError(
                    str(exc),
                    "EXTERNAL_TARGET_NAME_CONFLICT"
                    if exc.reason_code == "SCHEDULE_NAME_DUPLICATE"
                    else "EXTERNAL_TARGET_NAME_INVALID",
                ) from exc
            config = deepcopy(inspection.config)
            source_was_enabled = bool(
                (inspection.entry or {}).get("enabled", True)
            )
            config.schedule.enabled = False
            config.schedule.active_profile_id = None
            config.save_paths.local = str(
                self._resolve_external_save_root(
                    source_dir,
                    config.save_paths.local,
                )
            )

            old_task = self._query_external_task(candidate.task_name)
            if old_task.exists and old_task.running:
                raise ScheduleServiceError(
                    "旧配置の定期実行が実行中のため取り込めません",
                    "EXTERNAL_TASK_RUNNING",
                )
            if old_task.exists and not old_task.xml:
                raise ScheduleServiceError(
                    "旧Windowsタスクを安全に退避できないため取り込めません",
                    "EXTERNAL_TASK_BACKUP_UNAVAILABLE",
                )

            if self.migration_journal_path.exists():
                raise ScheduleServiceError(
                    "前回の定期実行移行を復旧してから再実行してください",
                    "MIGRATION_RECOVERY_PENDING",
                )
            journal = {
                "schema_version": _MIGRATION_JOURNAL_SCHEMA_VERSION,
                "source_registry_path": str(source_path),
                "schedule_id": schedule_id,
                "external_id": candidate.external_id,
                "old_task_name": candidate.task_name,
                "phase": "PREPARED",
                "old_task_enabled": bool(
                    old_task.exists and old_task.enabled is not False
                ),
                "target_revision": int(
                    current_document.get("revision", 0) or 0
                ),
                "source_revision": int(
                    source_document.get("revision", 0) or 0
                ),
            }
            self._write_migration_journal(journal)

            imported = False
            source_marked = False
            try:
                status = self.create_schedule(
                    config,
                    schedule_id=schedule_id,
                    name=imported_name,
                    expected_revision=int(
                        current_document.get("revision", 0) or 0
                    ),
                    preserve_storage_identity=True,
                )
                imported = True
                journal = self._advance_migration_journal(
                    journal,
                    "TARGET_STAGED",
                    target_revision=self.get_registry().revision,
                )
                if old_task.exists and old_task.enabled is not False:
                    self._set_external_task_enabled(candidate.task_name, False)
                journal = self._advance_migration_journal(
                    journal,
                    "OLD_DISABLED",
                )
                if source_was_enabled:
                    status = self.enable_schedule(schedule_id)
                journal = self._advance_migration_journal(
                    journal,
                    "TARGET_APPLIED",
                    target_revision=self.get_registry().revision,
                )
                migrated_document = deepcopy(source_document)
                source_entry = migrated_document["registrations"][schedule_id]
                source_entry.update(
                    {
                        "enabled": False,
                        "migration_status": "MIGRATED_OUT",
                        "lifecycle_state": "MIGRATED_OUT",
                        "migrated_at": self._now().isoformat(),
                        "migrated_to_namespace": self.task_namespace_id,
                        "migrated_to_schedule_id": schedule_id,
                    }
                )
                written = source_store.write_unlocked(
                    migrated_document,
                    expected_revision=int(
                        source_document.get("revision", 0) or 0
                    ),
                )
                source_marked = True
                journal = self._advance_migration_journal(
                    journal,
                    "SOURCE_MIGRATED",
                    source_revision=int(written.get("revision", 0) or 0),
                )
                warnings: list[str] = []
                warning_codes: list[str] = []
                history_imported = 0
                try:
                    history_imported = self.ledger.merge_from(
                        source_dir.parent / "logs" / "schedule-runs.jsonl",
                        schedule_id=schedule_id,
                    )
                except (OSError, TimeoutError, ValueError) as history_exc:
                    warning_codes.append("EXTERNAL_HISTORY_IMPORT_FAILED")
                    warnings.append(
                        "旧配置の実行履歴を取り込めませんでした: "
                        f"{history_exc}"
                    )
                if old_task.exists:
                    try:
                        self._delete_external_task_exact(candidate.task_name)
                    except ScheduleServiceError as cleanup_exc:
                        cleanup_document = deepcopy(written)
                        cleanup_entry = cleanup_document["registrations"][
                            schedule_id
                        ]
                        cleanup_entry.update(
                            {
                                "external_task_cleanup": "PENDING",
                                "external_task_cleanup_reason": (
                                    cleanup_exc.reason_code
                                ),
                            }
                        )
                        cleanup_written = cleanup_document
                        try:
                            cleanup_written = source_store.write_unlocked(
                                cleanup_document,
                                expected_revision=int(
                                    written.get("revision", 0) or 0
                                ),
                            )
                        except ScheduleServiceError:
                            # ownership移行と二重実行防止は完了しているため、
                            # 診断追記だけの失敗で有効なtargetを戻さない。
                            pass
                        status.reason_code = "EXTERNAL_TASK_CLEANUP_PENDING"
                        status.repair_reason = (
                            "旧Windowsタスクは無効化済みですが削除できません。"
                            "外部タスクの解除を後で再実行してください: "
                            f"{cleanup_exc}"
                        )
                        warning_codes.append(
                            "EXTERNAL_TASK_CLEANUP_PENDING"
                        )
                        warnings.append(status.repair_reason)
                        journal = self._advance_migration_journal(
                            journal,
                            "CLEANUP_PENDING",
                            source_revision=int(
                                cleanup_written.get("revision", 0)
                                or 0
                            ),
                        )
                reason_code = (
                    warning_codes[0]
                    if warning_codes
                    else "EXTERNAL_IMPORT_SUCCESS"
                )
                result = ScheduleMigrationResult(
                    candidate=candidate,
                    target_schedule_id=schedule_id,
                    target_name=imported_name,
                    status=status,
                    warnings=tuple(warnings),
                    reason_code=reason_code,
                    history_imported=history_imported,
                )
                if not warnings or (
                    "EXTERNAL_TASK_CLEANUP_PENDING" not in warning_codes
                ):
                    if not self._delete_migration_journal():
                        result = ScheduleMigrationResult(
                            candidate=result.candidate,
                            target_schedule_id=result.target_schedule_id,
                            target_name=result.target_name,
                            status=result.status,
                            warnings=(
                                *result.warnings,
                                "移行ジャーナルを削除できませんでした。"
                                "次回起動時に完了状態を再確認します",
                            ),
                            reason_code="MIGRATION_JOURNAL_CLEANUP_FAILED",
                            history_imported=result.history_imported,
                        )
                return result
            except Exception as exc:
                rollback_errors: list[Exception] = []
                if source_marked:
                    try:
                        source_store.write_unlocked(
                            source_document,
                            expected_revision=int(written.get("revision", 0) or 0),
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(rollback_exc)
                target_removed = not imported
                if imported:
                    try:
                        self.delete_schedule(schedule_id)
                        target_removed = True
                    except Exception as rollback_exc:
                        rollback_errors.append(rollback_exc)
                if old_task.exists and target_removed:
                    try:
                        self.task_client.create_or_update(
                            candidate.task_name,
                            str(old_task.xml),
                        )
                    except Exception as rollback_exc:
                        rollback_errors.append(rollback_exc)
                if rollback_errors:
                    try:
                        self._advance_migration_journal(
                            journal,
                            "ROLLBACK_FAILED",
                        )
                    except ScheduleServiceError:
                        pass
                    raise ScheduleServiceError(
                        "旧定期実行の取り込み失敗後に完全復元できませんでした",
                        "EXTERNAL_IMPORT_ROLLBACK_FAILED",
                    ) from rollback_errors[0]
                self._delete_migration_journal()
                if isinstance(exc, ScheduleServiceError):
                    raise
                raise ScheduleServiceError(
                    f"旧定期実行を取り込めません: {exc}",
                    "EXTERNAL_IMPORT_FAILED",
                ) from exc

    def import_external_schedules(
        self,
        external_ids: Iterable[str],
        source_config_dir: str | Path,
        *,
        expected_revision: Optional[int] = None,
        target_names: Optional[Mapping[str, str]] = None,
    ) -> dict[str, ScheduleMigrationResult]:
        """候補を1件ずつ独立トランザクションで取り込む。"""

        results: dict[str, ScheduleMigrationResult] = {}
        revision = expected_revision
        for external_id in external_ids:
            identifier = str(external_id)
            results[identifier] = self.import_external_schedule(
                identifier,
                source_config_dir,
                expected_revision=revision,
                target_name=(target_names or {}).get(identifier),
            )
            revision = self.get_registry().revision
        return results

    def remove_external_task(
        self,
        external_id: str,
        source_config_dir: Optional[str | Path] = None,
    ) -> bool:
        """選択済みの外部Windowsタスクだけを解除し台帳には触れない。"""

        candidate = self.inspect_external_schedule(
            external_id,
            source_config_dir,
        )
        if not candidate.task_name:
            raise ScheduleServiceError(
                "解除するWindowsタスクが見つかりません",
                "EXTERNAL_TASK_NOT_FOUND",
            )
        query = self._query_external_task(candidate.task_name)
        if not query.exists:
            raise ScheduleServiceError(
                "解除するWindowsタスクが見つかりません",
                "EXTERNAL_TASK_NOT_FOUND",
            )
        if query.running:
            raise ScheduleServiceError(
                "外部Windowsタスクが実行中のため解除できません",
                "EXTERNAL_TASK_RUNNING",
            )
        self._delete_external_task_exact(candidate.task_name)
        return True

    detach_external_task = remove_external_task

    def _write_migration_journal(self, document: Mapping[str, Any]) -> None:
        payload = self._validate_migration_journal(document)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                suffix=".tmp",
                prefix=".schedule-migration-journal-",
                dir=self.config_dir,
                delete=False,
            ) as stream:
                json.dump(
                    payload,
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.migration_journal_path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ScheduleServiceError(
                "定期実行移行ジャーナルを保存できません",
                "MIGRATION_JOURNAL_WRITE_FAILED",
            ) from exc

    def _advance_migration_journal(
        self,
        document: Mapping[str, Any],
        phase: str,
        *,
        target_revision: Optional[int] = None,
        source_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        payload = dict(document)
        payload["phase"] = phase
        if target_revision is not None:
            payload["target_revision"] = int(target_revision)
        if source_revision is not None:
            payload["source_revision"] = int(source_revision)
        self._write_migration_journal(payload)
        return payload

    def _delete_migration_journal(self) -> bool:
        try:
            self.migration_journal_path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def _read_migration_journal(self) -> dict[str, Any]:
        try:
            raw = json.loads(
                self.migration_journal_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleServiceError(
                "定期実行移行ジャーナルが壊れています",
                "MIGRATION_JOURNAL_INVALID",
            ) from exc
        return self._validate_migration_journal(raw)

    @staticmethod
    def _validate_migration_journal(
        document: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(document, Mapping):
            raise ScheduleServiceError(
                "定期実行移行ジャーナルの形式が不正です",
                "MIGRATION_JOURNAL_INVALID",
            )
        required = {
            "schema_version",
            "source_registry_path",
            "schedule_id",
            "external_id",
            "old_task_name",
            "phase",
            "old_task_enabled",
            "target_revision",
            "source_revision",
        }
        if set(document) != required:
            raise ScheduleServiceError(
                "定期実行移行ジャーナルに未知または不足した項目があります",
                "MIGRATION_JOURNAL_INVALID",
            )
        try:
            schedule_id = validate_schedule_id(str(document["schedule_id"]))
            target_revision = int(document["target_revision"])
            source_revision = int(document["source_revision"])
        except (ScheduleServiceError, TypeError, ValueError) as exc:
            raise ScheduleServiceError(
                "定期実行移行ジャーナルの識別情報が不正です",
                "MIGRATION_JOURNAL_INVALID",
            ) from exc
        external_id = str(document["external_id"])
        phase = str(document["phase"])
        old_task_name = str(document["old_task_name"])
        if (
            document["schema_version"] != _MIGRATION_JOURNAL_SCHEMA_VERSION
            or not re.fullmatch(r"legacy-[0-9a-f]{16}", external_id)
            or phase not in _MIGRATION_PHASES
            or not isinstance(document["old_task_enabled"], bool)
            or target_revision < 0
            or source_revision < 0
            or not old_task_name
        ):
            raise ScheduleServiceError(
                "定期実行移行ジャーナルの値が不正です",
                "MIGRATION_JOURNAL_INVALID",
            )
        # pathの実在確認は復旧時に行う。ここではUNC/deviceだけを拒否する。
        source_path = str(document["source_registry_path"])
        try:
            resolved_source = resolve_verified_local_path(source_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ScheduleServiceError(
                "定期実行移行ジャーナルの旧台帳パスが不正です",
                "MIGRATION_JOURNAL_INVALID",
            ) from exc
        if resolved_source.name != "schedule-registration.json":
            raise ScheduleServiceError(
                "定期実行移行ジャーナルの旧台帳名が不正です",
                "MIGRATION_JOURNAL_INVALID",
            )
        return {
            "schema_version": _MIGRATION_JOURNAL_SCHEMA_VERSION,
            "source_registry_path": str(resolved_source),
            "schedule_id": schedule_id,
            "external_id": external_id,
            "old_task_name": old_task_name,
            "phase": phase,
            "old_task_enabled": document["old_task_enabled"],
            "target_revision": target_revision,
            "source_revision": source_revision,
        }

    def _recover_migration_journal(self) -> None:
        """残存journalを実状態と照合し、commit完了かrollbackを行う。"""

        if not self.migration_journal_path.is_file():
            return
        try:
            journal = self._read_migration_journal()
        except ScheduleServiceError as exc:
            self._set_migration_recovery_warning(exc.reason_code, str(exc))
            return
        schedule_id = str(journal["schedule_id"])
        if self._migration_recovery_busy(schedule_id):
            self._set_migration_recovery_warning(
                "MIGRATION_RECOVERY_DEFERRED",
                "定期実行または待機中処理があるため、前回の移行復旧を延期しました",
            )
            return
        source_path = Path(str(journal["source_registry_path"]))
        source_dir = source_path.parent
        source_store = ScheduleRegistrationStore(source_path)
        try:
            with source_store.transaction():
                source_document = self._read_external_registry_document(
                    source_dir
                )
                source_entry = source_document["registrations"].get(
                    schedule_id
                )
                if not isinstance(source_entry, Mapping):
                    raise ScheduleServiceError(
                        "旧台帳に復旧対象の設定がありません",
                        "MIGRATION_RECOVERY_CONFLICT",
                    )
                expected_external_id = self._external_import_id(
                    source_dir,
                    schedule_id,
                    self._snapshot_id(source_entry),
                )
                if expected_external_id != journal["external_id"]:
                    raise ScheduleServiceError(
                        "旧台帳の設定世代が移行開始時と一致しません",
                        "MIGRATION_RECOVERY_CONFLICT",
                    )
                self._validate_external_task_name(
                    source_dir,
                    schedule_id,
                    str(journal["old_task_name"]),
                )
                current_document = self.registration_store.read()
                target_entry = current_document["registrations"].get(
                    schedule_id
                )
                if isinstance(target_entry, Mapping) and str(
                    target_entry.get("owner_instance_id") or ""
                ) != self.task_namespace_id:
                    raise ScheduleServiceError(
                        "現在台帳の同じIDは別の配置が所有しています",
                        "MIGRATION_RECOVERY_CONFLICT",
                    )

                source_migrated = self._entry_migrated_out(source_entry)
                if source_migrated and isinstance(target_entry, Mapping):
                    if self._recover_committed_migration(
                        journal,
                        target_entry,
                    ):
                        if source_entry.get("external_task_cleanup"):
                            completed_document = deepcopy(source_document)
                            completed_entry = completed_document[
                                "registrations"
                            ][schedule_id]
                            completed_entry[
                                "external_task_cleanup"
                            ] = "COMPLETED"
                            completed_entry.pop(
                                "external_task_cleanup_reason",
                                None,
                            )
                            source_store.write_unlocked(
                                completed_document,
                                expected_revision=int(
                                    source_document.get("revision", 0) or 0
                                ),
                            )
                        self._delete_migration_journal()
                        self._clear_migration_recovery_warning()
                    return
                self._rollback_interrupted_migration(
                    journal,
                    source_store,
                    source_document,
                    source_entry,
                    target_entry,
                )
                self._delete_migration_journal()
                self._clear_migration_recovery_warning()
        except ScheduleServiceError as exc:
            self._set_migration_recovery_warning(exc.reason_code, str(exc))
        except Exception as exc:
            self._set_migration_recovery_warning(
                "MIGRATION_RECOVERY_FAILED",
                f"前回の定期実行移行を復旧できません: {exc}",
            )

    def _recover_committed_migration(
        self,
        journal: Mapping[str, Any],
        target_entry: Mapping[str, Any],
    ) -> bool:
        schedule_id = str(journal["schedule_id"])
        target_task_name = str(
            target_entry.get("task_name") or self.task_name_for(schedule_id)
        )
        target_query = self._query_external_task(target_task_name)
        target_enabled = bool(target_entry.get("enabled", True))
        if target_enabled and not target_query.exists:
            self.repair_schedule(schedule_id)
            target_query = self._query_external_task(target_task_name)
        if target_query.running:
            self._set_migration_recovery_warning(
                "MIGRATION_RECOVERY_DEFERRED",
                "移行先タスクが実行中のため旧タスクの後処理を延期しました",
            )
            return False
        if target_enabled != bool(target_query.exists):
            raise ScheduleServiceError(
                "移行先の登録状態を安全に再構成できません",
                "MIGRATION_RECOVERY_CONFLICT",
            )
        old_task_name = str(journal["old_task_name"])
        old_query = self._query_external_task(old_task_name)
        if old_query.running:
            self._set_migration_recovery_warning(
                "MIGRATION_RECOVERY_DEFERRED",
                "旧Windowsタスクが実行中のため後処理を延期しました",
            )
            return False
        if old_query.exists:
            if old_query.enabled is not False:
                self._set_external_task_enabled(old_task_name, False)
            try:
                self._delete_external_task_exact(old_task_name)
            except ScheduleServiceError as exc:
                self._advance_migration_journal(
                    journal,
                    "CLEANUP_PENDING",
                )
                self._set_migration_recovery_warning(
                    "EXTERNAL_TASK_CLEANUP_PENDING",
                    f"旧Windowsタスクの削除を再試行できません: {exc}",
                )
                return False
        return True

    def _rollback_interrupted_migration(
        self,
        journal: Mapping[str, Any],
        source_store: ScheduleRegistrationStore,
        source_document: Mapping[str, Any],
        source_entry: Mapping[str, Any],
        target_entry: Optional[Mapping[str, Any]],
    ) -> None:
        schedule_id = str(journal["schedule_id"])
        old_task_name = str(journal["old_task_name"])
        old_query = self._query_external_task(old_task_name)
        if not old_query.exists and bool(journal["old_task_enabled"]):
            raise ScheduleServiceError(
                "旧Windowsタスクが失われているため安全にロールバックできません",
                "MIGRATION_ROLLBACK_INCOMPLETE",
            )
        if target_entry is not None:
            self.delete_schedule(schedule_id)
        if old_query.exists:
            self._set_external_task_enabled(
                old_task_name,
                bool(journal["old_task_enabled"]),
            )
        if self._entry_migrated_out(source_entry):
            restored_document = deepcopy(dict(source_document))
            restored = restored_document["registrations"][schedule_id]
            schedule_values = restored.get("schedule", {})
            restored["enabled"] = bool(
                schedule_values.get(
                    "enabled",
                    journal["old_task_enabled"],
                )
            )
            for key in (
                "migration_status",
                "migrated_at",
                "migrated_to_namespace",
                "migrated_to_schedule_id",
                "external_task_cleanup",
                "external_task_cleanup_reason",
            ):
                restored.pop(key, None)
            restored["lifecycle_state"] = (
                "ACTIVE" if restored["enabled"] else "DISABLED"
            )
            source_store.write_unlocked(
                restored_document,
                expected_revision=int(
                    source_document.get("revision", 0) or 0
                ),
            )

    def _migration_recovery_busy(self, schedule_id: str) -> bool:
        try:
            queue_status = self.queue_status_provider(schedule_id)
            if queue_status is not None and (
                bool(self._queue_status_value(queue_status, "waiting", False))
                or bool(self._queue_status_value(queue_status, "running", False))
            ):
                return True
        except Exception:
            return True
        schedule_guard = make_schedule_run_guard(schedule_id)
        with schedule_guard.try_acquire() as schedule_idle:
            if not schedule_idle:
                return True
            with DOWNLOAD_RUN_GUARD.try_acquire() as globally_idle:
                return not globally_idle

    def _set_migration_recovery_warning(self, code: str, message: str) -> None:
        self.migration_recovery_reason_code = code
        self.migration_recovery_warning = message

    def _clear_migration_recovery_warning(self) -> None:
        self.migration_recovery_reason_code = None
        self.migration_recovery_warning = None

    def _resolve_external_config_dir(self, value: str | Path) -> Path:
        try:
            source_dir = resolve_verified_local_path(value)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ScheduleServiceError(
                f"旧configフォルダーを安全に参照できません: {exc}",
                "EXTERNAL_SOURCE_INVALID",
            ) from exc
        if not source_dir.is_dir():
            raise ScheduleServiceError(
                "指定された旧configフォルダーが見つかりません",
                "EXTERNAL_SOURCE_NOT_FOUND",
            )
        if source_dir == self.config_dir:
            raise ScheduleServiceError(
                "現在使用中のconfigフォルダーは取り込み元にできません",
                "EXTERNAL_SOURCE_IS_CURRENT",
            )
        return source_dir

    @staticmethod
    def _resolve_external_save_root(source_dir: Path, value: str | Path) -> Path:
        """旧配置基準の相対保存先を、同じ実効場所の絶対パスへ固定する。"""

        raw = Path(str(value)).expanduser()
        candidate = raw if raw.is_absolute() else source_dir.parent / raw
        try:
            return resolve_verified_local_path(candidate)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ScheduleServiceError(
                f"旧定期実行の保存先を安全に引き継げません: {exc}",
                "EXTERNAL_SAVE_PATH_INVALID",
            ) from exc

    @staticmethod
    def _read_external_registry_document(source_dir: Path) -> dict[str, Any]:
        path = source_dir / "schedule-registration.json"
        if not path.is_file():
            raise ScheduleServiceError(
                "旧configフォルダーに定期実行台帳がありません",
                "EXTERNAL_REGISTRY_NOT_FOUND",
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleServiceError(
                "旧定期実行台帳が壊れています",
                "EXTERNAL_REGISTRY_INVALID",
            ) from exc
        if not isinstance(raw, Mapping):
            raise ScheduleServiceError(
                "旧定期実行台帳の形式が不正です",
                "EXTERNAL_REGISTRY_INVALID",
            )
        store = ScheduleRegistrationStore(path)
        try:
            version = raw.get("schema_version")
            if version == REGISTRATION_SCHEMA_VERSION:
                return store._validate_v2(raw)
            if version == 1:
                return store._validate_v2(store._migrate_v1(raw))
        except ScheduleServiceError as exc:
            raise ScheduleServiceError(
                f"旧定期実行台帳を検証できません: {exc}",
                "EXTERNAL_REGISTRY_INVALID",
            ) from exc
        raise ScheduleServiceError(
            "未対応の旧定期実行台帳です",
            "EXTERNAL_REGISTRY_INVALID",
        )

    def _inspect_external_document(
        self,
        source_dir: Path,
        document: Mapping[str, Any],
        current_entries: Mapping[str, Any],
    ) -> tuple[_ExternalImportInspection, ...]:
        profile_store = ScheduleProfileStore(
            source_dir / "schedule-profiles",
            recover_stale=False,
        )
        source_revision = int(document.get("revision", 0) or 0)
        inspections: list[_ExternalImportInspection] = []
        for schedule_id, raw_entry in document.get("registrations", {}).items():
            entry = deepcopy(dict(raw_entry))
            snapshot_id = self._snapshot_id(entry)
            task_name = str(entry.get("task_name") or "")
            display_name = str(entry.get("name") or DEFAULT_SCHEDULE_NAME)
            source_enabled = bool(entry.get("enabled", True))
            storage_key = str(entry.get("storage_key") or "")
            storage_folder = str(entry.get("storage_folder") or "")
            entry_schedule: Optional[ScheduleConfig]
            try:
                entry_schedule = self._schedule_from_metadata(entry)
            except ScheduleServiceError:
                entry_schedule = None
            effective_save_path: Optional[Path] = None
            wanted_name = "".join(display_name.split()).casefold()
            requires_target_name = any(
                "".join(
                    str(value.get("name") or DEFAULT_SCHEDULE_NAME).split()
                ).casefold()
                == wanted_name
                for value in current_entries.values()
                if isinstance(value, Mapping)
                and not self._entry_migrated_out(value)
            )
            external_id = self._external_import_id(
                source_dir,
                schedule_id,
                snapshot_id,
            )
            source_profile_path: Optional[Path] = None
            if snapshot_id:
                try:
                    source_profile_path = profile_store.path_for(snapshot_id)
                except ScheduleServiceError:
                    pass

            def rejected(code: str, reason: str) -> _ExternalImportInspection:
                return _ExternalImportInspection(
                    ExternalScheduleImportCandidate(
                        external_id=external_id,
                        source_schedule_id=schedule_id,
                        display_name=display_name,
                        task_name=task_name,
                        snapshot_id=snapshot_id,
                        importable=False,
                        reason_code=code,
                        reason=reason,
                        source_config_path=(
                            source_dir / "schedule-registration.json"
                        ),
                        source_config_dir=source_dir,
                        source_profile_path=source_profile_path,
                        source_revision=source_revision,
                        enabled=source_enabled,
                        schedule=entry_schedule,
                        effective_save_path=effective_save_path,
                        storage_key=storage_key,
                        storage_folder=storage_folder,
                        requires_target_name=requires_target_name,
                    ),
                    entry=entry,
                )

            if self._entry_migrated_out(entry):
                inspections.append(
                    rejected(
                        "EXTERNAL_ALREADY_MIGRATED",
                        "この旧定期実行は既に別配置へ取り込み済みです",
                    )
                )
                continue
            if schedule_id in current_entries:
                inspections.append(
                    rejected(
                        "EXTERNAL_SCHEDULE_CONFLICT",
                        "同じスケジュールIDを現在配置が既に使用しています",
                    )
                )
                continue
            if not snapshot_id:
                inspections.append(
                    rejected(
                        "EXTERNAL_PROFILE_NOT_FOUND",
                        "旧台帳に検索条件スナップショットIDがありません",
                    )
                )
                continue
            try:
                profile = profile_store.get(snapshot_id)
                if profile.schedule_id != schedule_id:
                    raise ScheduleServiceError(
                        "検索条件が別の定期実行に属しています",
                        "EXTERNAL_PROFILE_SCHEDULE_MISMATCH",
                    )
                if self._snapshot_fingerprint(entry) != profile.fingerprint:
                    raise ScheduleServiceError(
                        "旧台帳と検索条件のfingerprintが一致しません",
                        "EXTERNAL_PROFILE_FINGERPRINT_MISMATCH",
                    )
                snapshot = profile_store.read(snapshot_id)
                config = ConfigManager(
                    str(profile_store.path_for(snapshot_id))
                )._dict_to_config(snapshot)
                self._validate_app_config(config)
                effective_save_path = self._resolve_external_save_root(
                    source_dir,
                    config.save_paths.local,
                )
                self._validate_preserved_storage_identity(
                    config,
                    {"registrations": current_entries},
                    schedule_id,
                )
                recorded_schedule = self._schedule_from_metadata(entry)
                if self._schedule_comparison_key(recorded_schedule) != (
                    self._schedule_comparison_key(config.schedule)
                ):
                    raise ScheduleServiceError(
                        "旧台帳と検索条件の実行日時設定が一致しません",
                        "EXTERNAL_SCHEDULE_MISMATCH",
                    )
                self._validate_external_task_name(
                    source_dir,
                    schedule_id,
                    task_name,
                )
                task = self._query_external_task(task_name)
                if task.running:
                    raise ScheduleServiceError(
                        "旧配置の定期実行が実行中です",
                        "EXTERNAL_TASK_RUNNING",
                    )
                if task.exists and not task.xml:
                    raise ScheduleServiceError(
                        "旧Windowsタスクを安全に退避できません",
                        "EXTERNAL_TASK_BACKUP_UNAVAILABLE",
                    )
                if task.exists:
                    self._validate_external_task_definition(
                        task.xml or "",
                        entry,
                        recorded_schedule,
                        profile.path,
                        schedule_id,
                    )
            except ScheduleServiceError as exc:
                inspections.append(rejected(exc.reason_code, str(exc)))
                continue
            except (OSError, TypeError, ValueError) as exc:
                inspections.append(
                    rejected(
                        "EXTERNAL_CONFIG_INVALID",
                        f"旧定期実行の検索条件を検証できません: {exc}",
                    )
                )
                continue

            task_note = (
                "旧Windowsタスクと検索条件を検証しました"
                if task.exists
                else "旧Windowsタスクはありませんが検索条件を検証しました"
            )
            reason_code = "EXTERNAL_IMPORT_READY"
            if requires_target_name:
                reason_code = "EXTERNAL_TARGET_NAME_REQUIRED"
                task_note += "。同名設定があるため新しい名前を指定してください"
            inspections.append(
                _ExternalImportInspection(
                    ExternalScheduleImportCandidate(
                        external_id=external_id,
                        source_schedule_id=schedule_id,
                        display_name=display_name,
                        task_name=task_name,
                        snapshot_id=snapshot_id,
                        importable=True,
                        reason_code=reason_code,
                        reason=task_note,
                        source_config_path=(
                            source_dir / "schedule-registration.json"
                        ),
                        source_config_dir=source_dir,
                        source_profile_path=profile.path,
                        source_revision=source_revision,
                        enabled=source_enabled,
                        schedule=recorded_schedule,
                        effective_save_path=effective_save_path,
                        storage_key=storage_key,
                        storage_folder=storage_folder,
                        requires_target_name=requires_target_name,
                        running=False,
                    ),
                    config=config,
                    entry=entry,
                )
            )
        return tuple(inspections)

    def _validate_external_task_name(
        self,
        source_dir: Path,
        schedule_id: str,
        task_name: str,
    ) -> None:
        namespace_path = source_dir / "schedule-instance-id"
        namespace: Optional[str] = None
        if namespace_path.is_file():
            try:
                namespace = self._validate_install_id(
                    namespace_path.read_text(encoding="utf-8").strip()
                )
            except (OSError, ValueError) as exc:
                raise ScheduleServiceError(
                    "旧配置のtask namespaceが不正です",
                    "EXTERNAL_TASK_NAME_INVALID",
                ) from exc
        inferred = self._namespace_from_task_name(task_name, schedule_id)
        if inferred is None or (namespace is not None and inferred != namespace):
            raise ScheduleServiceError(
                "旧台帳のWindowsタスク名が配置識別子と一致しません",
                "EXTERNAL_TASK_NAME_INVALID",
            )

    def _validate_external_task_definition(
        self,
        xml_text: str,
        entry: Mapping[str, Any],
        schedule: ScheduleConfig,
        profile_path: Path,
        schedule_id: str,
    ) -> None:
        """外部taskが検証済みsnapshotだけを起動することを確認する。"""

        raw_arguments = entry.get("arguments", [])
        if not isinstance(raw_arguments, (list, tuple)):
            raise ScheduleServiceError(
                "旧Windowsタスクの起動引数が不正です",
                "EXTERNAL_TASK_DEFINITION_MISMATCH",
            )
        arguments = [str(value) for value in raw_arguments]

        def option_value(option: str) -> Optional[str]:
            try:
                index = arguments.index(option)
            except ValueError:
                return None
            if index + 1 >= len(arguments):
                return None
            return arguments[index + 1]

        config_value = option_value("--config")
        schedule_value = option_value("--schedule-id")
        try:
            config_matches = bool(config_value) and (
                Path(str(config_value)).resolve(strict=False)
                == profile_path.resolve(strict=False)
            )
        except (OSError, RuntimeError, ValueError):
            config_matches = False
        if (
            "--scheduled-run" not in arguments
            or schedule_value != schedule_id
            or not config_matches
        ):
            raise ScheduleServiceError(
                "旧Windowsタスクが候補の検索条件を参照していません",
                "EXTERNAL_TASK_DEFINITION_MISMATCH",
            )
        command = str(entry.get("command") or "")
        working = str(entry.get("working_directory") or "") or None
        try:
            expected_xml = build_task_xml(
                schedule,
                command,
                arguments,
                now=self._now(),
                working_directory=working,
            )
        except (ScheduleServiceError, TypeError, ValueError) as exc:
            raise ScheduleServiceError(
                "旧台帳からWindowsタスク定義を再構成できません",
                "EXTERNAL_TASK_DEFINITION_MISMATCH",
            ) from exc
        if not task_definitions_match(xml_text, expected_xml):
            raise ScheduleServiceError(
                "旧Windowsタスクの実行内容が旧台帳と一致しません",
                "EXTERNAL_TASK_DEFINITION_MISMATCH",
            )

    def _query_external_task(self, task_name: str) -> TaskQueryResult:
        try:
            return self.task_client.query(task_name)
        except ScheduleServiceError:
            raise
        except Exception as exc:
            raise ScheduleServiceError(
                f"旧Windowsタスクを照会できません: {exc}",
                "EXTERNAL_TASK_QUERY_FAILED",
            ) from exc

    def _delete_external_task_exact(self, task_name: str) -> None:
        try:
            try:
                deleted = self.task_client.delete(task_name, missing_ok=False)
                if deleted is False:
                    raise ScheduleServiceError(
                        "外部Windowsタスクが見つかりません",
                        "EXTERNAL_TASK_NOT_FOUND",
                    )
            except TypeError:
                deleted = self.task_client.delete(task_name)
                if deleted is False:
                    raise ScheduleServiceError(
                        "外部Windowsタスクが見つかりません",
                        "EXTERNAL_TASK_NOT_FOUND",
                    )
        except ScheduleServiceError:
            raise
        except Exception as exc:
            raise ScheduleServiceError(
                f"外部Windowsタスクを解除できません: {exc}",
                "EXTERNAL_TASK_REMOVE_FAILED",
            ) from exc

    def _set_external_task_enabled(self, task_name: str, enabled: bool) -> None:
        setter = getattr(self.task_client, "set_enabled", None)
        if callable(setter):
            try:
                setter(task_name, enabled)
                return
            except ScheduleServiceError:
                raise
            except Exception as exc:
                raise ScheduleServiceError(
                    "旧Windowsタスクの有効状態を変更できません",
                    "EXTERNAL_TASK_DISABLE_FAILED",
                ) from exc
        method = getattr(
            self.task_client,
            "enable" if enabled else "disable",
            None,
        )
        if not callable(method):
            raise ScheduleServiceError(
                "Windowsタスクの一時無効化機能が利用できません",
                "EXTERNAL_TASK_DISABLE_UNSUPPORTED",
            )
        try:
            method(task_name)
        except ScheduleServiceError:
            raise
        except Exception as exc:
            raise ScheduleServiceError(
                "旧Windowsタスクの有効状態を変更できません",
                "EXTERNAL_TASK_DISABLE_FAILED",
            ) from exc

    @staticmethod
    def _external_import_id(
        source_dir: Path,
        schedule_id: str,
        snapshot_id: str,
    ) -> str:
        source = os.path.normcase(str(source_dir.resolve(strict=False)))
        digest = hashlib.sha256(
            f"{source}\0{schedule_id}\0{snapshot_id}".encode("utf-8")
        ).hexdigest()
        return f"legacy-{digest[:16]}"

    def history(
        self,
        schedule_id: Optional[str] | int = None,
        limit: int = 20,
    ) -> list[ScheduledRunRecord]:
        """指定scheduleの履歴を返し、旧``history(20)``も維持する。"""

        if isinstance(schedule_id, int):
            if limit != 20:
                raise TypeError("limitを重複して指定できません")
            resolved_id = None
            resolved_limit = schedule_id
        else:
            resolved_id = (
                validate_schedule_id(schedule_id)
                if schedule_id is not None
                else None
            )
            resolved_limit = limit
        return self.ledger.recent(
            resolved_limit,
            schedule_id=resolved_id,
        )

    get_history = history

    def history_for_schedule(
        self,
        schedule_id: str,
        limit: int = 20,
        *,
        snapshot_id: Optional[str] = None,
    ) -> list[ScheduledRunRecord]:
        return self.ledger.recent(
            limit,
            schedule_id=validate_schedule_id(schedule_id),
            snapshot_id=snapshot_id,
        )

    def _status_from_entry(
        self,
        schedule_id: str,
        entry: Optional[Mapping[str, Any]],
        query: TaskQueryResult,
        current_config: Optional[AppConfig],
        *,
        latest_records: Optional[
            Mapping[str, Optional[ScheduledRunRecord]]
        ] = None,
    ) -> ScheduleRegistrationStatus:
        task_name = str(
            (entry or {}).get("task_name") or self.task_name_for(schedule_id)
        )
        if entry is None:
            # 画面の現在条件を問い合わせる単一status APIでは、この配置が
            # 管理していないtaskを代表状態へ昇格させない。外部taskは
            # get_statuses/list_external_schedule_candidatesで別行に公開する。
            if current_config is not None and not current_config.schedule.enabled:
                return ScheduleRegistrationStatus(
                    state=ScheduleState.DISABLED,
                    task_name=task_name,
                    schedule_id=schedule_id,
                    enabled=False,
                )
            if not query.exists and (
                current_config is None or not current_config.schedule.enabled
            ):
                return ScheduleRegistrationStatus(
                    state=ScheduleState.DISABLED,
                    task_name=task_name,
                    schedule_id=schedule_id,
                    enabled=False,
                )
            if query.exists:
                return self._external_task_status(
                    schedule_id,
                    task_name,
                    query,
                    reason_code="EXTERNAL_TASK_NOT_IMPORTABLE",
                    reason=(
                        "Windowsタスクは存在しますが、この配置の登録台帳が"
                        "ありません。旧設定フォルダーから取り込むか、"
                        "不要なら外部タスクを解除してください"
                    ),
                )
            reason_code = "TASK_NOT_FOUND"
            reason = (
                "登録済みのWindowsタスクが見つかりません。"
                "定期実行設定を保存し直してください"
            )
            return self._repair_status_for(
                schedule_id,
                task_name,
                reason_code,
                reason,
                None,
            )

        enabled = bool(entry.get("enabled", True))
        if not enabled:
            profile, integrity_status = self._inspect_disabled_registration(
                schedule_id,
                task_name,
                entry,
            )
            if integrity_status is not None:
                integrity_status.registered = query.exists
                return integrity_status
            if query.exists:
                return self._repair_status_for(
                    schedule_id,
                    task_name,
                    "TASK_PRESENT_WHILE_DISABLED",
                    "無効な定期実行のWindowsタスクが残っています。解除をやり直してください",
                    entry,
                    definition_mismatch=True,
                )
            return ScheduleRegistrationStatus(
                state=ScheduleState.DISABLED,
                registered=False,
                enabled=False,
                task_name=task_name,
                schedule_id=schedule_id,
                name=str(entry.get("name") or DEFAULT_SCHEDULE_NAME),
                profile_id=self._snapshot_id(entry),
                snapshot_id=self._snapshot_id(entry),
                profile_fingerprint=(
                    profile.fingerprint
                    if profile is not None
                    else self._snapshot_fingerprint(entry)
                ),
                storage_key=str(entry.get("storage_key") or ""),
                storage_folder=str(entry.get("storage_folder") or ""),
            )

        snapshot_id = self._snapshot_id(entry)
        try:
            profile = self.profile_store.get(snapshot_id)
        except ScheduleServiceError as exc:
            return self._repair_status_for(
                schedule_id,
                task_name,
                exc.reason_code,
                str(exc),
                entry,
            )
        if profile.schedule_id != schedule_id:
            return self._repair_status_for(
                schedule_id,
                task_name,
                "PROFILE_SCHEDULE_MISMATCH",
                "検索条件スナップショットが別の定期実行に属しています",
                entry,
                profile=profile,
            )
        recorded_path = str(
            entry.get("snapshot_path") or entry.get("profile_path") or ""
        )
        if not recorded_path or not self._path_text_equal(
            recorded_path,
            profile.path,
        ):
            relocation = self._entry_is_known_relocation(entry, profile)
            return self._repair_status_for(
                schedule_id,
                task_name,
                (
                    "INSTALLATION_PATH_CHANGED"
                    if relocation
                    else "PROFILE_PATH_MISMATCH"
                ),
                (
                    "配置フォルダーが変更されています。現在の配置へ付け替えてください"
                    if relocation
                    else "登録台帳のスナップショット保存先が現在の保存先と一致しません。設定を保存し直してください"
                ),
                entry,
                profile=profile,
                definition_mismatch=relocation,
            )
        if self._snapshot_fingerprint(entry) != profile.fingerprint:
            return self._repair_status_for(
                schedule_id,
                task_name,
                "PROFILE_FINGERPRINT_MISMATCH",
                "登録台帳と検索条件スナップショットの識別情報が一致しません。設定を保存し直してください",
                entry,
                profile=profile,
            )

        command = Path(str(entry.get("command", "")))
        if not command.is_file():
            return self._repair_status_for(
                schedule_id,
                task_name,
                "EXECUTABLE_NOT_FOUND",
                f"定期実行に登録された実行ファイルが見つかりません: {command}",
                entry,
                profile=profile,
            )
        working_directory = str(entry.get("working_directory", "")) or None
        if working_directory and not Path(working_directory).is_dir():
            return self._repair_status_for(
                schedule_id,
                task_name,
                "WORKING_DIRECTORY_NOT_FOUND",
                f"定期実行の作業フォルダーが見つかりません: {working_directory}",
                entry,
                profile=profile,
            )
        arguments = [str(value) for value in entry.get("arguments", [])]
        if command.stem.lower() in {"python", "pythonw"}:
            try:
                self._validate_source_python(command)
            except ScheduleServiceError as exc:
                return self._repair_status_for(
                    schedule_id,
                    task_name,
                    exc.reason_code,
                    str(exc),
                    entry,
                    profile=profile,
                )
            if not arguments or not Path(arguments[0]).is_file():
                return self._repair_status_for(
                    schedule_id,
                    task_name,
                    "SCRIPT_NOT_FOUND",
                    "定期実行の起動スクリプトが見つかりません",
                    entry,
                    profile=profile,
                )
        try:
            placement_changes = self._current_action_changes(
                schedule_id,
                entry,
                profile,
            )
        except ScheduleServiceError as exc:
            return self._repair_status_for(
                schedule_id,
                task_name,
                exc.reason_code,
                str(exc),
                entry,
                profile=profile,
            )
        if placement_changes:
            return self._repair_status_for(
                schedule_id,
                task_name,
                "INSTALLATION_PATH_CHANGED",
                "配置フォルダーが変更されています。現在の配置へ付け替えてください",
                entry,
                profile=profile,
                definition_mismatch=True,
            )
        if not query.exists:
            return self._repair_status_for(
                schedule_id,
                task_name,
                "TASK_NOT_FOUND",
                "登録済みのWindowsタスクが見つかりません。定期実行設定を保存し直してください",
                entry,
                profile=profile,
            )
        try:
            schedule = self._schedule_from_metadata(entry)
            expected_xml = build_task_xml(
                schedule,
                command,
                arguments,
                now=self._now(),
                working_directory=working_directory,
            )
        except (ScheduleServiceError, TypeError, ValueError) as exc:
            code = (
                exc.reason_code
                if isinstance(exc, ScheduleServiceError)
                else "REGISTRATION_METADATA_INVALID"
            )
            return self._repair_status_for(
                schedule_id,
                task_name,
                code,
                f"登録済みスケジュールの形式が不正です: {exc}",
                entry,
                profile=profile,
            )
        if query.enabled is False:
            return self._repair_status_for(
                schedule_id,
                task_name,
                "TASK_DISABLED_EXTERNALLY",
                "Windowsタスクが無効化されています。定期実行設定を保存し直してください",
                entry,
                profile=profile,
                definition_mismatch=True,
            )
        if not query.xml or not task_definitions_match(query.xml, expected_xml):
            return self._repair_status_for(
                schedule_id,
                task_name,
                "TASK_DEFINITION_MISMATCH",
                "Windowsタスクの定義が登録内容と一致しません。定期実行設定を保存し直してください",
                entry,
                profile=profile,
                definition_mismatch=True,
            )

        latest = (
            self.ledger.latest(schedule_id=schedule_id)
            if latest_records is None
            else latest_records.get(schedule_id)
        )
        created_at = self._metadata_timestamp(entry, "created_at", "registered_at")
        if latest is not None and not self._record_belongs_to_generation(
            latest,
            snapshot_id=snapshot_id,
            created_at=created_at,
        ):
            latest = None
        fingerprint_changed = (
            current_config is not None
            and not self.profile_store.matches_config(profile, current_config)
        )
        schedule_changed = (
            current_config is not None
            and self._schedule_comparison_key(current_config.schedule)
            != self._schedule_comparison_key(schedule)
        )
        definition_mismatch = fingerprint_changed or schedule_changed
        updated_at = self._metadata_timestamp(entry, "updated_at", "registered_at")
        task_failure = self._task_result_is_failure(query.last_result) and (
            query.last_run is None
            or updated_at is None
            or self._datetime_at_or_after(query.last_run, updated_at)
        )
        task_failure_is_latest = task_failure and self._task_result_is_newer(
            query.last_run,
            latest,
        )
        if query.running:
            state = ScheduleState.RUNNING
        elif definition_mismatch:
            state = ScheduleState.UPDATE_REQUIRED
        elif task_failure_is_latest:
            state = ScheduleState.LAST_FAILED
        elif latest is not None and latest.exit_code != 0:
            state = ScheduleState.LAST_FAILED
        else:
            state = ScheduleState.REGISTERED
        last_result = latest.result if latest else None
        reason_code = None
        if task_failure_is_latest:
            last_result = "failed"
            reason_code = f"TASK_EXIT_CODE_{query.last_result}"
        return ScheduleRegistrationStatus(
            state=state,
            registered=True,
            running=query.running,
            enabled=True,
            next_run=query.next_run or calculate_next_run(schedule, self._now()),
            last_run=query.last_run
            or ((latest.finished_at or latest.started_at) if latest else None),
            last_result=last_result,
            definition_mismatch=definition_mismatch,
            reason_code=reason_code,
            task_name=task_name,
            schedule_id=schedule_id,
            name=str(entry.get("name") or DEFAULT_SCHEDULE_NAME),
            profile_id=snapshot_id,
            snapshot_id=snapshot_id,
            profile_fingerprint=profile.fingerprint,
            new_count=latest.new_count if latest else 0,
            saved_count=latest.saved_count if latest else 0,
            existing_count=latest.existing_count if latest else 0,
            failed_count=latest.failed_count if latest else 0,
            task_exit_code=query.last_result,
            storage_key=str(entry.get("storage_key") or ""),
            storage_folder=str(entry.get("storage_folder") or ""),
        )

    def _inspect_disabled_registration(
        self,
        schedule_id: str,
        task_name: str,
        entry: Mapping[str, Any],
    ) -> tuple[
        Optional[ScheduledProfile],
        Optional[ScheduleRegistrationStatus],
    ]:
        """無効定義でも、再有効化に必要な資源の破損を検出する。"""

        snapshot_id = self._snapshot_id(entry)
        if not snapshot_id:
            return None, self._repair_status_for(
                schedule_id,
                task_name,
                "REGISTRATION_METADATA_INVALID",
                "無効な定期実行にスナップショットIDがありません。設定を保存し直してください",
                entry,
            )
        try:
            profile = self.profile_store.get(snapshot_id)
        except ScheduleServiceError as exc:
            return None, self._repair_status_for(
                schedule_id,
                task_name,
                exc.reason_code,
                str(exc),
                entry,
            )
        if profile.schedule_id != schedule_id:
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                "PROFILE_SCHEDULE_MISMATCH",
                "検索条件スナップショットが別の定期実行に属しています",
                entry,
                profile=profile,
            )

        recorded_path = str(
            entry.get("snapshot_path") or entry.get("profile_path") or ""
        )
        if (
            not recorded_path
            or Path(recorded_path).resolve(strict=False)
            != profile.path.resolve(strict=False)
        ):
            relocation = self._entry_is_known_relocation(entry, profile)
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                (
                    "INSTALLATION_PATH_CHANGED"
                    if relocation
                    else "PROFILE_PATH_MISMATCH"
                ),
                (
                    "配置フォルダーが変更されています。現在の配置へ付け替えてください"
                    if relocation
                    else "登録台帳のスナップショット保存先が現在の保存先と一致しません。設定を保存し直してください"
                ),
                entry,
                profile=profile,
                definition_mismatch=relocation,
            )
        if self._snapshot_fingerprint(entry) != profile.fingerprint:
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                "PROFILE_FINGERPRINT_MISMATCH",
                "登録台帳と検索条件スナップショットの識別情報が一致しません。設定を保存し直してください",
                entry,
                profile=profile,
            )

        try:
            self._schedule_from_metadata(entry)
        except ScheduleServiceError as exc:
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                exc.reason_code,
                str(exc),
                entry,
                profile=profile,
            )

        command = Path(str(entry.get("command") or ""))
        if not command.is_file():
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                "EXECUTABLE_NOT_FOUND",
                f"定期実行に登録された実行ファイルが見つかりません: {command}",
                entry,
                profile=profile,
            )
        working_directory = str(entry.get("working_directory") or "")
        if working_directory and not Path(working_directory).is_dir():
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                "WORKING_DIRECTORY_NOT_FOUND",
                f"定期実行の作業フォルダーが見つかりません: {working_directory}",
                entry,
                profile=profile,
            )
        raw_arguments = entry.get("arguments", [])
        if not isinstance(raw_arguments, (list, tuple)):
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                "REGISTRATION_METADATA_INVALID",
                "定期実行の起動引数が不正です。設定を保存し直してください",
                entry,
                profile=profile,
            )
        arguments = [str(value) for value in raw_arguments]
        if command.stem.lower() in {"python", "pythonw"}:
            try:
                self._validate_source_python(command)
            except ScheduleServiceError as exc:
                return profile, self._repair_status_for(
                    schedule_id,
                    task_name,
                    exc.reason_code,
                    str(exc),
                    entry,
                    profile=profile,
                )
            if not arguments or not Path(arguments[0]).is_file():
                return profile, self._repair_status_for(
                    schedule_id,
                    task_name,
                    "SCRIPT_NOT_FOUND",
                    "定期実行の起動スクリプトが見つかりません",
                    entry,
                    profile=profile,
                )
        try:
            placement_changes = self._current_action_changes(
                schedule_id,
                entry,
                profile,
            )
        except ScheduleServiceError as exc:
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                exc.reason_code,
                str(exc),
                entry,
                profile=profile,
            )
        if placement_changes:
            return profile, self._repair_status_for(
                schedule_id,
                task_name,
                "INSTALLATION_PATH_CHANGED",
                "配置フォルダーが変更されています。現在の配置へ付け替えてください",
                entry,
                profile=profile,
                definition_mismatch=True,
            )
        return profile, None

    # base末尾に残るv1 private実装よりこちらを優先する。
    def _read_registration(
        self,
        schedule_id: str = DEFAULT_SCHEDULE_ID,
    ) -> Optional[dict[str, Any]]:
        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            entry = document["registrations"].get(identifier)
            if entry is None:
                return None
            result = deepcopy(dict(entry))
            result["schema_version"] = REGISTRATION_SCHEMA_VERSION
            result["profile_id"] = self._snapshot_id(entry)
            result["profile_path"] = str(entry.get("snapshot_path") or "")
            result["profile_fingerprint"] = self._snapshot_fingerprint(entry)
            return result

    def _write_registration(self, metadata: dict[str, Any]) -> None:
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            revision = int(document.get("revision", 0) or 0)
            entry = deepcopy(dict(metadata))
            entry.pop("schema_version", None)
            entry.setdefault("schedule_id", DEFAULT_SCHEDULE_ID)
            entry.setdefault("name", DEFAULT_SCHEDULE_NAME)
            entry.setdefault("enabled", True)
            if "snapshot_id" not in entry and entry.get("profile_id"):
                entry["snapshot_id"] = entry["profile_id"]
            if "snapshot_path" not in entry and entry.get("profile_path"):
                entry["snapshot_path"] = entry["profile_path"]
            if "snapshot_fingerprint" not in entry and entry.get("profile_fingerprint"):
                entry["snapshot_fingerprint"] = entry["profile_fingerprint"]
            document["registrations"][DEFAULT_SCHEDULE_ID] = entry
            self.registration_store.write_unlocked(
                document,
                expected_revision=revision,
            )

    def _safe_query(self) -> Optional[TaskQueryResult]:
        return self._safe_query_for(self.task_name)

    @staticmethod
    def _metadata_timestamp(
        metadata: Mapping[str, Any],
        *keys: str,
    ) -> Optional[datetime]:
        for key in keys:
            value = metadata.get(key)
            if not value:
                continue
            try:
                return datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _datetime_at_or_after(value: datetime, boundary: datetime) -> bool:
        try:
            return value >= boundary
        except TypeError:
            return value.replace(tzinfo=None) >= boundary.replace(tzinfo=None)

    @classmethod
    def _record_belongs_to_generation(
        cls,
        record: ScheduledRunRecord,
        *,
        snapshot_id: str,
        created_at: Optional[datetime],
    ) -> bool:
        if record.snapshot_id == snapshot_id:
            return True
        record_time = record.finished_at or record.started_at or record.scheduled_at
        if created_at is None:
            return True
        if record_time is None:
            # 世代を証明できない旧レコードは、異なるsnapshotへ継承しない。
            return False
        return cls._datetime_at_or_after(record_time, created_at)

    @staticmethod
    def _has_retained_snapshots(document: Mapping[str, Any]) -> bool:
        if document.get("retained_snapshots"):
            return True
        return any(
            bool(entry.get("retained_snapshot_ids"))
            for entry in document.get("registrations", {}).values()
            if isinstance(entry, Mapping)
        )

    def _condition_fingerprint_for_entry(
        self,
        entry: Optional[Mapping[str, Any]],
    ) -> str:
        if not entry:
            return ""
        stored = str(entry.get("condition_fingerprint") or "")
        if stored:
            return stored
        snapshot_id = self._snapshot_id(entry)
        if not snapshot_id:
            return ""
        try:
            return calculate_condition_fingerprint(
                self.profile_store.read(snapshot_id)
            )
        except ScheduleServiceError:
            return ""

    def _condition_duplicate_ids(
        self,
        schedule_id: str,
        entry: Optional[Mapping[str, Any]],
        registrations: Mapping[str, Any],
    ) -> tuple[str, ...]:
        wanted = self._condition_fingerprint_for_entry(entry)
        if not wanted:
            return ()
        return tuple(
            sorted(
                other_id
                for other_id, other in registrations.items()
                if other_id != schedule_id
                and isinstance(other, Mapping)
                and self._condition_fingerprint_for_entry(other) == wanted
            )
        )

    def _decorate_condition_status(
        self,
        status: ScheduleRegistrationStatus,
        schedule_id: str,
        entry: Optional[Mapping[str, Any]],
        registrations: Mapping[str, Any],
    ) -> ScheduleRegistrationStatus:
        status.condition_fingerprint = self._condition_fingerprint_for_entry(entry)
        status.condition_duplicate_schedule_ids = self._condition_duplicate_ids(
            schedule_id,
            entry,
            registrations,
        )
        return status

    def find_condition_duplicates(self, schedule_id: str) -> tuple[str, ...]:
        """同一の検索・保存条件を持つ他スケジュールIDを返す。"""

        identifier = validate_schedule_id(schedule_id)
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            entry = document["registrations"].get(identifier)
            if entry is None:
                raise ScheduleServiceError(
                    "対象の定期実行が見つかりません",
                    "SCHEDULE_NOT_FOUND",
                )
            return self._condition_duplicate_ids(
                identifier,
                entry,
                document["registrations"],
            )

    get_condition_duplicates = find_condition_duplicates

    def finalize_scheduled_run(
        self,
        schedule_id: str,
        snapshot_id: Optional[str] = None,
    ) -> tuple[str, ...]:
        """実行記録の確定後に、更新・削除済みsnapshotを安全に回収する。"""

        identifier = validate_schedule_id(schedule_id)
        return self.cleanup_retained_snapshots(
            schedule_id=identifier,
            completed_snapshot_id=snapshot_id,
        )

    def cleanup_retained_snapshots(
        self,
        *,
        schedule_id: Optional[str] = None,
        completed_snapshot_id: Optional[str] = None,
    ) -> tuple[str, ...]:
        """active・rollback・待機/実行中を除いた旧snapshotを回収する。"""

        selected_id = (
            validate_schedule_id(schedule_id) if schedule_id is not None else None
        )
        removed: list[str] = []
        queued_snapshot_ids = self._queued_snapshot_ids()
        if queued_snapshot_ids is None:
            # ticketを照会できないときに旧snapshotを消すと、FIFO待機済みの
            # 実行が設定を失う。回収は次回の正常な照会まで延期する。
            return ()
        with self._lock, self.registration_store.transaction():
            document = self.registration_store.read_unlocked()
            revision = int(document.get("revision", 0) or 0)
            registrations = document["registrations"]
            active_snapshot_ids = {
                self._snapshot_id(entry)
                for entry in registrations.values()
                if isinstance(entry, Mapping) and self._snapshot_id(entry)
            }
            def delete_if_safe(
                owner_id: str,
                snapshot_id: str,
                task_name: str,
            ) -> bool:
                if (
                    not snapshot_id
                    or snapshot_id in active_snapshot_ids
                    or snapshot_id in self._protected_snapshot_ids
                    or snapshot_id in queued_snapshot_ids
                ):
                    return False
                if completed_snapshot_id == snapshot_id:
                    # 実行終了通知と次回起動の間にも競合窓を作らない。
                    # completed時はTask Schedulerのrunning反映遅延を避け、
                    # schedule mutexを真実源としてunlinkまで保持する。
                    schedule_guard = make_schedule_run_guard(owner_id)
                    with schedule_guard.try_acquire() as schedule_idle:
                        if not schedule_idle:
                            return False
                        try:
                            self.profile_store.delete(snapshot_id)
                        except ScheduleServiceError:
                            return False
                        removed.append(snapshot_id)
                        return True

                # 照会からunlinkまで両mutexを保持し、別process開始との
                # TOCTOUを作らない。Task削除後の実行中instanceも
                # schedule mutexによって検出できる。
                schedule_guard = make_schedule_run_guard(owner_id)
                with schedule_guard.try_acquire() as schedule_idle:
                    if not schedule_idle:
                        return False
                    with DOWNLOAD_RUN_GUARD.try_acquire() as globally_idle:
                        if not globally_idle:
                            return False
                        query = self._safe_query_for(task_name)
                        if query is None or query.running:
                            return False
                        try:
                            self.profile_store.delete(snapshot_id)
                        except ScheduleServiceError:
                            return False
                        removed.append(snapshot_id)
                        return True

            changed = False
            for owner_id, entry in registrations.items():
                if selected_id is not None and owner_id != selected_id:
                    continue
                retained_ids = [
                    str(value)
                    for value in entry.get("retained_snapshot_ids", [])
                    if value
                ]
                if not retained_ids:
                    continue
                task_name = str(
                    entry.get("task_name") or self.task_name_for(owner_id)
                )
                kept = [
                    snapshot_id
                    for snapshot_id in retained_ids
                    if not delete_if_safe(owner_id, snapshot_id, task_name)
                ]
                if kept != retained_ids:
                    entry["retained_snapshot_ids"] = kept
                    changed = True

            retained_items = document.get("retained_snapshots", [])
            kept_items: list[dict[str, Any]] = []
            for raw_item in retained_items:
                item = dict(raw_item)
                owner_id = str(item.get("schedule_id") or DEFAULT_SCHEDULE_ID)
                snapshot_id = str(item.get("snapshot_id") or "")
                if selected_id is not None and owner_id != selected_id:
                    kept_items.append(item)
                    continue
                task_name = str(
                    item.get("task_name") or self.task_name_for(owner_id)
                )
                if not delete_if_safe(owner_id, snapshot_id, task_name):
                    kept_items.append(item)
            if kept_items != retained_items:
                document["retained_snapshots"] = kept_items
                changed = True

            if changed:
                self.registration_store.write_unlocked(
                    document,
                    expected_revision=revision,
                )
        return tuple(removed)
