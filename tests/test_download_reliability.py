# -*- coding: utf-8 -*-

"""ダウンロード信頼性に関する回帰テスト。"""

import hashlib
import io
import json
import requests
import zipfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.app.run_result import RunOutcome, RunResult
from src.app.service import ApplicationService
from src.core.downloader import Downloader, _DownloadHistory
from src.models.config_model import (
    AppConfig,
    DownloadConditions,
    LoggingConfig,
    SavePaths,
    ScheduleConfig,
    SearchConditions,
)
from src.models.download_result import DownloadResult
from src.models.download_diagnostics import DownloadIssueCode
from src.models.download_task import DownloadTask
from src.models.file_info import FileInfo
from src.utils.http_client import (
    DownloadFileResult,
    DownloadStatus,
    HTTPClient,
)
from src.utils.logger import Logger


class FakeResponse:
    def __init__(
        self,
        chunks,
        status_code=200,
        content_type="application/pdf",
        content_length=None,
        headers=None,
    ):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.headers.setdefault("Content-Type", content_type)
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.closed = False

    def iter_content(self, chunk_size=8192):
        del chunk_size
        yield from self._chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def close(self):
        self.closed = True


def _client():
    client = HTTPClient.__new__(HTTPClient)
    client.logger = MagicMock()
    client.timeout = 30
    client.download_timeout = 300
    client.requests_per_second = 0
    client.session = MagicMock()
    return client


def _ooxml_payload(required_part):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(required_part, "<root />")
    return stream.getvalue()


def test_atomic_download_records_size_and_sha256(tmp_path):
    content = b"%PDF-1.7\nreliable"
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content[:8], content[8:]],
        content_length=len(content),
    )
    destination = tmp_path / "document.pdf"

    result = client.download_file(
        "https://example.test/document.pdf",
        str(destination),
        max_retries=1,
    )

    assert result.status == DownloadStatus.SUCCESS
    assert destination.read_bytes() == content
    assert result.bytes_written == len(content)
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert not (tmp_path / "document.pdf.part").exists()


def test_length_mismatch_keeps_existing_file_and_removes_part(tmp_path):
    client = _client()
    client.session.get.return_value = FakeResponse(
        [b"%PDF-short"],
        content_length=999,
    )
    destination = tmp_path / "document.pdf"
    destination.write_bytes(b"existing-good-file")

    result = client.download_file(
        "https://example.test/document.pdf",
        str(destination),
        max_retries=1,
    )

    assert result.status == DownloadStatus.FAILED
    assert destination.read_bytes() == b"existing-good-file"
    assert not (tmp_path / "document.pdf.part").exists()


def test_stream_cancel_keeps_existing_file_and_removes_part(tmp_path):
    client = _client()
    client.session.get.return_value = FakeResponse(
        [b"%PDF-first", b"second"],
        content_length=20,
    )
    destination = tmp_path / "document.pdf"
    destination.write_bytes(b"existing-good-file")
    progress_calls = 0

    def progress(_current, _total):
        nonlocal progress_calls
        progress_calls += 1
        return progress_calls < 1

    result = client.download_file(
        "https://example.test/document.pdf",
        str(destination),
        progress_callback=progress,
        max_retries=1,
    )

    assert result.status == DownloadStatus.CANCELLED
    assert destination.read_bytes() == b"existing-good-file"
    assert not (tmp_path / "document.pdf.part").exists()


def test_cancel_check_stops_active_stream_and_preserves_existing_file(tmp_path):
    content = [b"%PDF-first", b"second"]
    client = _client()
    client.session.get.return_value = FakeResponse(
        content,
        content_length=sum(len(chunk) for chunk in content),
    )
    destination = tmp_path / "document.pdf"
    destination.write_bytes(b"existing-good-file")
    cancel_checks = 0

    def cancel_check():
        nonlocal cancel_checks
        cancel_checks += 1
        # 試行前と最初のチャンクは継続し、次のチャンクで停止する。
        return cancel_checks >= 3

    result = client.download_file(
        "https://example.test/document.pdf",
        str(destination),
        cancel_check=cancel_check,
        max_retries=1,
    )

    assert result.status == DownloadStatus.CANCELLED
    assert destination.read_bytes() == b"existing-good-file"
    assert not (tmp_path / "document.pdf.part").exists()


def test_retry_after_is_used_and_total_attempts_are_bounded(tmp_path):
    content = b"%PDF-ok"
    client = _client()
    client.session.get.side_effect = [
        FakeResponse([], status_code=429, headers={"Retry-After": "2"}),
        FakeResponse([content], content_length=len(content)),
    ]
    waits = []
    client._wait = lambda seconds, cancel_check=None: (
        waits.append(seconds) or True
    )

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=10,
    )

    assert result.status == DownloadStatus.SUCCESS
    assert result.attempts == 2
    assert waits == [2.0]
    assert client.session.get.call_count == 2


def test_retry_after_wait_can_be_cancelled_without_another_attempt(tmp_path):
    client = _client()
    client.session.get.return_value = FakeResponse(
        [],
        status_code=429,
        headers={"Retry-After": "60"},
    )
    cancel_checks = 0

    def cancel_check():
        nonlocal cancel_checks
        cancel_checks += 1
        # 試行前は継続し、Retry-After待機に入った時点で停止する。
        return cancel_checks >= 2

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        cancel_check=cancel_check,
    )

    assert result.status == DownloadStatus.CANCELLED
    assert result.attempts == 1
    assert client.session.get.call_count == 1


def test_html_payload_is_rejected_even_with_binary_content_type(tmp_path):
    payload = b"<!doctype html><title>error</title>"
    client = _client()
    client.session.get.return_value = FakeResponse(
        [payload],
        content_type="application/octet-stream",
        content_length=len(payload),
    )
    destination = tmp_path / "document.pdf"

    result = client.download_file(
        "https://example.test/document.pdf",
        str(destination),
        max_retries=1,
    )

    assert result.status == DownloadStatus.FAILED
    assert not destination.exists()
    assert not (tmp_path / "document.pdf.part").exists()


def test_partial_content_is_never_promoted_to_final_file(tmp_path):
    content = b"%PDF-partial"
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content],
        status_code=206,
        content_length=len(content),
    )
    destination = tmp_path / "document.pdf"
    destination.write_bytes(b"existing-good-file")

    result = client.download_file(
        "https://example.test/document.pdf",
        str(destination),
        max_retries=3,
    )

    assert result.status == DownloadStatus.FAILED
    assert result.http_status == 206
    assert result.attempts == 1
    assert client.session.get.call_count == 1
    assert destination.read_bytes() == b"existing-good-file"
    assert not (tmp_path / "document.pdf.part").exists()


def test_http_404_is_classified_and_not_retried(tmp_path):
    client = _client()
    client.session.get.return_value = FakeResponse(
        [],
        status_code=404,
    )

    result = client.download_file(
        "https://example.test/missing.pdf",
        str(tmp_path / "missing.pdf"),
        max_retries=3,
    )

    assert result.status == DownloadStatus.FAILED
    assert result.primary_issue.code == DownloadIssueCode.HTTP_4XX
    assert result.http_status == 404
    assert result.attempts == 1
    assert client.session.get.call_count == 1


def test_missing_content_length_is_rejected(tmp_path):
    client = _client()
    client.session.get.return_value = FakeResponse([b"%PDF-unknown-size"])

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=1,
    )

    assert result.status == DownloadStatus.FAILED
    assert "Content-Length" in result.error


def test_file_signature_must_match_extension(tmp_path):
    content = b"not-a-real-pdf"
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content],
        content_type="application/octet-stream",
        content_length=len(content),
    )

    result = client.download_file(
        "https://example.test/document",
        str(tmp_path / "document.pdf"),
        max_retries=1,
    )

    assert result.status == DownloadStatus.FAILED
    assert "ファイル形式" in result.error


def test_bom_and_comment_prefixed_html_is_rejected(tmp_path):
    content = (
        b"\xef\xbb\xbf  <!-- proxy -->"
        b"<head><title>authentication required</title></head>"
    )
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content],
        content_type="application/octet-stream",
        content_length=len(content),
    )

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=1,
    )

    assert result.status == DownloadStatus.FAILED
    assert "HTMLレスポンス" in result.error


def test_valid_rtf_is_not_misclassified_as_json(tmp_path):
    content = b"{\\rtf1\\ansi reliable document}"
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content],
        content_type="application/rtf",
        content_length=len(content),
    )
    destination = tmp_path / "document.rtf"

    result = client.download_file(
        "https://example.test/document.rtf",
        str(destination),
        max_retries=1,
    )

    assert result.status == DownloadStatus.SUCCESS
    assert destination.read_bytes() == content


def test_missing_content_type_is_rejected(tmp_path):
    content = b"%PDF-content"
    response = FakeResponse([content], content_length=len(content))
    response.headers.pop("Content-Type")
    client = _client()
    client.session.get.return_value = response

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=1,
    )

    assert result.status == DownloadStatus.FAILED
    assert "Content-Type" in result.error


def test_ooxml_content_type_must_match_extension(tmp_path):
    content = _ooxml_payload("word/document.xml")
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content],
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        content_length=len(content),
    )

    result = client.download_file(
        "https://example.test/document.docx",
        str(tmp_path / "document.docx"),
        max_retries=1,
    )

    assert result.status == DownloadStatus.FAILED
    assert "Content-Type" in result.error


def test_ooxml_container_must_match_extension(tmp_path):
    content = _ooxml_payload("xl/workbook.xml")
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content],
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        content_length=len(content),
    )

    result = client.download_file(
        "https://example.test/document.docx",
        str(tmp_path / "document.docx"),
        max_retries=1,
    )

    assert result.status == DownloadStatus.FAILED
    assert "word/document.xml" in result.error


def test_valid_docx_container_is_accepted(tmp_path):
    content = _ooxml_payload("word/document.xml")
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content],
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        content_length=len(content),
    )
    destination = tmp_path / "document.docx"

    result = client.download_file(
        "https://example.test/document.docx",
        str(destination),
        max_retries=1,
    )

    assert result.status == DownloadStatus.SUCCESS
    assert destination.read_bytes() == content


def test_retry_after_is_used_for_503(tmp_path):
    content = b"%PDF-ok"
    first_response = FakeResponse(
        [],
        status_code=503,
        headers={"Retry-After": "4"},
    )
    client = _client()
    client.session.get.side_effect = [
        first_response,
        FakeResponse([content], content_length=len(content)),
    ]
    waits = []

    def record_wait(seconds, cancel_check=None):
        del cancel_check
        assert first_response.closed
        waits.append(seconds)
        return True

    client._wait = record_wait

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
    )

    assert result.status == DownloadStatus.SUCCESS
    assert waits == [4.0]


@pytest.mark.parametrize("status_code", [501, 599])
def test_every_5xx_status_is_retried_for_download(tmp_path, status_code):
    content = b"%PDF-ok"
    retry_response = FakeResponse([], status_code=status_code)
    client = _client()
    client.session.get.side_effect = [
        retry_response,
        FakeResponse([content], content_length=len(content)),
    ]
    waits = []
    client._wait = lambda seconds, cancel_check=None: (
        waits.append(seconds) or True
    )

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=3,
    )

    assert result.status == DownloadStatus.SUCCESS
    assert result.attempts == 2
    assert client.session.get.call_count == 2
    assert waits == [1.0]
    assert retry_response.closed


def test_timeout_is_bounded_to_three_total_attempts(tmp_path):
    client = _client()
    client.session.get.side_effect = requests.Timeout("read timed out")
    client._wait = lambda seconds, cancel_check=None: True

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=99,
    )

    assert result.status == DownloadStatus.FAILED
    assert result.attempts == 3
    assert client.session.get.call_count == 3


def test_connection_error_is_bounded_to_three_total_attempts(tmp_path):
    client = _client()
    client.session.get.side_effect = requests.ConnectionError(
        "connection reset"
    )
    client._wait = lambda seconds, cancel_check=None: True

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=99,
    )

    assert result.status == DownloadStatus.FAILED
    assert result.attempts == 3
    assert client.session.get.call_count == 3


@pytest.mark.parametrize(
    "request_error",
    [
        requests.exceptions.InvalidURL("invalid URL"),
        requests.exceptions.InvalidSchema("invalid schema"),
        requests.exceptions.TooManyRedirects("redirect loop"),
    ],
)
def test_deterministic_request_error_is_not_retried(
    tmp_path,
    request_error,
):
    client = _client()
    client.session.get.side_effect = request_error
    client._wait = MagicMock(return_value=True)

    result = client.download_file(
        "https://example.test/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=3,
    )

    assert result.status == DownloadStatus.FAILED
    assert result.attempts == 1
    assert client.session.get.call_count == 1
    client._wait.assert_not_called()


def test_locked_stale_part_returns_structured_failure(tmp_path):
    client = _client()
    destination = tmp_path / "document.pdf"
    part_path = tmp_path / "document.pdf.part"
    part_path.write_bytes(b"stale")

    with patch.object(
        Path,
        "unlink",
        side_effect=PermissionError("locked"),
    ):
        result = client.download_file(
            "https://example.test/document.pdf",
            str(destination),
        )

    assert result.status == DownloadStatus.FAILED
    assert result.attempts == 0
    assert "作業ファイルを削除できません" in result.error
    assert result.primary_issue.code == DownloadIssueCode.TEMP_CLEANUP_FAILED
    assert result.primary_issue.stage.value == "CLEANUP"
    assert result.primary_issue.severity.value == "ERROR"
    assert client.session.get.call_count == 0


def test_locked_stale_html_source_returns_cleanup_failure(tmp_path):
    client = _client()
    url = "https://example.test/document.pdf"
    destination = tmp_path / "document.pdf"
    source_token = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    html_source_path = tmp_path / f".ippi-source-{source_token}.html.part"
    html_source_path.write_bytes(b"stale HTML")
    original_unlink = Path.unlink

    def fail_only_for_stale_html(path, *args, **kwargs):
        if path == html_source_path:
            raise PermissionError("locked")
        return original_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", autospec=True) as unlink:
        unlink.side_effect = fail_only_for_stale_html
        result = client.download_file(url, str(destination))

    assert result.status == DownloadStatus.FAILED
    assert result.attempts == 0
    assert result.primary_issue.code == DownloadIssueCode.TEMP_CLEANUP_FAILED
    assert result.primary_issue.stage.value == "CLEANUP"
    assert result.primary_issue.severity.value == "ERROR"
    assert str(html_source_path) in result.error
    assert client.session.get.call_count == 0


def test_atomic_replace_failure_keeps_existing_file_and_removes_part(tmp_path):
    content = b"%PDF-replace"
    client = _client()
    client.session.get.return_value = FakeResponse(
        [content],
        content_length=len(content),
    )
    destination = tmp_path / "document.pdf"
    destination.write_bytes(b"existing-good-file")

    with patch(
        "src.utils.http_client.os.replace",
        side_effect=PermissionError("destination locked"),
    ):
        result = client.download_file(
            "https://example.test/document.pdf",
            str(destination),
            max_retries=1,
        )

    assert result.status == DownloadStatus.FAILED
    assert destination.read_bytes() == b"existing-good-file"
    assert not (tmp_path / "document.pdf.part").exists()


def test_retry_after_http_date_is_supported():
    future = datetime.now(timezone.utc) + timedelta(seconds=30)

    seconds = HTTPClient._retry_after_seconds(format_datetime(future), 1.0)

    assert 0 < seconds <= 30


@pytest.mark.parametrize(
    "value",
    ["Infinity", "-Infinity", "NaN", "1e309"],
)
def test_retry_after_non_finite_seconds_uses_fallback(value):
    assert HTTPClient._retry_after_seconds(value, 1.25) == 1.25


def test_download_result_total_and_outcomes_are_consistent():
    file_info = FileInfo("https://example.test/a", "a.pdf", ".pdf")
    result = DownloadResult(total=2)
    completed = DownloadTask(file_info, "a.pdf", status="completed")
    failed = DownloadTask(file_info, "b.pdf", status="failed")
    result.add_task(completed)
    result.update_status(completed)
    result.add_task(failed)
    result.update_status(failed)

    assert result.total == 2
    assert result.accounted == 2
    assert result.is_consistent
    assert result.outcome == RunOutcome.PARTIAL

    failed_only = DownloadResult(total=1)
    failed_only.add_task(failed)
    failed_only.update_status(failed)
    assert failed_only.outcome == RunOutcome.FAILED

    contradictory = RunResult(
        success=True,
        result=failed_only,
        outcome=RunOutcome.SUCCESS,
    )
    assert contradictory.success is False
    assert contradictory.outcome == RunOutcome.FAILED


def test_run_result_never_promotes_terminal_failure_to_success_family():
    file_info = FileInfo("https://example.test/a", "a.pdf", ".pdf")

    failed = DownloadResult(total=1)
    failed.add_task(DownloadTask(file_info, "", status="failed"))
    failed_partial = RunResult(
        success=True,
        result=failed,
        outcome=RunOutcome.PARTIAL,
    )
    assert failed_partial.outcome == RunOutcome.FAILED
    assert failed_partial.success is False

    cancelled = DownloadResult(total=1)
    cancelled.add_task(DownloadTask(file_info, "", status="cancelled"))
    cancelled_partial = RunResult(
        success=True,
        result=cancelled,
        outcome=RunOutcome.PARTIAL,
    )
    assert cancelled_partial.outcome == RunOutcome.CANCELLED
    assert cancelled_partial.success is False

    no_match = RunResult(
        success=True,
        result=DownloadResult(total=0),
        outcome=RunOutcome.PARTIAL,
    )
    assert no_match.outcome == RunOutcome.NO_MATCH
    assert no_match.success is False


def test_source_partial_is_allowed_only_for_successful_file_result():
    file_info = FileInfo("https://example.test/a", "a.pdf", ".pdf")
    successful = DownloadResult(total=1)
    successful.add_task(DownloadTask(file_info, "a.pdf", status="completed"))

    source_partial = RunResult(
        success=True,
        result=successful,
        outcome=RunOutcome.PARTIAL,
    )

    assert source_partial.outcome == RunOutcome.PARTIAL
    assert source_partial.success is True


def test_download_result_fixes_expected_total_and_detects_incomplete_or_extra_tasks():
    file_info = FileInfo("https://example.test/a", "a.pdf", ".pdf")
    result = DownloadResult(total=2)

    result.add_task(DownloadTask(file_info, "a.pdf", status="completed"))
    assert result.total == 2
    assert result.is_consistent is False

    result.add_task(DownloadTask(file_info, "b.pdf", status="failed"))
    assert result.total == 2
    assert result.is_consistent is True

    with pytest.raises(ValueError, match="期待総数"):
        result.add_task(DownloadTask(file_info, "c.pdf", status="completed"))


def test_download_result_keeps_dynamic_and_summary_compatibility():
    file_info = FileInfo("https://example.test/a", "a.pdf", ".pdf")
    dynamic = DownloadResult()
    dynamic.add_task(DownloadTask(file_info, "a.pdf", status="completed"))
    assert dynamic.total == 1
    assert dynamic.is_consistent

    summary = DownloadResult(total=2, success=1, failed=1)
    assert summary.total == 2
    assert summary.is_consistent


class FakeNaming:
    def generate_folder_name(self, _file_info):
        return "files"

    def generate_filename(self, file_info, _metadata, _index):
        return file_info.filename

    def ensure_unique(self, path):
        candidate = Path(path)
        if not candidate.exists():
            return str(candidate)
        return str(candidate.with_stem(candidate.stem + "_2"))


class FakeHTTPClient:
    def __init__(self):
        self.calls = 0
        self.content = b"%PDF-1.7\nhistory\n%%EOF\n"

    def download_file(
        self,
        url,
        save_path,
        progress_callback=None,
        max_retries=3,
        referer=None,
        cancel_check=None,
    ):
        del progress_callback, max_retries, referer, cancel_check
        self.calls += 1
        content = self.content
        Path(save_path).write_bytes(content)
        return DownloadFileResult(
            DownloadStatus.SUCCESS,
            url,
            save_path,
            bytes_written=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            attempts=1,
        )


def test_downloader_propagates_live_stream_cancellation_and_accounts_all_tasks(
    tmp_path,
):
    files = [
        FileInfo(
            f"https://example.test/{index}.pdf",
            f"{index}.pdf",
            ".pdf",
        )
        for index in range(2)
    ]
    content = [b"%PDF-first", b"second"]
    http = _client()
    http.session.get.return_value = FakeResponse(
        content,
        content_length=sum(len(chunk) for chunk in content),
    )
    downloader = Downloader(http, MagicMock())
    cancel_checks = 0

    def cancel_check():
        nonlocal cancel_checks
        cancel_checks += 1
        # Downloader開始確認、HTTP開始確認、先頭チャンクまでは継続する。
        return cancel_checks >= 4

    result = downloader.download_files(
        files,
        str(tmp_path),
        FakeNaming(),
        cancel_check=cancel_check,
    )

    assert result.total == 2
    assert result.cancelled == 2
    assert result.accounted == 2
    assert result.is_consistent
    assert result.outcome == RunOutcome.CANCELLED
    assert not list(tmp_path.rglob("*.part"))


class CancellingHTTPClient:
    def download_file(
        self,
        url,
        save_path,
        progress_callback=None,
        max_retries=3,
        referer=None,
        cancel_check=None,
    ):
        del progress_callback, max_retries, referer, cancel_check
        return DownloadFileResult(
            DownloadStatus.CANCELLED,
            url,
            save_path,
            attempts=1,
            error="キャンセルされました",
        )


def test_real_downloader_cancellation_accounts_for_every_task(tmp_path):
    files = [
        FileInfo(
            f"https://example.test/{index}.pdf",
            f"{index}.pdf",
            ".pdf",
        )
        for index in range(3)
    ]
    downloader = Downloader(CancellingHTTPClient(), MagicMock())

    result = downloader.download_files(
        files,
        str(tmp_path),
        FakeNaming(),
    )

    assert result.total == 3
    assert result.cancelled == 3
    assert result.accounted == 3
    assert result.is_consistent
    assert result.outcome == RunOutcome.CANCELLED


def test_history_skips_only_verified_url_size_and_hash(tmp_path):
    file_info = FileInfo(
        "https://example.test/a.pdf",
        "a.pdf",
        ".pdf",
        metadata={
            "document_name": "入札調書",
            "koji_name": "履歴確認工事",
        },
    )
    http = FakeHTTPClient()
    downloader = Downloader(http, MagicMock())

    first = downloader.download_files(
        [file_info], str(tmp_path), FakeNaming()
    )
    second_logger = MagicMock()
    second = Downloader(http, second_logger).download_files(
        [file_info], str(tmp_path), FakeNaming()
    )

    assert first.outcome == RunOutcome.SUCCESS
    assert second.outcome == RunOutcome.SUCCESS
    assert second.skipped == 1
    assert second.tasks[0].issues == []
    assert second.issue_counts == {}
    assert http.calls == 1
    final_lines = [
        call.args[0]
        for call in second_logger.info.call_args_list
        if call.args and call.args[0].startswith("download.file.final ")
    ]
    assert len(final_lines) == 1
    skip_payload = json.loads(
        final_lines[0].removeprefix("download.file.final ")
    )
    assert skip_payload["attempts"] == 0
    assert skip_payload["bytes"] == len(http.content)
    assert skip_payload["content_length"] is None
    assert skip_payload["content_type"] is None
    assert skip_payload["document_name"] == "入札調書"
    assert skip_payload["http_status"] is None
    assert skip_payload["issue_details"] == {}
    assert skip_payload["mode"] == "DIRECT"
    assert skip_payload["processor"] == ""
    assert skip_payload["project_name"] == "履歴確認工事"
    assert skip_payload["reason_code"] == "HISTORY_MATCH"
    assert skip_payload["save_path"] == str(tmp_path / "files" / "a.pdf")
    assert skip_payload["sha256"] == hashlib.sha256(
        http.content
    ).hexdigest()
    assert skip_payload["stage"] == "COMMIT"
    assert skip_payload["status"] == "SKIPPED"
    assert skip_payload["url"] == "https://example.test/a.pdf"
    assert skip_payload["validation_kind"] == "PDF"
    assert not second_logger.error.called

    saved = tmp_path / "files" / "a.pdf"
    tampered = bytearray(http.content)
    tampered[len(b"%PDF-1.7\n")] ^= 1
    assert len(tampered) == len(http.content)
    saved.write_bytes(tampered)
    third = Downloader(http, MagicMock()).download_files(
        [file_info], str(tmp_path), FakeNaming()
    )
    assert third.success == 1
    assert http.calls == 2


def test_history_recording_reuses_committed_result_without_second_file_read(
    tmp_path,
):
    file_info = FileInfo(
        "https://example.test/a.pdf",
        "a.pdf",
        ".pdf",
    )
    http = FakeHTTPClient()
    logger = MagicMock()
    downloader = Downloader(http, logger)
    downloader._sha256 = MagicMock(
        side_effect=PermissionError("second read is not allowed")
    )

    result = downloader.download_files(
        [file_info],
        str(tmp_path),
        FakeNaming(),
    )

    assert result.outcome == RunOutcome.SUCCESS
    assert result.success == 1
    assert result.failed == 0
    downloader._sha256.assert_not_called()
    final_lines = [
        call.args[0]
        for call in logger.info.call_args_list
        if call.args and call.args[0].startswith("download.file.final ")
    ]
    assert len(final_lines) == 1
    assert not logger.error.called
    history = (
        tmp_path / ".ippi-download-history.jsonl"
    ).read_text(encoding="utf-8")
    assert hashlib.sha256(http.content).hexdigest() in history


def test_history_metadata_failure_does_not_change_committed_success(
    tmp_path,
):
    file_info = FileInfo(
        "https://example.test/a.pdf",
        "a.pdf",
        ".pdf",
    )
    http = FakeHTTPClient()
    logger = MagicMock()
    downloader = Downloader(http, logger)
    original_stored_path = _DownloadHistory._stored_path
    calls = 0

    def fail_only_during_append(history, file_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("history path unavailable")
        return original_stored_path(history, file_path)

    with patch.object(
        _DownloadHistory,
        "_stored_path",
        fail_only_during_append,
    ):
        result = downloader.download_files(
            [file_info],
            str(tmp_path),
            FakeNaming(),
        )

    assert result.outcome == RunOutcome.SUCCESS
    assert result.success == 1
    assert result.failed == 0
    assert (tmp_path / "files" / "a.pdf").is_file()
    final_lines = [
        call.args[0]
        for call in logger.info.call_args_list
        if call.args and call.args[0].startswith("download.file.final ")
    ]
    assert len(final_lines) == 1
    assert not logger.error.called
    assert any(
        "ダウンロード履歴を保存できません" in call.args[0]
        for call in logger.warning.call_args_list
    )


@patch("src.app.service.HTTPClient")
@patch("src.app.service.Scraper")
@patch("src.app.service.Filter")
@patch("src.app.service.Naming")
@patch("src.app.service.Downloader")
def test_application_service_all_failed_is_not_success(
    downloader_cls,
    naming_cls,
    filter_cls,
    scraper_cls,
    http_client_cls,
    tmp_path,
):
    del naming_cls, http_client_cls
    file_info = FileInfo(
        "https://example.test/a.pdf",
        "a.pdf",
        ".pdf",
    )
    scraper_cls.return_value.fetch_page.return_value = MagicMock()
    scraper_cls.return_value.extract_file_links.return_value = [file_info]
    filter_cls.return_value.filter_files.return_value = [file_info]
    failed = DownloadResult(total=1)
    task = DownloadTask(file_info, "", status="failed")
    failed.add_task(task)
    failed.update_status(task)
    downloader_cls.return_value.download_files.return_value = failed

    service = ApplicationService(Logger(LoggingConfig(file=str(tmp_path / "test.log"))))
    config = AppConfig(
        target_urls=["https://example.test"],
        download_conditions=DownloadConditions(),
        search_conditions=SearchConditions(),
        save_paths=SavePaths(local=str(tmp_path / "downloads")),
        schedule=ScheduleConfig(),
        logging=LoggingConfig(file=str(tmp_path / "test.log")),
    )

    run_result = service.run(config)

    assert run_result.success is False
    assert run_result.outcome == RunOutcome.FAILED


def test_application_service_rejects_unsupported_multi_agency(tmp_path):
    service = ApplicationService(MagicMock())
    config = AppConfig(
        target_urls=["https://example.test"],
        search_conditions=SearchConditions(hachu_multi=["機関A", "機関B"]),
        save_paths=SavePaths(local=str(tmp_path / "downloads")),
    )

    run_result = service.run(config)

    assert run_result.success is False
    assert run_result.outcome == RunOutcome.FAILED
    assert "サポートされていません" in run_result.message
