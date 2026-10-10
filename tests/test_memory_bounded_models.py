# -*- coding: utf-8 -*-

"""長期運用時に履歴・集計が全量再計算へ戻らないための契約試験。"""

from __future__ import annotations

import hashlib
import json
import tracemalloc
from unittest.mock import MagicMock, patch

from src.core.downloader import _DownloadHistory
from src.models.download_result import DownloadResult
from src.models.download_task import DownloadTask
from src.models.file_info import FileInfo
from src.models.search_summary import (
    DocumentDecision,
    DocumentSummary,
    ProjectClassification,
    ProjectDocumentSummary,
    SearchExtractionSummary,
)


def _history_record(url: str, relative_path: str, content: bytes) -> dict:
    return {
        "schema_version": 2,
        "url": url,
        "target_path": relative_path,
        "path": relative_path,
        "expected_format": ".pdf",
        "status": "SUCCESS",
        "processing_mode": "DIRECT",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_download_history_retains_only_requested_latest_records(tmp_path):
    content = b"%PDF-1.7\nvalid\n%%EOF\n"
    lines = []
    for index in range(5_000):
        lines.append(json.dumps(_history_record(
            f"https://example.invalid/unrelated/{index}",
            f"old/{index}.pdf",
            content,
        )))

    wanted_url = "https://example.invalid/wanted"
    wanted_path = tmp_path / "files" / "wanted.pdf"
    wanted_path.parent.mkdir(parents=True)
    wanted_path.write_bytes(content)
    lines.append(json.dumps(_history_record(
        wanted_url,
        "files/wanted.pdf",
        content,
    )))
    history_path = tmp_path / _DownloadHistory.FILE_NAME
    history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    history = _DownloadHistory(tmp_path, MagicMock())
    assert not hasattr(history, "_records")
    assert history._exact_records == {}

    history.prepare_lookups(
        [(wanted_url, wanted_path, ".pdf")],
        [(wanted_url, ".pdf")],
    )

    assert len(history._exact_records) == 1
    assert len(history._url_format_records) == 1
    assert history.find_valid(wanted_url, wanted_path, ".pdf") is not None


def test_download_history_100k_lines_has_target_proportional_memory(tmp_path):
    content = b"%PDF-1.7\nvalid\n%%EOF\n"
    wanted_url = "https://example.invalid/wanted"
    wanted_path = tmp_path / "wanted.pdf"
    wanted_path.write_bytes(content)
    history_path = tmp_path / _DownloadHistory.FILE_NAME
    with history_path.open("w", encoding="utf-8", newline="\n") as stream:
        for index in range(100_000):
            stream.write(json.dumps(
                _history_record(
                    f"https://example.invalid/unrelated/{index}",
                    f"old/{index}.pdf",
                    content,
                ),
                separators=(",", ":"),
            ))
            stream.write("\n")
        stream.write(json.dumps(_history_record(
            wanted_url,
            "wanted.pdf",
            content,
        )))
        stream.write("\n")

    history = _DownloadHistory(tmp_path, MagicMock())
    tracemalloc.start()
    try:
        history.prepare_lookups(
            [(wanted_url, wanted_path, ".pdf")],
            [(wanted_url, ".pdf")],
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(history._exact_records) == 1
    assert len(history._url_format_records) == 1
    assert peak < 16 * 1024 * 1024


def test_download_result_updates_only_changed_task_counter():
    result = DownloadResult(total=2)
    first = DownloadTask(
        FileInfo("https://example.invalid/1", "1.pdf", ".pdf"),
        "1.pdf",
        status="pending",
    )
    second = DownloadTask(
        FileInfo("https://example.invalid/2", "2.pdf", ".pdf"),
        "2.pdf",
        status="pending",
    )

    with patch.object(
        result,
        "_recount",
        side_effect=AssertionError("全件再集計してはいけません"),
    ):
        result.add_task(first)
        result.add_task(second)
        first.status = "completed"
        result.update_status(first)
        result.update_status(first)
        second.status = "failed"
        result.update_status(second)

    assert result.success == 1
    assert result.failed == 1
    assert result.accounted == result.total == 2


def _project(project_id: str, *, expired: bool = False):
    status = "EXPIRED" if expired else "PUBLIC"
    decision = (
        DocumentDecision.EXCLUDED_EXPIRED.value
        if expired
        else DocumentDecision.DOWNLOAD_TARGET.value
    )
    classification = (
        ProjectClassification.EXPIRED_ONLY.value
        if expired
        else ProjectClassification.PUBLIC_AVAILABLE.value
    )
    return ProjectDocumentSummary(
        project_id=project_id,
        project_name=project_id,
        documents=[DocumentSummary(
            document_name="文書",
            public_status=status,
            decision=decision,
        )],
        classification=classification,
    )


def test_search_summary_upsert_uses_project_delta_without_full_refresh():
    summary = SearchExtractionSummary()

    with patch.object(
        summary,
        "refresh_counts",
        side_effect=AssertionError("全案件再集計してはいけません"),
    ):
        summary.upsert_project(_project("A"))
        summary.upsert_project(_project("B", expired=True))
        adopted = summary.upsert_project(_project("A", expired=True))

    assert adopted.classification == ProjectClassification.EXPIRED_ONLY.value
    assert summary.projects_scanned == 2
    assert summary.public_documents == 0
    assert summary.expired_documents == 2
    assert summary.expired_only_projects == 2
    assert summary.target_documents == 0
    assert len(summary._project_index) == 2


def test_search_summary_10k_projects_keeps_one_indexed_copy():
    summary = SearchExtractionSummary()

    for index in range(10_000):
        summary.upsert_project(_project(f"project-{index}"))

    assert summary.projects_scanned == 10_000
    assert summary.public_documents == 10_000
    assert summary.target_documents == 10_000
    assert len(summary.projects) == 10_000
    assert len(summary._project_index) == 10_000
    assert len(summary._project_contributions) == 10_000
