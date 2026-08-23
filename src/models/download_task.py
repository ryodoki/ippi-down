# -*- coding: utf-8 -*-

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
    # 失敗理由別サマリー用のフィールド（FR-005）
    http_status: Optional[int] = None  # HTTPステータスコード
    error_type: str = ""  # エラー種別: network, rate_limit, http_4xx, http_5xx, filesystem, other
    exception_type: str = ""  # 例外クラス名（無ければ空文字）
    url: str = ""  # ダウンロードURL（FileInfoからコピー）
    retry_attempts: int = 0  # 実際に試行した回数

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

