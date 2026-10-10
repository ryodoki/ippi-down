# -*- coding: utf-8 -*-

"""HTML入札調書の取得・PDF変換経路に関する統合テスト。"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Tuple
from unittest.mock import MagicMock

from src.core.downloader import Downloader
from src.models.download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadMode,
    DownloadStage,
    IssueSeverity,
)
from src.models.file_info import FileInfo
from src.utils.http_client import DownloadFileResult, DownloadStatus, HTTPClient


HTML_URL = (
    "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/"
    "KokaiBunshoServlet?AnkenKanriNo=example&BunshoKanriId=40"
)
HTML_BODY = (
    b"<!doctype html><html><head><title>nyusatsu</title></head>"
    b"<body><h1>bid sheet</h1></body></html>"
)
PDF_BODY = b"%PDF-1.7\nconverted bid sheet\n%%EOF\n"
FIXTURE_DIR = Path(__file__).parent / "fixtures"


class FakeResponse:
    """requests.Responseのダウンロード経路で必要な部分だけを再現する。"""

    def __init__(
        self,
        body: bytes,
        *,
        content_type: str = "text/html; charset=UTF-8",
        content_disposition: str = 'inline; filename="bid-sheet.html"',
        final_url: str = HTML_URL,
    ):
        self._body = body
        self.status_code = 200
        self.url = final_url
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Content-Disposition": content_disposition,
        }
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset : offset + chunk_size]

    def close(self):
        self.closed = True


@dataclass(frozen=True)
class FakeConversionResult:
    success: bool
    cancelled: bool = False
    error: str = ""
    issues: Tuple[DownloadIssue, ...] = ()
    processor: str = "fake-edge"
    edge_version: str = ""
    elapsed_seconds: float = 0.0
    bytes_written: int = 0
    sha256: str = ""


class FakeConverter:
    def __init__(
        self,
        result: FakeConversionResult,
        *,
        output: Optional[bytes] = None,
    ):
        self.result = result
        self.output = output
        self.calls = []
        self.source_body = b""

    def convert(
        self,
        source_html,
        output_part,
        cancel_check,
        **kwargs,
    ):
        self.calls.append(
            {
                "source_html": Path(source_html),
                "output_part": Path(output_part),
                "cancel_check": cancel_check,
                **kwargs,
            }
        )
        self.source_body = Path(source_html).read_bytes()
        if self.output is not None:
            Path(output_part).write_bytes(self.output)
        if (
            self.result.success
            and self.output is not None
            and self.result.bytes_written == 0
            and not self.result.sha256
        ):
            return replace(
                self.result,
                bytes_written=len(self.output),
                sha256=hashlib.sha256(self.output).hexdigest(),
            )
        return self.result


def _client(response: FakeResponse) -> HTTPClient:
    client = HTTPClient.__new__(HTTPClient)
    client.logger = MagicMock()
    client.timeout = 30
    client.download_timeout = 300
    client.requests_per_second = 0
    client.session = MagicMock()
    client.session.get.return_value = response
    return client


def _assert_no_work_files(directory: Path) -> None:
    assert not list(directory.glob("*.part"))
    assert not list(directory.glob(".ippi-source-*"))


def test_allowed_html_is_fetched_once_converted_and_atomically_committed(
    tmp_path,
):
    final_url = HTML_URL + "&redirected=1"
    response = FakeResponse(HTML_BODY, final_url=final_url)
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(
            success=True,
            processor="",
            edge_version="Microsoft Edge 131.0.2903.146",
            elapsed_seconds=1.25,
        ),
        output=PDF_BODY,
    )
    destination = tmp_path / "入札調書.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        max_retries=3,
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.status == DownloadStatus.SUCCESS
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert result.processor == "Microsoft Edge 131.0.2903.146"
    assert result.attempts == 1
    assert result.http_status == 200
    assert result.final_url == final_url
    assert result.content_type == "text/html; charset=UTF-8"
    assert result.content_length == len(HTML_BODY)
    assert result.content_disposition == 'inline; filename="bid-sheet.html"'
    assert result.bytes_written == len(PDF_BODY)
    assert result.sha256 == hashlib.sha256(PDF_BODY).hexdigest()
    assert result.issues == ()
    assert destination.read_bytes() == PDF_BODY
    assert client.session.get.call_count == 1
    assert len(converter.calls) == 1
    assert converter.source_body == HTML_BODY
    assert converter.calls[0]["output_part"] == Path(
        f"{destination}.part"
    )
    assert converter.calls[0]["source_url"] == final_url
    assert converter.calls[0]["document_name"] == "入札調書"
    assert converter.calls[0]["project_name"] == "テスト工事"
    assert response.closed
    _assert_no_work_files(tmp_path)


def test_conversion_reuses_converter_verified_size_and_sha256(tmp_path):
    response = FakeResponse(HTML_BODY)
    client = _client(response)
    verified_sha256 = hashlib.sha256(PDF_BODY).hexdigest()
    converter = FakeConverter(
        FakeConversionResult(
            success=True,
            bytes_written=len(PDF_BODY),
            sha256=verified_sha256,
        ),
        output=PDF_BODY,
    )
    client._sha256_path = MagicMock(
        side_effect=AssertionError("変換済みPDFを再ハッシュしてはいけません")
    )
    destination = tmp_path / "入札調書.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.status == DownloadStatus.SUCCESS
    assert result.bytes_written == len(PDF_BODY)
    assert result.sha256 == verified_sha256
    assert destination.read_bytes() == PDF_BODY
    client._sha256_path.assert_not_called()


def test_saved_id40_response_uses_html_to_pdf_mode(tmp_path):
    response = FakeResponse(
        (FIXTURE_DIR / "id40_bid_sheet.html").read_bytes(),
        content_type="text/html; charset=UTF-8",
        final_url=HTML_URL,
    )
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    destination = tmp_path / "入札調書.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="志津地すべり排水トンネル第３期工事",
    )

    assert result.success
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert converter.source_body.startswith(b"<HTML>")
    assert destination.read_bytes() == PDF_BODY


def test_saved_id41_response_sample_uses_direct_pdf_mode(tmp_path):
    metadata = json.loads(
        (FIXTURE_DIR / "id41_pdf_response.json").read_text(
            encoding="utf-8"
        )
    )
    pdf_sample = base64.b64decode(metadata["sample_base64"])
    response = FakeResponse(
        pdf_sample,
        content_type=metadata["content_type"],
        content_disposition='inline; filename="bid-sheet.pdf"',
        final_url=metadata["source_url"],
    )
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=b"must not be used",
    )
    destination = tmp_path / "入札調書（総合評価落札方式）.pdf"

    result = client.download_file(
        metadata["source_url"],
        str(destination),
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書（総合評価落札方式）",
        project_name="志津地すべり排水トンネル第３期工事",
    )

    assert pdf_sample.startswith(b"%PDF-")
    assert pdf_sample.rstrip().endswith(b"%%EOF")
    assert result.success
    assert result.processing_mode == DownloadMode.DIRECT
    assert converter.calls == []
    assert destination.read_bytes() == pdf_sample


def test_html_body_with_generic_binary_header_uses_conversion(tmp_path):
    response = FakeResponse(
        HTML_BODY,
        content_type="application/octet-stream",
    )
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    destination = tmp_path / "入札調書.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.success
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert destination.read_bytes() == PDF_BODY
    assert len(converter.calls) == 1
    assert client.session.get.call_count == 1


def test_oversized_html_is_rejected_before_the_response_is_fully_saved(
    tmp_path,
):
    response = FakeResponse(HTML_BODY)
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    converter.max_html_bytes = len(HTML_BODY) - 1
    destination = tmp_path / "入札調書.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert not result.success
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert result.primary_issue.code == DownloadIssueCode.HTML_STRUCTURE_INVALID
    assert result.primary_issue.stage == DownloadStage.VALIDATE
    assert converter.calls == []
    assert not destination.exists()
    _assert_no_work_files(tmp_path)


def test_underreported_html_size_cannot_bypass_stream_limit(tmp_path):
    response = FakeResponse(HTML_BODY)
    response.headers["Content-Length"] = "10"
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    converter.max_html_bytes = len(HTML_BODY) - 1
    destination = tmp_path / "入札調書.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        max_retries=3,
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert not result.success
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert result.primary_issue.code == DownloadIssueCode.HTML_STRUCTURE_INVALID
    assert result.attempts == 1
    assert client.session.get.call_count == 1
    assert converter.calls == []
    _assert_no_work_files(tmp_path)


def test_pdf_body_with_html_header_is_saved_directly(tmp_path):
    response = FakeResponse(PDF_BODY, content_type="text/html; charset=UTF-8")
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=b"must not be used",
    )
    destination = tmp_path / "入札調書.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.success
    assert result.processing_mode == DownloadMode.DIRECT
    assert destination.read_bytes() == PDF_BODY
    assert converter.calls == []
    assert client.session.get.call_count == 1


def test_non_html_error_body_is_never_sent_to_converter(tmp_path):
    response = FakeResponse(
        b'{"error":"not available"}',
        content_type="text/html; charset=UTF-8",
    )
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    destination = tmp_path / "入札調書.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.CONTENT_TYPE_MISMATCH
    assert converter.calls == []
    assert client.session.get.call_count == 1
    _assert_no_work_files(tmp_path)


def test_unapproved_html_is_not_converted_or_retried_and_keeps_existing_pdf(
    tmp_path,
):
    response = FakeResponse(HTML_BODY)
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    destination = tmp_path / "document.pdf"
    destination.write_bytes(b"%PDF-existing\n%%EOF\n")

    result = client.download_file(
        HTML_URL,
        str(destination),
        max_retries=3,
        allow_html_to_pdf=False,
        html_to_pdf_converter=converter,
    )

    assert result.status == DownloadStatus.FAILED
    assert result.processing_mode == DownloadMode.DIRECT
    assert result.attempts == 1
    assert result.primary_issue is not None
    assert result.primary_issue.code == DownloadIssueCode.UNEXPECTED_HTML
    assert result.primary_issue.stage == DownloadStage.CLASSIFY
    assert result.http_status == 200
    assert result.content_type == "text/html; charset=UTF-8"
    assert result.content_disposition == 'inline; filename="bid-sheet.html"'
    assert destination.read_bytes() == b"%PDF-existing\n%%EOF\n"
    assert client.session.get.call_count == 1
    assert converter.calls == []
    assert response.closed
    _assert_no_work_files(tmp_path)


def test_deterministic_conversion_failure_is_not_retried_and_issue_is_preserved(
    tmp_path,
):
    response = FakeResponse(HTML_BODY)
    client = _client(response)
    conversion_issue = DownloadIssue(
        DownloadIssueCode.EDGE_START_FAILED,
        DownloadStage.CONVERT,
        "Microsoft Edgeを起動できませんでした",
    )
    converter = FakeConverter(
        FakeConversionResult(
            success=False,
            error=conversion_issue.message,
            issues=(conversion_issue,),
        ),
        # 変換器が不完全な出力を残してもHTTP層が削除することを確認する。
        output=b"%PDF-incomplete",
    )
    destination = tmp_path / "document.pdf"
    existing_pdf = b"%PDF-existing\n%%EOF\n"
    destination.write_bytes(existing_pdf)

    result = client.download_file(
        HTML_URL,
        str(destination),
        max_retries=3,
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.status == DownloadStatus.FAILED
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert result.processor == "fake-edge"
    assert result.attempts == 1
    assert result.error == conversion_issue.message
    assert result.issues == (conversion_issue,)
    assert result.primary_issue == conversion_issue
    assert result.http_status == 200
    assert result.content_length == len(HTML_BODY)
    assert destination.read_bytes() == existing_pdf
    assert client.session.get.call_count == 1
    assert len(converter.calls) == 1
    assert response.closed
    _assert_no_work_files(tmp_path)


def test_conversion_cancellation_is_not_retried_and_cleans_all_work_files(
    tmp_path,
):
    response = FakeResponse(HTML_BODY)
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(
            success=False,
            cancelled=True,
            error="HTMLからPDFへの変換をキャンセルしました",
        ),
        output=b"%PDF-cancelled-part",
    )
    destination = tmp_path / "document.pdf"
    existing_pdf = b"%PDF-existing\n%%EOF\n"
    destination.write_bytes(existing_pdf)

    result = client.download_file(
        HTML_URL,
        str(destination),
        max_retries=3,
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.status == DownloadStatus.CANCELLED
    assert result.cancelled
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert result.processor == "fake-edge"
    assert result.attempts == 1
    assert result.primary_issue is not None
    assert result.primary_issue.code == DownloadIssueCode.CANCELLED
    assert result.primary_issue.stage == DownloadStage.CONVERT
    assert "キャンセル" in result.primary_issue.message
    assert destination.read_bytes() == existing_pdf
    assert client.session.get.call_count == 1
    assert len(converter.calls) == 1
    assert response.closed
    _assert_no_work_files(tmp_path)


def test_cancel_during_retry_wait_preserves_classified_html_mode(tmp_path):
    response = FakeResponse(HTML_BODY)
    response.headers["Content-Length"] = str(len(HTML_BODY) + 1)
    client = _client(response)
    client._wait = MagicMock(return_value=False)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    destination = tmp_path / "document.pdf"

    result = client.download_file(
        HTML_URL,
        str(destination),
        max_retries=3,
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.status == DownloadStatus.CANCELLED
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert result.processor == "msedge"
    assert result.primary_issue.code == DownloadIssueCode.CANCELLED
    assert result.primary_issue.stage == DownloadStage.CONVERT
    assert result.attempts == 1
    assert client.session.get.call_count == 1
    assert converter.calls == []
    _assert_no_work_files(tmp_path)


def test_commit_failure_after_conversion_keeps_html_mode_and_existing_pdf(
    tmp_path,
    monkeypatch,
):
    response = FakeResponse(HTML_BODY)
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    destination = tmp_path / "document.pdf"
    existing_pdf = b"%PDF-existing\n%%EOF\n"
    destination.write_bytes(existing_pdf)
    monkeypatch.setattr(
        "src.utils.http_client.os.replace",
        MagicMock(side_effect=PermissionError("locked")),
    )

    result = client.download_file(
        HTML_URL,
        str(destination),
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.status == DownloadStatus.FAILED
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert result.processor == "fake-edge"
    assert result.primary_issue is not None
    assert result.primary_issue.code == DownloadIssueCode.SAVE_FAILED
    assert result.primary_issue.stage == DownloadStage.COMMIT
    assert destination.read_bytes() == existing_pdf
    assert client.session.get.call_count == 1
    _assert_no_work_files(tmp_path)


def test_cancel_after_conversion_keeps_html_mode_and_convert_stage(tmp_path):
    response = FakeResponse(HTML_BODY)
    client = _client(response)
    converter = FakeConverter(
        FakeConversionResult(success=True),
        output=PDF_BODY,
    )
    destination = tmp_path / "document.pdf"
    existing_pdf = b"%PDF-existing\n%%EOF\n"
    destination.write_bytes(existing_pdf)
    checks = 0

    def cancel_check():
        nonlocal checks
        checks += 1
        return checks >= 4

    result = client.download_file(
        HTML_URL,
        str(destination),
        cancel_check=cancel_check,
        allow_html_to_pdf=True,
        html_to_pdf_converter=converter,
        document_name="入札調書",
        project_name="テスト工事",
    )

    assert result.status == DownloadStatus.CANCELLED
    assert result.processing_mode == DownloadMode.HTML_TO_PDF
    assert result.primary_issue is not None
    assert result.primary_issue.code == DownloadIssueCode.CANCELLED
    assert result.primary_issue.stage == DownloadStage.CONVERT
    assert destination.read_bytes() == existing_pdf
    assert client.session.get.call_count == 1
    _assert_no_work_files(tmp_path)


class FakeNaming:
    def generate_folder_name(self, _file_info):
        return "files"

    def generate_filename(self, file_info, _metadata, _index):
        return file_info.filename

    def ensure_unique(self, path):
        return path


class SequencedHTTPClient:
    """Downloaderへ異なる終端結果を順番に返すテスト用HTTPClient。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def download_file(
        self,
        url,
        save_path,
        progress_callback=None,
        max_retries=3,
        referer=None,
        cancel_check=None,
        **kwargs,
    ):
        del progress_callback, max_retries, referer, cancel_check
        self.calls.append(
            {"url": url, "save_path": save_path, "kwargs": kwargs}
        )
        status, attempts, mode, issues, error = self.outcomes.pop(0)
        if status == DownloadStatus.SUCCESS:
            Path(save_path).write_bytes(PDF_BODY)
        return DownloadFileResult(
            status,
            url,
            save_path,
            bytes_written=(
                len(PDF_BODY) if status == DownloadStatus.SUCCESS else 0
            ),
            sha256=(
                hashlib.sha256(PDF_BODY).hexdigest()
                if status == DownloadStatus.SUCCESS
                else ""
            ),
            attempts=attempts,
            error=error,
            processing_mode=mode,
            processor=("fake-edge" if mode == DownloadMode.HTML_TO_PDF else ""),
            issues=issues,
        )


def test_downloader_notifies_each_terminal_task_once_and_propagates_diagnostics(
    tmp_path,
):
    cleanup_warning = DownloadIssue(
        DownloadIssueCode.TEMP_CLEANUP_FAILED,
        DownloadStage.CLEANUP,
        "一時プロファイルの後処理に失敗しました",
        IssueSeverity.WARNING,
    )
    timeout_issue = DownloadIssue(
        DownloadIssueCode.NETWORK_TIMEOUT,
        DownloadStage.FETCH,
        "通信がタイムアウトしました",
    )
    cancel_issue = DownloadIssue(
        DownloadIssueCode.CANCELLED,
        DownloadStage.CONVERT,
        "HTMLからPDFへの変換をキャンセルしました",
    )
    http_client = SequencedHTTPClient(
        [
            (
                DownloadStatus.SUCCESS,
                1,
                DownloadMode.HTML_TO_PDF,
                (cleanup_warning,),
                "",
            ),
            (
                DownloadStatus.FAILED,
                3,
                DownloadMode.DIRECT,
                (timeout_issue,),
                timeout_issue.message,
            ),
            (
                DownloadStatus.CANCELLED,
                2,
                DownloadMode.HTML_TO_PDF,
                (cancel_issue,),
                cancel_issue.message,
            ),
        ]
    )
    file_list = [
        FileInfo(
            f"https://example.test/{index}",
            f"{index}.pdf",
            ".pdf",
            metadata={
                "document_name": "入札調書",
                "koji_name": f"テスト工事{index}",
            },
            allow_html_to_pdf=index in {0, 2},
        )
        for index in range(4)
    ]
    callbacks = []
    logger = MagicMock()
    downloader = Downloader(
        http_client,
        logger,
        html_to_pdf_converter=object(),
    )

    result = downloader.download_files(
        file_list,
        str(tmp_path),
        FakeNaming(),
        task_result_callback=lambda current, total, task: callbacks.append(
            (current, total, task)
        ),
    )

    assert [current for current, _total, _task in callbacks] == [1, 2, 3, 4]
    assert {total for _current, total, _task in callbacks} == {4}
    assert [task.status for _current, _total, task in callbacks] == [
        "completed",
        "failed",
        "cancelled",
        "cancelled",
    ]
    assert len({id(task) for _current, _total, task in callbacks}) == 4
    assert [task for _current, _total, task in callbacks] == result.tasks

    assert result.total == 4
    assert result.success == 1
    assert result.failed == 1
    assert result.cancelled == 2
    assert result.accounted == 4
    assert result.is_consistent
    assert result.converted == 1
    assert result.issue_counts == {
        DownloadIssueCode.TEMP_CLEANUP_FAILED: 1,
        DownloadIssueCode.NETWORK_TIMEOUT: 1,
        DownloadIssueCode.CANCELLED: 2,
    }
    assert result.failed_tasks == [result.tasks[1]]

    assert result.tasks[0].issues == [cleanup_warning]
    assert result.tasks[0].processing_mode == DownloadMode.HTML_TO_PDF
    assert result.tasks[0].retry_count == 0
    assert result.tasks[1].issues == [timeout_issue]
    assert result.tasks[1].processing_mode == DownloadMode.DIRECT
    assert result.tasks[1].retry_count == 2
    assert result.tasks[2].issues == [cancel_issue]
    assert result.tasks[2].processing_mode == DownloadMode.HTML_TO_PDF
    assert result.tasks[2].retry_count == 1
    assert len(result.tasks[3].issues) == 1
    assert result.tasks[3].issues[0].code == DownloadIssueCode.CANCELLED
    assert result.tasks[3].issues[0].stage == DownloadStage.FETCH
    assert result.tasks[3].error_message == (
        "ダウンロード開始前にキャンセルされました"
    )
    assert result.tasks[3].retry_count == 0

    final_lines = [
        call.args[0]
        for method in (logger.info, logger.error)
        for call in method.call_args_list
        if call.args and call.args[0].startswith("download.file.final ")
    ]
    assert len(final_lines) == len(file_list)
    final_payloads = [
        json.loads(line.removeprefix("download.file.final "))
        for line in final_lines
    ]
    assert [item["url"] for item in final_payloads].count(file_list[2].url) == 1
    unstarted = next(
        item for item in final_payloads if item["url"] == file_list[3].url
    )
    assert unstarted == {
        "attempts": 0,
        "bytes": 0,
        "content_length": None,
        "content_type": None,
        "document_name": "入札調書",
        "http_status": None,
        "issue_details": {},
        "mode": "DIRECT",
        "processor": "",
        "project_name": "テスト工事3",
        "reason": "ダウンロード開始前にキャンセルされました",
        "reason_code": "CANCELLED",
        "save_path": "",
        "sha256": "",
        "stage": "FETCH",
        "status": "CANCELLED",
        "url": "https://example.test/3",
    }

    assert len(http_client.calls) == 3
    assert http_client.calls[0]["kwargs"]["allow_html_to_pdf"] is True
    assert (
        http_client.calls[0]["kwargs"]["html_to_pdf_converter"]
        is downloader.html_to_pdf_converter
    )
    assert "allow_html_to_pdf" not in http_client.calls[1]["kwargs"]
    assert http_client.calls[2]["kwargs"]["allow_html_to_pdf"] is True
