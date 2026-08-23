# -*- coding: utf-8 -*-

"""pytest設定とフィクスチャ"""

import pytest
import ipaddress
import os
import socket
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils import netguard  # noqa: E402  （sys.path 追加後に import する）
from src.utils.rate_limiter import reset_shared_limiter  # noqa: E402

# 素のソケット関数（テスト実行中はここへ必ず戻す）
_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_SENDTO = socket.socket.sendto
_REAL_CREATE_CONNECTION = socket.create_connection

LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", ""}

# 環境変数でテストを制御
RUN_GUI_TESTS = os.getenv("RUN_GUI_TESTS", "0").lower() in ("1", "true", "yes")
RUN_NETWORK_TESTS = os.getenv("RUN_NETWORK_TESTS", "0").lower() in ("1", "true", "yes")
RUN_INTEGRATION_TESTS = os.getenv("RUN_INTEGRATION_TESTS", "0").lower() in ("1", "true", "yes")


def pytest_configure(config):
    """pytest設定"""
    # GUIテストのスキップ設定
    if not RUN_GUI_TESTS:
        config.addinivalue_line(
            "markers", "gui: GUI依存テスト（RUN_GUI_TESTS=1で有効化）"
        )
    
    # ネットワークテストのスキップ設定
    if not RUN_NETWORK_TESTS:
        config.addinivalue_line(
            "markers", "network: ネットワーク依存テスト（RUN_NETWORK_TESTS=1で有効化）"
        )
    
    # 統合テストのスキップ設定
    if not RUN_INTEGRATION_TESTS:
        config.addinivalue_line(
            "markers", "integration: 統合テスト（RUN_INTEGRATION_TESTS=1で有効化）"
        )


class SocketUseInTestError(RuntimeError):
    """network マーカーなしのテストが通信しようとした"""


def _is_loopback_host(host) -> bool:
    if host is None:
        return True
    text = str(host).strip().rstrip(".").casefold()
    if text in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _is_loopback_address(address) -> bool:
    if isinstance(address, tuple) and address:
        return _is_loopback_host(address[0])
    return True


def _install_socket_blocker():
    def blocked_getaddrinfo(host, port=None, family=0, type=0, proto=0, flags=0):
        if not _is_loopback_host(host):
            raise SocketUseInTestError(
                f"テスト中の名前解決は禁止です: {host}"
                "（実通信が必要なら @pytest.mark.network を付けてください）"
            )
        return _REAL_GETADDRINFO(host, port, family, type, proto, flags)

    def blocked_connect(self, address):
        if not _is_loopback_address(address):
            raise SocketUseInTestError(f"テスト中の接続は禁止です: {address}")
        return _REAL_CONNECT(self, address)

    def blocked_connect_ex(self, address):
        if not _is_loopback_address(address):
            raise SocketUseInTestError(f"テスト中の接続は禁止です: {address}")
        return _REAL_CONNECT_EX(self, address)

    def blocked_sendto(self, data, *args):
        address = args[-1] if args else None
        if address is not None and not _is_loopback_address(address):
            raise SocketUseInTestError(f"テスト中の送信は禁止です: {address}")
        return _REAL_SENDTO(self, data, *args)

    def blocked_create_connection(address, *args, **kwargs):
        if not _is_loopback_address(address):
            raise SocketUseInTestError(f"テスト中の接続は禁止です: {address}")
        return _REAL_CREATE_CONNECTION(address, *args, **kwargs)

    socket.getaddrinfo = blocked_getaddrinfo
    socket.socket.connect = blocked_connect
    socket.socket.connect_ex = blocked_connect_ex
    socket.socket.sendto = blocked_sendto
    socket.create_connection = blocked_create_connection


def _restore_real_socket():
    socket.getaddrinfo = _REAL_GETADDRINFO
    socket.socket.connect = _REAL_CONNECT
    socket.socket.connect_ex = _REAL_CONNECT_EX
    socket.socket.sendto = _REAL_SENDTO
    socket.create_connection = _REAL_CREATE_CONNECTION


@pytest.fixture(autouse=True)
def block_network(request):
    """通信を遮断し、エグレスガードの状態をテストごとに初期化する"""
    if "network" not in request.keywords:
        _install_socket_blocker()
    try:
        yield
    finally:
        # ガードを外してから素の関数に戻す（順序が逆だとガードのパッチが残る）
        netguard.uninstall_guard()
        _restore_real_socket()
        reset_shared_limiter()


@pytest.fixture
def real_create_connection():
    """素の socket.create_connection（ガード自体を検証するテスト用）"""
    return _REAL_CREATE_CONNECTION


@pytest.fixture
def temp_config_dir(tmp_path):
    """一時的な設定ディレクトリ"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def temp_log_dir(tmp_path):
    """一時的なログディレクトリ"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir
