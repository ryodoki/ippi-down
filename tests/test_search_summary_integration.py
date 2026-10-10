# -*- coding: utf-8 -*-

"""検索集計からサービスイベントまでの受入テスト。"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.app.events import EventType
from src.app.run_result import RunOutcome, RunResult
from src.app.service import ApplicationService
from src.core.parser.models import ProjectEntry
from src.core.scraper import Scraper
from src.models.download_result import DownloadResult
from src.models.download_task import DownloadTask
from src.models.file_info import FileInfo
from src.models.agency import (
    AgencyPath,
    AgencyPathResolution,
    AgencyResolutionStatus,
)
from src.models.search_summary import (
    DocumentDecision,
    DocumentSummary,
    ProjectClassification,
    ProjectDocumentSummary,
    SearchExtractionSummary,
)


def _document(
    project_number: int,
    document_number: int,
    *,
    status: str = "PUBLIC",
    decision: str = DocumentDecision.DOWNLOAD_TARGET.value,
    url: str | None = None,
) -> DocumentSummary:
    if url is None and status == "PUBLIC":
        url = (
            "https://example.invalid/document/"
            f"{project_number}/{document_number}.pdf"
        )
    return DocumentSummary(
        document_name=f"文書{project_number}-{document_number}",
        public_status=status,
        document_updated_at="2026-08-03T09:00:00+09:00",
        listing_end_at="2028-03-31T23:00:00+09:00",
        decision=decision,
        url=url or "",
        document_id=f"{project_number:02d}{document_number:02d}",
    )


def _acceptance_summary() -> SearchExtractionSummary:
    """13工事・公開中14文書・公開終了のみ7工事を組み立てる。"""
    public_document_counts = (4, 1, 3, 3, 1, 2)
    projects = [
        ProjectDocumentSummary(
            project_id=f"PUBLIC-{project_number}",
            project_name=f"公開中工事{project_number}",
            documents=[
                _document(project_number, document_number)
                for document_number in range(1, document_count + 1)
            ],
            classification=ProjectClassification.PUBLIC_AVAILABLE.value,
        )
        for project_number, document_count in enumerate(
            public_document_counts, start=1
        )
    ]
    projects.extend(
        ProjectDocumentSummary(
            project_id=f"EXPIRED-{project_number}",
            project_name=f"公開終了工事{project_number}",
            documents=[
                _document(
                    project_number + 100,
                    1,
                    status="EXPIRED",
                    decision=DocumentDecision.EXCLUDED_EXPIRED.value,
                    url="",
                )
            ],
            classification=ProjectClassification.EXPIRED_ONLY.value,
        )
        for project_number in range(1, 8)
    )
    summary = SearchExtractionSummary(
        projects=projects,
        projects_matched=13,
        complete=True,
    )
    summary.refresh_counts()
    return summary


def test_acceptance_counts_13_projects_14_public_and_7_expired_only():
    """受入例の案件・公開文書・対象文書の件数を一度に検証する。"""
    summary = _acceptance_summary()

    assert summary.projects_matched == 13
    assert summary.projects_scanned == 13
    assert summary.public_documents == 14
    assert summary.expired_documents == 7
    assert summary.expired_only_projects == 7
    assert summary.target_documents == 14

    message = ApplicationService._format_search_summary(summary)
    assert "検索解析完了: 案件13件" in message
    assert "公開中データ14件" in message
    assert "公開終了のみ7件" in message
    assert "今回のダウンロード対象14件" in message


def test_filter_decisions_distinguish_link_missing_type_and_user_filter():
    """公開中リンク欠落を終了扱いせず、対象外理由を分離する。"""
    target = _document(1, 1)
    keyword_excluded = _document(1, 2)
    type_excluded = _document(1, 3)
    link_missing = _document(1, 4, url="")
    expired = _document(
        1,
        5,
        status="EXPIRED",
        decision=DocumentDecision.EXCLUDED_EXPIRED.value,
        url="https://example.invalid/expired.pdf",
    )
    project = ProjectDocumentSummary(
        project_id="PROJECT-1",
        project_name="判定確認工事",
        documents=[
            target,
            keyword_excluded,
            type_excluded,
            link_missing,
            expired,
        ],
        classification=ProjectClassification.PUBLIC_AVAILABLE.value,
    )
    summary = SearchExtractionSummary(
        projects=[project], projects_matched=1, complete=True
    )
    all_files = [
        FileInfo(target.url, "target.pdf", ".pdf"),
        FileInfo(keyword_excluded.url, "filtered.pdf", ".pdf"),
    ]

    ApplicationService._apply_filter_decisions(
        summary, all_files, [all_files[0]]
    )

    assert target.decision == DocumentDecision.DOWNLOAD_TARGET.value
    assert (
        keyword_excluded.decision
        == DocumentDecision.EXCLUDED_FILTER.value
    )
    assert (
        type_excluded.decision
        == DocumentDecision.EXCLUDED_FILE_TYPE.value
    )
    assert (
        link_missing.decision
        == DocumentDecision.PUBLIC_LINK_MISSING.value
    )
    assert link_missing.public_status == "PUBLIC"
    assert expired.decision == DocumentDecision.EXCLUDED_EXPIRED.value
    assert summary.candidate_documents == 2
    assert summary.target_documents == 1


def test_download_results_replace_planned_decisions_with_final_results():
    """取得結果をDOWNLOADEDとREUSED_LEGACYへ確定する。"""
    downloaded = _document(1, 1)
    reused_legacy = _document(1, 2)
    summary = SearchExtractionSummary(
        projects=[
            ProjectDocumentSummary(
                project_id="PROJECT-1",
                project_name="結果反映工事",
                documents=[downloaded, reused_legacy],
                classification=(
                    ProjectClassification.PUBLIC_AVAILABLE.value
                ),
            )
        ],
        projects_matched=1,
        complete=True,
    )
    completed_task = DownloadTask(
        FileInfo(downloaded.url, "downloaded.pdf", ".pdf"),
        "C:/downloads/downloaded.pdf",
        status="completed",
    )
    reused_task = DownloadTask(
        FileInfo(reused_legacy.url, "legacy.pdf", ".pdf"),
        "C:/downloads/legacy.pdf",
        status="skipped",
        reuse_kind="LEGACY_PATH_ALIAS",
    )
    result = DownloadResult(
        total=2, tasks=[completed_task, reused_task]
    )

    ApplicationService._apply_download_results(summary, result)

    assert downloaded.decision == DocumentDecision.DOWNLOADED.value
    assert (
        reused_legacy.decision == DocumentDecision.REUSED_LEGACY.value
    )
    assert summary.target_documents == 2
    assert summary.download_count == 1
    assert summary.reuse_count == 1
    assert summary.legacy_reuse_count == 1


def test_failed_and_cancelled_documents_remain_in_target_total():
    """失敗・キャンセル後も「今回対象」の母数を縮めない。"""
    failed = _document(1, 1)
    cancelled = _document(1, 2)
    summary = SearchExtractionSummary(
        projects=[
            ProjectDocumentSummary(
                project_id="PROJECT-1",
                project_name="未完了結果工事",
                documents=[failed, cancelled],
                classification=(
                    ProjectClassification.PUBLIC_AVAILABLE.value
                ),
            )
        ],
        projects_matched=1,
        complete=True,
    )
    result = DownloadResult(
        total=2,
        tasks=[
            DownloadTask(
                FileInfo(failed.url, "failed.pdf", ".pdf"),
                "C:/downloads/failed.pdf",
                status="failed",
                error_message="取得失敗",
            ),
            DownloadTask(
                FileInfo(cancelled.url, "cancelled.pdf", ".pdf"),
                "C:/downloads/cancelled.pdf",
                status="cancelled",
            ),
        ],
    )

    ApplicationService._apply_download_results(summary, result)

    assert failed.decision == DocumentDecision.FAILED.value
    assert cancelled.decision == DocumentDecision.CANCELLED.value
    assert summary.target_documents == 2
    assert summary.download_count == 0
    assert summary.reuse_count == 0


def test_public_only_marks_expired_count_out_of_scope_in_service_event():
    """公開中のみ検索では、終了のみ工事件数を0件と断定しない。"""
    summary = _acceptance_summary()
    events = []
    service = ApplicationService(Mock())

    service._emit_search_summary(events.append, summary, public_only=True)

    assert summary.expired_scope_excluded is True
    assert len(events) == 1
    event = events[0]
    assert event.type is EventType.PROGRESS
    assert "公開終了のみ集計対象外（公開中のみ）" in event.message
    assert event.metadata["search_summary"][
        "expired_scope_excluded"
    ] is True


def test_service_events_include_project_document_dictionaries():
    """検索途中・終了イベントの双方へ同じ工事内訳を載せる。"""
    summary = _acceptance_summary()
    events = []
    service = ApplicationService(Mock())

    service._emit_search_summary(events.append, summary, public_only=False)
    run_result = RunResult(
        success=True,
        result=DownloadResult(total=14, success=14),
        message="完了",
        outcome=RunOutcome.SUCCESS,
        search_summary=summary,
    )
    service._emit_terminal_event(events.append, run_result)

    expected_projects = summary.project_dicts()
    assert events[0].metadata["projects"] == expected_projects
    assert events[0].metadata["search_summary"]["projects_matched"] == 13
    assert events[1].type is EventType.COMPLETE
    assert events[1].metadata["projects"] == expected_projects
    assert events[1].metadata["search_summary"]["public_documents"] == 14
    assert events[1].metadata["search_summary"][
        "expired_only_projects"
    ] == 7


def test_summary_merge_deduplicates_projects_and_prefers_valid_detail():
    """同一案件の詳細失敗が、別取得元の正常な内訳を上書きしない。"""
    document = _document(1, 1)
    valid = ProjectDocumentSummary(
        project_id="ANKEN-1",
        project_name="正常工事",
        documents=[document],
        classification=ProjectClassification.PUBLIC_AVAILABLE.value,
    )
    failed = ProjectDocumentSummary(
        project_id="ANKEN-1",
        project_name="正常工事",
        classification=ProjectClassification.DETAIL_FAILED.value,
        detail_error="一時的な解析失敗",
    )
    summary = SearchExtractionSummary(complete=True)

    summary.merge(SearchExtractionSummary(
        projects=[valid], projects_matched=1, complete=True
    ))
    summary.merge(SearchExtractionSummary(
        projects=[failed], projects_matched=1, complete=False
    ))

    assert summary.projects_matched == 1
    assert summary.projects_scanned == 1
    assert summary.public_documents == 1
    assert summary.detail_failed_projects == 0
    assert summary.projects[0].detail_error == ""
    assert summary.complete is False


def test_agency_classification_fields_and_reason_counts_propagate():
    resolved = ProjectDocumentSummary(
        project_id="A",
        project_name="解決済み",
        agency_resolution_status="detail_matched",
        agency_resolution_method="detail_label",
        agency_resolution_reason_code="OFFICE_LABEL_MATCH",
    )
    unresolved = ProjectDocumentSummary(
        project_id="B",
        project_name="未解決",
        agency_resolution_status="unresolved",
        agency_resolution_method="detail",
        agency_resolution_reason_code="AGENCY_FINE_NOT_FOUND",
        agency_resolution_reason="細分類候補なし",
    )
    summary = SearchExtractionSummary(projects=[resolved, unresolved])

    payload = summary.to_dict(include_projects=True)

    assert payload["agency_resolved_projects"] == 1
    assert payload["agency_unresolved_projects"] == 1
    assert payload["agency_resolution_counts"] == {
        "detail_matched": 1,
        "unresolved": 1,
    }
    assert payload["agency_issue_counts"] == {
        "AGENCY_FINE_NOT_FOUND": 1,
    }
    assert payload["projects"][1]["agency_resolution_reason"] == (
        "細分類候補なし"
    )
    assert payload["projects"][1]["planned_agency_folder"] == []


def test_scraper_logs_one_structured_agency_classification_per_project():
    logger = Mock()
    scraper = Scraper(Mock(), logger)
    path = AgencyPath.from_labels_and_codes(
        ("国の機関", "国土交通省", "中部地方整備局"),
        ("0", "21", "05"),
    )
    resolution = AgencyPathResolution(
        path=path,
        status=AgencyResolutionStatus.UNRESOLVED,
        method="detail",
        reason="細分類候補なし",
        office_name="飯田国道事務所",
        agency_id="02105000",
        reason_code="AGENCY_FINE_NOT_FOUND",
    )
    project_entry = ProjectEntry(
        detail_url="https://example.invalid/detail",
        koji_name="テスト工事",
        metadata={},
        agency_path=path,
        agency_resolution=resolution,
        office_name=resolution.office_name,
        agency_id=resolution.agency_id,
    )

    scraper._record_project_document_summary(
        project_entry=project_entry,
        koji_name="テスト工事",
        document_rows=[],
        candidates=[],
    )
    scraper._record_project_document_summary(
        project_entry=project_entry,
        koji_name="テスト工事",
        document_rows=[],
        candidates=[],
    )

    classification_logs = [
        call.args[0]
        for call in logger.warning.call_args_list
        if call.args and call.args[0].startswith("agency.classification ")
    ]
    assert len(classification_logs) == 1
    assert '"reason_code": "AGENCY_FINE_NOT_FOUND"' in (
        classification_logs[0]
    )
    assert '"hachusha_id": "02105000"' in classification_logs[0]
    classification_payload = json.loads(
        classification_logs[0].removeprefix("agency.classification ")
    )
    assert classification_payload["planned_agency_folder"] == [
        "99_分類未解決",
        "国の機関",
        "国土交通省",
        "中部地方整備局",
        "飯田国道事務所",
    ]
    project_payload = scraper.last_search_summary.projects[0].to_dict()
    assert project_payload["planned_agency_folder"] == (
        classification_payload["planned_agency_folder"]
    )


def test_scraper_classifies_expired_empty_unknown_and_failed_separately():
    """公開終了、文書なし、状態不明、解析失敗を相互排他的に数える。"""
    scraper = Scraper(Mock(), Mock())

    def record(row_no, rows, error=""):
        scraper._record_project_document_summary(
            project_entry=ProjectEntry(
                detail_url="https://example.invalid/search",
                koji_name=f"工事{row_no}",
                metadata={},
                page_no=1,
                row_no=row_no,
                source_url="https://example.invalid/search",
            ),
            koji_name=f"工事{row_no}",
            document_rows=rows,
            candidates=[],
            detail_error=error,
        )

    record(1, [SimpleNamespace(
        status="EXPIRED", document_name="終了文書", href=""
    )])
    record(2, [])
    record(3, [SimpleNamespace(
        status="UNKNOWN", document_name="不明文書", href=""
    )])
    record(4, [], "詳細取得失敗")

    summary = scraper.last_search_summary
    assert summary.projects_scanned == 4
    assert summary.expired_only_projects == 1
    assert summary.no_document_projects == 1
    assert summary.unknown_status_projects == 1
    assert summary.detail_failed_projects == 1
    assert (
        summary.expired_only_projects
        + summary.no_document_projects
        + summary.unknown_status_projects
        + summary.detail_failed_projects
    ) == summary.projects_scanned


def test_search_page_returned_for_detail_is_classified_as_detail_failure():
    """POSTバック誤応答を「公開文書なし」と誤表示しない。"""
    response = SimpleNamespace(
        encoding="utf-8",
        apparent_encoding="utf-8",
        status_code=200,
        content=(
            b"<html><head><title>\xe5\xb7\xa5\xe4\xba\x8b\xe6\xa4\x9c\xe7\xb4\xa2</title></head>"
            b"<body><table id='dgrSearchList'></table></body></html>"
        ),
    )
    http_client = Mock()
    http_client.post.return_value = response
    scraper = Scraper(http_client, Mock())
    current_soup = scraper._parse_response_to_soup(SimpleNamespace(
        encoding="utf-8",
        apparent_encoding="utf-8",
        content=(
            b"<form action='/detail'><input type='hidden' "
            b"name='__VIEWSTATE' value='x'></form>"
        ),
    ))

    files = scraper._extract_files_from_detail_page_via_postback(
        "https://example.invalid/search",
        "javascript:__doPostBack('dgrSearchList','$0')",
        [".pdf"],
        current_soup,
        koji_name="誤応答工事",
        project_entry=ProjectEntry(
            detail_url="https://example.invalid/search",
            koji_name="誤応答工事",
            metadata={},
            page_no=1,
            row_no=1,
            source_url="https://example.invalid/search",
        ),
    )

    assert files == []
    assert scraper.last_search_diagnostics.detail_failed == 1
    assert scraper.last_search_summary.detail_failed_projects == 1
    assert scraper.last_search_summary.no_document_projects == 0


def test_service_deduplicates_republished_files_and_merges_metadata():
    """複数ページで同じURLが再掲されても実行タスクは一件にする。"""
    first = FileInfo(
        "https://example.invalid/document.pdf",
        "document.pdf",
        ".pdf",
        metadata={"document_name": "入札公告"},
    )
    second = FileInfo(
        first.url,
        "duplicate.pdf",
        ".pdf",
        metadata={"document_updated_at": "2026-08-03T09:00:00+09:00"},
        allow_html_to_pdf=True,
    )

    unique = ApplicationService._deduplicate_files([first, second])

    assert unique == [first]
    assert first.metadata == {
        "document_name": "入札公告",
        "document_updated_at": "2026-08-03T09:00:00+09:00",
    }
    assert first.allow_html_to_pdf is True


def test_download_total_remains_authoritative_without_inventory_row():
    """フォールバック候補も対象総数から欠落させない。"""
    summary = SearchExtractionSummary(complete=True)
    result = DownloadResult(total=1, success=1)

    ApplicationService._apply_download_results(summary, result)

    assert summary.target_documents == 1
    assert summary.download_count == 1


def test_final_summary_event_is_emitted_before_terminal_event():
    """確定内訳を通知してから実行終了イベントを送る。"""
    summary = _acceptance_summary()
    events = []
    service = ApplicationService(Mock())

    service._emit_search_summary(events.append, summary, public_only=False)
    service._emit_terminal_event(
        events.append,
        RunResult(
            success=True,
            result=DownloadResult(total=14, success=14),
            message="完了",
            outcome=RunOutcome.SUCCESS,
            search_summary=summary,
        ),
    )

    assert [event.type for event in events] == [
        EventType.PROGRESS,
        EventType.COMPLETE,
    ]
