# -*- coding: utf-8 -*-

"""Search Result Parser（検索結果→案件一覧抽出）"""

import re
import unicodedata
from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from ...utils.logger import Logger
from ...app.exceptions import ScrapingError
from ...models.agency import AgencyPathResolution
from ...models.search_target import SearchTarget
from ..search_profiles import get_search_profile
from .models import ProjectEntry


class SearchResultParser:
    """検索結果パーサー（検索結果→案件一覧抽出）"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()

    def extract_project_entries(
        self,
        soup: BeautifulSoup,
        base_url: str,
        page_no: int = 0,
        agency_resolution: Optional[AgencyPathResolution] = None,
        search_target: object = SearchTarget.KOJI_KEIKA,
    ) -> List[ProjectEntry]:
        """検索結果表を見出し名に基づいて案件へ正規化する。"""
        entries = []
        profile = get_search_profile(search_target)
        
        try:
            # 検索結果テーブルを探す
            result_table = soup.find("table", id="dgrSearchList")
            if not result_table:
                self.logger.warning("検索結果テーブルが見つかりませんでした")
                return entries

            table_rows = result_table.find_all("tr")
            if not table_rows:
                return entries

            headers = [
                self._normalize(cell.get_text(" ", strip=True))
                for cell in table_rows[0].find_all(["th", "td"])
            ]
            header_indexes = {
                "hachu_kikan": self._find_header(
                    headers, "発注機関", "担当部事務所"
                ),
                "project_name": self._find_header(
                    headers, *profile.result_project_headers
                ),
                "contract_type": self._find_header(headers, "入札契約方式"),
                "koji_shubetsu": self._find_header(
                    headers, "工事区分", "工事種別"
                ),
                "koji_gyoushu": self._find_header(
                    headers, "工事の業種", "工事業種", "業種"
                ),
                "gyomu_kubun": self._find_header(headers, "業務区分"),
                "koukoku_date": self._find_header(headers, "公告日"),
                "kaisatsu_date": self._find_header(headers, "開札日"),
                "keiyaku_date": self._find_header(headers, "契約日"),
            }
            rows = table_rows[1:]
            
            for row_no, row in enumerate(rows, start=1):
                try:
                    cells = row.find_all("td")
                    if not cells:
                        continue

                    name_cell = self._cell(cells, header_indexes["project_name"])
                    detail_link = (
                        name_cell.find(
                            "a",
                            href=lambda value: value
                            and "__doPostBack" in value,
                        )
                        if name_cell
                        else None
                    )
                    if detail_link is None:
                        detail_link = row.find(
                            "a",
                            href=lambda value: value
                            and "__doPostBack" in value,
                        )
                    # 保存済みfixtureや旧サイト形式では、通常の詳細URLが
                    # 工事名とは別の「詳細」列に置かれている場合がある。
                    if detail_link is None:
                        detail_link = (
                            name_cell.find("a", href=True)
                            if name_cell
                            else None
                        )
                    if detail_link is None:
                        detail_link = row.find("a", href=True)
                    if not detail_link:
                        continue
                    
                    href = detail_link.get("href", "")
                    detail_url = urljoin(base_url, href)
                    if name_cell is not None and detail_link in name_cell.descendants:
                        project_name = self._cell_text(
                            cells, header_indexes["project_name"]
                        )
                    else:
                        project_name = detail_link.get_text(" ", strip=True)
                    project_name = project_name or self._cell_text(
                        cells, header_indexes["project_name"]
                    )
                    
                    if not project_name:
                        self.logger.debug("案件名が抽出できなかったため、この行をスキップします")
                        continue

                    event_target, event_argument = self._parse_postback(href)
                    koji_shubetsu = self._cell_text(
                        cells, header_indexes["koji_shubetsu"]
                    )
                    koji_gyoushu = self._cell_text(
                        cells, header_indexes["koji_gyoushu"]
                    )
                    if (
                        header_indexes["koji_shubetsu"] >= 0
                        and header_indexes["koji_shubetsu"]
                        == header_indexes["koji_gyoushu"]
                    ):
                        category_cell = self._cell(
                            cells, header_indexes["koji_shubetsu"]
                        )
                        combined_text = (
                            category_cell.get_text("／", strip=True)
                            if category_cell is not None
                            else koji_shubetsu
                        )
                        koji_shubetsu, koji_gyoushu = (
                            self._split_koji_category_cell(combined_text)
                        )
                    metadata = {
                        "project_name": project_name,
                        "koji_name": project_name,
                        "search_target": profile.target.value,
                        "hachu_kikan": self._cell_text(
                            cells, header_indexes["hachu_kikan"]
                        ),
                        "contract_type": self._cell_text(
                            cells, header_indexes["contract_type"]
                        ),
                        "koji_shubetsu": koji_shubetsu,
                        "koji_gyoushu": koji_gyoushu,
                        "gyomu_kubun": self._cell_text(
                            cells, header_indexes["gyomu_kubun"]
                        ),
                        "koukoku_date": self._cell_text(
                            cells, header_indexes["koukoku_date"]
                        ),
                        "kaisatsu_date": self._cell_text(
                            cells, header_indexes["kaisatsu_date"]
                        ),
                        "keiyaku_date": self._cell_text(
                            cells, header_indexes["keiyaku_date"]
                        ),
                    }
                    if agency_resolution is not None:
                        metadata.update(agency_resolution.to_metadata())
                    
                    entries.append(ProjectEntry(
                        detail_url=detail_url,
                        koji_name=project_name,
                        metadata=metadata,
                        page_no=page_no,
                        row_no=row_no,
                        event_target=event_target,
                        event_argument=event_argument,
                        source_url=base_url,
                        agency_path=(
                            agency_resolution.path
                            if agency_resolution is not None
                            else None
                        ),
                        agency_resolution=agency_resolution,
                        office_name=(
                            agency_resolution.office_name
                            if agency_resolution is not None
                            else ""
                        ),
                        agency_id=(
                            agency_resolution.agency_id
                            if agency_resolution is not None
                            else ""
                        ),
                        project_name=project_name,
                        search_target=profile.target.value,
                    ))
                except Exception as e:
                    self.logger.warning(f"行の解析エラー: {str(e)}")
                    continue
            
            self.logger.info(f"検索結果から{len(entries)}個の案件エントリを抽出しました")
            return entries
            
        except Exception as e:
            self.logger.error(f"検索結果解析エラー: {str(e)}")
            raise ScrapingError(f"検索結果解析エラー: {str(e)}")

    @staticmethod
    def _normalize(value: str) -> str:
        text = unicodedata.normalize("NFKC", value or "").replace("&nbsp;", "")
        return re.sub(r"[\s\u3000△▽／/]+", "", text)

    @classmethod
    def _find_header(cls, headers: List[str], *candidates: str) -> int:
        normalized_candidates = [cls._normalize(value) for value in candidates]
        for index, header in enumerate(headers):
            if any(candidate in header for candidate in normalized_candidates):
                return index
        return -1

    @staticmethod
    def _cell(cells, index: int):
        return cells[index] if 0 <= index < len(cells) else None

    @classmethod
    def _cell_text(cls, cells, index: int) -> str:
        cell = cls._cell(cells, index)
        return cell.get_text(" ", strip=True) if cell is not None else ""

    @staticmethod
    def _split_koji_category_cell(value: str) -> tuple[str, str]:
        """「工事種別／工事の業種」の共通セルを各条件へ分離する。"""
        parts = re.split(r"\s*[／/]\s*", value or "", maxsplit=1)
        shubetsu = parts[0].strip() if parts else ""
        gyoushu = parts[1].strip() if len(parts) > 1 else ""
        return shubetsu, gyoushu

    @staticmethod
    def _parse_postback(href: str) -> tuple[str, str]:
        match = re.search(
            r"__doPostBack\(\s*['\"]([^'\"]+)['\"]\s*,\s*"
            r"['\"]([^'\"]*)['\"]\s*\)",
            href or "",
        )
        return match.groups() if match else ("", "")
