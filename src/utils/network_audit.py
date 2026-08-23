# -*- coding: utf-8 -*-

"""外向き通信の監査ログ（TSV 1行 = 1判定）

列: 時刻 / 判定 / メソッド / 宛先 / ステータス / バイト数 / 所要ms / 詳細

判定は allow（送信した） / blocked（ポリシー違反で中止） /
robots_denied（robots.txt により中止） / rate_limited（相手から 429）の4種。
エグレスガードと HTTP クライアントの両方が同じ形式で書くため、1つのファイルを
時系列に読めば「いつ・どこへ・何をしたか」を後から説明できる。
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

COLUMNS = ("timestamp", "event", "method", "target", "status", "bytes", "elapsed_ms", "detail")

EVENT_ALLOW = "allow"
EVENT_BLOCKED = "blocked"
EVENT_ROBOTS_DENIED = "robots_denied"
EVENT_RATE_LIMITED = "rate_limited"


class NetworkAuditLog:
    """監査ログの追記書き込み（書き込み失敗で本体を止めない）"""

    def __init__(self, path: Optional[Any] = None, logger: Any = None) -> None:
        self.path = Path(path) if path else None
        self.logger = logger
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def write(
        self,
        event: str,
        target: str,
        method: str = "-",
        status: Optional[int] = None,
        size: Optional[int] = None,
        elapsed_ms: Optional[float] = None,
        detail: str = "",
    ) -> None:
        if self.path is None:
            return
        row = [
            datetime.now().isoformat(timespec="seconds"),
            event,
            method or "-",
            str(target),
            "-" if status is None else str(status),
            "-" if size is None else str(size),
            "-" if elapsed_ms is None else f"{elapsed_ms:.0f}",
            (detail or "").replace("\t", " ").replace("\n", " "),
        ]
        line = "\t".join(row) + "\n"
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except OSError as exc:
            if self.logger is not None:
                self.logger.debug(f"監査ログに書き込めません ({self.path}): {exc}")
