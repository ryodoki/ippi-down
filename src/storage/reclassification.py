# -*- coding: utf-8 -*-

"""検証済みの旧 ``99_分類未解決`` 文書を安全に再分類する。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

from ..core.downloader import DownloadHistory
from ..models.search_target import SearchTarget
from ..utils.file_utils import FileUtils
from ..utils.logger import Logger
from ..utils.path_utils import get_base_path, resolve_verified_local_path
from .layout import TARGET_STORAGE_FOLDERS, RunKind


CancelCheck = Callable[[], bool]


class ReclassificationCandidateState(str, Enum):
    """preview時点の候補判定。"""

    READY_MOVE = "READY_MOVE"
    READY_TARGET_REUSE = "READY_TARGET_REUSE"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"
    CONFLICT = "CONFLICT"


class ReclassificationApplyStatus(str, Enum):
    """候補単位の適用結果。"""

    MOVED = "MOVED"
    TARGET_REUSED = "TARGET_REUSED"
    SKIPPED = "SKIPPED"
    CONFLICT = "CONFLICT"
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    LOCKED = "LOCKED"


class ReclassificationPhase(str, Enum):
    """GUIへ通知する処理段階。"""

    RECOVER = "RECOVER"
    SCAN = "SCAN"
    RESOLVE = "RESOLVE"
    VALIDATE = "VALIDATE"
    APPLY = "APPLY"
    CLEANUP = "CLEANUP"


@dataclass(frozen=True)
class ReclassificationAgencySegment:
    """履歴とresolverの間で使用する発注機関1階層。"""

    level: str
    label: str
    code: str = ""


@dataclass(frozen=True)
class ReclassificationAgencyQuery:
    """3階層履歴の細分類候補を問い合わせる値。"""

    parent_segments: Tuple[ReclassificationAgencySegment, ...]
    office_name: str
    agency_id: str
    cancel_check: Optional[CancelCheck] = field(
        default=None,
        repr=False,
        compare=False,
    )
    search_target: str = SearchTarget.KOJI_KEIKA.value


class ReclassificationAgencyResolver(Protocol):
    """ネットワーク実装をサービス本体から分離するresolver契約。"""

    def resolve_candidates(
        self,
        query: ReclassificationAgencyQuery,
    ) -> Sequence[object]:
        """選択済み親階層配下の細分類候補を返す。"""


@dataclass(frozen=True)
class ReclassificationIssue:
    """plan/result全体に関する構造化診断。"""

    reason_code: str
    reason: str
    path: Optional[Path] = None


@dataclass(frozen=True)
class ReclassificationProgress:
    """GUIへ渡す軽量な進捗差分。"""

    phase: ReclassificationPhase
    current: int
    total: int
    message: str
    candidate_id: str = ""


@dataclass(frozen=True)
class ReclassificationCandidate:
    """1つの保存済み文書に対する再分類preview。"""

    candidate_id: str
    run_kind: RunKind
    storage_key: str
    run_root: Path
    history_path: Path
    source_path: Path
    target_path: Path
    url: str
    project_name: str
    document_name: str
    agency_segments: Tuple[ReclassificationAgencySegment, ...]
    new_agency_segments: Tuple[ReclassificationAgencySegment, ...]
    state: ReclassificationCandidateState
    reason_code: str
    reason: str
    size: int
    sha256: str
    expected_format: str
    final_url: str = ""
    processing_mode: str = "DIRECT"
    validation_kind: str = ""
    completed_at: str = ""
    document_updated_at: str = ""
    document_id: str = ""
    schedule_id: str = ""
    office_name: str = ""
    agency_id: str = ""
    history_line_number: int = 0
    history_record_fingerprint: str = ""
    history_stored_source_path: str = ""
    search_target: str = ""
    layout_version: int = 3

    @property
    def actionable(self) -> bool:
        return self.state in {
            ReclassificationCandidateState.READY_MOVE,
            ReclassificationCandidateState.READY_TARGET_REUSE,
        }


@dataclass(frozen=True)
class ReclassificationPlan:
    """履歴・ファイルを再検証して作成した不変preview。"""

    plan_id: str
    data_root: Path
    created_at: str
    candidates: Tuple[ReclassificationCandidate, ...] = ()
    history_files: Tuple[Path, ...] = ()
    scanned_records: int = 0
    cancelled: bool = False
    issues: Tuple[ReclassificationIssue, ...] = ()

    @property
    def actionable_count(self) -> int:
        return sum(candidate.actionable for candidate in self.candidates)

    @property
    def move_count(self) -> int:
        return sum(
            candidate.state is ReclassificationCandidateState.READY_MOVE
            for candidate in self.candidates
        )

    @property
    def target_reuse_count(self) -> int:
        return sum(
            candidate.state
            is ReclassificationCandidateState.READY_TARGET_REUSE
            for candidate in self.candidates
        )

    @property
    def unresolved_count(self) -> int:
        return sum(
            candidate.state is ReclassificationCandidateState.UNRESOLVED
            for candidate in self.candidates
        )

    @property
    def invalid_count(self) -> int:
        return sum(
            candidate.state is ReclassificationCandidateState.INVALID
            for candidate in self.candidates
        )

    @property
    def conflict_count(self) -> int:
        return sum(
            candidate.state is ReclassificationCandidateState.CONFLICT
            for candidate in self.candidates
        )


@dataclass(frozen=True)
class ReclassificationOutcome:
    """1候補の確定結果。"""

    candidate_id: str
    status: ReclassificationApplyStatus
    source_path: Path
    target_path: Path
    reason_code: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ReclassificationApplyResult:
    """再分類適用の集計。"""

    plan_id: str
    outcomes: Tuple[ReclassificationOutcome, ...] = ()
    issues: Tuple[ReclassificationIssue, ...] = ()
    cancelled: bool = False

    def _count(self, status: ReclassificationApplyStatus) -> int:
        return sum(outcome.status is status for outcome in self.outcomes)

    @property
    def moved_count(self) -> int:
        return self._count(ReclassificationApplyStatus.MOVED)

    @property
    def target_reused_count(self) -> int:
        return self._count(ReclassificationApplyStatus.TARGET_REUSED)

    @property
    def reused_count(self) -> int:
        """GUI向けの短い互換名。"""

        return self.target_reused_count

    @property
    def conflict_count(self) -> int:
        return self._count(ReclassificationApplyStatus.CONFLICT)

    @property
    def failed_count(self) -> int:
        return self._count(ReclassificationApplyStatus.FAILED)

    @property
    def invalid_count(self) -> int:
        return self._count(ReclassificationApplyStatus.INVALID)

    @property
    def cancelled_count(self) -> int:
        return self._count(ReclassificationApplyStatus.CANCELLED)

    @property
    def skipped_count(self) -> int:
        return self._count(ReclassificationApplyStatus.SKIPPED)


# 承認済み公開名。初期実装名もGUI adapterとの互換性のため維持する。
ReclassificationResult = ReclassificationApplyResult


class _RunGuardLike(Protocol):
    def try_acquire(self):
        """boolをyieldするcontext managerを返す。"""


@dataclass(frozen=True)
class _RunRoot:
    path: Path
    run_kind: RunKind
    storage_key: str = ""
    search_target: str = ""
    layout_version: int = 3


class _Cancelled(RuntimeError):
    pass


_ResolverCacheKey = Tuple[str, Tuple[Tuple[str, str, str], ...]]
_ResolverCacheValue = tuple[
    Tuple[ReclassificationAgencySegment, ...],
    str,
]


class ReclassificationService:
    """履歴を正本にして、同一実行ルート内だけで安全に再分類する。"""

    HISTORY_NAME = DownloadHistory.FILE_NAME
    JOURNAL_NAME = ".ippi-reclassification-journal.json"
    JOURNAL_SCHEMA_VERSION = 1
    RECLASSIFICATION_REASON_CODE = "AGENCY_PATH_RECLASSIFIED"

    def __init__(
        self,
        logger: Optional[Logger] = None,
        agency_resolver: Optional[
            ReclassificationAgencyResolver
            | Callable[[ReclassificationAgencyQuery], Sequence[object]]
        ] = None,
        run_guard: Optional[_RunGuardLike] = None,
    ) -> None:
        self.logger = logger or Logger()
        self.agency_resolver = agency_resolver
        if run_guard is None:
            from ..app.run_guard import DOWNLOAD_RUN_GUARD

            run_guard = DOWNLOAD_RUN_GUARD
        self.run_guard = run_guard
        self._file_utils = FileUtils()

    def scan(
        self,
        config: object,
        *,
        cancel_check: Optional[CancelCheck] = None,
        progress_callback: Optional[
            Callable[[ReclassificationProgress], None]
        ] = None,
    ) -> ReclassificationPlan:
        """通常・全定期実行履歴を走査し、変更前previewを返す。"""

        plan_id = uuid.uuid4().hex
        created_at = self._now()
        try:
            data_root, normal_name, scheduled_name, layout_version = (
                self._layout(config)
            )
        except (TypeError, ValueError, OSError) as exc:
            plan = ReclassificationPlan(
                plan_id=plan_id,
                data_root=Path("."),
                created_at=created_at,
                issues=(
                    ReclassificationIssue(
                        "RECLASSIFICATION_CONFIG_INVALID",
                        str(exc),
                    ),
                ),
            )
            self._log_scan_summary(plan)
            return plan

        with self.run_guard.try_acquire() as acquired:
            if not acquired:
                plan = ReclassificationPlan(
                    plan_id=plan_id,
                    data_root=data_root,
                    created_at=created_at,
                    issues=(
                        ReclassificationIssue(
                            "RECLASSIFICATION_RUN_LOCKED",
                            "ダウンロードまたは別の再分類処理が実行中です",
                        ),
                    ),
                )
                self._log_scan_summary(plan)
                return plan

            issues: list[ReclassificationIssue] = []
            try:
                run_roots = self._discover_run_roots(
                    data_root,
                    normal_name,
                    scheduled_name,
                    layout_version,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                plan = ReclassificationPlan(
                    plan_id=plan_id,
                    data_root=data_root,
                    created_at=created_at,
                    issues=(
                        ReclassificationIssue(
                            "RECLASSIFICATION_PATH_UNSAFE",
                            f"保存ルートを安全に確認できません: {exc}",
                            data_root,
                        ),
                    ),
                )
                self._log_scan_summary(plan)
                return plan
            usable_roots: list[_RunRoot] = []
            for index, run_root in enumerate(run_roots, start=1):
                self._progress(
                    progress_callback,
                    ReclassificationPhase.RECOVER,
                    index,
                    len(run_roots),
                    f"未完了処理を確認中: {run_root.path}",
                )
                try:
                    self._recover_journal(run_root.path)
                except Exception as exc:
                    issues.append(
                        ReclassificationIssue(
                            "RECLASSIFICATION_RECOVERY_FAILED",
                            f"未完了処理を復旧できません: {exc}",
                            run_root.path / self.JOURNAL_NAME,
                        )
                    )
                    continue
                usable_roots.append(run_root)

            candidates: list[ReclassificationCandidate] = []
            history_files: list[Path] = []
            scanned_records = 0
            cancelled = False
            resolver_cache: dict[
                _ResolverCacheKey,
                _ResolverCacheValue,
            ] = {}
            for index, run_root in enumerate(usable_roots, start=1):
                if self._cancelled(cancel_check):
                    cancelled = True
                    break
                self._progress(
                    progress_callback,
                    ReclassificationPhase.SCAN,
                    index,
                    len(usable_roots),
                    f"履歴を確認中: {run_root.path}",
                )
                history_path = run_root.path / self.HISTORY_NAME
                try:
                    root_candidates, root_scanned, root_cancelled = (
                        self._scan_history(
                            run_root,
                            cancel_check=cancel_check,
                            progress_callback=progress_callback,
                            resolver_cache=resolver_cache,
                        )
                    )
                    candidates.extend(root_candidates)
                    scanned_records += root_scanned
                    history_files.append(history_path)
                    if root_cancelled:
                        cancelled = True
                        break
                except Exception as exc:
                    issues.append(
                        ReclassificationIssue(
                            "RECLASSIFICATION_HISTORY_READ_FAILED",
                            f"履歴を確認できません: {exc}",
                            history_path,
                        )
                    )

            candidates.sort(
                key=lambda candidate: (
                    str(candidate.run_root).casefold(),
                    str(candidate.source_path).casefold(),
                    candidate.candidate_id,
                )
            )
            plan = ReclassificationPlan(
                plan_id=plan_id,
                data_root=data_root,
                created_at=created_at,
                candidates=tuple(candidates),
                history_files=tuple(history_files),
                scanned_records=scanned_records,
                cancelled=cancelled,
                issues=tuple(issues),
            )
            self._log_scan_summary(plan)
            return plan

    def apply(
        self,
        plan: ReclassificationPlan,
        candidate_ids: Optional[Iterable[str]] = None,
        *,
        cancel_check: Optional[CancelCheck] = None,
        progress_callback: Optional[
            Callable[[ReclassificationProgress], None]
        ] = None,
    ) -> ReclassificationApplyResult:
        """previewで選んだ候補だけを再検証し、1件ずつ確定する。"""

        if not isinstance(plan, ReclassificationPlan):
            raise TypeError("planはReclassificationPlanで指定してください")
        available = {item.candidate_id: item for item in plan.candidates}
        if candidate_ids is None:
            selected = [item for item in plan.candidates if item.actionable]
            unknown_ids: list[str] = []
        else:
            requested = list(dict.fromkeys(str(value) for value in candidate_ids))
            unknown_ids = [value for value in requested if value not in available]
            selected = [available[value] for value in requested if value in available]

        issues = [
            ReclassificationIssue(
                "RECLASSIFICATION_CANDIDATE_NOT_FOUND",
                f"previewにない候補IDです: {candidate_id}",
            )
            for candidate_id in unknown_ids
        ]
        outcomes: list[ReclassificationOutcome] = []
        if plan.cancelled:
            issues.append(
                ReclassificationIssue(
                    "RECLASSIFICATION_PLAN_INCOMPLETE",
                    "プレビューが途中でキャンセルされたため適用できません",
                )
            )
            outcomes.extend(
                self._outcome(
                    item,
                    ReclassificationApplyStatus.SKIPPED,
                    "RECLASSIFICATION_PLAN_INCOMPLETE",
                    "未完了のプレビューは適用できません",
                )
                for item in selected
            )
            result = ReclassificationApplyResult(
                plan.plan_id,
                tuple(outcomes),
                tuple(issues),
                cancelled=True,
            )
            self._log_apply_result(result, available)
            return result
        with self.run_guard.try_acquire() as acquired:
            if not acquired:
                outcomes.extend(
                    self._outcome(
                        item,
                        ReclassificationApplyStatus.LOCKED,
                        "RECLASSIFICATION_RUN_LOCKED",
                        "ダウンロードまたは別の再分類処理が実行中です",
                    )
                    for item in selected
                )
                result = ReclassificationApplyResult(
                    plan.plan_id,
                    tuple(outcomes),
                    tuple(issues),
                )
                self._log_apply_result(result, available)
                return result

            recovered_roots: set[Path] = set()
            cancelled = False
            for index, candidate in enumerate(selected, start=1):
                if self._cancelled(cancel_check):
                    cancelled = True
                    outcomes.extend(
                        self._outcome(
                            remaining,
                            ReclassificationApplyStatus.CANCELLED,
                            "RECLASSIFICATION_CANCELLED",
                            "利用者により再分類を中止しました",
                        )
                        for remaining in selected[index - 1 :]
                    )
                    break
                self._progress(
                    progress_callback,
                    ReclassificationPhase.APPLY,
                    index,
                    len(selected),
                    f"再分類中: {candidate.document_name or candidate.source_path.name}",
                    candidate.candidate_id,
                )
                if candidate.run_root not in recovered_roots:
                    try:
                        self._recover_journal(candidate.run_root)
                    except Exception as exc:
                        outcomes.append(
                            self._outcome(
                                candidate,
                                ReclassificationApplyStatus.FAILED,
                                "RECLASSIFICATION_RECOVERY_FAILED",
                                f"未完了処理を復旧できません: {exc}",
                            )
                        )
                        continue
                    recovered_roots.add(candidate.run_root)

                if not candidate.actionable:
                    status = (
                        ReclassificationApplyStatus.CONFLICT
                        if candidate.state
                        is ReclassificationCandidateState.CONFLICT
                        else ReclassificationApplyStatus.INVALID
                        if candidate.state
                        is ReclassificationCandidateState.INVALID
                        else ReclassificationApplyStatus.SKIPPED
                    )
                    outcomes.append(
                        self._outcome(
                            candidate,
                            status,
                            candidate.reason_code,
                            candidate.reason,
                        )
                    )
                    continue
                outcomes.append(
                    self._apply_candidate(candidate, cancel_check)
                )
                if outcomes[-1].status is ReclassificationApplyStatus.CANCELLED:
                    cancelled = True
                    outcomes.extend(
                        self._outcome(
                            remaining,
                            ReclassificationApplyStatus.CANCELLED,
                            "RECLASSIFICATION_CANCELLED",
                            "利用者により再分類を中止しました",
                        )
                        for remaining in selected[index:]
                    )
                    break

        result = ReclassificationApplyResult(
            plan.plan_id,
            tuple(outcomes),
            tuple(issues),
            cancelled,
        )
        self._log_apply_result(result, available)
        return result

    def _scan_history(
        self,
        run_root: _RunRoot,
        *,
        cancel_check: Optional[CancelCheck],
        progress_callback: Optional[
            Callable[[ReclassificationProgress], None]
        ],
        resolver_cache: dict[_ResolverCacheKey, _ResolverCacheValue],
    ) -> tuple[list[ReclassificationCandidate], int, bool]:
        history = DownloadHistory(
            run_root.path,
            self.logger,
            layout_version=run_root.layout_version,
        )
        self._assert_no_reparse(run_root.path)
        self._assert_no_reparse(history.path)
        latest: dict[tuple[str, str, str], tuple[int, dict[str, Any]]] = {}
        scanned = 0
        invalid_lines = 0
        with history.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if self._cancelled(cancel_check):
                    return [], scanned, True
                if not line.strip():
                    continue
                scanned += 1
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    invalid_lines += 1
                    continue
                if not isinstance(raw, dict):
                    invalid_lines += 1
                    continue
                record = dict(raw)
                stored_target = str(
                    record.get("target_path") or record.get("path") or ""
                )
                url = str(record.get("url") or "")
                expected_format = DownloadHistory.normalize_expected_format(
                    str(record.get("expected_format") or ""),
                    Path(stored_target or "file"),
                )
                if not stored_target or not url:
                    continue
                latest[(url, stored_target.casefold(), expected_format)] = (
                    line_number,
                    record,
                )

        if invalid_lines:
            self.logger.warning(
                f"再分類で不正な履歴行を無視しました: {history.path} "
                f"({invalid_lines}行)"
            )

        superseded: dict[
            tuple[str, str, str],
            tuple[int, str],
        ] = {}
        for line_number, record in latest.values():
            if self._cancelled(cancel_check):
                return [], scanned, True
            old_path = str(record.get("reclassified_from_path") or "")
            if (
                str(record.get("status") or "SUCCESS").upper() != "SUCCESS"
                or not old_path
                or not self._record_file_is_valid(history, record)
            ):
                continue
            identity = self._record_identity(record)
            previous = superseded.get(identity)
            if previous is None or line_number > previous[0]:
                superseded[identity] = (line_number, old_path.casefold())
        # 同じ旧ファイルを指す複数の履歴がある場合は最新行だけを採用する。
        # 再分類成功後も旧成功行はappend-only履歴に残るため、新しい成功行が
        # 明示的に置換した旧パスは候補へ戻さない。
        records = sorted(
            latest.values(),
            key=lambda value: value[0],
            reverse=True,
        )
        candidates: list[ReclassificationCandidate] = []
        seen_sources: set[Path] = set()
        total = len(records)
        for index, (line_number, record) in enumerate(records, start=1):
            if self._cancelled(cancel_check):
                return candidates, scanned, True
            if str(record.get("status") or "SUCCESS").upper() != "SUCCESS":
                continue
            try:
                record_layout = int(record.get("layout_version", 2))
                if record_layout != run_root.layout_version:
                    continue
            except (TypeError, ValueError):
                continue
            if run_root.search_target:
                try:
                    record_target = SearchTarget.coerce(
                        record.get("search_target")
                    ).value
                except (TypeError, ValueError):
                    continue
                if record_target != run_root.search_target:
                    continue
            stored_path = str(record.get("path") or "")
            replacement = superseded.get(self._record_identity(record))
            if (
                replacement is not None
                and replacement[0] > line_number
                and replacement[1] == stored_path.casefold()
            ):
                continue
            try:
                self._assert_no_reparse(run_root.path)
                source_path = self._history_lexical_path(
                    history,
                    stored_path,
                )
                self._assert_no_reparse(source_path)
                relative = source_path.relative_to(run_root.path)
            except (OSError, RuntimeError, ValueError) as exc:
                self.logger.warning(
                    "reclassification.scan.path_rejected "
                    + json.dumps(
                        {
                            "reason_code": "RECLASSIFICATION_PATH_UNSAFE",
                            "reason": str(exc),
                            "run_kind": run_root.run_kind.value,
                            "storage_key": run_root.storage_key,
                            "stored_path": stored_path,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                continue
            if not relative.parts or relative.parts[0] != "99_分類未解決":
                continue
            if source_path in seen_sources:
                continue
            seen_sources.add(source_path)
            self._progress(
                progress_callback,
                ReclassificationPhase.RESOLVE,
                index,
                total,
                f"分類を確認中: {relative.as_posix()}",
            )
            try:
                candidate = self._candidate_from_record(
                    run_root,
                    history,
                    record,
                    line_number,
                    source_path,
                    relative,
                    cancel_check,
                    resolver_cache,
                )
                candidates.append(candidate)
                self._log_scan_candidate(candidate)
            except _Cancelled:
                return candidates, scanned, True
        return candidates, scanned, False

    def _candidate_from_record(
        self,
        run_root: _RunRoot,
        history: DownloadHistory,
        record: Mapping[str, Any],
        line_number: int,
        source_path: Path,
        relative: Path,
        cancel_check: Optional[CancelCheck],
        resolver_cache: dict[_ResolverCacheKey, _ResolverCacheValue],
    ) -> ReclassificationCandidate:
        url = str(record.get("url") or "")
        document_name = str(record.get("document_name") or source_path.name)
        expected_format = DownloadHistory.normalize_expected_format(
            str(record.get("expected_format") or ""),
            source_path,
        )
        candidate_seed = "\0".join(
            (
                str(history.path),
                str(line_number),
                url,
                str(source_path),
                expected_format,
            )
        )
        candidate_id = hashlib.sha256(
            candidate_seed.encode("utf-8")
        ).hexdigest()[:24]
        segments = self._segments(record.get("agency_path"))
        office_name = str(record.get("office_name") or "").strip()
        agency_id = str(record.get("agency_id") or "").strip()
        search_target = SearchTarget.coerce(
            run_root.search_target or record.get("search_target")
        ).value
        resolution, state, code, reason = self._resolve_segments(
            segments,
            office_name,
            agency_id,
            search_target,
            cancel_check,
            resolver_cache,
        )
        target_path = source_path
        project_name = ""
        size = self._integer(record.get("size"), default=-1)
        sha256 = str(record.get("sha256") or "").strip().lower()

        if state in {
            ReclassificationCandidateState.READY_MOVE,
            ReclassificationCandidateState.READY_TARGET_REUSE,
        }:
            try:
                target_path, project_name = self._target_path(
                    run_root.path,
                    relative,
                    segments,
                    resolution,
                    consume_office_fallback=self._uses_office_fallback(
                        record.get("agency_path"),
                        segments,
                        office_name,
                    ),
                    office_name=office_name,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                state = ReclassificationCandidateState.INVALID
                code = "RECLASSIFICATION_PATH_INVALID"
                reason = f"再分類先を安全に生成できません: {exc}"

        if state in {
            ReclassificationCandidateState.READY_MOVE,
            ReclassificationCandidateState.READY_TARGET_REUSE,
        }:
            try:
                self._assert_no_reparse(run_root.path)
                self._assert_no_reparse(source_path)
                self._assert_no_reparse(target_path)
                if source_path.resolve() == target_path.resolve(
                    strict=False
                ):
                    raise ValueError("再分類元と移動先が同一です")
            except (OSError, RuntimeError, ValueError) as exc:
                state = ReclassificationCandidateState.INVALID
                code = "RECLASSIFICATION_PATH_UNSAFE"
                reason = f"再分類pathを安全に検証できません: {exc}"

        if state in {
            ReclassificationCandidateState.READY_MOVE,
            ReclassificationCandidateState.READY_TARGET_REUSE,
        }:
            valid, validation_reason = self._validate_source(
                history,
                source_path,
                size,
                sha256,
                expected_format,
            )
            if not valid:
                state = ReclassificationCandidateState.INVALID
                code = "RECLASSIFICATION_SOURCE_INVALID"
                reason = validation_reason
            else:
                state, code, reason = self._target_state(
                    history,
                    target_path,
                    size,
                    sha256,
                    expected_format,
                )

        return ReclassificationCandidate(
            candidate_id=candidate_id,
            run_kind=run_root.run_kind,
            storage_key=str(record.get("storage_key") or run_root.storage_key),
            search_target=search_target,
            layout_version=run_root.layout_version,
            run_root=run_root.path,
            history_path=history.path,
            source_path=source_path,
            target_path=target_path,
            url=url,
            project_name=project_name,
            document_name=document_name,
            agency_segments=segments,
            new_agency_segments=resolution,
            state=state,
            reason_code=code,
            reason=reason,
            size=size,
            sha256=sha256,
            expected_format=expected_format,
            final_url=str(record.get("final_url") or url),
            processing_mode=str(record.get("processing_mode") or "DIRECT"),
            validation_kind=str(record.get("validation_kind") or ""),
            completed_at=str(record.get("completed_at") or ""),
            document_updated_at=str(
                record.get("document_updated_at") or ""
            ),
            document_id=str(record.get("document_id") or ""),
            schedule_id=str(record.get("schedule_id") or ""),
            office_name=office_name,
            agency_id=agency_id,
            history_line_number=line_number,
            history_record_fingerprint=self._record_fingerprint(record),
            history_stored_source_path=history.stored_path(source_path),
        )

    def _resolve_segments(
        self,
        segments: Tuple[ReclassificationAgencySegment, ...],
        office_name: str,
        agency_id: str,
        search_target: str,
        cancel_check: Optional[CancelCheck],
        resolver_cache: dict[_ResolverCacheKey, _ResolverCacheValue],
    ) -> tuple[
        Tuple[ReclassificationAgencySegment, ...],
        ReclassificationCandidateState,
        str,
        str,
    ]:
        expected_levels = (
            "daibunrui",
            "chubunrui",
            "shoubunrui",
            "saibunrui",
        )
        if not 3 <= len(segments) <= 4:
            return (
                segments,
                ReclassificationCandidateState.UNRESOLVED,
                "RECLASSIFICATION_AGENCY_PATH_INCOMPLETE",
                "大・中・小の3階層以上を履歴から確認できません",
            )
        if tuple(segment.level for segment in segments) != expected_levels[: len(segments)]:
            return (
                segments,
                ReclassificationCandidateState.UNRESOLVED,
                "RECLASSIFICATION_AGENCY_LEVEL_INVALID",
                "発注機関階層の順序が不正です",
            )
        if any(not segment.label for segment in segments):
            return (
                segments,
                ReclassificationCandidateState.UNRESOLVED,
                "RECLASSIFICATION_AGENCY_LABEL_MISSING",
                "発注機関の表示名が不足しています",
            )
        if len(segments) == 4:
            if office_name:
                if self._text_matches(segments[3].label, office_name):
                    return (
                        segments,
                        ReclassificationCandidateState.READY_MOVE,
                        "RECLASSIFICATION_OFFLINE_MATCH",
                        "4階層と担当部・事務所の表示名を"
                        "オフラインで確認しました",
                    )
                return (
                    segments,
                    ReclassificationCandidateState.UNRESOLVED,
                    "AGENCY_OFFICE_CONFLICT",
                    "細分類と詳細ページの担当部・事務所が一致しません",
                )
            if segments[3].code and segments[3].code == agency_id:
                return (
                    segments,
                    ReclassificationCandidateState.READY_MOVE,
                    "RECLASSIFICATION_LEGACY_ID_MATCH",
                    "担当部・事務所名がない旧履歴を細分類codeと"
                    "HachushaIdの完全一致で確認しました",
                )
            return (
                segments,
                ReclassificationCandidateState.UNRESOLVED,
                "AGENCY_DETAIL_MISSING",
                "担当部・事務所名がなく、細分類codeとHachushaIdでも"
                "確認できません",
            )

        if not office_name:
            return (
                segments,
                ReclassificationCandidateState.UNRESOLVED,
                "RECLASSIFICATION_OFFICE_MISSING",
                "細分類の照合に必要な担当部・事務所名がありません",
            )
        if self.agency_resolver is None:
            return (
                segments,
                ReclassificationCandidateState.UNRESOLVED,
                "RECLASSIFICATION_RESOLVER_REQUIRED",
                "3階層履歴の細分類候補を確認するresolverがありません",
            )
        if self._cancelled(cancel_check):
            raise _Cancelled()
        query = ReclassificationAgencyQuery(
            parent_segments=segments,
            office_name=office_name,
            agency_id=agency_id,
            cancel_check=cancel_check,
            search_target=search_target,
        )
        cache_key: _ResolverCacheKey = (
            search_target,
            tuple(
                (segment.level, segment.code, segment.label)
                for segment in segments
            ),
        )
        cached = resolver_cache.get(cache_key)
        if cached is None:
            try:
                resolver = self.agency_resolver
                method = getattr(resolver, "resolve_candidates", None)
                raw_options = (
                    method(query) if callable(method) else resolver(query)
                )
                options = tuple(
                    option
                    for option in (
                        self._coerce_resolver_option(value)
                        for value in raw_options
                    )
                    if option is not None
                )
                cached = (options, "")
            except _Cancelled:
                raise
            except Exception as exc:
                cached = ((), str(exc) or type(exc).__name__)
            resolver_cache[cache_key] = cached
        options, resolver_error = cached
        if resolver_error:
            return (
                segments,
                ReclassificationCandidateState.UNRESOLVED,
                "RECLASSIFICATION_RESOLVER_FAILED",
                f"細分類候補を確認できません: {resolver_error}",
            )
        if self._cancelled(cancel_check):
            raise _Cancelled()
        matches = {
            (option.code, option.label): option
            for option in options
            if self._text_matches(option.label, office_name)
        }
        if len(matches) != 1:
            return (
                segments,
                ReclassificationCandidateState.UNRESOLVED,
                "RECLASSIFICATION_OFFICE_NOT_UNIQUE",
                "担当部・事務所に一致する細分類候補が"
                f"一意ではありません (matches={len(matches)})",
            )
        child = next(iter(matches.values()))
        return (
            (*segments, child),
            ReclassificationCandidateState.READY_MOVE,
            "RECLASSIFICATION_RESOLVER_MATCH",
            "細分類候補と担当部・事務所名を一意に照合しました",
        )

    def _target_path(
        self,
        run_root: Path,
        source_relative: Path,
        old_segments: Tuple[ReclassificationAgencySegment, ...],
        new_segments: Tuple[ReclassificationAgencySegment, ...],
        *,
        consume_office_fallback: bool = False,
        office_name: str = "",
    ) -> tuple[Path, str]:
        parts = source_relative.parts
        if not parts or parts[0] != "99_分類未解決":
            raise ValueError("元ファイルが99_分類未解決配下ではありません")
        safe_old_labels = tuple(
            self._file_utils.sanitize_path_component(segment.label)
            for segment in old_segments
        )
        stored_labels = parts[1 : 1 + len(old_segments)]
        if tuple(value.casefold() for value in stored_labels) != tuple(
            value.casefold() for value in safe_old_labels
        ):
            raise ValueError("履歴の発注機関階層と実保存先が一致しません")
        tail = parts[1 + len(old_segments) :]
        if consume_office_fallback:
            safe_office = self._file_utils.sanitize_path_component(
                office_name
            )
            if not tail or tail[0].casefold() != safe_office.casefold():
                raise ValueError(
                    "v2未解決履歴の担当部・事務所フォルダーが"
                    "実保存先と一致しません"
                )
            tail = tail[1:]
        if len(tail) < 3:
            raise ValueError("工事名・文書区分・ファイル名が不足しています")
        agency_labels = [segment.label for segment in new_segments]
        target = self._file_utils.build_safe_download_path_parts(
            run_root,
            [*agency_labels, *tail[:-1]],
            tail[-1],
            return_lexical=True,
        )
        self._assert_within(run_root, target)
        return target, tail[0]

    @staticmethod
    def _validate_source(
        history: DownloadHistory,
        path: Path,
        size: int,
        sha256: str,
        expected_format: str,
    ) -> tuple[bool, str]:
        if size <= 0 or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            return False, "履歴のサイズまたはSHA-256が不正です"
        return history.validate_file(
            path,
            expected_size=size,
            expected_sha256=sha256,
            expected_format=expected_format,
        )

    @staticmethod
    def _target_state(
        history: DownloadHistory,
        target: Path,
        size: int,
        sha256: str,
        expected_format: str,
    ) -> tuple[ReclassificationCandidateState, str, str]:
        if not target.exists():
            return (
                ReclassificationCandidateState.READY_MOVE,
                "RECLASSIFICATION_READY_MOVE",
                "検証後に同じ実行ルート内で移動できます",
            )
        valid, _ = history.validate_file(
            target,
            expected_size=size,
            expected_sha256=sha256,
            expected_format=expected_format,
        )
        if valid:
            return (
                ReclassificationCandidateState.READY_TARGET_REUSE,
                "RECLASSIFICATION_TARGET_IDENTICAL",
                "再分類先の同内容ファイルを正本として履歴化できます。"
                "旧ファイルは削除せず保持します",
            )
        return (
            ReclassificationCandidateState.CONFLICT,
            "RECLASSIFICATION_TARGET_CONFLICT",
            "再分類先に異なる内容のファイルがあるため変更しません",
        )

    def _apply_candidate(
        self,
        candidate: ReclassificationCandidate,
        cancel_check: Optional[CancelCheck],
    ) -> ReclassificationOutcome:
        history = DownloadHistory(
            candidate.run_root,
            self.logger,
            layout_version=candidate.layout_version,
        )
        try:
            self._assert_no_reparse(candidate.run_root)
            self._assert_no_reparse(candidate.source_path)
            self._assert_no_reparse(candidate.target_path)
            self._assert_no_reparse(candidate.history_path)
            self._assert_within(candidate.run_root, candidate.source_path)
            self._assert_within(candidate.run_root, candidate.target_path)
            self._assert_within(candidate.run_root, candidate.history_path)
            if candidate.source_path.resolve() == candidate.target_path.resolve(
                strict=False
            ):
                raise ValueError("再分類元と移動先が同一です")
            if candidate.history_path.resolve() != history.path.resolve():
                raise ValueError("preview後に履歴ファイルの場所が変わりました")
            current, stale_reason = self._history_record_is_current(
                candidate,
            )
            if not current:
                return self._outcome(
                    candidate,
                    ReclassificationApplyStatus.INVALID,
                    "STALE_PLAN",
                    stale_reason,
                )
            valid, reason = self._validate_source(
                history,
                candidate.source_path,
                candidate.size,
                candidate.sha256,
                candidate.expected_format,
            )
            if not valid:
                return self._outcome(
                    candidate,
                    ReclassificationApplyStatus.INVALID,
                    "RECLASSIFICATION_SOURCE_INVALID",
                    reason,
                )
            state, reason_code, reason = self._target_state(
                history,
                candidate.target_path,
                candidate.size,
                candidate.sha256,
                candidate.expected_format,
            )
            if state is ReclassificationCandidateState.CONFLICT:
                return self._outcome(
                    candidate,
                    ReclassificationApplyStatus.CONFLICT,
                    reason_code,
                    reason,
                )
            if self._cancelled(cancel_check):
                return self._outcome(
                    candidate,
                    ReclassificationApplyStatus.CANCELLED,
                    "RECLASSIFICATION_CANCELLED",
                    "利用者により再分類を中止しました",
                )
            operation = (
                "MOVE"
                if state is ReclassificationCandidateState.READY_MOVE
                else "REUSE_TARGET"
            )
            transaction_id = uuid.uuid4().hex
            new_record = self._reclassified_record(
                candidate,
                history,
                transaction_id,
            )
            journal = {
                "schema_version": self.JOURNAL_SCHEMA_VERSION,
                "transaction_id": transaction_id,
                "state": "PREPARED",
                "operation": operation,
                "source_path": history.stored_path(candidate.source_path),
                "target_path": history.stored_path(candidate.target_path),
                "staging_path": "",
                "history_path": self.HISTORY_NAME,
                "history_record": new_record,
                "created_at": self._now(),
            }
            self._write_journal(candidate.run_root, journal)
            try:
                candidate.target_path.parent.mkdir(parents=True, exist_ok=True)
                # mkdir前後でjunction等へ差し替えられていないかを、renameに
                # できるだけ近い時点でもう一度確認する。
                self._assert_no_reparse(candidate.run_root)
                self._assert_no_reparse(candidate.source_path)
                self._assert_no_reparse(candidate.target_path)
                self._assert_within(
                    candidate.run_root,
                    candidate.source_path,
                )
                self._assert_within(
                    candidate.run_root,
                    candidate.target_path,
                )
                if candidate.source_path.resolve() == (
                    candidate.target_path.resolve(strict=False)
                ):
                    raise ValueError("再分類元と移動先が同一です")
                self._same_filesystem(
                    candidate.run_root,
                    candidate.target_path.parent,
                )
                if operation == "MOVE":
                    if candidate.target_path.exists():
                        raise FileExistsError(
                            "再分類先がpreview後に作成されました"
                        )
                    os.rename(candidate.source_path, candidate.target_path)
                else:
                    # 同内容のtargetは正本として履歴化するが、利用者の旧fileは
                    # 明示的な整理操作なしに削除しない。
                    target_valid, target_reason = history.validate_file(
                        candidate.target_path,
                        expected_size=candidate.size,
                        expected_sha256=candidate.sha256,
                        expected_format=candidate.expected_format,
                    )
                    if not target_valid:
                        raise FileExistsError(
                            "再分類先がpreview後に変化しました: "
                            f"{target_reason}"
                        )
                journal["state"] = "FILE_MOVED"
                self._write_journal(candidate.run_root, journal)
                if self._cancelled(cancel_check):
                    raise _Cancelled()
                history.append_record(new_record, durable=True)
                journal["state"] = "HISTORY_APPENDED"
                self._write_journal(candidate.run_root, journal)
            except Exception as exc:
                if self._history_contains_id(
                    history.path,
                    transaction_id,
                    expected_record=new_record,
                ):
                    cleanup_warning = ""
                    try:
                        self._finish_committed_journal(
                            candidate.run_root,
                            journal,
                        )
                    except Exception as cleanup_exc:
                        cleanup_warning = f"（後処理警告: {cleanup_exc}）"
                        self.logger.warning(
                            "再分類の確定後処理を完了できません: "
                            f"{candidate.source_path} - {cleanup_exc}"
                        )
                    if operation == "MOVE":
                        return self._outcome(
                            candidate,
                            ReclassificationApplyStatus.MOVED,
                            self.RECLASSIFICATION_REASON_CODE,
                            "再分類先へ移動しました"
                            f"（履歴追記後の診断: {exc}）"
                            + cleanup_warning,
                        )
                    return self._outcome(
                        candidate,
                        ReclassificationApplyStatus.TARGET_REUSED,
                        "RECLASSIFICATION_TARGET_REUSED",
                        "同内容の再分類先を正本として履歴化しました。"
                        "旧ファイルは削除せず保持しています"
                        f"（履歴追記後の診断: {exc}）"
                        + cleanup_warning,
                    )
                else:
                    self._rollback_journal(candidate.run_root, journal)
                raise

            cleanup_warning = ""
            try:
                self._finish_committed_journal(candidate.run_root, journal)
            except Exception as exc:
                cleanup_warning = f"（後処理警告: {exc}）"
                self.logger.warning(
                    "再分類の後処理を完了できません: "
                    f"{candidate.source_path} - {exc}"
                )
            if operation == "MOVE":
                return self._outcome(
                    candidate,
                    ReclassificationApplyStatus.MOVED,
                    self.RECLASSIFICATION_REASON_CODE,
                    "再分類先へ移動しました" + cleanup_warning,
                )
            return self._outcome(
                candidate,
                ReclassificationApplyStatus.TARGET_REUSED,
                "RECLASSIFICATION_TARGET_REUSED",
                "同内容の再分類先を正本として履歴化しました。"
                "旧ファイルは削除せず保持しています"
                + cleanup_warning,
            )
        except _Cancelled:
            return self._outcome(
                candidate,
                ReclassificationApplyStatus.CANCELLED,
                "RECLASSIFICATION_CANCELLED",
                "利用者により再分類を中止し、元の状態へ戻しました",
            )
        except FileExistsError as exc:
            return self._outcome(
                candidate,
                ReclassificationApplyStatus.CONFLICT,
                "RECLASSIFICATION_TARGET_CONFLICT",
                str(exc),
            )
        except Exception as exc:
            return self._outcome(
                candidate,
                ReclassificationApplyStatus.FAILED,
                "RECLASSIFICATION_APPLY_FAILED",
                str(exc),
            )

    def _reclassified_record(
        self,
        candidate: ReclassificationCandidate,
        history: DownloadHistory,
        transaction_id: str,
    ) -> dict[str, object]:
        label_matched = bool(candidate.office_name)
        resolution = {
            "status": "detail_matched",
            "method": (
                "reclassification_offline"
                if len(candidate.agency_segments) == 4 and label_matched
                else "reclassification_legacy_id"
                if len(candidate.agency_segments) == 4
                else "reclassification_resolver"
            ),
            "reason": "",
            "reason_code": (
                "OFFICE_LABEL_MATCH" if label_matched else "LEGACY_ID_MATCH"
            ),
        }
        record: dict[str, object] = {
            "schema_version": DownloadHistory.SCHEMA_VERSION,
            "url": candidate.url,
            "target_path": history.stored_path(candidate.target_path),
            "path": history.stored_path(candidate.target_path),
            "expected_format": candidate.expected_format,
            "status": "SUCCESS",
            "processing_mode": candidate.processing_mode,
            "validation_kind": candidate.validation_kind
            or DownloadHistory.validation_kind(candidate.expected_format),
            "reason_code": self.RECLASSIFICATION_REASON_CODE,
            "final_url": candidate.final_url or candidate.url,
            "size": candidate.size,
            "sha256": candidate.sha256,
            "completed_at": candidate.completed_at or self._now(),
            "reuse_kind": "EXACT_PATH",
            "alias_from_path": history.stored_path(candidate.source_path),
            "document_name": candidate.document_name,
            "document_updated_at": candidate.document_updated_at,
            "document_id": candidate.document_id,
            "layout_version": candidate.layout_version,
            "search_target": candidate.search_target,
            "run_kind": candidate.run_kind.value,
            "office_name": candidate.office_name,
            "agency_id": candidate.agency_id,
            "agency_path": {
                "version": 2,
                "segments": [
                    {
                        "level": segment.level,
                        "label": segment.label,
                        "code": segment.code,
                    }
                    for segment in candidate.new_agency_segments
                ],
                "resolution": resolution,
            },
            "reclassification_id": transaction_id,
            "reclassified_at": self._now(),
            "reclassified_from_path": history.stored_path(
                candidate.source_path
            ),
        }
        if candidate.storage_key:
            record["storage_key"] = candidate.storage_key
        if candidate.schedule_id:
            record["schedule_id"] = candidate.schedule_id
        return record

    def _recover_journal(self, run_root: Path) -> None:
        journal_path = run_root / self.JOURNAL_NAME
        if not journal_path.is_file():
            return
        self._assert_no_reparse(run_root)
        self._assert_no_reparse(journal_path)
        self._assert_no_reparse(run_root / self.HISTORY_NAME)
        try:
            raw = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"再分類journalを読めません: {exc}") from exc
        journal = self._validate_journal(run_root, raw)
        history_path = run_root / self.HISTORY_NAME
        transaction_id = str(journal["transaction_id"])
        if self._history_contains_id(
            history_path,
            transaction_id,
            expected_record=dict(journal["history_record"]),
        ):
            self._finish_committed_journal(run_root, journal)
        else:
            self._rollback_journal(run_root, journal)

    @staticmethod
    def _journal_layout_version(journal: Mapping[str, Any]) -> int:
        record = journal.get("history_record")
        if not isinstance(record, Mapping):
            raise ValueError("再分類journalの履歴情報が不正です")
        try:
            layout_version = int(record.get("layout_version", 3))
        except (TypeError, ValueError) as exc:
            raise ValueError("再分類journalの保存レイアウトが不正です") from exc
        if layout_version not in {3, 4}:
            raise ValueError("再分類journalの保存レイアウトが未対応です")
        return layout_version

    def _validate_journal(
        self,
        run_root: Path,
        raw: object,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("再分類journalが辞書ではありません")
        journal = dict(raw)
        if self._integer(journal.get("schema_version"), 0) != 1:
            raise ValueError("未対応の再分類journalです")
        if str(journal.get("operation")) not in {"MOVE", "REUSE_TARGET"}:
            raise ValueError("再分類journalの操作種別が不正です")
        if str(journal.get("state")) not in {
            "PREPARED",
            "FILE_MOVED",
            "HISTORY_APPENDED",
        }:
            raise ValueError("再分類journalの状態が不正です")
        transaction_id = str(journal.get("transaction_id") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
            raise ValueError("再分類journalのIDが不正です")
        if str(journal.get("history_path") or "") != self.HISTORY_NAME:
            raise ValueError("再分類journalの履歴ファイル名が不正です")
        history = DownloadHistory(
            run_root,
            self.logger,
            layout_version=self._journal_layout_version(journal),
        )
        self._assert_no_reparse(run_root)
        self._assert_no_reparse(history.path)
        resolved_paths: dict[str, Path] = {}
        for key in ("source_path", "target_path"):
            stored = str(journal.get(key) or "")
            self._assert_no_reparse(
                self._history_lexical_path(history, stored)
            )
            resolved_paths[key] = history.actual_path(stored)
        if resolved_paths["source_path"] == resolved_paths["target_path"]:
            raise ValueError("再分類journalの移動元と移動先が同一です")
        staging = str(journal.get("staging_path") or "")
        if staging:
            self._assert_no_reparse(
                self._history_lexical_path(history, staging)
            )
            history.actual_path(staging)
        raw_record = journal.get("history_record")
        if not isinstance(raw_record, dict):
            raise ValueError("再分類journalの履歴レコードが不正です")
        record = dict(raw_record)
        if str(record.get("reclassification_id") or "") != transaction_id:
            raise ValueError("再分類journalと履歴レコードのIDが一致しません")
        if str(record.get("status") or "").upper() != "SUCCESS":
            raise ValueError("再分類journalの履歴レコードが成功ではありません")
        for key in ("target_path", "path"):
            stored = str(record.get(key) or "")
            if history.actual_path(stored) != resolved_paths["target_path"]:
                raise ValueError(
                    "再分類journalと履歴レコードの移動先が一致しません"
                )
        old_stored = str(record.get("reclassified_from_path") or "")
        if history.actual_path(old_stored) != resolved_paths["source_path"]:
            raise ValueError(
                "再分類journalと履歴レコードの移動元が一致しません"
            )
        if self._integer(record.get("size"), -1) <= 0:
            raise ValueError("再分類journalのfile sizeが不正です")
        if not re.fullmatch(
            r"[0-9a-fA-F]{64}",
            str(record.get("sha256") or ""),
        ):
            raise ValueError("再分類journalのSHA-256が不正です")
        expected_format = str(record.get("expected_format") or "").strip()
        normalized_format = DownloadHistory.normalize_expected_format(
            expected_format,
            resolved_paths["target_path"],
        )
        if (
            not expected_format
            or not normalized_format
            or normalized_format
            != resolved_paths["target_path"].suffix.casefold()
            or normalized_format
            != resolved_paths["source_path"].suffix.casefold()
        ):
            raise ValueError("再分類journalの期待形式が不正です")
        return journal

    def _rollback_journal(
        self,
        run_root: Path,
        journal: Mapping[str, Any],
    ) -> None:
        history = DownloadHistory(
            run_root,
            self.logger,
            layout_version=self._journal_layout_version(journal),
        )
        source = history.actual_path(str(journal["source_path"]))
        target = history.actual_path(str(journal["target_path"]))
        operation = str(journal["operation"])
        source_exists = source.exists()
        target_exists = target.exists()
        if source_exists and not source.is_file():
            raise RuntimeError("再分類元が通常fileではありません")
        if target_exists and not target.is_file():
            raise RuntimeError("再分類先が通常fileではありません")
        record = dict(journal["history_record"])
        if operation == "MOVE":
            if source_exists and not target_exists:
                valid, reason = self._journal_file_valid(
                    history,
                    source,
                    record,
                )
                if not valid:
                    raise RuntimeError(
                        f"移動前fileが不正なためjournalを保持します: {reason}"
                    )
            elif target_exists and not source_exists:
                valid, reason = self._journal_file_valid(
                    history,
                    target,
                    record,
                )
                if not valid:
                    raise RuntimeError(
                        f"移動先fileが不正なためrollbackしません: {reason}"
                    )
                source.parent.mkdir(parents=True, exist_ok=True)
                self._assert_no_reparse(source)
                os.rename(target, source)
            else:
                raise RuntimeError(
                    "再分類元と移動先の存在状態が曖昧なため"
                    "journalを保持します"
                )
        else:
            if not (source_exists and target_exists):
                raise RuntimeError(
                    "同内容target処理のfile存在状態が不正なため"
                    "journalを保持します"
                )
            for label, path in (("元", source), ("移動先", target)):
                valid, reason = self._journal_file_valid(
                    history,
                    path,
                    record,
                )
                if not valid:
                    raise RuntimeError(
                        f"{label}fileが不正なためjournalを保持します: {reason}"
                    )
        self._delete_journal(run_root)
        self._cleanup_empty_dirs(target.parent, run_root)

    def _finish_committed_journal(
        self,
        run_root: Path,
        journal: Mapping[str, Any],
    ) -> None:
        history = DownloadHistory(
            run_root,
            self.logger,
            layout_version=self._journal_layout_version(journal),
        )
        source = history.actual_path(str(journal["source_path"]))
        target = history.actual_path(str(journal["target_path"]))
        record = dict(journal["history_record"])
        operation = str(journal["operation"])
        if operation == "MOVE":
            if source.exists() or not target.is_file():
                raise RuntimeError(
                    "履歴追記済みMOVEのfile存在状態が不正です"
                )
            paths = (("再分類先", target),)
        else:
            if not source.is_file() or not target.is_file():
                raise RuntimeError(
                    "履歴追記済みtarget正本化のfile存在状態が不正です"
                )
            paths = (("元", source), ("再分類先", target))
        for label, path in paths:
            valid, reason = self._journal_file_valid(
                history,
                path,
                record,
            )
            if not valid:
                raise RuntimeError(
                    f"履歴追記済みの{label}fileが不正です: {reason}"
                )
        self._delete_journal(run_root)
        if operation == "MOVE":
            self._cleanup_empty_dirs(source.parent, run_root)

    def _write_journal(
        self,
        run_root: Path,
        journal: Mapping[str, Any],
    ) -> None:
        self._assert_no_reparse(run_root)
        path = run_root / self.JOURNAL_NAME
        temporary = run_root / (
            f"{self.JOURNAL_NAME}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        payload = json.dumps(
            dict(journal),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _delete_journal(self, run_root: Path) -> None:
        (run_root / self.JOURNAL_NAME).unlink(missing_ok=True)

    @staticmethod
    def _history_contains_id(
        history_path: Path,
        transaction_id: str,
        *,
        expected_record: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        if not history_path.is_file():
            return False
        with history_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if transaction_id not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("reclassification_id") == transaction_id
                    and str(record.get("status") or "").upper() == "SUCCESS"
                    and (
                        expected_record is None
                        or record == dict(expected_record)
                    )
                ):
                    return True
        return False

    def _history_record_is_current(
        self,
        candidate: ReclassificationCandidate,
    ) -> tuple[bool, str]:
        if not candidate.history_record_fingerprint:
            return False, "プレビューに履歴fingerprintがありません"
        if not candidate.history_stored_source_path:
            return False, "プレビューに履歴source pathがありません"
        identity = (
            candidate.url,
            candidate.history_stored_source_path.casefold(),
            DownloadHistory.normalize_expected_format(
                candidate.expected_format,
                candidate.source_path,
            ),
        )
        history = DownloadHistory(
            candidate.run_root,
            self.logger,
            layout_version=candidate.layout_version,
        )
        latest: Optional[Mapping[str, Any]] = None
        superseded = False
        try:
            with candidate.history_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw, Mapping):
                        continue
                    try:
                        lexical_source = self._history_lexical_path(
                            history,
                            str(raw.get("path") or ""),
                        )
                        self._assert_no_reparse(lexical_source)
                        source_key = lexical_source.relative_to(
                            history.base_dir
                        ).as_posix().casefold()
                    except (OSError, RuntimeError, ValueError):
                        continue
                    expected_format = DownloadHistory.normalize_expected_format(
                        str(raw.get("expected_format") or ""),
                        Path(str(raw.get("path") or "file")),
                    )
                    if (
                        line_number > candidate.history_line_number
                        and str(raw.get("status") or "SUCCESS").upper()
                        == "SUCCESS"
                        and str(raw.get("url") or "") == candidate.url
                        and expected_format == identity[2]
                    ):
                        old_stored = str(
                            raw.get("reclassified_from_path") or ""
                        )
                        try:
                            old_lexical = self._history_lexical_path(
                                history,
                                old_stored,
                            )
                            self._assert_no_reparse(old_lexical)
                            old_key = old_lexical.relative_to(
                                history.base_dir
                            ).as_posix().casefold()
                        except (OSError, RuntimeError, ValueError):
                            old_key = ""
                        if old_key == identity[1]:
                            superseded = True
                    if (
                        str(raw.get("url") or ""),
                        source_key,
                        expected_format,
                    ) == identity:
                        latest = raw
        except OSError as exc:
            return False, f"最新履歴を確認できません: {exc}"
        if superseded:
            return False, "preview後に同じ元fileの再分類履歴が追加されました"
        if latest is None:
            return False, "preview対象の最新履歴が見つかりません"
        if str(latest.get("status") or "SUCCESS").upper() != "SUCCESS":
            return False, "preview後に同じ文書の最新状態が変更されました"
        if self._record_fingerprint(latest) != (
            candidate.history_record_fingerprint
        ):
            return False, "preview後に同じ文書の成功履歴が更新されました"
        return True, ""

    def _journal_file_valid(
        self,
        history: DownloadHistory,
        path: Path,
        record: Mapping[str, Any],
    ) -> tuple[bool, str]:
        self._assert_no_reparse(path)
        return history.validate_file(
            path,
            expected_size=self._integer(record.get("size"), -1),
            expected_sha256=str(record.get("sha256") or ""),
            expected_format=str(record.get("expected_format") or ""),
        )

    @staticmethod
    def _history_lexical_path(
        history: DownloadHistory,
        stored_path: str,
    ) -> Path:
        if not stored_path:
            raise ValueError("履歴pathが空です")
        candidate = Path(stored_path)
        combined = candidate if candidate.is_absolute() else history.base_dir / candidate
        lexical = Path(os.path.abspath(os.fspath(combined)))
        try:
            lexical.relative_to(history.base_dir)
        except ValueError as exc:
            raise ValueError("履歴pathが保存ルート外を参照しています") from exc
        return lexical

    @staticmethod
    def _path_is_reparse(path: Path) -> bool:
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(metadata.st_mode):
            return True
        attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
        reparse_flag = int(
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        return bool(attributes & reparse_flag)

    @classmethod
    def _assert_no_reparse(cls, path: Path) -> None:
        """path自身と既存祖先にsymlink/reparse pointがないことを確認する。"""

        current = Path(os.path.abspath(os.fspath(path)))
        while True:
            if cls._path_is_reparse(current):
                raise ValueError(
                    f"symlinkまたはreparse pointは使用できません: {current}"
                )
            parent = current.parent
            if parent == current:
                return
            current = parent

    @staticmethod
    def _cleanup_empty_dirs(start: Path, run_root: Path) -> None:
        root = run_root.resolve()
        current = start.resolve()
        while current != root:
            try:
                current.relative_to(root)
            except ValueError:
                return
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    @staticmethod
    def _same_filesystem(run_root: Path, target_parent: Path) -> None:
        try:
            if run_root.stat().st_dev != target_parent.stat().st_dev:
                raise ValueError("異なるファイルシステムへの移動はできません")
        except OSError as exc:
            raise ValueError(f"保存先のファイルシステムを確認できません: {exc}") from exc

    @staticmethod
    def _assert_within(run_root: Path, candidate: Path) -> None:
        try:
            candidate.resolve().relative_to(run_root.resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("実行ルート外のパスは再分類できません") from exc

    def _discover_run_roots(
        self,
        data_root: Path,
        normal_name: str,
        scheduled_name: str,
        layout_version: int,
    ) -> list[_RunRoot]:
        roots: list[_RunRoot] = []
        if layout_version == 4:
            target_roots = [
                (data_root / folder, target.value)
                for target, folder in TARGET_STORAGE_FOLDERS.items()
            ]
        else:
            target_roots = [(data_root, "")]

        for target_root_candidate, search_target in target_roots:
            self._assert_no_reparse(target_root_candidate)
            target_root = target_root_candidate.resolve()
            self._assert_within(data_root, target_root)

            normal_candidate = target_root / normal_name
            self._assert_no_reparse(normal_candidate)
            normal = normal_candidate.resolve()
            self._assert_within(target_root, normal)
            if (normal / self.HISTORY_NAME).is_file():
                roots.append(
                    _RunRoot(
                        normal,
                        RunKind.MANUAL,
                        search_target=search_target,
                        layout_version=layout_version,
                    )
                )

            scheduled_candidate = target_root / scheduled_name
            self._assert_no_reparse(scheduled_candidate)
            scheduled = scheduled_candidate.resolve()
            self._assert_within(target_root, scheduled)
            if not scheduled.is_dir():
                continue
            for child in sorted(
                scheduled.iterdir(),
                key=lambda value: value.name.casefold(),
            ):
                if self._path_is_reparse(child):
                    raise ValueError(
                        "定期実行ルートにsymlinkまたはreparse pointが"
                        f"あります: {child}"
                    )
                if not child.is_dir():
                    continue
                resolved = child.resolve()
                self._assert_within(scheduled, resolved)
                if not (resolved / self.HISTORY_NAME).is_file():
                    continue
                storage_key = resolved.name.split("_", 1)[0]
                roots.append(
                    _RunRoot(
                        resolved,
                        RunKind.SCHEDULED,
                        storage_key,
                        search_target,
                        layout_version,
                    )
                )
        return roots

    @classmethod
    def _layout(cls, config: object) -> tuple[Path, str, str, int]:
        save_paths = getattr(config, "save_paths", config)
        try:
            layout_version = int(getattr(save_paths, "layout_version", 2))
        except (TypeError, ValueError) as exc:
            raise ValueError("layout_versionが不正です") from exc
        if layout_version not in {3, 4}:
            raise ValueError("再分類は保存レイアウトv3またはv4だけに対応します")
        local = str(getattr(save_paths, "local", "") or "").strip()
        normal = str(
            getattr(save_paths, "normal_folder", "") or ""
        ).strip()
        scheduled = str(
            getattr(save_paths, "scheduled_folder", "") or ""
        ).strip()
        if not local or not normal or not scheduled:
            raise ValueError("保存先または実行種別フォルダーが未設定です")
        for value, name in ((normal, "normal_folder"), (scheduled, "scheduled_folder")):
            if Path(value).name != value or value in {".", ".."}:
                raise ValueError(f"{name}は単一フォルダー名で指定してください")
        raw_text = os.fspath(local).strip()
        if raw_text.replace("/", "\\").startswith("\\\\"):
            # この呼出しは字句判定で拒否し、UNCへlstatしない。
            resolve_verified_local_path(local)
        raw_root = Path(local).expanduser()
        if not raw_root.is_absolute():
            raw_root = get_base_path() / raw_root
        lexical_root = Path(os.path.abspath(os.fspath(raw_root)))
        cls._assert_no_reparse(lexical_root)
        data_root = resolve_verified_local_path(local)
        cls._assert_no_reparse(data_root)
        return data_root, normal, scheduled, layout_version

    @staticmethod
    def _segments(value: object) -> Tuple[ReclassificationAgencySegment, ...]:
        if not isinstance(value, Mapping):
            return ()
        raw_segments = value.get("segments")
        if not isinstance(raw_segments, list):
            return ()
        result: list[ReclassificationAgencySegment] = []
        for raw in raw_segments:
            if not isinstance(raw, Mapping):
                continue
            result.append(
                ReclassificationAgencySegment(
                    str(raw.get("level") or "").strip(),
                    str(raw.get("label") or "").strip(),
                    str(raw.get("code") or "").strip(),
                )
            )
        return tuple(result)

    @staticmethod
    def _record_identity(record: Mapping[str, Any]) -> tuple[str, str, str]:
        """再分類済みの旧履歴を抑止する安定した文書identity。"""

        stored_path = str(
            record.get("target_path") or record.get("path") or ""
        )
        expected_format = DownloadHistory.normalize_expected_format(
            str(record.get("expected_format") or ""),
            Path(stored_path or "file"),
        )
        return (
            str(record.get("url") or ""),
            expected_format,
            str(record.get("document_id") or ""),
        )

    @staticmethod
    def _record_fingerprint(record: Mapping[str, Any]) -> str:
        payload = json.dumps(
            dict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _record_file_is_valid(
        self,
        history: DownloadHistory,
        record: Mapping[str, Any],
    ) -> bool:
        """成功行を旧pathの置換根拠に使えるか実体まで検証する。"""

        try:
            stored_path = str(
                record.get("target_path") or record.get("path") or ""
            )
            lexical = self._history_lexical_path(history, stored_path)
            self._assert_no_reparse(lexical)
            target = history.actual_path(stored_path)
            size = int(record.get("size", -1))
            sha256 = str(record.get("sha256") or "")
            expected_format = DownloadHistory.normalize_expected_format(
                str(record.get("expected_format") or ""),
                target,
            )
        except (OSError, TypeError, ValueError):
            return False
        valid, _ = history.validate_file(
            target,
            expected_size=size,
            expected_sha256=sha256,
            expected_format=expected_format,
        )
        return valid

    @staticmethod
    def _coerce_resolver_option(
        value: object,
    ) -> Optional[ReclassificationAgencySegment]:
        if isinstance(value, ReclassificationAgencySegment):
            level = value.level or "saibunrui"
            return ReclassificationAgencySegment(level, value.label, value.code)
        if isinstance(value, Mapping):
            label = str(value.get("label") or "").strip()
            code = str(value.get("code") or "").strip()
            level = str(value.get("level") or "saibunrui").strip()
        else:
            label = str(getattr(value, "label", "") or "").strip()
            code = str(getattr(value, "code", "") or "").strip()
            raw_level = getattr(value, "level", "saibunrui")
            level = str(getattr(raw_level, "value", raw_level) or "saibunrui")
        if not label or level != "saibunrui":
            return None
        return ReclassificationAgencySegment(level, label, code)

    @staticmethod
    def _uses_office_fallback(
        agency_path: object,
        segments: Sequence[ReclassificationAgencySegment],
        office_name: str,
    ) -> bool:
        """Naming v2が3階層後へ追加したoffice要素かを判定する。"""

        if len(segments) != 3 or not office_name:
            return False
        if any(
            ReclassificationService._text_matches(
                segment.label,
                office_name,
            )
            for segment in segments
        ):
            return False
        if not isinstance(agency_path, Mapping):
            return False
        try:
            if int(agency_path.get("version", 1)) < 2:
                return False
        except (TypeError, ValueError):
            return False
        resolution = agency_path.get("resolution")
        return bool(
            isinstance(resolution, Mapping)
            and str(resolution.get("status") or "").strip().casefold()
            == "unresolved"
        )

    @staticmethod
    def _text_matches(left: str, right: str) -> bool:
        def normalize(value: str) -> str:
            normalized = unicodedata.normalize("NFKC", str(value or ""))
            return re.sub(
                r"[\s\u3000・･／/()（）]+",
                "",
                normalized,
            ).casefold()

        normalized_left = normalize(left)
        normalized_right = normalize(right)
        return bool(
            normalized_left
            and normalized_right
            and (
                normalized_left == normalized_right
                or normalized_left in normalized_right
                or normalized_right in normalized_left
            )
        )

    @staticmethod
    def _integer(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _cancelled(cancel_check: Optional[CancelCheck]) -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception:
            return False

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _progress(
        self,
        callback: Optional[Callable[[ReclassificationProgress], None]],
        phase: ReclassificationPhase,
        current: int,
        total: int,
        message: str,
        candidate_id: str = "",
    ) -> None:
        if callback is None:
            return
        try:
            callback(
                ReclassificationProgress(
                    phase,
                    current,
                    total,
                    message,
                    candidate_id,
                )
            )
        except Exception as exc:
            self.logger.warning(f"再分類の進捗通知に失敗しました: {exc}")

    def _log_scan_candidate(
        self,
        candidate: ReclassificationCandidate,
    ) -> None:
        payload = self._candidate_log_fields(candidate)
        payload.update(
            {
                "state": candidate.state.value,
                "reason_code": candidate.reason_code,
                "reason": candidate.reason,
            }
        )
        level = (
            "info"
            if candidate.actionable
            else "warning"
        )
        self._structured_log(
            level,
            "reclassification.scan.candidate",
            payload,
        )

    def _log_scan_summary(self, plan: ReclassificationPlan) -> None:
        payload = {
            "plan_id": plan.plan_id,
            "history_files": len(plan.history_files),
            "scanned_records": plan.scanned_records,
            "candidates": len(plan.candidates),
            "actionable": plan.actionable_count,
            "move": plan.move_count,
            "target_reuse": plan.target_reuse_count,
            "unresolved": plan.unresolved_count,
            "invalid": plan.invalid_count,
            "conflict": plan.conflict_count,
            "cancelled": plan.cancelled,
            "issue_codes": [issue.reason_code for issue in plan.issues],
        }
        has_warning = bool(
            plan.cancelled
            or plan.issues
            or plan.unresolved_count
            or plan.invalid_count
            or plan.conflict_count
        )
        self._structured_log(
            "warning" if has_warning else "info",
            "reclassification.scan.summary",
            payload,
        )

    def _log_apply_result(
        self,
        result: ReclassificationApplyResult,
        candidates: Mapping[str, ReclassificationCandidate],
    ) -> None:
        warning_statuses = {
            ReclassificationApplyStatus.CONFLICT,
            ReclassificationApplyStatus.INVALID,
            ReclassificationApplyStatus.CANCELLED,
            ReclassificationApplyStatus.FAILED,
            ReclassificationApplyStatus.LOCKED,
        }
        for outcome in result.outcomes:
            candidate = candidates.get(outcome.candidate_id)
            payload: dict[str, object] = {
                "candidate_id": outcome.candidate_id,
                "source_path": str(outcome.source_path),
                "target_path": str(outcome.target_path),
                "status": outcome.status.value,
                "reason_code": outcome.reason_code,
                "reason": outcome.reason,
                "source_preserved": outcome.source_path.is_file(),
            }
            if candidate is not None:
                payload.update(self._candidate_log_fields(candidate))
            self._structured_log(
                "warning" if outcome.status in warning_statuses else "info",
                "reclassification.apply.outcome",
                payload,
            )
        summary = {
            "plan_id": result.plan_id,
            "total": len(result.outcomes),
            "moved": result.moved_count,
            "target_reused": result.target_reused_count,
            "conflict": result.conflict_count,
            "invalid": result.invalid_count,
            "skipped": result.skipped_count,
            "failed": result.failed_count,
            "cancelled": result.cancelled_count,
            "locked": sum(
                outcome.status is ReclassificationApplyStatus.LOCKED
                for outcome in result.outcomes
            ),
            "issue_codes": [issue.reason_code for issue in result.issues],
        }
        has_warning = bool(
            result.issues
            or result.cancelled
            or any(
                outcome.status in warning_statuses
                for outcome in result.outcomes
            )
        )
        self._structured_log(
            "warning" if has_warning else "info",
            "reclassification.apply.summary",
            summary,
        )

    @staticmethod
    def _candidate_log_fields(
        candidate: ReclassificationCandidate,
    ) -> dict[str, object]:
        return {
            "candidate_id": candidate.candidate_id,
            "run_kind": candidate.run_kind.value,
            "storage_key": candidate.storage_key,
            "project_name": candidate.project_name,
            "document_name": candidate.document_name,
            "source_path": str(candidate.source_path),
            "target_path": str(candidate.target_path),
        }

    def _structured_log(
        self,
        level: str,
        event: str,
        payload: Mapping[str, object],
    ) -> None:
        try:
            writer = getattr(self.logger, level)
            writer(
                event
                + " "
                + json.dumps(
                    dict(payload),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        except Exception:
            # 診断出力の失敗で、検証済みfile処理の成否を変えない。
            return

    @staticmethod
    def _outcome(
        candidate: ReclassificationCandidate,
        status: ReclassificationApplyStatus,
        reason_code: str,
        reason: str,
    ) -> ReclassificationOutcome:
        return ReclassificationOutcome(
            candidate.candidate_id,
            status,
            candidate.source_path,
            candidate.target_path,
            reason_code,
            reason,
        )


__all__ = [
    "ReclassificationAgencyQuery",
    "ReclassificationAgencyResolver",
    "ReclassificationAgencySegment",
    "ReclassificationApplyResult",
    "ReclassificationApplyStatus",
    "ReclassificationCandidate",
    "ReclassificationCandidateState",
    "ReclassificationIssue",
    "ReclassificationOutcome",
    "ReclassificationPhase",
    "ReclassificationPlan",
    "ReclassificationProgress",
    "ReclassificationResult",
    "ReclassificationService",
]
