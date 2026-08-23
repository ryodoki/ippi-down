# -*- coding: utf-8 -*-

"""ホスト単位のレート制限（相手サイトへの負荷を抑えるための作法）

- 同一ホストへの連続アクセスに最小間隔を空ける（±ジッタ付き）
- 同一ホストへの同時接続数を制限する
- 1回の実行で送るリクエスト総数に上限を設ける
- 稼働時間帯を制限できる
- 429 を受けたら以後の最小間隔を倍にする

時刻とスリープは差し替え可能にしてあるため、テストは実時間を待たずに検証できる。
"""

from __future__ import annotations

import random
import threading
from datetime import datetime, time as dt_time
from typing import Any, Callable, Dict, Optional

from ..app.exceptions import OutsideAllowedHoursError, RequestBudgetExceededError

MAX_INTERVAL_SECONDS = 60.0


def parse_allowed_hours(value: Optional[str]):
    """"HH:MM-HH:MM" を (開始, 終了) の time に変換する。未指定なら None。"""
    if not value:
        return None
    try:
        start_text, end_text = str(value).split("-", 1)
        start_hour, start_minute = (int(part) for part in start_text.strip().split(":", 1))
        end_hour, end_minute = (int(part) for part in end_text.strip().split(":", 1))
        return dt_time(start_hour, start_minute), dt_time(end_hour, end_minute)
    except (TypeError, ValueError):
        raise ValueError(f"allowed_hours は HH:MM-HH:MM 形式で指定してください: {value}")


def is_within_allowed_hours(window, now: dt_time) -> bool:
    if window is None:
        return True
    start, end = window
    if start <= end:
        return start <= now <= end
    # 日をまたぐ指定（例 22:00-06:00）
    return now >= start or now <= end


class RateLimiter:
    """ホスト単位のトークンバケット（間隔＋同時接続＋総量制限）"""

    def __init__(
        self,
        min_interval_seconds: float = 1.0,
        max_concurrency: int = 1,
        max_requests_per_run: int = 500,
        allowed_hours: Optional[str] = None,
        jitter_ratio: float = 0.2,
        logger: Any = None,
        monotonic: Callable[[], float] = None,
        sleep: Callable[[float], None] = None,
        jitter: Callable[[float, float], float] = None,
        now: Callable[[], datetime] = None,
    ) -> None:
        import time as _time

        self.default_min_interval = max(0.0, float(min_interval_seconds))
        self.max_concurrency = max(1, int(max_concurrency))
        self.max_requests_per_run = max(1, int(max_requests_per_run))
        self.allowed_hours = parse_allowed_hours(allowed_hours)
        self.jitter_ratio = max(0.0, float(jitter_ratio))
        self.logger = logger

        self._monotonic = monotonic or _time.monotonic
        self._sleep = sleep or _time.sleep
        self._jitter = jitter or random.uniform
        self._now = now or datetime.now

        self._lock = threading.Lock()
        self._intervals: Dict[str, float] = {}
        self._last_request: Dict[str, float] = {}
        self._semaphores: Dict[str, threading.Semaphore] = {}
        self._waits: Dict[str, float] = {}
        self.request_count = 0

    # ------------------------------------------------------------- 設定

    def min_interval_for(self, host: str) -> float:
        with self._lock:
            return self._intervals.get(host, self.default_min_interval)

    def set_min_interval(self, host: str, seconds: float) -> float:
        """ホストごとの最小間隔を引き上げる（robots の Crawl-delay 用。下げはしない）"""
        with self._lock:
            current = self._intervals.get(host, self.default_min_interval)
            updated = min(MAX_INTERVAL_SECONDS, max(current, float(seconds)))
            self._intervals[host] = updated
            return updated

    def note_rate_limited(self, host: str) -> float:
        """429 を受けたホストの最小間隔を倍にする"""
        with self._lock:
            current = self._intervals.get(host, self.default_min_interval) or 1.0
            updated = min(MAX_INTERVAL_SECONDS, current * 2)
            self._intervals[host] = updated
        if self.logger:
            self.logger.warning(
                f"レート制限を受けたため最小間隔を {updated:.1f} 秒に延長します: {host}"
            )
        return updated

    def last_wait_for(self, host: str) -> float:
        """直近の acquire で実際に待った秒数（テスト・監査用）"""
        with self._lock:
            return self._waits.get(host, 0.0)

    # ------------------------------------------------------------- 取得

    def _semaphore(self, host: str) -> threading.Semaphore:
        with self._lock:
            semaphore = self._semaphores.get(host)
            if semaphore is None:
                semaphore = threading.Semaphore(self.max_concurrency)
                self._semaphores[host] = semaphore
            return semaphore

    def acquire(self, host: str) -> float:
        """送信枠を確保する。必要なら最小間隔まで待つ。待った秒数を返す。"""
        if not is_within_allowed_hours(self.allowed_hours, self._now().time()):
            raise OutsideAllowedHoursError(
                "稼働を許可された時間帯の外側です。network.allowed_hours を確認してください"
            )

        with self._lock:
            if self.request_count >= self.max_requests_per_run:
                raise RequestBudgetExceededError(
                    f"1回の実行のリクエスト上限（{self.max_requests_per_run}件）に達しました"
                )

        self._semaphore(host).acquire()
        try:
            waited = self._wait_for_slot(host)
        except BaseException:
            self._semaphore(host).release()
            raise

        with self._lock:
            self.request_count += 1
            self._last_request[host] = self._monotonic()
            self._waits[host] = waited
        return waited

    def _wait_for_slot(self, host: str) -> float:
        with self._lock:
            interval = self._intervals.get(host, self.default_min_interval)
            last = self._last_request.get(host)
        if interval <= 0:
            return 0.0

        target = interval
        if self.jitter_ratio:
            span = interval * self.jitter_ratio
            target = max(0.0, interval + self._jitter(-span, span))

        if last is None:
            return 0.0
        elapsed = self._monotonic() - last
        remaining = target - elapsed
        if remaining <= 0:
            return 0.0
        self._sleep(remaining)
        return remaining

    def release(self, host: str) -> None:
        self._semaphore(host).release()

    def reset(self) -> None:
        """実行単位のカウンタを初期化する"""
        with self._lock:
            self.request_count = 0
            self._last_request.clear()
            self._waits.clear()

    def tighten_from_config(self, network_config: Any) -> None:
        """既存の制限を、より厳しい方向にのみ合わせる"""
        with self._lock:
            self.default_min_interval = max(
                self.default_min_interval,
                float(getattr(network_config, "min_interval_seconds", 0.0)),
            )
            self.max_concurrency = min(
                self.max_concurrency, max(1, int(getattr(network_config, "max_concurrency", 1)))
            )
            self.max_requests_per_run = min(
                self.max_requests_per_run,
                max(1, int(getattr(network_config, "max_requests_per_run", 500))),
            )

    @classmethod
    def from_config(cls, network_config: Any, logger: Any = None) -> "RateLimiter":
        return cls(
            min_interval_seconds=getattr(network_config, "min_interval_seconds", 1.0),
            max_concurrency=getattr(network_config, "max_concurrency", 1),
            max_requests_per_run=getattr(network_config, "max_requests_per_run", 500),
            allowed_hours=getattr(network_config, "allowed_hours", None),
            logger=logger,
        )


_shared: Optional[RateLimiter] = None
_shared_lock = threading.Lock()


def get_shared_limiter(network_config: Any, logger: Any = None) -> RateLimiter:
    """プロセス全体で共有するレート制限

    GUI のドロップダウン読み込みスレッドと本処理はそれぞれ HTTPClient を持つため、
    共有しないと同一ホストへ同時にアクセスしてしまう。制限は厳しい方向にのみ合わせる。
    """
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = RateLimiter.from_config(network_config, logger=logger)
        else:
            _shared.tighten_from_config(network_config)
        return _shared


def reset_shared_limiter() -> None:
    """共有インスタンスを破棄する（テストと実行の区切り用）"""
    global _shared
    with _shared_lock:
        _shared = None
