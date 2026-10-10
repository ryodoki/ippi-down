# -*- coding: utf-8 -*-

"""mainの非GUI引数と設定スナップショット読込テスト。"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

import src.main as main_module
from src.app.headless import HeadlessExitCode
from src.app.run_queue import RunQueue, RunQueueError
from src.app.run_result import RunResult
from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig
from src.models.download_result import RunOutcome
from src.scheduler.ledger import ScheduleRunLedger
from src.scheduler.installation import InstallationLocationStore
from src.scheduler.profile import (
    ScheduleProfileStore,
    calculate_profile_fingerprint,
)
from src.storage.layout import RunKind


@pytest.fixture(autouse=True)
def _isolated_installation_root(tmp_path, monkeypatch):
    """CLI単体テストを開発端末の実配置台帳から分離する。"""

    app_root = tmp_path / "app-root"
    app_root.mkdir()
    monkeypatch.setattr(main_module, "get_base_path", lambda: app_root)


def test_scheduled_notification_runs_once_after_history_sink(monkeypatch):
    config = AppConfig()
    config.schedule.notification_policy = "all_results"
    order = []
    notifier = Mock()
    notifier.notify.side_effect = lambda record, policy: (
        order.append(("notify", record.run_id, policy))
        or SimpleNamespace(
            status=SimpleNamespace(value="submitted"),
            reason_code="NOTIFICATION_SUBMITTED",
            elapsed_seconds=0.01,
        )
    )
    monkeypatch.setattr(
        main_module, "ScheduledRunNotifier", lambda: notifier
    )
    monkeypatch.setattr(
        main_module,
        "make_schedule_record_sink",
        lambda _path: lambda record: order.append(("history", record.run_id)),
    )
    monkeypatch.setattr(
        main_module,
        "run_scheduled_download",
        lambda *_args, **_kwargs: RunResult(
            success=True,
            message="完了",
            outcome=RunOutcome.SUCCESS,
        ),
    )

    exit_code = main_module._execute_cli_mode(
        config,
        Mock(),
        scheduled=True,
        profile_id="snapshot-a",
        schedule_id="schedule-a",
        snapshot_id="snapshot-a",
        run_id="run-a",
        use_waiting_queue=False,
        guard_already_acquired=True,
    )

    assert exit_code == HeadlessExitCode.SUCCESS
    assert order == [
        ("history", "run-a"),
        ("notify", "run-a", "all_results"),
    ]
    notifier.notify.assert_called_once()


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class _UnavailableGuard:
    @contextmanager
    def try_acquire(self):
        yield False


def test_scheduled_run_requires_config_and_records_reason(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("PPI_SCHEDULED_AT", raising=False)
    history_path = tmp_path / "schedule-runs.jsonl"
    monkeypatch.setattr(
        main_module,
        "get_logs_path",
        lambda name="app.log": tmp_path / name,
    )
    monkeypatch.setattr(
        main_module,
        "get_default_run_queue",
        lambda: RunQueue(tmp_path / "run-queue"),
    )

    exit_code = main_module.main(["--scheduled-run"])

    assert exit_code == HeadlessExitCode.CONFIG_INVALID
    record = ScheduleRunLedger(history_path).latest()
    assert record is not None
    assert record.reason_code == "CONFIG_PATH_REQUIRED"
    assert record.exit_code == 3
    assert record.scheduled_at is not None


def test_retired_installation_is_blocked_before_config_load(tmp_path, monkeypatch):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    store = InstallationLocationStore(
        old_root / "config" / "install-location.json"
    )
    store.write_retired("install-a", old_root, new_root)
    monkeypatch.setattr(main_module, "get_base_path", lambda: old_root)
    loader = Mock()
    startup_error = Mock()
    monkeypatch.setattr(main_module, "_load_runtime_config", loader)
    monkeypatch.setattr(main_module, "_show_startup_error", startup_error)

    exit_code = main_module.main([])

    assert exit_code == HeadlessExitCode.CONFIG_INVALID
    loader.assert_not_called()
    assert "移行済み" in startup_error.call_args.args[0]


def test_headless_moved_installation_requires_gui_confirmation(
    tmp_path,
    monkeypatch,
):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    InstallationLocationStore(
        new_root / "config" / "install-location.json"
    ).write("install-a", old_root)
    monkeypatch.setattr(main_module, "get_base_path", lambda: new_root)

    reason = main_module._installation_startup_block_reason(headless=True)

    assert reason is not None
    assert reason[0] == "INSTALLATION_PATH_CHANGED"


def test_headless_partial_relocation_is_blocked_without_location_marker(
    tmp_path,
    monkeypatch,
):
    from src.scheduler import service as service_module

    current_root = tmp_path / "current"
    current_root.mkdir()
    monkeypatch.setattr(main_module, "get_base_path", lambda: current_root)
    fake_service = Mock()
    fake_service.preview_installation_relocation.return_value = SimpleNamespace(
        required=True,
        reason_code="INSTALLATION_PATH_CHANGED",
        blocked_reason="",
    )
    constructor = Mock(return_value=fake_service)
    monkeypatch.setattr(service_module, "ScheduleService", constructor)

    reason = main_module._installation_startup_block_reason(headless=True)

    assert reason is not None
    assert reason[0] == "INSTALLATION_PATH_CHANGED"
    assert "GUI" in reason[1]
    constructor.assert_called_once()


def test_scheduled_run_loads_snapshot_profile_and_returns_zero(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("PPI_SCHEDULED_AT", raising=False)
    snapshot = tmp_path / "profile.yaml"
    data = ConfigManager()._config_to_dict(AppConfig())
    data["_schedule_profile"] = {
        "schema_version": 1,
        "profile_id": "profile-abc",
        "fingerprint": calculate_profile_fingerprint(data),
        "created_at": "2026-08-03T09:00:00+09:00",
    }
    snapshot.write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )
    history_path = tmp_path / "schedule-runs.jsonl"
    monkeypatch.setattr(
        main_module,
        "get_logs_path",
        lambda name="app.log": tmp_path / name,
    )
    monkeypatch.setattr(
        main_module,
        "get_default_run_queue",
        lambda: RunQueue(tmp_path / "run-queue"),
    )
    monkeypatch.setattr(
        main_module,
        "run_scheduled_download",
        lambda *args, **kwargs: RunResult(
            success=False,
            message="該当なし",
            outcome=RunOutcome.NO_MATCH,
        ),
    )
    finalizer = Mock()
    monkeypatch.setattr(
        main_module,
        "_finalize_scheduled_snapshot",
        finalizer,
    )

    exit_code = main_module.main(
        ["--scheduled-run", "--config", str(snapshot)]
    )

    assert exit_code == HeadlessExitCode.SUCCESS
    record = ScheduleRunLedger(history_path).latest()
    assert record is not None
    assert record.profile_id == "profile-abc"
    assert record.schedule_id == "default"
    assert record.snapshot_id == "profile-abc"
    assert record.run_id
    assert record.trigger_kind == "windows_task"
    assert record.display_name == "既存の定期実行"
    assert record.queue_wait_seconds >= 0
    assert record.result == "no_match"
    assert record.exit_code == 0
    assert record.scheduled_at is not None
    assert finalizer.call_args.kwargs == {
        "schedule_id": "default",
        "snapshot_id": "profile-abc",
    }


def test_run_once_partial_result_returns_two(monkeypatch):
    config = AppConfig()
    captured = {}
    monkeypatch.setattr(
        main_module,
        "_load_runtime_config",
        lambda path, **kwargs: (object(), config, "manual"),
    )

    def runner(*args, **kwargs):
        captured.update(kwargs)
        return RunResult(
            success=True,
            message="一部失敗",
            outcome=RunOutcome.PARTIAL,
        )

    monkeypatch.setattr(
        main_module,
        "run_scheduled_download",
        runner,
    )

    assert main_module.main(["--run-once"]) == 2
    assert captured["run_kind"] is RunKind.MANUAL


def test_malformed_nested_snapshot_returns_config_error(
    tmp_path,
    monkeypatch,
):
    snapshot = tmp_path / "malformed.yaml"
    snapshot.write_text(
        "target_urls:\n  - https://example.test\nsearch_conditions: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        main_module,
        "get_logs_path",
        lambda name="app.log": tmp_path / name,
    )

    assert main_module.main(
        ["--scheduled-run", "--config", str(snapshot)]
    ) == HeadlessExitCode.CONFIG_INVALID


def test_gui_invalid_existing_config_is_reported_before_startup(monkeypatch):
    startup_error = Mock()
    monkeypatch.setattr(
        main_module,
        "_load_runtime_config",
        Mock(
            side_effect=main_module._RuntimeConfigError(
                "設定ファイルが不正です",
                "CONFIG_INVALID",
            )
        ),
    )
    monkeypatch.setattr(main_module, "_show_startup_error", startup_error)

    assert main_module.main([]) == HeadlessExitCode.CONFIG_INVALID
    startup_error.assert_called_once_with("設定ファイルが不正です")


def test_modified_snapshot_fingerprint_is_rejected(
    tmp_path,
    monkeypatch,
):
    snapshot = tmp_path / "modified.yaml"
    data = ConfigManager()._config_to_dict(AppConfig())
    data["_schedule_profile"] = {
        "schema_version": 1,
        "profile_id": "profile-modified",
        "fingerprint": calculate_profile_fingerprint(data),
        "created_at": "2026-08-03T09:00:00+09:00",
    }
    data["search_conditions"]["koji_name"] = "登録後に変更"
    snapshot.write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )
    monkeypatch.setattr(
        main_module,
        "get_logs_path",
        lambda name="app.log": tmp_path / name,
    )

    assert main_module.main(
        ["--scheduled-run", "--config", str(snapshot)]
    ) == HeadlessExitCode.CONFIG_INVALID
    record = ScheduleRunLedger(
        tmp_path / "schedule-runs.jsonl"
    ).latest()
    assert record is not None
    assert record.reason_code == "PROFILE_FINGERPRINT_MISMATCH"


def test_background_is_deprecated_one_shot_alias(monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(
        main_module,
        "_load_runtime_config",
        lambda path, **kwargs: (object(), config, "manual"),
    )
    monkeypatch.setattr(
        main_module,
        "run_scheduled_download",
        lambda *args, **kwargs: RunResult(
            success=True,
            message="完了",
            outcome=RunOutcome.SUCCESS,
        ),
    )

    assert main_module.main(["--background"]) == 0


def test_v2_snapshot_schedule_id_is_validated_and_propagated(
    tmp_path,
    monkeypatch,
):
    profile = ScheduleProfileStore(tmp_path).create(
        AppConfig(),
        snapshot_id="snapshot-a",
        schedule_id="schedule-a",
        display_name="東北道路",
    )
    captured = {}
    monkeypatch.setattr(
        main_module,
        "_run_cli_mode",
        lambda config, logger, **kwargs: captured.update(kwargs) or 0,
    )

    assert main_module.main(
        [
            "--scheduled-run",
            "--config",
            str(profile.path),
            "--schedule-id",
            "schedule-a",
        ]
    ) == 0
    assert captured["schedule_id"] == "schedule-a"
    assert captured["snapshot_id"] == "snapshot-a"
    assert captured["profile_id"] == "snapshot-a"
    assert captured["trigger_kind"] == "windows_task"
    assert captured["display_name"] == "東北道路"
    assert captured["run_id"]


def test_v2_snapshot_rejects_task_schedule_id_mismatch(
    tmp_path,
    monkeypatch,
):
    profile = ScheduleProfileStore(tmp_path).create(
        AppConfig(),
        snapshot_id="snapshot-a",
        schedule_id="schedule-a",
    )
    monkeypatch.setattr(
        main_module,
        "get_logs_path",
        lambda name="app.log": tmp_path / name,
    )
    runner = Mock()
    monkeypatch.setattr(main_module, "run_scheduled_download", runner)

    exit_code = main_module.main(
        [
            "--scheduled-run",
            "--config",
            str(profile.path),
            "--schedule-id",
            "schedule-b",
        ]
    )

    assert exit_code == HeadlessExitCode.CONFIG_INVALID
    record = ScheduleRunLedger(tmp_path / "schedule-runs.jsonl").latest()
    assert record is not None
    assert record.reason_code == "SCHEDULE_ID_MISMATCH"
    assert record.schedule_id == "schedule-b"
    runner.assert_not_called()


def test_schedule_id_is_rejected_outside_scheduled_mode():
    assert main_module.main(
        ["--run-once", "--schedule-id", "schedule-a"]
    ) == HeadlessExitCode.CONFIG_INVALID


def test_queue_initialization_failure_is_recorded_as_exit_75(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        main_module,
        "get_logs_path",
        lambda name="app.log": tmp_path / name,
    )
    monkeypatch.setattr(
        main_module,
        "get_default_run_queue",
        Mock(side_effect=RunQueueError("アクセス不可")),
    )

    exit_code = main_module._run_cli_mode(
        AppConfig(),
        Mock(),
        scheduled=True,
        profile_id="snapshot-a",
        snapshot_id="snapshot-a",
        schedule_id="schedule-a",
        run_id="run-a",
        trigger_kind="scheduled",
    )

    assert exit_code == HeadlessExitCode.QUEUE_TIMEOUT
    record = ScheduleRunLedger(tmp_path / "schedule-runs.jsonl").latest()
    assert record is not None
    assert record.reason_code == "QUEUE_TIMEOUT"
    assert record.exit_code == 75
    assert record.run_id == "run-a"


def test_scheduled_wrapper_dispatches_own_ticket_without_wait_process(
    tmp_path,
    monkeypatch,
):
    queue = RunQueue(tmp_path / "run-queue")
    execute = Mock(return_value=0)
    monkeypatch.setattr(main_module, "get_default_run_queue", lambda: queue)
    monkeypatch.setattr(main_module, "_execute_cli_mode", execute)

    exit_code = main_module._run_cli_mode(
        AppConfig(),
        Mock(),
        scheduled=True,
        profile_id="snapshot-a",
        snapshot_id="snapshot-a",
        schedule_id="schedule-a",
        run_id="run-a",
        trigger_kind="windows_task",
        display_name="東北道路",
        config_path=str(tmp_path / "snapshot-a.yaml"),
    )

    assert exit_code == 0
    assert queue.list_queue() == []
    execute.assert_called_once()
    kwargs = execute.call_args.kwargs
    assert kwargs["use_waiting_queue"] is False
    assert kwargs["guard_already_acquired"] is True
    assert kwargs["schedule_id"] == "schedule-a"
    assert kwargs["snapshot_id"] == "snapshot-a"


def test_later_scheduled_process_enqueues_then_exits_when_dispatcher_exists(
    tmp_path,
    monkeypatch,
):
    clock = _Clock()
    queue = RunQueue(
        tmp_path / "run-queue",
        dispatcher_guard=_UnavailableGuard(),
        clock=clock,
        wall_clock=clock,
        sleep=clock.sleep,
        process_alive=lambda _pid: True,
    )
    execute = Mock(return_value=0)
    monkeypatch.setattr(main_module, "get_default_run_queue", lambda: queue)
    monkeypatch.setattr(main_module, "_execute_cli_mode", execute)

    exit_code = main_module._run_cli_mode(
        AppConfig(),
        Mock(),
        scheduled=True,
        profile_id="snapshot-a",
        snapshot_id="snapshot-a",
        schedule_id="schedule-a",
        run_id="run-a",
        trigger_kind="windows_task",
        config_path=str(tmp_path / "snapshot-a.yaml"),
    )

    assert exit_code == 0
    queued = queue.list_queue()
    assert len(queued) == 1
    assert queued[0].schedule_id == "schedule-a"
    assert queued[0].snapshot_id == "snapshot-a"
    execute.assert_not_called()


def test_scheduled_snapshot_cleanup_failure_only_warns(monkeypatch):
    service = Mock()
    service.finalize_scheduled_run.side_effect = RuntimeError("cleanup failed")
    monkeypatch.setattr(
        main_module,
        "_create_schedule_service",
        lambda _logger: service,
    )
    logger = Mock()

    main_module._finalize_scheduled_snapshot(
        logger,
        schedule_id="schedule-a",
        snapshot_id="snapshot-a",
    )

    service.finalize_scheduled_run.assert_called_once_with(
        "schedule-a", "snapshot-a"
    )
    logger.warning.assert_called_once()
