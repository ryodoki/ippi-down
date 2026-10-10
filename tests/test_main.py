# -*- coding: utf-8 -*-

"""エントリーポイントの非GUIスモークテスト。"""

import hashlib
import io
from threading import Lock
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.app.events import EventType, ProgressEvent
from src.main import (
    _GuiReclassificationAgencyResolver,
    _report_self_check,
    download_files,
    prepare_runtime_config,
    run_scheduled_download,
    run_self_check,
)
from src.models.agency import AgencyLevel, AgencyOption, AgencyPath
from src.models.config_model import AppConfig
from src.models.download_result import RunOutcome
from src.storage.layout import RunKind
from src.storage.reclassification import (
    ReclassificationAgencyQuery,
    ReclassificationAgencySegment,
)


def test_gui_reclassification_resolver_uses_shared_official_agency_service():
    parent = AgencyPath()
    for level, code, label in (
        (AgencyLevel.DAIBUNRUI, "0", "国の機関"),
        (AgencyLevel.CHUBUNRUI, "21", "国土交通省"),
        (AgencyLevel.SHOUBUNRUI, "05", "中部地方整備局"),
    ):
        parent = parent.append(AgencyOption(level, code, label, parent))
    child = AgencyOption(
        AgencyLevel.SAIBUNRUI,
        "128",
        "飯田国道事務所",
        parent,
    )
    scraper = Mock()
    scraper.get_agency_children_result.return_value = SimpleNamespace(
        options=(child,),
        error=None,
    )
    main_window = SimpleNamespace(
        _scraper_request_lock=Lock(),
        _get_scraper=lambda: scraper,
        _search_url="https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx",
    )
    cancel_check = Mock(return_value=False)
    query = ReclassificationAgencyQuery(
        parent_segments=tuple(
            ReclassificationAgencySegment(
                segment.level.value,
                segment.label,
                segment.code,
            )
            for segment in parent.segments
        ),
        office_name="飯田国道事務所",
        agency_id="02105000",
        cancel_check=cancel_check,
        search_target="gyomu_keika",
    )

    result = _GuiReclassificationAgencyResolver(main_window).resolve_candidates(query)

    assert result == (child,)
    scraper.get_agency_children_result.assert_called_once_with(
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=7",
        parent_path=parent,
        cancel_check=cancel_check,
    )


def test_self_check_succeeds_on_supported_python(capsys, monkeypatch):
    import src.core.html_to_pdf as html_to_pdf

    temporary_roots = []

    class FakeConverter:
        @classmethod
        def discover_edge(cls):
            return Path(r"C:\Program Files\Microsoft\Edge\msedge.exe")

        def __init__(self, *, edge_path, audit):
            assert edge_path.name == "msedge.exe"
            assert audit.logs_dir.name == "audit"

        def convert(
            self,
            source_html,
            output_part,
            cancel_check=None,
            *,
            source_url,
            document_name,
            project_name,
        ):
            assert "<h1>入札調書</h1>" in source_html
            assert source_url.startswith("https://e2ppiw01.e-bisc.go.jp/")
            assert document_name == "入札調書"
            assert project_name in source_html
            output_path = Path(output_part)
            temporary_roots.append(output_path.parent)
            content = b"%PDF-1.7\n/MediaBox [0 0 595.28 841.89]\nself-check\n%%EOF\n"
            output_path.write_bytes(content)
            return SimpleNamespace(
                success=True,
                primary_issue=None,
                error="",
                bytes_written=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )

    monkeypatch.setattr(html_to_pdf, "HtmlToPdfConverter", FakeConverter)

    assert run_self_check() == 0
    output = capsys.readouterr().out
    assert "self-check: OK" in output
    assert len(temporary_roots) == 1
    assert not temporary_roots[0].exists()


def test_self_check_succeeds_without_edge_using_internal_renderer(
    capsys,
    monkeypatch,
):
    import src.core.html_to_pdf as html_to_pdf

    class MissingEdgeConverter:
        @classmethod
        def discover_edge(cls):
            return None

        def __init__(self, *, edge_path, audit):
            assert edge_path is None
            assert audit.logs_dir.name == "audit"

        def convert(self, source_html, output_part, **_kwargs):
            assert "入札調書" in source_html
            content = b"%PDF-1.7\n/MediaBox [0 0 595.28 841.89]\nself-check\n%%EOF\n"
            Path(output_part).write_bytes(content)
            return SimpleNamespace(
                success=True,
                primary_issue=None,
                error="",
                bytes_written=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )

    monkeypatch.setattr(html_to_pdf, "HtmlToPdfConverter", MissingEdgeConverter)

    assert run_self_check() == 0
    assert "self-check: OK" in capsys.readouterr().out


def test_windowed_exe_self_check_writes_a_diagnostic_result(
    tmp_path,
    monkeypatch,
):
    executable = tmp_path / "ippi-down.exe"
    monkeypatch.setattr("src.main.sys.stdout", None)
    monkeypatch.setattr("src.main.sys.stderr", None)
    monkeypatch.setattr("src.main.sys.executable", str(executable))
    monkeypatch.setattr(
        "src.main.sys.frozen",
        True,
        raising=False,
    )

    _report_self_check(
        "ippi-down self-check: FAILED ([EDGE_NOT_FOUND] Edgeなし)",
        error=True,
    )

    assert (tmp_path / "self-check-result.txt").read_text(encoding="utf-8") == (
        "ippi-down self-check: FAILED ([EDGE_NOT_FOUND] Edgeなし)\n"
    )


def test_frozen_self_check_writes_result_even_with_non_none_stream(
    tmp_path,
    monkeypatch,
):
    """windowed exeの擬似streamがあっても診断ファイルを必ず残す。"""
    stream = io.StringIO()
    monkeypatch.setattr("src.main.sys.stdout", stream)
    monkeypatch.setattr("src.main.sys.executable", str(tmp_path / "ippi-down.exe"))
    monkeypatch.setattr("src.main.sys.frozen", True, raising=False)

    _report_self_check("ippi-down self-check: OK")

    assert stream.getvalue() == "ippi-down self-check: OK\n"
    assert (tmp_path / "self-check-result.txt").read_text(
        encoding="utf-8"
    ) == "ippi-down self-check: OK\n"


def test_prepare_runtime_config_disables_multi_agency_without_mutating_saved():
    config = AppConfig()
    config.search_conditions.hachu_multi = ["旧機関"]
    logger = Mock()

    runtime = prepare_runtime_config(config, logger)

    assert runtime.search_conditions.hachu_multi == []
    assert config.search_conditions.hachu_multi == ["旧機関"]
    logger.warning.assert_called_once()


def test_manual_download_does_not_reemit_terminal_failure(monkeypatch):
    terminal = ProgressEvent(type=EventType.FAIL, message="最終失敗")
    result = SimpleNamespace(
        success=False,
        message="最終失敗",
        outcome=RunOutcome.FAILED,
        result=None,
    )

    class FakeService:
        def __init__(self, logger):
            pass

        def run(self, config, progress_callback, cancel_check):
            progress_callback(terminal)
            return result

    monkeypatch.setattr("src.main.ApplicationService", FakeService)
    main_window = SimpleNamespace(
        logger=Mock(),
        event_handler=SimpleNamespace(emit=Mock()),
        cancel_flag=SimpleNamespace(is_set=lambda: False),
    )

    download_files(main_window, AppConfig())

    main_window.event_handler.emit.assert_called_once_with(terminal)


def test_scheduled_download_logs_terminal_failure_once(monkeypatch):
    terminal = ProgressEvent(type=EventType.FAIL, message="最終失敗")
    result = SimpleNamespace(
        success=False,
        message="最終失敗",
        error="",
        outcome=RunOutcome.FAILED,
        result=None,
    )

    received = {}

    class FakeService:
        def __init__(self, logger):
            pass

        def run(self, config, progress_callback, cancel_flag, **kwargs):
            received.update(kwargs)
            progress_callback(terminal)
            return result

    notifier = Mock()
    monkeypatch.setattr("src.main.ApplicationService", FakeService)
    monkeypatch.setattr("src.main.Notifier", lambda logger: notifier)
    logger = Mock()

    run_scheduled_download(AppConfig(), logger)

    logger.error.assert_called_once_with("最終失敗")
    notifier.notify.assert_called_once_with("ippi-down", "最終失敗", duration=10)
    assert received["run_kind"] is RunKind.SCHEDULED


def test_scheduled_partial_result_is_logged_as_warning(monkeypatch):
    terminal = ProgressEvent(type=EventType.COMPLETE, message="一部失敗")
    result = SimpleNamespace(
        success=True,
        message="一部失敗",
        error="先頭理由",
        outcome=RunOutcome.PARTIAL,
        result=object(),
    )

    class FakeService:
        def __init__(self, logger):
            pass

        def run(self, config, progress_callback, cancel_flag, **kwargs):
            progress_callback(terminal)
            return result

    notifier = Mock()
    monkeypatch.setattr("src.main.ApplicationService", FakeService)
    monkeypatch.setattr("src.main.Notifier", lambda logger: notifier)
    logger = Mock()

    run_scheduled_download(AppConfig(), logger)

    logger.warning.assert_called_once_with("一部失敗")
    assert all(call.args != ("一部失敗",) for call in logger.info.call_args_list)
    notifier.notify.assert_called_once_with("ippi-down", "一部失敗", duration=10)
