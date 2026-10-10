# -*- coding: utf-8 -*-

"""長時間GUI実行で保持量が増え続けないことを検証する。"""

from __future__ import annotations

from collections import deque
import gc
from threading import Event, get_ident
from unittest.mock import Mock
import warnings

from src.app.events import EventType, ProgressEvent
from src.gui.event_handler import EventHandler
from src.gui.main_window import MainWindow
from src.gui.option_load_coordinator import OptionLoadCoordinator
from src.models.config_model import LoggingConfig
from src.models.download_result import RunOutcome
from src.utils.logger import Logger


def _search_event(index: int) -> ProgressEvent:
    return ProgressEvent(
        type=EventType.PROGRESS,
        metadata={
            "phase": "search",
            "search_phase": "detail",
            "generation": 1,
            "project_delta": {
                "project_id": f"project-{index}",
                "project_name": f"工事{index}",
                "documents": [],
            },
        },
    )


def test_search_progress_is_coalesced_without_losing_project_deltas():
    root = Mock()
    window = Mock()
    handler = EventHandler(root, window)

    for index in range(10_000):
        assert handler.emit(_search_event(index)) is True

    assert handler.event_queue.qsize() == 0
    assert len(handler._pending_search_deltas) == 10_000

    handler._poll_events()

    metadata = window.update_search_progress.call_args.args[0]
    assert len(metadata["project_deltas"]) == 10_000
    assert metadata["project_deltas"][-1]["project_id"] == "project-9999"


def test_normal_event_queue_is_bounded_and_terminal_event_is_preserved():
    root = Mock()
    window = Mock()
    handler = EventHandler(root, window)

    for index in range(handler._MAX_QUEUED_EVENTS + 50):
        handler.emit(
            ProgressEvent(
                type=EventType.PROGRESS,
                current=index,
                total=1_000,
            )
        )
    handler.emit(
        ProgressEvent(
            type=EventType.COMPLETE,
            current=1_000,
            total=1_000,
        )
    )

    assert handler.event_queue.qsize() == handler._MAX_QUEUED_EVENTS
    assert handler.dropped_events == 50
    assert handler._next_item().type == EventType.COMPLETE


def test_pending_search_completion_is_delivered_before_terminal_event():
    root = Mock()
    window = Mock()
    order = []
    window.update_search_progress.side_effect = (
        lambda metadata: order.append(("search", metadata["search_phase"]))
    )
    window.set_run_outcome.side_effect = (
        lambda outcome, *_args, **_kwargs: order.append(("terminal", outcome))
    )
    handler = EventHandler(root, window)

    handler.emit(
        ProgressEvent(
            type=EventType.PROGRESS,
            metadata={
                "phase": "search",
                "search_phase": "complete",
                "generation": 1,
            },
        )
    )
    handler.emit(
        ProgressEvent(
            type=EventType.COMPLETE,
            current=43,
            total=43,
            metadata={"outcome": RunOutcome.SUCCESS.value},
        )
    )

    handler._poll_events()

    assert order == [
        ("search", "complete"),
        ("terminal", RunOutcome.SUCCESS),
    ]
    assert handler._pending_search_event is None


def test_stale_progress_does_not_overwrite_terminal_state():
    root = Mock()
    window = Mock()
    handler = EventHandler(root, window)
    handler.emit(
        ProgressEvent(type=EventType.PROGRESS, current=42, total=43)
    )
    handler.emit(
        ProgressEvent(
            type=EventType.COMPLETE,
            current=43,
            total=43,
            metadata={"outcome": RunOutcome.SUCCESS.value},
        )
    )

    handler._poll_events()

    window.set_run_outcome.assert_called_once_with(
        RunOutcome.SUCCESS, 43, 43
    )
    window.update_progress.assert_not_called()


def test_ui_callbacks_do_not_fall_back_to_an_unbounded_queue():
    root = Mock()
    handler = EventHandler(root, Mock())

    for index in range(handler._MAX_QUEUED_EVENTS * 3):
        handler.call_soon(lambda value: value, index)
    handler.emit(ProgressEvent(type=EventType.FAIL, error="failed"))

    assert handler.event_queue.qsize() == handler._MAX_QUEUED_EVENTS
    assert handler.dropped_events == handler._MAX_QUEUED_EVENTS * 2
    assert handler._next_item().type == EventType.FAIL


def test_critical_ui_callback_survives_full_normal_queue():
    root = Mock()
    handler = EventHandler(root, Mock())
    callback = Mock()

    for index in range(handler._MAX_QUEUED_EVENTS):
        handler.call_soon(lambda value: value, index)

    assert handler.call_soon_critical(callback, "done") is True
    item = handler._next_item()
    assert item.callback is callback
    assert item.args == ("done",)
    assert handler.event_queue.qsize() == handler._MAX_QUEUED_EVENTS


def test_event_handler_stop_cancels_after_and_rejects_new_work():
    root = Mock()
    root.after.return_value = "after-1"
    handler = EventHandler(root, Mock())
    handler.start_polling()

    handler.stop()

    root.after_cancel.assert_called_once_with("after-1")
    assert handler.emit(ProgressEvent(type=EventType.MESSAGE)) is False
    assert handler.call_soon(lambda: None) is False


def test_option_coordinator_keeps_only_latest_pending_task_per_key():
    coordinator = OptionLoadCoordinator(name="test-option-coordinator")
    started = Event()
    release = Event()
    latest_finished = Event()
    calls: list[int] = []
    discarded: list[int] = []

    def first() -> None:
        calls.append(-1)
        started.set()
        assert release.wait(2)

    coordinator.submit("active", first)
    assert started.wait(2)
    for index in range(1_000):
        coordinator.submit(
            "same-key",
            lambda value=index: (
                calls.append(value),
                latest_finished.set(),
            ),
            on_discard=lambda value=index: discarded.append(value),
        )

    assert coordinator.pending_count == 1
    release.set()
    assert latest_finished.wait(2)
    coordinator.stop()
    coordinator.join(2)

    assert calls == [-1, 999]
    assert len(discarded) == 999


def test_option_coordinator_bounds_distinct_pending_keys_and_prioritizes_user():
    coordinator = OptionLoadCoordinator(name="test-bounded-option-coordinator")
    started = Event()
    release = Event()
    user_finished = Event()
    discarded: list[int] = []

    def active() -> None:
        started.set()
        assert release.wait(2)

    coordinator.submit("active", active)
    assert started.wait(2)
    for index in range(1_000):
        coordinator.submit(
            f"prefetch-{index}",
            lambda: None,
            priority=OptionLoadCoordinator.PREFETCH_PRIORITY,
            on_discard=lambda value=index: discarded.append(value),
        )
    coordinator.submit(
        "user",
        user_finished.set,
        priority=OptionLoadCoordinator.USER_PRIORITY,
    )

    assert coordinator.pending_count == coordinator.MAX_PENDING
    assert discarded
    release.set()
    assert user_finished.wait(2)
    coordinator.stop()
    coordinator.join(2)


def test_main_window_applies_project_deltas_without_full_tuple_copy():
    window = MainWindow.__new__(MainWindow)
    window._ui_thread_id = get_ident()
    window._search_summary = None
    window._project_document_projects = ()
    window._project_document_projects_by_id = {}
    window._project_documents_dialog = None
    window.summary_var = Mock()
    window.btn_project_documents = Mock()

    deltas = [
        {
            "project_id": f"p-{index}",
            "project_name": f"工事{index}",
            "documents": [],
        }
        for index in range(10_000)
    ]
    window.update_search_summary(
        {"projects_matched": 10_000},
        project_deltas=deltas,
        snapshot_kind="delta",
    )

    assert len(window._project_document_projects_by_id) == 10_000
    assert window._project_document_projects == ()
    assert len(window._current_project_document_views()) == 10_000


def test_gui_log_discards_old_visible_lines():
    window = MainWindow.__new__(MainWindow)
    window._ui_thread_id = get_ident()
    window.log_text = Mock()
    window._gui_log_entries = deque()
    window._gui_log_lines = 0
    window._gui_log_bytes = 0

    for index in range(6_000):
        window.show_message(f"message-{index}")

    assert window._gui_log_lines <= window._GUI_LOG_MAX_LINES
    assert window._gui_log_bytes <= window._GUI_LOG_MAX_BYTES
    assert window.log_text.delete.called


def test_schedule_log_reader_limits_records_and_bytes(tmp_path):
    target = tmp_path / "schedule-runs.jsonl"
    with target.open("w", encoding="utf-8") as stream:
        for index in range(300):
            stream.write(
                '{"schedule_id":"target","index":%d,"padding":"%s"}\n'
                % (index, "x" * 200)
            )

    records = MainWindow._read_schedule_log_tail(
        target,
        "target",
        max_records=200,
        max_bytes=2 * 1024 * 1024,
    )

    assert len(records) == 200
    assert '"index": 100' in records[0]
    assert '"index": 299' in records[-1]


def test_repeated_logger_creation_reuses_open_handlers_without_warning(tmp_path):
    config = LoggingConfig(file=str(tmp_path / "memory-test.log"))
    first = Logger(config)
    handler_ids = tuple(id(handler) for handler in first.logger.handlers)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        for _ in range(1_000):
            Logger(config)
        gc.collect()

    assert tuple(id(handler) for handler in first.logger.handlers) == handler_ids
    assert not [item for item in caught if item.category is ResourceWarning]
