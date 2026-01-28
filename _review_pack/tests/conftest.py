# -*- coding: utf-8 -*-

"""pytest設定とフィクスチャ"""

import pytest
import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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
