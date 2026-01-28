"""ダウンロードタスクを保持するデータモデル"""

from dataclasses import dataclass
from typing import Optional
from .file_info import FileInfo


@dataclass
class DownloadTask:
    """ダウンロードタスクを保持するデータモデル"""

    file_info: FileInfo
    local_path: str
    status: str = "pending"  # pending, downloading, completed, failed
    error_message: str = ""
    retry_count: int = 0

    def mark_downloading(self):
        """ダウンロード中にマーク"""
        self.status = "downloading"

    def mark_completed(self):
        """完了にマーク"""
        self.status = "completed"
        self.error_message = ""

    def mark_failed(self, error_message: str):
        """失敗にマーク"""
        self.status = "failed"
        self.error_message = error_message
        self.retry_count += 1

    def can_retry(self, max_retries: int = 3) -> bool:
        """リトライ可能かどうかをチェック"""
        return self.status == "failed" and self.retry_count < max_retries

