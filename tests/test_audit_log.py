# -*- coding: utf-8 -*-

"""監査ログ（allow / blocked / robots_denied / rate_limited）のテスト"""

import socket
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.app.exceptions import BlockedRequestError
from src.models.config_model import NetworkConfig, RobotsConfig
from src.utils import netguard
from src.utils.netguard import BlockedConnectionError
from src.utils.network_audit import COLUMNS, NetworkAuditLog
from tests.test_url_policy import FakeResponse, make_client

ALLOWED_URL = "https://www.i-ppi.jp/IPPI/Search.aspx"
ROBOTS_BODY = "User-agent: *\nDisallow: /private/\n"


def read_rows(path: Path):
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [line.split("\t") for line in lines]


def test_writer_produces_one_row_per_decision(tmp_path):
    audit = NetworkAuditLog(tmp_path / "logs" / "network.log")
    audit.write("allow", "https://www.i-ppi.jp/a", method="GET", status=200, size=10, elapsed_ms=12.7)
    audit.write("blocked", "https://example.com/b", method="GET", detail="許可外")

    rows = read_rows(tmp_path / "logs" / "network.log")
    assert len(rows) == 2
    assert len(rows[0]) == len(COLUMNS)
    assert rows[0][1:7] == ["allow", "GET", "https://www.i-ppi.jp/a", "200", "10", "13"]
    assert rows[1][1] == "blocked"
    assert rows[1][7] == "許可外"


def test_writer_without_a_path_is_a_no_op(tmp_path):
    audit = NetworkAuditLog(None)
    assert audit.enabled is False
    audit.write("allow", "https://www.i-ppi.jp/a")
    assert list(tmp_path.iterdir()) == []


def test_tabs_and_newlines_do_not_break_the_format(tmp_path):
    path = tmp_path / "network.log"
    NetworkAuditLog(path).write("blocked", "https://x/y", detail="改行\nとタブ\tを含む")
    rows = read_rows(path)
    assert len(rows) == 1
    assert len(rows[0]) == len(COLUMNS)


def test_successful_request_is_recorded_as_allow(tmp_path):
    client = make_client(tmp_path, robots=RobotsConfig(enabled=False))
    client.session.response = FakeResponse(status_code=200, headers={"Content-Length": "42"})

    client.get(ALLOWED_URL)

    rows = read_rows(tmp_path / "network.log")
    assert rows[-1][1] == "allow"
    assert rows[-1][2] == "GET"
    assert rows[-1][3] == ALLOWED_URL
    assert rows[-1][4] == "200"
    assert rows[-1][5] == "42"


def test_blocked_request_is_recorded(tmp_path):
    client = make_client(tmp_path, robots=RobotsConfig(enabled=False))
    with pytest.raises(BlockedRequestError):
        client.get("https://example.com/x")

    rows = read_rows(tmp_path / "network.log")
    assert rows[-1][1] == "blocked"
    assert "許可リストにないホスト" in rows[-1][7]


def test_robots_denied_is_recorded(tmp_path):
    client = make_client(tmp_path, robots=RobotsConfig(enabled=True))
    client.session.response = FakeResponse(status_code=200, text=ROBOTS_BODY)

    with pytest.raises(BlockedRequestError):
        client.get("https://www.i-ppi.jp/private/list")

    events = [row[1] for row in read_rows(tmp_path / "network.log")]
    assert "robots_denied" in events


def test_rate_limited_is_recorded(tmp_path):
    client = make_client(tmp_path, robots=RobotsConfig(enabled=False))
    client.session.response = FakeResponse(status_code=429, headers={"Retry-After": "0"})

    with pytest.raises(Exception):
        client.get(ALLOWED_URL, max_retries=1)

    events = [row[1] for row in read_rows(tmp_path / "network.log")]
    assert "rate_limited" in events


def test_guard_and_client_share_one_log(tmp_path):
    audit_path = tmp_path / "network.log"
    netguard.install_from_config(NetworkConfig(audit_log=str(audit_path)))
    with pytest.raises(BlockedConnectionError):
        socket.getaddrinfo("telemetry.example.com", 443)

    client = make_client(tmp_path, robots=RobotsConfig(enabled=False))
    client.session.response = FakeResponse(status_code=200)
    client.get(ALLOWED_URL)

    rows = read_rows(audit_path)
    assert [row[2] for row in rows] == ["GUARD", "GET"]
    assert [row[1] for row in rows] == ["blocked", "allow"]
