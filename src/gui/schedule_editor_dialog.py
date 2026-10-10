# -*- coding: utf-8 -*-

"""保存済み定期実行条件を追加・編集するモーダル。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import inspect
import json
from queue import Empty, Queue
import re
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from .window_layout import fit_to_screen
from typing import Callable, Mapping, Optional

from ..models.config_model import AppConfig, ScheduleConfig, SearchConditions
from ..models.search_target import SearchTarget
from ..core.search_profiles import get_search_profile, search_profiles
from ..storage.layout import RunKind
from .schedule_management import format_storage_preview
from .option_load_coordinator import OptionLoadCoordinator
from .search_conditions_form import (
    DYNAMIC_FIELD_LABELS,
    DynamicOptionRequestToken,
    HACHU_DAIBUNRUI_FALLBACK_OPTIONS,
    KOJI_GYOUSHU_OPTIONS,
    KOJI_SHUBETSU_OPTIONS,
    PLACE_CHIHOU_OPTIONS,
    SearchConditionOptionModel,
    bind_search_comboboxes_to_canvas,
)


_NOTIFICATION_POLICY_TO_DISPLAY = {
    "off": "通知しない",
    "important_only": "重要な結果のみ（新規保存・失敗など）",
    "all_results": "すべての実行結果",
    "failures_only": "失敗時のみ",
}
_DISPLAY_TO_NOTIFICATION_POLICY = {
    display: policy for policy, display in _NOTIFICATION_POLICY_TO_DISPLAY.items()
}


def normalise_schedule_notification_policy(value: object) -> str:
    """enum・文字列・旧設定欠落をGUI用の安定値へ正規化する。"""

    raw = getattr(value, "value", value)
    text = str(raw or "off").strip()
    if text in _DISPLAY_TO_NOTIFICATION_POLICY:
        return _DISPLAY_TO_NOTIFICATION_POLICY[text]
    policy = text.lower()
    return policy if policy in _NOTIFICATION_POLICY_TO_DISPLAY else "off"


def format_schedule_notification_policy(value: object) -> str:
    """通知方針を日本語表示へ変換する。"""

    return _NOTIFICATION_POLICY_TO_DISPLAY[
        normalise_schedule_notification_policy(value)
    ]


@dataclass(frozen=True)
class ScheduleEditorResult:
    name: str
    config: AppConfig


class ScheduleEditorDialog:
    """1件だけを編集し、確定内容を呼出し側へ返す。"""

    _INTERVAL_TO_DISPLAY = {
        "daily": "毎日",
        "weekly": "毎週",
        "monthly": "毎月",
    }
    _DISPLAY_TO_INTERVAL = {
        display: interval for interval, display in _INTERVAL_TO_DISPLAY.items()
    }
    _WEEKDAY_TO_DISPLAY = {
        "monday": "月曜日",
        "tuesday": "火曜日",
        "wednesday": "水曜日",
        "thursday": "木曜日",
        "friday": "金曜日",
        "saturday": "土曜日",
        "sunday": "日曜日",
    }
    _DISPLAY_TO_WEEKDAY = {
        display: weekday for weekday, display in _WEEKDAY_TO_DISPLAY.items()
    }

    def __init__(
        self,
        parent: tk.Misc,
        config: AppConfig,
        *,
        name: str,
        title: str,
        current_config_provider: Optional[Callable[[], AppConfig]] = None,
        validator: Optional[Callable[[AppConfig], tuple[bool, list[str]]]] = None,
        dynamic_validator: Optional[
            Callable[[AppConfig], tuple[bool, list[str]]]
        ] = None,
        search_options_provider: Optional[
            Callable[[], Mapping[str, tuple[object, ...]]]
        ] = None,
        search_option_loader: Optional[
            Callable[..., list[object]]
        ] = None,
        search_options_reloader: Optional[Callable[[], None]] = None,
        summary_formatter: Optional[Callable[[AppConfig], str]] = None,
        option_load_coordinator: Optional[OptionLoadCoordinator] = None,
    ) -> None:
        self._config = deepcopy(config)
        self._current_config_provider = current_config_provider
        self._validator = validator
        self._dynamic_validator = dynamic_validator
        self._search_option_loader = search_option_loader
        self._search_options_reloader = search_options_reloader
        self._summary_formatter = summary_formatter or (lambda _config: "")
        self.result: Optional[ScheduleEditorResult] = None
        try:
            initial_options = (
                dict(search_options_provider() or {})
                if search_options_provider is not None
                else {}
            )
        except (RuntimeError, tk.TclError, ValueError):
            initial_options = {}
        initial_options.setdefault("hachu_daibunrui", HACHU_DAIBUNRUI_FALLBACK_OPTIONS)
        initial_options.setdefault("place_chihou", PLACE_CHIHOU_OPTIONS)
        initial_options.setdefault("koji_shubetsu", KOJI_SHUBETSU_OPTIONS)
        initial_options.setdefault("koji_gyoushu", KOJI_GYOUSHU_OPTIONS)
        initial_options.setdefault("gyomu_kubun", ())
        self._search_option_model = SearchConditionOptionModel(
            self._config.search_conditions,
            initial_options,
        )
        self._dynamic_combos: dict[str, ttk.Combobox] = {}
        self._option_queue: Queue = Queue(maxsize=32)
        self._owns_option_coordinator = option_load_coordinator is None
        self._option_coordinator = (
            option_load_coordinator
            if option_load_coordinator is not None
            else OptionLoadCoordinator(name="ippi-schedule-option-loader")
        )
        self._option_task_keys: set[str] = set()
        self._option_generations: dict[str, int] = {}
        self._option_user_revisions: dict[str, int] = {}
        self._option_loading: set[str] = set()
        self._option_errors: dict[str, str] = {}
        self._option_cancel_events: dict[str, Event] = {}
        self._option_reload_running = False
        self._option_poll_after_id = None
        self._test_notification_running = False
        self._closed = False
        self._target_drafts: dict[str, dict[str, str]] = {}

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        fit_to_screen(
            self.dialog, 820, 690, minimum_width=600, minimum_height=440
        )
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_cancel)

        outer = ttk.Frame(self.dialog, padding="10")
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        identity = ttk.Frame(outer)
        identity.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        identity.columnconfigure(1, weight=1)
        ttk.Label(identity, text="条件名:").grid(row=0, column=0, sticky=tk.W)
        self.name_var = tk.StringVar(value=name)
        ttk.Entry(identity, textvariable=self.name_var).grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(8, 0)
        )

        notebook = ttk.Notebook(outer)
        notebook.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        condition_tab = ttk.Frame(notebook, padding="10")
        schedule_tab = ttk.Frame(notebook, padding="10")
        notebook.add(condition_tab, text="実行条件")
        notebook.add(schedule_tab, text="実行予定")
        self._setup_condition_tab(condition_tab)
        self._setup_schedule_tab(schedule_tab)

        buttons = ttk.Frame(outer)
        buttons.grid(row=2, column=0, sticky=tk.E, pady=(10, 0))
        ttk.Button(buttons, text="キャンセル", command=self._on_cancel).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(buttons, text="保存", command=self._on_save).pack(side=tk.RIGHT)

        self._load_config(self._config)
        self._refresh_all_dynamic_combos()
        self._update_place_search_mode()
        self._refresh_dynamic_option_status()
        self._initial_ui_fingerprint = self._state_fingerprint()
        if self._search_option_loader is not None:
            self._option_poll_after_id = self.dialog.after(100, self._poll_option_queue)
            self._load_initial_dynamic_options()

    def _setup_condition_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        condition_notebook = ttk.Notebook(parent)
        condition_notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        search_tab = ttk.Frame(condition_notebook, padding="6")
        output_tab = ttk.Frame(condition_notebook, padding="10")
        condition_notebook.add(search_tab, text="検索条件")
        condition_notebook.add(output_tab, text="取得・保存条件")

        canvas = tk.Canvas(search_tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(search_tab, orient="vertical", command=canvas.yview)
        search_form = ttk.Frame(canvas)
        search_form.columnconfigure(0, weight=1)
        canvas_window = canvas.create_window((0, 0), window=search_form, anchor="nw")
        search_form.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, width=event.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        organisation = ttk.LabelFrame(search_form, text="発注機関", padding="8")
        organisation.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        organisation.columnconfigure(1, weight=1)
        organisation.columnconfigure(3, weight=1)
        self.hachu_daibunrui_var = tk.StringVar()
        self.hachu_chubunrui_var = tk.StringVar()
        self.hachu_shoubunrui_var = tk.StringVar()
        self.hachu_saibunrui_var = tk.StringVar()
        self.hachu_multi_var = tk.StringVar()
        for row, (field, label, variable) in enumerate(
            (
                ("hachu_daibunrui", "大分類:", self.hachu_daibunrui_var),
                ("hachu_chubunrui", "中分類:", self.hachu_chubunrui_var),
                ("hachu_shoubunrui", "小分類:", self.hachu_shoubunrui_var),
                ("hachu_saibunrui", "細分類:", self.hachu_saibunrui_var),
            )
        ):
            column = 0 if row % 2 == 0 else 2
            grid_row = row // 2
            ttk.Label(organisation, text=label).grid(
                row=grid_row, column=column, sticky=tk.W, padx=(0, 6), pady=2
            )
            combo = ttk.Combobox(
                organisation,
                textvariable=variable,
                state="readonly",
            )
            combo.grid(
                row=grid_row,
                column=column + 1,
                sticky=(tk.W, tk.E),
                padx=(0, 12),
                pady=2,
            )
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _event, selected=field: self._on_dynamic_option_selected(
                    selected
                ),
            )
            self._dynamic_combos[field] = combo
        ttk.Label(organisation, text="複数指定（旧設定）:").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 6), pady=2
        )
        ttk.Entry(
            organisation,
            textvariable=self.hachu_multi_var,
            state="readonly",
        ).grid(row=2, column=1, columnspan=3, sticky=(tk.W, tk.E), pady=2)
        ttk.Label(
            organisation,
            text=("発注機関は候補から直接変更できます。旧複数指定は互換表示のみです。"),
            foreground="#666666",
        ).grid(row=4, column=0, columnspan=4, sticky=tk.W, pady=(4, 0))
        self._agency_reload_button = ttk.Button(
            organisation,
            text="発注機関候補を再読み込み",
            command=self._reload_agency_options,
            state=("normal" if self._search_options_reloader else "disabled"),
        )
        self._agency_reload_button.grid(
            row=3, column=3, sticky=tk.E, padx=(0, 12), pady=(4, 0)
        )
        ttk.Label(organisation, text="検索対象:").grid(
            row=3, column=0, sticky=tk.W, padx=(0, 6), pady=(4, 0)
        )
        self.search_target_var = tk.StringVar()
        self.search_target_combo = ttk.Combobox(
            organisation,
            textvariable=self.search_target_var,
            values=tuple(
                profile.display_label for profile in search_profiles()
            ),
            state="readonly",
        )
        self.search_target_combo.grid(
            row=3, column=1, sticky=(tk.W, tk.E), padx=(0, 12), pady=(4, 0)
        )
        self.search_target_combo.bind(
            "<<ComboboxSelected>>", self._on_search_target_changed
        )

        names_place = ttk.LabelFrame(search_form, text="工事名・工事場所", padding="8")
        self.names_place_frame = names_place
        names_place.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        names_place.columnconfigure(1, weight=1)
        names_place.columnconfigure(3, weight=1)
        self.koji_name_var = tk.StringVar()
        self.place_search_type_var = tk.StringVar()
        self.place_chihou_var = tk.StringVar()
        self.place_todofuken_var = tk.StringVar()
        self.place_shichouson_var = tk.StringVar()
        self.place_text_var = tk.StringVar()
        self.project_name_label = ttk.Label(names_place, text="工事名:")
        self.project_name_label.grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(names_place, textvariable=self.koji_name_var).grid(
            row=0, column=1, columnspan=3, sticky=(tk.W, tk.E), pady=2
        )
        ttk.Label(names_place, text="場所指定:").grid(row=1, column=0, sticky=tk.W)
        self.place_search_type_combo = ttk.Combobox(
            names_place,
            textvariable=self.place_search_type_var,
            values=("list", "text"),
            state="readonly",
            width=8,
        )
        self.place_search_type_combo.grid(row=1, column=1, sticky=tk.W, pady=2)
        self.place_search_type_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._update_place_search_mode(),
        )
        for row, (field, label, variable) in enumerate(
            (
                ("place_chihou", "地方:", self.place_chihou_var),
                ("place_todofuken", "都道府県:", self.place_todofuken_var),
                ("place_shichouson", "市区町村:", self.place_shichouson_var),
                ("place_text", "文字列:", self.place_text_var),
            ),
            start=2,
        ):
            column = 0 if row % 2 == 0 else 2
            grid_row = 2 + ((row - 2) // 2)
            ttk.Label(names_place, text=label).grid(
                row=grid_row, column=column, sticky=tk.W, padx=(0, 6), pady=2
            )
            widget = (
                ttk.Entry(names_place, textvariable=variable)
                if field == "place_text"
                else ttk.Combobox(
                    names_place,
                    textvariable=variable,
                    state="readonly",
                )
            )
            widget.grid(
                row=grid_row,
                column=column + 1,
                sticky=(tk.W, tk.E),
                padx=(0, 12),
                pady=2,
            )
            if field == "place_text":
                self.place_text_entry = widget
            else:
                widget.bind(
                    "<<ComboboxSelected>>",
                    lambda _event, selected=field: self._on_dynamic_option_selected(
                        selected
                    ),
                )
                self._dynamic_combos[field] = widget

        contract = ttk.LabelFrame(search_form, text="契約方式・日付条件", padding="8")
        contract.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        contract.columnconfigure(1, weight=1)
        contract.columnconfigure(3, weight=1)
        self.contract_types_var = tk.StringVar()
        ttk.Label(contract, text="入札契約方式:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(contract, textvariable=self.contract_types_var).grid(
            row=0, column=1, columnspan=3, sticky=(tk.W, tk.E), pady=2
        )
        self.update_date_type_var = tk.StringVar()
        self.update_date_days_var = tk.StringVar()
        ttk.Label(contract, text="最終更新:").grid(row=1, column=0, sticky=tk.W)
        ttk.Combobox(
            contract,
            textvariable=self.update_date_type_var,
            values=("none", "past"),
            state="readonly",
            width=8,
        ).grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Label(contract, text="過去日数:").grid(row=1, column=2, sticky=tk.W)
        ttk.Entry(contract, textvariable=self.update_date_days_var, width=10).grid(
            row=1, column=3, sticky=tk.W, pady=2
        )
        self.koukoku_date_type_var = tk.StringVar()
        self.koukoku_date_start_var = tk.StringVar()
        self.koukoku_date_end_var = tk.StringVar()
        self.kaisatsu_date_type_var = tk.StringVar()
        self.kaisatsu_date_start_var = tk.StringVar()
        self.kaisatsu_date_end_var = tk.StringVar()
        self.keiyaku_date_type_var = tk.StringVar()
        self.keiyaku_date_start_var = tk.StringVar()
        self.keiyaku_date_end_var = tk.StringVar()
        date_rows = (
            (
                "公告日:",
                self.koukoku_date_type_var,
                self.koukoku_date_start_var,
                self.koukoku_date_end_var,
            ),
            (
                "開札日:",
                self.kaisatsu_date_type_var,
                self.kaisatsu_date_start_var,
                self.kaisatsu_date_end_var,
            ),
            (
                "契約日:",
                self.keiyaku_date_type_var,
                self.keiyaku_date_start_var,
                self.keiyaku_date_end_var,
            ),
        )
        for row, (label, mode_var, start_var, end_var) in enumerate(date_rows, start=2):
            ttk.Label(contract, text=label).grid(row=row, column=0, sticky=tk.W)
            line = ttk.Frame(contract)
            line.grid(row=row, column=1, columnspan=3, sticky=tk.W, pady=2)
            ttk.Combobox(
                line,
                textvariable=mode_var,
                values=("none", "range"),
                state="readonly",
                width=8,
            ).pack(side=tk.LEFT)
            ttk.Entry(line, textvariable=start_var, width=12).pack(
                side=tk.LEFT, padx=(8, 3)
            )
            ttk.Label(line, text="～").pack(side=tk.LEFT)
            ttk.Entry(line, textvariable=end_var, width=12).pack(
                side=tk.LEFT, padx=(3, 0)
            )

        details = ttk.LabelFrame(search_form, text="工事区分・価格等", padding="8")
        details.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        details.columnconfigure(1, weight=1)
        details.columnconfigure(3, weight=1)
        self.koji_shubetsu_var = tk.StringVar()
        self.koji_gyoushu_var = tk.StringVar()
        self.gyomu_kubun_var = tk.StringVar()
        self.yotei_price_min_var = tk.StringVar()
        self.yotei_price_max_var = tk.StringVar()
        self.rakusatsu_price_min_var = tk.StringVar()
        self.rakusatsu_price_max_var = tk.StringVar()
        self.rakusatsu_name_var = tk.StringVar()
        self.denshi_var = tk.BooleanVar()
        self.koukai_var = tk.BooleanVar()
        self.display_count_var = tk.StringVar()
        for row, (label, variable, label2, variable2) in enumerate(
            (
                (
                    "工事種別:",
                    self.koji_shubetsu_var,
                    "工事の業種:",
                    self.koji_gyoushu_var,
                ),
                (
                    "予定価格下限:",
                    self.yotei_price_min_var,
                    "上限:",
                    self.yotei_price_max_var,
                ),
                (
                    "落札価格下限:",
                    self.rakusatsu_price_min_var,
                    "上限:",
                    self.rakusatsu_price_max_var,
                ),
            )
        ):
            ttk.Label(details, text=label).grid(row=row, column=0, sticky=tk.W)
            if row == 0:
                first_widget = ttk.Combobox(
                    details, textvariable=variable, state="readonly"
                )
                self._dynamic_combos["koji_shubetsu"] = first_widget
                first_widget.bind(
                    "<<ComboboxSelected>>",
                    lambda _event: self._on_dynamic_option_selected(
                        "koji_shubetsu"
                    ),
                )
            else:
                first_widget = ttk.Entry(details, textvariable=variable)
            first_widget.grid(
                row=row,
                column=1,
                sticky=(tk.W, tk.E),
                padx=(0, 12),
                pady=2,
            )
            ttk.Label(details, text=label2).grid(row=row, column=2, sticky=tk.W)
            if row == 0:
                second_widget = ttk.Combobox(
                    details, textvariable=variable2, state="readonly"
                )
                self._dynamic_combos["koji_gyoushu"] = second_widget
                second_widget.bind(
                    "<<ComboboxSelected>>",
                    lambda _event: self._on_dynamic_option_selected(
                        "koji_gyoushu"
                    ),
                )
            else:
                second_widget = ttk.Entry(details, textvariable=variable2)
            second_widget.grid(row=row, column=3, sticky=(tk.W, tk.E), pady=2)
        ttk.Label(details, text="落札者名:").grid(row=3, column=0, sticky=tk.W)
        ttk.Entry(details, textvariable=self.rakusatsu_name_var).grid(
            row=3, column=1, columnspan=3, sticky=(tk.W, tk.E), pady=2
        )
        options = ttk.Frame(details)
        options.grid(row=4, column=0, columnspan=4, sticky=tk.W, pady=(4, 0))
        ttk.Checkbutton(options, text="電子入札のみ", variable=self.denshi_var).pack(
            side=tk.LEFT
        )
        ttk.Checkbutton(options, text="公開中のみ", variable=self.koukai_var).pack(
            side=tk.LEFT, padx=(12, 0)
        )
        ttk.Label(options, text="表示件数:").pack(side=tk.LEFT, padx=(18, 4))
        ttk.Combobox(
            options,
            textvariable=self.display_count_var,
            values=("20", "30", "50", "100"),
            state="readonly",
            width=6,
        ).pack(side=tk.LEFT)
        ttk.Label(details, text="業務区分:").grid(
            row=5, column=0, sticky=tk.W, pady=(4, 0)
        )
        self.gyomu_kubun_combobox = ttk.Combobox(
            details,
            textvariable=self.gyomu_kubun_var,
            state="readonly",
        )
        self.gyomu_kubun_combobox.grid(
            row=5,
            column=1,
            columnspan=3,
            sticky=(tk.W, tk.E),
            pady=(4, 0),
        )
        self.gyomu_kubun_combobox.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._on_dynamic_option_selected("gyomu_kubun"),
        )
        self._dynamic_combos["gyomu_kubun"] = self.gyomu_kubun_combobox
        import_frame = ttk.Frame(search_form)
        import_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(2, 6))
        ttk.Label(
            import_frame,
            text="候補は対象サイトから取得します。必要ならメイン画面条件も取り込めます。",
            foreground="#666666",
        ).pack(side=tk.LEFT)
        ttk.Button(
            import_frame,
            text="現在のメイン画面条件を取り込む",
            command=self._use_current_config,
        ).pack(side=tk.RIGHT)
        self._dynamic_option_status = tk.StringVar(value="")
        ttk.Label(
            search_form,
            textvariable=self._dynamic_option_status,
            foreground="#9a6700",
            wraplength=740,
            justify=tk.LEFT,
        ).grid(row=5, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        bind_search_comboboxes_to_canvas(search_form, canvas)

        output_tab.columnconfigure(1, weight=1)
        output_tab.rowconfigure(7, weight=1)
        ttk.Label(output_tab, text="対象URL（公式・固定）:").grid(
            row=0, column=0, sticky=tk.NW, padx=(0, 8), pady=3
        )
        self.target_urls_text = tk.Text(
            output_tab,
            height=3,
            wrap=tk.NONE,
            state=tk.DISABLED,
            takefocus=False,
        )
        self.target_urls_text.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=3)
        ttk.Label(output_tab, text="文書種別:").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 8), pady=3
        )
        self.file_types_var = tk.StringVar()
        ttk.Entry(output_tab, textvariable=self.file_types_var).grid(
            row=1, column=1, sticky=(tk.W, tk.E), pady=3
        )
        ttk.Label(output_tab, text="絞込キーワード:").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 8), pady=3
        )
        self.keywords_var = tk.StringVar()
        ttk.Entry(output_tab, textvariable=self.keywords_var).grid(
            row=2, column=1, sticky=(tk.W, tk.E), pady=3
        )
        ttk.Label(output_tab, text="文書日付範囲:").grid(
            row=3, column=0, sticky=tk.W, padx=(0, 8), pady=3
        )
        date_frame = ttk.Frame(output_tab)
        date_frame.grid(row=3, column=1, sticky=tk.W, pady=3)
        self.download_date_start_var = tk.StringVar()
        self.download_date_end_var = tk.StringVar()
        ttk.Entry(date_frame, textvariable=self.download_date_start_var, width=12).pack(
            side=tk.LEFT
        )
        ttk.Label(date_frame, text=" ～ ").pack(side=tk.LEFT)
        ttk.Entry(date_frame, textvariable=self.download_date_end_var, width=12).pack(
            side=tk.LEFT
        )
        ttk.Label(output_tab, text="データルート:").grid(
            row=4, column=0, sticky=tk.W, padx=(0, 8), pady=3
        )
        path_frame = ttk.Frame(output_tab)
        path_frame.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=3)
        path_frame.columnconfigure(0, weight=1)
        self.save_path_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.save_path_var).grid(
            row=0, column=0, sticky=(tk.W, tk.E)
        )
        ttk.Button(path_frame, text="参照...", command=self._browse_save_path).grid(
            row=0, column=1, padx=(6, 0)
        )
        self.storage_preview_var = tk.StringVar()
        ttk.Label(
            output_tab,
            textvariable=self.storage_preview_var,
            justify=tk.LEFT,
            foreground="#555555",
        ).grid(row=5, column=1, sticky=(tk.W, tk.E), pady=(2, 5))
        self.save_path_var.trace_add("write", self._update_storage_preview)
        ttk.Label(output_tab, text="ファイル名規則:").grid(
            row=6, column=0, sticky=tk.W, padx=(0, 8), pady=3
        )
        self.naming_rule_var = tk.StringVar()
        ttk.Entry(output_tab, textvariable=self.naming_rule_var).grid(
            row=6, column=1, sticky=(tk.W, tk.E), pady=3
        )
        summary_frame = ttk.LabelFrame(output_tab, text="条件要約", padding="8")
        summary_frame.grid(
            row=7,
            column=0,
            columnspan=2,
            sticky=(tk.W, tk.E, tk.N, tk.S),
            pady=(8, 0),
        )
        summary_frame.columnconfigure(0, weight=1)
        summary_frame.rowconfigure(0, weight=1)
        self.condition_summary_text = tk.Text(
            summary_frame, height=7, wrap=tk.WORD, state="disabled"
        )
        self.condition_summary_text.grid(
            row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S)
        )
        ttk.Button(
            summary_frame,
            text="現在のメイン画面条件を取り込む",
            command=self._use_current_config,
        ).grid(row=1, column=0, sticky=tk.E, pady=(8, 0))
        ttk.Label(
            summary_frame,
            text="取り込み操作を行うまで、保存済み条件は変更されません。",
            foreground="#666666",
        ).grid(row=2, column=0, sticky=tk.W, pady=(4, 0))

    def _setup_schedule_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self.enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            parent, text="この定期実行を有効にする", variable=self.enabled_var
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 8))

        ttk.Label(parent, text="実行間隔:").grid(row=1, column=0, sticky=tk.W)
        self.interval_var = tk.StringVar()
        self.interval_combo = ttk.Combobox(
            parent,
            textvariable=self.interval_var,
            values=list(self._DISPLAY_TO_INTERVAL),
            state="readonly",
            width=10,
        )
        self.interval_combo.grid(row=1, column=1, sticky=tk.W, pady=3)
        self.interval_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._update_schedule_fields()
        )

        ttk.Label(parent, text="実行時刻:").grid(
            row=1, column=2, sticky=tk.W, padx=(18, 6)
        )
        self.time_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.time_var, width=8).grid(
            row=1, column=3, sticky=tk.W
        )
        ttk.Label(parent, text="HH:MM").grid(row=1, column=4, sticky=tk.W)

        ttk.Label(parent, text="曜日:").grid(row=2, column=0, sticky=tk.W)
        self.weekday_var = tk.StringVar()
        self.weekday_combo = ttk.Combobox(
            parent,
            textvariable=self.weekday_var,
            values=list(self._DISPLAY_TO_WEEKDAY),
            state="readonly",
            width=10,
        )
        self.weekday_combo.grid(row=2, column=1, sticky=tk.W, pady=3)

        ttk.Label(parent, text="毎月の実行日:").grid(
            row=2, column=2, sticky=tk.W, padx=(18, 6)
        )
        self.day_var = tk.StringVar()
        self.day_spinbox = ttk.Spinbox(
            parent, textvariable=self.day_var, from_=1, to=28, width=5
        )
        self.day_spinbox.grid(row=2, column=3, sticky=tk.W)
        ttk.Label(parent, text="日（1～28）").grid(row=2, column=4, sticky=tk.W)

        self.start_when_available_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            parent,
            text="実行漏れ時にPC起動後1回だけ実行",
            variable=self.start_when_available_var,
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=4)
        self.wake_to_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="スリープを解除して実行",
            variable=self.wake_to_run_var,
        ).grid(row=3, column=3, columnspan=2, sticky=tk.W, pady=4)

        retry = ttk.Frame(parent)
        retry.grid(row=4, column=0, columnspan=5, sticky=tk.W, pady=4)
        ttk.Label(retry, text="一時障害の再試行:").pack(side=tk.LEFT)
        self.retry_count_var = tk.StringVar()
        ttk.Spinbox(
            retry, textvariable=self.retry_count_var, from_=0, to=10, width=4
        ).pack(side=tk.LEFT, padx=(6, 2))
        ttk.Label(retry, text="回 / 間隔").pack(side=tk.LEFT)
        self.retry_interval_var = tk.StringVar()
        ttk.Spinbox(
            retry,
            textvariable=self.retry_interval_var,
            from_=1,
            to=1440,
            width=5,
        ).pack(side=tk.LEFT, padx=(6, 2))
        ttk.Label(retry, text="分").pack(side=tk.LEFT)
        ttk.Label(parent, text="タイムゾーン: 日本標準時（Asia/Tokyo）").grid(
            row=5, column=0, columnspan=5, sticky=tk.W, pady=(8, 0)
        )
        ttk.Label(
            parent,
            text=(
                "Windowsタスクへ登録後はGUIを閉じても実行できます。"
                "Windowsへのログオンが必要です。"
            ),
            foreground="#666666",
        ).grid(row=6, column=0, columnspan=5, sticky=tk.W, pady=(8, 0))

        ttk.Label(parent, text="完了通知:").grid(
            row=7, column=0, sticky=tk.W, pady=(8, 0)
        )
        self.notification_policy_var = tk.StringVar(value="通知しない")
        self.notification_policy_combo = ttk.Combobox(
            parent,
            textvariable=self.notification_policy_var,
            values=list(_DISPLAY_TO_NOTIFICATION_POLICY),
            state="readonly",
            width=36,
        )
        self.notification_policy_combo.grid(
            row=7, column=1, columnspan=3, sticky=tk.W, pady=(8, 0)
        )
        self.btn_test_notification = ttk.Button(
            parent,
            text="テスト通知",
            command=self._on_test_notification,
        )
        self.btn_test_notification.grid(
            row=7, column=4, sticky=tk.W, padx=(8, 0), pady=(8, 0)
        )
        ttk.Label(
            parent,
            text=(
                "通知は補助機能です。集中モードや組織のポリシーにより"
                "表示されない場合も、実行履歴とログには結果が残ります。"
            ),
            foreground="#666666",
            wraplength=700,
            justify=tk.LEFT,
        ).grid(row=8, column=0, columnspan=5, sticky=(tk.W, tk.E), pady=(4, 0))

    @staticmethod
    def _parse_list(value: str, *, extensions: bool = False) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in value.replace("、", ",").replace("\n", ",").split(","):
            item = raw.strip()
            if not item:
                continue
            if extensions:
                item = item.lower()
                if not item.startswith("."):
                    item = f".{item}"
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _load_config(self, config: AppConfig) -> None:
        self._load_runtime_fields(config)
        self._load_search_fields(config.search_conditions)
        schedule = config.schedule
        self.enabled_var.set(schedule.enabled)
        self.interval_var.set(self._INTERVAL_TO_DISPLAY.get(schedule.interval, "毎日"))
        self.time_var.set(schedule.time)
        self.weekday_var.set(self._WEEKDAY_TO_DISPLAY.get(schedule.weekday, "月曜日"))
        self.day_var.set(str(schedule.day_of_month))
        self.start_when_available_var.set(schedule.start_when_available)
        self.wake_to_run_var.set(schedule.wake_to_run)
        self.retry_count_var.set(str(schedule.retry_count))
        self.retry_interval_var.set(str(schedule.retry_interval_minutes))
        self.notification_policy_var.set(
            format_schedule_notification_policy(
                getattr(schedule, "notification_policy", "off")
            )
        )
        self._update_schedule_fields()
        self._update_condition_summary()

    @staticmethod
    def _send_test_notification() -> object:
        """通知実装を遅延読込し、GUI起動自体への依存を避ける。"""

        from ..utils.scheduled_notifier import ScheduledRunNotifier

        notifier = ScheduledRunNotifier()
        test_notification = getattr(notifier, "test_notification", None)
        if not callable(test_notification):
            # 実装移行中の旧名称を1リリースだけ許容する。
            test_notification = getattr(notifier, "notify_test", None)
        if not callable(test_notification):
            raise RuntimeError("テスト通知機能を利用できません")
        return test_notification(
            title="ippi-down テスト通知",
            message="定期実行の完了通知を表示できます。",
        )

    @staticmethod
    def _test_notification_succeeded(result: object) -> bool:
        reason_code = str(getattr(result, "reason_code", "") or "").upper()
        if reason_code == "NOTIFICATION_SUBMITTED":
            return True
        for attribute in ("delivered", "submitted", "success"):
            value = getattr(result, attribute, None)
            if value is not None:
                return bool(value)
        return False

    def _on_test_notification(self) -> None:
        """短命な通知処理だけをワーカーへ送り、Tkを停止させない。"""

        if self._test_notification_running:
            return
        self._test_notification_running = True
        self.btn_test_notification.configure(state="disabled")

        def worker() -> None:
            try:
                result = self._send_test_notification()
                error = None
            except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
                result, error = None, str(exc)
            if self._closed:
                return
            try:
                self.dialog.after(
                    0,
                    self._finish_test_notification,
                    result,
                    error,
                )
            except tk.TclError:
                pass

        Thread(
            target=worker,
            name="ippi-test-notification",
            daemon=True,
        ).start()

    def _finish_test_notification(
        self,
        result: object,
        error: Optional[str] = None,
    ) -> None:
        self._test_notification_running = False
        if self._closed:
            return
        self.btn_test_notification.configure(state="normal")
        if error or not self._test_notification_succeeded(result):
            reason_code = str(
                getattr(result, "reason_code", "NOTIFICATION_FAILED")
                or "NOTIFICATION_FAILED"
            )
            detail = error or str(
                getattr(result, "reason", "通知を表示できませんでした")
            )
            messagebox.showwarning(
                "テスト通知",
                f"{detail} [{reason_code}]\n実行結果はログから確認できます。",
                parent=self.dialog,
            )
            return
        messagebox.showinfo(
            "テスト通知",
            "テスト通知を送信しました。",
            parent=self.dialog,
        )

    def _update_condition_summary(self) -> None:
        text = self._summary_formatter(self._config)
        self.condition_summary_text.configure(state="normal")
        self.condition_summary_text.delete("1.0", tk.END)
        self.condition_summary_text.insert("1.0", text)
        self.condition_summary_text.configure(state="disabled")

    def _update_schedule_fields(self) -> None:
        interval = self.interval_var.get()
        self.weekday_combo.configure(
            state="readonly" if interval == "毎週" else "disabled"
        )
        self.day_spinbox.configure(state="normal" if interval == "毎月" else "disabled")

    def _dynamic_variable(self, field: str) -> tk.StringVar:
        return getattr(self, f"{field}_var")

    def _current_dynamic_search(self) -> SearchConditions:
        search = deepcopy(self._config.search_conditions)
        for field in self._dynamic_combos:
            setattr(search, field, self._dynamic_variable(field).get().strip())
        search.place_search_type = self.place_search_type_var.get()
        return search

    def _refresh_dynamic_combo(self, field: str) -> None:
        combo = self._dynamic_combos.get(field)
        if combo is None:
            return
        current = self._dynamic_variable(field).get().strip()
        display_value = self._search_option_model.display_value(field, current)
        if display_value != current:
            self._dynamic_variable(field).set(display_value)
            current = display_value
        combo.configure(values=self._search_option_model.widget_values(field, current))
        parents = self._parents_for_option(field)
        parent_missing = bool(parents) and any(not value for value in parents)
        state = (
            "disabled"
            if field in self._option_loading or parent_missing
            else "readonly"
        )
        if field.startswith("place_") and self.place_search_type_var.get() != "list":
            state = "disabled"
        target_var = getattr(self, "search_target_var", None)
        target = (
            self._target_from_display(target_var.get())
            if target_var is not None
            else self._config.search_conditions.target
        )
        if target == SearchTarget.GYOMU_KEIKA and field in {
            "koji_shubetsu",
            "koji_gyoushu",
        }:
            state = "disabled"
        if target == SearchTarget.KOJI_KEIKA and field == "gyomu_kubun":
            state = "disabled"
        combo.configure(state=state)

    def _refresh_all_dynamic_combos(self) -> None:
        for field in self._dynamic_combos:
            self._refresh_dynamic_combo(field)

    def _update_place_search_mode(self) -> None:
        use_list = self.place_search_type_var.get() == "list"
        for field in ("place_chihou", "place_todofuken", "place_shichouson"):
            combo = self._dynamic_combos.get(field)
            if combo is not None:
                combo.configure(
                    state=(
                        "readonly"
                        if use_list and field not in self._option_loading
                        else "disabled"
                    )
                )
        if hasattr(self, "place_text_entry"):
            self.place_text_entry.configure(state="disabled" if use_list else "normal")
        self._refresh_dynamic_option_status()

    @staticmethod
    def _target_from_display(value: str) -> SearchTarget:
        for profile in search_profiles():
            if value in {profile.display_label, profile.target.value}:
                return profile.target
        return SearchTarget.KOJI_KEIKA

    def _target_draft_values(self) -> dict[str, str]:
        fields = (
            "hachu_daibunrui",
            "hachu_chubunrui",
            "hachu_shoubunrui",
            "hachu_saibunrui",
            "koji_name",
            "place_search_type",
            "place_chihou",
            "place_todofuken",
            "place_shichouson",
            "place_text",
            "contract_types",
            "koji_shubetsu",
            "koji_gyoushu",
            "gyomu_kubun",
        )
        return {
            field: str(getattr(self, f"{field}_var").get())
            for field in fields
        }

    @staticmethod
    def _default_target_draft(target: SearchTarget) -> dict[str, str]:
        search = SearchConditions.for_target(target)
        return {
            "hachu_daibunrui": "",
            "hachu_chubunrui": "",
            "hachu_shoubunrui": "",
            "hachu_saibunrui": "",
            "koji_name": search.effective_project_name,
            "place_search_type": search.place_search_type,
            "place_chihou": "",
            "place_todofuken": "",
            "place_shichouson": "",
            "place_text": "",
            "contract_types": ", ".join(search.contract_types),
            "koji_shubetsu": "",
            "koji_gyoushu": "",
            "gyomu_kubun": "",
        }

    def _refresh_target_presentation(self) -> None:
        target_var = getattr(self, "search_target_var", None)
        target = (
            self._target_from_display(target_var.get())
            if target_var is not None
            else self._config.search_conditions.target
        )
        profile = get_search_profile(target)
        self.names_place_frame.configure(
            text=f"{profile.project_label}・{profile.place_label}"
        )
        self.project_name_label.configure(text=f"{profile.project_label}:")
        self._refresh_all_dynamic_combos()

    def _on_search_target_changed(self, _event=None) -> None:
        old_target = self._config.search_conditions.target
        new_target = self._target_from_display(self.search_target_var.get())
        if new_target == old_target:
            return
        self._target_drafts[old_target.value] = self._target_draft_values()
        draft = self._target_drafts.get(new_target.value)
        if draft is None:
            draft = self._default_target_draft(new_target)
            self._target_drafts[new_target.value] = dict(draft)
        for field, value in draft.items():
            getattr(self, f"{field}_var").set(value)

        self._config.search_conditions.search_target = new_target.value
        self._config.target_urls = [get_search_profile(new_target).search_url]
        for field in tuple(self._dynamic_combos):
            self._option_generations[field] = (
                self._option_generations.get(field, 0) + 1
            )
            cancel_event = self._option_cancel_events.pop(field, None)
            if cancel_event is not None:
                cancel_event.set()
            self._option_loading.discard(field)
            self._option_errors.pop(field, None)
            self._search_option_model.update(field, ())
        self._refresh_target_presentation()
        self._load_runtime_fields(self._config)
        self._load_initial_dynamic_options()
        self._refresh_dynamic_option_status()

    def _parents_for_option(self, field: str) -> tuple[str, ...]:
        parent_fields = {
            "hachu_chubunrui": ("hachu_daibunrui",),
            "hachu_shoubunrui": (
                "hachu_daibunrui",
                "hachu_chubunrui",
            ),
            "hachu_saibunrui": (
                "hachu_daibunrui",
                "hachu_chubunrui",
                "hachu_shoubunrui",
            ),
            "place_todofuken": ("place_chihou",),
            "place_shichouson": ("place_chihou", "place_todofuken"),
        }.get(field, ())
        return tuple(
            self._dynamic_variable(parent).get().strip() for parent in parent_fields
        )

    def _invalidate_dynamic_fields(self, fields: tuple[str, ...]) -> None:
        cancel_events = getattr(self, "_option_cancel_events", {})
        user_revisions = getattr(self, "_option_user_revisions", None)
        if user_revisions is None:
            user_revisions = {}
            self._option_user_revisions = user_revisions
        for field in fields:
            self._option_generations[field] = self._option_generations.get(field, 0) + 1
            user_revisions[field] = user_revisions.get(field, 0) + 1
            self._option_loading.discard(field)
            cancel_event = cancel_events.pop(field, None)
            if cancel_event is not None:
                cancel_event.set()
            self._option_errors.pop(field, None)
            self._dynamic_variable(field).set("")
            self._search_option_model.update(field, ())
            self._refresh_dynamic_combo(field)

    def _on_dynamic_option_selected(self, field: str) -> None:
        user_revisions = getattr(self, "_option_user_revisions", None)
        if user_revisions is None:
            user_revisions = {}
            self._option_user_revisions = user_revisions
        user_revisions[field] = user_revisions.get(field, 0) + 1
        next_field = {
            "hachu_daibunrui": "hachu_chubunrui",
            "hachu_chubunrui": "hachu_shoubunrui",
            "hachu_shoubunrui": "hachu_saibunrui",
            "place_chihou": "place_todofuken",
            "place_todofuken": "place_shichouson",
        }.get(field)
        descendants = {
            "hachu_daibunrui": (
                "hachu_chubunrui",
                "hachu_shoubunrui",
                "hachu_saibunrui",
            ),
            "hachu_chubunrui": ("hachu_shoubunrui", "hachu_saibunrui"),
            "hachu_shoubunrui": ("hachu_saibunrui",),
            "place_chihou": ("place_todofuken", "place_shichouson"),
            "place_todofuken": ("place_shichouson",),
        }.get(field, ())
        if descendants:
            self._invalidate_dynamic_fields(descendants)
        if next_field is not None and self._dynamic_variable(field).get().strip():
            self._request_option_load(next_field)
        self._refresh_dynamic_option_status()

    def _load_initial_dynamic_options(self) -> None:
        for field in (
            "hachu_daibunrui",
            "place_chihou",
            "koji_shubetsu",
            "koji_gyoushu",
            "gyomu_kubun",
            "hachu_chubunrui",
            "hachu_shoubunrui",
            "hachu_saibunrui",
            "place_todofuken",
            "place_shichouson",
        ):
            parents = self._parents_for_option(field)
            if parents and any(not parent for parent in parents):
                continue
            self._request_option_load(
                field,
                priority=OptionLoadCoordinator.PREFETCH_PRIORITY,
            )

    def _reload_agency_options(self) -> None:
        """共有メモリ候補を破棄し、編集値を保持したまま再照合する。"""

        if (
            self._search_options_reloader is None
            or self._closed
            or self._option_reload_running
        ):
            return
        agency_fields = (
            "hachu_daibunrui",
            "hachu_chubunrui",
            "hachu_shoubunrui",
            "hachu_saibunrui",
        )
        cancel_events = getattr(self, "_option_cancel_events", {})
        for field in agency_fields:
            self._option_generations[field] = self._option_generations.get(field, 0) + 1
            cancel_event = cancel_events.pop(field, None)
            if cancel_event is not None:
                cancel_event.set()
            self._option_loading.discard(field)
            self._option_errors.pop(field, None)
            self._search_option_model.update(field, ())
            self._refresh_dynamic_combo(field)
        self._option_reload_running = True
        self._agency_reload_button.configure(state="disabled")
        self._refresh_dynamic_option_status()

        def worker() -> None:
            try:
                try:
                    parameters = inspect.signature(
                        self._search_options_reloader
                    ).parameters
                    accepts_target = "search_target" in parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters.values()
                    )
                except (TypeError, ValueError):
                    accepts_target = False
                if accepts_target:
                    self._search_options_reloader(
                        search_target=self._target_from_display(
                            self.search_target_var.get()
                        ).value
                    )
                else:
                    self._search_options_reloader()
                error = None
            except Exception as exc:
                error = str(exc)
            self._option_queue.put(("__agency_reload__", 0, (), error))

        if not self._submit_option_task("agency-reload", worker):
            self._option_queue.put_nowait(
                (
                    "__agency_reload__",
                    0,
                    (),
                    "候補取得ワーカーを利用できません",
                )
            )

    def _request_option_load(
        self,
        field: str,
        *,
        priority: int = OptionLoadCoordinator.USER_PRIORITY,
    ) -> None:
        if self._search_option_loader is None or self._closed:
            return
        parents = self._parents_for_option(field)
        generation = self._option_generations.get(field, 0) + 1
        self._option_generations[field] = generation
        token = DynamicOptionRequestToken(
            field=field,
            generation=generation,
            parent_values=parents,
            user_revision=getattr(self, "_option_user_revisions", {}).get(
                field, 0
            ),
        )
        cancel_events = getattr(self, "_option_cancel_events", None)
        if cancel_events is None:
            cancel_events = {}
            self._option_cancel_events = cancel_events
        previous_cancel = cancel_events.pop(field, None)
        if previous_cancel is not None:
            previous_cancel.set()
        request_cancel = Event()
        cancel_events[field] = request_cancel
        self._option_loading.add(field)
        self._option_errors.pop(field, None)
        self._refresh_dynamic_combo(field)
        self._refresh_dynamic_option_status()

        def worker() -> None:
            try:
                try:
                    parameters = inspect.signature(
                        self._search_option_loader
                    ).parameters
                    accepts_cancel = "cancel_check" in parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters.values()
                    )
                    accepts_target = "search_target" in parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters.values()
                    )
                except (TypeError, ValueError):
                    accepts_cancel = False
                    accepts_target = False
                kwargs = {}
                if accepts_cancel:
                    kwargs["cancel_check"] = request_cancel.is_set
                if accepts_target:
                    kwargs["search_target"] = self._target_from_display(
                        self.search_target_var.get()
                    ).value
                loaded = self._search_option_loader(field, parents, **kwargs)
                options = list(loaded or [])
                error = None
            except Exception as exc:  # 候補取得失敗はモーダル内で再選択を促す。
                options, error = [], str(exc)
            self._option_queue.put((field, token, options, error))

        if not self._submit_option_task(
            f"field:{field}", worker, priority=priority
        ):
            self._option_queue.put_nowait(
                (
                    field,
                    token,
                    (),
                    "候補取得ワーカーを利用できません",
                )
            )

    def _submit_option_task(
        self,
        key: str,
        callback: Callable[[], None],
        *,
        priority: int = OptionLoadCoordinator.USER_PRIORITY,
    ) -> bool:
        """設定モーダルの候補取得も共有単一ワーカーへ統合する。"""

        task_key = f"schedule-editor:{id(self)}:{key}"
        self._option_task_keys.add(task_key)
        return self._option_coordinator.submit(
            task_key,
            callback,
            priority=priority,
        )

    def _poll_option_queue(self) -> None:
        if self._closed:
            return
        try:
            while True:
                field, request_token, options, error = self._option_queue.get_nowait()
                if field == "__agency_reload__":
                    self._option_reload_running = False
                    self._agency_reload_button.configure(state="normal")
                    if error:
                        self._option_errors["hachu_daibunrui"] = error
                    else:
                        for agency_field in (
                            "hachu_daibunrui",
                            "hachu_chubunrui",
                            "hachu_shoubunrui",
                            "hachu_saibunrui",
                        ):
                            parents = self._parents_for_option(agency_field)
                            if parents and any(not parent for parent in parents):
                                continue
                            self._request_option_load(agency_field)
                    continue
                if isinstance(request_token, DynamicOptionRequestToken):
                    current_request = bool(
                        request_token.generation
                        == self._option_generations.get(field)
                        and request_token.parent_values
                        == self._parents_for_option(field)
                        and request_token.user_revision
                        == getattr(self, "_option_user_revisions", {}).get(
                            field, 0
                        )
                    )
                else:
                    # 1リリース分の内部キュー互換と、旧形式を使うテスト用。
                    current_request = request_token == self._option_generations.get(
                        field
                    )
                if not current_request:
                    if (
                        isinstance(request_token, DynamicOptionRequestToken)
                        and request_token.generation
                        == self._option_generations.get(field)
                    ):
                        # 新しい通信要求がなく、利用者編集だけで廃棄した
                        # 応答なら、読み込み中表示を残さない。
                        self._option_loading.discard(field)
                        getattr(self, "_option_cancel_events", {}).pop(
                            field, None
                        )
                        self._refresh_dynamic_combo(field)
                    continue
                self._option_loading.discard(field)
                getattr(self, "_option_cancel_events", {}).pop(field, None)
                if error:
                    self._option_errors[field] = error
                else:
                    self._option_errors.pop(field, None)
                    self._search_option_model.update(field, options)
                self._refresh_dynamic_combo(field)
        except Empty:
            pass
        self._refresh_dynamic_option_status()
        try:
            self._option_poll_after_id = self.dialog.after(100, self._poll_option_queue)
        except tk.TclError:
            self._closed = True

    def _refresh_dynamic_option_status(self) -> None:
        if not hasattr(self, "_dynamic_option_status"):
            return
        messages: list[str] = []
        if getattr(self, "_option_reload_running", False):
            messages.append("発注機関候補を再読み込み中です…")
        if self._option_loading:
            labels = "、".join(
                DYNAMIC_FIELD_LABELS.get(field, field)
                for field in sorted(self._option_loading)
            )
            messages.append(f"読み込み中: {labels}")
        if self._option_errors:
            labels = "、".join(
                DYNAMIC_FIELD_LABELS.get(field, field)
                for field in sorted(self._option_errors)
            )
            messages.append(f"候補を取得できませんでした: {labels}")
        messages.extend(
            self._search_option_model.warnings(self._current_dynamic_search())
        )
        self._dynamic_option_status.set("\n".join(messages))

    def _browse_save_path(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.dialog,
            initialdir=self.save_path_var.get() or ".",
        )
        if selected:
            self.save_path_var.set(selected)

    def _use_current_config(self) -> None:
        if self._current_config_provider is None:
            messagebox.showwarning(
                "実行条件",
                "メイン画面の条件を取得できません。",
                parent=self.dialog,
            )
            return
        try:
            current = self._current_config_provider()
            if not isinstance(current, AppConfig):
                raise ValueError("現在の検索条件を取得できませんでした")
            if self._validator is not None:
                valid, errors = self._validator(current)
                if not valid:
                    raise ValueError("\n".join(errors))
            # 実行予定は編集中の値を維持し、実行条件一式だけを置き換える。
            schedule = deepcopy(self._config.schedule)
            previous_save_paths = deepcopy(self._config.save_paths)
            self._config = deepcopy(current)
            self._config.schedule = schedule
            if previous_save_paths.layout_version < 3:
                # 旧snapshotはlocal直下という保存契約ごと維持する。
                self._config.save_paths = previous_save_paths
            elif previous_save_paths.schedule_storage_key:
                self._config.save_paths.layout_version = max(
                    previous_save_paths.layout_version,
                    self._config.save_paths.layout_version,
                )
                self._config.save_paths.scheduled_folder = (
                    previous_save_paths.scheduled_folder
                )
                self._config.save_paths.schedule_storage_key = (
                    previous_save_paths.schedule_storage_key
                )
                self._config.save_paths.schedule_storage_folder = (
                    previous_save_paths.schedule_storage_folder
                )
            self._search_option_model.set_initial(self._config.search_conditions)
            self._load_runtime_fields(self._config)
            self._load_search_fields(self._config.search_conditions)
            self._refresh_all_dynamic_combos()
            self._update_place_search_mode()
            self._refresh_dynamic_option_status()
            self._load_initial_dynamic_options()
            self._update_condition_summary()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("実行条件エラー", str(exc), parent=self.dialog)

    def _load_runtime_fields(self, config: AppConfig) -> None:
        self.target_urls_text.configure(state=tk.NORMAL)
        self.target_urls_text.delete("1.0", tk.END)
        self.target_urls_text.insert("1.0", "\n".join(config.target_urls))
        self.target_urls_text.configure(state=tk.DISABLED)
        self.file_types_var.set(", ".join(config.download_conditions.file_types))
        self.keywords_var.set(", ".join(config.download_conditions.keywords))
        date_range = config.download_conditions.date_range or {}
        self.download_date_start_var.set(date_range.get("start") or "")
        self.download_date_end_var.set(date_range.get("end") or "")
        self.save_path_var.set(config.save_paths.local)
        self._update_storage_preview()
        self.naming_rule_var.set(config.naming_rule)

    def _update_storage_preview(self, *_args) -> None:
        variable = getattr(self, "storage_preview_var", None)
        if variable is None:
            return
        preview_config = deepcopy(self._config)
        preview_config.save_paths.local = self.save_path_var.get().strip()
        save_paths = preview_config.save_paths
        if save_paths.layout_version < 3:
            key = "旧構成（固定キーなし）"
            folder = "旧構成（データルート直下）"
        else:
            key = save_paths.schedule_storage_key or "登録時に自動割当"
            folder = save_paths.schedule_storage_folder or "登録時に自動割当"
        try:
            path = format_storage_preview(preview_config, RunKind.SCHEDULED)
            variable.set(
                f"定期実行の保存予定: {path}\n"
                f"固定保存キー: {key} / フォルダー: {folder}"
            )
        except (TypeError, ValueError) as exc:
            variable.set(f"保存構成を確認してください: {exc}")

    def _load_search_fields(self, search: SearchConditions) -> None:
        """全SearchConditionsフィールドを編集UIへ復元する。"""

        profile = get_search_profile(search.target)
        self.search_target_var.set(profile.display_label)
        for variable, value in (
            (self.hachu_daibunrui_var, search.hachu_daibunrui),
            (self.hachu_chubunrui_var, search.hachu_chubunrui),
            (self.hachu_shoubunrui_var, search.hachu_shoubunrui),
            (self.hachu_saibunrui_var, search.hachu_saibunrui),
            (self.hachu_multi_var, ", ".join(search.hachu_multi or [])),
            (self.koji_name_var, search.effective_project_name),
            (self.place_search_type_var, search.place_search_type),
            (self.place_chihou_var, search.place_chihou),
            (self.place_todofuken_var, search.place_todofuken),
            (self.place_shichouson_var, search.place_shichouson),
            (self.place_text_var, search.place_text),
            (self.contract_types_var, ", ".join(search.contract_types or [])),
            (self.update_date_type_var, search.update_date_type),
            (self.update_date_days_var, search.update_date_days or ""),
            (self.koukoku_date_type_var, search.koukoku_date_type),
            (self.koukoku_date_start_var, search.koukoku_date_start or ""),
            (self.koukoku_date_end_var, search.koukoku_date_end or ""),
            (self.kaisatsu_date_type_var, search.kaisatsu_date_type),
            (self.kaisatsu_date_start_var, search.kaisatsu_date_start or ""),
            (self.kaisatsu_date_end_var, search.kaisatsu_date_end or ""),
            (self.keiyaku_date_type_var, search.keiyaku_date_type),
            (self.keiyaku_date_start_var, search.keiyaku_date_start or ""),
            (self.keiyaku_date_end_var, search.keiyaku_date_end or ""),
            (self.koji_shubetsu_var, search.koji_shubetsu),
            (self.koji_gyoushu_var, search.koji_gyoushu),
            (self.gyomu_kubun_var, search.gyomu_kubun),
            (self.yotei_price_min_var, search.yotei_price_min or ""),
            (self.yotei_price_max_var, search.yotei_price_max or ""),
            (self.rakusatsu_price_min_var, search.rakusatsu_price_min or ""),
            (self.rakusatsu_price_max_var, search.rakusatsu_price_max or ""),
            (self.rakusatsu_name_var, search.rakusatsu_name),
            (self.display_count_var, str(search.display_count)),
        ):
            variable.set(value)
        self.denshi_var.set(search.denshi)
        self.koukai_var.set(search.koukai)
        self._target_drafts[search.target.value] = self._target_draft_values()
        self._refresh_target_presentation()
        if self._dynamic_combos:
            self._refresh_all_dynamic_combos()
            self._update_place_search_mode()

    def _config_from_ui(self) -> AppConfig:
        name = self.name_var.get().strip()
        if not name:
            raise ValueError("条件名を入力してください")
        if len(name) > 80:
            raise ValueError("条件名は80文字以内で入力してください")
        try:
            day = int(self.day_var.get())
            retry_count = int(self.retry_count_var.get())
            retry_interval = int(self.retry_interval_var.get())
        except ValueError as exc:
            raise ValueError("実行日と再試行設定は整数で指定してください") from exc
        time_value = self.time_var.get().strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_value):
            raise ValueError("実行時刻はHH:MM形式で指定してください")
        if not 1 <= day <= 28:
            raise ValueError("毎月の実行日は1～28で指定してください")
        if not 0 <= retry_count <= 10:
            raise ValueError("再試行回数は0～10回で指定してください")
        if not 1 <= retry_interval <= 1440:
            raise ValueError("再試行間隔は1～1440分で指定してください")

        def optional_int(variable: tk.StringVar, label: str) -> Optional[int]:
            value = variable.get().strip()
            if not value:
                return None
            try:
                return int(value)
            except ValueError as exc:
                raise ValueError(f"{label}は整数で指定してください") from exc

        config = deepcopy(self._config)
        target_variable = getattr(self, "search_target_var", None)
        target = (
            self._target_from_display(target_variable.get())
            if target_variable is not None
            else self._config.search_conditions.target
        )
        profile = get_search_profile(target)
        config.target_urls = [profile.search_url]
        config.download_conditions.file_types = self._parse_list(
            self.file_types_var.get(), extensions=True
        )
        config.download_conditions.keywords = self._parse_list(self.keywords_var.get())
        download_date_start = self.download_date_start_var.get().strip()
        download_date_end = self.download_date_end_var.get().strip()
        config.download_conditions.date_range = (
            {
                "start": download_date_start or None,
                "end": download_date_end or None,
            }
            if download_date_start or download_date_end
            else None
        )
        config.save_paths.local = self.save_path_var.get().strip()
        config.naming_rule = self.naming_rule_var.get().strip()
        config.search_conditions = SearchConditions(
            hachu_daibunrui=self.hachu_daibunrui_var.get().strip(),
            hachu_chubunrui=self.hachu_chubunrui_var.get().strip(),
            hachu_shoubunrui=self.hachu_shoubunrui_var.get().strip(),
            hachu_saibunrui=self.hachu_saibunrui_var.get().strip(),
            hachu_multi=self._parse_list(self.hachu_multi_var.get()),
            koji_name=(
                self.koji_name_var.get().strip()
                if target == SearchTarget.KOJI_KEIKA
                else ""
            ),
            place_search_type=self.place_search_type_var.get(),
            place_chihou=self.place_chihou_var.get().strip(),
            place_todofuken=self.place_todofuken_var.get().strip(),
            place_shichouson=self.place_shichouson_var.get().strip(),
            place_text=self.place_text_var.get().strip(),
            contract_types=self._parse_list(self.contract_types_var.get()),
            update_date_type=self.update_date_type_var.get(),
            update_date_days=optional_int(
                self.update_date_days_var, "最終更新日の過去日数"
            ),
            koukoku_date_type=self.koukoku_date_type_var.get(),
            koukoku_date_start=(self.koukoku_date_start_var.get().strip() or None),
            koukoku_date_end=self.koukoku_date_end_var.get().strip() or None,
            kaisatsu_date_type=self.kaisatsu_date_type_var.get(),
            kaisatsu_date_start=(self.kaisatsu_date_start_var.get().strip() or None),
            kaisatsu_date_end=self.kaisatsu_date_end_var.get().strip() or None,
            keiyaku_date_type=self.keiyaku_date_type_var.get(),
            keiyaku_date_start=(self.keiyaku_date_start_var.get().strip() or None),
            keiyaku_date_end=self.keiyaku_date_end_var.get().strip() or None,
            koji_shubetsu=(
                self.koji_shubetsu_var.get().strip()
                if target == SearchTarget.KOJI_KEIKA
                else ""
            ),
            koji_gyoushu=(
                self.koji_gyoushu_var.get().strip()
                if target == SearchTarget.KOJI_KEIKA
                else ""
            ),
            yotei_price_min=optional_int(self.yotei_price_min_var, "予定価格の下限"),
            yotei_price_max=optional_int(self.yotei_price_max_var, "予定価格の上限"),
            rakusatsu_price_min=optional_int(
                self.rakusatsu_price_min_var, "落札価格の下限"
            ),
            rakusatsu_price_max=optional_int(
                self.rakusatsu_price_max_var, "落札価格の上限"
            ),
            rakusatsu_name=self.rakusatsu_name_var.get().strip(),
            denshi=self.denshi_var.get(),
            koukai=self.koukai_var.get(),
            display_count=optional_int(self.display_count_var, "表示件数") or 20,
            search_target=target.value,
            project_name=self.koji_name_var.get().strip(),
            gyomu_kubun=(
                self.gyomu_kubun_var.get().strip()
                if target == SearchTarget.GYOMU_KEIKA
                else ""
            ),
        )
        schedule_values = {
            "enabled": self.enabled_var.get(),
            "backend": "windows_task_scheduler",
            "timezone": "Asia/Tokyo",
            "interval": self._DISPLAY_TO_INTERVAL.get(
                self.interval_var.get(), "daily"
            ),
            "time": time_value,
            "weekday": self._DISPLAY_TO_WEEKDAY.get(
                self.weekday_var.get(), "monday"
            ),
            "day_of_month": day,
            "start_when_available": self.start_when_available_var.get(),
            "wake_to_run": self.wake_to_run_var.get(),
            "retry_count": retry_count,
            "retry_interval_minutes": retry_interval,
            "notification_policy": _DISPLAY_TO_NOTIFICATION_POLICY.get(
                self.notification_policy_var.get(), "off"
            ),
        }
        # モデル更新との前後関係にかかわらず旧ブランチを起動できるよう、
        # 利用可能なフィールドだけを渡す。
        parameters = inspect.signature(ScheduleConfig).parameters
        config.schedule = ScheduleConfig(
            **{
                name: value
                for name, value in schedule_values.items()
                if name in parameters
            }
        )
        return config

    @staticmethod
    def _dynamic_search_key(search: SearchConditions) -> tuple[object, ...]:
        """サイト候補から取得するため自由入力させないコード群。"""

        return (
            search.hachu_daibunrui,
            search.hachu_chubunrui,
            search.hachu_shoubunrui,
            search.hachu_saibunrui,
            tuple(search.hachu_multi or []),
            search.place_chihou,
            search.place_todofuken,
            search.place_shichouson,
            search.koji_shubetsu,
            search.koji_gyoushu,
            search.gyomu_kubun,
            search.search_target,
        )

    def _state_fingerprint(self) -> str:
        """入力途中の文字列も含め、未保存変更を安定して検出する。"""

        values: dict[str, object] = {}
        for name, value in vars(self).items():
            if not name.endswith("_var") or not callable(getattr(value, "get", None)):
                continue
            values[name] = value.get()
        target_text = getattr(self, "target_urls_text", None)
        if target_text is not None:
            values["target_urls_text"] = target_text.get("1.0", tk.END)
        encoded = json.dumps(
            values,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _on_cancel(self) -> None:
        initial = getattr(self, "_initial_ui_fingerprint", "")
        dirty = bool(initial) and self._state_fingerprint() != initial
        if dirty and not messagebox.askyesno(
            "未保存の変更",
            "未保存の変更を破棄して閉じますか？",
            parent=self.dialog,
        ):
            return
        self._close_dialog()

    def _close_dialog(self) -> None:
        self._closed = True
        cancel_events = getattr(self, "_option_cancel_events", {})
        for cancel_event in cancel_events.values():
            cancel_event.set()
        cancel_events.clear()
        coordinator = getattr(self, "_option_coordinator", None)
        if coordinator is not None:
            for task_key in getattr(self, "_option_task_keys", ()):
                coordinator.cancel(task_key)
            self._option_task_keys.clear()
            if getattr(self, "_owns_option_coordinator", False):
                coordinator.stop(cancel_pending=True)
        after_id = getattr(self, "_option_poll_after_id", None)
        if after_id is not None:
            try:
                self.dialog.after_cancel(after_id)
            except tk.TclError:
                pass
        self.dialog.destroy()

    def _agency_selection_errors(self, search: SearchConditions) -> list[str]:
        """保存済み値も含め、最新の発注機関候補との不一致を拒否する。"""

        errors: list[str] = []
        agency_fields = (
            "hachu_daibunrui",
            "hachu_chubunrui",
            "hachu_shoubunrui",
            "hachu_saibunrui",
        )
        if getattr(self, "_option_reload_running", False) and any(
            str(getattr(search, field, "") or "").strip()
            for field in agency_fields
        ):
            errors.append(
                "発注機関候補を再読み込み中です。完了してから保存してください"
            )
        for field in agency_fields:
            value = str(getattr(search, field, "") or "").strip()
            if not value:
                continue
            label = DYNAMIC_FIELD_LABELS.get(field, field)
            if field in self._option_loading:
                errors.append(
                    f"{label}の候補を読み込み中です。完了してから保存してください"
                )
                continue
            if field in self._option_errors:
                errors.append(f"{label}の候補を確認できません。再読み込みしてください")
                continue
            options = self._search_option_model.options(field)
            if options and not any(
                value in {option.code, option.label} for option in options
            ):
                errors.append(
                    f"{label}「{value}」は最新候補にありません。"
                    "候補から選択し直してください"
                )
        return errors

    def _on_save(self) -> None:
        try:
            config = self._config_from_ui()
            option_errors = self._search_option_model.validate(config.search_conditions)
            option_errors.extend(
                self._agency_selection_errors(config.search_conditions)
            )
            for field, error in self._option_errors.items():
                if field in {
                    "hachu_daibunrui",
                    "hachu_chubunrui",
                    "hachu_shoubunrui",
                    "hachu_saibunrui",
                }:
                    continue
                if (
                    field.startswith("place_")
                    and config.search_conditions.place_search_type != "list"
                ):
                    continue
                value = str(
                    getattr(config.search_conditions, field, "") or ""
                ).strip()
                if value:
                    label = DYNAMIC_FIELD_LABELS.get(field, field)
                    option_errors.append(
                        f"{label}「{value}」の候補を確認できません: {error}"
                    )
            dynamic_changed = self._dynamic_search_key(
                config.search_conditions
            ) != self._dynamic_search_key(self._config.search_conditions)
            if self._option_loading:
                option_errors.append(
                    "対象サイトの候補を読み込み中です。完了してから保存してください"
                )
            if option_errors:
                option_errors = list(dict.fromkeys(option_errors))
                raise ValueError(
                    "検索候補にエラーがあります:\n"
                    + "\n".join(f"・{error}" for error in option_errors)
                )
            if self._validator is not None:
                valid, errors = self._validator(config)
                if not valid:
                    raise ValueError(
                        "設定にエラーがあります:\n"
                        + "\n".join(f"・{error}" for error in errors)
                    )
            if self._dynamic_validator is not None and dynamic_changed:
                valid, errors = self._dynamic_validator(config)
                if not valid:
                    raise ValueError(
                        "動的検索条件にエラーがあります:\n"
                        + "\n".join(f"・{error}" for error in errors)
                    )
        except (TypeError, ValueError) as exc:
            messagebox.showerror("設定エラー", str(exc), parent=self.dialog)
            return
        self.result = ScheduleEditorResult(self.name_var.get().strip(), config)
        self._close_dialog()

    def show(self) -> Optional[ScheduleEditorResult]:
        self.dialog.wait_window()
        return self.result


__all__ = [
    "ScheduleEditorDialog",
    "ScheduleEditorResult",
    "format_schedule_notification_policy",
    "normalise_schedule_notification_policy",
]
