# -*- coding: utf-8 -*-

"""HTML解析・スクレイピングを行うクラス（ファサード）

実装の詳細は src/infrastructure/ppi/ 配下のモジュールに委譲している。
このクラスは外部 API の互換性を維持するための薄いラッパーである。
"""

from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

from ..models.file_info import FileInfo
from ..models.config_model import SearchConditions
from ..utils.http_client import HTTPClient
from ..utils.logger import Logger

from ..infrastructure.ppi.html import (
    normalize_search_url,
    parse_response_to_soup,
    set_response_encoding,
)
from ..infrastructure.ppi.forms import (
    get_all_hidden_inputs,
    get_all_form_inputs,
    do_postback,
    set_chubunrui_select_index,
)
from ..infrastructure.ppi.dropdowns import (
    get_dropdown_select,
    get_dropdown_value_from_text,
    parse_setListItemSub,
    parse_txtLargeKikanInf_h,
    parse_html_options,
    fetch_dropdown_options,
    fetch_hachu_daibunrui,
    fetch_hachu_chubunrui,
    fetch_hachu_shoubunrui,
    fetch_hachu_saibunrui,
    fetch_koji_prefecture,
    fetch_koji_city,
)
from ..infrastructure.ppi.detail import (
    extract_file_links as _extract_file_links,
    extract_metadata as _extract_metadata,
    extract_files_from_tables as _extract_files_from_tables,
    extract_link_metadata as _extract_link_metadata,
    extract_files_from_detail_via_postback as _extract_files_from_detail_via_postback,
    extract_files_from_detail_page as _extract_files_from_detail_page,
)
from ..infrastructure.ppi.search import (
    infer_search_tab_from_url as _infer_search_tab_from_url,
    ensure_agency_metadata as _ensure_agency_metadata,
    fetch_page as _fetch_page,
    submit_search_form as _submit_search_form,
    build_search_form_data as _build_search_form_data,
    extract_file_links_from_search_results as _extract_file_links_from_search_results,
)


class Scraper:
    """HTML解析・スクレイピングを行うクラス"""

    def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None):
        self.http_client = http_client
        self.logger = logger or Logger()

    # ────────────────────────────────────────────────────
    # HTML / エンコーディング
    # ────────────────────────────────────────────────────

    def _set_response_encoding(self, response) -> None:
        set_response_encoding(response)

    def _parse_response_to_soup(self, response) -> BeautifulSoup:
        return parse_response_to_soup(response)

    def _normalize_search_url(self, search_url: str) -> str:
        return normalize_search_url(search_url)

    # ────────────────────────────────────────────────────
    # フォーム操作
    # ────────────────────────────────────────────────────

    def _get_all_hidden_inputs(self, soup: BeautifulSoup) -> Dict[str, str]:
        return get_all_hidden_inputs(soup, self.logger)

    def _get_all_form_inputs(self, soup: BeautifulSoup) -> Dict[str, str]:
        return get_all_form_inputs(soup, self.logger)

    def _do_postback(self, url, soup, event_target, additional_data=None) -> BeautifulSoup:
        return do_postback(self.http_client, url, soup, event_target, self.logger, additional_data)

    def _set_chubunrui_select_index(self, soup, form_data, chubunrui_value) -> None:
        set_chubunrui_select_index(soup, form_data, chubunrui_value, self.logger)

    # ────────────────────────────────────────────────────
    # ドロップダウン（内部）
    # ────────────────────────────────────────────────────

    def _get_dropdown_select(self, soup, dropdown_name):
        return get_dropdown_select(soup, dropdown_name, self.logger)

    def _get_dropdown_value_from_text(self, soup, dropdown_name, display_text):
        return get_dropdown_value_from_text(soup, dropdown_name, display_text, self.logger)

    def _parse_setListItemSub(self, response_text, dropdown_name):
        return parse_setListItemSub(response_text, dropdown_name, self.logger)

    def _parse_txtLargeKikanInf_h(self, txt, target_key):
        return parse_txtLargeKikanInf_h(txt, target_key, self.logger)

    def _parse_html_options(self, soup, dropdown_name):
        return parse_html_options(soup, dropdown_name, self.logger)

    # ────────────────────────────────────────────────────
    # ドロップダウン（公開 API）
    # ────────────────────────────────────────────────────

    def get_dropdown_options(self, search_url, dropdown_name, parent_values=None):
        return fetch_dropdown_options(self.http_client, search_url, dropdown_name, self.logger, parent_values)

    def get_hachu_daibunrui_options(self, search_url):
        return fetch_hachu_daibunrui(self.http_client, search_url, self.logger)

    def get_hachu_chubunrui_options(self, search_url, daibunrui_value):
        return fetch_hachu_chubunrui(self.http_client, search_url, daibunrui_value, self.logger)

    def get_hachu_shoubunrui_options(self, search_url, daibunrui_value, chubunrui_value):
        return fetch_hachu_shoubunrui(self.http_client, search_url, daibunrui_value, chubunrui_value, self.logger)

    def get_hachu_saibunrui_options(self, search_url, daibunrui_value, chubunrui_value, shoubunrui_value):
        return fetch_hachu_saibunrui(self.http_client, search_url, daibunrui_value, chubunrui_value, shoubunrui_value, self.logger)

    def get_koji_prefecture_options(self, search_url, district_text):
        return fetch_koji_prefecture(self.http_client, search_url, district_text, self.logger)

    def get_koji_city_options(self, search_url, district_text, prefecture_text):
        return fetch_koji_city(self.http_client, search_url, district_text, prefecture_text, self.logger)

    # ────────────────────────────────────────────────────
    # 検索
    # ────────────────────────────────────────────────────

    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        return _fetch_page(self.http_client, url, self.logger)

    def submit_search_form(self, search_url, search_conditions) -> Optional[BeautifulSoup]:
        soup, result_url = _submit_search_form(self.http_client, search_url, search_conditions, self.logger)
        self._last_search_result_url = result_url
        return soup

    def _build_search_form_data(self, search_conditions, initial_soup):
        return _build_search_form_data(search_conditions, initial_soup, self.logger)

    # ────────────────────────────────────────────────────
    # ファイルリンク抽出
    # ────────────────────────────────────────────────────

    def extract_file_links(self, soup, base_url, file_types):
        return _extract_file_links(soup, base_url, file_types, self.logger)

    def extract_metadata(self, soup):
        return _extract_metadata(soup)

    def _extract_files_from_tables(self, soup, base_url, file_types):
        return _extract_files_from_tables(soup, base_url, file_types, self.logger)

    def _extract_link_metadata(self, link_tag):
        return _extract_link_metadata(link_tag)

    def extract_file_links_from_search_results(self, soup, base_url, file_types, search_conditions=None):
        last_url = getattr(self, "_last_search_result_url", base_url)
        files, total, new_url, unavailable = _extract_file_links_from_search_results(
            self.http_client, soup, base_url, file_types, self.logger,
            search_conditions, last_url,
        )
        self.last_search_total_koji_count = total
        self.last_search_unavailable_document_count = unavailable
        self._last_search_result_url = new_url
        return files

    def _extract_files_from_detail_page_via_postback(self, base_url, postback_href, file_types, current_soup, koji_name=None):
        last_url = getattr(self, "_last_search_result_url", base_url)
        saved = getattr(self, "_detail_page_saved", False)
        files, new_saved, unavailable = _extract_files_from_detail_via_postback(
            self.http_client, base_url, postback_href, file_types, current_soup,
            self.logger, last_url, koji_name=koji_name, detail_page_saved_flag=saved,
        )
        self._detail_page_saved = new_saved
        self._last_detail_unavailable_count = unavailable
        return files

    def _extract_files_from_detail_page(self, detail_url, file_types):
        return _extract_files_from_detail_page(self.http_client, detail_url, file_types, self.logger)

    # ────────────────────────────────────────────────────
    # ユーティリティ
    # ────────────────────────────────────────────────────

    def _infer_search_tab_from_url(self, url: str) -> str:
        return _infer_search_tab_from_url(url)

    def _ensure_agency_metadata(self, file_info, search_conditions, base_url):
        _ensure_agency_metadata(file_info, search_conditions, base_url)

    def _count_koji_in_page(self, soup, search_conditions=None):
        from ..infrastructure.ppi.search import _count_koji_in_page
        return _count_koji_in_page(soup, search_conditions)

    def _get_next_page(self, current_soup, base_url):
        from ..infrastructure.ppi.search import _get_next_page
        last_url = getattr(self, "_last_search_result_url", base_url)
        soup, new_url = _get_next_page(self.http_client, current_soup, base_url, last_url, self.logger)
        if soup:
            self._last_search_result_url = new_url
        return soup
