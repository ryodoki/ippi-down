# -*- coding: utf-8 -*-

"""HTTP通信と安全なファイルダウンロードを提供する。"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
import zipfile
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter

from .logger import Logger
from .network_audit import NetworkAuditLedger
from .outbound_policy import (
    NetworkPurpose,
    OutboundPolicy,
    OutboundPolicyError,
    PolicyEnforcedSession,
    RequestTransport,
)
from ..app.exceptions import NetworkError, RateLimitError
from ..models.download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadMode,
    DownloadStage,
    IssueSeverity,
)

if TYPE_CHECKING:
    from ..core.html_to_pdf import HtmlToPdfConverter


class DownloadStatus(str, Enum):
    """HTTPダウンロード単体の終了状態。"""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class DownloadFileResult:
    """ファイルダウンロードの詳細結果。

    ``__bool__`` を実装し、従来の ``if download_file(...):`` と互換にする。
    """

    status: DownloadStatus
    url: str
    save_path: str
    http_status: Optional[int] = None
    content_type: str = ""
    bytes_written: int = 0
    sha256: str = ""
    attempts: int = 0
    error: str = ""
    processing_mode: DownloadMode = DownloadMode.DIRECT
    processor: str = ""
    final_url: str = ""
    content_length: Optional[int] = None
    content_disposition: str = ""
    issues: Tuple[DownloadIssue, ...] = ()

    @property
    def success(self) -> bool:
        return self.status == DownloadStatus.SUCCESS

    @property
    def cancelled(self) -> bool:
        return self.status == DownloadStatus.CANCELLED

    @property
    def primary_issue(self) -> Optional[DownloadIssue]:
        """代表理由を返す。複数ある場合は最初のエラーを優先する。"""
        return next(
            (issue for issue in self.issues if issue.severity == IssueSeverity.ERROR),
            self.issues[0] if self.issues else None,
        )

    @property
    def conversion_engine(self) -> str:
        """変換エンジン名。既存の``processor``フィールドとの互換別名。"""
        return self.processor

    def __bool__(self) -> bool:
        return self.success


class _DownloadFailure(Exception):
    """再試行可否と構造化理由を保持する内部例外。"""

    def __init__(
        self,
        code: DownloadIssueCode,
        stage: DownloadStage,
        message: str,
        *,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.issue = DownloadIssue(code, stage, message)
        self.retryable = retryable


class HTTPClient:
    """HTTP通信を行うクラス（セッション管理含む）。"""

    _global_request_lock = threading.Lock()
    _global_last_request_started = 0.0

    def __init__(
        self,
        logger: Optional[Logger] = None,
        timeout: int = 30,
        download_timeout: int = 30,
        requests_per_second: float = 1.0,
        *,
        policy: Optional[OutboundPolicy] = None,
        transport: Optional[RequestTransport] = None,
        audit_ledger: Optional[NetworkAuditLedger] = None,
    ):
        self.logger = logger or Logger()
        self.timeout = timeout
        self.download_timeout = download_timeout
        self.requests_per_second = max(0.0, requests_per_second)
        self.policy = policy or OutboundPolicy()
        self.audit_ledger = audit_ledger or NetworkAuditLedger()
        self.session = PolicyEnforcedSession(
            self.policy,
            transport=transport,
            audit_callback=self.audit_ledger.record,
        )
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )

        # リトライはこのクラスで一元管理する。HTTPAdapter側では再試行しない。
        if transport is None:
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=0,
            )
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    def _purpose_context(self, purpose: Optional[NetworkPurpose | str]):
        """古いテスト用Sessionとも互換な用途contextを返す。"""

        factory = getattr(self.session, "purpose_context", None)
        if callable(factory):
            return factory(purpose)
        return nullcontext()

    def _throttle(
        self,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """プロセス内の全HTTPClient合計を既定1リクエスト/秒に制限する。"""
        if self.requests_per_second <= 0:
            return
        minimum_interval = 1.0 / self.requests_per_second
        with type(self)._global_request_lock:
            now = time.monotonic()
            wait_seconds = minimum_interval - (
                now - type(self)._global_last_request_started
            )
            if wait_seconds > 0:
                if not self._wait(wait_seconds, cancel_check):
                    raise NetworkError("HTTP待機中にキャンセルされました")
            type(self)._global_last_request_started = time.monotonic()

    @staticmethod
    def _retry_after_seconds(value: Optional[str], fallback: float) -> float:
        """Retry-After（秒またはHTTP-date）を待機秒数へ変換する。"""
        if not value:
            return fallback
        try:
            seconds = float(value)
            if not math.isfinite(seconds):
                return fallback
            return max(0.0, seconds)
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(
                    0.0,
                    (parsed - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                return fallback

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        """429と全5xxだけをHTTP状態に基づく再試行対象とする。"""
        return status_code == 429 or 500 <= status_code < 600

    @staticmethod
    def _is_retryable_request_error(
        error: requests.exceptions.RequestException,
    ) -> bool:
        """一時的な通信例外だけを再試行対象とする。"""
        return isinstance(
            error,
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ),
        )

    @staticmethod
    def _is_cancelled(cancel_check: Optional[Callable[[], bool]]) -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception:
            return False

    def _wait(
        self,
        seconds: float,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """待機する。キャンセルされた場合はFalseを返す。"""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if self._is_cancelled(cancel_check):
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.1, remaining))

    def _request(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        **kwargs,
    ) -> requests.Response:
        """通常リクエスト。``max_retries`` は初回を含む最大試行回数。"""
        max_attempts = max(1, min(int(max_retries), 3))
        last_error: Optional[Exception] = None
        request_timeout = kwargs.pop("timeout", self.timeout)
        cancel_check = kwargs.pop("cancel_check", None)
        purpose = kwargs.pop("purpose", None)

        for attempt in range(1, max_attempts + 1):
            try:
                if self._is_cancelled(cancel_check):
                    raise NetworkError("HTTPリクエストがキャンセルされました")
                self._throttle(cancel_check)
                with self._purpose_context(purpose):
                    response = self.session.request(
                        method,
                        url,
                        timeout=request_timeout,
                        **kwargs,
                    )
                if response.status_code == 429:
                    wait_time = self._retry_after_seconds(
                        response.headers.get("Retry-After"),
                        float(2 ** (attempt - 1)),
                    )
                    if attempt == max_attempts:
                        response.close()
                        raise RateLimitError(
                            f"レート制限に達しました: {url}",
                            retry_after=int(wait_time),
                        )
                    self.logger.warning(
                        f"レート制限: {wait_time:.1f}秒後に再試行 "
                        f"({attempt}/{max_attempts})"
                    )
                    response.close()
                    if not self._wait(wait_time, cancel_check):
                        raise NetworkError("HTTP再試行待機中にキャンセルされました")
                    continue
                if (
                    self._is_retryable_status(response.status_code)
                    and attempt < max_attempts
                ):
                    wait_time = self._retry_after_seconds(
                        response.headers.get("Retry-After"),
                        float(2 ** (attempt - 1)),
                    )
                    self.logger.warning(
                        f"HTTP {response.status_code}: {wait_time:.1f}秒後に再試行 "
                        f"({attempt}/{max_attempts})"
                    )
                    response.close()
                    if not self._wait(wait_time, cancel_check):
                        raise NetworkError("HTTP再試行待機中にキャンセルされました")
                    continue
                response.raise_for_status()
                return response
            except OutboundPolicyError:
                raise
            except RateLimitError:
                raise
            except requests.exceptions.RequestException as exc:
                last_error = exc
                error_response = None
                if isinstance(exc, requests.exceptions.HTTPError):
                    error_response = getattr(exc, "response", None)
                    status_code = getattr(error_response, "status_code", None)
                    if status_code is None or not self._is_retryable_status(
                        status_code
                    ):
                        if error_response is not None:
                            error_response.close()
                        break
                elif not self._is_retryable_request_error(exc):
                    break
                if attempt == max_attempts:
                    if error_response is not None:
                        error_response.close()
                    break
                if error_response is not None:
                    error_response.close()
                if not self._wait(float(2 ** (attempt - 1)), cancel_check):
                    raise NetworkError("HTTP再試行待機中にキャンセルされました")

        message = f"{method.upper()}リクエスト失敗: {url} - {last_error}"
        self.logger.error(message)
        raise NetworkError(message)

    def get(self, url: str, max_retries: int = 3, **kwargs) -> requests.Response:
        return self._request("GET", url, max_retries=max_retries, **kwargs)

    def post(
        self,
        url: str,
        data: Optional[Dict] = None,
        max_retries: int = 3,
        **kwargs,
    ) -> requests.Response:
        return self._request("POST", url, data=data, max_retries=max_retries, **kwargs)

    @staticmethod
    def _looks_like_html(chunk: bytes) -> bool:
        """互換API。HTML/XML系のエラーペイロードを保守的に判定する。"""
        return HTTPClient._looks_like_error_payload(chunk)

    @staticmethod
    def _looks_like_error_payload(chunk: bytes) -> bool:
        """BOM・コメント・空白を除いた先頭からHTML/JSON/XMLを検出する。"""
        prefix = chunk[:4096]
        if prefix.startswith(b"\xef\xbb\xbf"):
            prefix = prefix[3:]
        prefix = prefix.lstrip().lower()
        while prefix.startswith(b"<!--"):
            comment_end = prefix.find(b"-->")
            if comment_end < 0:
                return True
            prefix = prefix[comment_end + 3 :].lstrip()
        # RTFは正常な文書もJSONと同じ ``{`` から始まる。
        if prefix.startswith(b"{\\rtf"):
            return False
        return prefix.startswith(
            (
                b"<html",
                b"<!doctype html",
                b"<head",
                b"<body",
                b"<?xml",
                b"<error",
                b"<problem",
                b"{",
                b"[",
            )
        )

    @staticmethod
    def _looks_like_html_document(chunk: bytes) -> bool:
        """実データの先頭からHTML文書だけを判定する。

        JSON/XMLエラーをHTML→PDF変換へ渡さないため、
        ``_looks_like_error_payload`` とは意図的に分離している。
        """
        prefix = chunk[:8192]
        if prefix.startswith(b"\xef\xbb\xbf"):
            prefix = prefix[3:]
        prefix = prefix.lstrip().lower()
        while prefix.startswith(b"<!--"):
            comment_end = prefix.find(b"-->")
            if comment_end < 0:
                return False
            prefix = prefix[comment_end + 3 :].lstrip()
        if prefix.startswith(b"<?xml"):
            declaration_end = prefix.find(b"?>")
            if declaration_end < 0:
                return False
            prefix = prefix[declaration_end + 2 :].lstrip()
        return prefix.startswith(
            (
                b"<!doctype html",
                b"<html",
                b"<head",
                b"<body",
            )
        )

    @staticmethod
    def _invalid_content_type(content_type: str) -> bool:
        media_type = content_type.split(";", 1)[0].strip().lower()
        if not media_type:
            return True
        if media_type in {"text/html", "application/xhtml+xml"}:
            return True
        return (
            media_type.startswith("text/")
            or media_type.endswith("+json")
            or media_type.endswith("+xml")
            or media_type
            in {
                "application/json",
                "application/xml",
            }
        )

    @staticmethod
    def _content_type_matches_path(content_type: str, save_path: Path) -> bool:
        """保存拡張子に対して許容できるContent-Typeかを判定する。"""
        media_type = content_type.split(";", 1)[0].strip().lower()
        if not media_type:
            return False

        generic_binary = {
            "application/octet-stream",
            "binary/octet-stream",
            "application/download",
            "application/x-download",
            "application/force-download",
        }
        allowed_by_suffix = {
            ".pdf": {"application/pdf"},
            ".docx": {
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document",
                "application/zip",
            },
            ".xlsx": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/zip",
            },
            ".pptx": {
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation",
                "application/zip",
            },
            ".zip": {
                "application/zip",
                "application/x-zip-compressed",
            },
            ".doc": {
                "application/msword",
                "application/vnd.ms-word",
            },
            ".xls": {
                "application/vnd.ms-excel",
            },
            ".ppt": {
                "application/vnd.ms-powerpoint",
            },
            ".rtf": {
                "application/rtf",
                "text/rtf",
            },
        }
        suffix = save_path.suffix.lower()
        allowed = allowed_by_suffix.get(suffix)
        if allowed is not None:
            return media_type in allowed or media_type in generic_binary
        return not HTTPClient._invalid_content_type(content_type)

    @staticmethod
    def _matches_expected_signature(chunk: bytes, save_path: Path) -> bool:
        """既知の正式対象形式について拡張子とマジック番号を照合する。"""
        suffix = save_path.suffix.lower()
        signatures = {
            ".pdf": (b"%PDF-",),
            ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            ".xlsx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            ".pptx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
            ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
            ".ppt": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
            ".rtf": (b"{\\rtf",),
        }
        expected = signatures.get(suffix)
        return expected is None or chunk.startswith(expected)

    @staticmethod
    def _validate_ooxml_container(
        file_path: Path,
        save_path: Path,
    ) -> str:
        """OOXMLのZIP内部が保存拡張子と一致するか検証する。"""
        required_part_by_suffix = {
            ".docx": "word/document.xml",
            ".xlsx": "xl/workbook.xml",
            ".pptx": "ppt/presentation.xml",
        }
        required_part = required_part_by_suffix.get(save_path.suffix.lower())
        if required_part is None:
            return ""
        try:
            with zipfile.ZipFile(file_path, "r") as archive:
                names = {name.replace("\\", "/").lower() for name in archive.namelist()}
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            return f"OOXMLコンテナを検証できません: {exc}"

        if "[content_types].xml" not in names:
            return "OOXMLに[Content_Types].xmlがありません"
        if required_part not in names:
            return (
                f"拡張子{save_path.suffix.lower()}に必要な{required_part}がありません"
            )
        return ""

    def _remove_part(self, part_path: Path) -> str:
        """作業ファイルを削除し、失敗時は診断文字列を返す。"""
        try:
            part_path.unlink(missing_ok=True)
            return ""
        except OSError as exc:
            message = f"作業ファイルを削除できません: {part_path} - {exc}"
            self.logger.warning(message)
            return message

    def download_file(
        self,
        url: str,
        save_path: str,
        progress_callback: Optional[Callable[[int, int], Optional[bool]]] = None,
        max_retries: int = 3,
        referer: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        allow_html_to_pdf: bool = False,
        html_to_pdf_converter: Optional["HtmlToPdfConverter"] = None,
        document_name: str = "",
        project_name: str = "",
        run_id: str = "",
        document_id: str = "",
    ) -> DownloadFileResult:
        """ファイルを同一ディレクトリの ``.part`` へ取得して原子的に確定する。

        ``max_retries`` は互換性のため引数名を維持するが、意味は
        「初回を含む最大試行回数」であり、上限は3回。許可済みの
        入札調書HTMLは一度だけ取得し、内蔵生成または監視下のEdge変換後に
        PDFを確定する。
        """
        from urllib.parse import urlparse

        max_attempts = max(1, min(int(max_retries), 3))
        save_path_obj = Path(save_path)
        part_path = save_path_obj.with_name(save_path_obj.name + ".part")
        source_token = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        html_source_path = save_path_obj.parent / (
            f".ippi-source-{source_token}.html.part"
        )

        def issue(
            code: DownloadIssueCode,
            stage: DownloadStage,
            message: str,
            *,
            severity: IssueSeverity = IssueSeverity.ERROR,
            details: Optional[Dict[str, object]] = None,
        ) -> DownloadIssue:
            return DownloadIssue(
                code,
                stage,
                message,
                severity,
                details or {},
            )

        last_http_status: Optional[int] = None
        last_content_type = ""
        last_content_length: Optional[int] = None
        last_content_disposition = ""
        last_final_url = url

        def make_result(
            status: DownloadStatus,
            *,
            attempt: int,
            error: str = "",
            issues: Tuple[DownloadIssue, ...] = (),
            mode: DownloadMode = DownloadMode.DIRECT,
            processor: str = "",
            bytes_written: int = 0,
            sha256: str = "",
        ) -> DownloadFileResult:
            return DownloadFileResult(
                status,
                url,
                str(save_path_obj),
                http_status=last_http_status,
                content_type=last_content_type,
                bytes_written=bytes_written,
                sha256=sha256,
                attempts=attempt,
                error=error,
                processing_mode=mode,
                processor=processor,
                final_url=last_final_url,
                content_length=last_content_length,
                content_disposition=last_content_disposition,
                issues=issues,
            )

        def cleanup_work_files() -> str:
            messages = [
                self._remove_part(path) for path in (part_path, html_source_path)
            ]
            return "; ".join(message for message in messages if message)

        def cancelled_result(
            attempt: int,
            *,
            mode: DownloadMode = DownloadMode.DIRECT,
            message: str = "キャンセルされました",
            base_issues: Tuple[DownloadIssue, ...] = (),
            processor: str = "",
        ) -> DownloadFileResult:
            cleanup_error = cleanup_work_files()
            result_issues = tuple(base_issues)
            if not any(
                item.code == DownloadIssueCode.CANCELLED for item in result_issues
            ):
                result_issues += (
                    issue(
                        DownloadIssueCode.CANCELLED,
                        DownloadStage.CONVERT
                        if mode == DownloadMode.HTML_TO_PDF
                        else DownloadStage.FETCH,
                        message,
                    ),
                )
            if cleanup_error:
                result_issues += (
                    issue(
                        DownloadIssueCode.TEMP_CLEANUP_FAILED,
                        DownloadStage.CLEANUP,
                        cleanup_error,
                        severity=IssueSeverity.WARNING,
                    ),
                )
            return make_result(
                DownloadStatus.CANCELLED,
                attempt=attempt,
                error=message,
                issues=result_issues,
                mode=mode,
                processor=(
                    processor or ("msedge" if mode == DownloadMode.HTML_TO_PDF else "")
                ),
            )

        try:
            save_path_obj.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            message = f"保存先ディレクトリを作成できません: {exc}"
            save_issue = issue(
                DownloadIssueCode.SAVE_FAILED,
                DownloadStage.COMMIT,
                message,
            )
            return DownloadFileResult(
                DownloadStatus.FAILED,
                url,
                str(save_path_obj),
                attempts=0,
                error=message,
                issues=(save_issue,),
            )
        download_headers = {
            "Accept": (
                "application/pdf,text/html;q=0.9,application/octet-stream,*/*;q=0.8"
                if allow_html_to_pdf
                else "application/pdf,application/octet-stream,*/*"
            ),
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            # Content-Lengthを保存バイト数と厳密比較できるよう圧縮を要求しない。
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if referer:
            download_headers["Referer"] = referer
            parsed_referer = urlparse(referer)
            download_headers["Origin"] = (
                f"{parsed_referer.scheme}://{parsed_referer.netloc}"
            )

        for attempt in range(1, max_attempts + 1):
            response = None
            current_mode = DownloadMode.DIRECT
            current_processor = ""
            last_content_length = None
            last_content_disposition = ""
            cleanup_error = cleanup_work_files()
            if cleanup_error:
                cleanup_issue = issue(
                    DownloadIssueCode.TEMP_CLEANUP_FAILED,
                    DownloadStage.CLEANUP,
                    cleanup_error,
                )
                return make_result(
                    DownloadStatus.FAILED,
                    attempt=attempt - 1,
                    error=cleanup_error,
                    issues=(cleanup_issue,),
                )
            if self._is_cancelled(cancel_check):
                return cancelled_result(attempt - 1)
            try:
                self._throttle(cancel_check)
                with self._purpose_context(NetworkPurpose.DOWNLOAD):
                    response = self.session.get(
                        url,
                        stream=True,
                        timeout=(10, self.download_timeout),
                        headers=download_headers,
                        allow_redirects=True,
                    )
                last_http_status = response.status_code
                last_content_type = response.headers.get("Content-Type", "")
                last_content_disposition = response.headers.get(
                    "Content-Disposition", ""
                )
                last_final_url = getattr(response, "url", url) or url

                if self._is_retryable_status(response.status_code):
                    wait_time = self._retry_after_seconds(
                        response.headers.get("Retry-After"),
                        float(2 ** (attempt - 1)),
                    )
                    code = (
                        DownloadIssueCode.RATE_LIMIT
                        if response.status_code == 429
                        else DownloadIssueCode.HTTP_5XX
                    )
                    raise _DownloadFailure(
                        code,
                        DownloadStage.FETCH,
                        f"HTTP {response.status_code}",
                        retryable=attempt < max_attempts,
                    )

                if response.status_code != 200:
                    code = (
                        DownloadIssueCode.HTTP_4XX
                        if 400 <= response.status_code < 500
                        else DownloadIssueCode.HTTP_STATUS
                    )
                    raise _DownloadFailure(
                        code,
                        DownloadStage.FETCH,
                        f"想定外のHTTP状態です: {response.status_code} "
                        "(完全応答の200のみ受け付けます)",
                    )

                content_length_header = response.headers.get("Content-Length")
                if not content_length_header:
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_LENGTH_MISSING,
                        DownloadStage.FETCH,
                        "Content-Lengthがないため完全性を確認できません",
                    )
                try:
                    expected_size = int(content_length_header)
                except ValueError as exc:
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_LENGTH_INVALID,
                        DownloadStage.FETCH,
                        f"不正なContent-Lengthです: {content_length_header}",
                    ) from exc
                if expected_size <= 0:
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_LENGTH_INVALID,
                        DownloadStage.FETCH,
                        f"不正なContent-Lengthです: {content_length_header}",
                    )
                last_content_length = expected_size

                content_iterator = response.iter_content(chunk_size=8192)
                first_payload_chunk = b""
                for candidate_chunk in content_iterator:
                    if self._is_cancelled(cancel_check):
                        raise InterruptedError("キャンセルされました")
                    if candidate_chunk:
                        first_payload_chunk = candidate_chunk
                        break
                if not first_payload_chunk:
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_LENGTH_MISMATCH,
                        DownloadStage.FETCH,
                        "空のレスポンスです",
                        retryable=True,
                    )

                media_type = last_content_type.split(";", 1)[0].strip().lower()
                header_is_html = media_type in {
                    "text/html",
                    "application/xhtml+xml",
                }
                payload_is_html = self._looks_like_html_document(first_payload_chunk)
                payload_is_expected = self._matches_expected_signature(
                    first_payload_chunk,
                    save_path_obj,
                )
                payload_is_pdf = (
                    save_path_obj.suffix.lower() == ".pdf"
                    and first_payload_chunk.startswith(b"%PDF-")
                )
                if not last_content_type.strip():
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_TYPE_MISMATCH,
                        DownloadStage.CLASSIFY,
                        "Content-Typeがないためファイル形式を確認できません",
                    )
                conversion_mode = bool(
                    payload_is_html
                    and save_path_obj.suffix.lower() == ".pdf"
                    and allow_html_to_pdf
                    and html_to_pdf_converter is not None
                )
                if conversion_mode:
                    current_mode = DownloadMode.HTML_TO_PDF
                    max_html_bytes = int(
                        getattr(
                            html_to_pdf_converter,
                            "max_html_bytes",
                            0,
                        )
                        or 0
                    )
                    if max_html_bytes > 0 and expected_size > max_html_bytes:
                        raise _DownloadFailure(
                            DownloadIssueCode.HTML_STRUCTURE_INVALID,
                            DownloadStage.VALIDATE,
                            "入札調書HTMLが変換可能なサイズ上限を超えています",
                        )
                elif payload_is_html:
                    raise _DownloadFailure(
                        DownloadIssueCode.UNEXPECTED_HTML,
                        DownloadStage.CLASSIFY,
                        "PDFではなくHTMLレスポンスが返されました",
                    )
                elif not payload_is_expected and header_is_html:
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_TYPE_MISMATCH,
                        DownloadStage.CLASSIFY,
                        "HTMLのContent-Typeですが、変換可能なHTML文書ではありません",
                    )
                elif not payload_is_pdf and not self._content_type_matches_path(
                    last_content_type, save_path_obj
                ):
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_TYPE_MISMATCH,
                        DownloadStage.CLASSIFY,
                        f"拡張子{save_path_obj.suffix.lower()}に対して"
                        f"不正なContent-Typeです: "
                        f"{last_content_type or '(missing)'}",
                    )

                digest = hashlib.sha256()
                written = 0
                stream_path = html_source_path if conversion_mode else part_path
                with stream_path.open("wb") as output:
                    for chunk in chain(
                        (first_payload_chunk,),
                        content_iterator,
                    ):
                        if self._is_cancelled(cancel_check):
                            raise InterruptedError("キャンセルされました")
                        if not chunk:
                            continue
                        if (
                            conversion_mode
                            and max_html_bytes > 0
                            and written + len(chunk) > max_html_bytes
                        ):
                            raise _DownloadFailure(
                                DownloadIssueCode.HTML_STRUCTURE_INVALID,
                                DownloadStage.VALIDATE,
                                "入札調書HTMLが変換可能なサイズ上限を超えています",
                            )
                        output.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        if progress_callback:
                            callback_result = progress_callback(written, expected_size)
                            if callback_result is False:
                                raise InterruptedError("キャンセルされました")
                    output.flush()
                    os.fsync(output.fileno())

                if self._is_cancelled(cancel_check):
                    raise InterruptedError("キャンセルされました")
                if written == 0:
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_LENGTH_MISMATCH,
                        DownloadStage.FETCH,
                        "空のレスポンスです",
                        retryable=True,
                    )
                if written != expected_size:
                    raise _DownloadFailure(
                        DownloadIssueCode.CONTENT_LENGTH_MISMATCH,
                        DownloadStage.FETCH,
                        f"Content-Length不一致: expected={expected_size}, "
                        f"actual={written}",
                        retryable=True,
                    )

                result_mode = DownloadMode.DIRECT
                result_processor = ""
                result_issues: Tuple[DownloadIssue, ...] = ()
                if conversion_mode:
                    self.logger.info(
                        "download.convert.start "
                        f'processor=auto file="{save_path_obj.name}" '
                        f'source_type="{last_content_type}"'
                    )
                    try:
                        conversion = html_to_pdf_converter.convert(
                            html_source_path,
                            part_path,
                            cancel_check,
                            source_url=last_final_url,
                            document_name=document_name,
                            project_name=project_name,
                            run_id=run_id,
                            document_id=document_id,
                        )
                    except Exception as exc:
                        reason = " ".join(str(exc).split())[-500:]
                        conversion_issue = issue(
                            DownloadIssueCode.CONVERSION_EXIT_ERROR,
                            DownloadStage.CONVERT,
                            "HTMLからPDFへの変換処理で"
                            f"予期しないエラーが発生しました: {reason}",
                        )
                        cleanup_error = cleanup_work_files()
                        conversion_issues = (conversion_issue,)
                        if cleanup_error:
                            conversion_issues += (
                                issue(
                                    DownloadIssueCode.TEMP_CLEANUP_FAILED,
                                    DownloadStage.CLEANUP,
                                    cleanup_error,
                                    severity=IssueSeverity.WARNING,
                                ),
                            )
                        return make_result(
                            DownloadStatus.FAILED,
                            attempt=attempt,
                            error=conversion_issue.message,
                            issues=conversion_issues,
                            mode=DownloadMode.HTML_TO_PDF,
                            processor="HTML-to-PDF",
                        )
                    edge_version = str(getattr(conversion, "edge_version", "") or "")
                    renderer = str(getattr(conversion, "renderer", "") or "")
                    renderer_version = str(
                        getattr(conversion, "renderer_version", "") or ""
                    )
                    if renderer:
                        conversion_processor = " ".join(
                            value for value in (renderer, renderer_version) if value
                        )
                    else:
                        conversion_processor = str(
                            getattr(conversion, "processor", "") or ""
                        )
                    if not conversion_processor:
                        conversion_processor = edge_version or "Microsoft Edge"
                        if not conversion_processor.casefold().startswith(
                            "microsoft edge"
                        ):
                            conversion_processor = (
                                f"Microsoft Edge {conversion_processor}"
                            )
                    current_processor = conversion_processor
                    source_cleanup_error = self._remove_part(html_source_path)
                    if getattr(conversion, "cancelled", False):
                        conversion_issues = tuple(
                            getattr(conversion, "issues", ()) or ()
                        )
                        if source_cleanup_error:
                            conversion_issues += (
                                issue(
                                    DownloadIssueCode.TEMP_CLEANUP_FAILED,
                                    DownloadStage.CLEANUP,
                                    source_cleanup_error,
                                    severity=IssueSeverity.WARNING,
                                ),
                            )
                        return cancelled_result(
                            attempt,
                            mode=DownloadMode.HTML_TO_PDF,
                            message=(
                                getattr(conversion, "error", "")
                                or "キャンセルされました"
                            ),
                            base_issues=conversion_issues,
                            processor=conversion_processor,
                        )
                    if not getattr(conversion, "success", False):
                        conversion_issues = tuple(
                            getattr(conversion, "issues", ()) or ()
                        )
                        conversion_error = getattr(conversion, "error", "") or (
                            conversion_issues[0].message
                            if conversion_issues
                            else "HTMLからPDFへの変換に失敗しました"
                        )
                        if source_cleanup_error:
                            conversion_issues += (
                                issue(
                                    DownloadIssueCode.TEMP_CLEANUP_FAILED,
                                    DownloadStage.CLEANUP,
                                    source_cleanup_error,
                                    severity=IssueSeverity.WARNING,
                                ),
                            )
                        output_cleanup_error = self._remove_part(part_path)
                        if output_cleanup_error:
                            conversion_issues += (
                                issue(
                                    DownloadIssueCode.TEMP_CLEANUP_FAILED,
                                    DownloadStage.CLEANUP,
                                    output_cleanup_error,
                                    severity=IssueSeverity.WARNING,
                                ),
                            )
                        return make_result(
                            DownloadStatus.FAILED,
                            attempt=attempt,
                            error=conversion_error,
                            issues=conversion_issues,
                            mode=DownloadMode.HTML_TO_PDF,
                            processor=conversion_processor,
                        )
                    result_mode = DownloadMode.HTML_TO_PDF
                    result_processor = conversion_processor
                    result_issues = tuple(getattr(conversion, "issues", ()) or ())
                    if source_cleanup_error:
                        result_issues += (
                            issue(
                                DownloadIssueCode.TEMP_CLEANUP_FAILED,
                                DownloadStage.CLEANUP,
                                source_cleanup_error,
                                severity=IssueSeverity.WARNING,
                            ),
                        )
                    pdf_bytes = int(getattr(conversion, "bytes_written", 0) or 0)
                    pdf_sha256 = str(getattr(conversion, "sha256", "") or "")
                    self.logger.info(
                        "download.convert.complete "
                        f'processor="{result_processor}" '
                        f'conversion_id="{str(getattr(conversion, "conversion_id", "") or "")}" '
                        f'edge_version="{edge_version}" '
                        f"elapsed_seconds="
                        f"{float(getattr(conversion, 'elapsed_seconds', 0.0)):.3f} "
                        "paper=A4 orientation=portrait margins_mm=10 "
                        "header_footer=false "
                        f'file="{save_path_obj.name}" '
                        f"bytes={pdf_bytes} sha256={pdf_sha256}"
                    )
                else:
                    with part_path.open("rb") as downloaded_file:
                        signature = downloaded_file.read(4096)
                    if self._looks_like_error_payload(signature):
                        raise _DownloadFailure(
                            DownloadIssueCode.UNEXPECTED_HTML,
                            DownloadStage.CLASSIFY,
                            "HTML/JSON/XMLエラーレスポンスを検出しました",
                        )
                    if not self._matches_expected_signature(signature, save_path_obj):
                        raise _DownloadFailure(
                            DownloadIssueCode.PAYLOAD_SIGNATURE_MISMATCH,
                            DownloadStage.VALIDATE,
                            f"拡張子{save_path_obj.suffix.lower()}と"
                            "ファイル形式が一致しません",
                        )
                    container_error = self._validate_ooxml_container(
                        part_path, save_path_obj
                    )
                    if container_error:
                        raise _DownloadFailure(
                            DownloadIssueCode.OOXML_INVALID,
                            DownloadStage.VALIDATE,
                            container_error,
                        )
                    pdf_bytes = written
                    pdf_sha256 = digest.hexdigest()

                # os.replaceは同一ボリューム上で原子的。既存の正常ファイルは
                # 検証完了まで変更されない。
                if self._is_cancelled(cancel_check):
                    raise InterruptedError("キャンセルされました")
                try:
                    os.replace(part_path, save_path_obj)
                except OSError as exc:
                    raise _DownloadFailure(
                        DownloadIssueCode.SAVE_FAILED,
                        DownloadStage.COMMIT,
                        f"保存ファイルを確定できません: {exc}",
                    ) from exc
                return make_result(
                    DownloadStatus.SUCCESS,
                    attempt=attempt,
                    issues=result_issues,
                    mode=result_mode,
                    processor=result_processor,
                    bytes_written=pdf_bytes,
                    sha256=pdf_sha256,
                )

            except InterruptedError as exc:
                return cancelled_result(
                    attempt,
                    mode=current_mode,
                    message=str(exc),
                    processor=current_processor,
                )
            except (
                _DownloadFailure,
                NetworkError,
                requests.exceptions.RequestException,
                OSError,
            ) as exc:
                retry_after = (
                    response.headers.get("Retry-After")
                    if response is not None
                    else None
                )
                was_conversion = current_mode == DownloadMode.HTML_TO_PDF
                if response is not None:
                    response.close()
                    response = None
                if isinstance(exc, _DownloadFailure):
                    failure = exc
                elif isinstance(exc, OutboundPolicyError):
                    failure = _DownloadFailure(
                        (
                            DownloadIssueCode.REDIRECT_POLICY_BLOCKED
                            if exc.redirect
                            else DownloadIssueCode.OUTBOUND_POLICY_BLOCKED
                        ),
                        DownloadStage.FETCH,
                        str(exc),
                    )
                elif isinstance(exc, NetworkError):
                    if self._is_cancelled(cancel_check):
                        return cancelled_result(
                            attempt - 1,
                            mode=current_mode,
                            processor=current_processor,
                        )
                    failure = _DownloadFailure(
                        DownloadIssueCode.NETWORK_ERROR,
                        DownloadStage.FETCH,
                        str(exc),
                        retryable=True,
                    )
                elif isinstance(exc, requests.exceptions.Timeout):
                    failure = _DownloadFailure(
                        DownloadIssueCode.NETWORK_TIMEOUT,
                        DownloadStage.FETCH,
                        f"通信がタイムアウトしました: {exc}",
                        retryable=True,
                    )
                elif isinstance(
                    exc,
                    (
                        requests.exceptions.ConnectionError,
                        requests.exceptions.ChunkedEncodingError,
                    ),
                ):
                    failure = _DownloadFailure(
                        DownloadIssueCode.NETWORK_ERROR,
                        DownloadStage.FETCH,
                        f"通信エラー: {exc}",
                        retryable=True,
                    )
                elif isinstance(exc, requests.exceptions.TooManyRedirects):
                    failure = _DownloadFailure(
                        DownloadIssueCode.REDIRECT_POLICY_BLOCKED,
                        DownloadStage.FETCH,
                        f"リダイレクト上限5回を超えました: {exc}",
                    )
                elif isinstance(exc, requests.exceptions.RequestException):
                    failure = _DownloadFailure(
                        DownloadIssueCode.NETWORK_ERROR,
                        DownloadStage.FETCH,
                        f"通信エラー: {exc}",
                    )
                else:
                    failure = _DownloadFailure(
                        DownloadIssueCode.SAVE_FAILED,
                        DownloadStage.COMMIT,
                        f"ファイル操作に失敗しました: {exc}",
                    )
                cleanup_error = cleanup_work_files()
                failure_issues = (failure.issue,)
                if cleanup_error:
                    failure_issues += (
                        issue(
                            DownloadIssueCode.TEMP_CLEANUP_FAILED,
                            DownloadStage.CLEANUP,
                            cleanup_error,
                            severity=IssueSeverity.WARNING,
                        ),
                    )
                if failure.retryable and attempt < max_attempts:
                    wait_time = self._retry_after_seconds(
                        retry_after,
                        float(2 ** (attempt - 1)),
                    )
                    self.logger.warning(
                        "download.retry "
                        f"stage={failure.issue.stage.value} "
                        f"code={failure.issue.code.value} "
                        f"attempt={attempt}/{max_attempts} "
                        f"wait_seconds={wait_time:.1f} "
                        f'url="{url}" reason="{failure.issue.message}"'
                    )
                    if not self._wait(wait_time, cancel_check):
                        return cancelled_result(
                            attempt,
                            mode=current_mode,
                            processor=current_processor,
                        )
                    continue
                return make_result(
                    DownloadStatus.FAILED,
                    attempt=attempt,
                    error=failure.issue.message,
                    issues=failure_issues,
                    mode=(
                        DownloadMode.HTML_TO_PDF
                        if was_conversion
                        else DownloadMode.DIRECT
                    ),
                    processor=(
                        current_processor or ("msedge" if was_conversion else "")
                    ),
                )
            finally:
                if response is not None:
                    response.close()

        fallback = issue(
            DownloadIssueCode.UNKNOWN,
            DownloadStage.FETCH,
            "ダウンロードに失敗しました",
        )
        return make_result(
            DownloadStatus.FAILED,
            attempt=max_attempts,
            error=fallback.message,
            issues=(fallback,),
        )

    @staticmethod
    def _sha256_path(file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def get_session(self) -> requests.Session:
        return self.session

    def close(self):
        self.session.close()
