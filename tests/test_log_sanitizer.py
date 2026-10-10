# -*- coding: utf-8 -*-

"""診断ログの秘密情報マスキングを検証する。"""

from __future__ import annotations

import logging

from src.utils.log_sanitizer import RedactingFormatter, sanitize_log_text


def test_log_sanitizer_keeps_endpoint_but_removes_query_values_and_userinfo():
    message = (
        "GET https://user:secret@e2ppiw01.e-bisc.go.jp/"
        "CALS/Publish/KokaiBunshoServlet?AnkenKanriNo=123&BunshoKanriId=40"
    )

    sanitized = sanitize_log_text(message)

    assert "e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet" in sanitized
    assert "AnkenKanriNo=<redacted>" in sanitized
    assert "BunshoKanriId=<redacted>" in sanitized
    assert "user" not in sanitized
    assert "secret" not in sanitized
    assert "123" not in sanitized


def test_log_sanitizer_removes_sensitive_headers_and_bearer_tokens():
    sanitized = sanitize_log_text(
        "Authorization: Bearer abcdefghijklmnop\n"
        "Cookie: session=secret\nProxy-Authorization: Basic abcdefgh"
    )

    assert "abcdefghijklmnop" not in sanitized
    assert "session=secret" not in sanitized
    assert "Basic abcdefgh" not in sanitized
    assert sanitized.count("<redacted>") == 3


def test_redacting_formatter_sanitizes_exception_traceback():
    formatter = RedactingFormatter("%(levelname)s %(message)s")
    try:
        raise RuntimeError("https://example.test/path?token=very-secret")
    except RuntimeError:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "request failed",
            (),
            exc_info=__import__("sys").exc_info(),
        )

    output = formatter.format(record)

    assert "very-secret" not in output
    assert "token=<redacted>" in output
