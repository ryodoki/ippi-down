# -*- coding: utf-8 -*-

"""診断ログから通信・認証情報を除去する。"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit, urlunsplit


_URL_PATTERN = re.compile(r"https?://[^\s\]\[\)\(\}\{\"'<>]+", re.IGNORECASE)
_SENSITIVE_HEADER_PATTERN = re.compile(
    r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)"
    r"\s*:\s*[^\r\n]+"
)
_BEARER_PATTERN = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
)


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,;:":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "<redacted-url>" + trailing

    hostname = parsed.hostname or ""
    if not hostname:
        return "<redacted-url>" + trailing
    try:
        port = parsed.port
    except ValueError:
        return "<redacted-url>" + trailing
    netloc = hostname
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]"
    if port is not None:
        netloc = f"{netloc}:{port}"

    query_keys: list[str] = []
    for item in parsed.query.split("&"):
        key = item.split("=", 1)[0].strip()
        if key and key not in query_keys:
            query_keys.append(key)
    redacted_query = "&".join(f"{key}=<redacted>" for key in query_keys)
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path, redacted_query, "")
    ) + trailing


def sanitize_log_text(value: object) -> str:
    """秘密値を残さず、通信先host/pathとquery名だけを保持する。"""

    text = str(value)
    text = _SENSITIVE_HEADER_PATTERN.sub(
        lambda match: f"{match.group(1)}: <redacted>", text
    )
    text = _BEARER_PATTERN.sub("Bearer <redacted>", text)
    return _URL_PATTERN.sub(_redact_url, text)


class RedactingFormatter(logging.Formatter):
    """tracebackを含む完成済みログ行へ共通マスキングを適用する。"""

    def format(self, record: logging.LogRecord) -> str:
        return sanitize_log_text(super().format(record))
