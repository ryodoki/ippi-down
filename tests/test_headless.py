# -*- coding: utf-8 -*-

"""非GUI実行の終了コード、再試行、履歴の回帰テスト。"""

from datetime import datetime, timezone
from contextlib import contextmanager
from unittest.mock import Mock

from src.app.headless import (
    HeadlessExitCode,
    RetryPolicy,
    execute_headless,
    exit_code_for_run_result,
    is_transient_failure,
    make_schedule_record_sink,
)
from src.app.run_guard import RunGuard
from src.app.run_queue import QueueTurn
from src.app.run_result import RunResult
from src.models.download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadStage,
)
from src.models.download_result import DownloadResult, RunOutcome
from src.models.download_task import DownloadTask
from src.models.file_info import FileInfo
from src.scheduler.ledger import ScheduleRunLedger


class _AvailableMutex:
    def __init__(self):
        self.held = False

    def try_acquire(self):
        if self.held:
            return None
        self.held = True
        return object()

    def release(self, token):
        assert token is not None
        self.held = False


class _FakeQueue:
    def __init__(self, turns=None):
        self.turns = list(turns or [QueueTurn(True, 0.0)])
        self.in_slot = False
        self.calls = []

    @contextmanager
    def schedule_lease(self, schedule_id):
        self.calls.append(("lease", schedule_id))
        yield True

    @contextmanager
    def wait_for_turn(self, schedule_id, run_id, **kwargs):
        self.calls.append(
            (
                "turn",
                schedule_id,
                run_id,
                kwargs.get("snapshot_id"),
            )
        )
        turn = self.turns.pop(0)
        self.in_slot = turn.acquired
        try:
            yield turn
        finally:
            self.in_slot = False


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def _failed_result(code: DownloadIssueCode) -> RunResult:
    task = DownloadTask(
        file_info=FileInfo(
            "https://example.test/file.pdf", "file.pdf", ".pdf"
        ),
        local_path="file.pdf",
        status="failed",
        error_message="失敗",
        issues=[
            DownloadIssue(
                code=code,
                stage=DownloadStage.FETCH,
                message="一時的な失敗",
            )
        ],
    )
    return RunResult(
        success=False,
        result=DownloadResult(total=1, tasks=[task]),
        message="失敗",
    )


def test_exit_codes_match_run_outcomes():
    assert exit_code_for_run_result(
        RunResult(success=True, outcome=RunOutcome.SUCCESS)
    ) == HeadlessExitCode.SUCCESS
    assert exit_code_for_run_result(
        RunResult(success=False, outcome=RunOutcome.NO_MATCH)
    ) == HeadlessExitCode.SUCCESS
    assert exit_code_for_run_result(
        RunResult(success=True, outcome=RunOutcome.PARTIAL)
    ) == HeadlessExitCode.FAILED
    assert exit_code_for_run_result(
        RunResult(success=False, outcome=RunOutcome.CANCELLED)
    ) == HeadlessExitCode.CANCELLED


def test_only_transient_structured_failures_are_retryable():
    assert is_transient_failure(
        _failed_result(DownloadIssueCode.HTTP_5XX)
    )
    assert is_transient_failure(
        _failed_result(DownloadIssueCode.NETWORK_TIMEOUT)
    )
    assert not is_transient_failure(
        _failed_result(DownloadIssueCode.SAVE_FAILED)
    )


def test_partial_result_with_only_transient_failures_is_retryable():
    failed = _failed_result(DownloadIssueCode.NETWORK_TIMEOUT).result.tasks[0]
    completed = DownloadTask(
        file_info=FileInfo(
            "https://example.test/ok.pdf", "ok.pdf", ".pdf"
        ),
        local_path="ok.pdf",
        status="completed",
    )
    result = RunResult(
        success=True,
        result=DownloadResult(total=2, tasks=[completed, failed]),
        message="一部失敗",
    )

    assert result.outcome == RunOutcome.PARTIAL
    assert is_transient_failure(result)


def test_japanese_network_failure_without_file_result_is_retryable():
    result = RunResult(
        success=False,
        error="検索ページの取得で一時的なネットワーク障害が発生しました",
        outcome=RunOutcome.FAILED,
    )

    assert is_transient_failure(result)


def test_explicit_search_failure_codes_control_retry_strictly():
    transient = RunResult(
        success=False,
        error="[HTTP_5XX] 検索ページを取得できません",
        outcome=RunOutcome.FAILED,
    )
    mixed = RunResult(
        success=False,
        error=(
            "[NETWORK_ERROR] 一部の詳細取得に失敗; "
            "[HTML_STRUCTURE_INVALID] 応答形式が不正"
        ),
        outcome=RunOutcome.FAILED,
    )
    conversion_timeout = RunResult(
        success=False,
        error="[CONVERSION_TIMEOUT] HTMLからPDFへの変換が時間切れ",
        outcome=RunOutcome.FAILED,
    )

    assert is_transient_failure(transient)
    assert not is_transient_failure(mixed)
    assert not is_transient_failure(conversion_timeout)


def test_execute_headless_stops_after_configured_transient_retries():
    runner = Mock(
        return_value=RunResult(
            success=False,
            error="[NETWORK_ERROR] 検索ページを取得できません",
            outcome=RunOutcome.FAILED,
        )
    )
    sleeps = []

    execution = execute_headless(
        runner,
        logger=Mock(),
        retry_policy=RetryPolicy(retry_count=2, interval_minutes=15),
        guard=RunGuard(process_mutex=_AvailableMutex()),
        sleep=sleeps.append,
    )

    assert runner.call_count == 3
    assert sleeps == [900, 900]
    assert execution.exit_code == HeadlessExitCode.FAILED
    assert execution.record.retry_count == 2
    assert execution.record.reason_code == "NETWORK_ERROR"


def test_retry_wait_callback_wraps_each_retry_sleep():
    runner = Mock(
        side_effect=[
            RunResult(
                success=False,
                error="[NETWORK_ERROR] 一時障害",
                outcome=RunOutcome.FAILED,
            ),
            RunResult(success=True, outcome=RunOutcome.SUCCESS),
        ]
    )
    events = []

    execution = execute_headless(
        runner,
        logger=Mock(),
        retry_policy=RetryPolicy(retry_count=1, interval_minutes=0),
        guard=RunGuard(process_mutex=_AvailableMutex()),
        sleep=lambda _seconds: None,
        retry_wait_callback=lambda waiting, attempt, seconds: events.append(
            (waiting, attempt, seconds)
        ),
    )

    assert execution.exit_code == HeadlessExitCode.SUCCESS
    assert events == [(True, 1, 0), (False, 1, 0)]


def test_execute_headless_retries_and_records_final_counts(tmp_path):
    attempts = [
        _failed_result(DownloadIssueCode.NETWORK_ERROR),
        RunResult(
            success=True,
            result=DownloadResult(total=2, success=1, skipped=1),
            message="完了",
        ),
    ]
    runner = Mock(side_effect=attempts)
    sleeps = []
    history_path = tmp_path / "schedule-runs.jsonl"
    moment = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)

    execution = execute_headless(
        runner,
        logger=Mock(),
        profile_id="profile-1",
        retry_policy=RetryPolicy(retry_count=2, interval_minutes=15),
        guard=RunGuard(process_mutex=_AvailableMutex()),
        record_sink=make_schedule_record_sink(history_path),
        sleep=sleeps.append,
        now=lambda: moment,
    )

    assert execution.exit_code == HeadlessExitCode.SUCCESS
    assert runner.call_count == 2
    assert sleeps == [900]
    assert execution.record.retry_count == 1
    assert execution.record.new_count == 1
    assert execution.record.existing_count == 1

    records = ScheduleRunLedger(history_path).recent()
    assert len(records) == 1
    assert records[0].profile_id == "profile-1"
    assert records[0].result == "success"
    assert records[0].exit_code == 0


def test_retry_history_counts_files_saved_by_earlier_attempt_as_new():
    failed = _failed_result(DownloadIssueCode.NETWORK_ERROR).result.tasks[0]
    completed = DownloadTask(
        file_info=FileInfo(
            "https://example.test/first.pdf", "first.pdf", ".pdf"
        ),
        local_path="first.pdf",
        status="completed",
    )
    first = RunResult(
        success=True,
        result=DownloadResult(total=2, tasks=[completed, failed]),
        message="一部失敗",
    )
    second = RunResult(
        success=True,
        result=DownloadResult(total=2, success=1, skipped=1),
        message="完了",
    )

    execution = execute_headless(
        Mock(side_effect=[first, second]),
        logger=Mock(),
        retry_policy=RetryPolicy(retry_count=2, interval_minutes=0),
        guard=RunGuard(process_mutex=_AvailableMutex()),
        sleep=lambda _seconds: None,
    )

    assert execution.record.new_count == 2
    assert execution.record.existing_count == 0


def test_execute_headless_returns_busy_without_calling_runner():
    mutex = _AvailableMutex()
    mutex.held = True
    runner = Mock()

    execution = execute_headless(
        runner,
        logger=Mock(),
        guard=RunGuard(process_mutex=mutex),
    )

    assert execution.exit_code == HeadlessExitCode.ALREADY_RUNNING
    assert execution.record.reason_code == "ALREADY_RUNNING"
    runner.assert_not_called()


def test_execute_headless_maps_keyboard_interrupt_to_130():
    execution = execute_headless(
        Mock(side_effect=KeyboardInterrupt),
        logger=Mock(),
        guard=RunGuard(process_mutex=_AvailableMutex()),
    )

    assert execution.exit_code == HeadlessExitCode.CANCELLED
    assert execution.record.exit_code == 130


def test_queue_timeout_is_75_and_keeps_execution_identity():
    queue = _FakeQueue([QueueTurn(False, 7200.0, "QUEUE_TIMEOUT")])
    runner = Mock()

    execution = execute_headless(
        runner,
        logger=Mock(),
        profile_id="snapshot-a",
        snapshot_id="snapshot-a",
        schedule_id="schedule-a",
        run_id="run-a",
        trigger_kind="scheduled",
        display_name="道路案件",
        run_queue=queue,
    )

    assert execution.exit_code == HeadlessExitCode.QUEUE_TIMEOUT
    assert execution.record.reason_code == "QUEUE_TIMEOUT"
    assert execution.record.queue_wait_seconds == 7200
    assert execution.record.schedule_id == "schedule-a"
    assert execution.record.snapshot_id == "snapshot-a"
    assert execution.record.run_id == "run-a"
    assert execution.record.trigger_kind == "scheduled"
    assert execution.record.display_name == "道路案件"
    runner.assert_not_called()


def test_retry_releases_global_slot_before_sleep_and_requeues():
    queue = _FakeQueue(
        [QueueTurn(True, 1.5), QueueTurn(True, 2.5)]
    )
    attempts = [
        RunResult(
            success=False,
            error="[NETWORK_ERROR] 一時障害",
            outcome=RunOutcome.FAILED,
        ),
        RunResult(success=True, outcome=RunOutcome.SUCCESS),
    ]

    def runner():
        assert queue.in_slot is True
        return attempts.pop(0)

    def retry_sleep(_seconds):
        assert queue.in_slot is False

    execution = execute_headless(
        runner,
        logger=Mock(),
        profile_id="snapshot-a",
        snapshot_id="snapshot-a",
        schedule_id="schedule-a",
        run_id="run-a",
        trigger_kind="scheduled",
        retry_policy=RetryPolicy(retry_count=1, interval_minutes=0),
        run_queue=queue,
        sleep=retry_sleep,
    )

    assert execution.exit_code == HeadlessExitCode.SUCCESS
    assert execution.record.retry_count == 1
    assert execution.record.queue_wait_seconds == 4.0
    assert [call[0] for call in queue.calls] == ["lease", "turn", "turn"]


def test_processing_deadline_is_recorded_as_run_timeout_not_cancel():
    queue = _FakeQueue()
    clock = _Clock()
    seen_deadlines = []

    def runner():
        clock.value = 7201.0
        return RunResult(
            success=False,
            result=DownloadResult(total=2, success=1, failed=1),
            outcome=RunOutcome.CANCELLED,
        )

    execution = execute_headless(
        runner,
        logger=Mock(),
        profile_id="snapshot-a",
        schedule_id="schedule-a",
        run_queue=queue,
        processing_timeout_seconds=7200,
        processing_deadline_callback=seen_deadlines.append,
        clock=clock,
    )

    assert seen_deadlines == [7200.0]
    assert execution.exit_code == HeadlessExitCode.RUN_TIMEOUT
    assert execution.record.reason_code == "RUN_TIMEOUT"
    assert execution.record.exit_code == 2
    assert execution.record.result == "failed"
    assert execution.record.new_count == 1
    assert execution.record.failed_count == 1
