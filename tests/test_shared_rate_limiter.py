# -*- coding: utf-8 -*-

"""レート制限をプロセス全体で共有していることのテスト

GUI のドロップダウン読み込みスレッドと本処理はそれぞれ HTTPClient を持つため、
共有していないと同一ホストへ同時に出てしまう。
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.config_model import LoggingConfig, NetworkConfig, RobotsConfig
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger
from src.utils.rate_limiter import get_shared_limiter, reset_shared_limiter


def make_shared_client(tmp_path):
    return HTTPClient(
        Logger(LoggingConfig(level="INFO")),
        network_config=NetworkConfig(
            audit_log=str(tmp_path / "network.log"), robots=RobotsConfig(enabled=False)
        ),
    )


def test_clients_share_one_limiter(tmp_path):
    first = make_shared_client(tmp_path)
    second = make_shared_client(tmp_path)
    assert first.rate_limiter is second.rate_limiter


def test_shared_limiter_only_gets_stricter():
    get_shared_limiter(NetworkConfig(min_interval_seconds=1.0, max_requests_per_run=500))
    limiter = get_shared_limiter(
        NetworkConfig(min_interval_seconds=3.0, max_requests_per_run=10, max_concurrency=5)
    )
    assert limiter.default_min_interval == 3.0
    assert limiter.max_requests_per_run == 10
    assert limiter.max_concurrency == 1

    relaxed = get_shared_limiter(
        NetworkConfig(min_interval_seconds=0.1, max_requests_per_run=9999)
    )
    assert relaxed.default_min_interval == 3.0
    assert relaxed.max_requests_per_run == 10


def test_reset_creates_a_fresh_limiter():
    first = get_shared_limiter(NetworkConfig())
    reset_shared_limiter()
    assert get_shared_limiter(NetworkConfig()) is not first
