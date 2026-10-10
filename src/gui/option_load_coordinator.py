# -*- coding: utf-8 -*-

"""検索条件候補を有限個のワーカーで取得するための調停器。"""

from __future__ import annotations

import logging
from threading import Condition, Thread
from typing import Callable, Optional


class OptionLoadCoordinator:
    """キー単位で古い未開始要求を置換する単一ワーカー。"""

    USER_PRIORITY = 0
    PREFETCH_PRIORITY = 10
    MAX_PENDING = 64

    def __init__(self, *, name: str = "ippi-option-loader") -> None:
        self._condition = Condition()
        self._tasks: dict[
            str,
            tuple[
                int,
                int,
                Callable[[], None],
                Optional[Callable[[], None]],
            ],
        ] = {}
        self._sequence = 0
        self._stopped = False
        self._active = False
        self._thread = Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(
        self,
        key: str,
        callback: Callable[[], None],
        *,
        priority: int = USER_PRIORITY,
        on_discard: Optional[Callable[[], None]] = None,
    ) -> bool:
        """未開始の同一キー要求を最新callbackで置き換える。"""
        discarded = None
        with self._condition:
            if self._stopped:
                return False
            task_key = str(key)
            previous = self._tasks.get(task_key)
            if previous is not None:
                discarded = previous[3]
            elif len(self._tasks) >= self.MAX_PENDING:
                worst_key, worst = max(
                    self._tasks.items(),
                    # 数値が大きいほど低優先度。同順位では古い要求を捨てる。
                    key=lambda item: (item[1][0], -item[1][1]),
                )
                if int(priority) > worst[0]:
                    return False
                discarded = worst[3]
                self._tasks.pop(worst_key, None)
            self._sequence += 1
            self._tasks[task_key] = (
                int(priority),
                self._sequence,
                callback,
                on_discard,
            )
            self._condition.notify()
        if discarded is not None:
            discarded()
        return True

    def cancel(self, key: str) -> bool:
        """指定キーの未開始要求を破棄する。実行中callbackは呼出側で取消す。"""

        discarded = None
        with self._condition:
            task = self._tasks.pop(str(key), None)
            if task is not None:
                discarded = task[3]
        if discarded is not None:
            discarded()
        return task is not None

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stopped or bool(self._tasks)
                )
                if self._stopped and not self._tasks:
                    return
                key, (_priority, _sequence, callback, _on_discard) = min(
                    self._tasks.items(),
                    key=lambda item: (item[1][0], item[1][1]),
                )
                self._tasks.pop(key, None)
                self._active = True
            try:
                callback()
            except Exception:
                # 個別callbackの失敗で共有ワーカーを失わない。通常の
                # callbackは自身で日本語エラーをGUIへ通知する。
                logging.getLogger("ppi_file_downloader").exception(
                    "検索候補ワーカーで未処理例外が発生しました"
                )
            finally:
                with self._condition:
                    self._active = False
                    self._condition.notify_all()

    def stop(self, *, cancel_pending: bool = True) -> None:
        """新規受付を止め、必要なら未開始要求を破棄する。"""
        discarded: list[Callable[[], None]] = []
        with self._condition:
            self._stopped = True
            if cancel_pending:
                discarded = [
                    task[3] for task in self._tasks.values() if task[3] is not None
                ]
                self._tasks.clear()
            self._condition.notify_all()
        for callback in discarded:
            callback()

    @property
    def is_idle(self) -> bool:
        with self._condition:
            return not self._active and not self._tasks

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._tasks)

    def join(self, timeout: float | None = None) -> None:
        """終了要求後のワーカー完了を待つ（主に終了処理・テスト用）。"""
        self._thread.join(timeout)


__all__ = ["OptionLoadCoordinator"]
