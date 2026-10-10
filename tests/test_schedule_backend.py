# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tracemalloc
from types import SimpleNamespace
import pytest
import yaml

from src.app.run_guard import make_schedule_run_guard
from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig, ScheduleConfig
from src.scheduler.ledger import ScheduleRunLedger
from src.scheduler.models import (
    ScheduleRegistrationStatus,
    ScheduleServiceError,
    ScheduleState,
    ScheduledRunRecord,
)
from src.scheduler.profile import (
    PROFILE_METADATA_KEY,
    PROFILE_SCHEMA_VERSION,
    ScheduleProfileStore,
    calculate_condition_fingerprint,
    calculate_profile_fingerprint,
)
from src.scheduler.service import (
    ScheduleService,
    calculate_next_run,
    japan_timezone,
)
from src.scheduler.task_scheduler import (
    CommandResult,
    SchtasksClient,
    TaskQueryResult,
    build_task_xml,
    task_definitions_match,
    task_definition_signature,
)


JST = timezone(timedelta(hours=9))


class FakeTaskClient:
    def __init__(self):
        self.xml = None
        self.exists = False
        self.running = False
        self.fail_registration = False
        self.calls = []
        self.next_run = None
        self.last_run = None
        self.last_result = None
        self.enabled = None

    def query(self, task_name):
        self.calls.append(("query", task_name))
        return TaskQueryResult(
            self.exists,
            self.running,
            self.xml,
            next_run=self.next_run,
            last_run=self.last_run,
            last_result=self.last_result,
            enabled=self.enabled,
        )

    def create_or_update(self, task_name, xml):
        self.calls.append(("create", task_name, xml))
        if self.fail_registration:
            raise ScheduleServiceError("登録失敗", "TASK_REGISTER_FAILED")
        self.exists = True
        self.xml = xml

    def delete(self, task_name, missing_ok=False):
        self.calls.append(("delete", task_name, missing_ok))
        existed = self.exists
        self.exists = False
        self.xml = None
        return existed

    def run(self, task_name):
        self.calls.append(("run", task_name))
        return self.exists


class MultiTaskClient:
    def __init__(self):
        self.tasks = {}
        self.calls = []
        self.fail_for = set()
        self.running = set()
        self.disabled = set()
        self.fail_delete_for = set()
        self.fail_disable_for = set()
        self.query_many_calls = 0

    def query(self, task_name):
        self.calls.append(("query", task_name))
        xml = self.tasks.get(task_name)
        return TaskQueryResult(
            exists=xml is not None,
            running=task_name in self.running,
            xml=xml,
            enabled=(task_name not in self.disabled) if xml is not None else None,
        )

    def query_many(self, task_names):
        self.query_many_calls += 1
        return {task_name: self.query(task_name) for task_name in task_names}

    def create_or_update(self, task_name, xml):
        self.calls.append(("create", task_name, xml))
        if task_name in self.fail_for:
            raise ScheduleServiceError("登録失敗", "TASK_REGISTER_FAILED")
        self.tasks[task_name] = xml
        self.disabled.discard(task_name)

    def delete(self, task_name, missing_ok=False):
        self.calls.append(("delete", task_name, missing_ok))
        if task_name in self.fail_delete_for:
            raise ScheduleServiceError("削除失敗", "TASK_DELETE_FAILED")
        self.disabled.discard(task_name)
        return self.tasks.pop(task_name, None) is not None

    def set_enabled(self, task_name, enabled):
        self.calls.append(("set_enabled", task_name, enabled))
        if not enabled and task_name in self.fail_disable_for:
            raise ScheduleServiceError("無効化失敗", "TASK_DISABLE_FAILED")
        if task_name not in self.tasks:
            raise ScheduleServiceError("タスクなし", "TASK_NOT_FOUND")
        if enabled:
            self.disabled.discard(task_name)
        else:
            self.disabled.add(task_name)
        return True

    def run(self, task_name):
        self.calls.append(("run", task_name))
        return task_name in self.tasks


def _service(
    tmp_path,
    client,
    now=None,
    queue_status_provider=None,
    queue_ticket_provider=None,
):
    executable = tmp_path / "ippi-down.exe"
    executable.write_bytes(b"stub")
    return ScheduleService(
        config_dir=tmp_path / "config",
        logs_dir=tmp_path / "logs",
        install_id="test-install",
        task_client=client,
        executable=executable,
        app_root=tmp_path,
        now_provider=lambda: now or datetime(2026, 8, 3, 10, 0, tzinfo=JST),
        queue_status_provider=queue_status_provider,
        queue_ticket_provider=queue_ticket_provider,
    )


@pytest.mark.parametrize(
    ("interval", "extra", "expected"),
    [
        ("daily", {}, datetime(2026, 8, 4, 9, 0, tzinfo=JST)),
        (
            "weekly",
            {"weekday": "monday"},
            datetime(2026, 8, 10, 9, 0, tzinfo=JST),
        ),
        (
            "monthly",
            {"day_of_month": 28},
            datetime(2026, 8, 28, 9, 0, tzinfo=JST),
        ),
    ],
)
def test_calculate_next_run(interval, extra, expected):
    config = ScheduleConfig(enabled=True, interval=interval, time="09:00", **extra)
    now = datetime(2026, 8, 3, 10, 0, tzinfo=JST)
    assert calculate_next_run(config, now) == expected


def test_japan_timezone_does_not_require_external_tzdata():
    assert japan_timezone().utcoffset(None) == timedelta(hours=9)


def test_monthly_task_uses_native_calendar_trigger_and_working_directory(tmp_path):
    xml = build_task_xml(
        ScheduleConfig(
            enabled=True,
            interval="monthly",
            time="08:15",
            day_of_month=28,
        ),
        tmp_path / "ippi-down.exe",
        ["--scheduled-run", "--config", tmp_path / "profile.yaml"],
        now=datetime(2026, 8, 3, tzinfo=JST),
        user_id="DOMAIN\\user",
        working_directory=tmp_path,
    )

    assert "ScheduleByMonth" in xml
    assert "<Day>28</Day>" in xml
    assert "ScheduleByDay" not in xml
    assert "<WorkingDirectory>" in xml
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>" in xml
    assert "<ExecutionTimeLimit>PT4H</ExecutionTimeLimit>" in xml
    assert task_definition_signature(xml)


def test_task_definition_comparison_ignores_scheduler_added_trigger_defaults(tmp_path):
    expected = build_task_xml(
        ScheduleConfig(enabled=True, interval="daily", time="08:15"),
        tmp_path / "ippi-down.exe",
        ["--scheduled-run", "--config", tmp_path / "profile.yaml"],
        now=datetime(2026, 8, 3, tzinfo=JST),
        working_directory=tmp_path,
    )
    actual = expected.replace(
        "<Enabled>true</Enabled><ScheduleByDay>",
        "<Enabled>true</Enabled><RandomDelay>PT0S</RandomDelay><ScheduleByDay>",
    ).replace("2026-08-03T08:15:00", "2026-09-01T08:15:00")

    assert task_definitions_match(actual, expected) is True


def test_task_definition_comparison_accepts_omitted_windows_defaults(tmp_path):
    expected = build_task_xml(
        ScheduleConfig(enabled=True, interval="daily", time="08:15"),
        tmp_path / "ippi-down.exe",
        ["--scheduled-run", "--config", tmp_path / "profile.yaml"],
        working_directory=tmp_path,
    )
    actual = expected.replace("<WakeToRun>false</WakeToRun>", "").replace(
        "<RunLevel>LeastPrivilege</RunLevel>", ""
    )

    assert task_definitions_match(actual, expected) is True


def test_schtasks_query_does_not_treat_access_denied_as_missing():
    client = SchtasksClient(
        runner=lambda *_args, **_kwargs: CommandResult(
            1, stderr="ERROR: Access is denied."
        )
    )

    with pytest.raises(ScheduleServiceError) as raised:
        client.query(r"\ippi-down\Download-test")

    assert raised.value.reason_code == "TASK_QUERY_FAILED"


def test_schtasks_create_ensures_parent_folder_before_xml_registration():
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        return CommandResult(0)

    client = SchtasksClient(runner=runner)
    client.create_or_update(r"\ippi-down\Download-test", "<Task />")

    assert commands[0][0] == "powershell.exe"
    assert "Schedule.Service" in commands[0][-1]
    assert commands[1][0] == "schtasks.exe"
    assert commands[1][1:3] == ["/Create", "/TN"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows絶対パス専用")
def test_default_schtasks_client_uses_get_system_directory_paths(
    tmp_path,
    monkeypatch,
):
    from src.scheduler import task_scheduler as task_scheduler_module

    system_directory = tmp_path / "Windows" / "System32"
    monkeypatch.setattr(
        task_scheduler_module,
        "_windows_system_directory",
        lambda: system_directory.resolve(strict=False),
    )

    client = SchtasksClient()

    assert client.executable == str(
        (system_directory / "schtasks.exe").resolve(strict=False)
    )
    assert client.powershell_executable == str(
        (
            system_directory
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        ).resolve(strict=False)
    )


def test_schtasks_client_preserves_explicit_program_injection():
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        return CommandResult(0)

    client = SchtasksClient(
        runner=runner,
        executable=r"C:\trusted-test\schtasks.exe",
        powershell_executable=r"C:\trusted-test\powershell.exe",
    )

    client.create_or_update(r"\ippi-down\Download-test", "<Task />")

    assert commands[0][0] == r"C:\trusted-test\powershell.exe"
    assert commands[1][0] == r"C:\trusted-test\schtasks.exe"


def test_schtasks_create_reports_task_folder_failure():
    client = SchtasksClient(
        runner=lambda *_args, **_kwargs: CommandResult(
            1, stderr="folder policy denied"
        )
    )

    with pytest.raises(ScheduleServiceError) as raised:
        client.create_or_update(r"\ippi-down\Download-test", "<Task />")

    assert raised.value.reason_code == "TASK_FOLDER_CREATE_FAILED"


def test_schtasks_query_parses_english_runtime_details(tmp_path):
    xml = build_task_xml(
        ScheduleConfig(enabled=True, interval="daily", time="09:00"),
        tmp_path / "ippi-down.exe",
        ["--scheduled-run", "--config", tmp_path / "profile.yaml"],
    )
    details = (
        '"HostName","TaskName","Next Run Time","Status",'
        '"Last Run Time","Last Result"\n'
        '"PC","\\ippi-down\\Download-test","08/04/2026 09:00:00",'
        '"Ready","08/03/2026 09:00:00","2"\n'
    )
    responses = iter((CommandResult(0, xml), CommandResult(0, details)))
    client = SchtasksClient(runner=lambda *_args, **_kwargs: next(responses))

    result = client.query(r"\ippi-down\Download-test")

    assert result.exists is True
    assert result.enabled is True
    assert result.next_run == datetime(2026, 8, 4, 9, 0, tzinfo=JST)
    assert result.last_run == datetime(2026, 8, 3, 9, 0, tzinfo=JST)
    assert result.last_result == 2


def test_schtasks_query_parses_japanese_never_run_details(tmp_path):
    xml = build_task_xml(
        ScheduleConfig(enabled=True, interval="monthly", day_of_month=28),
        tmp_path / "ippi-down.exe",
        [],
    )
    details = (
        '"ホスト名","タスク名","次回の実行時刻","状態",'
        '"前回の実行時刻","前回の結果"\n'
        '"PC","\\ippi-down\\Download-test","2026/08/28 9:00:00",'
        '"準備完了","1999/11/30 0:00:00","267011"\n'
    )
    responses = iter((CommandResult(0, xml), CommandResult(0, details)))
    client = SchtasksClient(runner=lambda *_args, **_kwargs: next(responses))

    result = client.query(r"\ippi-down\Download-test")

    assert result.next_run == datetime(2026, 8, 28, 9, 0, tzinfo=JST)
    assert result.last_run is None
    assert result.last_result == 0x41303


def test_schtasks_query_reuses_short_status_and_longer_xml_cache(tmp_path):
    xml = build_task_xml(
        ScheduleConfig(enabled=True),
        tmp_path / "ippi-down.exe",
        [],
    )
    details = (
        '"HostName","TaskName","Next Run Time","Status",'
        '"Last Run Time","Last Result"\n'
        '"PC","\\ippi-down\\Download-test","N/A",'
        '"Ready","N/A","267011"\n'
    )
    calls = []
    clock = [0.0]

    def runner(command, **_kwargs):
        calls.append(command)
        if "/XML" in command:
            return CommandResult(0, xml)
        return CommandResult(0, details)

    client = SchtasksClient(
        runner=runner,
        query_cache_seconds=1,
        xml_cache_seconds=60,
        clock=lambda: clock[0],
    )

    first = client.query(r"\ippi-down\Download-test")
    second = client.query(r"\ippi-down\Download-test")
    assert first is second
    assert len(calls) == 2

    clock[0] = 2.0
    refreshed = client.query(r"\ippi-down\Download-test")
    assert refreshed.exists is True
    assert len(calls) == 3
    assert sum("/XML" in command for command in calls) == 1


def test_schtasks_query_many_batches_runtime_and_reuses_xml_cache(tmp_path):
    first_name = r"\ippi-down\Download-test-first"
    second_name = r"\ippi-down\Download-test-second"
    xml_by_name = {
        first_name: build_task_xml(
            ScheduleConfig(enabled=True),
            tmp_path / "ippi-down.exe",
            [],
        ),
        second_name: build_task_xml(
            ScheduleConfig(enabled=True),
            tmp_path / "ippi-down.exe",
            [],
        ),
    }
    details = (
        '"HostName","TaskName","Next Run Time","Status",'
        '"Last Run Time","Last Result"\n'
        f'"PC","{first_name}","08/04/2026 09:00:00",'
        '"Running","08/03/2026 09:00:00","0"\n'
        f'"PC","{second_name}","08/04/2026 09:30:00",'
        '"Ready","N/A","267011"\n'
    )
    calls = []
    clock = [0.0]

    def runner(command, **_kwargs):
        calls.append(command)
        if "/XML" in command:
            return CommandResult(0, xml_by_name[command[3]])
        assert command[1:] == ["/Query", "/V", "/FO", "CSV"]
        return CommandResult(0, details)

    client = SchtasksClient(
        runner=runner,
        query_cache_seconds=1,
        xml_cache_seconds=60,
        clock=lambda: clock[0],
    )

    first = client.query_many((first_name, second_name))

    assert first[first_name].running is True
    assert first[second_name].running is False
    assert first[second_name].last_run is None
    assert first[second_name].last_result == 0x41303
    assert len(calls) == 3
    assert sum("/XML" in command for command in calls) == 2
    assert sum(command[1:] == ["/Query", "/V", "/FO", "CSV"] for command in calls) == 1

    clock[0] = 2.0
    refreshed = client.query_many((first_name, second_name))

    assert refreshed[first_name].exists is True
    assert len(calls) == 4
    assert sum("/XML" in command for command in calls) == 2
    assert sum(command[1:] == ["/Query", "/V", "/FO", "CSV"] for command in calls) == 2


def test_schtasks_query_many_parses_japanese_names_and_marks_absent_missing(tmp_path):
    existing_name = r"\ippi-down\Download-test"
    missing_name = r"\ippi-down\Download-missing"
    xml = build_task_xml(
        ScheduleConfig(enabled=True),
        tmp_path / "ippi-down.exe",
        [],
    )
    details = (
        '"ホスト名","タスク名","次回の実行時刻","状態",'
        '"前回の実行時刻","前回の結果"\n'
        f'"PC","{existing_name.upper()}","2026/08/28 9:00:00",'
        '"準備完了","1999/11/30 0:00:00","267011"\n'
    )
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        if "/XML" in command:
            return CommandResult(0, xml)
        return CommandResult(0, details)

    client = SchtasksClient(runner=runner)

    result = client.query_many((existing_name, missing_name))

    assert result[existing_name].exists is True
    assert result[existing_name].next_run == datetime(2026, 8, 28, 9, 0, tzinfo=JST)
    assert result[missing_name] == TaskQueryResult(exists=False)
    assert sum("/XML" in command for command in calls) == 1


def test_schtasks_query_many_refreshes_cached_xml_when_action_changes(tmp_path):
    task_name = r"\ippi-down\Download-test"
    first_command = tmp_path / "old" / "ippi-down.exe"
    second_command = tmp_path / "new" / "ippi-down.exe"
    xml_documents = [
        build_task_xml(ScheduleConfig(enabled=True), first_command, []),
        build_task_xml(ScheduleConfig(enabled=True), second_command, []),
    ]
    clock = [0.0]
    detail_command = [str(first_command)]
    xml_calls = 0

    def runner(command, **_kwargs):
        nonlocal xml_calls
        if "/XML" in command:
            document = xml_documents[min(xml_calls, 1)]
            xml_calls += 1
            return CommandResult(0, document)
        details = (
            '"TaskName","Status","Task To Run","Scheduled Task State"\n'
            f'"{task_name}","Ready","{detail_command[0]}","Enabled"\n'
        )
        return CommandResult(0, details)

    client = SchtasksClient(
        runner=runner,
        query_cache_seconds=1,
        xml_cache_seconds=float("inf"),
        clock=lambda: clock[0],
    )

    first = client.query_many((task_name,))[task_name]
    assert first.xml == xml_documents[0]
    assert xml_calls == 1

    detail_command[0] = str(second_command)
    clock[0] = 2.0
    second = client.query_many((task_name,))[task_name]

    assert second.xml == xml_documents[1]
    assert xml_calls == 2


def test_schtasks_task_name_list_cache_is_shared_between_prefixes():
    calls = []
    output = (
        '"\\ippi-down\\Download-first-one","N/A","Ready"\n'
        '"\\ippi-down\\Download-second-two","N/A","Ready"\n'
    )

    def runner(command, **_kwargs):
        calls.append(command)
        return CommandResult(0, output)

    client = SchtasksClient(runner=runner, list_cache_seconds=1)

    assert client.list_task_names(r"\ippi-down\Download-first") == (
        r"\ippi-down\Download-first-one",
    )
    assert client.list_task_names(r"\ippi-down\Download-second") == (
        r"\ippi-down\Download-second-two",
    )
    assert calls == [["schtasks.exe", "/Query", "/FO", "CSV", "/NH"]]


def test_task_definition_comparison_detects_external_disable(tmp_path):
    expected = build_task_xml(
        ScheduleConfig(enabled=True),
        tmp_path / "ippi-down.exe",
        [],
    )
    actual = expected.replace(
        "<Enabled>true</Enabled><Hidden>",
        "<Enabled>false</Enabled><Hidden>",
    )

    assert task_definitions_match(actual, expected) is False


def test_profile_and_condition_fingerprints_have_distinct_scopes(tmp_path):
    config = AppConfig()
    original_profile = calculate_profile_fingerprint(config)
    original_condition = calculate_condition_fingerprint(config)
    config.schedule.time = "18:00"
    assert calculate_profile_fingerprint(config) != original_profile
    assert calculate_condition_fingerprint(config) == original_condition
    config.search_conditions.koji_name = "橋梁"
    assert calculate_condition_fingerprint(config) != original_condition

    store = ScheduleProfileStore(tmp_path / "profiles")
    profile = store.create(config, profile_id="profile-1", created_at=datetime(2026, 8, 3, tzinfo=JST))
    document = store.read(profile.path)
    assert document[PROFILE_METADATA_KEY]["fingerprint"] == profile.fingerprint


def test_ledger_keeps_recent_valid_records_when_a_line_is_corrupt(tmp_path):
    ledger = ScheduleRunLedger(tmp_path / "schedule-runs.jsonl")
    ledger.append(ScheduledRunRecord(profile_id="a", result="success", saved_count=2))
    with ledger.path.open("a", encoding="utf-8") as stream:
        stream.write("{broken\n")
    ledger.append(
        ScheduledRunRecord(
            profile_id="b", result="partial_failure", failed_count=1, exit_code=2
        )
    )

    assert [record.profile_id for record in ledger.recent(20)] == ["b", "a"]
    assert ledger.latest().exit_code == 2
    assert ledger.latest("a").profile_id == "a"
    assert ledger.recent(20, profile_id="a")[0].profile_id == "a"


def test_ledger_latest_many_reads_each_schedule_once_and_skips_corrupt_tail(
    tmp_path,
):
    ledger = ScheduleRunLedger(tmp_path / "schedule-runs.jsonl")
    ledger.append(
        ScheduledRunRecord(
            schedule_id="first",
            profile_id="first-old",
            result="failed",
            exit_code=2,
        )
    )
    ledger.append(
        ScheduledRunRecord(
            schedule_id="second",
            profile_id="second-current",
            result="success",
        )
    )
    ledger.append(
        ScheduledRunRecord(
            schedule_id="first",
            profile_id="first-current",
            result="success",
        )
    )
    with ledger.path.open("ab") as stream:
        # UTF-8文字の途中で電源断した場合も、直前の正常行まで利用する。
        stream.write(b'{"schedule_id":"first","display_name":"\xe3\x81')

    records = ledger.latest_many(["first", "second", "missing", "first"])

    assert list(records) == ["first", "second", "missing"]
    assert records["first"].snapshot_id == "first-current"
    assert records["second"].snapshot_id == "second-current"
    assert records["missing"] is None


def test_ledger_large_history_is_read_in_bounded_reverse_chunks(
    tmp_path,
    monkeypatch,
):
    history_path = tmp_path / "schedule-runs.jsonl"
    schedule_count = 50
    with history_path.open("wb") as stream:
        for index in range(100_000):
            schedule_id = f"schedule-{index % schedule_count}"
            payload = {
                "schedule_id": schedule_id,
                "snapshot_id": f"snapshot-{index}",
                "result": "success",
            }
            stream.write(
                json.dumps(payload, separators=(",", ":")).encode("utf-8")
                + b"\n"
            )
        # 電源断を模した不完全な最終行。直前までの履歴を利用できること。
        stream.write(b'{"schedule_id":')

    def reject_full_text_read(*_args, **_kwargs):
        raise AssertionError("履歴ファイル全体をread_textしてはいけません")

    monkeypatch.setattr(Path, "read_text", reject_full_text_read)
    ledger = ScheduleRunLedger(history_path)
    tracemalloc.start()
    try:
        records = ledger.latest_many(
            f"schedule-{index}" for index in range(schedule_count)
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert all(record is not None for record in records.values())
    assert peak < 16 * 1024 * 1024
    assert len(ledger.recent(20)) == 20


def test_ledger_serializes_appends_across_processes(tmp_path):
    history_path = tmp_path / "schedule-runs.jsonl"
    worker = (
        "import sys\n"
        "from src.scheduler.ledger import ScheduleRunLedger\n"
        "from src.scheduler.models import ScheduledRunRecord\n"
        "ledger = ScheduleRunLedger(sys.argv[1])\n"
        "for index in range(int(sys.argv[3])):\n"
        "    ledger.append(ScheduledRunRecord("
        "profile_id=f'{sys.argv[2]}-{index}', result='success'))\n"
    )
    project_root = Path(__file__).resolve().parents[1]
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                worker,
                str(history_path),
                f"worker-{worker_index}",
                "12",
            ],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for worker_index in range(3)
    ]

    results = [process.communicate(timeout=30) for process in processes]

    for process, (_stdout, stderr) in zip(processes, results):
        assert process.returncode == 0, stderr
    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 36
    assert all(isinstance(json.loads(line), dict) for line in lines)
    records = ScheduleRunLedger(history_path).recent(100)
    assert len({record.profile_id for record in records}) == 36


def test_ledger_process_lock_is_released_after_exception(tmp_path):
    first = ScheduleRunLedger(tmp_path / "schedule-runs.jsonl")
    second = ScheduleRunLedger(first.path)

    with pytest.raises(RuntimeError):
        with first._process_lock():
            raise RuntimeError("test failure")

    with second._process_lock():
        pass


def test_register_and_status_detect_unpublished_search_changes(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))

    registered = service.register(config)
    assert registered.state == ScheduleState.REGISTERED
    assert registered.profile_id == config.schedule.active_profile_id
    assert client.xml is not None

    current = service.get_status(config)
    assert current.state == ScheduleState.REGISTERED
    config.search_conditions.koji_name = "未反映"
    changed = service.get_status(config)
    assert changed.state == ScheduleState.UPDATE_REQUIRED
    assert changed.definition_mismatch is True


def test_registered_task_is_marked_for_update_if_config_was_disabled(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    service.register(config)

    config.schedule.enabled = False
    status = service.get_status(config)

    assert status.state == ScheduleState.UPDATE_REQUIRED
    assert status.definition_mismatch is True


def test_external_task_disable_is_reported_as_repair_required(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    service.register(config)
    client.enabled = False

    status = service.get_status(config)

    assert status.state == ScheduleState.REPAIR_REQUIRED
    assert status.reason_code == "TASK_DISABLED_EXTERNALLY"


def test_task_scheduler_failure_is_visible_when_process_never_wrote_ledger(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    service.register(config)
    client.last_run = datetime(2026, 8, 3, 11, 0, tzinfo=JST)
    client.last_result = 3

    status = service.get_status(config)

    assert status.state == ScheduleState.LAST_FAILED
    assert status.last_result == "failed"
    assert status.reason_code == "TASK_EXIT_CODE_3"
    assert status.task_exit_code == 3


def test_updated_schedule_keeps_failure_history_across_snapshots(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    first = service.register(config)
    service.ledger.append(
        ScheduledRunRecord(
            profile_id=first.profile_id,
            result="failed",
            failed_count=1,
            exit_code=2,
            finished_at=datetime(2026, 8, 3, 10, 5, tzinfo=JST),
        )
    )

    config.search_conditions.koji_name = "更新後"
    second = service.register(config)
    status = service.get_status(config)

    assert second.profile_id != first.profile_id
    assert status.state == ScheduleState.LAST_FAILED
    assert status.last_result == "failed"


def test_schedule_config_rejects_non_boolean_task_flags_and_long_retry():
    with pytest.raises(ValueError, match="start_when_available"):
        ScheduleConfig(start_when_available="false")
    with pytest.raises(ValueError, match="wake_to_run"):
        ScheduleConfig(wake_to_run=1)
    with pytest.raises(ValueError, match="1440"):
        ScheduleConfig(retry_interval_minutes=1441)


def test_schedule_service_registry_round_trip_preserves_notification_policy(
    tmp_path,
):
    service = _service(tmp_path, MultiTaskClient())
    config = AppConfig(
        schedule=ScheduleConfig(
            enabled=False,
            notification_policy="all_results",
        )
    )

    service.create_schedule("通知あり", config, schedule_id="notify")
    registry = service.registration_store.read()
    restored = service.get_registered_config("notify")

    assert (
        registry["registrations"]["notify"]["schedule"]["notification_policy"]
        == "all_results"
    )
    assert restored is not None
    assert restored.schedule.notification_policy == "all_results"


def test_failed_update_preserves_previous_task_metadata_and_profile(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    first = service.register(config)
    old_xml = client.xml
    old_metadata = service.registration_path.read_bytes()
    old_profile = service.profile_store.path_for(first.profile_id)

    config.search_conditions.koji_name = "new"
    client.fail_registration = True
    with pytest.raises(ScheduleServiceError, match="登録失敗"):
        service.register(config)

    assert client.xml == old_xml
    assert service.registration_path.read_bytes() == old_metadata
    assert old_profile.exists()
    assert len(list(service.profile_store.root.glob("*.yaml"))) == 1


def test_registration_state_backup_restores_exact_previous_profile(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    config.search_conditions.koji_name = "更新前"
    first = service.register(config)
    first_xml = client.xml
    backup = service.capture_registration_state()

    config.search_conditions.koji_name = "更新後"
    second = service.register(config)
    assert second.profile_id != first.profile_id

    service.restore_registration_state(backup)

    restored = service._read_registration()
    assert restored["profile_id"] == first.profile_id
    assert task_definition_signature(client.xml) == task_definition_signature(
        first_xml
    )
    assert service.get_registered_config().search_conditions.koji_name == "更新前"
    assert not service.profile_store.path_for(second.profile_id).exists()


def test_empty_registration_backup_removes_new_task_and_profile(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    backup = service.capture_registration_state()
    registered = service.register(
        AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    )

    service.restore_registration_state(backup)

    assert client.exists is False
    assert not service.registration_path.exists()
    assert not service.profile_store.path_for(registered.profile_id).exists()


def test_metadata_write_failure_rolls_task_back_and_removes_new_profile(
    tmp_path, monkeypatch
):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    first = service.register(config)
    old_xml = client.xml
    old_metadata = service.registration_path.read_bytes()

    config.search_conditions.koji_name = "new"

    def fail_metadata(_metadata):
        raise ScheduleServiceError("metadata failure", "REGISTRATION_METADATA_WRITE_FAILED")

    monkeypatch.setattr(service, "_write_registration", fail_metadata)
    with pytest.raises(ScheduleServiceError, match="metadata failure"):
        service.register(config)

    assert task_definition_signature(client.xml) == task_definition_signature(old_xml)
    assert service.registration_path.read_bytes() == old_metadata
    assert service.profile_store.path_for(first.profile_id).exists()
    assert len(list(service.profile_store.root.glob("*.yaml"))) == 1


def test_action_validation_failure_does_not_leave_orphan_profile(tmp_path):
    client = FakeTaskClient()
    service = ScheduleService(
        config_dir=tmp_path / "config",
        logs_dir=tmp_path / "logs",
        install_id="test-install",
        task_client=client,
        executable=tmp_path / "missing.exe",
        app_root=tmp_path,
    )
    config = AppConfig(schedule=ScheduleConfig(enabled=True))

    with pytest.raises(ScheduleServiceError) as raised:
        service.register(config)

    assert raised.value.reason_code == "EXECUTABLE_NOT_FOUND"
    assert list(service.profile_store.root.glob("*.yaml")) == []


def test_source_registration_rejects_broken_or_conda_venv(tmp_path):
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_bytes(b"stub")
    (scripts / "pythonw.exe").write_bytes(b"stub")
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("# stub\n", encoding="utf-8")
    def runner(*args, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="did not find executable at miniconda3\\python.exe",
        )
    service = ScheduleService(
        config_dir=tmp_path / "config",
        logs_dir=tmp_path / "logs",
        install_id="test-install",
        task_client=FakeTaskClient(),
        app_root=tmp_path,
        script_path=source,
        python_runner=runner,
    )

    with pytest.raises(ScheduleServiceError) as raised:
        service.register(AppConfig(schedule=ScheduleConfig(enabled=True)))

    assert raised.value.reason_code == "PYTHON_ENVIRONMENT_INVALID"
    assert "scripts\\setup.ps1" in str(raised.value)
    assert list(service.profile_store.root.glob("*.yaml")) == []


def test_corrupt_registration_metadata_is_reported_as_repair_required(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    service.registration_path.parent.mkdir(parents=True, exist_ok=True)
    service.registration_path.write_text("{broken", encoding="utf-8")

    status = service.get_status(AppConfig())

    assert status.state == ScheduleState.REPAIR_REQUIRED
    assert status.reason_code == "REGISTRATION_METADATA_INVALID"


def test_install_move_uses_distinct_task_namespace_and_shared_coordination(tmp_path):
    stable_id = tmp_path / "user-data" / "install-id"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_executable = first_root / "ippi-down.exe"
    first_executable.parent.mkdir(parents=True)
    first_executable.write_bytes(b"stub")
    client = FakeTaskClient()
    first_service = ScheduleService(
        config_dir=first_root / "config",
        logs_dir=first_root / "logs",
        task_client=client,
        executable=first_executable,
        app_root=first_root,
        install_id_path=stable_id,
    )
    first_service.register(
        AppConfig(schedule=ScheduleConfig(enabled=True))
    )

    second_service = ScheduleService(
        config_dir=second_root / "config",
        logs_dir=second_root / "logs",
        task_client=client,
        executable=second_root / "ippi-down.exe",
        app_root=second_root,
        install_id_path=stable_id,
    )
    status = second_service.get_status(AppConfig())

    assert second_service.install_id != first_service.install_id
    assert second_service.coordination_id == first_service.coordination_id
    assert status.state == ScheduleState.DISABLED


def test_legacy_install_id_is_migrated_to_stable_user_path(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "install-id").write_text(
        "legacy-id\n", encoding="utf-8"
    )
    stable_id = tmp_path / "user-data" / "install-id"
    service = ScheduleService(
        config_dir=config_dir,
        logs_dir=tmp_path / "logs",
        task_client=FakeTaskClient(),
        install_id_path=stable_id,
    )

    assert service.install_id == "legacy-id"
    assert stable_id.read_text(encoding="utf-8").strip() == "legacy-id"


def _external_migration_services(tmp_path):
    client = MultiTaskClient()
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_exe = source_root / "ippi-down.exe"
    target_exe = target_root / "ippi-down.exe"
    source_exe.parent.mkdir(parents=True)
    target_exe.parent.mkdir(parents=True)
    source_exe.write_bytes(b"source")
    target_exe.write_bytes(b"target")
    source = ScheduleService(
        config_dir=source_root / "config",
        logs_dir=source_root / "logs",
        task_namespace_id="source-instance",
        coordination_id="shared-user",
        task_client=client,
        executable=source_exe,
        app_root=source_root,
        now_provider=lambda: datetime(2026, 8, 3, 10, 0, tzinfo=JST),
    )
    target = ScheduleService(
        config_dir=target_root / "config",
        logs_dir=target_root / "logs",
        task_namespace_id="target-instance",
        coordination_id="shared-user",
        task_client=client,
        executable=target_exe,
        app_root=target_root,
        now_provider=lambda: datetime(2026, 8, 3, 10, 0, tzinfo=JST),
    )
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    config.save_paths.local = ".\\downloads"
    source.create_schedule(
        config,
        schedule_id="tunnel",
        name="トンネル工事",
    )
    return source, target, client, source_root, target_root


def test_external_preview_allows_verified_snapshot_when_task_is_missing(tmp_path):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    client.tasks.pop(source.task_name_for("tunnel"))

    candidates = target.preview_external_imports(source_root / "config")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.importable is True
    assert candidate.reason_code == "EXTERNAL_IMPORT_READY"
    assert candidate.enabled is True
    assert candidate.effective_save_path == (source_root / "downloads").resolve()
    assert candidate.storage_key == "S001"


def test_external_import_transfers_ownership_and_preserves_storage(tmp_path):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    candidate = target.preview_external_imports(source_root / "config")[0]
    old_task_name = source.task_name_for("tunnel")

    result = target.import_external_schedule(
        candidate.external_id,
        source_root / "config",
    )

    assert result.success is True
    assert result.status.enabled is True
    assert result.status.storage_key == "S001"
    assert old_task_name not in client.tasks
    target_task_name = target.task_name_for("tunnel")
    assert target_task_name in client.tasks
    target_entry = json.loads(
        target.registration_path.read_text(encoding="utf-8")
    )["registrations"]["tunnel"]
    assert target_entry["owner_instance_id"] == "target-instance"
    assert target_entry["lifecycle_state"] == "ACTIVE"
    assert target_entry["storage_key"] == "S001"
    source_entry = json.loads(
        source.registration_path.read_text(encoding="utf-8")
    )["registrations"]["tunnel"]
    assert source_entry["migration_status"] == "MIGRATED_OUT"
    assert source_entry["lifecycle_state"] == "MIGRATED_OUT"


def test_external_import_keeps_disabled_old_task_as_cleanup_warning(tmp_path):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    candidate = target.preview_external_imports(source_root / "config")[0]
    old_task_name = source.task_name_for("tunnel")
    client.fail_delete_for.add(old_task_name)

    result = target.import_external_schedule(
        candidate.external_id,
        source_root / "config",
    )

    assert result.success is True
    assert result.reason_code == "EXTERNAL_TASK_CLEANUP_PENDING"
    assert result.warnings
    assert old_task_name in client.tasks
    assert old_task_name in client.disabled
    assert target.task_name_for("tunnel") in client.tasks
    source_entry = json.loads(
        source.registration_path.read_text(encoding="utf-8")
    )["registrations"]["tunnel"]
    assert source_entry["migration_status"] == "MIGRATED_OUT"
    assert source_entry["external_task_cleanup"] == "PENDING"
    journal = json.loads(
        target.migration_journal_path.read_text(encoding="utf-8")
    )
    assert set(journal) == {
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
    assert journal["phase"] == "CLEANUP_PENDING"


def test_external_import_rolls_back_when_old_task_cannot_be_disabled(tmp_path):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    candidate = target.preview_external_imports(source_root / "config")[0]
    old_task_name = source.task_name_for("tunnel")
    client.fail_disable_for.add(old_task_name)

    with pytest.raises(ScheduleServiceError) as raised:
        target.import_external_schedule(
            candidate.external_id,
            source_root / "config",
        )

    assert raised.value.reason_code == "TASK_DISABLE_FAILED"
    assert target.get_schedule("tunnel") is None
    assert old_task_name in client.tasks
    source_entry = json.loads(
        source.registration_path.read_text(encoding="utf-8")
    )["registrations"]["tunnel"]
    assert "migration_status" not in source_entry


def test_external_preview_rejects_task_action_for_another_snapshot(tmp_path):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    old_task_name = source.task_name_for("tunnel")
    client.tasks[old_task_name] = client.tasks[old_task_name].replace(
        "--schedule-id tunnel",
        "--schedule-id another",
    )

    candidate = target.preview_external_imports(source_root / "config")[0]

    assert candidate.importable is False
    assert candidate.reason_code == "EXTERNAL_TASK_DEFINITION_MISMATCH"


def test_external_import_merges_history_once_by_run_id(tmp_path):
    source, target, _, source_root, _ = _external_migration_services(tmp_path)
    record = ScheduledRunRecord(
        schedule_id="tunnel",
        snapshot_id="old-snapshot",
        run_id="same-run",
        result="success",
    )
    source.ledger.append(record)
    target.ledger.append(record)
    candidate = target.preview_external_imports(source_root / "config")[0]

    result = target.import_external_schedule(
        candidate.external_id,
        source_root / "config",
    )

    assert result.history_imported == 0
    assert len(target.history("tunnel", limit=20)) == 1


def _write_crash_journal(target, source, candidate, phase):
    source_document = json.loads(
        source.registration_path.read_text(encoding="utf-8")
    )
    target_document = target.registration_store.read()
    target._write_migration_journal(
        {
            "schema_version": 1,
            "source_registry_path": str(source.registration_path),
            "schedule_id": "tunnel",
            "external_id": candidate.external_id,
            "old_task_name": source.task_name_for("tunnel"),
            "phase": phase,
            "old_task_enabled": True,
            "target_revision": target_document["revision"],
            "source_revision": source_document["revision"],
        }
    )


def _stage_import_target(source, target, source_root, *, enabled=False):
    config = source.get_registered_config("tunnel")
    assert config is not None
    config.schedule.enabled = False
    config.schedule.active_profile_id = None
    config.save_paths.local = str((source_root / "downloads").resolve())
    target.create_schedule(
        config,
        schedule_id="tunnel",
        name="トンネル工事",
        preserve_storage_identity=True,
    )
    if enabled:
        target.enable_schedule("tunnel")


def _reopen_migration_target(target, client, *, queue_status=None):
    return ScheduleService(
        config_dir=target.config_dir,
        logs_dir=target.logs_dir,
        task_namespace_id="target-instance",
        coordination_id="shared-user",
        task_client=client,
        executable=target.executable,
        app_root=target.app_root,
        now_provider=lambda: datetime(2026, 8, 3, 10, 0, tzinfo=JST),
        queue_status_provider=(
            queue_status if queue_status is not None else (lambda _id: None)
        ),
    )


@pytest.mark.parametrize(
    ("phase", "stage_target", "disable_old", "enable_target"),
    [
        ("PREPARED", False, False, False),
        ("TARGET_STAGED", True, False, False),
        ("OLD_DISABLED", True, True, False),
        ("TARGET_APPLIED", True, True, True),
    ],
)
def test_migration_journal_rolls_back_uncommitted_crash_phases(
    tmp_path,
    phase,
    stage_target,
    disable_old,
    enable_target,
):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    candidate = target.preview_external_imports(source_root / "config")[0]
    old_task_name = source.task_name_for("tunnel")
    if stage_target:
        _stage_import_target(
            source,
            target,
            source_root,
            enabled=enable_target,
        )
    if disable_old:
        client.set_enabled(old_task_name, False)
    _write_crash_journal(target, source, candidate, phase)

    reopened = _reopen_migration_target(target, client)

    assert reopened.get_schedule("tunnel") is None
    assert old_task_name in client.tasks
    assert old_task_name not in client.disabled
    assert not reopened.migration_journal_path.exists()
    assert reopened.migration_recovery_warning is None


@pytest.mark.parametrize("journal_phase", ["SOURCE_MIGRATED", "TARGET_APPLIED"])
def test_migration_journal_completes_committed_cleanup(tmp_path, journal_phase):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    candidate = target.preview_external_imports(source_root / "config")[0]
    old_task_name = source.task_name_for("tunnel")
    client.fail_delete_for.add(old_task_name)
    target.import_external_schedule(candidate.external_id, source_root / "config")
    journal = target._read_migration_journal()
    target._advance_migration_journal(journal, journal_phase)
    client.fail_delete_for.clear()

    reopened = _reopen_migration_target(target, client)

    assert reopened.get_schedule("tunnel") is not None
    assert old_task_name not in client.tasks
    assert not reopened.migration_journal_path.exists()
    assert reopened.migration_recovery_warning is None
    source_entry = json.loads(
        source.registration_path.read_text(encoding="utf-8")
    )["registrations"]["tunnel"]
    assert source_entry["external_task_cleanup"] == "COMPLETED"


def test_migration_journal_defers_recovery_while_queue_is_active(tmp_path):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    candidate = target.preview_external_imports(source_root / "config")[0]
    _write_crash_journal(target, source, candidate, "PREPARED")

    reopened = _reopen_migration_target(
        target,
        client,
        queue_status=lambda _id: SimpleNamespace(waiting=True, running=False),
    )

    assert reopened.migration_journal_path.exists()
    assert reopened.migration_recovery_reason_code == "MIGRATION_RECOVERY_DEFERRED"
    assert source.task_name_for("tunnel") in client.tasks


def test_migration_journal_keeps_evidence_when_rollback_is_incomplete(tmp_path):
    source, target, client, source_root, _ = _external_migration_services(tmp_path)
    candidate = target.preview_external_imports(source_root / "config")[0]
    _stage_import_target(source, target, source_root)
    old_task_name = source.task_name_for("tunnel")
    client.tasks.pop(old_task_name)
    _write_crash_journal(target, source, candidate, "TARGET_STAGED")

    reopened = _reopen_migration_target(target, client)

    assert reopened.migration_journal_path.exists()
    assert (
        reopened.migration_recovery_reason_code
        == "MIGRATION_ROLLBACK_INCOMPLETE"
    )
    assert reopened.get_schedule("tunnel") is not None


def test_old_enabled_process_schedule_requires_explicit_migration(tmp_path):
    logger_messages = []

    class Logger:
        def info(self, message):
            logger_messages.append(("info", message))

        def warning(self, message):
            logger_messages.append(("warning", message))

        def error(self, message):
            logger_messages.append(("error", message))

    manager = ConfigManager(str(tmp_path / "config.yaml"), Logger())
    config = manager._dict_to_config(
        {"schedule": {"enabled": True, "interval": "daily", "time": "09:00"}}
    )

    assert config.schedule.enabled is False
    assert config.schedule.backend == "legacy_process"
    assert config.schedule.requires_migration is True
    assert any("Windowsタスクへ移行" in message for _, message in logger_messages)


def test_v1_registration_is_atomically_migrated_as_default_without_task_rename(
    tmp_path,
):
    service = _service(tmp_path, MultiTaskClient())
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="07:30"))
    profile = service.profile_store.create(
        config,
        profile_id="legacy-snapshot",
        created_at=datetime(2026, 8, 3, tzinfo=JST),
    )
    legacy_task_name = r"\ippi-down\Download-legacy-install"
    legacy = {
        "schema_version": 1,
        "task_name": legacy_task_name,
        "profile_id": profile.profile_id,
        "profile_path": str(profile.path),
        "profile_fingerprint": profile.fingerprint,
        "registered_at": "2026-08-03T09:00:00+09:00",
        "schedule": ConfigManager()._config_to_dict(config)["schedule"],
        "command": str(service.executable),
        "arguments": ["--scheduled-run", "--config", str(profile.path)],
        "working_directory": str(tmp_path),
    }
    service.registration_path.parent.mkdir(parents=True, exist_ok=True)
    service.registration_path.write_text(
        json.dumps(legacy, ensure_ascii=False),
        encoding="utf-8",
    )

    migrated = service._read_registration()
    raw = json.loads(service.registration_path.read_text(encoding="utf-8"))

    assert raw["schema_version"] == 2
    assert raw["migrated_from"] == 1
    assert set(raw["registrations"]) == {"default"}
    assert raw["registrations"]["default"]["task_name"] == legacy_task_name
    assert raw["registrations"]["default"]["name"] == "既存の定期実行"
    assert migrated["profile_id"] == profile.profile_id


def test_failed_v1_registry_migration_preserves_original_bytes(tmp_path, monkeypatch):
    service = _service(tmp_path, MultiTaskClient())
    legacy = {
        "schema_version": 1,
        "task_name": service.task_name,
        "profile_id": "legacy-snapshot",
        "profile_path": str(tmp_path / "legacy.yaml"),
        "profile_fingerprint": "fingerprint",
        "schedule": {"enabled": True},
    }
    service.registration_path.parent.mkdir(parents=True)
    service.registration_path.write_text(json.dumps(legacy), encoding="utf-8")
    original = service.registration_path.read_bytes()

    def fail_write(_document):
        raise ScheduleServiceError("write failed", "REGISTRATION_METADATA_WRITE_FAILED")

    monkeypatch.setattr(service.registration_store, "_atomic_write", fail_write)

    with pytest.raises(ScheduleServiceError) as raised:
        service.get_registry()

    assert raised.value.reason_code == "REGISTRATION_METADATA_WRITE_FAILED"
    assert service.registration_path.read_bytes() == original


def test_multiple_schedules_use_stable_task_names_and_batch_status_query(tmp_path):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    default_config = AppConfig(schedule=ScheduleConfig(enabled=True, time="08:00"))
    second_config = AppConfig(schedule=ScheduleConfig(enabled=True, time="18:00"))
    second_config.search_conditions.koji_name = "橋梁"

    default_status = service.register(default_config)
    second_status = service.create_schedule(
        second_config,
        schedule_id="bridge",
        name="橋梁案件",
    )
    statuses = service.get_statuses()
    registry = service.get_registry()

    assert default_status.task_name == r"\ippi-down\Download-test-install"
    assert second_status.task_name == r"\ippi-down\Download-test-install-bridge"
    assert set(client.tasks) == {default_status.task_name, second_status.task_name}
    assert set(registry.registrations) == {"default", "bridge"}
    assert statuses["default"].state == ScheduleState.REGISTERED
    assert statuses["bridge"].state == ScheduleState.REGISTERED
    assert client.query_many_calls == 1
    assert "--schedule-id bridge" in client.tasks[second_status.task_name]


def test_batch_status_uses_one_ledger_lookup_for_all_schedules(
    tmp_path,
    monkeypatch,
):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    service.register(AppConfig(schedule=ScheduleConfig(enabled=True, time="08:00")))
    service.create_schedule(
        AppConfig(schedule=ScheduleConfig(enabled=True, time="18:00")),
        schedule_id="bridge",
        name="橋梁案件",
    )
    registrations = {
        schedule_id: service.get_schedule(schedule_id)
        for schedule_id in ("default", "bridge")
    }
    expected = {
        schedule_id: ScheduledRunRecord(
            schedule_id=schedule_id,
            snapshot_id=registration.snapshot_id,
            result="success",
            saved_count=index,
        )
        for index, (schedule_id, registration) in enumerate(
            registrations.items(),
            start=1,
        )
    }
    calls: list[tuple[str, ...]] = []

    def latest_many(schedule_ids):
        calls.append(tuple(schedule_ids))
        return expected

    def reject_individual_lookup(*_args, **_kwargs):
        raise AssertionError("get_statusesからlatestを個別に呼んではいけません")

    monkeypatch.setattr(service.ledger, "latest_many", latest_many)
    monkeypatch.setattr(service.ledger, "latest", reject_individual_lookup)

    statuses = service.get_statuses()

    assert len(calls) == 1
    assert set(calls[0]) == {"default", "bridge"}
    assert statuses["default"].saved_count == 1
    assert statuses["bridge"].saved_count == 2


def test_duplicate_is_disabled_and_id_crud_does_not_change_other_schedule(tmp_path):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    source = service.register(
        AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    )

    duplicated = service.duplicate_schedule(
        "default",
        schedule_id="copy",
        name="複製",
    )
    assert duplicated.state == ScheduleState.DISABLED
    assert duplicated.task_name not in client.tasks
    assert source.task_name in client.tasks

    enabled = service.enable_schedule("copy")
    assert enabled.state == ScheduleState.REGISTERED
    assert service.run_schedule_now("copy") is True
    assert ("run", duplicated.task_name) in client.calls

    disabled = service.disable_schedule("copy")
    assert disabled.state == ScheduleState.DISABLED
    assert duplicated.task_name not in client.tasks
    assert source.task_name in client.tasks

    service.ledger.append(
        ScheduledRunRecord(
            schedule_id="copy",
            snapshot_id=duplicated.snapshot_id,
            result="success",
        )
    )
    service.ledger.append(
        ScheduledRunRecord(
            schedule_id="default",
            snapshot_id=source.snapshot_id,
            result="failed",
        )
    )
    assert [item.schedule_id for item in service.history_for_schedule("copy")] == [
        "copy"
    ]

    assert service.delete_schedule("copy") is True
    assert service.get_schedule("copy") is None
    assert service.get_schedule("default") is not None


def test_stale_registry_revision_rejects_update_before_task_or_snapshot_change(
    tmp_path,
):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    service.create_schedule(config, schedule_id="one", name="One")
    stale_revision = service.get_registry().revision

    config.search_conditions.koji_name = "更新1"
    service.update_schedule(
        "one",
        config,
        expected_revision=stale_revision,
    )
    current = service.get_schedule("one")
    task_xml = client.tasks[current.task_name]
    snapshot_count = len(service.profile_store.list(schedule_id="one"))

    config.search_conditions.koji_name = "更新2"
    with pytest.raises(ScheduleServiceError) as raised:
        service.update_schedule(
            "one",
            config,
            expected_revision=stale_revision,
        )

    assert raised.value.reason_code == "REGISTRATION_CONFLICT"
    assert service.get_schedule("one").snapshot_id == current.snapshot_id
    assert client.tasks[current.task_name] == task_xml
    assert len(service.profile_store.list(schedule_id="one")) == snapshot_count


def test_failed_second_registration_preserves_first_registration(tmp_path):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    first = service.create_schedule(
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="first",
    )
    second_task = service.task_name_for("second")
    client.fail_for.add(second_task)

    with pytest.raises(ScheduleServiceError) as raised:
        service.create_schedule(
            AppConfig(schedule=ScheduleConfig(enabled=True, time="15:00")),
            schedule_id="second",
        )

    assert raised.value.reason_code == "TASK_REGISTER_FAILED"
    assert set(service.get_registry().registrations) == {"first"}
    assert client.tasks[first.task_name]
    assert second_task not in client.tasks
    assert service.profile_store.list(schedule_id="second") == []


def test_profile_store_recovers_only_expired_unowned_atomic_tmp(tmp_path):
    store = ScheduleProfileStore(tmp_path / "profiles")
    store.root.mkdir(parents=True)
    stale = store.root / ".ippi-profile-snapshot-p101-c1000-old.tmp"
    active = store.root / ".ippi-profile-snapshot-p202-c1000-active.tmp"
    fresh = store.root / ".ippi-profile-snapshot-p303-c9999-fresh.tmp"
    unknown = store.root / ".some-other-writer.tmp"
    for path in (stale, active, fresh, unknown):
        path.write_text("temporary", encoding="utf-8")

    removed = store.recover_stale_temporary_files(
        stale_after_seconds=60,
        now=10_000,
        process_alive=lambda pid: pid == 202,
    )

    assert removed == (stale,)
    assert not stale.exists()
    assert active.exists()
    assert fresh.exists()
    assert unknown.exists()


def test_profile_v2_records_owner_and_v1_condition_fingerprint_still_loads(tmp_path):
    store = ScheduleProfileStore(tmp_path / "profiles")
    config = AppConfig(schedule=ScheduleConfig(enabled=True, time="11:00"))
    profile = store.create(
        config,
        snapshot_id="snapshot-v2",
        schedule_id="schedule-a",
        display_name="案件A",
        created_at=datetime(2026, 8, 3, tzinfo=JST),
    )
    document = store.read(profile.path)
    metadata = document[PROFILE_METADATA_KEY]

    assert metadata["schema_version"] == PROFILE_SCHEMA_VERSION
    assert metadata["snapshot_id"] == "snapshot-v2"
    assert metadata["schedule_id"] == "schedule-a"
    assert metadata["display_name"] == "案件A"
    assert store.get("snapshot-v2").snapshot_id == "snapshot-v2"

    legacy_document = ConfigManager()._config_to_dict(config)
    legacy_document[PROFILE_METADATA_KEY] = {
        "schema_version": 1,
        "profile_id": "snapshot-v1",
        "fingerprint": calculate_condition_fingerprint(legacy_document),
        "created_at": "2026-08-03T09:00:00+09:00",
    }
    legacy_path = store.path_for("snapshot-v1")
    legacy_path.write_text(
        yaml.safe_dump(legacy_document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    assert store.get("snapshot-v1").schedule_id == "default"


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    [
        ("snapshot_id", "different-id", "PROFILE_ID_MISMATCH"),
        ("schedule_id", "different-owner", "PROFILE_INTEGRITY_MISMATCH"),
        ("display_name", "改ざん名", "PROFILE_INTEGRITY_MISMATCH"),
    ],
)
def test_profile_v2_rejects_tampered_identity_metadata(
    tmp_path,
    field,
    value,
    reason_code,
):
    store = ScheduleProfileStore(tmp_path / "profiles")
    profile = store.create(
        AppConfig(),
        snapshot_id="sealed-snapshot",
        schedule_id="owner-a",
        display_name="案件A",
    )
    document = yaml.safe_load(profile.path.read_text(encoding="utf-8"))
    document[PROFILE_METADATA_KEY][field] = value
    profile.path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ScheduleServiceError) as raised:
        store.read(profile.path)

    assert raised.value.reason_code == reason_code


def test_profile_v2_rejects_snapshot_filename_mismatch(tmp_path):
    store = ScheduleProfileStore(tmp_path / "profiles")
    profile = store.create(AppConfig(), snapshot_id="original-snapshot")
    renamed = store.path_for("renamed-snapshot")
    renamed.write_bytes(profile.path.read_bytes())

    with pytest.raises(ScheduleServiceError) as raised:
        store.read(renamed)

    assert raised.value.reason_code == "PROFILE_PATH_MISMATCH"


def test_profile_v2_without_new_integrity_fields_remains_readable(tmp_path):
    store = ScheduleProfileStore(tmp_path / "profiles")
    profile = store.create(
        AppConfig(),
        snapshot_id="rolling-v2",
        schedule_id="owner-a",
    )
    document = yaml.safe_load(profile.path.read_text(encoding="utf-8"))
    metadata = document[PROFILE_METADATA_KEY]
    metadata.pop("integrity_fingerprint")
    metadata.pop("condition_fingerprint")
    profile.path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    assert store.get("rolling-v2").schedule_id == "owner-a"


def test_schedule_names_are_unique_after_whitespace_and_case_normalisation(
    tmp_path,
):
    service = _service(tmp_path, MultiTaskClient())
    disabled = AppConfig(schedule=ScheduleConfig(enabled=False))
    service.create_schedule("A lpha", disabled, schedule_id="one")

    with pytest.raises(ScheduleServiceError) as duplicate:
        service.create_schedule(
            "alpha",
            AppConfig(schedule=ScheduleConfig(enabled=False)),
            schedule_id="two",
        )
    assert duplicate.value.reason_code == "SCHEDULE_NAME_DUPLICATE"

    renamed = service.update_schedule(
        "one",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        name=" ALPHA ",
    )
    assert renamed.name == "ALPHA"

    copied = service.duplicate_schedule("one", "Beta", schedule_id="copy")
    assert copied.enabled is False
    assert copied.name == "Beta"

    with pytest.raises(ScheduleServiceError) as too_long:
        service.create_schedule(
            "x" * 81,
            AppConfig(schedule=ScheduleConfig(enabled=False)),
        )
    assert too_long.value.reason_code == "SCHEDULE_NAME_INVALID"


def test_schedule_storage_keys_are_monotonic_and_names_do_not_move_folders(
    tmp_path,
):
    service = _service(tmp_path, MultiTaskClient())
    disabled = AppConfig(schedule=ScheduleConfig(enabled=False))

    first = service.create_schedule("道路/案件", disabled, schedule_id="one")
    second = service.create_schedule(
        "河川案件",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        schedule_id="two",
    )

    assert (first.storage_key, first.storage_folder) == (
        "S001",
        "S001_道路_案件",
    )
    assert (second.storage_key, second.storage_folder) == (
        "S002",
        "S002_河川案件",
    )
    service.delete_schedule("one")
    third = service.create_schedule(
        "橋梁案件",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        schedule_id="three",
    )
    assert third.storage_key == "S003"

    renamed = service.update_schedule(
        "two",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        name="名称変更後",
    )
    assert (renamed.storage_key, renamed.storage_folder) == (
        "S002",
        "S002_河川案件",
    )
    registered = service.get_registered_config("two")
    assert registered.save_paths.schedule_storage_key == "S002"
    assert registered.save_paths.schedule_storage_folder == "S002_河川案件"


def test_duplicate_schedule_receives_a_new_storage_identity(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    original = service.create_schedule(
        "原本",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        schedule_id="original",
    )

    copied = service.duplicate_schedule(
        "original",
        "複製",
        schedule_id="copy",
    )

    assert original.storage_key == "S001"
    assert copied.storage_key == "S002"
    assert copied.storage_folder == "S002_複製"


def test_explicit_storage_layout_migration_replaces_v3_snapshot_with_v4(
    tmp_path,
):
    service = _service(tmp_path, MultiTaskClient())
    config = AppConfig(schedule=ScheduleConfig(enabled=False))
    config.save_paths.layout_version = 3
    original = service.create_schedule(
        "旧保存構成",
        config,
        schedule_id="layout-v3",
    )
    original_config = service.get_registered_config("layout-v3")

    result = service.migrate_storage_layout_v4()
    migrated = service.get_schedule("layout-v3")
    migrated_config = service.get_registered_config("layout-v3")

    assert original_config.save_paths.layout_version == 3
    assert result["migrated"] == ("layout-v3",)
    assert result["failed"] == {}
    assert migrated.snapshot_id != original.snapshot_id
    assert migrated_config.save_paths.layout_version == 4
    assert migrated.storage_key == original.storage_key
    assert migrated.storage_folder == original.storage_folder


def test_legacy_snapshot_without_layout_version_keeps_original_save_root(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    legacy_config = AppConfig(schedule=ScheduleConfig(enabled=False))
    legacy_document = ConfigManager()._config_to_dict(legacy_config)
    legacy_document["save_paths"] = {"local": str(tmp_path / "legacy-root")}
    legacy_document[PROFILE_METADATA_KEY] = {
        "schema_version": 1,
        "profile_id": "legacy-layout",
        "fingerprint": calculate_condition_fingerprint(legacy_document),
        "created_at": "2026-08-03T09:00:00+09:00",
    }
    legacy_path = service.profile_store.path_for("legacy-layout")
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        yaml.safe_dump(legacy_document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    legacy_registry = {
        "schema_version": 1,
        "task_name": service.task_name,
        "profile_id": "legacy-layout",
        "profile_path": str(legacy_path),
        "profile_fingerprint": calculate_condition_fingerprint(legacy_document),
        "registered_at": "2026-08-03T09:00:00+09:00",
        "schedule": legacy_document["schedule"],
        "command": str(service.executable),
        "arguments": ["--scheduled-run", "--config", str(legacy_path)],
        "working_directory": str(tmp_path),
    }
    service.registration_path.parent.mkdir(parents=True, exist_ok=True)
    service.registration_path.write_text(
        json.dumps(legacy_registry, ensure_ascii=False),
        encoding="utf-8",
    )
    service.get_registry()

    update = AppConfig(schedule=ScheduleConfig(enabled=False))
    update.save_paths.local = str(tmp_path / "new-root")
    service.update_schedule("default", update, name="名称変更")
    registered = service.get_registered_config("default")

    assert registered.save_paths.layout_version == 2
    assert registered.save_paths.local == str(tmp_path / "legacy-root")
    assert registered.save_paths.schedule_storage_key == ""


def test_profile_fingerprint_rejects_storage_folder_tampering(tmp_path):
    store = ScheduleProfileStore(tmp_path / "profiles")
    config = AppConfig(schedule=ScheduleConfig(enabled=False))
    config.save_paths.schedule_storage_key = "S001"
    config.save_paths.schedule_storage_folder = "S001_案件A"
    profile = store.create(
        config,
        snapshot_id="storage-sealed",
        schedule_id="owner-a",
        display_name="案件A",
    )
    document = yaml.safe_load(profile.path.read_text(encoding="utf-8"))
    document["save_paths"]["schedule_storage_folder"] = "S001_改変"
    profile.path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ScheduleServiceError) as raised:
        store.read(profile.path)

    assert raised.value.reason_code == "PROFILE_FINGERPRINT_MISMATCH"


def test_schedule_timestamps_preserve_creation_and_advance_update(tmp_path):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    clock = [datetime(2026, 8, 3, 9, 0, tzinfo=JST)]
    service.now_provider = lambda: clock[0]
    service.create_schedule(
        "案件A",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="one",
    )
    first = service.get_schedule("one")

    clock[0] += timedelta(hours=2)
    updated_config = AppConfig(schedule=ScheduleConfig(enabled=True))
    updated_config.search_conditions.koji_name = "更新"
    service.update_schedule("one", updated_config)
    updated = service.get_schedule("one")

    assert first.created_at == clock[0] - timedelta(hours=2)
    assert updated.created_at == first.created_at
    assert updated.updated_at == clock[0]


def test_condition_duplicate_warning_ignores_schedule_timing(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    first_config = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    second_config = AppConfig(schedule=ScheduleConfig(enabled=True, time="18:00"))
    service.create_schedule("午前", first_config, schedule_id="morning")
    second = service.create_schedule("夕方", second_config, schedule_id="evening")

    assert second.condition_duplicate_schedule_ids == ("morning",)
    assert service.find_condition_duplicates("morning") == ("evening",)
    assert (
        service.get_schedule("morning").condition_fingerprint
        == service.get_schedule("evening").condition_fingerprint
    )

    second_config.search_conditions.koji_name = "別条件"
    service.update_schedule("evening", second_config)
    assert service.find_condition_duplicates("morning") == ()


def test_running_update_retains_old_snapshot_until_status_cleanup(tmp_path):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    service.create_schedule("案件A", config, schedule_id="one")
    previous = service.get_schedule("one")
    client.running.add(previous.task_name)

    config.search_conditions.koji_name = "更新後"
    service.update_schedule("one", config)
    assert previous.snapshot_path.exists()
    assert previous.snapshot_id in service.registration_store.read()[
        "registrations"
    ]["one"]["retained_snapshot_ids"]

    client.running.remove(previous.task_name)
    service.get_schedule_status("one")
    assert not previous.snapshot_path.exists()
    assert service.registration_store.read()["registrations"]["one"][
        "retained_snapshot_ids"
    ] == []


def test_fifo_ticket_keeps_retained_snapshot_until_dispatch_completes(tmp_path):
    client = MultiTaskClient()
    tickets = []
    service = _service(
        tmp_path,
        client,
        queue_ticket_provider=lambda: list(tickets),
    )
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    service.create_schedule("案件A", config, schedule_id="one")
    previous = service.get_schedule("one")
    client.running.add(previous.task_name)

    config.search_conditions.koji_name = "更新後"
    service.update_schedule("one", config)
    client.running.remove(previous.task_name)
    tickets.append(
        SimpleNamespace(state="queued", snapshot_id=previous.snapshot_id)
    )

    assert service.cleanup_retained_snapshots(schedule_id="one") == ()
    assert previous.snapshot_path.exists()

    tickets.clear()
    assert service.cleanup_retained_snapshots(schedule_id="one") == (
        previous.snapshot_id,
    )
    assert not previous.snapshot_path.exists()


def test_capture_protects_old_snapshot_until_success_is_released(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    service.create_schedule("案件A", config, schedule_id="one")
    previous = service.get_schedule("one")
    backup = service.capture_registration_state("one")

    config.search_conditions.koji_name = "更新後"
    service.update_schedule("one", config)
    assert previous.snapshot_path.exists()

    service.release_registration_state(backup)
    assert not previous.snapshot_path.exists()


def test_delete_during_run_retains_snapshot_then_cleans_without_losing_history(
    tmp_path,
):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    service.create_schedule(
        "案件A",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="one",
    )
    previous = service.get_schedule("one")
    service.ledger.append(
        ScheduledRunRecord(
            schedule_id="one",
            snapshot_id=previous.snapshot_id,
            result="success",
        )
    )
    client.running.add(previous.task_name)

    service.delete_schedule("one")
    assert previous.snapshot_path.exists()
    assert service.registration_store.read()["retained_snapshots"]

    client.running.remove(previous.task_name)
    assert service.get_statuses() == {}
    assert not previous.snapshot_path.exists()
    assert service.registration_store.read()["retained_snapshots"] == []
    assert service.history_for_schedule("one")[0].result == "success"


def test_completed_run_cleanup_keeps_snapshot_while_new_run_holds_schedule_mutex(
    tmp_path,
):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    service.create_schedule("案件A", config, schedule_id="one")
    previous = service.get_schedule("one")
    client.running.add(previous.task_name)
    config.search_conditions.koji_name = "更新後"
    service.update_schedule("one", config)
    client.running.remove(previous.task_name)

    guard = make_schedule_run_guard("one")
    with guard.try_acquire() as acquired:
        assert acquired is True
        assert service.finalize_scheduled_run(
            "one", previous.snapshot_id
        ) == ()
        assert previous.snapshot_path.exists()

    assert service.finalize_scheduled_run("one", previous.snapshot_id) == (
        previous.snapshot_id,
    )
    assert not previous.snapshot_path.exists()


def test_enable_revalidates_settings_saved_while_disabled(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    service.create_schedule(
        "未完成",
        AppConfig(schedule=ScheduleConfig(enabled=False, time="invalid")),
        schedule_id="one",
    )

    with pytest.raises(ScheduleServiceError) as raised:
        service.enable_schedule("one")

    assert raised.value.reason_code == "CONFIG_INVALID"


def test_repair_updates_stale_snapshot_path_in_registry(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    service.create_schedule(
        "案件A",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="one",
    )
    registration = service.get_schedule("one")
    document = service.registration_store.read()
    document["registrations"]["one"]["snapshot_path"] = str(
        tmp_path / "moved" / "missing.yaml"
    )
    service.registration_store.write(document)

    service.repair_schedule("one")

    repaired = service.get_schedule("one")
    assert repaired.snapshot_path == registration.snapshot_path
    assert str(registration.snapshot_path) in repaired.arguments


def test_recreated_schedule_id_does_not_inherit_prior_generation_failure(tmp_path):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    clock = [datetime(2026, 8, 3, 9, 0, tzinfo=JST)]
    service.now_provider = lambda: clock[0]
    first = service.register(AppConfig(schedule=ScheduleConfig(enabled=True)))
    service.ledger.append(
        ScheduledRunRecord(
            # schedule_idのない旧JSONLもfrom_dictではdefaultへ移行される。
            profile_id=first.snapshot_id,
            result="failed",
            failed_count=1,
            exit_code=2,
            finished_at=clock[0] + timedelta(minutes=5),
        )
    )
    service.unregister()

    clock[0] += timedelta(days=1)
    second = service.register(AppConfig(schedule=ScheduleConfig(enabled=True)))
    status = service.get_status()

    assert second.snapshot_id != first.snapshot_id
    assert status.state == ScheduleState.REGISTERED
    assert status.last_result is None
    assert service.history_for_schedule("default")[0].result == "failed"


def test_stale_task_result_before_registration_update_is_ignored(tmp_path):
    client = FakeTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    service.register(config)
    client.last_run = datetime(2026, 8, 3, 9, 0, tzinfo=JST)
    client.last_result = 3

    status = service.get_status(config)

    assert status.state == ScheduleState.REGISTERED
    assert status.reason_code is None


def test_public_id_apis_and_history_keep_legacy_call_forms(tmp_path):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    default_config = AppConfig(schedule=ScheduleConfig(enabled=True))
    default_status = service.register(default_config)
    other_status = service.create_schedule(
        "別案件",
        AppConfig(schedule=ScheduleConfig(enabled=True, time="18:00")),
        schedule_id="other",
    )
    service.ledger.append(
        ScheduledRunRecord(
            schedule_id="default",
            snapshot_id=default_status.snapshot_id,
            result="success",
        )
    )
    service.ledger.append(
        ScheduledRunRecord(
            schedule_id="other",
            snapshot_id=other_status.snapshot_id,
            result="failed",
        )
    )

    assert service.run_now("other") is True
    assert service.get_status("other").schedule_id == "other"
    assert service.get_status(default_config).schedule_id == "default"
    assert [item.schedule_id for item in service.history("other")] == ["other"]
    assert len(service.history(1)) == 1
    assert len(service.history(schedule_id="default", limit=20)) == 1


def test_schedule_status_queue_fields_have_backward_compatible_defaults():
    status = ScheduleRegistrationStatus()

    assert status.queued is False
    assert status.queue_waiting is False
    assert status.queue_position is None
    assert status.queue_total == 0


def test_schedule_ids_are_case_insensitively_unique_before_side_effects(tmp_path):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    service.create_schedule(
        "道路",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="Road",
    )
    tasks_before = dict(client.tasks)
    profiles_before = service.profile_store.list()

    with pytest.raises(ScheduleServiceError) as raised:
        service.create_schedule(
            "橋梁",
            AppConfig(schedule=ScheduleConfig(enabled=True)),
            schedule_id="road",
        )

    assert raised.value.reason_code == "SCHEDULE_ALREADY_EXISTS"
    assert client.tasks == tasks_before
    assert service.profile_store.list() == profiles_before


def test_failed_task_rollback_is_reported_and_keeps_repair_snapshot(
    tmp_path,
    monkeypatch,
):
    client = MultiTaskClient()
    service = _service(tmp_path, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    service.create_schedule("案件A", config, schedule_id="one")
    previous = service.get_schedule("one")
    previous_xml = client.tasks[previous.task_name]
    create_count = 0

    def create_then_fail_restore(task_name, xml):
        nonlocal create_count
        create_count += 1
        if create_count > 1:
            raise ScheduleServiceError("復元失敗", "TASK_REGISTER_FAILED")
        client.tasks[task_name] = xml

    def fail_registry_write(*_args, **_kwargs):
        raise ScheduleServiceError(
            "台帳更新失敗",
            "REGISTRATION_METADATA_WRITE_FAILED",
        )

    monkeypatch.setattr(client, "create_or_update", create_then_fail_restore)
    monkeypatch.setattr(service, "_put_registration", fail_registry_write)
    config.search_conditions.koji_name = "更新後"

    with pytest.raises(ScheduleServiceError) as raised:
        service.update_schedule("one", config)

    assert raised.value.reason_code == "REGISTRATION_ROLLBACK_FAILED"
    assert service.get_schedule("one").snapshot_id == previous.snapshot_id
    assert client.tasks[previous.task_name] != previous_xml
    # 新taskが参照する可能性があるため、新snapshotを消してはならない。
    assert len(service.profile_store.list(schedule_id="one")) == 2


def test_public_status_prefers_fifo_waiting_over_task_scheduler_running(tmp_path):
    client = MultiTaskClient()
    service = _service(
        tmp_path,
        client,
        queue_status_provider=lambda schedule_id: SimpleNamespace(
            schedule_id=schedule_id,
            waiting=True,
            position=2,
            total_waiting=3,
        ),
    )
    registered = service.create_schedule(
        "案件A",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="one",
    )
    # FIFO待機中もWindows Task Scheduler上のprocessはrunningになる。
    client.running.add(registered.task_name)

    status = service.get_status("one")

    assert status.state == ScheduleState.QUEUED
    assert status.running is True
    assert status.queued is True
    assert status.queue_waiting is True
    assert status.queue_position == 2
    assert status.queue_total == 3


def test_public_status_uses_dispatcher_ticket_as_running_source(tmp_path):
    client = MultiTaskClient()
    service = _service(
        tmp_path,
        client,
        queue_status_provider=lambda schedule_id: SimpleNamespace(
            schedule_id=schedule_id,
            waiting=False,
            running=True,
            position=None,
            total_waiting=0,
        ),
    )
    service.create_schedule(
        "案件A",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="one",
    )

    status = service.get_status("one")

    assert status.state == ScheduleState.RUNNING
    assert status.running is True
    assert status.queue_waiting is False
    assert status.queue_position is None


def test_public_status_exposes_retry_waiting_state(tmp_path):
    client = MultiTaskClient()
    service = _service(
        tmp_path,
        client,
        queue_status_provider=lambda schedule_id: SimpleNamespace(
            schedule_id=schedule_id,
            waiting=False,
            running=True,
            retry_waiting=True,
            position=None,
            total_waiting=0,
        ),
    )
    service.create_schedule(
        "案件A",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="one",
    )

    status = service.get_status("one")

    assert status.state == ScheduleState.RETRY_WAITING
    assert status.running is True
    assert status.retry_waiting is True


def test_public_status_keeps_repair_priority_while_exposing_queue_fields(tmp_path):
    client = MultiTaskClient()
    service = _service(
        tmp_path,
        client,
        queue_status_provider=lambda _schedule_id: {
            "waiting": True,
            "position": 1,
            "total_waiting": 1,
        },
    )
    registered = service.create_schedule(
        "案件A",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="one",
    )
    client.tasks.pop(registered.task_name)

    status = service.get_status("one")

    assert status.state == ScheduleState.REPAIR_REQUIRED
    assert status.queue_waiting is True
    assert status.queue_position == 1
    assert status.queue_total == 1


def test_public_statuses_isolate_queue_provider_failure_per_schedule(tmp_path):
    client = MultiTaskClient()
    calls: list[str] = []

    def queue_status(schedule_id):
        calls.append(schedule_id)
        if schedule_id == "second":
            raise RuntimeError("queue unavailable")
        return SimpleNamespace(waiting=True, position=1, total_waiting=1)

    service = _service(
        tmp_path,
        client,
        queue_status_provider=queue_status,
    )
    service.create_schedule(
        "案件A",
        AppConfig(schedule=ScheduleConfig(enabled=True)),
        schedule_id="first",
    )
    service.create_schedule(
        "案件B",
        AppConfig(schedule=ScheduleConfig(enabled=True, time="18:00")),
        schedule_id="second",
    )

    statuses = service.get_statuses()

    assert calls == ["first", "second"]
    assert statuses["first"].state == ScheduleState.QUEUED
    assert statuses["first"].queue_waiting is True
    assert statuses["second"].state == ScheduleState.REGISTERED
    assert statuses["second"].queue_waiting is False
    assert statuses["second"].queue_position is None


def test_valid_disabled_schedule_is_disabled_when_windows_task_is_absent(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    service.create_schedule(
        "無効案件",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        schedule_id="one",
    )

    single = service.get_schedule_status("one")
    batch = service.get_statuses()["one"]

    assert single.state == ScheduleState.DISABLED
    assert batch.state == ScheduleState.DISABLED
    assert single.reason_code is None
    assert single.registered is False


@pytest.mark.parametrize(
    ("damage", "reason_code"),
    [
        ("snapshot_missing", "PROFILE_NOT_FOUND"),
        ("snapshot_tampered", "PROFILE_FINGERPRINT_MISMATCH"),
        ("snapshot_path", "PROFILE_PATH_MISMATCH"),
        ("registry_fingerprint", "PROFILE_FINGERPRINT_MISMATCH"),
        ("schedule_metadata", "REGISTRATION_METADATA_INVALID"),
        ("command_missing", "EXECUTABLE_NOT_FOUND"),
    ],
)
def test_disabled_schedule_prioritises_definition_damage_over_disabled(
    tmp_path,
    damage,
    reason_code,
):
    service = _service(tmp_path, MultiTaskClient())
    service.create_schedule(
        "無効案件",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        schedule_id="one",
    )
    registration = service.get_schedule("one")
    document = service.registration_store.read()
    entry = document["registrations"]["one"]

    if damage == "snapshot_missing":
        registration.snapshot_path.unlink()
    elif damage == "snapshot_tampered":
        snapshot = yaml.safe_load(
            registration.snapshot_path.read_text(encoding="utf-8")
        )
        snapshot["search_conditions"]["koji_name"] = "改ざん"
        registration.snapshot_path.write_text(
            yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    elif damage == "snapshot_path":
        entry["snapshot_path"] = str(tmp_path / "old" / "missing.yaml")
        service.registration_store.write(document)
    elif damage == "registry_fingerprint":
        entry["snapshot_fingerprint"] = "0" * 64
        service.registration_store.write(document)
    elif damage == "schedule_metadata":
        entry["schedule"] = "broken"
        service.registration_store.write(document)
    elif damage == "command_missing":
        entry["command"] = str(tmp_path / "missing.exe")
        service.registration_store.write(document)

    single = service.get_schedule_status("one")
    batch = service.get_statuses()["one"]

    assert single.state == ScheduleState.REPAIR_REQUIRED
    assert batch.state == ScheduleState.REPAIR_REQUIRED
    assert single.reason_code == reason_code
    assert batch.reason_code == reason_code
    assert single.registered is False


def test_disabled_schedule_rejects_snapshot_owned_by_another_schedule(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    disabled = AppConfig(schedule=ScheduleConfig(enabled=False))
    service.create_schedule("案件A", disabled, schedule_id="one")
    service.create_schedule(
        "案件B",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        schedule_id="two",
    )
    other = service.get_schedule("two")
    document = service.registration_store.read()
    entry = document["registrations"]["one"]
    entry["snapshot_id"] = other.snapshot_id
    entry["snapshot_path"] = str(other.snapshot_path)
    entry["snapshot_fingerprint"] = other.snapshot_fingerprint
    service.registration_store.write(document)

    status = service.get_schedule_status("one")

    assert status.state == ScheduleState.REPAIR_REQUIRED
    assert status.reason_code == "PROFILE_SCHEDULE_MISMATCH"


def test_disabled_source_registration_checks_script_exists(tmp_path):
    service = _service(tmp_path, MultiTaskClient())
    service.create_schedule(
        "ソース版",
        AppConfig(schedule=ScheduleConfig(enabled=False)),
        schedule_id="one",
    )
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    pythonw = scripts / "pythonw.exe"
    pythonw.write_bytes(b"stub")
    pythonw.with_name("python.exe").write_bytes(b"stub")
    service.python_runner = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0,
        stdout="",
        stderr="",
    )
    document = service.registration_store.read()
    entry = document["registrations"]["one"]
    entry["command"] = str(pythonw)
    entry["arguments"] = [str(tmp_path / "src" / "missing-main.py")]
    service.registration_store.write(document)

    status = service.get_schedule_status("one")

    assert status.state == ScheduleState.REPAIR_REQUIRED
    assert status.reason_code == "SCRIPT_NOT_FOUND"
