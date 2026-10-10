# -*- coding: utf-8 -*-

"""Detail Page Parser（詳細ページ→公開文書一覧抽出）"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from ...utils.logger import Logger
from ...app.exceptions import ScrapingError
from .document_classifier import classify_document_candidate
from .models import (
    DetailExtractionResult,
    DocumentPublicationStatus,
    DocumentRowInfo,
    FileCandidate,
)


_JST = timezone(timedelta(hours=9))
_COLUMN_ALIASES = {
    "document_name": ("文書名称", "文書名", "文書"),
    "status": ("公開状況", "公開状態", "状態"),
    "document_updated_at": ("最終更新日", "更新日時", "更新日"),
    "listing_end_at": ("掲載終了日", "公開終了日", "終了日"),
}
_DEFAULT_COLUMNS = {
    "document_name": 0,
    "status": 1,
    "document_updated_at": 2,
    "listing_end_at": 3,
}
_TABLE_SECTIONS = {
    "dgrKokoku": "入札公告等",
    "dgrKeika": "入札経過・その他",
}


class DetailPageParser:
    """詳細ページパーサー（詳細ページ→ファイル一覧抽出）"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()

    def extract_file_candidates(
        self,
        soup: BeautifulSoup,
        base_url: str,
        file_types: List[str],
        koji_name: Optional[str] = None
    ) -> List[FileCandidate]:
        """公開中の文書から候補だけを返す互換API。"""

        return self.extract_detail_result(
            soup,
            base_url,
            file_types,
            koji_name,
        ).candidates

    def extract_detail_result(
        self,
        soup: BeautifulSoup,
        base_url: str,
        file_types: List[str],
        koji_name: Optional[str] = None,
    ) -> DetailExtractionResult:
        """公開文書の全行とダウンロード候補を抽出する。"""

        try:
            document_rows = self._extract_document_rows(soup, base_url)
            candidates = self._to_file_candidates(
                document_rows,
                file_types,
                koji_name or "",
            )

            self.logger.debug(
                "分割パーサー: 詳細ページから"
                f"文書{len(document_rows)}件、取得候補{len(candidates)}件を"
                "抽出しました"
            )
            return DetailExtractionResult(
                document_rows=document_rows,
                candidates=candidates,
                project_metadata=self.extract_project_metadata(soup),
            )

        except Exception as e:
            self.logger.error(f"詳細ページ解析エラー: {str(e)}")
            raise ScrapingError(f"詳細ページ解析エラー: {str(e)}")

    def extract_document_rows(
        self,
        soup: BeautifulSoup,
        base_url: str,
    ) -> List[DocumentRowInfo]:
        """取得対象外も含む公開文書表の全行を返す。"""

        try:
            return self._extract_document_rows(soup, base_url)
        except Exception as e:
            self.logger.error(f"詳細ページ解析エラー: {str(e)}")
            raise ScrapingError(f"詳細ページ解析エラー: {str(e)}")

    def extract_project_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        """案件詳細から発注機関、担当部・事務所、発注者IDを抽出する。"""

        metadata: Dict[str, str] = {}
        hachu_kikan = self._value_by_id_or_label(
            soup,
            ("lblHachukikan", "lblHachuKikan"),
            ("発注機関", "発注者", "発注元"),
        )
        office_name = self._value_by_id_or_label(
            soup,
            ("lblHachusha", "lblTantouBusho"),
            (
                "担当部・事務所",
                "担当部事務所",
                "担当部署",
                "担当事務所",
            ),
        )
        if hachu_kikan:
            metadata["hachu_kikan"] = hachu_kikan
        if office_name:
            metadata["office_name"] = office_name

        agency_id = self._extract_hachusha_id(soup)
        if agency_id:
            metadata["agency_id"] = agency_id
        return metadata

    @classmethod
    def _value_by_id_or_label(
        cls,
        soup: BeautifulSoup,
        element_ids: Tuple[str, ...],
        labels: Tuple[str, ...],
    ) -> str:
        for element_id in element_ids:
            element = soup.find(id=element_id)
            if element is not None:
                value = element.get_text(" ", strip=True)
                if value:
                    return value

        normalized_labels = {
            cls._normalize_header(label) for label in labels
        }
        for element in soup.find_all(["td", "th", "dt", "label"]):
            if cls._normalize_header(
                element.get_text(" ", strip=True)
            ) not in normalized_labels:
                continue
            sibling = element.find_next_sibling(["td", "dd"])
            if sibling is not None:
                value = sibling.get_text(" ", strip=True)
                if value:
                    return value
        return ""

    @staticmethod
    def _extract_hachusha_id(soup: BeautifulSoup) -> str:
        for field in soup.find_all(["input", "meta"]):
            field_name = str(
                field.get("name") or field.get("id") or ""
            )
            if field_name.casefold() == "hachushaid":
                value = str(
                    field.get("value") or field.get("content") or ""
                ).strip()
                if value:
                    return value

        script_text = "\n".join(
            script.get_text(" ", strip=False)
            for script in soup.find_all("script")
        )
        match = re.search(
            r"\bHachushaId\s*=\s*['\"]([^'\"]+)['\"]",
            script_text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()

        # 発注者IDがDownload URLへ直接埋め込まれる旧HTMLにも対応する。
        html_text = str(soup)
        match = re.search(
            r"UserEntry_Download\.aspx\?[^'\"\s>]*data2=([^&'\"\s>]+)",
            html_text,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip() if match else ""

    def _extract_document_rows(
        self,
        soup: BeautifulSoup,
        base_url: str,
    ) -> List[DocumentRowInfo]:
        document_rows: List[DocumentRowInfo] = []
        for table, section in self._find_document_tables(soup):
            table_id = str(table.get("id") or "")
            rows = table.find_all("tr")
            columns, header_row_index = self._find_columns(rows)

            for row_index, row in enumerate(rows):
                if row_index == header_row_index:
                    continue
                cells = row.find_all(["td", "th"], recursive=False)
                if not cells:
                    continue

                document_name = self._cell_text(
                    cells, columns["document_name"]
                )
                if not document_name or self._is_header_text(document_name):
                    continue

                status_index = columns["status"]
                status_text = self._cell_text(cells, status_index)
                status = self._classify_publication_status(status_text)
                status_cell = self._cell(cells, status_index)
                link = (
                    status_cell.find("a", href=True)
                    if status_cell is not None
                    else None
                )
                if link is None:
                    link = row.find("a", href=True)
                href = (
                    urljoin(base_url, link.get("href", "").strip())
                    if link is not None and link.get("href", "").strip()
                    else None
                )

                updated_text = self._cell_text(
                    cells, columns["document_updated_at"]
                )
                end_text = self._cell_text(
                    cells, columns["listing_end_at"]
                )
                document_rows.append(
                    DocumentRowInfo(
                        document_name=document_name,
                        status=status,
                        status_text=status_text,
                        document_updated_at=self._normalize_datetime(
                            updated_text
                        ),
                        document_updated_at_text=updated_text,
                        listing_end_at=self._normalize_datetime(end_text),
                        listing_end_at_text=end_text,
                        section=section,
                        document_id=self._extract_document_id(href),
                        href=href,
                        table_id=table_id,
                    )
                )
        return document_rows

    def _to_file_candidates(
        self,
        document_rows: List[DocumentRowInfo],
        file_types: List[str],
        koji_name: str,
    ) -> List[FileCandidate]:
        candidates: List[FileCandidate] = []
        for document in document_rows:
            if not document.is_downloadable or not document.href:
                continue

            classification = classify_document_candidate(
                document.href,
                document.document_name,
                file_types,
            )
            if not classification.file_type:
                continue

            updated_for_filename = self._datetime_for_filename(
                document.document_updated_at
            )
            metadata = {
                "koji_name": koji_name,
                # titleは従来互換。文書固有値は別キーで保護する。
                "title": document.document_name,
                "document_title": document.document_name,
                "document_name": document.document_name,
                "document_updated_at": document.document_updated_at,
                "document_updated_at_text": (
                    document.document_updated_at_text
                ),
                "document_updated_at_filename": updated_for_filename,
                "listing_end_at": document.listing_end_at,
                "listing_end_at_text": document.listing_end_at_text,
                "document_expires_at": document.document_expires_at,
                "document_expires_at_text": document.listing_end_at_text,
                "document_section": document.section,
                "document_id": document.document_id,
                "publication_status": document.status.value,
                "publication_status_text": document.status_text,
            }
            candidates.append(
                FileCandidate(
                    url=document.href,
                    filename=self._generate_filename(
                        document.href,
                        document.document_name,
                        classification.file_type,
                    ),
                    file_type=classification.file_type,
                    document_name=document.document_name,
                    metadata=metadata,
                    allow_html_to_pdf=classification.allow_html_to_pdf,
                    document_info=document,
                )
            )
        return candidates

    def _find_document_tables(self, soup) -> List[Tuple[object, str]]:
        identified = [
            (table, _TABLE_SECTIONS[table_id])
            for table_id in _TABLE_SECTIONS
            if (table := soup.find("table", id=table_id)) is not None
        ]
        if identified:
            return identified

        found: List[Tuple[object, str]] = []
        for table in soup.find_all("table"):
            section = self._infer_section(table)
            if section:
                found.append((table, section))
        return found

    def _infer_section(self, table) -> str:
        for elem in table.find_all_previous(
            ["div", "span", "td", "th", "h1", "h2", "h3"],
            limit=12,
        ):
            text = elem.get_text(" ", strip=True)
            if "入札経過・その他" in text:
                return "入札経過・その他"
            if "入札公告等" in text:
                return "入札公告等"
        return ""

    def _find_columns(self, rows) -> Tuple[Dict[str, int], int]:
        for row_index, row in enumerate(rows):
            cells = row.find_all(["td", "th"], recursive=False)
            texts = [cell.get_text(" ", strip=True) for cell in cells]
            discovered: Dict[str, int] = {}
            for index, text in enumerate(texts):
                normalized = self._normalize_header(text)
                for key, aliases in _COLUMN_ALIASES.items():
                    if normalized in aliases:
                        discovered[key] = index
                        break
            if "document_name" in discovered and "status" in discovered:
                return {
                    **_DEFAULT_COLUMNS,
                    **discovered,
                }, row_index
        return dict(_DEFAULT_COLUMNS), -1

    @staticmethod
    def _cell(cells, index: int):
        return cells[index] if 0 <= index < len(cells) else None

    @classmethod
    def _cell_text(cls, cells, index: int) -> str:
        cell = cls._cell(cells, index)
        return cell.get_text(" ", strip=True) if cell is not None else ""

    @staticmethod
    def _normalize_header(text: str) -> str:
        return re.sub(r"[\s　：:]", "", text)

    @classmethod
    def _is_header_text(cls, text: str) -> bool:
        normalized = cls._normalize_header(text)
        return any(
            normalized in aliases for aliases in _COLUMN_ALIASES.values()
        )

    @staticmethod
    def _classify_publication_status(
        status_text: str,
    ) -> DocumentPublicationStatus:
        normalized = re.sub(r"[\s　]", "", status_text)
        if any(
            marker in normalized
            for marker in ("非公開", "公開停止", "公開不可")
        ):
            return DocumentPublicationStatus.NON_PUBLIC
        if any(
            marker in normalized
            for marker in ("公開予定", "公開前", "掲載予定")
        ):
            return DocumentPublicationStatus.SCHEDULED
        if any(
            marker in normalized
            for marker in ("公開終了", "掲載終了", "終了済", "公開期間終了")
        ):
            return DocumentPublicationStatus.EXPIRED
        if "公開中" in normalized:
            return DocumentPublicationStatus.PUBLIC
        return DocumentPublicationStatus.UNKNOWN

    @staticmethod
    def _normalize_datetime(value: str) -> str:
        text = value.strip()
        if not text:
            return ""

        match = re.fullmatch(
            r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
            r"(?:\s*(\d{1,2})\s*時\s*(\d{1,2})\s*分"
            r"(?:\s*(\d{1,2})\s*秒)?)?",
            text,
        )
        if not match:
            match = re.fullmatch(
                r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
                r"(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?",
                text,
            )
        if not match:
            return ""

        parts = [int(part) if part is not None else 0 for part in match.groups()]
        try:
            parsed = datetime(*parts, tzinfo=_JST)
        except ValueError:
            return ""
        return parsed.isoformat(timespec="seconds")

    @staticmethod
    def _datetime_for_filename(value: str) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(value).strftime("%Y%m%d_%H%M")
        except ValueError:
            return ""

    @staticmethod
    def _extract_document_id(url: Optional[str]) -> str:
        if not url:
            return ""
        query = parse_qs(urlparse(url).query)
        for key, values in query.items():
            if key.casefold() == "bunshokanriid" and values:
                return values[0]
        return ""

    def _infer_file_type(self, url: str, file_types: List[str]) -> Optional[str]:
        """URLと既知の配信Servletから対象ファイル種別を推測する。"""
        return (
            classify_document_candidate(url, "", file_types).file_type
            or None
        )

    def _extract_document_name(self, link) -> Optional[str]:
        """文書名称を抽出"""
        # 同じ行の他のセルから文書名称を探す
        row = link.find_parent("tr")
        if row:
            cells = row.find_all("td")
            for cell in cells:
                text = cell.get_text(strip=True)
                if text and text != "公開中":
                    return text
        return None

    def _generate_filename(
        self,
        url: str,
        document_name: Optional[str],
        file_type: str,
    ) -> str:
        """ファイル名を生成"""
        if document_name:
            ext = Path(url.split("?", 1)[0]).suffix or file_type
            return f"{document_name}{ext}"
        else:
            return Path(url.split("?", 1)[0]).name or f"file{file_type}"
