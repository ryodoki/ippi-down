# -*- coding: utf-8 -*-

"""Parser用データモデル"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from ...models.agency import AgencyPath, AgencyPathResolution
from ...models.search_target import SearchTarget


@dataclass
class ProjectEntry:
    """検索結果の案件エントリ"""
    detail_url: str
    koji_name: str
    metadata: dict
    page_no: int = 0
    row_no: int = 0
    event_target: str = ""
    event_argument: str = ""
    source_url: str = ""
    agency_path: Optional[AgencyPath] = None
    agency_resolution: Optional[AgencyPathResolution] = None
    office_name: str = ""
    agency_id: str = ""
    project_name: str = ""
    search_target: str = SearchTarget.KOJI_KEIKA.value

    def __post_init__(self) -> None:
        self.search_target = SearchTarget.coerce(self.search_target).value
        self.project_name = str(self.project_name or self.koji_name or "").strip()
        # koji_nameは既存parser・命名規則向けの互換別名として維持する。
        self.koji_name = self.project_name
        if self.metadata is None:
            self.metadata = {}
        self.metadata.setdefault("project_name", self.project_name)
        self.metadata.setdefault("koji_name", self.project_name)
        self.metadata.setdefault("search_target", self.search_target)


class DocumentPublicationStatus(str, Enum):
    """i-ppiの公開文書行から判定した公開状態。"""

    PUBLIC = "PUBLIC"
    EXPIRED = "EXPIRED"
    SCHEDULED = "SCHEDULED"
    NON_PUBLIC = "NON_PUBLIC"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DocumentRowInfo:
    """詳細ページの「公開文書」表に表示される1行。

    日時は解析できた場合に ``ISO 8601 (Asia/Tokyo)`` で保持し、
    HPの表示値は ``*_text`` にそのまま残す。
    """

    document_name: str
    status: DocumentPublicationStatus
    status_text: str = ""
    document_updated_at: str = ""
    document_updated_at_text: str = ""
    listing_end_at: str = ""
    listing_end_at_text: str = ""
    section: str = ""
    document_id: str = ""
    href: Optional[str] = None
    table_id: str = ""

    @property
    def publication_status(self) -> DocumentPublicationStatus:
        """呼び出し側が意味を読み取りやすい互換エイリアス。"""

        return self.status

    @property
    def document_expires_at(self) -> str:
        """「掲載終了日」の互換エイリアス。"""

        return self.listing_end_at

    @property
    def is_downloadable(self) -> bool:
        """公開中でかつ取得先があるか。"""

        return self.status is DocumentPublicationStatus.PUBLIC and bool(
            self.href
        )


@dataclass
class FileCandidate:
    """ファイル候補（詳細ページから抽出）"""
    url: str
    filename: str
    file_type: str
    document_name: Optional[str] = None
    metadata: Optional[dict] = None
    allow_html_to_pdf: bool = False
    document_info: Optional[DocumentRowInfo] = None


@dataclass
class DetailExtractionResult:
    """詳細ページの全文書行とダウンロード候補。"""

    document_rows: List[DocumentRowInfo] = field(default_factory=list)
    candidates: List[FileCandidate] = field(default_factory=list)
    project_metadata: dict = field(default_factory=dict)
