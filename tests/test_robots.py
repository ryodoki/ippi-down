# -*- coding: utf-8 -*-

"""robots.txt 遵守のテスト"""

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.app.exceptions import BlockedRequestError
from src.models.config_model import RobotsConfig
from src.utils.robots import RobotsPolicy
from tests.test_url_policy import FakeResponse, make_client

# robots.txt の User-agent 行は製品トークンで照合される
UA = "ippi-down"
BASE = "https://www.i-ppi.jp"

ROBOTS_BODY = """
User-agent: *
Disallow: /private/
Crawl-delay: 5

User-agent: ippi-down
Disallow: /secret/
"""


def _fetcher(status=200, body=ROBOTS_BODY, error=None, counter=None):
    def fetch(url):
        if counter is not None:
            counter.append(url)
        if error is not None:
            raise error
        return status, body

    return fetch


def test_disallowed_paths_are_not_fetched():
    policy = RobotsPolicy(_fetcher())
    assert policy.can_fetch(UA, f"{BASE}/IPPI/Search.aspx")
    assert not policy.can_fetch(UA, f"{BASE}/secret/list")
    # 自分向けのブロックが無いエージェントには * のルールが適用される
    assert not policy.can_fetch("other-agent", f"{BASE}/private/x")


def test_crawl_delay_is_reported():
    policy = RobotsPolicy(_fetcher())
    assert policy.crawl_delay("other-agent", f"{BASE}/x") == 5.0


def test_request_rate_is_converted_to_an_interval():
    body = "User-agent: *\nRequest-rate: 1/10\nDisallow:\n"
    policy = RobotsPolicy(_fetcher(body=body))
    assert policy.crawl_delay(UA, f"{BASE}/x") == 10.0


def test_missing_robots_txt_means_no_restriction():
    policy = RobotsPolicy(_fetcher(status=404, body=""))
    assert policy.can_fetch(UA, f"{BASE}/anything")


def test_forbidden_robots_txt_blocks_everything():
    policy = RobotsPolicy(_fetcher(status=403, body=""))
    assert not policy.can_fetch(UA, f"{BASE}/anything")


def test_fetch_failure_blocks_by_default_and_can_be_relaxed():
    blocking = RobotsPolicy(_fetcher(error=OSError("接続できません")))
    assert not blocking.can_fetch(UA, f"{BASE}/x")

    relaxed = RobotsPolicy(_fetcher(error=OSError("接続できません")), on_error="allow")
    assert relaxed.can_fetch(UA, f"{BASE}/x")

    server_error = RobotsPolicy(_fetcher(status=503, body=""))
    assert not server_error.can_fetch(UA, f"{BASE}/x")


def test_robots_txt_is_fetched_once_per_host():
    calls = []
    policy = RobotsPolicy(_fetcher(counter=calls))
    for path in ("/a", "/b", "/c"):
        policy.can_fetch(UA, BASE + path)
    assert calls == [f"{BASE}/robots.txt"]
    assert policy.fetch_count == 1


def test_cache_expires_after_the_ttl():
    calls = []
    clock = [0.0]
    policy = RobotsPolicy(
        _fetcher(counter=calls),
        cache_ttl_seconds=100,
        monotonic=lambda: clock[0],
    )
    policy.can_fetch(UA, f"{BASE}/a")
    clock[0] = 50
    policy.can_fetch(UA, f"{BASE}/b")
    assert len(calls) == 1
    clock[0] = 200
    policy.can_fetch(UA, f"{BASE}/c")
    assert len(calls) == 2


def test_disabled_policy_allows_everything():
    policy = RobotsPolicy(_fetcher(), enabled=False)
    assert policy.can_fetch(UA, f"{BASE}/secret/x")
    assert policy.crawl_delay(UA, f"{BASE}/x") is None
    assert policy.fetch_count == 0


def test_http_client_refuses_disallowed_urls(tmp_path):
    client = make_client(tmp_path, robots=RobotsConfig(enabled=True))
    client.session.response = FakeResponse(status_code=200, text=ROBOTS_BODY)

    with pytest.raises(BlockedRequestError) as excinfo:
        client.get(f"{BASE}/secret/list")
    assert excinfo.value.reason == "robots_denied"

    audit = (tmp_path / "network.log").read_text(encoding="utf-8")
    assert "robots_denied" in audit


def test_http_client_applies_crawl_delay_to_the_rate_limiter(tmp_path):
    # * の Crawl-delay: 5 が最小間隔として採用される
    body = "User-agent: *\nCrawl-delay: 5\nDisallow: /private/\n"
    client = make_client(tmp_path, robots=RobotsConfig(enabled=True))
    client.session.response = FakeResponse(status_code=200, text=body)

    client.get(f"{BASE}/IPPI/Search.aspx")
    assert client.rate_limiter.min_interval_for("www.i-ppi.jp") == 5.0


def test_http_client_matches_robots_by_product_token(tmp_path):
    client = make_client(tmp_path, robots=RobotsConfig(enabled=True))
    assert client.robots_user_agent == "ippi-down"
