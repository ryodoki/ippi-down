# -*- coding: utf-8 -*-

"""robots.txt の遵守

ホストごとに robots.txt を1回だけ取得してキャッシュし、Disallow の URL は
取得しない。Crawl-delay / Request-rate はレート制限の下限として採用する。

取得は呼び出し側から渡される fetcher に委ねる（アプリの共有セッションと
エグレスガードを通すため、urllib による独自取得はしない）。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

# (status_code, body) を返す関数。取得できない場合は例外を投げてよい。
Fetcher = Callable[[str], Tuple[Optional[int], str]]


class _Entry:
    def __init__(self, parser: Optional[RobotFileParser], allow_all: bool, fetched_at: float):
        self.parser = parser
        self.allow_all = allow_all
        self.fetched_at = fetched_at


class RobotsPolicy:
    """robots.txt に基づく取得可否の判定"""

    def __init__(
        self,
        fetcher: Fetcher,
        enabled: bool = True,
        on_error: str = "block",
        cache_ttl_seconds: int = 86400,
        logger: Any = None,
        monotonic: Callable[[], float] = None,
    ) -> None:
        self.fetcher = fetcher
        self.enabled = bool(enabled)
        self.on_error = on_error if on_error in ("block", "allow") else "block"
        self.cache_ttl_seconds = int(cache_ttl_seconds)
        self.logger = logger
        self._monotonic = monotonic or time.monotonic
        self._cache: Dict[Tuple[str, str], _Entry] = {}
        self.fetch_count = 0

    @classmethod
    def from_config(cls, network_config: Any, fetcher: Fetcher, logger: Any = None) -> "RobotsPolicy":
        robots = getattr(network_config, "robots", None)
        return cls(
            fetcher=fetcher,
            enabled=getattr(robots, "enabled", True),
            on_error=getattr(robots, "on_error", "block"),
            cache_ttl_seconds=getattr(robots, "cache_ttl_seconds", 86400),
            logger=logger,
        )

    # ------------------------------------------------------------- 判定

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if not self.enabled:
            return True
        entry = self._entry_for(url)
        if entry.allow_all or entry.parser is None:
            return entry.allow_all
        return bool(entry.parser.can_fetch(user_agent, url))

    def crawl_delay(self, user_agent: str, url: str) -> Optional[float]:
        """Crawl-delay と Request-rate から導いた最小間隔（秒）"""
        if not self.enabled:
            return None
        entry = self._entry_for(url)
        if entry.parser is None:
            return None

        candidates = []
        try:
            delay = entry.parser.crawl_delay(user_agent)
            if delay is not None:
                candidates.append(float(delay))
        except (AttributeError, ValueError):
            pass
        try:
            rate = entry.parser.request_rate(user_agent)
            if rate is not None and rate.requests:
                candidates.append(float(rate.seconds) / float(rate.requests))
        except (AttributeError, ValueError, ZeroDivisionError):
            pass
        return max(candidates) if candidates else None

    def clear_cache(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------- 取得

    @staticmethod
    def robots_url_for(url: str) -> str:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))

    def _entry_for(self, url: str) -> _Entry:
        parsed = urlparse(url)
        key = (parsed.scheme.casefold(), parsed.netloc.casefold())
        cached = self._cache.get(key)
        if cached is not None and self._monotonic() - cached.fetched_at < self.cache_ttl_seconds:
            return cached
        entry = self._load(self.robots_url_for(url))
        self._cache[key] = entry
        return entry

    def _load(self, robots_url: str) -> _Entry:
        now = self._monotonic()
        self.fetch_count += 1
        try:
            status, body = self.fetcher(robots_url)
        except Exception as exc:
            return self._on_failure(robots_url, f"取得に失敗しました: {exc}", now)

        if status == 200:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse((body or "").splitlines())
            return _Entry(parser, allow_all=False, fetched_at=now)

        if status in (401, 403):
            # RFC 9309: アクセスできない robots.txt は全面禁止として扱う
            self._log(
                "warning",
                f"robots.txt へのアクセスが拒否されました（{status}）。全面的に取得を控えます: {robots_url}",
            )
            return _Entry(None, allow_all=False, fetched_at=now)

        if status is not None and 400 <= status < 500:
            # 404 など「robots.txt が無い」= 制限なし
            return _Entry(None, allow_all=True, fetched_at=now)

        return self._on_failure(robots_url, f"想定外のステータス: {status}", now)

    def _on_failure(self, robots_url: str, detail: str, now: float) -> _Entry:
        if self.on_error == "allow":
            self._log("warning", f"robots.txt を確認できませんでした（{detail}）。設定により続行します: {robots_url}")
            return _Entry(None, allow_all=True, fetched_at=now)
        self._log("warning", f"robots.txt を確認できませんでした（{detail}）。安全側で取得を中止します: {robots_url}")
        return _Entry(None, allow_all=False, fetched_at=now)

    def _log(self, level: str, message: str) -> None:
        if self.logger is None:
            return
        getattr(self.logger, level, None) and getattr(self.logger, level)(message)
