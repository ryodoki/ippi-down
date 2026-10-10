# -*- coding: utf-8 -*-

"""ダウンロード結果を保持するデータモデル"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from .download_diagnostics import DownloadIssueCode, DownloadMode
from .download_task import DownloadTask


class RunOutcome(str, Enum):
    """アプリケーション実行の終了状態。"""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NO_MATCH = "NO_MATCH"


@dataclass
class DownloadResult:
    """ダウンロード結果を保持するデータモデル"""

    total: int = 0  # 総ファイル数
    success: int = 0  # 成功数
    failed: int = 0  # 失敗数
    skipped: int = 0  # スキップ数
    cancelled: int = 0  # キャンセル数
    tasks: List[DownloadTask] = field(default_factory=list)
    _dynamic_total: bool = field(init=False, repr=False, compare=False)
    _task_indexes: Dict[int, int] = field(
        init=False,
        repr=False,
        compare=False,
        default_factory=dict,
    )
    _task_statuses: List[str] = field(
        init=False,
        repr=False,
        compare=False,
        default_factory=list,
    )

    def __post_init__(self) -> None:
        """期待総数と、集計値だけを渡す旧APIの両方を初期化する。

        ``total > 0`` は呼び出し側が登録した期待総数として固定する。
        引数なしの ``DownloadResult()`` は従来どおり、追加されたタスク数を
        総数として扱う動的モードにする。
        """
        if self.total < 0:
            raise ValueError("totalは0以上である必要があります")

        has_summary_counts = any(
            count != 0
            for count in (
                self.success,
                self.failed,
                self.skipped,
                self.cancelled,
            )
        )
        self._dynamic_total = self.total == 0 and not has_summary_counts

        if self.tasks:
            if not self._dynamic_total and len(self.tasks) > self.total:
                raise ValueError(
                    "登録済みタスク数が期待総数を超えています: "
                    f"tasks={len(self.tasks)}, total={self.total}"
                )
            if self._dynamic_total:
                self.total = len(self.tasks)
            self._recount()

    def add_task(self, task: DownloadTask):
        """タスクを追加する。

        ``total`` を先に指定した既存コードとの互換性を保ちつつ、
        タスク追加で総数を二重加算しない。
        """
        if not self._dynamic_total and len(self.tasks) >= self.total:
            raise ValueError(
                "タスク数が期待総数を超えるため追加できません: "
                f"total={self.total}"
            )
        self.tasks.append(task)
        task_index = len(self.tasks) - 1
        self._task_indexes[id(task)] = task_index
        self._task_statuses.append(task.status)
        self._apply_status_delta(task.status, 1)
        if self._dynamic_total:
            self.total = len(self.tasks)

    def update_status(self, task: DownloadTask):
        """指定タスクの状態差分だけを件数へ反映する。"""
        task_index = self._task_indexes.get(id(task))
        if (
            task_index is None
            or task_index >= len(self.tasks)
            or self.tasks[task_index] is not task
        ):
            # 公開tasksリストを直接変更する旧コードにも安全側で対応する。
            self._recount()
            return
        previous = self._task_statuses[task_index]
        current = task.status
        if previous == current:
            return
        self._apply_status_delta(previous, -1)
        self._apply_status_delta(current, 1)
        self._task_statuses[task_index] = current

    def _apply_status_delta(self, status: str, amount: int) -> None:
        """終端状態のカウンターを一定時間で更新する。"""
        attribute = {
            "completed": "success",
            "failed": "failed",
            "skipped": "skipped",
            "cancelled": "cancelled",
        }.get(status)
        if attribute is not None:
            setattr(self, attribute, getattr(self, attribute) + amount)

    def _recount(self) -> None:
        """タスクを唯一の根拠として状態別件数を再集計する。"""
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.cancelled = 0
        self._task_indexes.clear()
        self._task_statuses.clear()
        for index, task in enumerate(self.tasks):
            self._task_indexes[id(task)] = index
            self._task_statuses.append(task.status)
            self._apply_status_delta(task.status, 1)

    @property
    def accounted(self) -> int:
        """終了状態が確定したタスク数。"""
        return self.success + self.failed + self.skipped + self.cancelled

    @property
    def is_consistent(self) -> bool:
        """状態別件数の合計が総数と一致するか。"""
        if self.tasks:
            return (
                len(self.tasks) == self.total
                and self.accounted == len(self.tasks)
            )
        # 集計値だけを渡す旧APIも検証可能なまま維持する。
        return self.accounted == self.total

    @property
    def outcome(self) -> RunOutcome:
        """件数から実行結果を導出する。"""
        if self.total == 0:
            return RunOutcome.NO_MATCH
        if self.cancelled > 0:
            return RunOutcome.CANCELLED
        completed = self.success + self.skipped
        if self.failed == 0 and completed == self.total:
            return RunOutcome.SUCCESS
        if self.failed > 0 and completed > 0:
            return RunOutcome.PARTIAL
        return RunOutcome.FAILED

    @property
    def failed_tasks(self) -> List[DownloadTask]:
        """失敗したタスクを登録順で返す。"""
        return [task for task in self.tasks if task.status == "failed"]

    @property
    def reused(self) -> int:
        """検証済みの保存済みファイルを再利用した件数。

        ``skipped`` は既存APIとの互換性のため維持し、新しい表示では
        意図が明確なこの名前を使用する。
        """
        return self.skipped

    @property
    def legacy_reused(self) -> int:
        """旧名称の実ファイルを履歴エイリアスで再利用した件数。"""
        return sum(
            task.status == "skipped"
            and task.reuse_kind == "LEGACY_PATH_ALIAS"
            for task in self.tasks
        )

    @property
    def issue_counts(self) -> Dict[DownloadIssueCode, int]:
        """全タスクの診断理由をコード単位で集計する。"""
        counts: Dict[DownloadIssueCode, int] = {}
        for task in self.tasks:
            for issue in task.issues:
                counts[issue.code] = counts.get(issue.code, 0) + 1
        return counts

    @property
    def converted(self) -> int:
        """HTMLからPDFへ変換して正常終了した件数。"""
        return sum(
            task.status == "completed"
            and task.processing_mode == DownloadMode.HTML_TO_PDF
            for task in self.tasks
        )

    def get_success_rate(self) -> float:
        """成功率を取得（%）"""
        if self.total == 0:
            return 0.0
        return (self.success / self.total) * 100
