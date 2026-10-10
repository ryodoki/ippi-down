# -*- coding: utf-8 -*-

"""pytest設定とフィクスチャ"""

import pytest
import logging
import os
import socket
import sys
import tempfile
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 環境変数でテストを制御
RUN_GUI_TESTS = os.getenv("RUN_GUI_TESTS", "0").lower() in ("1", "true", "yes")
RUN_NETWORK_TESTS = os.getenv("RUN_NETWORK_TESTS", "0").lower() in ("1", "true", "yes")
RUN_INTEGRATION_TESTS = os.getenv("RUN_INTEGRATION_TESTS", "0").lower() in ("1", "true", "yes")
_TEST_LOG_TEMP = tempfile.TemporaryDirectory(prefix="ippi-down-pytest-logs-")
_TEST_LOG_DIR = Path(_TEST_LOG_TEMP.name)


def pytest_configure(config):
    """pytest設定"""
    # Logger()の既定出力をテスト専用一時フォルダーへ向け、本番の
    # logs/app.logへ疑似エラーやexample.testの記録を混入させない。
    import src.utils.logger as logger_module

    logger_module.get_logs_path = lambda name="app.log": _TEST_LOG_DIR / name
    # LoggingConfig.fileが明示されていても、Loggerが作る全ファイルを
    # pytest専用一時領域へ隔離する。アプリ本体のresolve_app_pathは
    # 変更しないため、保存先などのパステストには影響しない。
    def test_log_resolver(path):
        return _TEST_LOG_DIR / Path(path).name
    logger_module.resolve_app_path = test_log_resolver
    import src.utils.logger_factory as logger_factory_module

    logger_factory_module.resolve_app_path = test_log_resolver
    import src.utils.network_audit as network_audit_module

    network_audit_module.get_logs_path = (
        lambda name="network-audit.jsonl": _TEST_LOG_DIR / name
    )
    config.addinivalue_line(
        "markers", "gui: GUI依存テスト（RUN_GUI_TESTS=1で有効化）"
    )
    config.addinivalue_line(
        "markers", "network: ネットワーク依存テスト（RUN_NETWORK_TESTS=1で有効化）"
    )
    config.addinivalue_line(
        "markers", "integration: 統合テスト（RUN_INTEGRATION_TESTS=1で有効化）"
    )


def pytest_collection_modifyitems(config, items):
    """環境変数が有効なカテゴリだけを収集対象として実行する。"""
    del config
    disabled = []
    if not RUN_GUI_TESTS:
        disabled.append(("gui", "RUN_GUI_TESTS=1で有効化"))
    if not RUN_NETWORK_TESTS:
        disabled.append(("network", "RUN_NETWORK_TESTS=1で有効化"))
    if not RUN_INTEGRATION_TESTS:
        disabled.append(("integration", "RUN_INTEGRATION_TESTS=1で有効化"))

    for marker_name, reason in disabled:
        skip_marker = pytest.mark.skip(reason=reason)
        for item in items:
            if marker_name in item.keywords:
                item.add_marker(skip_marker)


def pytest_unconfigure(config):
    """テストログのハンドラーを閉じて一時フォルダーを削除する。"""
    del config
    logging.shutdown()
    _TEST_LOG_TEMP.cleanup()


@pytest.fixture(autouse=True)
def block_unexpected_network(request, monkeypatch):
    """標準テストからの実socket・DNS通信をfail-closedで禁止する。

    実サイトを使うテストは ``network`` markerと
    ``RUN_NETWORK_TESTS=1`` の両方が明示された場合だけ解除する。
    HTTPの正常系・異常系はrecording transportまたはmockで検証する。
    """

    if request.node.get_closest_marker("network") is not None:
        if RUN_NETWORK_TESTS:
            return

    def blocked(*_args, **_kwargs):
        raise AssertionError(
            "標準pytest中の実ネットワーク通信は禁止されています。"
            "実通信テストにはnetwork markerを付け、専用jobで実行してください"
        )

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


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
