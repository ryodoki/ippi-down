# -*- coding: utf-8 -*-

"""GUIイベントハンドラー（スレッドセーフ）"""

import queue
import tkinter as tk
from dataclasses import dataclass
from dataclasses import replace
from threading import Lock
from typing import Any, Callable
from ..app.events import ProgressEvent, EventType
from ..models.download_result import RunOutcome


@dataclass
class _UiCall:
    """GUIスレッドで実行する処理。"""

    callback: Callable[..., Any]
    args: tuple
    kwargs: dict


class EventHandler:
    """スレッドセーフなイベントハンドラー"""

    _MAX_QUEUED_EVENTS = 512
    _TERMINAL_TYPES = frozenset({EventType.FAIL, EventType.COMPLETE})

    def __init__(self, root: tk.Tk, main_window):
        """初期化"""
        self.root = root
        self.main_window = main_window
        # 通常イベントは必ず上限を持たせる。検索進捗は別スロットで最新値と
        # 案件差分を統合し、GUIが一時停止しても世代ごとの全件コピーを
        # キューへ積み続けない。
        self.event_queue: queue.Queue = queue.Queue(
            maxsize=self._MAX_QUEUED_EVENTS
        )
        # 無制限queueは終了イベント専用にする。通常のUI callbackを
        # fallback投入してGUI停滞中に増え続けないようにする。
        self._terminal_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._pending_lock = Lock()
        self._pending_search_event: ProgressEvent | None = None
        self._pending_search_projects: Any = None
        self._pending_search_deltas: dict[str, Any] = {}
        self._pending_generation: Any = None
        self._after_id: Any = None
        self._running = False
        self._stopped = False
        # 終了イベントを処理した後に、通常キューへ残っていた古い進捗が
        # 完了表示を上書きしないようにする。次のSTARTで解除する。
        self._terminal_seen = False
        self.dropped_events = 0
        self._poll_interval = 100  # ミリ秒
        self._max_events_per_poll = 100

    def start_polling(self):
        """イベントポーリングを開始"""
        if self._running or self._stopped:
            return
        self._running = True
        self._poll_events()

    def _poll_events(self):
        """イベントキューをポーリングしてUIを更新"""
        if self._stopped:
            return
        try:
            for _ in range(self._max_events_per_poll):
                item = self._next_item()
                if item is None:
                    break
                if isinstance(item, _UiCall):
                    item.callback(*item.args, **item.kwargs)
                else:
                    self._handle_event(item)
        finally:
            if not self._stopped:
                # 次のポーリングをスケジュール
                self._after_id = self.root.after(
                    self._poll_interval, self._poll_events
                )

    def _next_item(self) -> Any:
        """優先イベント、通常イベント、統合済み検索進捗の順に得る。"""
        try:
            return self._terminal_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            return self.event_queue.get_nowait()
        except queue.Empty:
            return self._take_search_progress()

    @staticmethod
    def _is_search_progress(event: Any) -> bool:
        return bool(
            isinstance(event, ProgressEvent)
            and event.type == EventType.PROGRESS
            and event.metadata
            and event.metadata.get("phase") == "search"
        )

    @staticmethod
    def _project_delta_key(project: Any, fallback: int) -> str:
        if isinstance(project, dict):
            for name in ("project_id", "anken_kanri_no", "anken_id", "id"):
                value = project.get(name)
                if value not in (None, ""):
                    return str(value)
        return f"__delta_{fallback}"

    def _coalesce_search_progress(self, event: ProgressEvent) -> None:
        metadata = dict(event.metadata or {})
        generation = metadata.get("generation", 0)
        with self._pending_lock:
            if (
                self._pending_search_event is not None
                and generation != self._pending_generation
            ):
                # 新しい検索世代を受けたら、前世代の未表示データを捨てる。
                self._pending_search_projects = None
                self._pending_search_deltas.clear()
            self._pending_generation = generation
            projects = metadata.get("projects")
            snapshot_kind = str(metadata.get("snapshot_kind", "")).lower()
            if projects is not None and snapshot_kind in {
                "page",
                "final",
                "full",
            }:
                self._pending_search_projects = projects
                self._pending_search_deltas.clear()
            deltas = metadata.get("project_deltas")
            if deltas is None:
                delta = metadata.get("project_delta")
                deltas = () if delta is None else (delta,)
            for delta in deltas:
                key = self._project_delta_key(
                    delta, len(self._pending_search_deltas)
                )
                self._pending_search_deltas[key] = delta
            self._pending_search_event = replace(event, metadata=metadata)

    def _take_search_progress(self) -> ProgressEvent | None:
        with self._pending_lock:
            event = self._pending_search_event
            if event is None:
                return None
            metadata = dict(event.metadata or {})
            if self._pending_search_projects is not None:
                metadata["projects"] = self._pending_search_projects
            if self._pending_search_deltas:
                metadata["project_deltas"] = list(
                    self._pending_search_deltas.values()
                )
            self._pending_search_event = None
            self._pending_search_projects = None
            self._pending_search_deltas.clear()
            self._pending_generation = None
        return replace(event, metadata=metadata)

    def _handle_event(self, event: ProgressEvent):
        """イベントを処理"""
        if event.type == EventType.START:
            self._terminal_seen = False
            self.main_window.update_progress(0, event.total, "開始")
            if event.message:
                self.main_window.show_message(event.message, "info")

        elif event.type == EventType.PROGRESS:
            if self._terminal_seen:
                # COMPLETE/FAILは通常イベントより優先して配送される。
                # その時点で通常キューに残っていた旧進捗は、次回実行の
                # STARTまでは終端表示を上書きさせない。
                return
            phase = (
                event.metadata.get("phase")
                if event.metadata
                else None
            )
            if phase == "search":
                self.main_window.update_search_progress(event.metadata)
            else:
                self.main_window.update_progress(
                    event.current, event.total, event.filename or ""
                )
            if event.message:
                self.main_window.show_message(event.message, "info")

        elif event.type == EventType.SUCCESS:
            if event.message:
                self.main_window.show_message(event.message, "info")

        elif event.type == EventType.FAIL:
            self._terminal_seen = True
            outcome = self._get_event_outcome(
                event, RunOutcome.FAILED
            )
            self.main_window.set_run_outcome(
                outcome, event.current, event.total
            )
            error_msg = event.error or event.message or "エラーが発生しました"
            self.main_window.show_message(error_msg, "error")

        elif event.type == EventType.SKIP:
            if event.message:
                self.main_window.show_message(event.message, "warning")

        elif event.type == EventType.MESSAGE:
            msg_type = event.metadata.get("type", "info") if event.metadata else "info"
            self.main_window.show_message(event.message, msg_type)

        elif event.type == EventType.COMPLETE:
            self._terminal_seen = True
            outcome = self._get_event_outcome(
                event, RunOutcome.SUCCESS
            )
            all_reused = bool(
                event.metadata
                and event.metadata.get("all_reused")
            )
            if all_reused:
                self.main_window.set_run_outcome(
                    outcome,
                    event.current,
                    event.total,
                    all_reused=True,
                )
            else:
                self.main_window.set_run_outcome(
                    outcome, event.current, event.total
                )
            if event.message:
                msg_type = (
                    event.metadata.get("type", "info")
                    if event.metadata
                    else "info"
                )
                self.main_window.show_message(event.message, msg_type)

    @staticmethod
    def _get_event_outcome(
        event: ProgressEvent, fallback: RunOutcome
    ) -> RunOutcome:
        """イベントmetadataの終了状態を安全に復元する。"""
        raw_outcome = (
            event.metadata.get("outcome")
            if event.metadata
            else None
        )
        try:
            return RunOutcome(raw_outcome) if raw_outcome else fallback
        except ValueError:
            return fallback

    def emit(self, event: ProgressEvent):
        """イベントを発行（スレッドセーフ）"""
        if self._stopped:
            return False
        if self._is_search_progress(event):
            self._coalesce_search_progress(event)
            return True
        if event.type in self._TERMINAL_TYPES:
            # 検索進捗は専用スロットに統合されるため、通常の優先順では
            # COMPLETEが先に処理されて最終検索表示が成功表示を上書きする。
            # 保留分を同じ優先キューへ先に移し、検索→終端の順を保証する。
            pending_search = self._take_search_progress()
            if pending_search is not None:
                self._terminal_queue.put(pending_search)
            self._terminal_queue.put(event)
            return True
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            # 通常進捗は古いものから破棄し、最新表示へ追いつかせる。
            try:
                self.event_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.event_queue.put_nowait(event)
            except queue.Full:
                self.dropped_events += 1
                return False
            self.dropped_events += 1
        return True

    def call_soon(self, callback: Callable[..., Any], *args, **kwargs):
        """任意の処理をTkメインスレッドのポーリング処理へ渡す。"""
        if self._stopped:
            return False
        call = _UiCall(callback, args, kwargs)
        try:
            self.event_queue.put_nowait(call)
        except queue.Full:
            # 最新callbackを優先しつつ、保持量は通常queue上限内に保つ。
            # 完了・失敗・取消は別のterminal queueなので影響を受けない。
            try:
                self.event_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.event_queue.put_nowait(call)
            except queue.Full:
                self.dropped_events += 1
                return False
            self.dropped_events += 1
        return True

    def call_soon_critical(
        self,
        callback: Callable[..., Any],
        *args,
        **kwargs,
    ) -> bool:
        """破棄できない終了処理をTkメインスレッドへ優先配送する。"""
        if self._stopped:
            return False
        self._terminal_queue.put(_UiCall(callback, args, kwargs))
        return True

    def stop(self) -> None:
        """ポーリングを解除し、終了後のイベント保持を止める。"""
        if self._stopped:
            return
        self._stopped = True
        self._running = False
        after_id = self._after_id
        self._after_id = None
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except (tk.TclError, AttributeError):
                pass
        with self._pending_lock:
            self._pending_search_event = None
            self._pending_search_projects = None
            self._pending_search_deltas.clear()
            self._pending_generation = None
        while True:
            try:
                self.event_queue.get_nowait()
            except queue.Empty:
                break
        while True:
            try:
                self._terminal_queue.get_nowait()
            except queue.Empty:
                break
