# -*- coding: utf-8 -*-

"""設定ダイアログ - 検索条件タブ

setup_search_tab とドロップダウンハンドラ、config ↔ UI 変換を
SettingsDialog から分離した単一責務クラス。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, TYPE_CHECKING
from threading import Thread

from ...core.ppi_dropdowns import get_labels, code_to_label, label_to_code

if TYPE_CHECKING:
    from ...models.config_model import SearchConditions, AppConfig
    from ...utils.logger import Logger
    from ...app.lookup_service import LookupService


class SettingsSearchTab:
    """設定ダイアログの検索条件タブ"""

    def __init__(
        self,
        parent: ttk.Frame,
        dialog: tk.Toplevel,
        get_lookup_service: Callable[[], "LookupService"],
        logger: "Logger",
        on_hachu_multi_select: Callable,
    ):
        self._dialog = dialog
        self._get_lookup_service = get_lookup_service
        self.logger = logger
        self._on_hachu_multi_select = on_hachu_multi_select

        self._build_widgets(parent)

    # ------------------------------------------------------------------
    # Widget 構築
    # ------------------------------------------------------------------

    def _build_widgets(self, parent: ttk.Frame):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # --- 発注機関（リスト検索） ---
        hachu_frame = ttk.LabelFrame(scrollable, text="発注機関（リスト検索）", padding="5")
        hachu_frame.pack(fill=tk.X, pady=(0, 10))

        hachu_input = ttk.Frame(hachu_frame)
        hachu_input.pack(fill=tk.X)

        ttk.Label(hachu_input, text="大分類:").pack(side=tk.LEFT, padx=(0, 5))
        self.hachu_daibunrui_var = tk.StringVar()
        self.hachu_daibunrui_combo = ttk.Combobox(
            hachu_input, textvariable=self.hachu_daibunrui_var,
            values=["", "国の機関", "地方公共団体（都道府県）", "地方公共団体（市区町村）", "テスト機関"],
            state="readonly", width=25,
        )
        self.hachu_daibunrui_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.hachu_daibunrui_combo.bind("<<ComboboxSelected>>", self._on_hachu_daibunrui_changed)

        ttk.Label(hachu_input, text="中分類:").pack(side=tk.LEFT, padx=(0, 5))
        self.hachu_chubunrui_var = tk.StringVar()
        self.hachu_chubunrui_combo = ttk.Combobox(
            hachu_input, textvariable=self.hachu_chubunrui_var,
            values=[""], state="readonly", width=25,
        )
        self.hachu_chubunrui_combo.pack(side=tk.LEFT)

        # --- 発注機関（複数選択検索） ---
        hachu_multi_frame = ttk.LabelFrame(scrollable, text="発注機関（複数選択検索）", padding="5")
        hachu_multi_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(hachu_multi_frame, text="複数選択", command=self._on_hachu_multi_select).pack(anchor=tk.W)
        ttk.Label(
            hachu_multi_frame, text="※リスト検索と複数選択検索は同時に使用できません。",
            font=("", 8), foreground="gray",
        ).pack(anchor=tk.W, pady=(5, 0))

        # --- 工事名 ---
        koji_name_frame = ttk.LabelFrame(scrollable, text="工事名（文字列検索）", padding="5")
        koji_name_frame.pack(fill=tk.X, pady=(0, 10))

        self.koji_name_var = tk.StringVar()
        ttk.Entry(koji_name_frame, textvariable=self.koji_name_var, width=60).pack(fill=tk.X)
        ttk.Label(koji_name_frame, text="※条件の複数指定はできません。", font=("", 8), foreground="gray").pack(
            anchor=tk.W, pady=(5, 0)
        )

        # --- 工事場所（リスト検索） ---
        place_list_frame = ttk.LabelFrame(scrollable, text="工事場所（リスト検索）", padding="5")
        place_list_frame.pack(fill=tk.X, pady=(0, 10))

        place_list_input = ttk.Frame(place_list_frame)
        place_list_input.pack(fill=tk.X)

        self.place_list_radio_var = tk.StringVar(value="list")
        ttk.Radiobutton(place_list_input, text="リスト検索", variable=self.place_list_radio_var, value="list").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        ttk.Label(place_list_input, text="地方:").pack(side=tk.LEFT, padx=(0, 5))
        self.place_chihou_var = tk.StringVar()
        self._place_chihou_options = ["", "北海道", "東北", "関東", "北陸", "中部", "近畿", "中国", "四国", "九州・沖縄"]
        self.place_chihou_combobox = ttk.Combobox(
            place_list_input, textvariable=self.place_chihou_var,
            values=self._place_chihou_options, state="readonly", width=12,
        )
        self.place_chihou_combobox.pack(side=tk.LEFT, padx=(0, 10))
        self.place_chihou_combobox.bind("<<ComboboxSelected>>", self._on_place_chihou_changed)

        ttk.Label(place_list_input, text="都道府県:").pack(side=tk.LEFT, padx=(0, 5))
        self.place_todofuken_var = tk.StringVar()
        self.place_todofuken_combobox = ttk.Combobox(
            place_list_input, textvariable=self.place_todofuken_var,
            values=[""], state="readonly", width=15,
        )
        self.place_todofuken_combobox.pack(side=tk.LEFT, padx=(0, 10))
        self.place_todofuken_combobox.bind("<<ComboboxSelected>>", self._on_place_todofuken_changed)

        ttk.Label(place_list_input, text="市町村:").pack(side=tk.LEFT, padx=(0, 5))
        self.place_shichouson_var = tk.StringVar()
        self.place_shichouson_combobox = ttk.Combobox(
            place_list_input, textvariable=self.place_shichouson_var,
            values=[""], state="readonly", width=15,
        )
        self.place_shichouson_combobox.pack(side=tk.LEFT)

        # --- 工事場所（文字列検索） ---
        place_text_frame = ttk.LabelFrame(scrollable, text="工事場所（文字列検索）", padding="5")
        place_text_frame.pack(fill=tk.X, pady=(0, 10))

        place_text_input = ttk.Frame(place_text_frame)
        place_text_input.pack(fill=tk.X)

        ttk.Radiobutton(place_text_input, text="文字列検索", variable=self.place_list_radio_var, value="text").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        self.place_text_var = tk.StringVar()
        self._place_text_entry = ttk.Entry(place_text_input, textvariable=self.place_text_var, width=40)
        self._place_text_entry.pack(side=tk.LEFT)
        self._place_text_entry.config(state="disabled")

        self.place_list_radio_var.trace("w", lambda *args: self._on_place_radio_change())

        # --- 入札契約方式 ---
        contract_frame = ttk.LabelFrame(scrollable, text="入札契約方式", padding="5")
        contract_frame.pack(fill=tk.X, pady=(0, 10))

        contract_types = ["一般競争入札", "公募型指名競争入札", "指名競争入札", "随意契約", "その他方式"]
        self.contract_vars: dict[str, tk.BooleanVar] = {}
        for ct in contract_types:
            var = tk.BooleanVar(value=True)
            self.contract_vars[ct] = var
            ttk.Checkbutton(contract_frame, text=ct, variable=var).pack(anchor=tk.W)

        # --- 最終更新日 ---
        update_frame = ttk.LabelFrame(scrollable, text="最終更新日", padding="5")
        update_frame.pack(fill=tk.X, pady=(0, 10))

        self.update_date_radio_var = tk.StringVar(value="none")
        ttk.Radiobutton(update_frame, text="指定なし", variable=self.update_date_radio_var, value="none").pack(anchor=tk.W)

        update_input = ttk.Frame(update_frame)
        update_input.pack(fill=tk.X, pady=(5, 0))

        ttk.Radiobutton(update_input, text="過去", variable=self.update_date_radio_var, value="past").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.update_date_days_var = tk.StringVar()
        self._update_date_entry = ttk.Entry(update_input, textvariable=self.update_date_days_var, width=5)
        self._update_date_entry.pack(side=tk.LEFT, padx=(0, 5))
        self._update_date_entry.config(state="disabled")
        ttk.Label(update_input, text="日以内").pack(side=tk.LEFT)

        self.update_date_radio_var.trace("w", lambda *args: self._on_update_date_radio_change())

        # --- 公告日 ---
        koukoku_frame = ttk.LabelFrame(scrollable, text="公告日", padding="5")
        koukoku_frame.pack(fill=tk.X, pady=(0, 10))

        self.koukoku_date_radio_var = tk.StringVar(value="none")
        ttk.Radiobutton(koukoku_frame, text="指定なし", variable=self.koukoku_date_radio_var, value="none").pack(anchor=tk.W)

        koukoku_input = ttk.Frame(koukoku_frame)
        koukoku_input.pack(fill=tk.X, pady=(5, 0))
        ttk.Radiobutton(koukoku_input, text="期間指定", variable=self.koukoku_date_radio_var, value="range").pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(koukoku_input, text="から").pack(side=tk.LEFT, padx=(0, 5))
        self.koukoku_date_start_var = tk.StringVar()
        ttk.Entry(koukoku_input, textvariable=self.koukoku_date_start_var, width=12).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(koukoku_input, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(koukoku_input, text="まで").pack(side=tk.LEFT, padx=(0, 5))
        self.koukoku_date_end_var = tk.StringVar()
        ttk.Entry(koukoku_input, textvariable=self.koukoku_date_end_var, width=12).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(koukoku_input, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # --- 開札日 ---
        kaisatsu_frame = ttk.LabelFrame(scrollable, text="開札日", padding="5")
        kaisatsu_frame.pack(fill=tk.X, pady=(0, 10))

        self.kaisatsu_date_radio_var = tk.StringVar(value="none")
        ttk.Radiobutton(kaisatsu_frame, text="指定なし", variable=self.kaisatsu_date_radio_var, value="none").pack(anchor=tk.W)

        kaisatsu_input = ttk.Frame(kaisatsu_frame)
        kaisatsu_input.pack(fill=tk.X, pady=(5, 0))
        ttk.Radiobutton(kaisatsu_input, text="期間指定", variable=self.kaisatsu_date_radio_var, value="range").pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(kaisatsu_input, text="から").pack(side=tk.LEFT, padx=(0, 5))
        self.kaisatsu_date_start_var = tk.StringVar()
        ttk.Entry(kaisatsu_input, textvariable=self.kaisatsu_date_start_var, width=12).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(kaisatsu_input, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(kaisatsu_input, text="まで").pack(side=tk.LEFT, padx=(0, 5))
        self.kaisatsu_date_end_var = tk.StringVar()
        ttk.Entry(kaisatsu_input, textvariable=self.kaisatsu_date_end_var, width=12).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(kaisatsu_input, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # --- 契約日 ---
        keiyaku_frame = ttk.LabelFrame(scrollable, text="契約日", padding="5")
        keiyaku_frame.pack(fill=tk.X, pady=(0, 10))

        self.keiyaku_date_radio_var = tk.StringVar(value="none")
        ttk.Radiobutton(keiyaku_frame, text="指定なし", variable=self.keiyaku_date_radio_var, value="none").pack(anchor=tk.W)

        keiyaku_input = ttk.Frame(keiyaku_frame)
        keiyaku_input.pack(fill=tk.X, pady=(5, 0))
        ttk.Radiobutton(keiyaku_input, text="期間指定", variable=self.keiyaku_date_radio_var, value="range").pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(keiyaku_input, text="から").pack(side=tk.LEFT, padx=(0, 5))
        self.keiyaku_date_start_var = tk.StringVar()
        ttk.Entry(keiyaku_input, textvariable=self.keiyaku_date_start_var, width=12).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(keiyaku_input, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(keiyaku_input, text="まで").pack(side=tk.LEFT, padx=(0, 5))
        self.keiyaku_date_end_var = tk.StringVar()
        ttk.Entry(keiyaku_input, textvariable=self.keiyaku_date_end_var, width=12).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(keiyaku_input, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # --- 工事種別 ---
        koji_shubetsu_frame = ttk.LabelFrame(scrollable, text="工事種別", padding="5")
        koji_shubetsu_frame.pack(fill=tk.X, pady=(0, 10))

        self.koji_shubetsu_var = tk.StringVar()
        ttk.Combobox(
            koji_shubetsu_frame, textvariable=self.koji_shubetsu_var,
            values=get_labels("koji_shubetsu"), state="readonly", width=40,
        ).pack(fill=tk.X)

        # --- 工事の業種 ---
        koji_gyoushu_frame = ttk.LabelFrame(scrollable, text="工事の業種", padding="5")
        koji_gyoushu_frame.pack(fill=tk.X, pady=(0, 10))

        self.koji_gyoushu_var = tk.StringVar()
        ttk.Combobox(
            koji_gyoushu_frame, textvariable=self.koji_gyoushu_var,
            values=get_labels("koji_gyoushu"), state="readonly", width=40,
        ).pack(fill=tk.X)

        # --- 予定価格 ---
        yotei_frame = ttk.LabelFrame(scrollable, text="予定価格（範囲指定）", padding="5")
        yotei_frame.pack(fill=tk.X, pady=(0, 10))

        yotei_input = ttk.Frame(yotei_frame)
        yotei_input.pack(fill=tk.X)
        self.yotei_price_min_var = tk.StringVar()
        ttk.Entry(yotei_input, textvariable=self.yotei_price_min_var, width=15).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(yotei_input, text="（円）～").pack(side=tk.LEFT, padx=(0, 5))
        self.yotei_price_max_var = tk.StringVar()
        ttk.Entry(yotei_input, textvariable=self.yotei_price_max_var, width=15).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(yotei_input, text="（円）").pack(side=tk.LEFT)

        # --- 落札価格／契約価格 ---
        rakusatsu_price_frame = ttk.LabelFrame(scrollable, text="落札価格／契約価格（範囲指定）", padding="5")
        rakusatsu_price_frame.pack(fill=tk.X, pady=(0, 10))

        rakusatsu_price_input = ttk.Frame(rakusatsu_price_frame)
        rakusatsu_price_input.pack(fill=tk.X)
        self.rakusatsu_price_min_var = tk.StringVar()
        ttk.Entry(rakusatsu_price_input, textvariable=self.rakusatsu_price_min_var, width=15).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(rakusatsu_price_input, text="（円）～").pack(side=tk.LEFT, padx=(0, 5))
        self.rakusatsu_price_max_var = tk.StringVar()
        ttk.Entry(rakusatsu_price_input, textvariable=self.rakusatsu_price_max_var, width=15).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(rakusatsu_price_input, text="（円）").pack(side=tk.LEFT)

        # --- 落札者名 ---
        rakusatsu_name_frame = ttk.LabelFrame(scrollable, text="落札者名／契約者名（文字列検索）", padding="5")
        rakusatsu_name_frame.pack(fill=tk.X, pady=(0, 10))

        self.rakusatsu_name_var = tk.StringVar()
        ttk.Entry(rakusatsu_name_frame, textvariable=self.rakusatsu_name_var, width=60).pack(fill=tk.X)
        ttk.Label(rakusatsu_name_frame, text="※条件の複数指定はできません。", font=("", 8), foreground="gray").pack(
            anchor=tk.W, pady=(5, 0)
        )

        # --- 電子入札 ---
        denshi_frame = ttk.LabelFrame(scrollable, text="電子入札", padding="5")
        denshi_frame.pack(fill=tk.X, pady=(0, 10))

        self.denshi_var = tk.BooleanVar()
        ttk.Checkbutton(denshi_frame, text="対象案件のみ", variable=self.denshi_var).pack(anchor=tk.W)

        # --- 公開文書 ---
        koukai_frame = ttk.LabelFrame(scrollable, text="公開文書", padding="5")
        koukai_frame.pack(fill=tk.X, pady=(0, 10))

        self.koukai_var = tk.BooleanVar()
        ttk.Checkbutton(koukai_frame, text="公開中のみ", variable=self.koukai_var).pack(anchor=tk.W)

        # --- 表示件数 ---
        display_frame = ttk.LabelFrame(scrollable, text="一覧画面の表示件数", padding="5")
        display_frame.pack(fill=tk.X, pady=(0, 10))

        self.display_count_var = tk.StringVar(value="20")
        ttk.Combobox(
            display_frame, textvariable=self.display_count_var,
            values=["20", "30", "50", "100"], state="readonly", width=10,
        ).pack(anchor=tk.W)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # ------------------------------------------------------------------
    # Radio 変更ハンドラ
    # ------------------------------------------------------------------

    def _on_place_radio_change(self):
        if self.place_list_radio_var.get() == "text":
            self._place_text_entry.config(state="normal")
        else:
            self._place_text_entry.config(state="disabled")

    def _on_update_date_radio_change(self):
        if self.update_date_radio_var.get() == "past":
            self._update_date_entry.config(state="normal")
        else:
            self._update_date_entry.config(state="disabled")

    # ------------------------------------------------------------------
    # Config ↔ UI
    # ------------------------------------------------------------------

    def load_from_config(self, sc: "SearchConditions"):
        """検索条件を UI に反映"""
        self.hachu_daibunrui_var.set(sc.hachu_daibunrui or "")
        self.hachu_chubunrui_var.set(sc.hachu_chubunrui or "")
        self.koji_name_var.set(sc.koji_name or "")
        self.place_list_radio_var.set(sc.place_search_type or "list")
        self.place_chihou_var.set(sc.place_chihou or "")
        self.place_todofuken_var.set(sc.place_todofuken or "")
        self.place_shichouson_var.set(sc.place_shichouson or "")
        self.place_text_var.set(sc.place_text or "")

        for ct, var in self.contract_vars.items():
            var.set(ct in (sc.contract_types or []))

        self.update_date_radio_var.set(sc.update_date_type or "none")
        if sc.update_date_days:
            self.update_date_days_var.set(str(sc.update_date_days))

        self.koukoku_date_radio_var.set(sc.koukoku_date_type or "none")
        if sc.koukoku_date_start:
            self.koukoku_date_start_var.set(sc.koukoku_date_start)
        if sc.koukoku_date_end:
            self.koukoku_date_end_var.set(sc.koukoku_date_end)

        self.kaisatsu_date_radio_var.set(sc.kaisatsu_date_type or "none")
        if sc.kaisatsu_date_start:
            self.kaisatsu_date_start_var.set(sc.kaisatsu_date_start)
        if sc.kaisatsu_date_end:
            self.kaisatsu_date_end_var.set(sc.kaisatsu_date_end)

        self.keiyaku_date_radio_var.set(sc.keiyaku_date_type or "none")
        if sc.keiyaku_date_start:
            self.keiyaku_date_start_var.set(sc.keiyaku_date_start)
        if sc.keiyaku_date_end:
            self.keiyaku_date_end_var.set(sc.keiyaku_date_end)

        self.koji_shubetsu_var.set(code_to_label("koji_shubetsu", sc.koji_shubetsu or "", self.logger))
        self.koji_gyoushu_var.set(code_to_label("koji_gyoushu", sc.koji_gyoushu or "", self.logger))

        if sc.yotei_price_min:
            self.yotei_price_min_var.set(str(sc.yotei_price_min))
        if sc.yotei_price_max:
            self.yotei_price_max_var.set(str(sc.yotei_price_max))
        if sc.rakusatsu_price_min:
            self.rakusatsu_price_min_var.set(str(sc.rakusatsu_price_min))
        if sc.rakusatsu_price_max:
            self.rakusatsu_price_max_var.set(str(sc.rakusatsu_price_max))

        self.rakusatsu_name_var.set(sc.rakusatsu_name or "")
        self.denshi_var.set(sc.denshi or False)
        self.koukai_var.set(sc.koukai or False)
        self.display_count_var.set(str(sc.display_count or 20))

    def write_to_search_conditions(self, existing_sc: Optional["SearchConditions"] = None) -> "SearchConditions":
        """UI の値を SearchConditions に変換して返す

        UI に無い項目（hachu_shoubunrui / saibunrui / multi）は
        existing_sc から引き継ぐ。
        """
        from ...models.config_model import SearchConditions

        contract_types = [ct for ct, var in self.contract_vars.items() if var.get()]

        update_date_days = None
        if self.update_date_radio_var.get() == "past":
            try:
                update_date_days = int(self.update_date_days_var.get())
            except ValueError:
                pass

        def safe_int(value: str) -> Optional[int]:
            try:
                return int(value) if value.strip() else None
            except ValueError:
                return None

        hachu_shoubunrui = (existing_sc.hachu_shoubunrui or "") if existing_sc else ""
        hachu_saibunrui = (existing_sc.hachu_saibunrui or "") if existing_sc else ""
        hachu_multi = (existing_sc.hachu_multi or []) if existing_sc else []

        return SearchConditions(
            hachu_daibunrui=self.hachu_daibunrui_var.get(),
            hachu_chubunrui=self.hachu_chubunrui_var.get(),
            hachu_shoubunrui=hachu_shoubunrui,
            hachu_saibunrui=hachu_saibunrui,
            hachu_multi=hachu_multi,
            koji_name=self.koji_name_var.get(),
            place_search_type=self.place_list_radio_var.get(),
            place_chihou=self.place_chihou_var.get(),
            place_todofuken=self.place_todofuken_var.get(),
            place_shichouson=self.place_shichouson_var.get(),
            place_text=self.place_text_var.get(),
            contract_types=contract_types,
            update_date_type=self.update_date_radio_var.get(),
            update_date_days=update_date_days,
            koukoku_date_type=self.koukoku_date_radio_var.get(),
            koukoku_date_start=self.koukoku_date_start_var.get() or None,
            koukoku_date_end=self.koukoku_date_end_var.get() or None,
            kaisatsu_date_type=self.kaisatsu_date_radio_var.get(),
            kaisatsu_date_start=self.kaisatsu_date_start_var.get() or None,
            kaisatsu_date_end=self.kaisatsu_date_end_var.get() or None,
            keiyaku_date_type=self.keiyaku_date_radio_var.get(),
            keiyaku_date_start=self.keiyaku_date_start_var.get() or None,
            keiyaku_date_end=self.keiyaku_date_end_var.get() or None,
            koji_shubetsu=label_to_code("koji_shubetsu", self.koji_shubetsu_var.get(), self.logger),
            koji_gyoushu=label_to_code("koji_gyoushu", self.koji_gyoushu_var.get(), self.logger),
            yotei_price_min=safe_int(self.yotei_price_min_var.get()),
            yotei_price_max=safe_int(self.yotei_price_max_var.get()),
            rakusatsu_price_min=safe_int(self.rakusatsu_price_min_var.get()),
            rakusatsu_price_max=safe_int(self.rakusatsu_price_max_var.get()),
            rakusatsu_name=self.rakusatsu_name_var.get(),
            denshi=self.denshi_var.get(),
            koukai=self.koukai_var.get(),
            display_count=int(self.display_count_var.get()) if self.display_count_var.get() else 20,
        )

    # ------------------------------------------------------------------
    # 大分類オプション非同期ロード
    # ------------------------------------------------------------------

    def load_daibunrui_options(self):
        """大分類オプションを非同期でロード"""
        def load():
            try:
                svc = self._get_lookup_service()
                opts = svc.get_hachu_daibunrui()
                self._dialog.after(0, lambda: self._apply_daibunrui(opts))
            except Exception as e:
                self.logger.warning(f"設定ダイアログ 発注機関オプション読み込みエラー: {e}")
                self._dialog.after(0, lambda: self._apply_daibunrui([]))
        Thread(target=load, daemon=True).start()

    def _apply_daibunrui(self, options: list):
        if options:
            self.hachu_daibunrui_combo["values"] = [""] + options
        current_d = (self.hachu_daibunrui_var.get() or "").strip()
        if current_d:
            self._load_chubunrui_for(current_d)
        chihou = (self.place_chihou_var.get() or "").strip()
        if chihou:
            self._load_todofuken_for(chihou)

    # ------------------------------------------------------------------
    # 発注機関ドロップダウン
    # ------------------------------------------------------------------

    def _on_hachu_daibunrui_changed(self, event=None):
        d = (self.hachu_daibunrui_var.get() or "").strip()
        self.hachu_chubunrui_var.set("")
        self.hachu_chubunrui_combo["values"] = [""]
        if not d:
            return
        self._load_chubunrui_for(d)

    def _load_chubunrui_for(self, d: str):
        def load():
            try:
                svc = self._get_lookup_service()
                opts = svc.get_hachu_chubunrui(d)
                self._dialog.after(0, lambda: self._update_chubunrui(opts))
            except Exception as e:
                self.logger.warning(f"中分類オプション読み込みエラー: {e}")
                self._dialog.after(0, lambda: self._update_chubunrui([]))
        Thread(target=load, daemon=True).start()

    def _update_chubunrui(self, options: list):
        if options is None:
            options = []
        self.hachu_chubunrui_combo["values"] = [""] + options if options else [""]
        c = (self.hachu_chubunrui_var.get() or "").strip()
        if c and options and c in options:
            self.hachu_chubunrui_combo.current(options.index(c) + 1)

    # ------------------------------------------------------------------
    # 工事場所ドロップダウン
    # ------------------------------------------------------------------

    def _on_place_chihou_changed(self, event=None):
        chihou = (self.place_chihou_var.get() or "").strip()
        self.place_todofuken_var.set("")
        self.place_shichouson_var.set("")
        self.place_todofuken_combobox["values"] = [""]
        self.place_shichouson_combobox["values"] = [""]
        if not chihou:
            return
        self._load_todofuken_for(chihou)

    def _load_todofuken_for(self, chihou: str):
        def load():
            try:
                svc = self._get_lookup_service()
                opts = svc.get_koji_prefecture(chihou)
                self._dialog.after(0, lambda: self._apply_todofuken(opts))
            except Exception as e:
                self.logger.warning(f"都道府県オプション読み込みエラー: {e}")
                self._dialog.after(0, lambda: self._apply_todofuken([]))
        Thread(target=load, daemon=True).start()

    def _apply_todofuken(self, options: list):
        if options is None:
            options = []
        self.place_todofuken_combobox["values"] = [""] + options if options else [""]
        todofuken = (self.place_todofuken_var.get() or "").strip()
        if todofuken and options and todofuken in options:
            self.place_todofuken_combobox.current(options.index(todofuken) + 1)
            chihou = (self.place_chihou_var.get() or "").strip()
            if chihou:
                self._load_shichouson_for(chihou, todofuken)
        else:
            self.place_shichouson_combobox["values"] = [""]

    def _on_place_todofuken_changed(self, event=None):
        chihou = (self.place_chihou_var.get() or "").strip()
        todofuken = (self.place_todofuken_var.get() or "").strip()
        self.place_shichouson_var.set("")
        self.place_shichouson_combobox["values"] = [""]
        if not chihou or not todofuken:
            return
        self._load_shichouson_for(chihou, todofuken)

    def _load_shichouson_for(self, chihou: str, todofuken: str):
        def load():
            try:
                svc = self._get_lookup_service()
                opts = svc.get_koji_city(chihou, todofuken)
                self._dialog.after(0, lambda: self._update_shichouson(opts))
            except Exception as e:
                self.logger.warning(f"市町村オプション読み込みエラー: {e}")
                self._dialog.after(0, lambda: self._update_shichouson([]))
        Thread(target=load, daemon=True).start()

    def _update_shichouson(self, options: list):
        if options is None:
            options = []
        self.place_shichouson_combobox["values"] = [""] + options if options else [""]
        shichouson = (self.place_shichouson_var.get() or "").strip()
        if shichouson and options and shichouson in options:
            self.place_shichouson_combobox.current(options.index(shichouson) + 1)
