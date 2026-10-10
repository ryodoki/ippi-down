# -*- coding: utf-8 -*-

"""構造化されたダウンロード診断モデルのテスト。"""

from dataclasses import FrozenInstanceError

import pytest

from src.models.download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadMode,
    DownloadStage,
    IssueSeverity,
)
from src.models.download_result import DownloadResult
from src.models.download_task import DownloadTask
from src.models.file_info import FileInfo
from src.utils.http_client import (
    DownloadFileResult,
    DownloadStatus,
)


def _file_info(name: str = "document.pdf") -> FileInfo:
    return FileInfo(
        url=f"https://example.test/{name}",
        filename=name,
        file_type=".pdf",
    )


def _issue(
    code: DownloadIssueCode,
    *,
    severity: IssueSeverity = IssueSeverity.ERROR,
) -> DownloadIssue:
    return DownloadIssue(
        code=code,
        stage=DownloadStage.VALIDATE,
        message="検証に失敗しました",
        severity=severity,
        details={"http_status": 200, "retryable": False},
    )


def test_download_issue_is_frozen_and_has_independent_details_defaults():
    first = DownloadIssue(
        DownloadIssueCode.UNKNOWN,
        DownloadStage.CLASSIFY,
        "分類できません",
    )
    second = DownloadIssue(
        DownloadIssueCode.UNKNOWN,
        DownloadStage.CLASSIFY,
        "分類できません",
    )

    assert first.details == {}
    assert first.details is not second.details
    with pytest.raises(FrozenInstanceError):
        first.message = "変更"


def test_download_file_result_keeps_old_positional_api_and_selects_primary_issue():
    warning = _issue(
        DownloadIssueCode.TEMP_CLEANUP_FAILED,
        severity=IssueSeverity.WARNING,
    )
    error = _issue(DownloadIssueCode.OUTPUT_INVALID_PDF)

    legacy = DownloadFileResult(
        DownloadStatus.SUCCESS,
        "https://example.test/a.pdf",
        "a.pdf",
        200,
        "application/pdf",
        123,
        "abc",
        1,
        "",
    )
    diagnosed = DownloadFileResult(
        DownloadStatus.FAILED,
        "https://example.test/a",
        "a.pdf",
        processing_mode=DownloadMode.HTML_TO_PDF,
        processor="Microsoft Edge 130",
        final_url="https://example.test/final",
        content_length=456,
        content_disposition="attachment",
        issues=(warning, error),
    )

    assert legacy.success
    assert legacy.processing_mode == DownloadMode.DIRECT
    assert legacy.primary_issue is None
    assert diagnosed.primary_issue is error


def test_download_task_mark_methods_accept_diagnostics_without_breaking_old_calls():
    task = DownloadTask(_file_info(), "document.pdf")
    issue = _issue(DownloadIssueCode.CONVERSION_EXIT_ERROR)

    task.mark_failed("変換に失敗しました", [issue], DownloadMode.HTML_TO_PDF)

    assert task.status == "failed"
    assert task.retry_count == 1
    assert task.issues == [issue]
    assert task.processing_mode == DownloadMode.HTML_TO_PDF

    task.mark_completed()
    assert task.status == "completed"
    assert task.error_message == ""
    assert task.issues == [issue]
    assert task.processing_mode == DownloadMode.HTML_TO_PDF


def test_download_result_exposes_failed_tasks_issue_counts_and_converted_count():
    conversion_issue = _issue(DownloadIssueCode.CONVERSION_EXIT_ERROR)
    cleanup_warning = _issue(
        DownloadIssueCode.TEMP_CLEANUP_FAILED,
        severity=IssueSeverity.WARNING,
    )
    result = DownloadResult(total=3)

    converted = DownloadTask(
        _file_info("converted.pdf"),
        "converted.pdf",
        status="completed",
        issues=[cleanup_warning],
        processing_mode=DownloadMode.HTML_TO_PDF,
    )
    failed = DownloadTask(
        _file_info("failed.pdf"),
        "failed.pdf",
        status="failed",
        issues=[conversion_issue, conversion_issue],
        processing_mode=DownloadMode.HTML_TO_PDF,
    )
    direct = DownloadTask(
        _file_info("direct.pdf"),
        "direct.pdf",
        status="completed",
    )
    for task in (converted, failed, direct):
        result.add_task(task)

    assert result.failed_tasks == [failed]
    assert result.issue_counts == {
        DownloadIssueCode.TEMP_CLEANUP_FAILED: 1,
        DownloadIssueCode.CONVERSION_EXIT_ERROR: 2,
    }
    assert result.converted == 1
