# -*- coding: utf-8 -*-

"""Scraper のヘルパー（search_tab 推定・表示→value 変換）のユニットテスト"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bs4 import BeautifulSoup
from src.core.scraper import Scraper


@pytest.fixture
def scraper():
    return Scraper(http_client=MagicMock(), logger=MagicMock())


class TestInferSearchTabFromUrl:
    """_infer_search_tab_from_url のテスト（search_tab unknown 回避）"""

    def test_tab_4_returns_works(self, scraper):
        url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        assert scraper._infer_search_tab_from_url(url) == "works"

    def test_tab_6_returns_services(self, scraper):
        url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=6"
        assert scraper._infer_search_tab_from_url(url) == "services"

    def test_no_tab_returns_unknown(self, scraper):
        url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
        assert scraper._infer_search_tab_from_url(url) == "unknown"

    def test_path_searchworks_returns_works(self, scraper):
        url = "https://example.com/path/SearchWorks/Search.aspx"
        assert scraper._infer_search_tab_from_url(url) == "works"

    def test_path_searchworks_lowercase_returns_works(self, scraper):
        url = "https://example.com/foo/searchworks/bar"
        assert scraper._infer_search_tab_from_url(url) == "works"

    def test_empty_url_returns_unknown(self, scraper):
        assert scraper._infer_search_tab_from_url("") == "unknown"

    def test_tab_overrides_path(self, scraper):
        url = "https://example.com/SearchWorks/page.aspx?tab=6"
        assert scraper._infer_search_tab_from_url(url) == "services"


class TestGetDropdownValueFromText:
    """_get_dropdown_value_from_text のテスト（工事場所 表示→value 変換で使用）"""

    def test_returns_value_for_matching_text(self, scraper):
        html = """
        <select name="drpKojiDistrict" id="drpKojiDistrict">
            <option value="">選択</option>
            <option value="1">北海道</option>
            <option value="2">東北</option>
        </select>
        """
        soup = BeautifulSoup(html, "lxml")
        assert scraper._get_dropdown_value_from_text(soup, "drpKojiDistrict", "東北") == "2"
        assert scraper._get_dropdown_value_from_text(soup, "drpKojiDistrict", "北海道") == "1"

    def test_returns_none_when_text_not_found(self, scraper):
        html = '<select name="drpKojiDistrict"><option value="1">北海道</option></select>'
        soup = BeautifulSoup(html, "lxml")
        assert scraper._get_dropdown_value_from_text(soup, "drpKojiDistrict", "東北") is None

    def test_returns_none_for_missing_select(self, scraper):
        soup = BeautifulSoup("<div></div>", "lxml")
        assert scraper._get_dropdown_value_from_text(soup, "drpKojiDistrict", "東北") is None
