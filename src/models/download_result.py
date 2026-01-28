"""ダウンロード結果を保持するデータモデル"""

from dataclasses import dataclass, field
from typing import List
from .download_task import DownloadTask


@dataclass
class DownloadResult:
    """ダウンロード結果を保持するデータモデル"""

    total: int = 0  # 総ファイル数
    success: int = 0  # 成功数
    failed: int = 0  # 失敗数
    skipped: int = 0  # スキップ数
    tasks: List[DownloadTask] = field(default_factory=list)

    def add_task(self, task: DownloadTask):
        """タスクを追加"""
        self.tasks.append(task)
        self.total += 1

    def update_status(self, task: DownloadTask):
        """タスクのステータスを更新"""
        if task.status == "completed":
            self.success += 1
        elif task.status == "failed":
            self.failed += 1
        elif task.status == "skipped":
            self.skipped += 1
        elif task.status == "pending":
            self.skipped += 1

    def get_success_rate(self) -> float:
        """成功率を取得（%）"""
        if self.total == 0:
            return 0.0
        return (self.success / self.total) * 100

