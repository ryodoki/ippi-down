"""HTTPClientのテスト"""

import pytest
from pathlib import Path
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient
from src.utils.logger import Logger
from src.models.config_model import LoggingConfig


class TestHTTPClient:
    """HTTPClientのテストクラス"""

    @pytest.fixture
    def logger(self):
        """ロガーのフィクスチャ"""
        return Logger(LoggingConfig(level="INFO"))

    @pytest.fixture
    def http_client(self, logger):
        """HTTPClientのフィクスチャ"""
        return HTTPClient(logger)

    def test_http_client_initialization(self, http_client):
        """HTTPClientの初期化テスト"""
        assert http_client is not None
        assert http_client.session is not None
        assert "User-Agent" in http_client.session.headers

    def test_user_agent(self, http_client):
        """User-Agentの確認"""
        user_agent = http_client.session.headers.get("User-Agent", "")
        assert "Mozilla" in user_agent
        assert "Chrome" in user_agent

    def test_timeout_settings(self, logger):
        """タイムアウト設定のテスト"""
        client = HTTPClient(logger, timeout=60, download_timeout=120)
        assert client.timeout == 60
        assert client.download_timeout == 120

    def test_close(self, http_client):
        """セッションクローズのテスト"""
        http_client.close()
        # クローズ後もセッションオブジェクトは存在するが、使用できない状態になる
        assert http_client.session is not None

