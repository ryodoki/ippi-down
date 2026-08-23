# -*- coding: utf-8 -*-

"""エグレスガード（許可リスト方式）のテスト"""

import socket
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.config_model import NetworkConfig
from src.utils import netguard
from src.utils.netguard import BlockedConnectionError, NetworkPolicy

ALLOWED_HOST = "www.i-ppi.jp"
ALLOWED_IP = "93.184.216.34"
OTHER_IP = "93.184.216.35"
PRIVATE_IP = "10.1.2.3"


def _fake_resolver(mapping):
    def resolver(host, port=None, family=0, type=0, proto=0, flags=0):
        ip = mapping.get(str(host))
        if ip is None:
            raise socket.gaierror(f"未登録のホスト: {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 443))]

    return resolver


def test_default_policy_allows_only_the_target_site():
    policy = NetworkPolicy()
    assert policy.allows_host(ALLOWED_HOST)
    assert policy.allows_host("WWW.I-PPI.JP")
    assert not policy.allows_host("i-ppi.jp.evil.test")
    assert not policy.allows_host("example.com")
    assert not policy.denies_everything


def test_other_hosts_are_blocked_at_name_resolution():
    netguard.install_guard()
    with pytest.raises(BlockedConnectionError):
        socket.getaddrinfo("example.com", 443)
    assert any("example.com" in event for event in netguard.blocked_events())


def test_allowed_host_resolves_and_only_its_address_is_reachable(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver({ALLOWED_HOST: ALLOWED_IP}))
    netguard.install_guard()

    infos = socket.getaddrinfo(ALLOWED_HOST, 443)
    assert infos[0][4][0] == ALLOWED_IP

    netguard.check_ip(ALLOWED_IP, 443)
    with pytest.raises(BlockedConnectionError):
        netguard.check_ip(OTHER_IP, 443)


def test_ip_literal_connect_is_blocked():
    netguard.install_guard()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(BlockedConnectionError):
            sock.connect((OTHER_IP, 443))


def test_private_addresses_are_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver({ALLOWED_HOST: PRIVATE_IP}))
    netguard.install_guard()
    socket.getaddrinfo(ALLOWED_HOST, 443)

    with pytest.raises(BlockedConnectionError):
        netguard.check_ip(PRIVATE_IP, 443)


def test_create_connection_is_guarded(monkeypatch, real_create_connection):
    monkeypatch.setattr(socket, "create_connection", real_create_connection)
    netguard.install_guard()
    with pytest.raises(BlockedConnectionError):
        socket.create_connection(("example.com", 443), timeout=1)


def test_install_from_config_uses_the_configured_allowlist(tmp_path):
    audit = tmp_path / "logs" / "network.log"
    config = NetworkConfig(allowed_hosts=["www.example.jp"], audit_log=str(audit))
    policy = netguard.install_from_config(config)

    assert policy.allowed_hosts == ("www.example.jp",)
    with pytest.raises(BlockedConnectionError):
        socket.getaddrinfo(ALLOWED_HOST, 443)

    fields = audit.read_text(encoding="utf-8").strip().split("\t")
    assert fields[1] == "blocked"
    assert fields[3] == f"{ALLOWED_HOST}:443"


def test_install_is_idempotent_and_uninstall_restores():
    before = socket.getaddrinfo
    netguard.install_guard()
    patched = socket.getaddrinfo
    netguard.install_guard()
    assert socket.getaddrinfo is patched

    netguard.uninstall_guard()
    assert socket.getaddrinfo is before
    assert not netguard.is_installed()


def test_loopback_is_allowed_by_default():
    netguard.install_guard()
    netguard.check_ip("127.0.0.1", 8000)
    netguard.check_host("localhost", 8000)

    netguard.reconfigure(allow_loopback=False)
    with pytest.raises(BlockedConnectionError):
        netguard.check_ip("127.0.0.1", 8000)
