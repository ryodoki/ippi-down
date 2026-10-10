# -*- coding: utf-8 -*-

"""履歴v2と明示的な再取得に関する回帰テスト。"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.downloader import Downloader, RedownloadPolicy
from src.models.download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadMode,
    DownloadStage,
)
from src.models.download_result import RunOutcome
from src.models.file_info import FileInfo
from src.utils.http_client import DownloadFileResult, DownloadStatus


PDF_V1 = b"%PDF-1.7\nfirst version\n%%EOF\n"
PDF_V2 = b"%PDF-1.7\nsecond version\n%%EOF\n"


def _xlsx_bytes(*, include_workbook: bool) -> bytes:
    """履歴検証に必要な最小限のOOXMLコンテナを作る。"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if include_workbook:
            archive.writestr("xl/workbook.xml", "<workbook/>")
    return output.getvalue()


class FixedNaming:
    """テストで生成先を明示するNaming代替。"""

    def __init__(self, folder: str = "files"):
        self.folder = folder

    def generate_folder_name(self, _file_info):
        return self.folder

    def generate_filename(self, file_info, _metadata, _index):
        return file_info.filename

    def ensure_unique(self, path):
        candidate = Path(path)
        if not candidate.exists():
            return str(candidate)
        return str(candidate.with_stem(f"{candidate.stem}_2"))


class UpdatedNameNaming(FixedNaming):
    """旧名称と異なる文書更新日時付きの名前を生成する。"""

    def generate_filename(self, _file_info, _metadata, _index):
        return "設計書_20260529_1358.pdf"


class RecordingHTTPClient:
    """成功・失敗を決め打ちし、Downloaderからの呼び出しを記録する。"""

    def __init__(
        self,
        *,
        status: DownloadStatus = DownloadStatus.SUCCESS,
        content: bytes = PDF_V1,
        mode: DownloadMode = DownloadMode.DIRECT,
        issue: DownloadIssue | None = None,
    ):
        self.status = status
        self.content = content
        self.mode = mode
        self.issue = issue
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
            {
                "url": url,
                "save_path": save_path,
                "kwargs": kwargs,
            }
        )
        if self.status == DownloadStatus.SUCCESS:
            Path(save_path).write_bytes(self.content)
            return DownloadFileResult(
                self.status,
                url,
                save_path,
                http_status=200,
                content_type="application/pdf",
                content_length=len(self.content),
                bytes_written=len(self.content),
                sha256=hashlib.sha256(self.content).hexdigest(),
                attempts=1,
                processing_mode=self.mode,
                processor=(
                    "Microsoft Edge"
                    if self.mode == DownloadMode.HTML_TO_PDF
                    else ""
                ),
                final_url=url,
            )

        issue = self.issue or DownloadIssue(
            DownloadIssueCode.NETWORK_TIMEOUT,
            DownloadStage.FETCH,
            "通信がタイムアウトしました",
        )
        return DownloadFileResult(
            self.status,
            url,
            save_path,
            attempts=3,
            error=issue.message,
            processing_mode=self.mode,
            issues=(issue,),
            final_url=url,
        )


def _file(index: int = 0, *, html_to_pdf: bool = False) -> FileInfo:
    return FileInfo(
        f"https://example.test/document-{index}.pdf",
        f"document-{index}.pdf",
        ".pdf",
        metadata={
            "document_name": "入札調書" if html_to_pdf else "設計書",
            "koji_name": f"履歴確認工事{index}",
        },
        allow_html_to_pdf=html_to_pdf,
    )


def _legacy_history_record(
    base_dir: Path,
    file_info: FileInfo,
    relative_path: Path,
    content: bytes,
    *,
    layout_version: int | None = None,
) -> None:
    destination = base_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    record = {
        "url": file_info.url,
        "path": str(relative_path),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "completed_at": "2026-07-31T00:00:00+00:00",
    }
    if layout_version is not None:
        record["layout_version"] = layout_version
    (base_dir / ".ippi-download-history.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _history_records(base_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (
            base_dir / ".ippi-download-history.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_all_verified_files_are_reused_without_http_and_counted(tmp_path):
    files = [_file(index) for index in range(14)]
    initial_http = RecordingHTTPClient()

    initial = Downloader(initial_http, MagicMock()).download_files(
        files,
        str(tmp_path),
        FixedNaming(),
    )
    assert initial.success == 14
    first_record = _history_records(tmp_path)[0]
    assert first_record["schema_version"] == 2
    assert first_record["status"] == "SUCCESS"
    assert first_record["processing_mode"] == DownloadMode.DIRECT.value
    assert first_record["validation_kind"] == "PDF"
    assert first_record["expected_format"] == ".pdf"
    assert first_record["reason_code"] == ""
    assert first_record["target_path"] == "files/document-0.pdf"
    assert first_record["path"] == "files/document-0.pdf"
    assert first_record["url"] == files[0].url
    assert first_record["final_url"] == files[0].url
    assert first_record["size"] == len(PDF_V1)
    assert first_record["sha256"] == hashlib.sha256(PDF_V1).hexdigest()
    assert first_record["completed_at"]

    reuse_http = RecordingHTTPClient(content=PDF_V2)
    reused = Downloader(reuse_http, MagicMock()).download_files(
        files,
        str(tmp_path),
        FixedNaming(),
    )

    assert reuse_http.calls == []
    assert reused.reused == 14
    assert reused.skipped == 14
    assert reused.success == 0
    assert reused.accounted == reused.total == 14
    assert reused.is_consistent
    assert reused.outcome == RunOutcome.SUCCESS


def test_legacy_history_is_reused_only_after_current_format_validation(
    tmp_path,
):
    file_info = _file()
    relative_path = Path("files") / file_info.filename
    _legacy_history_record(tmp_path, file_info, relative_path, PDF_V1)
    http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )

    assert http.calls == []
    assert result.reused == 1
    assert result.tasks[0].local_path == str(tmp_path / relative_path)
    assert result.tasks[0].processing_mode == DownloadMode.DIRECT


@pytest.mark.parametrize(
    "invalid_pdf",
    [
        b"<html><body>error page</body></html>",
        b"%PDF-1.7\nmissing end marker\n",
    ],
)
def test_invalid_pdf_with_matching_legacy_hash_is_not_reused(
    tmp_path,
    invalid_pdf,
):
    file_info = _file()
    relative_path = Path("files") / file_info.filename
    _legacy_history_record(
        tmp_path,
        file_info,
        relative_path,
        invalid_pdf,
    )
    http = RecordingHTTPClient(content=PDF_V2)
    logger = MagicMock()

    result = Downloader(http, logger).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )

    assert len(http.calls) == 1
    assert result.success == 1
    assert result.reused == 0
    assert result.tasks[0].status == "completed"
    assert any(
        DownloadIssueCode.HISTORY_INVALID.value in str(call.args[0])
        for call in logger.warning.call_args_list
    )


def test_invalid_ooxml_with_matching_legacy_hash_is_not_reused(
    tmp_path,
):
    file_info = FileInfo(
        "https://example.test/book.xlsx",
        "book.xlsx",
        ".xlsx",
    )
    relative_path = Path("files") / file_info.filename
    _legacy_history_record(
        tmp_path,
        file_info,
        relative_path,
        _xlsx_bytes(include_workbook=False),
    )
    replacement = _xlsx_bytes(include_workbook=True)
    http = RecordingHTTPClient(content=replacement)

    repaired = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )

    assert len(http.calls) == 1
    assert repaired.success == 1
    assert repaired.reused == 0

    reuse_http = RecordingHTTPClient(content=b"unused")
    reused = Downloader(reuse_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )
    assert reuse_http.calls == []
    assert reused.reused == 1


def test_same_url_at_a_new_generated_path_is_not_reused(tmp_path):
    file_info = _file()
    initial_http = RecordingHTTPClient(content=PDF_V1)
    Downloader(initial_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming("old-name"),
    )
    second_http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(second_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming("new-name"),
    )

    assert len(second_http.calls) == 1
    assert result.success == 1
    assert result.reused == 0
    assert Path(result.tasks[0].local_path) == (
        tmp_path / "new-name" / file_info.filename
    )


def test_force_refresh_atomically_replaces_the_same_target(tmp_path):
    file_info = _file()
    initial_http = RecordingHTTPClient(content=PDF_V1)
    Downloader(initial_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )
    destination = tmp_path / "files" / file_info.filename
    refresh_http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(refresh_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
        redownload_policy=RedownloadPolicy.FORCE_REFRESH,
    )

    assert len(refresh_http.calls) == 1
    assert Path(refresh_http.calls[0]["save_path"]) == destination
    assert result.success == 1
    assert result.reused == 0
    assert Path(result.tasks[0].local_path) == destination
    assert destination.read_bytes() == PDF_V2
    assert not (destination.parent / "document-0_2.pdf").exists()


def test_force_refresh_failure_preserves_existing_and_blocks_old_success_reuse(
    tmp_path,
):
    file_info = _file()
    Downloader(
        RecordingHTTPClient(content=PDF_V1),
        MagicMock(),
    ).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )
    destination = tmp_path / "files" / file_info.filename
    failure = DownloadIssue(
        DownloadIssueCode.NETWORK_TIMEOUT,
        DownloadStage.FETCH,
        "通信がタイムアウトしました",
    )
    failed_http = RecordingHTTPClient(
        status=DownloadStatus.FAILED,
        issue=failure,
    )

    failed = Downloader(failed_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
        redownload_policy=RedownloadPolicy.FORCE_REFRESH,
    )

    assert failed.failed == 1
    assert destination.read_bytes() == PDF_V1
    assert not list(destination.parent.glob("*.part"))
    records = _history_records(tmp_path)
    assert records[-1]["status"] == "FAILED"
    assert records[-1]["reason_code"] == DownloadIssueCode.NETWORK_TIMEOUT.value

    retry_http = RecordingHTTPClient(content=PDF_V2)
    retried = Downloader(retry_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )

    assert len(retry_http.calls) == 1
    assert retried.success == 1
    assert retried.reused == 0
    assert destination.read_bytes() == PDF_V2


@pytest.mark.parametrize(
    ("status", "issue_code", "expected_history_status"),
    [
        (
            DownloadStatus.CANCELLED,
            DownloadIssueCode.CANCELLED,
            "CANCELLED",
        ),
        (
            DownloadStatus.FAILED,
            DownloadIssueCode.SAVE_FAILED,
            "FAILED",
        ),
    ],
)
def test_cancel_or_commit_failure_blocks_old_success_and_retries(
    tmp_path,
    status,
    issue_code,
    expected_history_status,
):
    file_info = _file()
    Downloader(
        RecordingHTTPClient(content=PDF_V1),
        MagicMock(),
    ).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )
    destination = tmp_path / "files" / file_info.filename
    stage = (
        DownloadStage.FETCH
        if status == DownloadStatus.CANCELLED
        else DownloadStage.COMMIT
    )
    issue = DownloadIssue(
        issue_code,
        stage,
        (
            "キャンセルされました"
            if status == DownloadStatus.CANCELLED
            else "保存ファイルを確定できません"
        ),
    )

    terminal = Downloader(
        RecordingHTTPClient(status=status, issue=issue),
        MagicMock(),
    ).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
        redownload_policy=RedownloadPolicy.FORCE_REFRESH,
    )

    assert destination.read_bytes() == PDF_V1
    assert terminal.cancelled == (
        1 if status == DownloadStatus.CANCELLED else 0
    )
    assert terminal.failed == (
        1 if status == DownloadStatus.FAILED else 0
    )
    assert _history_records(tmp_path)[-1]["status"] == (
        expected_history_status
    )

    retry_http = RecordingHTTPClient(content=PDF_V2)
    retried = Downloader(retry_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )
    assert len(retry_http.calls) == 1
    assert retried.success == 1
    assert destination.read_bytes() == PDF_V2


def test_reused_html_to_pdf_history_preserves_mode_and_log_metadata(tmp_path):
    file_info = _file(html_to_pdf=True)
    Downloader(
        RecordingHTTPClient(
            content=PDF_V1,
            mode=DownloadMode.HTML_TO_PDF,
        ),
        MagicMock(),
    ).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )
    logger = MagicMock()
    http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(http, logger).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(),
    )

    assert http.calls == []
    assert result.reused == 1
    assert result.tasks[0].processing_mode == DownloadMode.HTML_TO_PDF
    final_lines = [
        call.args[0]
        for call in logger.info.call_args_list
        if call.args and call.args[0].startswith("download.file.final ")
    ]
    assert len(final_lines) == 1
    payload = json.loads(
        final_lines[0].removeprefix("download.file.final ")
    )
    assert payload["status"] == "SKIPPED"
    assert payload["reason_code"] == "HISTORY_MATCH"
    assert payload["mode"] == DownloadMode.HTML_TO_PDF.value
    assert payload["bytes"] == len(PDF_V1)
    assert payload["sha256"] == hashlib.sha256(PDF_V1).hexdigest()
    assert payload["attempts"] == 0
    assert payload["http_status"] is None
    assert payload["validation_kind"] == "PDF"


def test_fresh_legacy_name_is_reused_as_alias_without_renaming(tmp_path):
    file_info = _file()
    file_info.metadata["document_updated_at"] = "2026年05月29日 13時58分"
    file_info.metadata["document_id"] = "18"
    old_relative = Path("files") / "old-generic-name.pdf"
    _legacy_history_record(tmp_path, file_info, old_relative, PDF_V1)
    new_path = tmp_path / "files" / "設計書_20260529_1358.pdf"
    http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        UpdatedNameNaming(),
    )

    assert http.calls == []
    assert result.reused == 1
    assert result.legacy_reused == 1
    assert result.tasks[0].reuse_kind == "LEGACY_PATH_ALIAS"
    assert Path(result.tasks[0].local_path) == tmp_path / old_relative
    assert not new_path.exists()
    assert (tmp_path / old_relative).read_bytes() == PDF_V1

    records = _history_records(tmp_path)
    alias = records[-1]
    assert alias["target_path"] == "files/設計書_20260529_1358.pdf"
    assert alias["path"] == old_relative.as_posix()
    assert alias["reuse_kind"] == "LEGACY_PATH_ALIAS"
    assert alias["alias_from_path"] == old_relative.as_posix()
    assert alias["document_name"] == "設計書"
    assert alias["document_updated_at"] == "2026-05-29T13:58:00+09:00"
    assert alias["document_id"] == "18"
    # エイリアス作成時刻で鮮度を水増しせず、元の取得日時を維持する。
    assert alias["completed_at"] == "2026-07-31T00:00:00+00:00"

    second_http = RecordingHTTPClient(content=PDF_V2)
    second = Downloader(second_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        UpdatedNameNaming(),
    )
    assert second_http.calls == []
    assert second.legacy_reused == 1
    assert len(_history_records(tmp_path)) == 2


def test_legacy_alias_reuse_does_not_create_empty_proposed_folder(
    tmp_path,
):
    """HTTP通信しない旧名再利用では予定先の空フォルダーを作らない。"""
    file_info = _file()
    file_info.metadata["document_updated_at"] = "2026年05月29日 13時58分"
    old_relative = Path("old-location") / "old-generic-name.pdf"
    _legacy_history_record(
        tmp_path,
        file_info,
        old_relative,
        PDF_V1,
        layout_version=3,
    )
    http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        UpdatedNameNaming(folder="new-location"),
        layout_version=3,
    )

    assert http.calls == []
    assert result.legacy_reused == 1
    assert (tmp_path / old_relative).read_bytes() == PDF_V1
    assert not (tmp_path / "new-location").exists()


def test_unresolved_legacy_alias_is_redownloaded_to_classified_path(
    tmp_path,
):
    """99未解決から分類確定した場合は旧版を保持して正規先へ保存する。"""
    file_info = _file()
    file_info.metadata["document_updated_at"] = "2026年05月29日 13時58分"
    old_relative = (
        Path("99_分類未解決")
        / "国の機関"
        / "document-0.pdf"
    )
    _legacy_history_record(
        tmp_path,
        file_info,
        old_relative,
        PDF_V1,
        layout_version=3,
    )
    target_path = tmp_path / "国の機関" / file_info.filename
    http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(folder="国の機関"),
        layout_version=3,
    )

    assert len(http.calls) == 1
    assert Path(http.calls[0]["save_path"]) == target_path
    assert result.success == 1
    assert result.reused == 0
    assert target_path.read_bytes() == PDF_V2
    assert (tmp_path / old_relative).read_bytes() == PDF_V1
    assert any(
        issue.code == DownloadIssueCode.LEGACY_PATH_REDOWNLOAD
        for issue in result.tasks[0].issues
    )

    second_http = RecordingHTTPClient(content=PDF_V1)
    second = Downloader(second_http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(folder="国の機関"),
        layout_version=3,
    )

    assert second_http.calls == []
    assert second.reused == 1
    assert second.legacy_reused == 0
    assert target_path.read_bytes() == PDF_V2


def test_unresolved_legacy_redownload_preserves_unknown_target(tmp_path):
    """正規予定先に履歴外ファイルがあれば上書きせず別名へ保存する。"""
    file_info = _file()
    file_info.metadata["document_updated_at"] = "2026年05月29日 13時58分"
    old_relative = (
        Path("99_分類未解決")
        / "国の機関"
        / file_info.filename
    )
    _legacy_history_record(
        tmp_path,
        file_info,
        old_relative,
        PDF_V1,
        layout_version=3,
    )
    target_path = tmp_path / "国の機関" / file_info.filename
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(b"untracked user file")
    http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        FixedNaming(folder="国の機関"),
        layout_version=3,
    )

    saved_path = Path(result.tasks[0].local_path)
    assert result.success == 1
    assert len(http.calls) == 1
    assert saved_path != target_path
    assert saved_path.parent == target_path.parent
    assert saved_path.read_bytes() == PDF_V2
    assert target_path.read_bytes() == b"untracked user file"
    assert (tmp_path / old_relative).read_bytes() == PDF_V1


def test_newer_document_update_downloads_new_name_and_keeps_legacy(tmp_path):
    file_info = _file()
    file_info.metadata["document_updated_at"] = "2026年08月01日 09時00分"
    old_relative = Path("files") / "old-generic-name.pdf"
    _legacy_history_record(tmp_path, file_info, old_relative, PDF_V1)
    http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        UpdatedNameNaming(),
    )

    new_path = tmp_path / "files" / "設計書_20260529_1358.pdf"
    assert len(http.calls) == 1
    assert result.success == 1
    assert result.reused == 0
    assert new_path.read_bytes() == PDF_V2
    assert (tmp_path / old_relative).read_bytes() == PDF_V1


def test_force_refresh_from_legacy_alias_writes_new_name_and_keeps_old(tmp_path):
    file_info = _file()
    file_info.metadata["document_updated_at"] = "2026年05月29日 13時58分"
    old_relative = Path("files") / "old-generic-name.pdf"
    _legacy_history_record(tmp_path, file_info, old_relative, PDF_V1)
    http = RecordingHTTPClient(content=PDF_V2)

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        UpdatedNameNaming(),
        redownload_policy=RedownloadPolicy.FORCE_REFRESH,
    )

    new_path = tmp_path / "files" / "設計書_20260529_1358.pdf"
    assert len(http.calls) == 1
    assert result.success == 1
    assert new_path.read_bytes() == PDF_V2
    assert (tmp_path / old_relative).read_bytes() == PDF_V1
