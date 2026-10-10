# -*- coding: utf-8 -*-

"""GUIを持たない単発・定期実行の終了コード、再試行、履歴を統一する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
import json
from pathlib import Path
import re
import time
from typing import Callable, Optional, Protocol
import uuid

from ..models.download_diagnostics import DownloadIssueCode, IssueSeverity
from ..models.download_result import RunOutcome
from .run_guard import DOWNLOAD_RUN_GUARD, RunGuard
from .run_queue import (
    DEFAULT_PROCESSING_SECONDS,
    DEFAULT_QUEUE_WAIT_SECONDS,
    RunQueue,
    RunQueueError,
)
from .run_result import RunResult


class HeadlessExitCode(IntEnum):
    """Windowsタスクと手動CLIで共通のプロセス終了コード。"""

    SUCCESS = 0
    FAILED = 2
    PARTIAL_OR_FAILED = 2
    RUN_TIMEOUT = 2
    CONFIG_INVALID = 3
    ALREADY_RUNNING = 75
    QUEUE_TIMEOUT = 75
    CANCELLED = 130


# 短い名称も外部呼び出し側との互換用に公開する。
ExitCode = HeadlessExitCode


@dataclass(frozen=True)
class RetryPolicy:
    """ジョブ全体を再実行する回数と間隔。"""

    retry_count: int = 0
    interval_minutes: float = 15

    def __post_init__(self) -> None:
        if self.retry_count < 0:
            raise ValueError("retry_countは0以上である必要があります")
        if self.interval_minutes < 0:
            raise ValueError("interval_minutesは0以上である必要があります")


@dataclass(frozen=True)
class ExecutionRecord:
    """scheduler層へ渡す、秘密情報を含まない実行履歴データ。"""

    profile_id: str
    scheduled_at: Optional[datetime]
    started_at: datetime
    finished_at: datetime
    result: str
    new_count: int = 0
    saved_count: int = 0
    existing_count: int = 0
    failed_count: int = 0
    retry_count: int = 0
    reason_code: str = ""
    exit_code: int = 0
    schedule_id: str = "default"
    snapshot_id: str = ""
    run_id: str = ""
    trigger_kind: str = "manual_cli"
    queue_wait_seconds: float = 0.0
    display_name: str = ""

    def to_mapping(self) -> dict[str, object]:
        def iso(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() if value else None

        return {
            "profile_id": self.profile_id,
            "schedule_id": self.schedule_id,
            "snapshot_id": self.snapshot_id or self.profile_id,
            "run_id": self.run_id,
            "trigger_kind": self.trigger_kind,
            "queue_wait_seconds": round(
                max(0.0, float(self.queue_wait_seconds)), 3
            ),
            "display_name": self.display_name,
            "scheduled_at": iso(self.scheduled_at),
            "started_at": iso(self.started_at),
            "finished_at": iso(self.finished_at),
            "result": self.result,
            "new_count": self.new_count,
            "saved_count": self.saved_count,
            "existing_count": self.existing_count,
            "failed_count": self.failed_count,
            "retry_count": self.retry_count,
            "reason_code": self.reason_code,
            "exit_code": self.exit_code,
        }


@dataclass(frozen=True)
class HeadlessExecutionResult:
    """呼び出し元へ返す終了コードと最終RunResult。"""

    exit_code: HeadlessExitCode
    run_result: Optional[RunResult]
    record: ExecutionRecord


class _LoggerLike(Protocol):
    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str, exc_info: bool = False) -> None: ...


_TRANSIENT_ISSUE_CODES = {
    DownloadIssueCode.RATE_LIMIT,
    DownloadIssueCode.HTTP_5XX,
    DownloadIssueCode.NETWORK_TIMEOUT,
    DownloadIssueCode.NETWORK_ERROR,
}
_TRANSIENT_REASON_CODES = {
    code.value for code in _TRANSIENT_ISSUE_CODES
}
_REASON_CODE_PATTERN = re.compile(r"\[([A-Z][A-Z0-9_]*)\]")
JST = timezone(timedelta(hours=9), name="JST")
_TRANSIENT_TEXT = re.compile(
    r"(?:\bHTTP\s*5\d\d\b|\b429\b|rate[ -]?limit|"
    r"timed?\s*out|timeout|connection (?:reset|aborted|refused)|"
    r"temporary (?:network )?failure|タイムアウト|一時的な(?:通信|接続|ネットワーク)|"
    r"(?:通信|接続|ネットワーク)(?:エラー|障害|失敗))",
    re.IGNORECASE,
)


def is_transient_failure(run_result: RunResult) -> bool:
    """構造化診断が一時障害だけを示す場合に限って再試行する。"""
    if run_result.outcome not in {RunOutcome.FAILED, RunOutcome.PARTIAL}:
        return False

    download_result = run_result.result
    failed_tasks = (
        list(getattr(download_result, "failed_tasks", []))
        if download_result is not None
        else []
    )
    reason_codes: list[str] = []
    if failed_tasks:
        for task in failed_tasks:
            issues = [
                issue
                for issue in getattr(task, "issues", [])
                if getattr(issue, "severity", IssueSeverity.ERROR)
                == IssueSeverity.ERROR
            ]
            if not issues:
                return False
            reason_codes.extend(
                str(getattr(issue.code, "value", issue.code))
                for issue in issues
            )

    diagnostic = " ".join(
        value
        for value in (run_result.error or "", run_result.message or "")
        if value
    )
    reason_codes.extend(_REASON_CODE_PATTERN.findall(diagnostic))
    if reason_codes:
        # 一時障害と決定的障害が混在する場合、ジョブ全体の再実行はしない。
        return all(
            code in _TRANSIENT_REASON_CODES for code in reason_codes
        )

    if failed_tasks:
        return False

    # 旧RunResultとの互換経路だけ、明示的な通信障害表現をfallback判定する。
    # 曖昧な失敗は再試行しない。
    return bool(_TRANSIENT_TEXT.search(diagnostic))


def exit_code_for_run_result(run_result: RunResult) -> HeadlessExitCode:
    outcome = run_result.outcome
    if outcome in {RunOutcome.SUCCESS, RunOutcome.NO_MATCH}:
        return HeadlessExitCode.SUCCESS
    if outcome == RunOutcome.CANCELLED:
        return HeadlessExitCode.CANCELLED
    return HeadlessExitCode.FAILED


def _first_reason_code(run_result: RunResult) -> str:
    download_result = run_result.result
    if download_result is not None:
        for task in getattr(download_result, "failed_tasks", []):
            issues = list(getattr(task, "issues", []))
            primary = next(
                (
                    issue
                    for issue in issues
                    if getattr(issue, "severity", IssueSeverity.ERROR)
                    == IssueSeverity.ERROR
                ),
                issues[0] if issues else None,
            )
            if primary is not None:
                return str(getattr(primary.code, "value", primary.code))

    diagnostic = " ".join(
        value
        for value in (run_result.error or "", run_result.message or "")
        if value
    )
    explicit_reason = _REASON_CODE_PATTERN.search(diagnostic)
    if explicit_reason is not None:
        return explicit_reason.group(1)

    return {
        RunOutcome.SUCCESS: "SUCCESS",
        RunOutcome.NO_MATCH: "NO_MATCH",
        RunOutcome.PARTIAL: "PARTIAL_FAILURE",
        RunOutcome.CANCELLED: "CANCELLED",
        RunOutcome.FAILED: "RUN_FAILED",
    }.get(run_result.outcome, "RUN_FAILED")


def _record_from_result(
    run_result: RunResult,
    *,
    profile_id: str,
    scheduled_at: Optional[datetime],
    started_at: datetime,
    finished_at: datetime,
    retry_count: int,
    attempt_results: Optional[list[RunResult]] = None,
    schedule_id: str = "default",
    snapshot_id: str = "",
    run_id: str = "",
    trigger_kind: str = "manual_cli",
    queue_wait_seconds: float = 0.0,
    display_name: str = "",
) -> ExecutionRecord:
    result = run_result.result
    attempts = attempt_results or [run_result]
    new_count = sum(
        int(getattr(attempt.result, "success", 0) or 0)
        for attempt in attempts
        if attempt.result is not None
    )
    existing_count = int(
        getattr(result, "reused", getattr(result, "skipped", 0)) or 0
    )
    # 再試行前に保存できたファイルは、最終試行では保存済み確認になる。
    # ジョブ全体では新規保存として一度だけ数え、既存件数との二重計上を防ぐ。
    prior_new = sum(
        int(getattr(attempt.result, "success", 0) or 0)
        for attempt in attempts[:-1]
        if attempt.result is not None
    )
    existing_count = max(0, existing_count - prior_new)
    failed_count = int(getattr(result, "failed", 0) or 0)
    exit_code = exit_code_for_run_result(run_result)
    outcome = run_result.outcome or RunOutcome.FAILED
    return ExecutionRecord(
        profile_id=profile_id,
        scheduled_at=scheduled_at,
        started_at=started_at,
        finished_at=finished_at,
        result=outcome.value.lower(),
        new_count=new_count,
        # backendモデルではsaved_countとnew_countを併存させているため、
        # 現在のRunResultではどちらも新規保存件数を設定する。
        saved_count=new_count,
        existing_count=existing_count,
        failed_count=failed_count,
        retry_count=retry_count,
        reason_code=_first_reason_code(run_result),
        exit_code=int(exit_code),
        schedule_id=schedule_id,
        snapshot_id=snapshot_id or profile_id,
        run_id=run_id,
        trigger_kind=trigger_kind,
        queue_wait_seconds=queue_wait_seconds,
        display_name=display_name,
    )


def _write_record(
    sink: Optional[Callable[[ExecutionRecord], None]],
    record: ExecutionRecord,
    logger: _LoggerLike,
) -> None:
    if sink is None:
        return
    try:
        sink(record)
    except Exception as exc:
        # 履歴の障害でダウンロード結果や終了コードを上書きしない。
        logger.error(f"定期実行履歴を保存できません: {exc}")


def execute_headless(
    runner: Callable[[], RunResult],
    *,
    logger: _LoggerLike,
    profile_id: str = "default",
    schedule_id: str = "default",
    snapshot_id: str = "",
    run_id: str = "",
    trigger_kind: str = "manual_cli",
    display_name: str = "",
    scheduled_at: Optional[datetime] = None,
    retry_policy: RetryPolicy = RetryPolicy(),
    guard: RunGuard = DOWNLOAD_RUN_GUARD,
    run_queue: Optional[RunQueue] = None,
    initial_queue_wait_seconds: float = 0.0,
    queue_wait_timeout_seconds: float = DEFAULT_QUEUE_WAIT_SECONDS,
    processing_timeout_seconds: float = DEFAULT_PROCESSING_SECONDS,
    processing_deadline_callback: Optional[Callable[[float], None]] = None,
    retry_wait_callback: Optional[Callable[[bool, int, float], None]] = None,
    record_sink: Optional[Callable[[ExecutionRecord], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(JST),
    clock: Callable[[], float] = time.monotonic,
) -> HeadlessExecutionResult:
    """FIFO待機、排他、再試行、履歴を1つの論理実行として扱う。"""
    started_at = now()
    resolved_snapshot_id = snapshot_id or profile_id
    resolved_run_id = run_id or uuid.uuid4().hex
    queue_wait_seconds = max(0.0, float(initial_queue_wait_seconds))
    retries_done = 0
    attempt_results: list[RunResult] = []
    processing_deadline: Optional[float] = None

    def control_result(
        *,
        result: str,
        reason_code: str,
        exit_code: HeadlessExitCode,
    ) -> HeadlessExecutionResult:
        record = ExecutionRecord(
            profile_id=profile_id,
            schedule_id=schedule_id,
            snapshot_id=resolved_snapshot_id,
            run_id=resolved_run_id,
            trigger_kind=trigger_kind,
            queue_wait_seconds=queue_wait_seconds,
            display_name=display_name,
            scheduled_at=scheduled_at,
            started_at=started_at,
            finished_at=now(),
            result=result,
            retry_count=retries_done,
            reason_code=reason_code,
            exit_code=int(exit_code),
        )
        _write_record(record_sink, record, logger)
        return HeadlessExecutionResult(exit_code, None, record)

    def run_timeout_result(source: Optional[RunResult] = None) -> RunResult:
        return RunResult(
            success=False,
            result=source.result if source is not None else None,
            error="[RUN_TIMEOUT] 実処理が2時間の上限に達しました",
            message="定期実行は実処理時間の上限に達したため終了しました",
            outcome=RunOutcome.FAILED,
            search_summary=(
                source.search_summary if source is not None else None
            ),
        )

    def perform_attempts(*, queued: bool) -> Optional[HeadlessExecutionResult]:
        nonlocal processing_deadline
        nonlocal queue_wait_seconds
        nonlocal retries_done

        while True:
            if queued:
                wait_limit = max(0.0, float(queue_wait_timeout_seconds))
                if processing_deadline is not None:
                    remaining = processing_deadline - clock()
                    if remaining <= 0:
                        run_result = run_timeout_result()
                        attempt_results.append(run_result)
                        break
                    wait_limit = min(wait_limit, remaining)
                try:
                    turn_context = run_queue.wait_for_turn(  # type: ignore[union-attr]
                        schedule_id,
                        resolved_run_id,
                        snapshot_id=resolved_snapshot_id,
                        timeout_seconds=wait_limit,
                    )
                    with turn_context as turn:
                        queue_wait_seconds += max(0.0, turn.wait_seconds)
                        if not turn.acquired:
                            if (
                                processing_deadline is not None
                                and clock() >= processing_deadline
                            ):
                                run_result = run_timeout_result()
                                attempt_results.append(run_result)
                                break
                            logger.warning(
                                "実行キューの待機時間が2時間を超えたため、"
                                "今回の実行を開始しません"
                            )
                            return control_result(
                                result="queue_timeout",
                                reason_code="QUEUE_TIMEOUT",
                                exit_code=HeadlessExitCode.QUEUE_TIMEOUT,
                            )

                        if processing_deadline is None:
                            processing_deadline = (
                                clock()
                                + max(0.0, float(processing_timeout_seconds))
                            )
                            if processing_deadline_callback is not None:
                                processing_deadline_callback(
                                    processing_deadline
                                )
                        if clock() >= processing_deadline:
                            run_result = run_timeout_result()
                        else:
                            run_result = runner()
                            if clock() >= processing_deadline:
                                # ApplicationServiceのcancel_checkが返した
                                # CANCELLEDも、期限起因ならRUN_TIMEOUTへ正規化する。
                                run_result = run_timeout_result(run_result)
                except RunQueueError as exc:
                    logger.error(f"実行キューを利用できません: {exc}")
                    return control_result(
                        result="queue_timeout",
                        reason_code="QUEUE_TIMEOUT",
                        exit_code=HeadlessExitCode.QUEUE_TIMEOUT,
                    )
            else:
                run_result = runner()

            attempt_results.append(run_result)
            if (
                run_result.error
                and "[RUN_TIMEOUT]" in run_result.error
            ):
                break
            if (
                retries_done >= retry_policy.retry_count
                or not is_transient_failure(run_result)
            ):
                break
            retries_done += 1
            logger.warning(
                "一時的な障害のためジョブを再試行します: "
                f"{retries_done}/{retry_policy.retry_count}回, "
                f"待機={retry_policy.interval_minutes:g}分"
            )
            retry_delay = retry_policy.interval_minutes * 60
            actual_delay = retry_delay
            if queued and processing_deadline is not None:
                remaining = max(0.0, processing_deadline - clock())
                actual_delay = min(retry_delay, remaining)
            if retry_wait_callback is not None:
                try:
                    retry_wait_callback(True, retries_done, actual_delay)
                except Exception as exc:
                    logger.warning(
                        "再試行待機状態を更新できません: " f"{exc}"
                    )
            try:
                sleep(actual_delay)
            finally:
                if retry_wait_callback is not None:
                    try:
                        retry_wait_callback(False, retries_done, actual_delay)
                    except Exception as exc:
                        logger.warning(
                            "再試行待機状態を解除できません: " f"{exc}"
                        )
            if (
                queued
                and processing_deadline is not None
                and clock() >= processing_deadline
            ):
                run_result = run_timeout_result()
                attempt_results.append(run_result)
                break

        finished_at = now()
        record = _record_from_result(
            run_result,
            profile_id=profile_id,
            schedule_id=schedule_id,
            snapshot_id=resolved_snapshot_id,
            run_id=resolved_run_id,
            trigger_kind=trigger_kind,
            queue_wait_seconds=queue_wait_seconds,
            display_name=display_name,
            scheduled_at=scheduled_at,
            started_at=started_at,
            finished_at=finished_at,
            retry_count=retries_done,
            attempt_results=attempt_results,
        )
        _write_record(record_sink, record, logger)
        return HeadlessExecutionResult(
            exit_code_for_run_result(run_result), run_result, record
        )

    try:
        if run_queue is not None:
            with run_queue.schedule_lease(schedule_id) as acquired:
                if not acquired:
                    logger.warning(
                        "同じ定期実行が既に開始済みのため、"
                        "今回の実行を開始しません"
                    )
                    return control_result(
                        result="busy",
                        reason_code="ALREADY_RUNNING",
                        exit_code=HeadlessExitCode.ALREADY_RUNNING,
                    )
                return perform_attempts(queued=True)

        with guard.try_acquire() as acquired:
            if not acquired:
                logger.warning(
                    "別のダウンロードが実行中のため、"
                    "今回の実行を開始しません"
                )
                return control_result(
                    result="busy",
                    reason_code="ALREADY_RUNNING",
                    exit_code=HeadlessExitCode.ALREADY_RUNNING,
                )
            return perform_attempts(queued=False)
    except RunQueueError as exc:
        logger.error(f"実行キューを利用できません: {exc}")
        return control_result(
            result="queue_timeout",
            reason_code="QUEUE_TIMEOUT",
            exit_code=HeadlessExitCode.QUEUE_TIMEOUT,
        )
    except KeyboardInterrupt:
        logger.warning("ダウンロードをキャンセルしました")
        return control_result(
            result="cancelled",
            reason_code="CANCELLED",
            exit_code=HeadlessExitCode.CANCELLED,
        )
    except Exception as exc:
        # ApplicationServiceは通常RunResultへ変換するが、注入runnerや
        # 初期化経路の例外にも安定した終了コードを返す。
        logger.error(
            f"ダウンロード実行中に予期しないエラーが発生しました: {exc}"
        )
        run_result = RunResult(
            success=False,
            error=str(exc),
            message="ダウンロード実行中に予期しないエラーが発生しました",
            outcome=RunOutcome.FAILED,
        )
        attempt_results.append(run_result)
        record = _record_from_result(
            run_result,
            profile_id=profile_id,
            schedule_id=schedule_id,
            snapshot_id=resolved_snapshot_id,
            run_id=resolved_run_id,
            trigger_kind=trigger_kind,
            queue_wait_seconds=queue_wait_seconds,
            display_name=display_name,
            scheduled_at=scheduled_at,
            started_at=started_at,
            finished_at=now(),
            retry_count=retries_done,
            attempt_results=attempt_results,
        )
        _write_record(record_sink, record, logger)
        return HeadlessExecutionResult(
            HeadlessExitCode.FAILED, run_result, record
        )


def make_schedule_record_sink(
    path: Path,
) -> Callable[[ExecutionRecord], None]:
    """scheduler backendを遅延importしてJSONL履歴sinkを作る。

    軽量な単発CLIや移行途中の配布物でもimport時にはscheduler backendを
    必須にしない。backendが含まれない場合だけ同じschemaで直接追記する。
    """

    def sink(record: ExecutionRecord) -> None:
        try:
            from src.scheduler.ledger import ScheduleRunLedger
            from src.scheduler.models import ScheduledRunRecord
        except ImportError:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                record.to_mapping(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(payload + "\n")
            return

        # backendとのローリング更新中も動作させつつ、対応済みの診断項目は
        # すべて渡す。
        from dataclasses import fields

        supported = {field.name for field in fields(ScheduledRunRecord)}
        values = {
            "profile_id": record.profile_id,
            "schedule_id": record.schedule_id,
            "snapshot_id": record.snapshot_id or record.profile_id,
            "run_id": record.run_id,
            "trigger_kind": record.trigger_kind,
            "queue_wait_seconds": record.queue_wait_seconds,
            "display_name": record.display_name,
            "scheduled_at": record.scheduled_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "result": record.result,
            "new_count": record.new_count,
            "saved_count": record.saved_count,
            "existing_count": record.existing_count,
            "failed_count": record.failed_count,
            "retry_count": record.retry_count,
            "reason_code": record.reason_code,
            "exit_code": record.exit_code,
        }
        backend_record = ScheduledRunRecord(
            **{key: value for key, value in values.items() if key in supported}
        )
        ScheduleRunLedger(path).append(backend_record)

    return sink


def make_config_failure_record(
    *,
    profile_id: str,
    reason_code: str,
    schedule_id: str = "default",
    snapshot_id: str = "",
    run_id: str = "",
    trigger_kind: str = "windows_task",
    display_name: str = "",
    at: Optional[datetime] = None,
    scheduled_at: Optional[datetime] = None,
) -> ExecutionRecord:
    """設定読込前の失敗も同じ履歴schemaへ記録する。"""
    moment = at or datetime.now(JST)
    return ExecutionRecord(
        profile_id=profile_id,
        scheduled_at=scheduled_at,
        started_at=moment,
        finished_at=moment,
        result="config_invalid",
        reason_code=reason_code,
        exit_code=int(HeadlessExitCode.CONFIG_INVALID),
        schedule_id=schedule_id,
        snapshot_id=snapshot_id or profile_id,
        run_id=run_id or uuid.uuid4().hex,
        trigger_kind=trigger_kind,
        display_name=display_name,
    )


def make_queue_timeout_record(
    *,
    profile_id: str,
    schedule_id: str,
    snapshot_id: str = "",
    run_id: str = "",
    trigger_kind: str = "windows_task",
    display_name: str = "",
    at: Optional[datetime] = None,
    scheduled_at: Optional[datetime] = None,
) -> ExecutionRecord:
    """キュー初期化前の障害もQUEUE_TIMEOUTとして履歴化する。"""

    moment = at or datetime.now(JST)
    return ExecutionRecord(
        profile_id=profile_id,
        schedule_id=schedule_id,
        snapshot_id=snapshot_id or profile_id,
        run_id=run_id or uuid.uuid4().hex,
        trigger_kind=trigger_kind,
        display_name=display_name,
        scheduled_at=scheduled_at,
        started_at=moment,
        finished_at=moment,
        result="queue_timeout",
        reason_code="QUEUE_TIMEOUT",
        exit_code=int(HeadlessExitCode.QUEUE_TIMEOUT),
    )


__all__ = [
    "ExecutionRecord",
    "ExitCode",
    "HeadlessExecutionResult",
    "HeadlessExitCode",
    "RetryPolicy",
    "execute_headless",
    "exit_code_for_run_result",
    "is_transient_failure",
    "make_config_failure_record",
    "make_queue_timeout_record",
    "make_schedule_record_sink",
]
