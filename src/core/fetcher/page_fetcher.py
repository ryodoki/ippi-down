# -*- coding: utf-8 -*-

"""Page Fetcher（HTTP取得/リトライ/429制御）"""

from typing import Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from ...utils.http_client import HTTPClient
from ...utils.outbound_policy import NetworkPurpose
from ...utils.logger import Logger
from ...app.exceptions import NetworkError, ScrapingError


class PageFetcher:
    """ページ取得を行うクラス（HTTP取得/リトライ/429制御）"""

    def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None):
        """初期化"""
        self.http_client = http_client
        self.logger = logger or Logger()

    def _normalize_search_url(self, search_url: str) -> str:
        """呼出元が選択した対象URLを変更せず返す。"""

        return str(search_url or "")

    def fetch_page(
        self,
        url: str,
        purpose: Optional[NetworkPurpose] = None,
    ) -> Optional[BeautifulSoup]:
        """ページを取得してBeautifulSoupオブジェクトを返す"""
        response = None
        try:
            normalized_url = self._normalize_search_url(url)
            self.logger.info(f"ページを取得中: {normalized_url}")
            if purpose is None:
                purpose = (
                    NetworkPurpose.DETAIL
                    if urlparse(normalized_url).path.endswith(
                        (
                            "/IPPI/SearchServices/Web/Koji/Keika/List.aspx",
                            "/IPPI/SearchServices/Web/Gyomu/Keika/List.aspx",
                        )
                    )
                    else NetworkPurpose.SEARCH
                )
            response = self.http_client.get(
                normalized_url,
                purpose=purpose,
            )
            
            if response.encoding:
                response.encoding = response.apparent_encoding or 'utf-8'
            else:
                response.encoding = 'utf-8'
            
            try:
                soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
            
            return soup
        except NetworkError:
            raise
        except Exception as e:
            self.logger.error(f"ページ取得エラー: {url} - {str(e)}", exc_info=True)
            raise ScrapingError(f"ページ取得エラー: {url} - {str(e)}")
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
