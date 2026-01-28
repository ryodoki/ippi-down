"""GUIイベントハンドラー（スレッドセーフ）"""

import queue
import tkinter as tk
from typing import Optional
from ..app.events import ProgressEvent, EventType


class EventHandler:
    """スレッドセーフなイベントハンドラー"""

    def __init__(self, root: tk.Tk, main_window):
        """初期化"""
        self.root = root
        self.main_window = main_window
        self.event_queue: queue.Queue = queue.Queue()
        self._poll_interval = 100  # ミリ秒

    def start_polling(self):
        """イベントポーリングを開始"""
        self._poll_events()

    def _poll_events(self):
        """イベントキューをポーリングしてUIを更新"""
        try:
            while True:
                event: ProgressEvent = self.event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        finally:
            # 次のポーリングをスケジュール
            self.root.after(self._poll_interval, self._poll_events)

    def _handle_event(self, event: ProgressEvent):
        """イベントを処理"""
        if event.type == EventType.START:
            self.main_window.update_progress(0, event.total, "開始")
            if event.message:
                self.main_window.show_message(event.message, "info")

        elif event.type == EventType.PROGRESS:
            self.main_window.update_progress(
                event.current, event.total, event.filename or ""
            )
            if event.message:
                self.main_window.show_message(event.message, "info")

        elif event.type == EventType.SUCCESS:
            if event.message:
                self.main_window.show_message(event.message, "info")

        elif event.type == EventType.FAIL:
            error_msg = event.error or event.message or "エラーが発生しました"
            self.main_window.show_message(error_msg, "error")

        elif event.type == EventType.SKIP:
            if event.message:
                self.main_window.show_message(event.message, "warning")

        elif event.type == EventType.MESSAGE:
            msg_type = event.metadata.get("type", "info") if event.metadata else "info"
            self.main_window.show_message(event.message, msg_type)

        elif event.type == EventType.COMPLETE:
            self.main_window.update_progress(event.total, event.total, "完了")
            if event.message:
                self.main_window.show_message(event.message, "info")

    def emit(self, event: ProgressEvent):
        """イベントを発行（スレッドセーフ）"""
        self.event_queue.put(event)
