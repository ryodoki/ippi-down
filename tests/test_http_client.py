# -*- coding: utf-8 -*-

"""HTTPClientのテスト"""

import pytest
import requests
from unittest.mock import Mock

from src.app.exceptions import NetworkError
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
        assert http_client.download_timeout == 30

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
        http_client.session.close = Mock()
        http_client.close()
        http_client.session.close.assert_called_once_with()

    @pytest.mark.parametrize("status_code", [501, 599])
    def test_request_retries_every_5xx(
        self,
        http_client,
        status_code,
    ):
        """通常リクエストも未知の5xxを再試行する。"""
        retry_response = Mock(status_code=status_code, headers={})
        success_response = Mock(status_code=200, headers={})
        http_client.session.request = Mock(
            side_effect=[retry_response, success_response]
        )
        http_client._throttle = Mock()
        http_client._wait = Mock(return_value=True)

        result = http_client._request(
            "GET",
            "https://example.test/resource",
            max_retries=3,
        )

        assert result is success_response
        assert http_client.session.request.call_count == 2
        retry_response.close.assert_called_once_with()
        http_client._wait.assert_called_once_with(1.0, None)

    def test_request_does_not_retry_4xx(self, http_client):
        """通常リクエストの4xxは決定的エラーとして扱う。"""
        response = Mock(status_code=404, headers={})
        error = requests.HTTPError("HTTP 404", response=response)
        response.raise_for_status.side_effect = error
        http_client.session.request = Mock(return_value=response)
        http_client._throttle = Mock()
        http_client._wait = Mock(return_value=True)

        with pytest.raises(NetworkError):
            http_client._request(
                "GET",
                "https://example.test/missing",
                max_retries=3,
            )

        http_client.session.request.assert_called_once()
        response.close.assert_called_once_with()
        http_client._wait.assert_not_called()

    @pytest.mark.parametrize(
        "request_error",
        [
            requests.exceptions.InvalidURL("invalid URL"),
            requests.exceptions.InvalidSchema("invalid schema"),
            requests.exceptions.TooManyRedirects("redirect loop"),
        ],
    )
    def test_request_does_not_retry_deterministic_errors(
        self,
        http_client,
        request_error,
    ):
        """URLやリダイレクトの決定的エラーは初回で終了する。"""
        http_client.session.request = Mock(side_effect=request_error)
        http_client._throttle = Mock()
        http_client._wait = Mock(return_value=True)

        with pytest.raises(NetworkError):
            http_client._request(
                "GET",
                "https://example.test/resource",
                max_retries=3,
            )

        http_client.session.request.assert_called_once()
        http_client._wait.assert_not_called()

    @pytest.mark.parametrize(
        "request_error",
        [
            requests.exceptions.Timeout("timed out"),
            requests.exceptions.ConnectionError("connection reset"),
            requests.exceptions.ChunkedEncodingError("incomplete response"),
        ],
    )
    def test_request_retries_only_transient_transport_errors(
        self,
        http_client,
        request_error,
    ):
        """一時的な通信例外は正常応答まで再試行する。"""
        success_response = Mock(status_code=200, headers={})
        http_client.session.request = Mock(
            side_effect=[request_error, success_response]
        )
        http_client._throttle = Mock()
        http_client._wait = Mock(return_value=True)

        result = http_client._request(
            "GET",
            "https://example.test/resource",
            max_retries=3,
        )

        assert result is success_response
        assert http_client.session.request.call_count == 2
        http_client._wait.assert_called_once_with(1.0, None)
