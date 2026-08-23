# -*- coding: utf-8 -*-

"""ファイル抽出結果"""

from dataclasses import dataclass, field
from typing import List

from ..models.file_info import FileInfo


@dataclass
class ExtractResult:
    """スクレイピングによるファイル抽出の結果"""

    files: List[FileInfo] = field(default_factory=list)
    search_failed_urls: List[str] = field(default_factory=list)
    fetch_failed_urls: List[str] = field(default_factory=list)
    total_koji_count: int = 0
    unavailable_document_count: int = 0

    @property
    def had_connection_failure(self) -> bool:
        return bool(self.search_failed_urls or self.fetch_failed_urls)
