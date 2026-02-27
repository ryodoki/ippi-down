# -*- coding: utf-8 -*-
"""HTTP レスポンスのエンコーディング処理・BeautifulSoup 生成"""

from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse, parse_qs


def set_response_encoding(response) -> None:
    """レスポンスのエンコーディングを設定"""
    if response.encoding:
        response.encoding = response.apparent_encoding or "utf-8"
    else:
        response.encoding = "utf-8"


def parse_response_to_soup(response) -> BeautifulSoup:
    """レスポンスから BeautifulSoup を生成"""
    set_response_encoding(response)
    try:
        return BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
    except (UnicodeDecodeError, LookupError):
        try:
            return BeautifulSoup(response.content, "lxml", from_encoding="utf-8")
        except UnicodeDecodeError:
            return BeautifulSoup(response.content.decode("utf-8", errors="ignore"), "lxml")


def normalize_search_url(search_url: str) -> str:
    """検索 URL を正規化（tab=4 パラメータを追加）"""
    parsed = urlparse(search_url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    query_params["tab"] = ["4"]
    new_query = "&".join(
        f"{k}={v[0]}" if len(v) == 1 else "&".join(f"{k}={val}" for val in v)
        for k, v in query_params.items()
    )
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
