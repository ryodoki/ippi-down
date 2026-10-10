# -*- coding: utf-8 -*-

"""MainWindowの検索条件保持と実行時スナップショットの回帰テスト。"""

from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

from src.app.service import format_search_conditions
from src.gui.main_window import MainWindow
from src.gui.search_conditions_form import SearchConditionOptionModel
from src.models.config_model import AppConfig, SearchConditions
from src.models.download_diagnostics import RedownloadPolicy


class _Variable:
    def __init__(self, value="") -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class _Combobox:
    def __init__(self, values=()) -> None:
        self.values = list(values)

    def __getitem__(self, key):
        if key != "values":
            raise KeyError(key)
        return self.values

    def __setitem__(self, key, value) -> None:
        if key != "values":
            raise KeyError(key)
        self.values = list(value)

    def cget(self, key):
        return self[key]


def _dynamic_window() -> MainWindow:
    window = MainWindow.__new__(MainWindow)
    window.config = AppConfig()
    window._dynamic_status_vars = {}
    return window


def _place_window() -> MainWindow:
    window = _dynamic_window()
    window.place_search_type_var = _Variable("list")
    window.place_chihou_var = _Variable("関東")
    window.place_todofuken_var = _Variable("東京都")
    window.place_shichouson_var = _Variable("千代田区")
    window.place_chihou_combobox = _Combobox(("", "関東"))
    window.place_todofuken_combobox = _Combobox(("", "東京都"))
    window.place_shichouson_combobox = _Combobox(("", "千代田区"))
    window._update_place_search_mode = Mock()
    window._begin_option_load = Mock()
    window._submit_option_task = Mock()
    window._search_url = "https://example.invalid/search"
    return window


def test_dynamic_response_started_before_user_edit_is_discarded():
    window = _dynamic_window()
    window.koji_shubetsu_var = _Variable("一般土木工事")
    window.koji_shubetsu_combobox = _Combobox(("", "一般土木工事"))
    token = window._new_dynamic_option_token("koji_shubetsu", ())

    window.koji_shubetsu_var.set("アスファルト舗装工事")
    window._on_dynamic_option_selected("koji_shubetsu")
    applied = window._apply_dynamic_options(
        "koji_shubetsu",
        ["一般土木工事", "建築工事"],
        token,
    )

    assert applied is False
    assert window.koji_shubetsu_var.get() == "アスファルト舗装工事"
    assert window.koji_shubetsu_combobox.values == ["", "一般土木工事"]


def test_dynamic_options_preserve_unknown_selection_and_require_reselection():
    window = _dynamic_window()
    status = _Variable()
    window._dynamic_status_vars = {"koji_shubetsu": status}
    window.koji_shubetsu_var = _Variable("アスファルト舗装工事")
    window.koji_shubetsu_combobox = _Combobox(
        ("", "アスファルト舗装工事")
    )

    applied = window._apply_dynamic_options(
        "koji_shubetsu",
        ["一般土木工事", "建築工事"],
    )

    assert applied is True
    assert window.koji_shubetsu_var.get() == "アスファルト舗装工事"
    assert window.koji_shubetsu_combobox.values == [
        "",
        "一般土木工事",
        "建築工事",
        "アスファルト舗装工事",
    ]
    assert window._dynamic_invalid_fields == {"koji_shubetsu"}
    assert status.get() == "再選択が必要"


def test_explicit_selection_of_retained_unknown_value_stays_invalid():
    window = _dynamic_window()
    status = _Variable()
    window._dynamic_status_vars = {"koji_shubetsu": status}
    window.koji_shubetsu_var = _Variable("廃止された工事種別")
    window.koji_shubetsu_combobox = _Combobox(
        ("", "一般土木工事", "廃止された工事種別")
    )
    window._ensure_dynamic_option_state()
    window._search_option_model.update("koji_shubetsu", [("01", "一般土木工事")])

    window._on_dynamic_option_selected("koji_shubetsu")

    assert window._dynamic_invalid_fields == {"koji_shubetsu"}
    assert status.get() == "再選択が必要"


def test_candidate_code_is_restored_as_its_display_name():
    window = _dynamic_window()
    window.koji_shubetsu_var = _Variable("01")
    window.koji_shubetsu_combobox = _Combobox(("", "01"))

    applied = window._apply_dynamic_options(
        "koji_shubetsu", [("01", "一般土木工事")]
    )

    assert applied is True
    assert window.koji_shubetsu_var.get() == "一般土木工事"
    assert window.koji_shubetsu_combobox.values == ["", "一般土木工事"]
    assert not window._dynamic_invalid_fields


def test_programmatic_parent_refresh_keeps_place_descendants():
    window = _place_window()

    window.on_place_chihou_changed()

    assert window.place_todofuken_var.get() == "東京都"
    assert window.place_shichouson_var.get() == "千代田区"
    assert window.place_todofuken_combobox.values == ["", "東京都"]
    assert window.place_shichouson_combobox.values == ["", "千代田区"]
    window._submit_option_task.assert_called_once()


def test_explicit_parent_selection_clears_place_descendants():
    window = _place_window()

    window.on_place_chihou_changed(SimpleNamespace())

    assert window.place_todofuken_var.get() == ""
    assert window.place_shichouson_var.get() == ""
    assert window.place_todofuken_combobox.values == []
    assert window.place_shichouson_combobox.values == []
    window._submit_option_task.assert_called_once()


def test_text_place_mode_ignores_retained_invalid_list_values():
    window = _dynamic_window()
    window._agency_invalid_fields = set()
    window._dynamic_invalid_fields = {"place_todofuken"}
    for field in MainWindow._AGENCY_FIELDS:
        setattr(window, f"{field}_var", _Variable())
    window.koji_shubetsu_var = _Variable()
    window.koji_gyoushu_var = _Variable()
    window.place_search_type_var = _Variable("text")
    window.place_chihou_var = _Variable("関東")
    window.place_todofuken_var = _Variable("旧都道府県")
    window.place_shichouson_var = _Variable()

    assert window._validate_dynamic_search_selections() == ""


def test_schedule_option_snapshot_excludes_retained_unknown_widget_value():
    window = _dynamic_window()
    window._agency_option_guard = Lock()
    window._agency_option_cache = {}
    window._agency_cache_epoch = 0
    for field in MainWindow._AGENCY_FIELDS:
        setattr(window, f"{field}_var", _Variable())
    window._search_option_model = SearchConditionOptionModel(
        SearchConditions(),
        {
            "place_chihou": [("3", "関東")],
            "koji_shubetsu": [("01", "一般土木工事")],
            "koji_gyoushu": [("010", "土木一式工事")],
        },
    )
    # 表示ウィジェットには保持用の旧値がある想定だが、
    # snapshotは構造化候補モデルだけを正本にする。
    window.koji_shubetsu_combobox = _Combobox(
        ("", "一般土木工事", "廃止された工事種別")
    )

    snapshot = window._schedule_search_options_snapshot()

    labels = [option.label for option in snapshot["koji_shubetsu"]]
    assert labels == ["一般土木工事"]
    assert "廃止された工事種別" not in labels


def test_condition_summary_records_type_and_industry_deterministically():
    conditions = SearchConditions(
        hachu_daibunrui="国の機関",
        hachu_chubunrui="国土交通省",
        koji_name="トンネル",
        koji_shubetsu="アスファルト舗装工事",
        koji_gyoushu="土木一式工事",
    )

    summary = format_search_conditions(conditions)

    assert summary == (
        "発注機関・大=国の機関 / 発注機関・中=国土交通省 / "
        "工事名=トンネル / 工事種別=アスファルト舗装工事 / "
        "工事業種=土木一式工事 / 表示件数=20"
    )


def test_download_thread_rejects_changed_condition_summary_before_callback():
    window = MainWindow.__new__(MainWindow)
    window.download_callback = Mock()
    window.event_handler = Mock()
    window.cancel_flag = SimpleNamespace(is_set=lambda: False)
    window.logger = Mock()
    window.show_message = Mock()
    window._reset_download_ui = Mock()
    config = AppConfig(
        search_conditions=SearchConditions(
            koji_shubetsu="アスファルト舗装工事",
            koji_gyoushu="土木一式工事",
        )
    )

    window._download_thread(
        config,
        True,
        RedownloadPolicy.REUSE_VERIFIED,
        "工事種別=一般土木工事 / 工事業種=土木一式工事",
    )

    window.download_callback.assert_not_called()
    assert "検索条件スナップショット" in window.logger.error.call_args.args[0]
    queued = window.event_handler.call_soon.call_args.args
    assert queued[0] is window.show_message
    assert "検索条件スナップショット" in queued[1]
    assert queued[2] == "error"
    window.event_handler.call_soon_critical.assert_called_once_with(
        window._reset_download_ui
    )
