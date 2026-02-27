# -*- coding: utf-8 -*-

"""検索条件フレーム

setup_search_conditions と関連するドロップダウンハンドラを
MainWindow から分離した単一責務ウィジェット。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, TYPE_CHECKING
from threading import Thread

from ...core.ppi_dropdowns import get_labels, code_to_label, label_to_code

if TYPE_CHECKING:
    from ...models.config_model import SearchConditions
    from ...utils.logger import Logger
    from ...app.lookup_service import LookupService


class SearchConditionsFrame:
    """検索条件の UI 構築・操作・config 双方向変換を担うクラス"""

    def __init__(
        self,
        parent: ttk.Frame,
        search_conditions: "SearchConditions",
        get_lookup_service: Callable[[], "LookupService"],
        logger: "Logger",
    ):
        self._parent = parent
        self._get_lookup_service = get_lookup_service
        self.logger = logger

        self._build_widgets(parent, search_conditions)

    # ------------------------------------------------------------------
    # Widget 構築
    # ------------------------------------------------------------------

    def _build_widgets(self, parent: ttk.Frame, sc: "SearchConditions"):
        """全検索条件ウィジェットを構築する"""
        row = 0
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        # --- 発注機関（リスト検索） ---
        hachu_frame = ttk.LabelFrame(parent, text="発注機関（リスト検索）", padding="5")
        hachu_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        hachu_frame.columnconfigure(1, weight=1)
        row += 1

        self.hachu_daibunrui_var = tk.StringVar(value=sc.hachu_daibunrui)
        self.hachu_daibunrui_combo = self._combo(hachu_frame, 0, "大分類:", self.hachu_daibunrui_var)
        self.hachu_daibunrui_combo.bind("<<ComboboxSelected>>", self._on_hachu_daibunrui_changed)

        self.hachu_chubunrui_var = tk.StringVar(value=sc.hachu_chubunrui)
        self.hachu_chubunrui_combo = self._combo(hachu_frame, 1, "中分類:", self.hachu_chubunrui_var)
        self.hachu_chubunrui_combo.bind("<<ComboboxSelected>>", self._on_hachu_chubunrui_changed)
        self.hachu_chubunrui_combo.bind("<FocusIn>", self._on_hachu_chubunrui_focusin)

        self.hachu_shoubunrui_var = tk.StringVar(value=sc.hachu_shoubunrui)
        self.hachu_shoubunrui_combo = self._combo(hachu_frame, 2, "小分類:", self.hachu_shoubunrui_var)
        self.hachu_shoubunrui_combo.bind("<<ComboboxSelected>>", self._on_hachu_shoubunrui_changed)
        self.hachu_shoubunrui_combo.bind("<FocusIn>", self._on_hachu_shoubunrui_focusin)

        self.hachu_saibunrui_var = tk.StringVar(value=sc.hachu_saibunrui)
        self.hachu_saibunrui_combo = self._combo(hachu_frame, 3, "細分類:", self.hachu_saibunrui_var)
        self.hachu_saibunrui_combo.bind("<<ComboboxSelected>>", self._on_hachu_saibunrui_changed)
        self.hachu_saibunrui_combo.bind("<FocusIn>", self._on_hachu_saibunrui_focusin)

        # --- 発注機関（複数選択検索） ---
        hachu_multi_frame = ttk.LabelFrame(parent, text="発注機関（複数選択検索）", padding="5")
        hachu_multi_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        hachu_multi_frame.columnconfigure(0, weight=1)
        row += 1

        hachu_multi_input = ttk.Frame(hachu_multi_frame)
        hachu_multi_input.pack(fill=tk.X)
        self.hachu_multi_var = tk.StringVar()
        ttk.Entry(hachu_multi_input, textvariable=self.hachu_multi_var, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5
        )
        ttk.Label(hachu_multi_input, text="(カンマ区切りで複数指定)").pack(side=tk.LEFT, padx=5)
        ttk.Label(
            hachu_multi_frame,
            text="※リスト検索と複数選択検索は同時に使用できません。",
            font=("", 8), foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))

        # --- 工事名 ---
        koji_name_frame = ttk.LabelFrame(parent, text="工事名（文字列検索）", padding="5")
        koji_name_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.koji_name_var = tk.StringVar(value=sc.koji_name)
        ttk.Label(koji_name_frame, text="工事名:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(koji_name_frame, textvariable=self.koji_name_var, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5
        )
        ttk.Label(koji_name_frame, text="※条件の複数指定はできません。", font=("", 8), foreground="gray").pack(
            anchor=tk.W, padx=5, pady=(5, 0)
        )

        # --- 工事場所（リスト検索） ---
        place_frame = ttk.LabelFrame(parent, text="工事場所（リスト検索）", padding="5")
        place_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        place_frame.columnconfigure(1, weight=1)
        row += 1

        self._place_chihou_options = ["", "北海道", "東北", "関東", "北陸", "中部", "近畿", "中国", "四国", "九州・沖縄"]
        initial_chihou = sc.place_chihou if sc.place_chihou else ""
        self.place_chihou_var = tk.StringVar(value=initial_chihou)
        self.place_chihou_combobox = ttk.Combobox(
            place_frame, textvariable=self.place_chihou_var,
            values=self._place_chihou_options, state="readonly", width=30,
        )
        ttk.Label(place_frame, text="地方:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.place_chihou_combobox.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        self.place_chihou_combobox.bind("<<ComboboxSelected>>", self._on_place_chihou_changed)
        self._set_chihou_current(initial_chihou)

        self.place_todofuken_var = tk.StringVar(value=sc.place_todofuken)
        self.place_todofuken_combobox = ttk.Combobox(
            place_frame, textvariable=self.place_todofuken_var,
            values=[""], state="readonly", width=30,
        )
        ttk.Label(place_frame, text="都道府県:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.place_todofuken_combobox.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        self.place_todofuken_combobox.bind("<<ComboboxSelected>>", self._on_place_todofuken_changed)

        self.place_shichouson_var = tk.StringVar(value=sc.place_shichouson)
        self.place_shichouson_combobox = ttk.Combobox(
            place_frame, textvariable=self.place_shichouson_var,
            values=[""], state="readonly", width=30,
        )
        ttk.Label(place_frame, text="市町村:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.place_shichouson_combobox.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        # --- 工事場所（文字列検索） ---
        place_text_frame = ttk.LabelFrame(parent, text="工事場所（文字列検索）", padding="5")
        place_text_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.place_text_var = tk.StringVar(value=sc.place_text)
        ttk.Label(place_text_frame, text="工事場所:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(place_text_frame, textvariable=self.place_text_var, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5
        )
        ttk.Label(place_text_frame, text="※条件の複数指定はできません。", font=("", 8), foreground="gray").pack(
            anchor=tk.W, padx=5, pady=(5, 0)
        )

        # --- 入札契約方式 ---
        contract_frame = ttk.LabelFrame(parent, text="入札契約方式", padding="5")
        contract_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        contract_types = ["一般競争入札", "公募型指名競争入札", "指名競争入札", "随意契約", "その他方式"]
        self.contract_type_vars: dict[str, tk.BooleanVar] = {}
        for i, ct in enumerate(contract_types):
            var = tk.BooleanVar(value=ct in sc.contract_types)
            self.contract_type_vars[ct] = var
            ttk.Checkbutton(contract_frame, text=ct, variable=var).grid(
                row=i // 3, column=i % 3, sticky=tk.W, padx=5, pady=2
            )

        # --- 最終更新日 ---
        update_frame = ttk.LabelFrame(parent, text="最終更新日", padding="5")
        update_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.update_date_type_var = tk.StringVar(
            value="none" if sc.update_date_type == "none" else "past"
        )
        ttk.Radiobutton(update_frame, text="指定なし", variable=self.update_date_type_var, value="none").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(update_frame, text="過去", variable=self.update_date_type_var, value="past").pack(side=tk.LEFT, padx=5)
        self.update_date_days_var = tk.StringVar(
            value=str(sc.update_date_days) if sc.update_date_days else ""
        )
        ttk.Entry(update_frame, textvariable=self.update_date_days_var, width=5).pack(side=tk.LEFT, padx=5)
        ttk.Label(update_frame, text="日以内").pack(side=tk.LEFT)

        # --- 公告日 ---
        koukoku_frame = ttk.LabelFrame(parent, text="公告日", padding="5")
        koukoku_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.koukoku_date_type_var = tk.StringVar(value=sc.koukoku_date_type)
        ttk.Radiobutton(koukoku_frame, text="指定なし", variable=self.koukoku_date_type_var, value="none").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(koukoku_frame, text="期間指定", variable=self.koukoku_date_type_var, value="range").pack(side=tk.LEFT, padx=5)
        ttk.Label(koukoku_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.koukoku_date_start_var = tk.StringVar(value=sc.koukoku_date_start or "")
        ttk.Entry(koukoku_frame, textvariable=self.koukoku_date_start_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(koukoku_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)

        # --- 開札日 ---
        kaisatsu_frame = ttk.LabelFrame(parent, text="開札日", padding="5")
        kaisatsu_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.kaisatsu_date_type_var = tk.StringVar(value=sc.kaisatsu_date_type)
        ttk.Radiobutton(kaisatsu_frame, text="指定なし", variable=self.kaisatsu_date_type_var, value="none").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(kaisatsu_frame, text="期間指定", variable=self.kaisatsu_date_type_var, value="range").pack(side=tk.LEFT, padx=5)
        ttk.Label(kaisatsu_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.kaisatsu_date_start_var = tk.StringVar(value=sc.kaisatsu_date_start or "")
        ttk.Entry(kaisatsu_frame, textvariable=self.kaisatsu_date_start_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(kaisatsu_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)

        # --- 契約日 ---
        keiyaku_frame = ttk.LabelFrame(parent, text="契約日", padding="5")
        keiyaku_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.keiyaku_date_type_var = tk.StringVar(value=sc.keiyaku_date_type)
        ttk.Radiobutton(keiyaku_frame, text="指定なし", variable=self.keiyaku_date_type_var, value="none").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(keiyaku_frame, text="期間指定", variable=self.keiyaku_date_type_var, value="range").pack(side=tk.LEFT, padx=5)
        ttk.Label(keiyaku_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.keiyaku_date_start_var = tk.StringVar(value=sc.keiyaku_date_start or "")
        ttk.Entry(keiyaku_frame, textvariable=self.keiyaku_date_start_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(keiyaku_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)

        # --- 工事種別 ---
        koji_shubetsu_frame = ttk.LabelFrame(parent, text="工事種別", padding="5")
        koji_shubetsu_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        koji_shubetsu_opts = get_labels("koji_shubetsu")
        koji_shubetsu_input = ttk.Frame(koji_shubetsu_frame)
        koji_shubetsu_input.pack(fill=tk.X)
        display_val = code_to_label("koji_shubetsu", sc.koji_shubetsu, self.logger)
        self.koji_shubetsu_var = tk.StringVar(value=display_val)
        ttk.Label(koji_shubetsu_input, text="▽以下から選択").pack(side=tk.LEFT, padx=5)
        ttk.Combobox(
            koji_shubetsu_input, textvariable=self.koji_shubetsu_var,
            values=koji_shubetsu_opts, state="readonly", width=40,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Label(koji_shubetsu_frame, text="※国土交通省及び内閣府沖縄総合事務局の区分。", font=("", 8), foreground="gray").pack(
            anchor=tk.W, padx=5, pady=(5, 0)
        )

        # --- 工事の業種 ---
        koji_gyoushu_frame = ttk.LabelFrame(parent, text="工事の業種", padding="5")
        koji_gyoushu_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        koji_gyoushu_opts = get_labels("koji_gyoushu")
        koji_gyoushu_input = ttk.Frame(koji_gyoushu_frame)
        koji_gyoushu_input.pack(fill=tk.X)
        display_val = code_to_label("koji_gyoushu", sc.koji_gyoushu, self.logger)
        self.koji_gyoushu_var = tk.StringVar(value=display_val)
        ttk.Label(koji_gyoushu_input, text="▽以下から選択").pack(side=tk.LEFT, padx=5)
        ttk.Combobox(
            koji_gyoushu_input, textvariable=self.koji_gyoushu_var,
            values=koji_gyoushu_opts, state="readonly", width=40,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Label(koji_gyoushu_frame, text="※建設業法（別表第一）準拠。", font=("", 8), foreground="gray").pack(
            anchor=tk.W, padx=5, pady=(5, 0)
        )

        # --- 予定価格 ---
        yotei_frame = ttk.LabelFrame(parent, text="予定価格（範囲指定）", padding="5")
        yotei_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.yotei_price_min_var = tk.StringVar(value=str(sc.yotei_price_min) if sc.yotei_price_min else "")
        self.yotei_price_max_var = tk.StringVar(value=str(sc.yotei_price_max) if sc.yotei_price_max else "")
        ttk.Label(yotei_frame, text="（円）").pack(side=tk.LEFT, padx=5)
        ttk.Entry(yotei_frame, textvariable=self.yotei_price_min_var, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(yotei_frame, text="～").pack(side=tk.LEFT, padx=5)
        ttk.Entry(yotei_frame, textvariable=self.yotei_price_max_var, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(yotei_frame, text="（円）").pack(side=tk.LEFT, padx=5)

        # --- 落札価格／契約価格 ---
        rakusatsu_price_frame = ttk.LabelFrame(parent, text="落札価格／契約価格（範囲指定）", padding="5")
        rakusatsu_price_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.rakusatsu_price_min_var = tk.StringVar(value=str(sc.rakusatsu_price_min) if sc.rakusatsu_price_min else "")
        self.rakusatsu_price_max_var = tk.StringVar(value=str(sc.rakusatsu_price_max) if sc.rakusatsu_price_max else "")
        ttk.Label(rakusatsu_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)
        ttk.Entry(rakusatsu_price_frame, textvariable=self.rakusatsu_price_min_var, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(rakusatsu_price_frame, text="～").pack(side=tk.LEFT, padx=5)
        ttk.Entry(rakusatsu_price_frame, textvariable=self.rakusatsu_price_max_var, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(rakusatsu_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)

        # --- 落札者名／契約者名 ---
        rakusatsu_name_frame = ttk.LabelFrame(parent, text="落札者名／契約者名（文字列検索）", padding="5")
        rakusatsu_name_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.rakusatsu_name_var = tk.StringVar(value=sc.rakusatsu_name)
        ttk.Label(rakusatsu_name_frame, text="落札者名／契約者名:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(rakusatsu_name_frame, textvariable=self.rakusatsu_name_var, width=50).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5
        )
        ttk.Label(rakusatsu_name_frame, text="※条件の複数指定はできません。", font=("", 8), foreground="gray").pack(
            anchor=tk.W, padx=5, pady=(5, 0)
        )

        # --- オプション ---
        option_frame = ttk.LabelFrame(parent, text="オプション", padding="5")
        option_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.denshi_var = tk.BooleanVar(value=sc.denshi)
        ttk.Checkbutton(option_frame, text="電子入札：対象案件のみ", variable=self.denshi_var).pack(side=tk.LEFT, padx=5)
        self.koukai_var = tk.BooleanVar(value=sc.koukai)
        ttk.Checkbutton(option_frame, text="公開文書：公開中のみ", variable=self.koukai_var).pack(side=tk.LEFT, padx=5)

        # --- 表示件数 ---
        display_count_frame = ttk.LabelFrame(parent, text="一覧画面の表示件数", padding="5")
        display_count_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)

        self.display_count_var = tk.StringVar(value=str(sc.display_count))
        for count in ["20", "30", "50", "100"]:
            ttk.Radiobutton(
                display_count_frame, text=f"{count}件",
                variable=self.display_count_var, value=count,
            ).pack(side=tk.LEFT, padx=5)

    # ------------------------------------------------------------------
    # Helper: readonly combobox 生成
    # ------------------------------------------------------------------

    @staticmethod
    def _combo(parent_frame: ttk.Frame, grid_row: int, label: str, var: tk.StringVar) -> ttk.Combobox:
        ttk.Label(parent_frame, text=label).grid(row=grid_row, column=0, sticky=tk.W, padx=5, pady=2)
        cb = ttk.Combobox(parent_frame, textvariable=var, values=[], state="readonly", width=30)
        cb.grid(row=grid_row, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        return cb

    # ------------------------------------------------------------------
    # Config ↔ UI 変換
    # ------------------------------------------------------------------

    def load_from_config(self, sc: "SearchConditions"):
        """config → UI へ反映"""
        self.hachu_daibunrui_var.set(sc.hachu_daibunrui or "")
        self.hachu_chubunrui_var.set(sc.hachu_chubunrui or "")
        self.hachu_shoubunrui_var.set(sc.hachu_shoubunrui or "")
        self.hachu_saibunrui_var.set(sc.hachu_saibunrui or "")

        if sc.hachu_multi:
            self.hachu_multi_var.set(", ".join(sc.hachu_multi))
        else:
            self.hachu_multi_var.set("")

        self.koji_name_var.set(sc.koji_name or "")

        # 地方
        place_chihou = sc.place_chihou if sc.place_chihou else ""
        self._set_chihou_current(place_chihou)
        self.place_todofuken_var.set(sc.place_todofuken or "")
        self.place_shichouson_var.set(sc.place_shichouson or "")
        self.place_text_var.set(sc.place_text or "")

        for ct, var in self.contract_type_vars.items():
            var.set(ct in sc.contract_types)

        self.update_date_type_var.set(sc.update_date_type or "none")
        self.update_date_days_var.set(str(sc.update_date_days) if sc.update_date_days is not None else "")

        self.koukoku_date_type_var.set(sc.koukoku_date_type or "none")
        self.koukoku_date_start_var.set(sc.koukoku_date_start or "")
        self.kaisatsu_date_type_var.set(sc.kaisatsu_date_type or "none")
        self.kaisatsu_date_start_var.set(sc.kaisatsu_date_start or "")
        self.keiyaku_date_type_var.set(sc.keiyaku_date_type or "none")
        self.keiyaku_date_start_var.set(sc.keiyaku_date_start or "")

        self.koji_shubetsu_var.set(code_to_label("koji_shubetsu", sc.koji_shubetsu, self.logger))
        self.koji_gyoushu_var.set(code_to_label("koji_gyoushu", sc.koji_gyoushu, self.logger))

        self.yotei_price_min_var.set(str(sc.yotei_price_min) if sc.yotei_price_min is not None else "")
        self.yotei_price_max_var.set(str(sc.yotei_price_max) if sc.yotei_price_max is not None else "")
        self.rakusatsu_price_min_var.set(str(sc.rakusatsu_price_min) if sc.rakusatsu_price_min is not None else "")
        self.rakusatsu_price_max_var.set(str(sc.rakusatsu_price_max) if sc.rakusatsu_price_max is not None else "")

        self.rakusatsu_name_var.set(sc.rakusatsu_name or "")
        self.denshi_var.set(sc.denshi)
        self.koukai_var.set(sc.koukai)
        self.display_count_var.set(str(sc.display_count) if sc.display_count is not None else "20")

        self._parent.after(0, self.restore_hachu_hierarchy)
        self._parent.after(200, self.restore_place_hierarchy)

    def write_to_config(self, sc: "SearchConditions"):
        """UI → config へ書き戻す"""
        sc.hachu_daibunrui = self.hachu_daibunrui_var.get()
        sc.hachu_chubunrui = self.hachu_chubunrui_var.get()
        sc.hachu_shoubunrui = self.hachu_shoubunrui_var.get()
        sc.hachu_saibunrui = self.hachu_saibunrui_var.get()

        multi_text = self.hachu_multi_var.get().strip()
        sc.hachu_multi = [s.strip() for s in multi_text.split(",") if s.strip()] if multi_text else []

        sc.koji_name = self.koji_name_var.get()

        place_text_raw = (self.place_text_var.get() or "").strip()
        if place_text_raw:
            sc.place_search_type = "text"
            sc.place_text = place_text_raw
            sc.place_chihou = ""
            sc.place_todofuken = ""
            sc.place_shichouson = ""
        else:
            sc.place_search_type = "list"
            sc.place_text = ""
            sc.place_chihou = self.place_chihou_var.get()
            sc.place_todofuken = self.place_todofuken_var.get()
            sc.place_shichouson = self.place_shichouson_var.get()

        sc.contract_types = [ct for ct, var in self.contract_type_vars.items() if var.get()]

        sc.update_date_type = self.update_date_type_var.get()
        try:
            sc.update_date_days = int(self.update_date_days_var.get())
        except ValueError:
            sc.update_date_days = None

        sc.koukoku_date_type = self.koukoku_date_type_var.get()
        sc.koukoku_date_start = self.koukoku_date_start_var.get() or None
        sc.koukoku_date_end = None

        sc.kaisatsu_date_type = self.kaisatsu_date_type_var.get()
        sc.kaisatsu_date_start = self.kaisatsu_date_start_var.get() or None
        sc.kaisatsu_date_end = None

        sc.keiyaku_date_type = self.keiyaku_date_type_var.get()
        sc.keiyaku_date_start = self.keiyaku_date_start_var.get() or None
        sc.keiyaku_date_end = None

        sc.koji_shubetsu = label_to_code("koji_shubetsu", self.koji_shubetsu_var.get(), self.logger)
        sc.koji_gyoushu = label_to_code("koji_gyoushu", self.koji_gyoushu_var.get(), self.logger)

        for attr, var in [
            ("yotei_price_min", self.yotei_price_min_var),
            ("yotei_price_max", self.yotei_price_max_var),
            ("rakusatsu_price_min", self.rakusatsu_price_min_var),
            ("rakusatsu_price_max", self.rakusatsu_price_max_var),
        ]:
            try:
                setattr(sc, attr, int(var.get()) if var.get() else None)
            except ValueError:
                setattr(sc, attr, None)

        sc.rakusatsu_name = self.rakusatsu_name_var.get()
        sc.denshi = self.denshi_var.get()
        sc.koukai = self.koukai_var.get()
        try:
            sc.display_count = int(self.display_count_var.get())
        except ValueError:
            sc.display_count = 20

    # ------------------------------------------------------------------
    # 地方 Combobox 選択ヘルパー
    # ------------------------------------------------------------------

    def _set_chihou_current(self, value: str):
        if not value:
            self.place_chihou_var.set("")
            self.place_chihou_combobox.current(0)
        else:
            self.place_chihou_var.set(value)
            try:
                idx = self._place_chihou_options.index(value)
                self.place_chihou_combobox.current(idx)
            except ValueError:
                self.place_chihou_combobox.current(0)

    # ------------------------------------------------------------------
    # 発注機関ドロップダウンの動的取得
    # ------------------------------------------------------------------

    def load_daibunrui_options(self):
        """大分類オプションを非同期でロード"""
        def load_in_thread():
            try:
                svc = self._get_lookup_service()
                options = svc.get_hachu_daibunrui()
                self._parent.after(0, lambda: self._update_daibunrui_options(options))
            except Exception as e:
                self.logger.warning(f"大分類オプション読み込みエラー: {e}")
                self._parent.after(0, lambda: self._update_daibunrui_options([]))
        Thread(target=load_in_thread, daemon=True).start()

    def _update_daibunrui_options(self, options: list):
        if not options:
            self.logger.warning("大分類オプションが空です。")
            return
        self.hachu_daibunrui_combo["values"] = [""] + options
        current = self.hachu_daibunrui_var.get()
        if current and current in options:
            self.hachu_daibunrui_combo.current(options.index(current) + 1)

    def _on_hachu_daibunrui_changed(self, event=None):
        d = (self.hachu_daibunrui_var.get() or "").strip()
        self.hachu_chubunrui_var.set("")
        self.hachu_chubunrui_combo["values"] = [""]
        self.hachu_shoubunrui_var.set("")
        self.hachu_shoubunrui_combo["values"] = [""]
        self.hachu_saibunrui_var.set("")
        self.hachu_saibunrui_combo["values"] = [""]
        if not d:
            return

        def load_in_thread():
            try:
                svc = self._get_lookup_service()
                options = svc.get_hachu_chubunrui(d)
                self._parent.after(0, lambda: self._update_chubunrui_options(options))
            except Exception as e:
                self.logger.warning(f"中分類オプション読み込みエラー: {e}")
                self._parent.after(0, lambda: self._update_chubunrui_options([]))
        Thread(target=load_in_thread, daemon=True).start()

    def _update_chubunrui_options(self, options: list):
        if options is None:
            options = []
        self.hachu_chubunrui_combo["values"] = [""] + options if options else [""]

    def _on_hachu_chubunrui_changed(self, event=None):
        d = (self.hachu_daibunrui_var.get() or "").strip()
        c = (self.hachu_chubunrui_var.get() or "").strip()
        self.hachu_shoubunrui_var.set("")
        self.hachu_shoubunrui_combo["values"] = [""]
        self.hachu_saibunrui_var.set("")
        self.hachu_saibunrui_combo["values"] = [""]
        if not d or not c:
            return

        def load_in_thread():
            try:
                svc = self._get_lookup_service()
                options = svc.get_hachu_shoubunrui(d, c)
                self._parent.after(0, lambda: self._update_shoubunrui_options(options))
            except Exception as e:
                self.logger.warning(f"小分類オプション読み込みエラー: {e}")
                self._parent.after(0, lambda: self._update_shoubunrui_options([]))
        Thread(target=load_in_thread, daemon=True).start()

    def _update_shoubunrui_options(self, options: list):
        if options is None:
            options = []
        self.hachu_shoubunrui_combo["values"] = [""] + options if options else [""]

    def _on_hachu_shoubunrui_changed(self, event=None):
        d = (self.hachu_daibunrui_var.get() or "").strip()
        c = (self.hachu_chubunrui_var.get() or "").strip()
        s = (self.hachu_shoubunrui_var.get() or "").strip()
        self.hachu_saibunrui_var.set("")
        self.hachu_saibunrui_combo["values"] = [""]
        if not d or not c or not s:
            return

        def load_in_thread():
            try:
                svc = self._get_lookup_service()
                options = svc.get_hachu_saibunrui(d, c, s)
                self._parent.after(0, lambda: self._update_saibunrui_options(options))
            except Exception as e:
                self.logger.warning(f"細分類オプション読み込みエラー: {e}")
                self._parent.after(0, lambda: self._update_saibunrui_options([]))
        Thread(target=load_in_thread, daemon=True).start()

    def _update_saibunrui_options(self, options: list):
        if options is None:
            options = []
        self.hachu_saibunrui_combo["values"] = [""] + options if options else [""]

    def _on_hachu_saibunrui_changed(self, event=None):
        pass

    def _is_values_effectively_empty(self, combo: ttk.Combobox) -> bool:
        vals = list(combo["values"])
        return not vals or vals == [""]

    def _on_hachu_chubunrui_focusin(self, event=None):
        if self._is_values_effectively_empty(self.hachu_chubunrui_combo):
            d = (self.hachu_daibunrui_var.get() or "").strip()
            if d:
                def load():
                    try:
                        svc = self._get_lookup_service()
                        options = svc.get_hachu_chubunrui(d)
                        self._parent.after(0, lambda: self._update_chubunrui_options(options))
                    except Exception as e:
                        self.logger.warning(f"中分類オプション読み込みエラー(focusin): {e}")
                Thread(target=load, daemon=True).start()

    def _on_hachu_shoubunrui_focusin(self, event=None):
        if self._is_values_effectively_empty(self.hachu_shoubunrui_combo):
            d = (self.hachu_daibunrui_var.get() or "").strip()
            c = (self.hachu_chubunrui_var.get() or "").strip()
            if d and c:
                def load():
                    try:
                        svc = self._get_lookup_service()
                        options = svc.get_hachu_shoubunrui(d, c)
                        self._parent.after(0, lambda: self._update_shoubunrui_options(options))
                    except Exception as e:
                        self.logger.warning(f"小分類オプション読み込みエラー(focusin): {e}")
                Thread(target=load, daemon=True).start()

    def _on_hachu_saibunrui_focusin(self, event=None):
        if self._is_values_effectively_empty(self.hachu_saibunrui_combo):
            d = (self.hachu_daibunrui_var.get() or "").strip()
            c = (self.hachu_chubunrui_var.get() or "").strip()
            s = (self.hachu_shoubunrui_var.get() or "").strip()
            if d and c and s:
                def load():
                    try:
                        svc = self._get_lookup_service()
                        options = svc.get_hachu_saibunrui(d, c, s)
                        self._parent.after(0, lambda: self._update_saibunrui_options(options))
                    except Exception as e:
                        self.logger.warning(f"細分類オプション読み込みエラー(focusin): {e}")
                Thread(target=load, daemon=True).start()

    # ------------------------------------------------------------------
    # 発注機関 階層復元
    # ------------------------------------------------------------------

    def restore_hachu_hierarchy(self):
        """大分類→中分類→小分類→細分類 の階層オプションを現在値で復元"""
        d = (self.hachu_daibunrui_var.get() or "").strip()
        c = (self.hachu_chubunrui_var.get() or "").strip()
        s = (self.hachu_shoubunrui_var.get() or "").strip()
        a = (self.hachu_saibunrui_var.get() or "").strip()
        if not d:
            return

        def load_in_thread():
            results: dict = {}
            try:
                svc = self._get_lookup_service()
                results["chubunrui"] = svc.get_hachu_chubunrui(d)
                if c:
                    results["shoubunrui"] = svc.get_hachu_shoubunrui(d, c)
                if c and s:
                    results["saibunrui"] = svc.get_hachu_saibunrui(d, c, s)
            except Exception as e:
                self.logger.error(f"発注機関階層復元エラー: {e}")
            self._parent.after(0, lambda: self._apply_restored_hachu(results, d, c, s, a))
        Thread(target=load_in_thread, daemon=True).start()

    def _apply_restored_hachu(
        self, results: dict, d: str, c: str, s: str, a: str,
    ):
        try:
            if "chubunrui" in results:
                raw = results["chubunrui"] or []
                self.hachu_chubunrui_combo["values"] = [""] + raw
                if c and raw and c in raw:
                    self.hachu_chubunrui_combo.current(raw.index(c) + 1)
            if "shoubunrui" in results:
                raw = results["shoubunrui"] or []
                self.hachu_shoubunrui_combo["values"] = [""] + raw
                if s and raw and s in raw:
                    self.hachu_shoubunrui_combo.current(raw.index(s) + 1)
            if "saibunrui" in results:
                raw = results["saibunrui"] or []
                self.hachu_saibunrui_combo["values"] = [""] + raw
                if a and raw and a in raw:
                    self.hachu_saibunrui_combo.current(raw.index(a) + 1)
        except Exception as e:
            self.logger.warning(f"発注機関階層反映エラー: {e}")

    # ------------------------------------------------------------------
    # 工事場所ドロップダウンの動的取得
    # ------------------------------------------------------------------

    def _on_place_chihou_changed(self, event=None):
        chihou = (self.place_chihou_var.get() or "").strip()
        self.place_todofuken_var.set("")
        self.place_shichouson_var.set("")
        self.place_todofuken_combobox["values"] = [""]
        self.place_shichouson_combobox["values"] = [""]
        if not chihou:
            return

        def load():
            try:
                svc = self._get_lookup_service()
                options = svc.get_koji_prefecture(chihou)
                self._parent.after(0, lambda: self._update_todofuken_options(options))
            except Exception as e:
                self.logger.warning(f"都道府県オプション読み込みエラー: {e}")
                self._parent.after(0, lambda: self._update_todofuken_options([]))
        Thread(target=load, daemon=True).start()

    def _update_todofuken_options(self, options: list):
        if options is None:
            options = []
        self.place_todofuken_combobox["values"] = [""] + options if options else [""]
        if not options:
            self.logger.warning("都道府県オプションが空です。")

    def _on_place_todofuken_changed(self, event=None):
        chihou = (self.place_chihou_var.get() or "").strip()
        todofuken = (self.place_todofuken_var.get() or "").strip()
        self.place_shichouson_var.set("")
        self.place_shichouson_combobox["values"] = [""]
        if not chihou or not todofuken:
            return

        def load():
            try:
                svc = self._get_lookup_service()
                options = svc.get_koji_city(chihou, todofuken)
                self._parent.after(0, lambda: self._update_shichouson_options(options))
            except Exception as e:
                self.logger.warning(f"市町村オプション読み込みエラー: {e}")
                self._parent.after(0, lambda: self._update_shichouson_options([]))
        Thread(target=load, daemon=True).start()

    def _update_shichouson_options(self, options: list):
        if options is None:
            options = []
        self.place_shichouson_combobox["values"] = [""] + options if options else [""]
        if not options:
            self.logger.warning("市町村オプションが空です。")

    # ------------------------------------------------------------------
    # 工事場所 階層復元
    # ------------------------------------------------------------------

    def restore_place_hierarchy(self):
        """地方→都道府県→市町村 の階層オプションを現在値で復元"""
        chihou = (self.place_chihou_var.get() or "").strip()
        todofuken = (self.place_todofuken_var.get() or "").strip()
        shichouson = (self.place_shichouson_var.get() or "").strip()
        if not chihou:
            return

        def load():
            results: dict = {}
            try:
                svc = self._get_lookup_service()
                results["todofuken"] = svc.get_koji_prefecture(chihou)
                if todofuken:
                    results["shichouson"] = svc.get_koji_city(chihou, todofuken)
            except Exception as e:
                self.logger.warning(f"工事場所階層復元エラー: {e}")
            self._parent.after(0, lambda: self._apply_restored_place(results, chihou, todofuken, shichouson))
        Thread(target=load, daemon=True).start()

    def _apply_restored_place(
        self, results: dict, chihou: str, todofuken: str, shichouson: str,
    ):
        try:
            if "todofuken" in results:
                raw = results["todofuken"] or []
                self.place_todofuken_combobox["values"] = [""] + raw
                if todofuken and todofuken in raw:
                    self.place_todofuken_combobox.current(raw.index(todofuken) + 1)
            if "shichouson" in results:
                raw = results["shichouson"] or []
                self.place_shichouson_combobox["values"] = [""] + raw
                if shichouson and raw and shichouson in raw:
                    self.place_shichouson_combobox.current(raw.index(shichouson) + 1)
        except Exception as e:
            self.logger.warning(f"工事場所階層反映エラー: {e}")
