# -*- coding: utf-8 -*-

"""ダウンロードタスクを保持するデータモデル"""

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from .download_diagnostics import DownloadIssue, DownloadMode
from .file_info import FileInfo


@dataclass
class DownloadTask:
    """ダウンロードタスクを保持するデータモデル"""

    file_info: FileInfo
    local_path: str
    status: str = "pending"  # pending, downloading, completed, failed, skipped, cancelled
    error_message: str = ""
    retry_count: int = 0
    issues: List[DownloadIssue] = field(default_factory=list)
    processing_mode: DownloadMode = DownloadMode.DIRECT
    bytes_written: int = 0
    sha256: str = ""
    validation_kind: str = ""
    reuse_kind: str = ""

    def mark_downloading(self):
        """ダウンロード中にマーク"""
        self.status = "downloading"

    def mark_completed(
        self,
        issues: Optional[Iterable[DownloadIssue]] = None,
        processing_mode: Optional[DownloadMode] = None,
    ):
        """完了にマーク"""
        self.status = "completed"
        self.error_message = ""
        self._update_diagnostics(issues, processing_mode)

    def mark_failed(
        self,
        error_message: str,
        issues: Optional[Iterable[DownloadIssue]] = None,
        processing_mode: Optional[DownloadMode] = None,
    ):
        """失敗にマーク"""
        self.status = "failed"
        self.error_message = error_message
        self.retry_count += 1
        self._update_diagnostics(issues, processing_mode)

    def mark_cancelled(
        self,
        error_message: str = "キャンセルされました",
        issues: Optional[Iterable[DownloadIssue]] = None,
        processing_mode: Optional[DownloadMode] = None,
    ):
        """キャンセル済みにマーク"""
        self.status = "cancelled"
        self.error_message = error_message
        self._update_diagnostics(issues, processing_mode)

    def _update_diagnostics(
        self,
        issues: Optional[Iterable[DownloadIssue]],
        processing_mode: Optional[DownloadMode],
    ) -> None:
        """指定された診断情報だけを更新し、旧呼び出しの値は保持する。"""
        if issues is not None:
            self.issues = list(issues)
        if processing_mode is not None:
            self.processing_mode = processing_mode

    def can_retry(self, max_retries: int = 3) -> bool:
        """リトライ可能かどうかをチェック"""
        return self.status == "failed" and self.retry_count < max_retries
