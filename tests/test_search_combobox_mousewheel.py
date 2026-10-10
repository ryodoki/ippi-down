# -*- coding: utf-8 -*-

"""検索Comboboxのホイール保護と候補照合のheadlessテスト。"""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from src.gui import search_conditions_form as form
from src.gui.search_conditions_form import (
    DynamicOptionRequestToken,
    SearchConditionOptionModel,
    bind_combobox_mousewheel_to_canvas,
)
from src.models.config_model import SearchConditions


class _FakeTk:
    def __init__(self, *, popdown_mapped: bool = False) -> None:
        self.popdown_mapped = popdown_mapped

    def call(self, *args):
        if args[0] == "ttk::combobox::PopdownWindow":
            return ".combo.popdown"
        if args[:2] == ("winfo", "ismapped"):
            return int(self.popdown_mapped)
        raise AssertionError(args)


class _FakeCombo:
    def __init__(self, *, popdown_mapped: bool = False) -> None:
        self.tk = _FakeTk(popdown_mapped=popdown_mapped)
        self.bindings = {}
        self.unbound = []

    def __str__(self) -> str:
        return ".combo"

    def bind(self, sequence, callback, add=None):
        self.bindings[sequence] = callback
        assert add == "+"
        return "binding-id"

    def unbind(self, sequence, bind_id):
        self.unbound.append((sequence, bind_id))

    def winfo_children(self):
        return ()


class _FakeCanvas:
    def __init__(self) -> None:
        self.scrolls = []

    def yview_scroll(self, amount, units) -> None:
        self.scrolls.append((amount, units))


class _FakeContainer:
    def __init__(self, *children) -> None:
        self.children = children

    def winfo_children(self):
        return self.children


def test_closed_combobox_mousewheel_scrolls_canvas_and_stops_value_change():
    combo = _FakeCombo()
    canvas = _FakeCanvas()

    bind_combobox_mousewheel_to_canvas(combo, canvas)
    result = combo.bindings["<MouseWheel>"](SimpleNamespace(delta=-120))

    assert result == "break"
    assert canvas.scrolls == [(1, "units")]


def test_open_combobox_popdown_keeps_normal_mousewheel_handling():
    combo = _FakeCombo(popdown_mapped=True)
    canvas = _FakeCanvas()

    bind_combobox_mousewheel_to_canvas(combo, canvas)
    result = combo.bindings["<MouseWheel>"](SimpleNamespace(delta=-120))

    assert result is None
    assert canvas.scrolls == []


def test_combobox_mousewheel_supports_sub_120_touchpad_delta():
    combo = _FakeCombo()
    canvas = _FakeCanvas()

    bind_combobox_mousewheel_to_canvas(combo, canvas)
    result = combo.bindings["<MouseWheel>"](SimpleNamespace(delta=1))

    assert result == "break"
    assert canvas.scrolls == [(-1, "units")]


def test_all_nested_search_comboboxes_are_bound(monkeypatch):
    first = _FakeCombo()
    second = _FakeCombo()
    container = _FakeContainer(first, _FakeContainer(second))
    canvas = _FakeCanvas()
    monkeypatch.setattr(form.ttk, "Combobox", _FakeCombo)

    bind_ids = form.bind_search_comboboxes_to_canvas(container, canvas)

    assert bind_ids == ("binding-id", "binding-id")
    assert "<MouseWheel>" in first.bindings
    assert "<MouseWheel>" in second.bindings


def test_reconcile_preserves_unknown_current_value_and_marks_it_invalid():
    model = SearchConditionOptionModel(
        SearchConditions(koji_shubetsu="アスファルト舗装工事"),
        {"koji_shubetsu": ["アスファルト舗装工事"]},
    )

    result = model.reconcile(
        "koji_shubetsu",
        "アスファルト舗装工事",
        ["一般土木工事"],
    )

    assert result.applied is True
    assert result.value_preserved is True
    assert result.invalid is True
    assert result.widget_values == (
        "",
        "一般土木工事",
        "アスファルト舗装工事",
    )
    assert "再選択が必要" in result.reason
    assert [option.label for option in model.options("koji_shubetsu")] == [
        "一般土木工事"
    ]


def test_dynamic_option_request_token_is_immutable():
    token = DynamicOptionRequestToken(
        field="place_todofuken",
        generation=3,
        parent_values=("関東",),
        user_revision=7,
    )

    with pytest.raises(FrozenInstanceError):
        token.generation = 4

