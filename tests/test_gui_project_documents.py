# -*- coding: utf-8 -*-

"""検索集計と工事・文書内訳GUIの単体テスト。"""

from threading import get_ident
from types import SimpleNamespace
from unittest.mock import Mock

from src.gui.main_window import MainWindow
from src.gui.project_documents_dialog import (
    FILTER_AGENCY_UNRESOLVED,
    FILTER_EMPTY,
    FILTER_EXPIRED,
    FILTER_TARGET,
    FILTER_UNKNOWN,
    filter_projects,
    format_search_summary,
    normalise_projects,
)
from src.models.search_summary import (
    DocumentDecision,
    DocumentSummary,
    ProjectDocumentSummary,
    SearchExtractionSummary,
)


class _Variable:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Widget:
    def __init__(self):
        self.options = {}

    def config(self, **kwargs):
        self.options.update(kwargs)


def _project_payloads():
    return [
        {
            "project_id": "A001",
            "project_name": "国道13号 金山第二トンネル工事",
            "documents": [
                {
                    "document_name": "入札公告",
                    "public_status": "公開中",
                    "document_updated_at": "2025年07月29日 16時53分",
                    "listing_end_at": "2027-03-31T23:00:00+09:00",
                    "decision": "DOWNLOAD",
                },
                {
                    "document_name": "設計書",
                    "public_status": "PUBLIC",
                    "document_updated_at": "20260529_1358",
                    "decision": "REUSE_LEGACY",
                },
            ],
        },
        {
            "project_id": "A002",
            "project_name": "公開終了工事",
            "documents": [
                {
                    "document_name": "旧入札公告",
                    "public_status": "EXPIRED",
                    "listing_end_at": "2025-03-31T23:00:00",
                }
            ],
        },
        {
            "project_id": "A003",
            "project_name": "文書なし工事",
            "documents": [],
        },
        {
            "project_id": "A004",
            "project_name": "確認不能工事",
            "classification": "DETAIL_FAILED",
            "documents": [],
        },
    ]


def test_normalise_projects_preserves_document_specific_values():
    """文書名・公開状態・行固有日時・取得判定を表示へ引き継ぐ。"""
    projects = normalise_projects(_project_payloads())
    project = projects[0]

    assert project.name == "国道13号 金山第二トンネル工事"
    assert project.public_count == 2
    assert project.target_count == 2
    assert project.documents[0].name == "入札公告"
    assert project.documents[0].updated_at == "2025/07/29 16:53"
    assert project.documents[0].listing_end_at == "2027/03/31 23:00"
    assert project.documents[0].decision == "新規・更新"
    assert project.documents[1].updated_at == "2026/05/29 13:58"
    assert project.documents[1].decision == "旧命名を再利用"


def test_normalise_current_search_summary_dataclasses():
    """サービス公開モデルを変換し、日本語の確定判定を表示する。"""
    project = ProjectDocumentSummary(
        project_id="A100",
        project_name="モデル工事",
        documents=[
            DocumentSummary(
                document_name="入札調書",
                public_status="PUBLIC",
                document_updated_at="2026-02-04T14:22:00+09:00",
                decision=DocumentDecision.REUSED.value,
            )
        ],
        classification="PUBLIC_AVAILABLE",
    )
    summary = SearchExtractionSummary(
        projects=[project],
        projects_matched=1,
        complete=True,
    )
    summary.refresh_counts()

    projects = normalise_projects(summary.projects)

    assert projects[0].documents[0].decision == "保存済み"
    assert projects[0].target_count == 1
    assert "検索解析完了：案件1件" in format_search_summary(
        summary, projects
    )


def test_project_filters_and_text_search():
    """内訳の5分類と工事・文書名検索を工事単位で適用する。"""
    projects = normalise_projects(_project_payloads())

    assert [p.project_id for p in filter_projects(projects, FILTER_TARGET)] == [
        "A001"
    ]
    assert [p.project_id for p in filter_projects(projects, FILTER_EXPIRED)] == [
        "A002"
    ]
    assert [p.project_id for p in filter_projects(projects, FILTER_EMPTY)] == [
        "A003",
        "A004",
    ]
    assert [p.project_id for p in filter_projects(projects, FILTER_UNKNOWN)] == [
        "A004"
    ]
    assert [
        p.project_id
        for p in filter_projects(projects, FILTER_AGENCY_UNRESOLVED)
    ] == ["A001", "A002", "A003", "A004"]
    assert [p.project_id for p in filter_projects(projects, query="設計書")] == [
        "A001"
    ]


def test_project_agency_diagnostics_and_planned_folder_are_visible():
    """発注機関の確定根拠と保存予定階層を表示モデルへ引き継ぐ。"""

    (project,) = normalise_projects(
        [
            {
                "project_id": "A010",
                "project_name": "道路改良工事",
                "agency_path": {
                    "version": 2,
                    "segments": [
                        {"level": "daibunrui", "label": "国の機関", "code": "1"},
                        {"level": "chubunrui", "label": "国土交通省", "code": "2"},
                        {"level": "shoubunrui", "label": "東北地方整備局", "code": "3"},
                        {"level": "saibunrui", "label": "仙台河川国道事務所", "code": "4"},
                    ],
                    "resolution": {
                        "status": "detail_matched",
                        "reason_code": "OFFICE_LABEL_MATCH",
                    },
                },
                "agency_resolution_status": "detail_matched",
                "agency_resolution_reason_code": "OFFICE_LABEL_MATCH",
                "documents": [
                    {
                        "document_name": "入札公告",
                        "public_status": "PUBLIC",
                        "section": "入札公告等",
                    }
                ],
            }
        ]
    )

    assert project.agency_status_label == "詳細情報で確定"
    assert project.agency_reason_code == "OFFICE_LABEL_MATCH"
    assert project.agency_path.endswith("東北地方整備局 > 仙台河川国道事務所")
    assert project.planned_folder == (
        "国の機関\\国土交通省\\東北地方整備局\\"
        "仙台河川国道事務所\\道路改良工事"
    )
    assert filter_projects((project,), FILTER_AGENCY_UNRESOLVED) == ()


def test_unresolved_agency_uses_quarantine_folder_and_reason_label():
    """分類未解決は推測せず99配下と固定理由を表示する。"""

    (project,) = normalise_projects(
        [
            {
                "project_name": "トンネル工事",
                "office_name": "不明事務所",
                "agency_resolution_status": "unresolved",
                "agency_resolution_reason_code": "AGENCY_FINE_NOT_FOUND",
                "documents": [],
            }
        ]
    )

    assert project.is_agency_unresolved is True
    assert project.agency_reason == (
        "担当部・事務所に一致する細分類がありません"
    )
    assert project.planned_folder == (
        "99_分類未解決\\不明事務所\\トンネル工事"
    )


def test_project_prefers_core_planned_agency_folder():
    """GUIで保存実装と異なる階層を再計算せず、公開済み計画を使う。"""

    (project,) = normalise_projects(
        [
            {
                "project_name": "橋梁工事",
                "agency_resolution_status": "selected",
                "planned_agency_folder": ["正本の大分類", "正本の細分類"],
                "documents": [],
            }
        ]
    )

    assert project.planned_folder == (
        "正本の大分類\\正本の細分類\\橋梁工事"
    )


def test_format_search_summary_keeps_expired_scope_distinct():
    """公開終了が検索範囲外の場合は0件ではなく集計対象外と表示する。"""
    text = format_search_summary(
        {
            "projects_matched": 13,
            "public_documents": 14,
            "expired_only_projects": 7,
            "target_documents": 14,
            "download_count": 0,
            "reuse_count": 14,
            "legacy_reuse_count": 14,
            "complete": True,
        }
    )

    assert "検索解析完了：案件13件" in text
    assert "公開中データ14件" in text
    assert "公開終了のみ7件" in text
    assert "今回の対象：14件" in text
    assert "保存済み確認14件〈旧命名14件〉" in text

    excluded = format_search_summary(
        {
            "projects_matched": 13,
            "expired_scope_excluded": True,
            "complete": True,
        }
    )
    assert "公開終了のみ集計対象外" in excluded


def test_main_window_consumes_search_summary_on_ui_thread():
    """検索イベントの集計・内訳を固定表示と開いている画面へ渡す。"""
    dialog = Mock()
    dialog.is_alive.return_value = True
    window = MainWindow.__new__(MainWindow)
    window._ui_thread_id = get_ident()
    window._search_summary = None
    window._project_document_projects = ()
    window._project_documents_dialog = dialog
    window.summary_var = _Variable("検索集計：未実行")
    window.btn_project_documents = _Widget()
    window._set_search_progress_mode = Mock()

    window.update_search_progress(
        {
            "phase": "search",
            "search_phase": "complete",
            "page": 1,
            "row": 13,
            "rows_on_page": 13,
            "projects_scanned": 13,
            "files_discovered": 14,
            "search_summary": {
                "projects_matched": 13,
                "public_documents": 14,
                "expired_only_projects": 7,
                "target_documents": 14,
                "download_count": 14,
            },
            "projects": _project_payloads(),
        }
    )

    assert "検索解析完了：案件13件" in window.summary_var.get()
    assert window.btn_project_documents.options["state"] == "normal"
    assert len(window._project_document_projects) == 4
    dialog.update_data.assert_called_once()
    window._set_search_progress_mode.assert_called_once_with(
        "検索解析完了。ダウンロード対象を確認しています..."
    )


def test_search_summary_update_from_worker_is_queued():
    """ワーカースレッド相当の呼出しではTk変数へ直接触れない。"""
    window = MainWindow.__new__(MainWindow)
    window._ui_thread_id = -1
    window.event_handler = SimpleNamespace(call_soon=Mock())
    window.summary_var = _Variable("変更前")

    summary = {"projects_matched": 1}
    projects = _project_payloads()[:1]
    window.update_search_summary(summary, projects, complete=False)

    assert window.summary_var.get() == "変更前"
    window.event_handler.call_soon.assert_called_once_with(
        window.update_search_summary,
        summary,
        projects,
        complete=False,
    )
