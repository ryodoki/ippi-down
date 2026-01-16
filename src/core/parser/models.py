"""Parser用データモデル"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProjectEntry:
    """検索結果の案件エントリ"""
    detail_url: str
    koji_name: str
    metadata: dict


@dataclass
class FileCandidate:
    """ファイル候補（詳細ページから抽出）"""
    url: str
    filename: str
    file_type: str
    document_name: Optional[str] = None
    metadata: Optional[dict] = None
