# -*- coding: utf-8 -*-

"""GUIの一回限り再取得指定と保存済み表示の回帰テスト。"""

from threading import get_ident
from types import SimpleNamespace
from unittest.mock import Mock

from src.app.events import EventType, ProgressEvent
from src.app.service import ApplicationService, _ExtractionResult
from src.gui.event_handler import EventHandler
from src.gui.main_window import MainWindow
from src.main import download_files
from src.models.config_model import AppConfig, SavePaths
from src.models.download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadStage,
    IssueSeverity,
    RedownloadPolicy,
)
from src.models.download_result import DownloadResult, RunOutcome
from src.models.download_task import DownloadTask
from src.models.file_info import FileInfo


class _Variable:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Widget:
    def __init__(self):
        self.options = {}

    def config(self, **kwargs):
        self.options.update(kwargs)


class _Progressbar(_Widget):
    def __init__(self):
        super().__init__()
        self.values = {}

    def stop(self):
        return None

    def configure(self, **kwargs):
        self.config(**kwargs)

    def __setitem__(self, key, value):
        self.values[key] = value


def test_service_all_reused_message_and_policy(tmp_path):
    """全件履歴一致を失敗に見える「成功0・スキップN」にしない。"""
    logger = Mock()
    service = ApplicationService(logger)
    files = [
        FileInfo(
            f"https://example.invalid/{index}.pdf",
            f"{index}.pdf",
            ".pdf",
        )
        for index in range(2)
    ]
    service._initialize_components = Mock()
    service._extract_files = Mock(
        return_value=_ExtractionResult(files=files, attempted=1)
    )
    service._filter_files = Mock(return_value=files)
    service._download_files = Mock(
        return_value=DownloadResult(total=2, skipped=2)
    )
    events = []

    run_result = service.run(
        AppConfig(save_paths=SavePaths(local=str(tmp_path))),
        progress_callback=events.append,
        redownload_policy=RedownloadPolicy.FORCE_REFRESH,
    )

    assert run_result.outcome == RunOutcome.SUCCESS
    assert "完了（2件すべて保存済み）" in run_result.message
    assert "新規保存=0" in run_result.message
    assert "保存済み確認=2" in run_result.message
    assert "スキップ" not in run_result.message
    assert service._download_files.call_args.args[-1] == (
        RedownloadPolicy.FORCE_REFRESH
    )
    terminal = events[-1]
    assert terminal.type == EventType.COMPLETE
    assert terminal.metadata["all_reused"] is True
    assert terminal.metadata["reused"] == 2


def test_event_handler_uses_all_reused_terminal_label():
    """完了イベントの全件保存済み情報を進捗欄へ伝える。"""
    window = Mock()
    handler = EventHandler.__new__(EventHandler)
    handler.main_window = window
    event = ProgressEvent(
        type=EventType.COMPLETE,
        message="完了（2件すべて保存済み）",
        current=2,
        total=2,
        metadata={
            "outcome": RunOutcome.SUCCESS.value,
            "type": "info",
            "all_reused": True,
        },
    )

    handler._handle_event(event)

    window.set_run_outcome.assert_called_once_with(
        RunOutcome.SUCCESS,
        2,
        2,
        all_reused=True,
    )


def test_service_forwards_policy_and_reports_reused_progress(tmp_path):
    """Downloaderへ指定を渡し、履歴一致も完了件数へ数える。"""
    service = ApplicationService(Mock())
    service._downloader = Mock()
    service._naming = Mock()
    service._downloader.download_files.return_value = DownloadResult(
        total=1,
        skipped=1,
    )
    file_info = FileInfo(
        "https://example.invalid/file.pdf",
        "file.pdf",
        ".pdf",
    )
    events = []

    service._download_files(
        [file_info],
        AppConfig(save_paths=SavePaths(local=str(tmp_path))),
        events.append,
        None,
        RedownloadPolicy.FORCE_REFRESH,
    )

    call = service._downloader.download_files.call_args
    assert call.kwargs["redownload_policy"] == (
        RedownloadPolicy.FORCE_REFRESH
    )
    callback = call.kwargs["task_result_callback"]
    callback(
        1,
        1,
        DownloadTask(
            file_info=file_info,
            local_path="",
            status="skipped",
        ),
    )
    progress = events[-1]
    assert progress.type == EventType.PROGRESS
    assert progress.current == 1
    assert progress.total == 1
    assert "保存済み確認" in progress.message
    assert "HTTP通信なし" in progress.message


def test_service_reports_history_repair_and_preserved_existing_file(
    tmp_path,
):
    """履歴不正の修復と再取得失敗時の既存保持をGUIへ伝える。"""
    service = ApplicationService(Mock())
    service._downloader = Mock()
    service._naming = Mock()
    service._downloader.download_files.return_value = DownloadResult(
        total=1,
        success=1,
    )
    file_info = FileInfo(
        "https://example.invalid/file.pdf",
        "file.pdf",
        ".pdf",
    )
    events = []
    service._download_files(
        [file_info],
        AppConfig(save_paths=SavePaths(local=str(tmp_path))),
        events.append,
        None,
    )
    callback = service._downloader.download_files.call_args.kwargs[
        "task_result_callback"
    ]
    history_issue = DownloadIssue(
        DownloadIssueCode.HISTORY_INVALID,
        DownloadStage.VALIDATE,
        "保存済みPDFの終端を確認できません",
        IssueSeverity.WARNING,
    )

    callback(
        1,
        1,
        DownloadTask(
            file_info=file_info,
            local_path="file.pdf",
            status="completed",
            issues=[history_issue],
        ),
    )

    warning = events[-1]
    assert warning.type == EventType.MESSAGE
    assert warning.metadata["type"] == "warning"
    assert "[HISTORY_INVALID]" in warning.message
    assert "再取得済み" in warning.message

    failure_issue = DownloadIssue(
        DownloadIssueCode.NETWORK_ERROR,
        DownloadStage.FETCH,
        "通信に失敗しました",
        details={"existing_file_preserved": True},
    )
    callback(
        1,
        1,
        DownloadTask(
            file_info=file_info,
            local_path="file.pdf",
            status="failed",
            error_message=failure_issue.message,
            issues=[failure_issue],
        ),
    )

    failure = events[-1]
    assert failure.type == EventType.MESSAGE
    assert "既存の正常ファイルは保持されています" in failure.message
    assert "[NETWORK_ERROR]" in failure.message

    callback(
        1,
        1,
        DownloadTask(
            file_info=file_info,
            local_path="file.pdf",
            status="failed",
            error_message=failure_issue.message,
            issues=[failure_issue, history_issue],
        ),
    )

    invalid_failure = events[-1]
    assert "検証不合格の既存ファイル" in invalid_failure.message
    assert "正常ファイル" not in invalid_failure.message


def test_service_reports_legacy_path_redownload(tmp_path):
    """旧分類場所から正規保存先への再取得をGUIへ明示する。"""
    service = ApplicationService(Mock())
    service._downloader = Mock()
    service._naming = Mock()
    service._downloader.download_files.return_value = DownloadResult(
        total=1,
        success=1,
    )
    file_info = FileInfo(
        "https://example.invalid/file.pdf",
        "file.pdf",
        ".pdf",
    )
    events = []
    service._download_files(
        [file_info],
        AppConfig(save_paths=SavePaths(local=str(tmp_path))),
        events.append,
        None,
    )
    callback = service._downloader.download_files.call_args.kwargs[
        "task_result_callback"
    ]
    issue = DownloadIssue(
        DownloadIssueCode.LEGACY_PATH_REDOWNLOAD,
        DownloadStage.VALIDATE,
        "旧分類場所の保存済みファイルを保持して再取得しました",
        IssueSeverity.WARNING,
    )

    callback(
        1,
        1,
        DownloadTask(
            file_info=file_info,
            local_path=str(tmp_path / "classified" / "file.pdf"),
            status="completed",
            issues=[issue],
        ),
    )

    warning = events[-1]
    assert warning.type == EventType.MESSAGE
    assert warning.metadata["type"] == "warning"
    assert "正規保存先へ再取得しました" in warning.message
    assert "[LEGACY_PATH_REDOWNLOAD]" in warning.message


def test_main_window_all_reused_progress_label():
    """全件保存済みの成功を進捗欄で明示する。"""
    window = MainWindow.__new__(MainWindow)
    window._ui_thread_id = get_ident()
    window._last_run_outcome = None
    window.progress_bar = _Progressbar()
    window.progress_var = _Variable()

    window.set_run_outcome(
        RunOutcome.SUCCESS,
        current=2,
        total=2,
        all_reused=True,
    )

    assert window.progress_var.get() == "完了（2件すべて保存済み）"
    assert window.progress_bar.values["value"] == 100


def test_download_thread_passes_one_shot_policy_to_callback():
    """GUIスナップショットと一緒に今回だけの再取得指定を渡す。"""
    window = MainWindow.__new__(MainWindow)
    window.download_callback = Mock()
    window.event_handler = Mock()
    window.cancel_flag = Mock()
    config = AppConfig()

    window._download_thread(
        config,
        True,
        RedownloadPolicy.FORCE_REFRESH,
    )

    window.download_callback.assert_called_once_with(
        window,
        config,
        True,
        RedownloadPolicy.FORCE_REFRESH,
    )
    window.event_handler.call_soon_critical.assert_called_once_with(
        window._reset_download_ui
    )


def test_main_download_forwards_explicit_policy(monkeypatch):
    """GUIコールバック境界で再取得指定を失わない。"""
    received = {}

    class _Service:
        def __init__(self, logger):
            del logger

        def run(
            self,
            config,
            progress_callback,
            cancel_check,
            redownload_policy,
        ):
            del config, progress_callback, cancel_check
            received["policy"] = redownload_policy
            return SimpleNamespace(result=None)

    monkeypatch.setattr("src.main.ApplicationService", _Service)
    window = SimpleNamespace(
        logger=Mock(),
        event_handler=SimpleNamespace(emit=Mock()),
        cancel_flag=SimpleNamespace(is_set=lambda: False),
    )

    download_files(
        window,
        AppConfig(),
        redownload_policy=RedownloadPolicy.FORCE_REFRESH,
    )

    assert received["policy"] == RedownloadPolicy.FORCE_REFRESH


def test_reset_download_ui_clears_one_shot_option():
    """完了・失敗・キャンセル後に再取得指定を必ずOFFへ戻す。"""
    window = MainWindow.__new__(MainWindow)
    window.download_thread = object()
    window._last_run_outcome = RunOutcome.CANCELLED
    window.redownload_existing_var = _Variable(True)
    window.chk_redownload_existing = _Widget()
    window.btn_cancel = _Widget()
    window._refresh_download_button_state = Mock()

    window._reset_download_ui()

    assert window.redownload_existing_var.get() is False
    assert window.chk_redownload_existing.options["state"] == "normal"
