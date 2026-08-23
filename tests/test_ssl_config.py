# -*- coding: utf-8 -*-

"""SSL 設定とエラーメッセージのテスト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.ssl_config import configure_ssl, ssl_error_hint


def test_configure_ssl_idempotent():
    """configure_ssl は複数回呼んでも例外にならない"""
    configure_ssl()
    configure_ssl()


def test_ssl_error_hint_detects_certificate_failure():
    """証明書検証エラー時にヒントを返す"""
    msg = ssl_error_hint(
        "certificate verify failed: unable to get local issuer certificate"
    )
    assert msg is not None
    assert "SSL" in msg


def test_ssl_error_hint_ignores_other_errors():
    """非 SSL エラーでは None"""
    assert ssl_error_hint("connection timed out") is None
