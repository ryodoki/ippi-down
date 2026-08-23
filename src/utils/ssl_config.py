# -*- coding: utf-8 -*-

"""SSL/TLS 証明書検証の設定（Windows 証明書ストア対応）"""

import sys
from typing import Optional

_configured = False


def configure_ssl() -> bool:
    """OS の信頼済み証明書ストアを Python に適用する。

    Norton 等の SSL 検査（中間者証明書）環境では、certifi のみでは
    接続に失敗する。Windows では truststore で OS ストアを利用する。

    Returns:
        truststore を適用した場合 True、未適用の場合 False
    """
    global _configured
    if _configured:
        return True

    if sys.platform == "win32":
        try:
            import truststore  # type: ignore[import-untyped]

            truststore.inject_into_ssl()
            _configured = True
            return True
        except ImportError:
            pass

    _configured = True
    return False


def ssl_error_hint(error_message: str) -> Optional[str]:
    """SSL 検証エラー時のユーザー向けヒントを返す。"""
    lowered = error_message.lower()
    if "certificate verify failed" not in lowered and "ssl" not in lowered:
        return None

    hints = [
        "SSL証明書の検証に失敗しました。",
        "Norton 等のウイルス対策ソフトの「SSL/TLS 検査」が有効な場合、",
        "Python はブラウザと異なる証明書ストアを使うため接続できないことがあります。",
        "対処: truststore をインストール済みか確認するか、",
        "ウイルス対策の SSL 検査を一時的に無効化してください。",
    ]
    return " ".join(hints)
