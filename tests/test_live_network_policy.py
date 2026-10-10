# -*- coding: utf-8 -*-

"""明示実行時だけ公式検索画面を1回読む最小疎通試験。"""

from __future__ import annotations

import pytest

from src.utils.http_client import HTTPClient
from src.utils.outbound_policy import NetworkPurpose


SEARCH_URL = (
    "https://www.i-ppi.jp/IPPI/SearchServices/Web/"
    "Search/Search/Search.aspx?tab=4"
)


@pytest.mark.network
def test_live_official_search_endpoint_is_reachable_through_policy():
    """POSTや文書取得を行わず、許可済み公式画面だけを1 GETする。"""

    client = HTTPClient(
        timeout=10,
        download_timeout=10,
        requests_per_second=1,
    )
    response = None
    try:
        response = client.get(
            SEARCH_URL,
            max_retries=1,
            purpose=NetworkPurpose.SEARCH,
        )
        assert response.status_code == 200
        assert "text/html" in response.headers.get(
            "Content-Type", ""
        ).casefold()
        assert response.url.startswith(
            "https://www.i-ppi.jp/IPPI/SearchServices/Web/"
        )
    finally:
        if response is not None:
            response.close()
        client.close()
