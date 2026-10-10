# -*- coding: utf-8 -*-

"""Metadata Extractor（FileInfoへメタデータ正規化）"""

from typing import Optional
from ...models.file_info import FileInfo
from ...models.agency import (
    AgencyPathResolution,
    AgencyResolutionReasonCode,
    AgencyResolutionStatus,
)
from ...utils.logger import Logger
from ..parser.models import FileCandidate, ProjectEntry


class MetadataExtractor:
    """メタデータ抽出・正規化クラス"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()

    def to_file_info(
        self,
        candidate: FileCandidate,
        project_entry: Optional[ProjectEntry] = None,
        page_url: Optional[str] = None
    ) -> FileInfo:
        """FileCandidateをFileInfoに変換"""
        # メタデータをマージ
        metadata = candidate.metadata.copy() if candidate.metadata else {}
        
        # FileCandidateの属性をメタデータに追加
        if candidate.document_name:
            metadata["document_name"] = candidate.document_name
        
        if project_entry:
            # プロジェクトエントリのメタデータを優先
            if project_entry.metadata:
                metadata.update(project_entry.metadata)
            project_name = (
                project_entry.project_name or project_entry.koji_name
            )
            if project_name:
                metadata["project_name"] = project_name
                # 既存テンプレート・履歴との互換別名。業務でも案件名を返す。
                metadata["koji_name"] = project_name
            metadata["search_target"] = project_entry.search_target
            resolution = project_entry.agency_resolution
            if resolution is None and project_entry.agency_path is not None:
                resolution = AgencyPathResolution(
                    path=project_entry.agency_path,
                    status=(
                        AgencyResolutionStatus.SELECTED
                        if project_entry.agency_path.is_complete
                        else AgencyResolutionStatus.UNRESOLVED
                    ),
                    method="search_selection",
                    reason=(
                        ""
                        if project_entry.agency_path.is_complete
                        else "細分類まで解決されていません"
                    ),
                    office_name=project_entry.office_name,
                    agency_id=project_entry.agency_id,
                    reason_code=(
                        AgencyResolutionReasonCode.SELECTED.value
                        if project_entry.agency_path.is_complete
                        else AgencyResolutionReasonCode.PATH_INCOMPLETE.value
                    ),
                )
            if resolution is not None:
                metadata.update(resolution.to_metadata())
            else:
                if project_entry.office_name:
                    metadata["office_name"] = project_entry.office_name
                if project_entry.agency_id:
                    metadata["agency_id"] = project_entry.agency_id
        
        # FileInfoを作成
        file_info = FileInfo(
            url=candidate.url,
            filename=candidate.filename,
            file_type=candidate.file_type,
            metadata=metadata,
            page_url=page_url or candidate.url,
            allow_html_to_pdf=candidate.allow_html_to_pdf,
        )
        
        return file_info
