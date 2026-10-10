# -*- coding: utf-8 -*-

"""案件ごとの公開文書を確認する非モーダル画面。"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import PureWindowsPath
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from tkinter import ttk
from .window_layout import fit_to_screen
from typing import Any, Callable, Optional

from ..utils.file_utils import FileUtils


FILTER_ALL = "すべて"
FILTER_TARGET = "DL対象あり"
FILTER_EXPIRED = "公開終了のみ"
FILTER_EMPTY = "文書なし"
FILTER_UNKNOWN = "確認不能"
FILTER_AGENCY_UNRESOLVED = "分類未解決"
FILTER_OPTIONS = (
    FILTER_ALL,
    FILTER_TARGET,
    FILTER_EXPIRED,
    FILTER_EMPTY,
    FILTER_UNKNOWN,
    FILTER_AGENCY_UNRESOLVED,
)

_STATUS_LABELS = {
    "PUBLIC": "公開中",
    "EXPIRED": "公開終了",
    "SCHEDULED": "公開予定",
    "NON_PUBLIC": "非公開",
    "UNKNOWN": "確認不能",
}
_STATUS_ALIASES = {
    "PUBLIC": "PUBLIC",
    "OPEN": "PUBLIC",
    "CURRENT": "PUBLIC",
    "公開中": "PUBLIC",
    "EXPIRED": "EXPIRED",
    "CLOSED": "EXPIRED",
    "END": "EXPIRED",
    "公開終了": "EXPIRED",
    "掲載終了": "EXPIRED",
    "SCHEDULED": "SCHEDULED",
    "FUTURE": "SCHEDULED",
    "公開予定": "SCHEDULED",
    "NON_PUBLIC": "NON_PUBLIC",
    "PRIVATE": "NON_PUBLIC",
    "非公開": "NON_PUBLIC",
    "UNKNOWN": "UNKNOWN",
    "確認不能": "UNKNOWN",
    "不明": "UNKNOWN",
}
_TARGET_DECISIONS = {
    "DOWNLOAD",
    "DOWNLOAD_TARGET",
    "DOWNLOADED",
    "NEW",
    "UPDATE",
    "NEW_OR_UPDATE",
    "REUSED",
    "REUSED_LEGACY",
    "REUSE_EXACT",
    "REUSE_LEGACY",
    "HISTORY_MATCH",
}
_DECISION_LABELS = {
    "DOWNLOAD": "新規・更新",
    "DOWNLOAD_TARGET": "新規・更新",
    "DOWNLOADED": "新規・更新",
    "NEW": "新規・更新",
    "UPDATE": "新規・更新",
    "NEW_OR_UPDATE": "新規・更新",
    "REUSED": "保存済み",
    "REUSE_EXACT": "保存済み",
    "HISTORY_MATCH": "保存済み",
    "REUSED_LEGACY": "旧命名を再利用",
    "REUSE_LEGACY": "旧命名を再利用",
    "PUBLIC_LINK_MISSING": "確認不能（公開中リンクなし）",
    "UNAVAILABLE": "確認不能",
    "FAILED": "失敗",
    "CANCELLED": "キャンセル",
    "NOT_EVALUATED": "未判定",
    "UNKNOWN": "確認不能",
}
_UNKNOWN_DECISIONS = {
    "PUBLIC_LINK_MISSING",
    "UNAVAILABLE",
    "NOT_EVALUATED",
    "UNKNOWN",
}
_JST = timezone(timedelta(hours=9))

_AGENCY_STATUS_LABELS = {
    "selected": "検索条件で確定",
    "detail_matched": "詳細情報で確定",
    "unresolved": "分類未解決",
}
_AGENCY_REASON_LABELS = {
    "AGENCY_SELECTED": "検索条件の発注機関階層を使用しました",
    "OFFICE_LABEL_MATCH": "担当部・事務所名を分類候補と照合しました",
    "LEGACY_ID_MATCH": "旧形式の機関IDを分類候補と照合しました",
    "AGENCY_SELECTION_MISSING": "発注機関が選択されていません",
    "AGENCY_DETAIL_MISSING": "詳細ページに担当部・事務所情報がありません",
    "AGENCY_FINE_NOT_FOUND": "担当部・事務所に一致する細分類がありません",
    "AGENCY_FINE_AMBIGUOUS": "担当部・事務所に一致する細分類が複数あります",
    "AGENCY_OFFICE_CONFLICT": "検索条件と詳細ページの担当部・事務所が一致しません",
    "AGENCY_CATALOG_FETCH_FAILED": "発注機関候補を取得できませんでした",
    "AGENCY_PATH_INCOMPLETE": "発注機関階層が途中までしか確定していません",
}


@dataclass(frozen=True)
class DocumentView:
    """Treeviewへ表示する文書情報。"""

    name: str
    status: str
    updated_at: str
    listing_end_at: str
    decision: str
    decision_code: str
    is_target: bool
    is_unknown: bool
    section: str = ""


@dataclass(frozen=True)
class ProjectView:
    """Treeviewへ表示する工事情報。"""

    project_id: str
    name: str
    documents: tuple[DocumentView, ...]
    public_count: int
    expired_count: int
    target_count: int
    classification: str
    agency_path: str = ""
    agency_status: str = "unresolved"
    agency_status_label: str = "分類未解決"
    agency_reason_code: str = ""
    agency_reason: str = ""
    office_name: str = ""
    agency_id: str = ""
    planned_folder: str = ""

    @property
    def is_expired_only(self) -> bool:
        """文書があり、すべて公開終了かを返す。"""
        if self.classification == "EXPIRED_ONLY":
            return True
        return bool(self.documents) and all(
            document.status == "EXPIRED" for document in self.documents
        )

    @property
    def is_unknown(self) -> bool:
        """確認不能な工事または文書を含むかを返す。"""
        return self.classification in {
            "UNKNOWN",
            "DETAIL_FAILED",
            "PUBLIC_LINK_MISSING",
        } or any(document.is_unknown for document in self.documents)

    @property
    def is_agency_unresolved(self) -> bool:
        """保存先の発注機関分類が確定していないかを返す。"""

        return self.agency_status == "unresolved"


def _enum_value(value: Any) -> Any:
    """Enumを外部表現へ変換する。"""
    return value.value if isinstance(value, Enum) else value


def payload_value(payload: Any, *names: str, default: Any = None) -> Any:
    """dictまたはdataclass風オブジェクトから値を取得する。"""
    if payload is None:
        return default
    for name in names:
        if isinstance(payload, Mapping) and name in payload:
            return payload[name]
        if hasattr(payload, name):
            return getattr(payload, name)
    return default


def _as_sequence(value: Any) -> list[Any]:
    """文字列を除く反復可能値をlistへ正規化する。"""
    if value is None:
        return []
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, (str, bytes)):
        return []
    if isinstance(value, Iterable):
        return list(value)
    return []


def _normalise_code(value: Any) -> str:
    """状態・判定コードを比較用の大文字へ揃える。"""
    value = _enum_value(value)
    return str(value or "").strip().upper().replace("-", "_")


def _normalise_status(value: Any) -> str:
    """HP・モデル双方の公開状態を固定コードへ揃える。"""
    raw = str(_enum_value(value) or "").strip()
    if not raw:
        return "UNKNOWN"
    return _STATUS_ALIASES.get(raw, _STATUS_ALIASES.get(raw.upper(), "UNKNOWN"))


def _format_datetime(value: Any) -> str:
    """HP日時またはISO日時を一覧用の日本時間表記へ変換する。"""
    value = _enum_value(value)
    if value is None or value == "":
        return "－"
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        patterns = (
            (r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})$", "%Y%m%d_%H%M"),
            (
                r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s*"
                r"(\d{1,2})時(\d{1,2})分$",
                "%Y年%m月%d日 %H時%M分",
            ),
        )
        parsed = None
        for pattern, date_format in patterns:
            if re.match(pattern, text):
                try:
                    parsed = datetime.strptime(text, date_format)
                except ValueError:
                    parsed = None
                break
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_JST)
    return parsed.strftime("%Y/%m/%d %H:%M")


def _decision_label(payload: Any, status: str) -> tuple[str, str, bool]:
    """ダウンロード計画の判定を表示文言へ変換する。"""
    raw = payload_value(
        payload,
        "decision",
        "download_decision",
        "plan",
        "action",
        default="",
    )
    code = _normalise_code(raw)
    reason = str(
        payload_value(
            payload,
            "decision_reason",
            "reason",
            "exclusion_reason",
            default="",
        )
        or ""
    ).strip()
    explicit_target = payload_value(
        payload,
        "is_target",
        "target",
        "download_target",
        "eligible",
        default=None,
    )
    is_target = (
        bool(explicit_target)
        if explicit_target is not None
        else code in _TARGET_DECISIONS
    )
    if code in _DECISION_LABELS:
        return _DECISION_LABELS[code], code, is_target
    if code.startswith("EXCLUDED") or code in {"SKIP", "OUT_OF_SCOPE"}:
        label = f"対象外（{reason}）" if reason else "対象外"
        return label, code, False
    if raw:
        return str(_enum_value(raw)), code, is_target
    if status == "EXPIRED":
        return "対象外（公開終了）", "EXCLUDED_EXPIRED", False
    if status in {"UNKNOWN", "NON_PUBLIC", "SCHEDULED"}:
        return "確認不能", "UNKNOWN", False
    if explicit_target:
        return "新規・更新", "DOWNLOAD", True
    return "対象外", "OUT_OF_SCOPE", False


def _agency_segment_labels(value: Any) -> tuple[str, ...]:
    """agency_pathから順序を保った表示名だけを取り出す。"""

    if not isinstance(value, Mapping):
        return ()
    labels: list[str] = []
    for raw_segment in _as_sequence(value.get("segments")):
        label = str(payload_value(raw_segment, "label", "name", default="") or "").strip()
        if not label:
            continue
        if labels and labels[-1].casefold() == label.casefold():
            continue
        labels.append(label)
    return tuple(labels)


def _agency_resolution(payload: Any) -> tuple[str, str, str, tuple[str, ...]]:
    """案件payloadの分類状態・理由・パスを現行公開項目から得る。"""

    agency_path = payload_value(payload, "agency_path", default={})
    resolution = (
        agency_path.get("resolution", {})
        if isinstance(agency_path, Mapping)
        else {}
    )
    if not isinstance(resolution, Mapping):
        resolution = {"status": resolution}
    status = _normalise_code(
        payload_value(
            payload,
            "agency_resolution_status",
            default=payload_value(resolution, "status", default=""),
        )
    ).lower()
    labels = _agency_segment_labels(agency_path)
    if status not in _AGENCY_STATUS_LABELS:
        # 状態がない旧payloadは、完全に確定したとは推測せず安全側で扱う。
        status = "unresolved"
    reason_code = _normalise_code(
        payload_value(
            payload,
            "agency_resolution_reason_code",
            default=payload_value(resolution, "reason_code", default=""),
        )
    )
    reason = str(
        payload_value(
            payload,
            "agency_resolution_reason",
            default=payload_value(resolution, "reason", default=""),
        )
        or ""
    ).strip()
    if not reason:
        reason = _AGENCY_REASON_LABELS.get(reason_code, "")
    return status, reason_code, reason, labels


def _document_section_folder(section: str) -> str:
    """公開文書区分を保存仕様v3のフォルダー名へ変換する。"""

    normalized = str(section or "").strip()
    if normalized == "入札公告等" or "入札公告" in normalized:
        return "01_入札公告等"
    if normalized == "入札経過・その他" or "入札経過" in normalized or "入札の経過" in normalized:
        return "02_入札経過・その他"
    return "99_区分不明"


def _planned_project_folder(
    project_name: str,
    agency_labels: tuple[str, ...],
    agency_status: str,
    office_name: str,
    planned_agency_parts: tuple[str, ...] = (),
) -> str:
    """実行ルートから工事フォルダーまでの表示用相対パスを生成する。"""

    if planned_agency_parts:
        parts = list(planned_agency_parts)
        parts.append(project_name or "案件名不明")
        return str(PureWindowsPath(*parts))

    labels = list(agency_labels)
    if agency_status == "unresolved" and office_name and all(
        label.casefold() != office_name.casefold() for label in labels
    ):
        labels.append(office_name)
    parts: list[str] = []
    if agency_status == "unresolved" or not labels:
        parts.append("99_分類未解決")
    parts.extend(labels)
    parts.append(project_name or "案件名不明")
    safe_parts: list[str] = []
    for part in parts:
        safe = FileUtils.sanitize_path_component(part)
        if safe_parts and safe_parts[-1].casefold() == safe.casefold():
            continue
        safe_parts.append(safe)
    return str(PureWindowsPath(*safe_parts))


def normalise_document(payload: Any) -> DocumentView:
    """任意の文書payloadを表示モデルへ変換する。"""
    status = _normalise_status(
        payload_value(
            payload,
            "public_status",
            "status",
            "publication_status",
            default="UNKNOWN",
        )
    )
    decision, decision_code, is_target = _decision_label(payload, status)
    name = str(
        payload_value(
            payload,
            "document_name",
            "name",
            "title",
            default="文書名不明",
        )
        or "文書名不明"
    ).strip()
    return DocumentView(
        name=name,
        status=status,
        updated_at=_format_datetime(
            payload_value(
                payload,
                "document_updated_at",
                "updated_at",
                "last_updated_at",
            )
        ),
        listing_end_at=_format_datetime(
            payload_value(
                payload,
                "listing_end_at",
                "publication_end_at",
                "end_at",
            )
        ),
        decision=decision,
        decision_code=decision_code,
        is_target=is_target,
        is_unknown=(
            status == "UNKNOWN" or decision_code in _UNKNOWN_DECISIONS
        ),
        section=str(
            payload_value(payload, "section", "document_section", default="")
            or ""
        ).strip(),
    )


def normalise_project(payload: Any, index: int = 0) -> ProjectView:
    """任意の工事payloadを表示モデルへ変換する。"""
    documents = tuple(
        normalise_document(document)
        for document in _as_sequence(
            payload_value(
                payload,
                "documents",
                "document_rows",
                "rows",
                default=[],
            )
        )
    )
    counts = payload_value(payload, "counts", default={})
    public_count = payload_value(
        payload,
        "public_count",
        "public_documents",
        default=payload_value(counts, "public", "public_count", default=None),
    )
    expired_count = payload_value(
        payload,
        "expired_count",
        "expired_documents",
        default=payload_value(counts, "expired", "expired_count", default=None),
    )
    target_count = payload_value(
        payload,
        "target_count",
        "target_documents",
        default=payload_value(counts, "target", "target_count", default=None),
    )
    classification = _normalise_code(
        payload_value(
            payload,
            "classification",
            "project_status",
            "result_status",
            default="",
        )
    )
    if not classification:
        if not documents:
            classification = "NO_DOCUMENTS"
        elif all(document.status == "EXPIRED" for document in documents):
            classification = "EXPIRED_ONLY"
        elif any(document.is_unknown for document in documents):
            classification = "UNKNOWN"
        else:
            classification = "AVAILABLE"
    project_id = str(
        payload_value(
            payload,
            "project_id",
            "anken_kanri_no",
            "anken_id",
            "id",
            default=index,
        )
    )
    name = str(
        payload_value(
            payload,
            "project_name",
            "koji_name",
            "name",
            "title",
            default=f"案件 {index + 1}",
        )
        or f"案件 {index + 1}"
    ).strip()
    agency_status, agency_reason_code, agency_reason, agency_labels = (
        _agency_resolution(payload)
    )
    office_name = str(
        payload_value(payload, "office_name", "department_name", default="")
        or ""
    ).strip()
    planned_agency_parts = tuple(
        str(part or "").strip()
        for part in _as_sequence(
            payload_value(payload, "planned_agency_folder", default=())
        )
        if str(part or "").strip()
    )
    return ProjectView(
        project_id=project_id,
        name=name,
        documents=documents,
        public_count=(
            int(public_count)
            if public_count is not None
            else sum(document.status == "PUBLIC" for document in documents)
        ),
        expired_count=(
            int(expired_count)
            if expired_count is not None
            else sum(document.status == "EXPIRED" for document in documents)
        ),
        target_count=(
            int(target_count)
            if target_count is not None
            else sum(document.is_target for document in documents)
        ),
        classification=classification,
        agency_path=" > ".join(agency_labels) or "（階層なし）",
        agency_status=agency_status,
        agency_status_label=_AGENCY_STATUS_LABELS[agency_status],
        agency_reason_code=agency_reason_code,
        agency_reason=agency_reason,
        office_name=office_name,
        agency_id=str(
            payload_value(payload, "agency_id", "hachusha_id", default="")
            or ""
        ).strip(),
        planned_folder=_planned_project_folder(
            name,
            agency_labels,
            agency_status,
            office_name,
            planned_agency_parts,
        ),
    )


def normalise_projects(payload: Any) -> tuple[ProjectView, ...]:
    """工事一覧payloadを不変な表示モデルへ変換する。"""
    return tuple(
        normalise_project(project, index)
        for index, project in enumerate(_as_sequence(payload))
    )


def filter_projects(
    projects: Iterable[ProjectView],
    selected_filter: str = FILTER_ALL,
    query: str = "",
) -> tuple[ProjectView, ...]:
    """状態フィルターと案件・文書名検索を適用する。"""
    needle = query.strip().casefold()
    filtered = []
    for project in projects:
        if selected_filter == FILTER_TARGET and project.target_count <= 0:
            continue
        if selected_filter == FILTER_EXPIRED and not project.is_expired_only:
            continue
        if selected_filter == FILTER_EMPTY and project.documents:
            continue
        if selected_filter == FILTER_UNKNOWN and not project.is_unknown:
            continue
        if (
            selected_filter == FILTER_AGENCY_UNRESOLVED
            and not project.is_agency_unresolved
        ):
            continue
        if needle:
            haystacks = [
                project.name,
                project.agency_path,
                project.agency_reason,
                project.agency_reason_code,
                project.planned_folder,
            ]
            haystacks.extend(document.name for document in project.documents)
            if not any(needle in text.casefold() for text in haystacks):
                continue
        filtered.append(project)
    return tuple(filtered)


def _summary_int(payload: Any, *names: str, fallback: int = 0) -> int:
    """集計payloadから安全に整数を得る。"""
    value = payload_value(payload, *names, default=fallback)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return fallback


def format_search_summary(
    summary: Any,
    projects: Iterable[ProjectView] = (),
    *,
    complete: bool | None = None,
) -> str:
    """固定表示用の検索・取得予定集計を生成する。"""
    project_list = tuple(projects)
    projects_matched = _summary_int(
        summary,
        "projects_matched",
        "matched_projects",
        "total_projects",
        "projects_total",
        fallback=len(project_list),
    )
    public_documents = _summary_int(
        summary,
        "public_documents",
        "public_document_count",
        "public_count",
        fallback=sum(project.public_count for project in project_list),
    )
    expired_only = _summary_int(
        summary,
        "expired_only_projects",
        "expired_only_count",
        fallback=sum(project.is_expired_only for project in project_list),
    )
    target_documents = _summary_int(
        summary,
        "target_documents",
        "target_document_count",
        "target_count",
        fallback=sum(project.target_count for project in project_list),
    )
    download_count = _summary_int(
        summary,
        "download_count",
        "new_or_update_count",
        "downloads_planned",
    )
    reuse_count = _summary_int(
        summary,
        "reuse_count",
        "reused_count",
        "verified_reuse_count",
    )
    legacy_reuse_count = _summary_int(
        summary,
        "legacy_reuse_count",
        "legacy_reused_count",
    )
    if complete is None:
        complete = bool(
            payload_value(
                summary,
                "complete",
                "is_complete",
                "final",
                default=False,
            )
        )
    prefix = "検索解析完了" if complete else "検索解析中"
    scope_excluded = bool(
        payload_value(
            summary,
            "expired_scope_excluded",
            "expired_not_in_scope",
            default=False,
        )
    )
    expired_text = "集計対象外" if scope_excluded else f"{expired_only}件"
    first_line = (
        f"{prefix}：案件{projects_matched}件 / 公開中データ"
        f"{public_documents}件 / 公開終了のみ{expired_text}"
    )
    second_line = (
        f"今回の対象：{target_documents}件（新規・更新{download_count}件 / "
        f"保存済み確認{reuse_count}件"
    )
    if legacy_reuse_count:
        second_line += f"〈旧命名{legacy_reuse_count}件〉"
    resolved_value = payload_value(
        summary,
        "agency_resolved_projects",
        default=None,
    )
    unresolved_value = payload_value(
        summary,
        "agency_unresolved_projects",
        default=None,
    )
    resolved_projects = (
        _summary_int(
            summary,
            "agency_resolved_projects",
        )
        if resolved_value is not None
        else sum(not project.is_agency_unresolved for project in project_list)
    )
    unresolved_projects = (
        _summary_int(
            summary,
            "agency_unresolved_projects",
        )
        if unresolved_value is not None
        else sum(project.is_agency_unresolved for project in project_list)
    )
    agency_line = (
        f"保存先分類：確定{resolved_projects}件 / "
        f"分類未解決{unresolved_projects}件"
    )
    raw_issue_counts = payload_value(summary, "agency_issue_counts", default={})
    if isinstance(raw_issue_counts, Mapping) and raw_issue_counts:
        issue_labels = []
        for raw_code, raw_count in sorted(raw_issue_counts.items()):
            try:
                issue_count = int(raw_count or 0)
            except (TypeError, ValueError):
                continue
            if issue_count <= 0:
                continue
            code = _normalise_code(raw_code)
            label = _AGENCY_REASON_LABELS.get(code, code)
            issue_labels.append(f"{label} {issue_count}件")
        if issue_labels:
            agency_line += "（" + "、".join(issue_labels) + "）"
    return f"{first_line}\n{second_line}）\n{agency_line}"


class ProjectDocumentsDialog:
    """工事と公開文書を階層表示する、確認専用の別画面。"""

    _INSERT_CHUNK_SIZE = 50

    def __init__(
        self,
        parent: tk.Misc,
        projects: Iterable[ProjectView] = (),
        summary_text: str = "",
        on_close: Optional[Callable[[], None]] = None,
    ):
        self.parent = parent
        self.projects = tuple(projects)
        self._projects_by_id = {
            project.project_id: project for project in self.projects
        }
        self._on_close = on_close
        self._closed = False
        self._render_generation = 0
        self._render_after_id: str | None = None

        self.window = tk.Toplevel(parent)
        self.window.title("案件・文書内訳")
        fit_to_screen(
            self.window, 1380, 680, minimum_width=600, minimum_height=400
        )
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)

        controls = ttk.Frame(self.window, padding=(10, 10, 10, 5))
        controls.grid(row=0, column=0, sticky=(tk.W, tk.E))
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="表示:").grid(row=0, column=0, padx=(0, 5))
        self.filter_var = tk.StringVar(value=FILTER_ALL)
        filter_combo = ttk.Combobox(
            controls,
            textvariable=self.filter_var,
            values=FILTER_OPTIONS,
            state="readonly",
            width=16,
        )
        filter_combo.grid(row=0, column=1, padx=(0, 15))
        filter_combo.bind("<<ComboboxSelected>>", self._schedule_render)

        ttk.Label(controls, text="案件・文書・分類情報:").grid(
            row=0, column=2, padx=(0, 5)
        )
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(controls, textvariable=self.search_var)
        search_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(0, 10))
        self.search_var.trace_add("write", self._schedule_render)

        self.count_var = tk.StringVar()
        ttk.Label(controls, textvariable=self.count_var).grid(row=0, column=4)

        self.summary_var = tk.StringVar(value=summary_text)
        ttk.Label(
            self.window,
            textvariable=self.summary_var,
            justify=tk.LEFT,
            padding=(10, 0, 10, 5),
        ).grid(row=1, column=0, sticky=(tk.W, tk.E))

        tree_frame = ttk.Frame(self.window, padding=(10, 0, 10, 10))
        tree_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = (
            "agency_path",
            "agency_status",
            "planned_folder",
            "agency_reason",
            "status",
            "updated",
            "end",
            "decision",
        )
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="案件・文書")
        self.tree.heading("agency_path", text="発注機関階層")
        self.tree.heading("agency_status", text="分類状態")
        self.tree.heading("planned_folder", text="保存予定フォルダー")
        self.tree.heading("agency_reason", text="分類理由")
        self.tree.heading("status", text="公開状態")
        self.tree.heading("updated", text="最終更新日")
        self.tree.heading("end", text="掲載終了日")
        self.tree.heading("decision", text="今回の判定")
        self.tree.column("#0", width=320, minwidth=180, stretch=True)
        self.tree.column("agency_path", width=310, minwidth=160, stretch=True)
        self.tree.column("agency_status", width=115, minwidth=100, stretch=False)
        self.tree.column("planned_folder", width=430, minwidth=220, stretch=True)
        self.tree.column("agency_reason", width=320, minwidth=180, stretch=True)
        self.tree.column("status", width=170, minwidth=100, stretch=False)
        self.tree.column("updated", width=145, minwidth=120, stretch=False)
        self.tree.column("end", width=145, minwidth=120, stretch=False)
        self.tree.column("decision", width=200, minwidth=130, stretch=True)

        vertical = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.tree.yview
        )
        horizontal = ttk.Scrollbar(
            tree_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        vertical.grid(row=0, column=1, sticky=(tk.N, tk.S))
        horizontal.grid(row=1, column=0, sticky=(tk.W, tk.E))

        self._schedule_render()

    def is_alive(self) -> bool:
        """Toplevelが破棄されていないかを返す。"""
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def show(self) -> None:
        """画面を非モーダルのまま前面へ戻す。"""
        self.window.deiconify()
        self.window.lift()

    def update_data(
        self,
        projects: Iterable[ProjectView],
        summary_text: str,
    ) -> None:
        """進行中の検索結果を画面へ反映する。"""
        self.projects = tuple(projects)
        self._projects_by_id = {
            project.project_id: project for project in self.projects
        }
        self.summary_var.set(summary_text)
        self._schedule_render()

    def apply_deltas(
        self,
        projects: Iterable[ProjectView],
        summary_text: str,
    ) -> None:
        """進捗で変更された案件だけを正本へ反映する。"""
        for project in projects:
            self._projects_by_id[project.project_id] = project
        self.projects = tuple(self._projects_by_id.values())
        self.summary_var.set(summary_text)
        self._schedule_render()

    def close(self) -> None:
        """予約描画と案件参照を解放してToplevelを破棄する。"""
        if self._closed:
            return
        self._closed = True
        self._render_generation += 1
        if self._render_after_id is not None:
            try:
                self.window.after_cancel(self._render_after_id)
            except tk.TclError:
                pass
            self._render_after_id = None
        self.projects = ()
        self._projects_by_id.clear()
        try:
            self.tree.delete(*self.tree.get_children())
        except tk.TclError:
            pass
        try:
            self.window.destroy()
        finally:
            callback = self._on_close
            self._on_close = None
            if callback is not None:
                callback()

    def _schedule_render(self, *_args: Any) -> None:
        """既存の分割描画を無効化し、新しい描画を予約する。"""
        self._render_generation += 1
        generation = self._render_generation
        if self._render_after_id is not None:
            try:
                self.window.after_cancel(self._render_after_id)
            except tk.TclError:
                pass
            self._render_after_id = None
        self._render_after_id = self.window.after_idle(
            lambda: self._start_render(generation)
        )

    def _start_render(self, generation: int) -> None:
        """フィルター後の工事を描画キューへ渡す。"""
        if generation != self._render_generation or not self.is_alive():
            return
        self._render_after_id = None
        self.tree.delete(*self.tree.get_children())
        filtered = filter_projects(
            self.projects,
            self.filter_var.get(),
            self.search_var.get(),
        )
        self.count_var.set(f"表示 {len(filtered)} / {len(self.projects)} 案件")
        self._insert_chunk(filtered, 0, generation)

    def _insert_chunk(
        self,
        projects: tuple[ProjectView, ...],
        start: int,
        generation: int,
    ) -> None:
        """大量結果でもGUIを占有しないよう工事を分割挿入する。"""
        if generation != self._render_generation or not self.is_alive():
            return
        end = min(start + self._INSERT_CHUNK_SIZE, len(projects))
        for project in projects[start:end]:
            parent_id = self.tree.insert(
                "",
                tk.END,
                text=project.name,
                values=(
                    project.agency_path,
                    project.agency_status_label,
                    project.planned_folder,
                    (
                        f"{project.agency_reason} "
                        f"[{project.agency_reason_code}]"
                        if project.agency_reason_code
                        else project.agency_reason or "－"
                    ),
                    f"公開中{project.public_count}・公開終了"
                    f"{project.expired_count}",
                    "",
                    "",
                    f"今回対象{project.target_count}",
                ),
                open=False,
            )
            for document in project.documents:
                self.tree.insert(
                    parent_id,
                    tk.END,
                    text=document.name,
                    values=(
                        "",
                        "",
                        str(
                            PureWindowsPath(
                                project.planned_folder,
                                _document_section_folder(document.section),
                            )
                        ),
                        "",
                        _STATUS_LABELS[document.status],
                        document.updated_at,
                        document.listing_end_at,
                        document.decision,
                    ),
                )
        if end < len(projects):
            self._render_after_id = self.window.after_idle(
                lambda: self._insert_chunk(projects, end, generation)
            )
        else:
            self._render_after_id = None
