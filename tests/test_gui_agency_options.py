# -*- coding: utf-8 -*-

"""発注機関候補のGUI共有・競合制御テスト。"""

from threading import Event, Lock, Thread
from unittest.mock import Mock

from src.gui.main_window import MainWindow
from src.gui.schedule_editor_dialog import ScheduleEditorDialog
from src.gui.search_conditions_form import (
    SearchConditionOptionModel,
    normalise_search_options,
)
from src.models.agency import AgencyLevel, AgencyOption, AgencyPath
from src.models.config_model import SearchConditions


class _Variable:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _Combo:
    def __init__(self) -> None:
        self.values = ()
        self.state = "readonly"

    def __setitem__(self, name: str, value) -> None:
        if name == "values":
            self.values = tuple(value)

    def cget(self, name: str):
        if name == "values":
            return self.values
        raise KeyError(name)

    def configure(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]


def _root_option(label: str = "国の機関") -> AgencyOption:
    return AgencyOption(
        level=AgencyLevel.DAIBUNRUI,
        code="1",
        label=label,
        parent_path=AgencyPath(),
    )


def _bare_window() -> MainWindow:
    window = MainWindow.__new__(MainWindow)
    window._agency_generations = {
        field: 0 for field in MainWindow._AGENCY_FIELDS
    }
    window._agency_loading_fields = set()
    window._agency_invalid_fields = set()
    window._agency_cancel_events = {}
    window._agency_request_parents = {}
    window._agency_status_vars = {
        field: _Variable() for field in MainWindow._AGENCY_FIELDS
    }
    for field in MainWindow._AGENCY_FIELDS:
        setattr(window, f"{field}_var", _Variable())
        setattr(window, f"{field}_combo", _Combo())
    window._finish_option_load = Mock()
    window._request_agency_options = Mock()
    window.logger = Mock()
    window.show_message = Mock()
    return window


def test_normalise_search_options_preserves_agency_code_and_label():
    option = _root_option()

    result = normalise_search_options([option])

    assert [(item.code, item.label) for item in result] == [("1", "国の機関")]


def test_agency_update_preserves_unknown_saved_value_and_requires_reselection():
    window = _bare_window()
    window.hachu_daibunrui_var.set("廃止された機関")

    window._apply_agency_options(
        "hachu_daibunrui",
        0,
        (),
        (_root_option(),),
        None,
        finish_load=False,
    )

    assert window.hachu_daibunrui_var.get() == "廃止された機関"
    assert window.hachu_daibunrui_combo.values == (
        "",
        "国の機関",
        "廃止された機関",
    )
    assert "hachu_daibunrui" in window._agency_invalid_fields
    assert window._agency_status_vars["hachu_daibunrui"].get() == "再選択が必要"
    assert "選択し直してください" in window._validate_dynamic_search_selections()


def test_agency_update_discards_response_from_old_generation():
    window = _bare_window()
    window._agency_generations["hachu_daibunrui"] = 2

    window._apply_agency_options(
        "hachu_daibunrui",
        1,
        (),
        (_root_option(),),
        None,
        finish_load=True,
    )

    assert window.hachu_daibunrui_combo.values == ()
    window._finish_option_load.assert_called_once_with()


def test_agency_child_is_disabled_until_parent_is_selected():
    window = _bare_window()

    window._set_agency_field_state("hachu_chubunrui")
    assert window.hachu_chubunrui_combo.state == "disabled"

    window.hachu_daibunrui_var.set("国の機関")
    window._set_agency_field_state("hachu_chubunrui")
    assert window.hachu_chubunrui_combo.state == "readonly"


def test_agency_singleflight_coalesces_same_parent_request():
    window = MainWindow.__new__(MainWindow)
    window._agency_option_cache = {}
    window._agency_option_flights = {}
    window._agency_option_guard = Lock()
    window._agency_cache_epoch = 0
    window._agency_catalog_epoch = 0
    window._scraper_request_lock = Lock()
    started = Event()
    release = Event()
    calls = []

    def fetch(parent: AgencyPath, _cancel_check=None):
        calls.append(parent)
        started.set()
        assert release.wait(2)
        return (_root_option(),)

    window._fetch_agency_children = fetch
    results = []
    first = Thread(
        target=lambda: results.append(
            window._get_agency_children_singleflight(AgencyPath())
        )
    )
    second = Thread(
        target=lambda: results.append(
            window._get_agency_children_singleflight(AgencyPath())
        )
    )

    first.start()
    assert started.wait(2)
    second.start()
    release.set()
    first.join(2)
    second.join(2)

    assert len(calls) == 1
    assert results == [(_root_option(),), (_root_option(),)]


def test_cancelled_a_request_is_not_reused_by_new_a_request():
    window = MainWindow.__new__(MainWindow)
    window._agency_option_cache = {}
    window._agency_option_flights = {}
    window._agency_option_guard = Lock()
    window._agency_cache_epoch = 0
    window._agency_catalog_epoch = 0
    window._scraper_request_lock = Lock()
    first_started = Event()
    release_first = Event()
    old_cancel = Event()
    new_cancel = Event()
    calls = []

    def fetch(parent: AgencyPath, cancel_check=None):
        calls.append(parent)
        if len(calls) == 1:
            first_started.set()
            assert release_first.wait(2)
            if cancel_check is not None and cancel_check():
                raise RuntimeError("cancelled")
        return (_root_option(),)

    window._fetch_agency_children = fetch
    results = []
    errors = []

    def request(cancel_check):
        try:
            results.append(
                window._get_agency_children_singleflight(
                    AgencyPath(), cancel_check
                )
            )
        except RuntimeError as exc:
            errors.append(str(exc))

    first = Thread(target=request, args=(old_cancel.is_set,))
    second = Thread(target=request, args=(new_cancel.is_set,))
    first.start()
    assert first_started.wait(2)
    old_cancel.set()
    second.start()
    release_first.set()
    first.join(2)
    second.join(2)

    assert len(calls) == 2
    assert results == [(_root_option(),)]
    assert errors == ["cancelled"]


def test_schedule_agency_loader_returns_shared_agency_options():
    window = MainWindow.__new__(MainWindow)
    parent = AgencyPath.from_labels_and_codes(["国の機関"], ["1"])
    child = AgencyOption(
        level=AgencyLevel.CHUBUNRUI,
        code="10",
        label="国土交通省",
        parent_path=parent,
    )
    window._initial_search_option_cache = {}
    window._resolve_agency_path = Mock(return_value=parent)
    window._get_agency_children_singleflight = Mock(return_value=(child,))
    window._call_scraper_method = Mock()

    result = window._load_schedule_search_options(
        "hachu_chubunrui", ("国の機関",)
    )

    assert result == [child]
    window._resolve_agency_path.assert_called_once_with(("国の機関",), None)
    window._call_scraper_method.assert_not_called()


def test_schedule_editor_rejects_unknown_saved_agency_after_refresh():
    dialog = ScheduleEditorDialog.__new__(ScheduleEditorDialog)
    saved = SearchConditions(hachu_daibunrui="廃止された機関")
    dialog._search_option_model = SearchConditionOptionModel(
        saved,
        {"hachu_daibunrui": [_root_option()]},
    )
    dialog._option_loading = set()
    dialog._option_errors = {}

    errors = dialog._agency_selection_errors(saved)

    assert len(errors) == 1
    assert "最新候補にありません" in errors[0]
    assert "選択し直してください" in errors[0]
