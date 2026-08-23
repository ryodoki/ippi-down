# -*- coding: utf-8 -*-

"""ダウンロード結果を保持するデータモデル"""

from dataclasses import dataclass, field
from typing import List
from pathlib import Path
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
        # totalは初期化時に設定済みのため、ここではインクリメントしない

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

    def summarize_failures(self) -> dict[str, int]:
        """失敗理由別件数サマリーを生成（FR-005）
        
        Returns:
            失敗理由別の件数辞書
            - network: ネットワークエラー（タイムアウト、接続エラー）
            - rate_limit: 429（Too Many Requests）
            - http_5xx: サーバーエラー（500-599）
            - http_4xx: クライアントエラー（400-499、429以外）
            - filesystem: ファイルシステムエラー
            - other: その他
        """
        summary = {
            "network": 0,
            "rate_limit": 0,
            "http_5xx": 0,
            "http_4xx": 0,
            "filesystem": 0,
            "other": 0,
        }
        
        for task in self.tasks:
            if task.status == "failed" and task.error_type:
                error_type = task.error_type
                if error_type in summary:
                    summary[error_type] += 1
                else:
                    summary["other"] += 1
        
        return summary

    def get_save_directories(self) -> List[str]:
        """実際にファイルが保存されたディレクトリ一覧（重複なし・ソート済み）"""
        dirs = set()
        for task in self.tasks:
            if task.local_path and task.status in ("completed", "skipped"):
                dirs.add(str(Path(task.local_path).parent))
        return sorted(dirs)

    def summarize_skips(self) -> dict[str, int]:
        """スキップ理由別件数（FR-005 / FR-008）"""
        summary: dict[str, int] = {}
        for task in self.tasks:
            if task.status != "skipped":
                continue
            reason = task.error_message or "duplicate"
            summary[reason] = summary.get(reason, 0) + 1
        return summary

    def get_completed_paths(self, limit: int = 5) -> List[str]:
        """今回新規保存されたファイルパス（最大 limit 件）"""
        paths = [
            task.local_path
            for task in self.tasks
            if task.status == "completed" and task.local_path
        ]
        return paths[:limit]
