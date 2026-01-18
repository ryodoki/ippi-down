# -*- coding: utf-8 -*-

"""Metadata Extractor（FileInfoへメタデータ正規化）"""

from typing import Optional, Dict, Any
from ...models.file_info import FileInfo
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
            if project_entry.koji_name:
                metadata["koji_name"] = project_entry.koji_name
        
        # FileInfoを作成
        file_info = FileInfo(
            url=candidate.url,
            filename=candidate.filename,
            file_type=candidate.file_type,
            metadata=metadata,
            page_url=page_url or candidate.url
        )
        
        return file_info
