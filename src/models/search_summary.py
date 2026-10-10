# -*- coding: utf-8 -*-

"""検索結果と公開文書の集計モデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Tuple


class ProjectClassification(str, Enum):
    """案件単位の公開文書状態。"""

    PUBLIC_AVAILABLE = "PUBLIC_AVAILABLE"
    EXPIRED_ONLY = "EXPIRED_ONLY"
    NO_DOCUMENTS = "NO_DOCUMENTS"
    UNKNOWN = "UNKNOWN"
    DETAIL_FAILED = "DETAIL_FAILED"


class DocumentDecision(str, Enum):
    """文書が今回の実行でどう扱われるか。"""

    DOWNLOAD_TARGET = "DOWNLOAD_TARGET"
    DOWNLOADED = "DOWNLOADED"
    REUSED = "REUSED"
    REUSED_LEGACY = "REUSED_LEGACY"
    EXCLUDED_EXPIRED = "EXCLUDED_EXPIRED"
    EXCLUDED_FILE_TYPE = "EXCLUDED_FILE_TYPE"
    EXCLUDED_FILTER = "EXCLUDED_FILTER"
    PUBLIC_LINK_MISSING = "PUBLIC_LINK_MISSING"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass
class DocumentSummary:
    """GUIとログへ渡す公開文書1行の情報。"""

    document_name: str
    public_status: str
    document_updated_at: str = ""
    listing_end_at: str = ""
    decision: str = DocumentDecision.NOT_EVALUATED.value
    decision_reason: str = ""
    url: str = ""
    document_id: str = ""
    section: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_name": self.document_name,
            "public_status": self.public_status,
            "document_updated_at": self.document_updated_at,
            "listing_end_at": self.listing_end_at,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "url": self.url,
            "document_id": self.document_id,
            "section": self.section,
        }


@dataclass
class ProjectDocumentSummary:
    """案件と、その公開文書一覧。"""

    project_id: str
    project_name: str
    documents: List[DocumentSummary] = field(default_factory=list)
    classification: str = ProjectClassification.UNKNOWN.value
    detail_error: str = ""
    agency_path: Dict[str, Any] = field(default_factory=dict)
    agency_resolution_status: str = ""
    agency_resolution_method: str = ""
    agency_resolution_reason_code: str = ""
    agency_resolution_reason: str = ""
    office_name: str = ""
    agency_id: str = ""
    planned_agency_folder: List[str] = field(default_factory=list)

    @property
    def counts(self) -> Dict[str, int]:
        public = sum(
            item.public_status == "PUBLIC" for item in self.documents
        )
        expired = sum(
            item.public_status == "EXPIRED" for item in self.documents
        )
        target = sum(
            item.decision
            in {
                DocumentDecision.DOWNLOAD_TARGET.value,
                DocumentDecision.DOWNLOADED.value,
                DocumentDecision.REUSED.value,
                DocumentDecision.REUSED_LEGACY.value,
                DocumentDecision.FAILED.value,
                DocumentDecision.CANCELLED.value,
            }
            for item in self.documents
        )
        return {
            "public": public,
            "expired": expired,
            "target": target,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "documents": [item.to_dict() for item in self.documents],
            "counts": self.counts,
            "classification": self.classification,
            "detail_error": self.detail_error,
            "agency_path": dict(self.agency_path),
            "agency_resolution_status": self.agency_resolution_status,
            "agency_resolution_method": self.agency_resolution_method,
            "agency_resolution_reason_code": (
                self.agency_resolution_reason_code
            ),
            "agency_resolution_reason": self.agency_resolution_reason,
            "office_name": self.office_name,
            "agency_id": self.agency_id,
            "planned_agency_folder": list(self.planned_agency_folder),
        }


@dataclass
class SearchExtractionSummary:
    """検索・詳細解析・ダウンロード判定を通した集計。"""

    projects: List[ProjectDocumentSummary] = field(default_factory=list)
    projects_matched: int = 0
    projects_scanned: int = 0
    public_documents: int = 0
    expired_documents: int = 0
    expired_only_projects: int = 0
    no_document_projects: int = 0
    unknown_status_projects: int = 0
    detail_failed_projects: int = 0
    candidate_documents: int = 0
    target_documents: int = 0
    download_count: int = 0
    reuse_count: int = 0
    legacy_reuse_count: int = 0
    complete: bool = False
    expired_scope_excluded: bool = False
    agency_resolution_counts: Dict[str, int] = field(default_factory=dict)
    agency_issue_counts: Dict[str, int] = field(default_factory=dict)
    _project_index: Dict[str, int] = field(
        init=False,
        repr=False,
        compare=False,
        default_factory=dict,
    )
    _project_contributions: Dict[
        str, Tuple[int, int, int, int, int, int, int]
    ] = field(
        init=False,
        repr=False,
        compare=False,
        default_factory=dict,
    )
    _project_agency_contributions: Dict[str, Tuple[str, str]] = field(
        init=False,
        repr=False,
        compare=False,
        default_factory=dict,
    )

    def __post_init__(self) -> None:
        if self.projects:
            self.refresh_counts()

    def merge(self, other: "SearchExtractionSummary") -> None:
        """複数検索URLの集計を案件IDで重複排除して統合する。"""
        # ``projects_matched`` may be larger than ``projects`` while a search
        # is cancelled part-way through a page.  Keep that unscanned remainder
        # without treating already materialised (and therefore deduplicable)
        # projects as new matches on every source URL.
        self_unscanned = max(
            0, self.projects_matched - len(self.projects)
        )
        other_unscanned = max(
            0, other.projects_matched - len(other.projects)
        )
        self._ensure_project_index()
        for project in other.projects:
            self.upsert_project(project)
        self.projects_matched = (
            len(self.projects) + self_unscanned + other_unscanned
        )
        self.candidate_documents += other.candidate_documents
        self.download_count += other.download_count
        self.reuse_count += other.reuse_count
        self.legacy_reuse_count += other.legacy_reuse_count
        self.complete = self.complete and other.complete
        self.expired_scope_excluded = (
            self.expired_scope_excluded or other.expired_scope_excluded
        )

    @staticmethod
    def _prefer_project(
        candidate: ProjectDocumentSummary,
        current: ProjectDocumentSummary,
    ) -> bool:
        """重複案件では失敗結果より正常かつ情報量の多い解析を採用する。"""
        candidate_failed = (
            candidate.classification
            == ProjectClassification.DETAIL_FAILED.value
        )
        current_failed = (
            current.classification
            == ProjectClassification.DETAIL_FAILED.value
        )
        if candidate_failed != current_failed:
            return not candidate_failed
        if len(candidate.documents) != len(current.documents):
            return len(candidate.documents) > len(current.documents)
        # 同品質なら、後から取得した解析結果を採用する。
        return True

    def refresh_counts(self) -> None:
        """案件一覧から状態別件数と増分索引を一度の走査で再構築する。"""
        self._project_index.clear()
        self._project_contributions.clear()
        self._project_agency_contributions.clear()
        self.public_documents = 0
        self.expired_documents = 0
        self.expired_only_projects = 0
        self.no_document_projects = 0
        self.unknown_status_projects = 0
        self.detail_failed_projects = 0
        self.target_documents = 0
        self.agency_resolution_counts.clear()
        self.agency_issue_counts.clear()
        for index, project in enumerate(self.projects):
            self._project_index[project.project_id] = index
            contribution = self._project_contribution(project)
            self._project_contributions[project.project_id] = contribution
            self._apply_project_contribution(contribution, 1)
            agency_contribution = self._project_agency_contribution(project)
            self._project_agency_contributions[project.project_id] = (
                agency_contribution
            )
            self._apply_project_agency_contribution(
                agency_contribution, 1
            )
        self.projects_scanned = len(self.projects)
        self.projects_matched = max(
            self.projects_matched, self.projects_scanned
        )

    @staticmethod
    def _project_contribution(
        project: ProjectDocumentSummary,
    ) -> Tuple[int, int, int, int, int, int, int]:
        """1案件が各集計値へ加える件数を一度だけ計算する。"""
        public = 0
        expired = 0
        target = 0
        target_decisions = {
            DocumentDecision.DOWNLOAD_TARGET.value,
            DocumentDecision.DOWNLOADED.value,
            DocumentDecision.REUSED.value,
            DocumentDecision.REUSED_LEGACY.value,
            DocumentDecision.FAILED.value,
            DocumentDecision.CANCELLED.value,
        }
        for document in project.documents:
            public += document.public_status == "PUBLIC"
            expired += document.public_status == "EXPIRED"
            target += document.decision in target_decisions
        classification = project.classification
        return (
            public,
            expired,
            int(classification == ProjectClassification.EXPIRED_ONLY.value),
            int(classification == ProjectClassification.NO_DOCUMENTS.value),
            int(classification == ProjectClassification.UNKNOWN.value),
            int(classification == ProjectClassification.DETAIL_FAILED.value),
            target,
        )

    def _apply_project_contribution(
        self,
        contribution: Tuple[int, int, int, int, int, int, int],
        multiplier: int,
    ) -> None:
        attributes = (
            "public_documents",
            "expired_documents",
            "expired_only_projects",
            "no_document_projects",
            "unknown_status_projects",
            "detail_failed_projects",
            "target_documents",
        )
        for attribute, value in zip(attributes, contribution):
            setattr(
                self,
                attribute,
                getattr(self, attribute) + multiplier * value,
            )

    @staticmethod
    def _project_agency_contribution(
        project: ProjectDocumentSummary,
    ) -> Tuple[str, str]:
        status = str(project.agency_resolution_status or "").strip().lower()
        reason_code = str(
            project.agency_resolution_reason_code or ""
        ).strip()
        if status != "unresolved":
            reason_code = ""
        return status, reason_code

    def _apply_project_agency_contribution(
        self,
        contribution: Tuple[str, str],
        multiplier: int,
    ) -> None:
        status, reason_code = contribution
        if status:
            new_count = self.agency_resolution_counts.get(status, 0) + multiplier
            if new_count > 0:
                self.agency_resolution_counts[status] = new_count
            else:
                self.agency_resolution_counts.pop(status, None)
        if reason_code:
            new_count = self.agency_issue_counts.get(reason_code, 0) + multiplier
            if new_count > 0:
                self.agency_issue_counts[reason_code] = new_count
            else:
                self.agency_issue_counts.pop(reason_code, None)

    @property
    def agency_resolved_projects(self) -> int:
        return sum(
            self.agency_resolution_counts.get(status, 0)
            for status in ("selected", "detail_matched")
        )

    @property
    def agency_unresolved_projects(self) -> int:
        return self.agency_resolution_counts.get("unresolved", 0)

    def upsert_project(
        self,
        project: ProjectDocumentSummary,
    ) -> ProjectDocumentSummary:
        """案件IDで追加・置換し、状態別件数を差分更新する。"""
        self._ensure_project_index()
        index = self._project_index.get(project.project_id)
        if index is None:
            self.projects.append(project)
            index = len(self.projects) - 1
            self._project_index[project.project_id] = index
            contribution = self._project_contribution(project)
            self._project_contributions[project.project_id] = contribution
            self._apply_project_contribution(contribution, 1)
            agency_contribution = self._project_agency_contribution(project)
            self._project_agency_contributions[project.project_id] = (
                agency_contribution
            )
            self._apply_project_agency_contribution(
                agency_contribution, 1
            )
            self.projects_scanned = len(self.projects)
            self.projects_matched = max(
                self.projects_matched,
                self.projects_scanned,
            )
            return project

        current = self.projects[index]
        if not self._prefer_project(project, current):
            return current
        current_contribution = self._project_contributions.get(
            project.project_id,
            self._project_contribution(current),
        )
        self._apply_project_contribution(current_contribution, -1)
        current_agency_contribution = self._project_agency_contributions.get(
            project.project_id,
            self._project_agency_contribution(current),
        )
        self._apply_project_agency_contribution(
            current_agency_contribution, -1
        )
        self.projects[index] = project
        contribution = self._project_contribution(project)
        self._project_contributions[project.project_id] = contribution
        self._apply_project_contribution(contribution, 1)
        agency_contribution = self._project_agency_contribution(project)
        self._project_agency_contributions[project.project_id] = (
            agency_contribution
        )
        self._apply_project_agency_contribution(agency_contribution, 1)
        return project

    def _ensure_project_index(self) -> None:
        """公開リストの直接更新と重複案件を索引へ安全に取り込む。"""
        if len(self._project_index) == len(self.projects):
            return
        by_id: Dict[str, ProjectDocumentSummary] = {}
        for project in self.projects:
            current = by_id.get(project.project_id)
            if current is None or self._prefer_project(project, current):
                by_id[project.project_id] = project
        self.projects = list(by_id.values())
        self.refresh_counts()

    def project_dicts(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self.projects]

    def to_dict(self, *, include_projects: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "projects_matched": self.projects_matched,
            "projects_scanned": self.projects_scanned,
            "public_documents": self.public_documents,
            "expired_documents": self.expired_documents,
            "expired_only_projects": self.expired_only_projects,
            "no_document_projects": self.no_document_projects,
            "unknown_status_projects": self.unknown_status_projects,
            "detail_failed_projects": self.detail_failed_projects,
            "candidate_documents": self.candidate_documents,
            "target_documents": self.target_documents,
            "download_count": self.download_count,
            "reuse_count": self.reuse_count,
            "legacy_reuse_count": self.legacy_reuse_count,
            "complete": self.complete,
            "expired_scope_excluded": self.expired_scope_excluded,
            "agency_resolution_counts": dict(self.agency_resolution_counts),
            "agency_issue_counts": dict(self.agency_issue_counts),
            "agency_resolved_projects": self.agency_resolved_projects,
            "agency_unresolved_projects": self.agency_unresolved_projects,
        }
        if include_projects:
            payload["projects"] = self.project_dicts()
        return payload


__all__ = [
    "DocumentDecision",
    "DocumentSummary",
    "ProjectClassification",
    "ProjectDocumentSummary",
    "SearchExtractionSummary",
]
