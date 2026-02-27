# -*- coding: utf-8 -*-
"""GUI 用ドロップダウンオプション取得サービス

GUI から core/scraper を直接呼ばず、この application 層を経由する。
内部で infrastructure/ppi/dropdowns を呼び出す。
"""

from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING

from ..infrastructure.ppi.dropdowns import (
    fetch_hachu_daibunrui,
    fetch_hachu_chubunrui,
    fetch_hachu_shoubunrui,
    fetch_hachu_saibunrui,
    fetch_koji_prefecture,
    fetch_koji_city,
)

if TYPE_CHECKING:
    from ..utils.http_client import HTTPClient
    from ..utils.logger import Logger


class LookupService:
    """階層ドロップダウンオプション取得（GUI 用）"""

    DEFAULT_SEARCH_URL = (
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    )

    def __init__(
        self,
        http_client: "HTTPClient",
        logger: "Logger",
        search_url: Optional[str] = None,
    ):
        self._http_client = http_client
        self._logger = logger
        self._search_url = search_url or self.DEFAULT_SEARCH_URL

    @property
    def search_url(self) -> str:
        return self._search_url

    @search_url.setter
    def search_url(self, value: str) -> None:
        self._search_url = value

    def get_hachu_daibunrui(self) -> List[str]:
        return fetch_hachu_daibunrui(self._http_client, self._search_url, self._logger)

    def get_hachu_chubunrui(self, daibunrui_text: str) -> List[str]:
        return fetch_hachu_chubunrui(self._http_client, self._search_url, daibunrui_text, self._logger)

    def get_hachu_shoubunrui(self, daibunrui_text: str, chubunrui_text: str) -> List[str]:
        return fetch_hachu_shoubunrui(self._http_client, self._search_url, daibunrui_text, chubunrui_text, self._logger)

    def get_hachu_saibunrui(
        self, daibunrui_text: str, chubunrui_text: str, shoubunrui_text: str
    ) -> List[str]:
        return fetch_hachu_saibunrui(
            self._http_client, self._search_url, daibunrui_text, chubunrui_text, shoubunrui_text, self._logger
        )

    def get_koji_prefecture(self, district_text: str) -> List[str]:
        return fetch_koji_prefecture(self._http_client, self._search_url, district_text, self._logger)

    def get_koji_city(self, district_text: str, prefecture_text: str) -> List[str]:
        return fetch_koji_city(self._http_client, self._search_url, district_text, prefecture_text, self._logger)
