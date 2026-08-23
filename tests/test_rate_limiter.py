# -*- coding: utf-8 -*-

"""レート制限（最小間隔・同時接続・総量・稼働時間帯）のテスト"""

import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.app.exceptions import OutsideAllowedHoursError, RequestBudgetExceededError
from src.models.config_model import NetworkConfig, RobotsConfig
from src.utils.rate_limiter import RateLimiter, is_within_allowed_hours, parse_allowed_hours
from tests.test_url_policy import FakeResponse, make_client

HOST = "www.i-ppi.jp"


class FakeClock:
    """monotonic と sleep を差し替えて実時間を待たずに検証する"""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_limiter(clock=None, **kwargs):
    clock = clock or FakeClock()
    settings = dict(
        min_interval_seconds=1.0,
        jitter=lambda low, high: 0.0,  # ジッタを固定して間隔だけを検証する
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    settings.update(kwargs)
    return RateLimiter(**settings), clock


def test_consecutive_requests_wait_for_the_minimum_interval():
    limiter, clock = make_limiter()

    assert limiter.acquire(HOST) == 0.0  # 初回は待たない
    limiter.release(HOST)
    assert limiter.acquire(HOST) == pytest.approx(1.0)
    limiter.release(HOST)
    assert clock.sleeps == [1.0]


def test_elapsed_time_counts_towards_the_interval():
    limiter, clock = make_limiter()
    limiter.acquire(HOST)
    limiter.release(HOST)

    clock.now += 0.6
    assert limiter.acquire(HOST) == pytest.approx(0.4)
    limiter.release(HOST)

    clock.now += 5
    assert limiter.acquire(HOST) == 0.0


def test_interval_is_tracked_per_host():
    limiter, _ = make_limiter()
    limiter.acquire(HOST)
    limiter.release(HOST)
    assert limiter.acquire("other.i-ppi.jp") == 0.0
    limiter.release("other.i-ppi.jp")


def test_jitter_is_applied_around_the_interval():
    limiter, clock = make_limiter(jitter=lambda low, high: high)  # 最大側に振れた場合
    limiter.acquire(HOST)
    limiter.release(HOST)
    assert limiter.acquire(HOST) == pytest.approx(1.2)
    limiter.release(HOST)


def test_concurrency_is_serialised_to_one():
    limiter, _ = make_limiter(min_interval_seconds=0.0, max_concurrency=1)
    limiter.acquire(HOST)

    entered = threading.Event()

    def worker():
        limiter.acquire(HOST)
        entered.set()
        limiter.release(HOST)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert not entered.wait(0.2), "同時接続が直列化されていません"

    limiter.release(HOST)
    assert entered.wait(2)
    thread.join(2)


def test_request_budget_stops_the_run():
    limiter, _ = make_limiter(min_interval_seconds=0.0, max_requests_per_run=2)
    for _ in range(2):
        limiter.acquire(HOST)
        limiter.release(HOST)

    with pytest.raises(RequestBudgetExceededError):
        limiter.acquire(HOST)

    limiter.reset()
    limiter.acquire(HOST)
    limiter.release(HOST)


def test_crawl_delay_only_raises_the_interval():
    limiter, _ = make_limiter(min_interval_seconds=2.0)
    assert limiter.set_min_interval(HOST, 5.0) == 5.0
    assert limiter.set_min_interval(HOST, 1.0) == 5.0
    assert limiter.min_interval_for(HOST) == 5.0


def test_rate_limited_response_doubles_the_interval():
    limiter, _ = make_limiter(min_interval_seconds=1.0)
    assert limiter.note_rate_limited(HOST) == 2.0
    assert limiter.note_rate_limited(HOST) == 4.0
    assert limiter.min_interval_for(HOST) == 4.0


def test_allowed_hours_window():
    assert parse_allowed_hours(None) is None
    window = parse_allowed_hours("08:00-22:00")
    assert is_within_allowed_hours(window, datetime(2026, 1, 1, 9, 0).time())
    assert not is_within_allowed_hours(window, datetime(2026, 1, 1, 23, 0).time())

    overnight = parse_allowed_hours("22:00-06:00")
    assert is_within_allowed_hours(overnight, datetime(2026, 1, 1, 23, 0).time())
    assert is_within_allowed_hours(overnight, datetime(2026, 1, 1, 5, 0).time())
    assert not is_within_allowed_hours(overnight, datetime(2026, 1, 1, 12, 0).time())

    with pytest.raises(ValueError):
        parse_allowed_hours("morning")


def test_requests_outside_allowed_hours_are_refused():
    limiter, _ = make_limiter(
        allowed_hours="08:00-22:00",
        now=lambda: datetime(2026, 1, 1, 3, 0),
    )
    with pytest.raises(OutsideAllowedHoursError):
        limiter.acquire(HOST)


def test_http_client_counts_requests_and_reacts_to_429(tmp_path):
    client = make_client(tmp_path, robots=RobotsConfig(enabled=False))
    client.session.response = FakeResponse(status_code=200, headers={"Content-Length": "10"})

    client.get(f"https://{HOST}/a")
    client.get(f"https://{HOST}/b")
    assert client.rate_limiter.request_count == 2

    client.session.response = FakeResponse(status_code=429, headers={"Retry-After": "0"})
    with pytest.raises(Exception):
        client.get(f"https://{HOST}/c", max_retries=1)
    assert client.rate_limiter.min_interval_for(HOST) > 0

    audit = (tmp_path / "network.log").read_text(encoding="utf-8")
    assert "rate_limited" in audit


def test_rate_limiter_is_built_from_config():
    config = NetworkConfig(
        min_interval_seconds=2.5, max_concurrency=3, max_requests_per_run=7
    )
    limiter = RateLimiter.from_config(config)
    assert limiter.default_min_interval == 2.5
    assert limiter.max_concurrency == 3
    assert limiter.max_requests_per_run == 7
