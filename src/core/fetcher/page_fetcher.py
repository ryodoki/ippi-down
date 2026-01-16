"""Page Fetcher（HTTP取得/リトライ/429制御）"""

from typing import Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse, parse_qs
from ...utils.http_client import HTTPClient
from ...utils.logger import Logger
from ...app.exceptions import NetworkError, ScrapingError


class PageFetcher:
    """ページ取得を行うクラス（HTTP取得/リトライ/429制御）"""

    def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None):
        """初期化"""
        self.http_client = http_client
        self.logger = logger or Logger()

    def _normalize_search_url(self, search_url: str) -> str:
        """検索URLを正規化（tab=4パラメータを追加）"""
        parsed = urlparse(search_url)
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        # tab=4パラメータを追加（必須）
        query_params['tab'] = ['4']
        new_query = '&'.join(
            f"{k}={v[0]}" if len(v) == 1 else '&'.join(f"{k}={val}" for val in v)
            for k, v in query_params.items()
        )
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        return normalized

    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """ページを取得してBeautifulSoupオブジェクトを返す"""
        try:
            normalized_url = self._normalize_search_url(url)
            self.logger.info(f"ページを取得中: {normalized_url}")
            response = self.http_client.get(normalized_url)
            
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
