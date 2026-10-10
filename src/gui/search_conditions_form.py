# -*- coding: utf-8 -*-

"""メイン画面と定期実行編集画面で共有する検索候補モデル。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
from typing import Iterable, Mapping, Sequence

from ..models.config_model import SearchConditions
from ..models.search_target import SearchTarget


PLACE_CHIHOU_OPTIONS = (
    "北海道",
    "東北",
    "関東",
    "北陸",
    "中部",
    "近畿",
    "中国",
    "四国",
    "九州・沖縄",
)

# 互換export。発注機関候補は公式サイト取得だけを正本とし、固定候補は持たない。
HACHU_DAIBUNRUI_FALLBACK_OPTIONS: tuple[str, ...] = ()

CONTRACT_TYPE_OPTIONS = (
    "一般競争入札",
    "公募型指名競争入札",
    "指名競争入札",
    "随意契約",
    "その他方式",
)

KOJI_SHUBETSU_OPTIONS = (
    "一般土木工事",
    "アスファルト舗装工事",
    "鋼橋上部工事",
    "造園工事",
    "建築工事",
    "木造建築工事",
    "電気設備工事",
    "暖冷房衛生設備工事",
    "セメント・コンクリート舗装工事",
    "プレストレスト・コンクリート工事",
    "法面処理工事",
    "塗装工事",
    "維持修繕工事",
    "浚渫工事",
    "グラウト工事",
    "杭打工事",
    "さく井工事",
    "プレハブ建築工事",
    "機械設備工事",
    "通信設備工事",
    "受変電設備工事",
    "港湾土木工事",
    "農林土木工事",
    "農林建築工事",
    "橋梁補修工事",
    "その他",
)

KOJI_GYOUSHU_OPTIONS = (
    "土木一式工事",
    "建築一式工事",
    "大工工事",
    "左官工事",
    "とび・土工・コンクリート工事",
    "石工事",
    "屋根工事",
    "電気工事",
    "管工事",
    "タイル・れんが・ブロック工事",
    "鋼構造物工事",
    "鉄筋工事",
    "舗装工事",
    "浚渫工事",
    "板金工事",
    "ガラス工事",
    "塗装工事",
    "防水工事",
    "内装仕上工事",
    "機械器具設置工事",
    "熱絶縁工事",
    "電気通信工事",
    "造園工事",
    "さく井工事",
    "建具工事",
    "水道施設工事",
    "消防施設工事",
    "清掃施設工事",
    "解体工事",
    "その他",
)

DYNAMIC_FIELD_LABELS = {
    "hachu_daibunrui": "発注機関・大分類",
    "hachu_chubunrui": "発注機関・中分類",
    "hachu_shoubunrui": "発注機関・小分類",
    "hachu_saibunrui": "発注機関・細分類",
    "place_chihou": "地方",
    "place_todofuken": "都道府県",
    "place_shichouson": "市区町村",
    "koji_shubetsu": "工事種別",
    "koji_gyoushu": "工事の業種",
    "gyomu_kubun": "業務区分",
}


@dataclass(frozen=True)
class SearchOption:
    """対象サイトのvalue（コード）と利用者向け表示名。"""

    code: str
    label: str


@dataclass(frozen=True)
class DynamicOptionRequestToken:
    """非同期候補取得を開始した時点の選択状態。"""

    field: str
    generation: int
    parent_values: tuple[str, ...]
    user_revision: int


@dataclass(frozen=True)
class OptionReconcileResult:
    """取得候補と画面上の現在値を照合した結果。"""

    applied: bool
    value_preserved: bool
    invalid: bool
    reason: str
    widget_values: tuple[str, ...]
    selected_value: str = ""


def _combobox_popdown_is_open(combobox: ttk.Combobox) -> bool:
    """ttk Comboboxの候補一覧が表示中かを安全に判定する。"""

    try:
        popdown = combobox.tk.call(
            "ttk::combobox::PopdownWindow", str(combobox)
        )
        mapped = combobox.tk.call("winfo", "ismapped", popdown)
        return bool(int(mapped))
    except (AttributeError, tk.TclError, TypeError, ValueError):
        # Tcl/Tkの破棄中や、Tk実装差で内部コマンドが利用できない場合は、
        # 閉じたComboboxとして標準の値変更を抑止する側へ倒す。
        return False


def _mousewheel_scroll_units(event: object) -> int:
    delta = int(getattr(event, "delta", 0) or 0)
    if not delta:
        return 0
    units = int(-delta / 120)
    if units:
        return units
    # 高解像度ホイール／タッチパッドの120未満のdeltaも1単位流す。
    return -1 if delta > 0 else 1


def bind_combobox_mousewheel_to_canvas(
    combobox: ttk.Combobox,
    canvas: tk.Canvas,
) -> str | None:
    """閉じた検索Comboboxのホイール操作をCanvasへ転送する。

    Widgetレベルのbindingがttkのclass bindingより先に動き、``"break"``を
    返すことで選択値の変更を防ぐ。候補一覧が開いている間は処理せず、一覧の
    通常スクロールを維持する。
    """

    previous = getattr(combobox, "_ippi_mousewheel_canvas_binding", None)
    if previous is not None and previous[0] is canvas:
        return previous[1]
    if previous is not None:
        try:
            combobox.unbind("<MouseWheel>", previous[1])
        except (AttributeError, tk.TclError, TypeError):
            pass

    def on_mousewheel(event: object) -> str | None:
        if _combobox_popdown_is_open(combobox):
            return None
        units = _mousewheel_scroll_units(event)
        if units:
            try:
                canvas.yview_scroll(units, "units")
            except (AttributeError, tk.TclError):
                pass
        return "break"

    bind_id = combobox.bind("<MouseWheel>", on_mousewheel, add="+")
    combobox._ippi_mousewheel_canvas_binding = (canvas, bind_id)
    return bind_id


def bind_search_comboboxes_to_canvas(
    container: tk.Misc,
    canvas: tk.Canvas,
) -> tuple[str | None, ...]:
    """container配下にある全検索Comboboxへホイール保護を適用する。"""

    binding_ids: list[str | None] = []
    for child in container.winfo_children():
        if isinstance(child, ttk.Combobox):
            binding_ids.append(bind_combobox_mousewheel_to_canvas(child, canvas))
        binding_ids.extend(bind_search_comboboxes_to_canvas(child, canvas))
    return tuple(binding_ids)


def normalise_search_options(values: Iterable[object]) -> tuple[SearchOption, ...]:
    """文字列・(code, label)・dictを重複のない候補へ正規化する。"""

    result: list[SearchOption] = []
    seen: set[tuple[str, str]] = set()
    for raw in values or ():
        if isinstance(raw, SearchOption):
            option = raw
        elif hasattr(raw, "code") and hasattr(raw, "label"):
            # AgencyOptionなど、対象サイトのコード付き候補をそのまま受け取る。
            # repr文字列へ潰すと、定期実行編集画面だけコードを失うため、
            # GUI共通の候補モデルで明示的に扱う。
            option = SearchOption(
                str(getattr(raw, "code", "") or "").strip(),
                str(getattr(raw, "label", "") or "").strip(),
            )
        elif isinstance(raw, Mapping):
            code = str(raw.get("value") or raw.get("code") or "").strip()
            label = str(raw.get("label") or raw.get("text") or code).strip()
            option = SearchOption(code, label)
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            if len(raw) < 2:
                continue
            option = SearchOption(str(raw[0]).strip(), str(raw[1]).strip())
        else:
            text = str(raw or "").strip()
            option = SearchOption(text, text)
        if option.code in {"", "-1"} or not option.label:
            continue
        key = (option.code, option.label)
        if key not in seen:
            seen.add(key)
            result.append(option)
    return tuple(result)


def validate_search_condition_structure(search: SearchConditions) -> list[str]:
    """親のない階層値など、候補取得に依存しない不整合を返す。"""

    errors: list[str] = []
    hierarchies = [
        (
            "hachu_daibunrui",
            "hachu_chubunrui",
            "hachu_shoubunrui",
            "hachu_saibunrui",
        )
    ]
    if search.place_search_type == "list":
        hierarchies.append(("place_chihou", "place_todofuken", "place_shichouson"))
    for fields in hierarchies:
        parent_selected = True
        for field in fields:
            value = str(getattr(search, field, "") or "").strip()
            if value and not parent_selected:
                errors.append(
                    f"{DYNAMIC_FIELD_LABELS[field]}の上位項目を選択してください"
                )
            parent_selected = parent_selected and bool(value)
    return errors


class SearchConditionOptionModel:
    """候補の表示名↔コードと、保存済み未知値の扱いを一元化する。"""

    def __init__(
        self,
        initial: SearchConditions,
        options: Mapping[str, Iterable[object]] | None = None,
    ) -> None:
        self.initial = deepcopy(initial)
        self._options: dict[str, tuple[SearchOption, ...]] = {}
        for field, values in (options or {}).items():
            self.update(field, values)

    def set_initial(self, search: SearchConditions) -> None:
        self.initial = deepcopy(search)

    def update(self, field: str, values: Iterable[object]) -> None:
        if field in DYNAMIC_FIELD_LABELS:
            self._options[field] = normalise_search_options(values)

    def reconcile(
        self,
        field: str,
        current: str,
        values: Iterable[object],
    ) -> OptionReconcileResult:
        """最新候補を反映し、現在値を候補一覧から黙って消さない。"""

        if field not in DYNAMIC_FIELD_LABELS:
            return OptionReconcileResult(
                applied=False,
                value_preserved=True,
                invalid=False,
                reason=f"未対応の検索候補項目です: {field}",
                widget_values=(),
                selected_value=str(current or "").strip(),
            )

        self.update(field, values)
        requested = str(current or "").strip()
        match = self._match(field, requested)
        selected_value = match.label if match is not None else requested
        widget_values = self.widget_values(field, selected_value)
        value_preserved = not requested or selected_value in widget_values
        invalid = bool(requested and match is None)
        reason = (
            f"{DYNAMIC_FIELD_LABELS[field]}「{requested}」は最新候補にありません。"
            "再選択が必要です"
            if invalid
            else ""
        )
        return OptionReconcileResult(
            applied=True,
            value_preserved=value_preserved,
            invalid=invalid,
            reason=reason,
            widget_values=widget_values,
            selected_value=selected_value,
        )

    def options(self, field: str) -> tuple[SearchOption, ...]:
        return self._options.get(field, ())

    def widget_values(self, field: str, current: str = "") -> tuple[str, ...]:
        labels = [option.label for option in self.options(field)]
        value = str(current or "").strip()
        match = self._match(field, value)
        if match is not None:
            value = match.label
        if value and value not in labels:
            # 旧設定のコードや、サイトから消えた表示名を黙って消さない。
            labels.append(value)
        return tuple(dict.fromkeys(("", *labels)))

    def _match(self, field: str, value: str) -> SearchOption | None:
        requested = str(value or "").strip()
        return next(
            (
                option
                for option in self.options(field)
                if requested in {option.code, option.label}
            ),
            None,
        )

    def contains(self, field: str, value: str) -> bool:
        """表示名またはコードが取得済み候補に存在するか返す。"""

        requested = str(value or "").strip()
        return not requested or self._match(field, requested) is not None

    def display_value(self, field: str, value: str) -> str:
        """送信コードを対応する表示名へ正規化する。"""

        requested = str(value or "").strip()
        match = self._match(field, requested)
        return match.label if match is not None else requested

    def warnings(self, search: SearchConditions) -> list[str]:
        warnings: list[str] = []
        for field, label in DYNAMIC_FIELD_LABELS.items():
            value = str(getattr(search, field, "") or "").strip()
            if not value:
                continue
            options = self.options(field)
            match = self._match(field, value)
            if match is not None and value == match.code and match.code != match.label:
                warnings.append(
                    f"{label}: コード「{value}」（表示名「{match.label}」）を保持中"
                )
            elif options and match is None:
                warnings.append(f"{label}: 保存済みの未知値「{value}」を保持中")
            elif not options:
                warnings.append(f"{label}: 候補未取得の保存値「{value}」を保持中")
        return warnings

    def validate(self, search: SearchConditions) -> list[str]:
        errors = validate_search_condition_structure(search)
        for field, label in DYNAMIC_FIELD_LABELS.items():
            if field.startswith("place_") and search.place_search_type != "list":
                continue
            if (
                search.target == SearchTarget.GYOMU_KEIKA
                and field in {"koji_shubetsu", "koji_gyoushu"}
            ):
                continue
            if (
                search.target == SearchTarget.KOJI_KEIKA
                and field == "gyomu_kubun"
            ):
                continue
            value = str(getattr(search, field, "") or "").strip()
            options = self.options(field)
            if not value or not options or self._match(field, value) is not None:
                continue
            # 保存済みの値も画面から黙って消さないが、最新候補と
            # 一致しない状態のまま実行・保存はさせない。旧値を特別扱い
            # すると、サイト側の候補変更後に別条件で実行され得る。
            errors.append(
                f"{label}「{value}」は対象サイトの最新候補にありません。"
                "候補から選択し直してください"
            )
        return errors


__all__ = [
    "CONTRACT_TYPE_OPTIONS",
    "DYNAMIC_FIELD_LABELS",
    "DynamicOptionRequestToken",
    "HACHU_DAIBUNRUI_FALLBACK_OPTIONS",
    "KOJI_GYOUSHU_OPTIONS",
    "KOJI_SHUBETSU_OPTIONS",
    "OptionReconcileResult",
    "PLACE_CHIHOU_OPTIONS",
    "SearchConditionOptionModel",
    "SearchOption",
    "bind_combobox_mousewheel_to_canvas",
    "bind_search_comboboxes_to_canvas",
    "normalise_search_options",
    "validate_search_condition_structure",
]
