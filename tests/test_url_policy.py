# -*- coding: utf-8 -*-

"""HTTPClient の URL ポリシー（許可スキーム・許可ホスト）のテスト"""

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.app.exceptions import BlockedRequestError
from src.models.config_model import LoggingConfig, NetworkConfig, RobotsConfig
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger
from src.utils.rate_limiter import RateLimiter

ALLOWED_URL = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        return None


class FakeSession:
    """通信せずに呼び出しを記録するセッション"""

    def __init__(self, headers=None, response=None):
        self.headers = dict(headers or {})
        self.calls = []
        self.response = response or FakeResponse()

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return self.response

    def mount(self, *args, **kwargs):
        return None

    def close(self):
        return None


def make_client(tmp_path, **overrides):
    settings = dict(
        min_interval_seconds=0.0,
        audit_log=str(tmp_path / "network.log"),
        robots=RobotsConfig(enabled=False),
    )
    settings.update(overrides)
    client = HTTPClient(
        Logger(LoggingConfig(level="INFO")),
        network_config=NetworkConfig(**settings),
        # テストごとに独立した制限を使う（共有インスタンスの状態を持ち込まない）
        rate_limiter=RateLimiter(min_interval_seconds=0.0, jitter=lambda low, high: 0.0),
    )
    client.session = FakeSession(headers=client.session.headers)
    return client


def test_allowed_url_passes(tmp_path):
    client = make_client(tmp_path)
    response = client.get(ALLOWED_URL)
    assert response.status_code == 200
    assert client.session.calls == [("GET", ALLOWED_URL)]


def test_other_host_is_refused_before_sending(tmp_path):
    client = make_client(tmp_path)
    for url in (
        "https://example.com/data.pdf",
        "https://www.i-ppi.jp.evil.test/x",
        "https://203.0.113.9/x",
    ):
        with pytest.raises(BlockedRequestError):
            client.get(url)
    assert client.session.calls == []


def test_plain_http_is_refused(tmp_path):
    client = make_client(tmp_path)
    with pytest.raises(BlockedRequestError):
        client.get("http://www.i-ppi.jp/index.html")
    assert client.session.calls == []


def test_non_http_schemes_and_broken_urls_are_refused(tmp_path):
    client = make_client(tmp_path)
    for url in ("file:///C:/secret.txt", "ftp://www.i-ppi.jp/x", "", "not a url"):
        with pytest.raises(BlockedRequestError):
            client.get(url)


def test_post_and_download_share_the_same_check(tmp_path):
    client = make_client(tmp_path)
    with pytest.raises(BlockedRequestError):
        client.post("https://example.com/submit", data={"a": 1})

    # HTML から抽出した動的リンクも download_file を通るため同じ検査が効く
    with pytest.raises(BlockedRequestError):
        client.download_file(
            "https://cdn.example.com/attachment.pdf", str(tmp_path / "out.pdf")
        )
    assert client.session.calls == []


def test_wildcard_host_pattern(tmp_path):
    client = make_client(tmp_path, allowed_hosts=["*.i-ppi.jp"])
    client.get("https://www.i-ppi.jp/a")
    client.get("https://i-ppi.jp/b")
    with pytest.raises(BlockedRequestError):
        client.get("https://i-ppi.jp.evil.test/c")


def test_user_agent_identifies_the_tool(tmp_path):
    client = make_client(tmp_path)
    assert "ippi-down/" in client.user_agent
    assert "Mozilla" in client.user_agent

    override = make_client(tmp_path, user_agent="ippi-down/1.0 (+contact@example.jp)")
    assert override.user_agent == "ippi-down/1.0 (+contact@example.jp)"
    assert "Mozilla" not in override.user_agent
