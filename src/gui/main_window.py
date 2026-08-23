<<<<<<< HEAD
"""メインウィンドウクラス（CustomTkinter版）"""
=======
# -*- coding: utf-8 -*-

"""メインウィンドウクラス"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

import customtkinter as ctk
import tkinter as tk
import tkinter.font
from tkinter import filedialog, messagebox
from typing import Optional, Callable
from threading import Thread, Event
from ..models.config_model import AppConfig
from ..utils.logger import Logger
from ..gui.event_handler import EventHandler
from ..utils.http_client import HTTPClient
from ..core.scraper import Scraper
from ..config.config_manager import ConfigManager

# CustomTkinter テーマ設定
ctk.set_appearance_mode("dark")  # ダークモード
ctk.set_default_color_theme("blue")  # ブルーテーマ


class MainWindow:
    """メインウィンドウクラス"""

    def __init__(self, root: tk.Tk, config: AppConfig, config_manager: ConfigManager, logger: Optional[Logger] = None):
        """初期化"""
        self.root = root
        self.config = config
        self.config_manager = config_manager
        self.logger = logger or Logger()
        self.download_callback: Optional[Callable] = None

        # ダウンロードキャンセル用のフラグ
        self.cancel_flag = Event()
        self.download_thread: Optional[Thread] = None

        # 階層ドロップダウン用のHTTPClientとScraper（遅延初期化）
        self._http_client = None
        self._scraper = None
        # tabパラメータなしのSearch.aspxを使用
        self._search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"

        # 日本語フォントの設定
        self.setup_font()
        self.setup_ui()
        self.setup_bindings()
        
        # イベントハンドラーを初期化（スレッドセーフなUI更新用）
        self.event_handler = EventHandler(root, self)
        self.event_handler.start_polling()
        
        # 初期化時に大分類のオプションを取得（遅延実行：root.afterでGUI表示後に実行）
        # import時にHTTPリクエストが送られないようにするため
        self.root.after(100, self.load_hachu_daibunrui_options)

    def setup_font(self):
        """日本語フォントを設定（Windows専用）"""
        # Windowsで利用可能な日本語フォントを試す
        fonts_to_try = ["Yu Gothic UI", "MS UI Gothic", "Meiryo UI", "MS PGothic"]
        default_font = None

        # 利用可能なフォントを確認
        try:
            available_fonts = tk.font.families()
            for font in fonts_to_try:
                if font in available_fonts:
                    default_font = font
                    break
        except Exception:
            pass

<<<<<<< HEAD
        # フォントが見つかった場合は設定（CustomTkinterでは内部で管理されるため、tkのみ設定）
        if default_font:
            try:
                # tkウィジェットのデフォルトフォントを設定
=======
        # フォントが見つかった場合は設定
        if default_font:
            try:
                # ttkスタイルのデフォルトフォントを設定
                style = ttk.Style()
                style.configure(".", font=(default_font, 9))
                # tkウィジェットのデフォルトフォントも設定
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33
                default_font_obj = tk.font.nametofont("TkDefaultFont")
                default_font_obj.configure(family=default_font, size=9)
            except Exception as e:
                self.logger.warning(f"フォント設定エラー: {str(e)}")

    def setup_ui(self):
        """UIをセットアップ"""
        self.root.title("ippi-down - ppi.jp入札情報ダウンローダー")
        self.root.geometry("1200x800")

        # メインフレーム（CustomTkinter）
        main_frame = ctk.CTkFrame(self.root, corner_radius=0)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=6, pady=6)

        # ツールバー（CustomTkinterボタン）- コンパクト
        toolbar = ctk.CTkFrame(main_frame, fg_color="transparent")
        toolbar.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 2))

        self.btn_settings = ctk.CTkButton(
            toolbar, text="⚙設定", command=self.on_settings_open,
            width=70, height=28, corner_radius=4,
            fg_color="#4a5568", hover_color="#718096",
            font=ctk.CTkFont(size=13)
        )
        self.btn_settings.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_download = ctk.CTkButton(
            toolbar, text="▶ダウンロード", command=self.on_download_start,
            width=120, height=28, corner_radius=4,
            fg_color="#3182ce", hover_color="#4299e1",
            font=ctk.CTkFont(size=13)
        )
        self.btn_download.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_cancel = ctk.CTkButton(
            toolbar, text="⏹停止", command=self.on_download_cancel,
            width=70, height=28, corner_radius=4,
            fg_color="#e53e3e", hover_color="#fc8181",
            state="disabled",
            font=ctk.CTkFont(size=13)
        )
        self.btn_cancel.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_clear = ctk.CTkButton(
            toolbar, text="🗑クリア", command=self.on_clear_log,
            width=80, height=28, corner_radius=4,
            fg_color="#4a5568", hover_color="#718096",
            font=ctk.CTkFont(size=13)
        )
        self.btn_clear.pack(side=tk.LEFT)

        # PanedWindow（上下リサイズ可能）
        paned_window = tk.PanedWindow(main_frame, orient=tk.VERTICAL, sashwidth=4, sashrelief=tk.RAISED, bg="#555555")
        paned_window.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 2))

        # 上部: 検索条件フレーム
        search_container = ctk.CTkFrame(paned_window, corner_radius=3)
        
        search_label = ctk.CTkLabel(search_container, text="🔍 検索条件", font=ctk.CTkFont(size=16, weight="bold"))
        search_label.pack(anchor=tk.W, padx=8, pady=(6, 4))
        
        # CTkScrollableFrameでスクロール可能なフレーム
        scrollable_frame = ctk.CTkScrollableFrame(search_container, corner_radius=2)
        scrollable_frame.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        # 検索条件を配置
        self.setup_search_conditions(scrollable_frame)

        paned_window.add(search_container, minsize=100, stretch="always")

        # 下部: 進捗＋ログ
        bottom_container = ctk.CTkFrame(paned_window, corner_radius=3)

        # 進捗（CustomTkinter）
        progress_frame = ctk.CTkFrame(bottom_container, corner_radius=2, fg_color="transparent")
        progress_frame.pack(fill=tk.X, padx=6, pady=(6, 4))

        progress_header = ctk.CTkFrame(progress_frame, fg_color="transparent")
        progress_header.pack(fill=tk.X)
        ctk.CTkLabel(progress_header, text="📊 進捗:", font=ctk.CTkFont(size=14, weight="bold")).pack(side=tk.LEFT)
        self.progress_var = tk.StringVar(value="待機中...")
        self.progress_status_label = ctk.CTkLabel(progress_header, textvariable=self.progress_var, font=ctk.CTkFont(size=13))
        self.progress_status_label.pack(side=tk.LEFT, padx=(8, 0))

        self.progress_bar = ctk.CTkProgressBar(progress_frame, mode="determinate", height=16, corner_radius=3)
        self.progress_bar.pack(fill=tk.X, pady=(4, 0))
        self.progress_bar.set(0)  # 初期値0

        # ログ表示（CustomTkinter）
        log_frame = ctk.CTkFrame(bottom_container, corner_radius=2, fg_color="transparent")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 6))

        log_label = ctk.CTkLabel(log_frame, text="📋 ログ", font=ctk.CTkFont(size=14, weight="bold"))
        log_label.pack(anchor=tk.W)

        self.log_text = ctk.CTkTextbox(log_frame, height=100, corner_radius=3, font=ctk.CTkFont(size=12))
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        paned_window.add(bottom_container, minsize=80, stretch="always")

        # グリッドの重み設定
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)  # PanedWindow

    def setup_search_conditions(self, parent):
        """検索条件UIをセットアップ（3列レイアウト・バランス改善版）"""
        search_conditions = self.config.search_conditions
        
        # フォント設定
        title_font = ctk.CTkFont(size=14, weight="bold")
        label_font = ctk.CTkFont(size=12)
        input_font = ctk.CTkFont(size=12)
        check_font = ctk.CTkFont(size=12)
        
        # 共通設定
        combo_h = 30
        entry_h = 30
        frame_border = "#666666"
        frame_radius = 5
        input_radius = 4
        
        # 親フレームの列設定（3列均等）
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=1)
        
        # ===== 左列 =====
        left_col = ctk.CTkFrame(parent, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 4))
        
        # 発注機関
        hachu_frame = ctk.CTkFrame(left_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        hachu_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(hachu_frame, text="🏢 発注機関", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        
        hachu_grid = ctk.CTkFrame(hachu_frame, fg_color="transparent")
        hachu_grid.pack(fill=tk.X, padx=8, pady=(0, 6))
        
        ctk.CTkLabel(hachu_grid, text="大分類:", font=label_font).grid(row=0, column=0, sticky=tk.W, pady=3)
        self.hachu_daibunrui_var = tk.StringVar(value=search_conditions.hachu_daibunrui)
        self.hachu_daibunrui_combo = ctk.CTkComboBox(hachu_grid, variable=self.hachu_daibunrui_var, values=[], width=180, height=combo_h, corner_radius=input_radius, font=input_font, command=self.on_hachu_daibunrui_changed)
        self.hachu_daibunrui_combo.grid(row=0, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        ctk.CTkLabel(hachu_grid, text="中分類:", font=label_font).grid(row=1, column=0, sticky=tk.W, pady=3)
        self.hachu_chubunrui_var = tk.StringVar(value=search_conditions.hachu_chubunrui)
        self.hachu_chubunrui_combo = ctk.CTkComboBox(hachu_grid, variable=self.hachu_chubunrui_var, values=[], width=180, height=combo_h, corner_radius=input_radius, font=input_font, command=self.on_hachu_chubunrui_changed)
        self.hachu_chubunrui_combo.grid(row=1, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        ctk.CTkLabel(hachu_grid, text="小分類:", font=label_font).grid(row=2, column=0, sticky=tk.W, pady=3)
        self.hachu_shoubunrui_var = tk.StringVar(value=search_conditions.hachu_shoubunrui)
        self.hachu_shoubunrui_combo = ctk.CTkComboBox(hachu_grid, variable=self.hachu_shoubunrui_var, values=[], width=180, height=combo_h, corner_radius=input_radius, font=input_font, command=self.on_hachu_shoubunrui_changed)
        self.hachu_shoubunrui_combo.grid(row=2, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        ctk.CTkLabel(hachu_grid, text="細分類:", font=label_font).grid(row=3, column=0, sticky=tk.W, pady=3)
        self.hachu_saibunrui_var = tk.StringVar(value=search_conditions.hachu_saibunrui)
        self.hachu_saibunrui_combo = ctk.CTkComboBox(hachu_grid, variable=self.hachu_saibunrui_var, values=[], width=180, height=combo_h, corner_radius=input_radius, font=input_font)
        self.hachu_saibunrui_combo.grid(row=3, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        self.hachu_multi_var = tk.StringVar()
        
        # 工事場所
        place_frame = ctk.CTkFrame(left_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        place_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(place_frame, text="📍 工事場所", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        
        place_grid = ctk.CTkFrame(place_frame, fg_color="transparent")
        place_grid.pack(fill=tk.X, padx=8, pady=(0, 6))
        
        place_chihou_options = ["", "北海道", "東北", "関東", "北陸", "中部", "近畿", "中国", "四国", "九州・沖縄"]
        ctk.CTkLabel(place_grid, text="地方:", font=label_font).grid(row=0, column=0, sticky=tk.W, pady=3)
        self.place_chihou_var = tk.StringVar(value=search_conditions.place_chihou or "")
        self.place_chihou_combobox = ctk.CTkComboBox(place_grid, variable=self.place_chihou_var, values=place_chihou_options, width=180, height=combo_h, corner_radius=input_radius, font=input_font)
        self.place_chihou_combobox.grid(row=0, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        ctk.CTkLabel(place_grid, text="都道府県:", font=label_font).grid(row=1, column=0, sticky=tk.W, pady=3)
        self.place_todofuken_var = tk.StringVar(value=search_conditions.place_todofuken)
        self.place_todofuken_combo = ctk.CTkComboBox(place_grid, variable=self.place_todofuken_var, values=[], width=180, height=combo_h, corner_radius=input_radius, font=input_font)
        self.place_todofuken_combo.grid(row=1, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        ctk.CTkLabel(place_grid, text="市町村:", font=label_font).grid(row=2, column=0, sticky=tk.W, pady=3)
        self.place_shichouson_var = tk.StringVar(value=search_conditions.place_shichouson)
        self.place_shichouson_combo = ctk.CTkComboBox(place_grid, variable=self.place_shichouson_var, values=[], width=180, height=combo_h, corner_radius=input_radius, font=input_font)
        self.place_shichouson_combo.grid(row=2, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        ctk.CTkLabel(place_grid, text="文字列:", font=label_font).grid(row=3, column=0, sticky=tk.W, pady=3)
        self.place_text_var = tk.StringVar(value=search_conditions.place_text)
        ctk.CTkEntry(place_grid, textvariable=self.place_text_var, width=180, height=entry_h, corner_radius=input_radius, font=input_font).grid(row=3, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        # ===== 中央列 =====
        center_col = ctk.CTkFrame(parent, fg_color="transparent")
        center_col.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=4)
        
        # 工事名
        koji_frame = ctk.CTkFrame(center_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        koji_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(koji_frame, text="🔨 工事名", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        self.koji_name_var = tk.StringVar(value=search_conditions.koji_name)
        ctk.CTkEntry(koji_frame, textvariable=self.koji_name_var, height=entry_h, corner_radius=input_radius, font=input_font).pack(fill=tk.X, padx=8, pady=(0, 6))
        
        # 落札者名
        name_frame = ctk.CTkFrame(center_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        name_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(name_frame, text="👤 落札者名", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        self.rakusatsu_name_var = tk.StringVar(value=search_conditions.rakusatsu_name)
        ctk.CTkEntry(name_frame, textvariable=self.rakusatsu_name_var, height=entry_h, corner_radius=input_radius, font=input_font).pack(fill=tk.X, padx=8, pady=(0, 6))
        
        # 種別・業種
        type_frame = ctk.CTkFrame(center_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        type_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(type_frame, text="🔧 種別・業種", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        
        type_grid = ctk.CTkFrame(type_frame, fg_color="transparent")
        type_grid.pack(fill=tk.X, padx=8, pady=(0, 6))
        
        koji_shubetsu_options = ["", "一般土木工事", "建築工事", "電気設備工事", "機械設備工事", "その他"]
        koji_gyoushu_options = ["", "土木一式工事", "建築一式工事", "電気工事", "管工事", "その他"]
        
        ctk.CTkLabel(type_grid, text="工事種別:", font=label_font).grid(row=0, column=0, sticky=tk.W, pady=3)
        self.koji_shubetsu_var = tk.StringVar(value=search_conditions.koji_shubetsu)
        self.koji_shubetsu_combo = ctk.CTkComboBox(type_grid, variable=self.koji_shubetsu_var, values=koji_shubetsu_options, width=180, height=combo_h, corner_radius=input_radius, font=input_font)
        self.koji_shubetsu_combo.grid(row=0, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        ctk.CTkLabel(type_grid, text="業種:", font=label_font).grid(row=1, column=0, sticky=tk.W, pady=3)
        self.koji_gyoushu_var = tk.StringVar(value=search_conditions.koji_gyoushu)
        self.koji_gyoushu_combo = ctk.CTkComboBox(type_grid, variable=self.koji_gyoushu_var, values=koji_gyoushu_options, width=180, height=combo_h, corner_radius=input_radius, font=input_font)
        self.koji_gyoushu_combo.grid(row=1, column=1, sticky=tk.W, padx=(6, 0), pady=3)
        
        # 入札契約方式
        contract_frame = ctk.CTkFrame(center_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        contract_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(contract_frame, text="📋 入札契約方式", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        
        contract_grid = ctk.CTkFrame(contract_frame, fg_color="transparent")
        contract_grid.pack(fill=tk.X, padx=8, pady=(0, 8))
        contract_types = [("一般競争入札", "一般競争"), ("公募型指名競争入札", "公募型指名"), ("指名競争入札", "指名競争"), ("随意契約", "随意契約"), ("その他方式", "その他")]
        self.contract_type_vars = {}
        for i, (full_name, short_name) in enumerate(contract_types):
            var = tk.BooleanVar(value=full_name in search_conditions.contract_types)
            self.contract_type_vars[full_name] = var
            ctk.CTkCheckBox(contract_grid, text=short_name, variable=var, font=check_font, height=26, corner_radius=4, checkbox_width=20, checkbox_height=20).grid(row=i // 3, column=i % 3, sticky=tk.W, padx=4, pady=3)
        
        # ===== 右列 =====
        right_col = ctk.CTkFrame(parent, fg_color="transparent")
        right_col.grid(row=0, column=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(4, 0))
        
        # 日付条件
        date_frame = ctk.CTkFrame(right_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        date_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(date_frame, text="📅 日付条件", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        
        date_grid = ctk.CTkFrame(date_frame, fg_color="transparent")
        date_grid.pack(fill=tk.X, padx=8, pady=(0, 6))
        
        # 最終更新日
        ctk.CTkLabel(date_grid, text="更新日:", font=label_font).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.update_date_type_var = tk.StringVar(value="none" if search_conditions.update_date_type == "none" else "past")
        update_inner = ctk.CTkFrame(date_grid, fg_color="transparent")
        update_inner.grid(row=0, column=1, sticky=tk.W, pady=2)
        ctk.CTkRadioButton(update_inner, text="なし", variable=self.update_date_type_var, value="none", font=label_font, height=20).pack(side=tk.LEFT)
        ctk.CTkRadioButton(update_inner, text="過去", variable=self.update_date_type_var, value="past", font=label_font, height=20).pack(side=tk.LEFT, padx=(8, 0))
        self.update_date_days_var = tk.StringVar(value=str(search_conditions.update_date_days) if search_conditions.update_date_days else "30")
        ctk.CTkEntry(update_inner, textvariable=self.update_date_days_var, width=45, height=22, corner_radius=input_radius, font=input_font).pack(side=tk.LEFT, padx=4)
        ctk.CTkLabel(update_inner, text="日", font=label_font).pack(side=tk.LEFT)
        
        # 公告日・開札日・契約日
        for i, (name, var_name, type_var_name) in enumerate([
            ("公告日:", "koukoku_date_start_var", "koukoku_date_type_var"),
            ("開札日:", "kaisatsu_date_start_var", "kaisatsu_date_type_var"),
            ("契約日:", "keiyaku_date_start_var", "keiyaku_date_type_var"),
        ]):
            ctk.CTkLabel(date_grid, text=name, font=label_font).grid(row=i+1, column=0, sticky=tk.W, pady=2)
            setattr(self, type_var_name, tk.StringVar(value=getattr(search_conditions, type_var_name.replace("_var", ""))))
            inner = ctk.CTkFrame(date_grid, fg_color="transparent")
            inner.grid(row=i+1, column=1, sticky=tk.W, pady=2)
            ctk.CTkRadioButton(inner, text="なし", variable=getattr(self, type_var_name), value="none", font=label_font, height=20).pack(side=tk.LEFT)
            ctk.CTkRadioButton(inner, text="指定", variable=getattr(self, type_var_name), value="range", font=label_font, height=20).pack(side=tk.LEFT, padx=(8, 0))
            setattr(self, var_name, tk.StringVar(value=getattr(search_conditions, var_name.replace("_var", "")) or ""))
            ctk.CTkEntry(inner, textvariable=getattr(self, var_name), width=90, height=22, corner_radius=input_radius, font=input_font, placeholder_text="YYYY-MM-DD").pack(side=tk.LEFT, padx=4)
        
        # 価格条件
        price_frame = ctk.CTkFrame(right_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        price_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(price_frame, text="💰 価格条件", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        
        price_grid = ctk.CTkFrame(price_frame, fg_color="transparent")
        price_grid.pack(fill=tk.X, padx=8, pady=(0, 6))
        
        ctk.CTkLabel(price_grid, text="予定価格:", font=label_font).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.yotei_price_min_var = tk.StringVar(value=str(search_conditions.yotei_price_min) if search_conditions.yotei_price_min else "")
        self.yotei_price_max_var = tk.StringVar(value=str(search_conditions.yotei_price_max) if search_conditions.yotei_price_max else "")
        price_inner1 = ctk.CTkFrame(price_grid, fg_color="transparent")
        price_inner1.grid(row=0, column=1, sticky=tk.W, pady=2)
        ctk.CTkEntry(price_inner1, textvariable=self.yotei_price_min_var, width=70, height=22, corner_radius=input_radius, font=input_font, placeholder_text="最小").pack(side=tk.LEFT)
        ctk.CTkLabel(price_inner1, text="～", font=label_font).pack(side=tk.LEFT, padx=2)
        ctk.CTkEntry(price_inner1, textvariable=self.yotei_price_max_var, width=70, height=22, corner_radius=input_radius, font=input_font, placeholder_text="最大").pack(side=tk.LEFT)
        ctk.CTkLabel(price_inner1, text="円", font=label_font).pack(side=tk.LEFT, padx=(2, 0))
        
        ctk.CTkLabel(price_grid, text="落札価格:", font=label_font).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.rakusatsu_price_min_var = tk.StringVar(value=str(search_conditions.rakusatsu_price_min) if search_conditions.rakusatsu_price_min else "")
        self.rakusatsu_price_max_var = tk.StringVar(value=str(search_conditions.rakusatsu_price_max) if search_conditions.rakusatsu_price_max else "")
        price_inner2 = ctk.CTkFrame(price_grid, fg_color="transparent")
        price_inner2.grid(row=1, column=1, sticky=tk.W, pady=2)
        ctk.CTkEntry(price_inner2, textvariable=self.rakusatsu_price_min_var, width=70, height=22, corner_radius=input_radius, font=input_font, placeholder_text="最小").pack(side=tk.LEFT)
        ctk.CTkLabel(price_inner2, text="～", font=label_font).pack(side=tk.LEFT, padx=2)
        ctk.CTkEntry(price_inner2, textvariable=self.rakusatsu_price_max_var, width=70, height=22, corner_radius=input_radius, font=input_font, placeholder_text="最大").pack(side=tk.LEFT)
        ctk.CTkLabel(price_inner2, text="円", font=label_font).pack(side=tk.LEFT, padx=(2, 0))
        
        # オプション
        option_frame = ctk.CTkFrame(right_col, corner_radius=frame_radius, border_width=1, border_color=frame_border)
        option_frame.pack(fill=tk.X, pady=(0, 4))
        ctk.CTkLabel(option_frame, text="⚙️ オプション", font=title_font).pack(anchor=tk.W, padx=8, pady=(6, 4))
        
        option_inner = ctk.CTkFrame(option_frame, fg_color="transparent")
        option_inner.pack(fill=tk.X, padx=8, pady=(0, 6))
        
        self.denshi_var = tk.BooleanVar(value=search_conditions.denshi)
        ctk.CTkCheckBox(option_inner, text="電子入札のみ", variable=self.denshi_var, font=check_font, height=26, corner_radius=4, checkbox_width=20, checkbox_height=20).pack(side=tk.LEFT, padx=(0, 16))
        
        self.koukai_var = tk.BooleanVar(value=search_conditions.koukai)
        ctk.CTkCheckBox(option_inner, text="公開中のみ", variable=self.koukai_var, font=check_font, height=26, corner_radius=4, checkbox_width=20, checkbox_height=20).pack(side=tk.LEFT, padx=(0, 16))
        
        ctk.CTkLabel(option_inner, text="表示件数:", font=label_font).pack(side=tk.LEFT, padx=(12, 6))
        self.display_count_var = tk.StringVar(value=str(search_conditions.display_count))
        ctk.CTkComboBox(option_inner, variable=self.display_count_var, values=["20", "30", "50", "100"], width=80, height=combo_h, corner_radius=input_radius, font=input_font).pack(side=tk.LEFT)

    def setup_bindings(self):
        """イベントバインディングをセットアップ"""
        pass

    def _get_scraper(self):
        """Scraperインスタンスを取得（遅延初期化）"""
        if self._scraper is None:
            if self._http_client is None:
                self._http_client = HTTPClient(self.logger)
            self._scraper = Scraper(self._http_client, self.logger)
        return self._scraper

    def load_hachu_daibunrui_options(self):
        """大分類のオプションを読み込む"""
        def load_in_thread():
            try:
                scraper = self._get_scraper()
                options = scraper.get_hachu_daibunrui_options(self._search_url)
                # GUIスレッドで更新
                self.root.after(0, lambda: self._update_hachu_daibunrui_options(options))
            except Exception as e:
                self.logger.error(f"大分類オプション読み込みエラー: {str(e)}")
                self.root.after(0, lambda: self.show_message(f"大分類オプションの読み込みに失敗しました: {str(e)}", "error"))
        
        Thread(target=load_in_thread, daemon=True).start()

    def _update_hachu_daibunrui_options(self, options: list):
        """大分類のオプションを更新"""
        if options:
            self.hachu_daibunrui_combo.configure(values=[""] + options)
        else:
            # フォールバック: 固定のオプション
            self.hachu_daibunrui_combo.configure(values=["", "国の機関", "地方公共団体（都道府県）", "地方公共団体（市区町村）", "テスト機関"])

    def on_hachu_daibunrui_changed(self, value=None):
        """大分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        if not daibunrui_value:
            # 大分類がクリアされた場合は、中分類以下もクリア
            self.hachu_chubunrui_combo.configure(values=[])
            self.hachu_chubunrui_var.set("")
            self.hachu_shoubunrui_combo.configure(values=[])
            self.hachu_shoubunrui_var.set("")
            self.hachu_saibunrui_combo.configure(values=[])
            self.hachu_saibunrui_var.set("")
            return
        
        # 中分類のオプションを読み込む
        def load_in_thread():
            try:
                scraper = self._get_scraper()
                options = scraper.get_hachu_chubunrui_options(self._search_url, daibunrui_value)
                self.root.after(0, lambda: self._update_hachu_chubunrui_options(options))
            except Exception as e:
                self.logger.error(f"中分類オプション読み込みエラー: {str(e)}")
                self.root.after(0, lambda: self.show_message(f"中分類オプションの読み込みに失敗しました: {str(e)}", "error"))
        
        # 中分類以下をクリア
        self.hachu_chubunrui_var.set("")
        self.hachu_shoubunrui_var.set("")
        self.hachu_saibunrui_var.set("")
        self.hachu_shoubunrui_combo.configure(values=[])
        self.hachu_saibunrui_combo.configure(values=[])
        
        Thread(target=load_in_thread, daemon=True).start()

    def _update_hachu_chubunrui_options(self, options: list):
        """中分類のオプションを更新"""
        self.hachu_chubunrui_combo.configure(values=[""] + options)

    def on_hachu_chubunrui_changed(self, value=None):
        """中分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        chubunrui_value = self.hachu_chubunrui_var.get()
        if not chubunrui_value or not daibunrui_value:
            # 小分類以下をクリア
            self.hachu_shoubunrui_combo.configure(values=[])
            self.hachu_shoubunrui_var.set("")
            self.hachu_saibunrui_combo.configure(values=[])
            self.hachu_saibunrui_var.set("")
            return
        
        # 小分類のオプションを読み込む
        def load_in_thread():
            try:
                scraper = self._get_scraper()
                options = scraper.get_hachu_shoubunrui_options(self._search_url, daibunrui_value, chubunrui_value)
                self.root.after(0, lambda: self._update_hachu_shoubunrui_options(options))
            except Exception as e:
                self.logger.error(f"小分類オプション読み込みエラー: {str(e)}")
                self.root.after(0, lambda: self.show_message(f"小分類オプションの読み込みに失敗しました: {str(e)}", "error"))
        
        # 小分類・細分類をクリア
        self.hachu_shoubunrui_var.set("")
<<<<<<< HEAD
        self.hachu_shoubunrui_combo.configure(values=[])
=======
        self.hachu_shoubunrui_combo['values'] = []
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33
        self.hachu_saibunrui_var.set("")
        self.hachu_saibunrui_combo.configure(values=[])
        
        Thread(target=load_in_thread, daemon=True).start()

    def _update_hachu_shoubunrui_options(self, options: list):
        """小分類のオプションを更新"""
        self.hachu_shoubunrui_combo.configure(values=[""] + options)

    def on_hachu_shoubunrui_changed(self, value=None):
        """小分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        chubunrui_value = self.hachu_chubunrui_var.get()
        shoubunrui_value = self.hachu_shoubunrui_var.get()
        if not shoubunrui_value or not chubunrui_value or not daibunrui_value:
            # 細分類をクリア
            self.hachu_saibunrui_combo.configure(values=[])
            self.hachu_saibunrui_var.set("")
            return
        
        # 細分類のオプションを読み込む
        def load_in_thread():
            try:
                scraper = self._get_scraper()
                options = scraper.get_hachu_saibunrui_options(self._search_url, daibunrui_value, chubunrui_value, shoubunrui_value)
                self.root.after(0, lambda: self._update_hachu_saibunrui_options(options))
            except Exception as e:
                self.logger.error(f"細分類オプション読み込みエラー: {str(e)}")
                self.root.after(0, lambda: self.show_message(f"細分類オプションの読み込みに失敗しました: {str(e)}", "error"))
        
        Thread(target=load_in_thread, daemon=True).start()

    def _update_hachu_saibunrui_options(self, options: list):
        """細分類のオプションを更新"""
        self.hachu_saibunrui_combo.configure(values=[""] + options)

    def set_download_callback(self, callback: Callable):
        """ダウンロードコールバックを設定"""
        self.download_callback = callback

    def on_download_start(self):
        """ダウンロード開始ボタンのハンドラ"""
        if not self.download_callback:
            messagebox.showwarning("警告", "ダウンロード機能が設定されていません")
            return

        # キャンセルフラグをリセット
        self.cancel_flag.clear()

        # UIを更新
        self.btn_download.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress_bar.set(0)  # CTkProgressBarは0-1の範囲
        self.progress_var.set("ダウンロードを開始しています...")

        # 別スレッドでダウンロードを実行
        self.download_thread = Thread(target=self._download_thread)
        self.download_thread.daemon = True
        self.download_thread.start()

    def on_download_cancel(self):
        """ダウンロードキャンセルボタンのハンドラ"""
        if self.cancel_flag.is_set():
            return  # 既にキャンセル済み
        
        self.cancel_flag.set()
        self.logger.info("ダウンロードをキャンセルしました")
        self.show_message("ダウンロードをキャンセルしました", "warning")
        self.progress_var.set("キャンセル中...")
        
        # UIを更新
        self.btn_cancel.configure(state="disabled")

    def _download_thread(self):
        """ダウンロードスレッド"""
        try:
            if self.download_callback:
                self.download_callback(self)
        except Exception as e:
            if not self.cancel_flag.is_set():
            self.logger.error(f"ダウンロードエラー: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("エラー", f"ダウンロードエラー: {str(e)}"))
        finally:
            self.root.after(0, lambda: self._reset_download_ui())

    def _reset_download_ui(self):
        """ダウンロードUIをリセット"""
        self.btn_download.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        if not self.cancel_flag.is_set():
            self.progress_var.set("完了")

    def update_progress(self, current: int, total: int, filename: str = ""):
        """進捗を更新"""
        if total > 0:
            percentage = current / total  # CTkProgressBarは0-1の範囲
            self.progress_bar.set(percentage)
            self.progress_var.set(f"{current}/{total} ({percentage*100:.1f}%) - {filename}")

    def show_message(self, message: str, level: str = "info"):
        """メッセージを表示"""
        # レベルに応じた色付きプレフィックス
        level_colors = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅"
        }
        prefix = level_colors.get(level.lower(), "ℹ️")
        self.log_text.insert("end", f"{prefix} [{level.upper()}] {message}\n")
        self.log_text.see("end")

    def on_clear_log(self):
        """ログをクリア"""
        self.log_text.delete("1.0", "end")
        self.show_message("ログをクリアしました", "info")

    def on_settings_open(self):
        """設定画面を開く"""
        from ..gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.root, self.config, self.config_manager, self.logger)
        result = dialog.show()

        if result:
            # 設定が保存された場合、メインウィンドウの設定を更新
            self.config = result
            self.load_config_to_ui()

    def load_config_to_ui(self):
        """設定をUIに反映"""
        # 検索条件をUIに反映
        search_conditions = self.config.search_conditions
        
        # 発注機関（リスト検索）
        self.hachu_daibunrui_var.set(search_conditions.hachu_daibunrui)
        self.hachu_chubunrui_var.set(search_conditions.hachu_chubunrui)
        self.hachu_shoubunrui_var.set(search_conditions.hachu_shoubunrui)
        self.hachu_saibunrui_var.set(search_conditions.hachu_saibunrui)

        # 発注機関（複数選択検索）
        if search_conditions.hachu_multi:
            self.hachu_multi_var.set(", ".join(search_conditions.hachu_multi))
        else:
            self.hachu_multi_var.set("")

        # 工事名
        self.koji_name_var.set(search_conditions.koji_name)

        # 工事場所（空文字列の場合は明示的に空文字列を設定）
        place_chihou_value = search_conditions.place_chihou if search_conditions.place_chihou else ""
        # readonlyのComboboxで空文字列を選択するには、current(0)を使用する必要がある
        if not place_chihou_value:
            # 空文字列の場合は、Comboboxのcurrent(0)を使用
            self.place_chihou_var.set("")
            if hasattr(self, 'place_chihou_combobox'):
                self.place_chihou_combobox.current(0)
        else:
            self.place_chihou_var.set(place_chihou_value)
            # 値が設定されている場合、その値のインデックスを探す
            place_chihou_options = ["", "北海道", "東北", "関東", "北陸", "中部", "近畿", "中国", "四国", "九州・沖縄"]
            try:
                index = place_chihou_options.index(place_chihou_value)
                if hasattr(self, 'place_chihou_combobox'):
                    self.place_chihou_combobox.current(index)
            except ValueError:
                # 値が見つからない場合は空文字列を選択
                if hasattr(self, 'place_chihou_combobox'):
                    self.place_chihou_combobox.current(0)
        self.place_todofuken_var.set(search_conditions.place_todofuken)
        self.place_shichouson_var.set(search_conditions.place_shichouson)
        self.place_text_var.set(search_conditions.place_text)

        # 入札契約方式
        for contract_type, var in self.contract_type_vars.items():
            var.set(contract_type in search_conditions.contract_types)

        # 最終更新日
        self.update_date_type_var.set(search_conditions.update_date_type)
        if search_conditions.update_date_days:
            self.update_date_days_var.set(str(search_conditions.update_date_days))

        # 公告日、開札日、契約日
        self.koukoku_date_type_var.set(search_conditions.koukoku_date_type)
        self.koukoku_date_start_var.set(search_conditions.koukoku_date_start or "")
        
        self.kaisatsu_date_type_var.set(search_conditions.kaisatsu_date_type)
        self.kaisatsu_date_start_var.set(search_conditions.kaisatsu_date_start or "")
        
        self.keiyaku_date_type_var.set(search_conditions.keiyaku_date_type)
        self.keiyaku_date_start_var.set(search_conditions.keiyaku_date_start or "")

        # 工事種別、工事の業種
        self.koji_shubetsu_var.set(search_conditions.koji_shubetsu)
        self.koji_gyoushu_var.set(search_conditions.koji_gyoushu)

        # 価格
        if search_conditions.yotei_price_min:
            self.yotei_price_min_var.set(str(search_conditions.yotei_price_min))
        if search_conditions.yotei_price_max:
            self.yotei_price_max_var.set(str(search_conditions.yotei_price_max))
        if search_conditions.rakusatsu_price_min:
            self.rakusatsu_price_min_var.set(str(search_conditions.rakusatsu_price_min))
        if search_conditions.rakusatsu_price_max:
            self.rakusatsu_price_max_var.set(str(search_conditions.rakusatsu_price_max))

        # 落札者名
        self.rakusatsu_name_var.set(search_conditions.rakusatsu_name)

        # オプション
        self.denshi_var.set(search_conditions.denshi)
        self.koukai_var.set(search_conditions.koukai)

        # 表示件数
        self.display_count_var.set(str(search_conditions.display_count))

    def get_config_from_ui(self) -> AppConfig:
        """UIから設定を取得"""
        # 検索条件を取得
        search_conditions = self.config.search_conditions

        # 発注機関（リスト検索）
        search_conditions.hachu_daibunrui = self.hachu_daibunrui_var.get()
        search_conditions.hachu_chubunrui = self.hachu_chubunrui_var.get()
        search_conditions.hachu_shoubunrui = self.hachu_shoubunrui_var.get()
        search_conditions.hachu_saibunrui = self.hachu_saibunrui_var.get()

        # 発注機関（複数選択検索）
        hachu_multi_text = self.hachu_multi_var.get().strip()
        if hachu_multi_text:
            search_conditions.hachu_multi = [item.strip() for item in hachu_multi_text.split(",") if item.strip()]
        else:
            search_conditions.hachu_multi = []

        # 工事名
        search_conditions.koji_name = self.koji_name_var.get()

        # 工事場所
        search_conditions.place_chihou = self.place_chihou_var.get()
        search_conditions.place_todofuken = self.place_todofuken_var.get()
        search_conditions.place_shichouson = self.place_shichouson_var.get()
        search_conditions.place_text = self.place_text_var.get()

        # 入札契約方式
        search_conditions.contract_types = [
            ct for ct, var in self.contract_type_vars.items() if var.get()
        ]

        # 最終更新日
        search_conditions.update_date_type = self.update_date_type_var.get()
        try:
            search_conditions.update_date_days = int(self.update_date_days_var.get())
        except ValueError:
            search_conditions.update_date_days = None

        # 公告日、開札日、契約日
        search_conditions.koukoku_date_type = self.koukoku_date_type_var.get()
        search_conditions.koukoku_date_start = self.koukoku_date_start_var.get() or None
        
        search_conditions.kaisatsu_date_type = self.kaisatsu_date_type_var.get()
        search_conditions.kaisatsu_date_start = self.kaisatsu_date_start_var.get() or None
        
        search_conditions.keiyaku_date_type = self.keiyaku_date_type_var.get()
        search_conditions.keiyaku_date_start = self.keiyaku_date_start_var.get() or None

        # 工事種別、工事の業種（単一選択）
        search_conditions.koji_shubetsu = self.koji_shubetsu_var.get()
        search_conditions.koji_gyoushu = self.koji_gyoushu_var.get()

        # 価格
        try:
            search_conditions.yotei_price_min = int(self.yotei_price_min_var.get()) if self.yotei_price_min_var.get() else None
        except ValueError:
            search_conditions.yotei_price_min = None
        try:
            search_conditions.yotei_price_max = int(self.yotei_price_max_var.get()) if self.yotei_price_max_var.get() else None
        except ValueError:
            search_conditions.yotei_price_max = None
        try:
            search_conditions.rakusatsu_price_min = int(self.rakusatsu_price_min_var.get()) if self.rakusatsu_price_min_var.get() else None
        except ValueError:
            search_conditions.rakusatsu_price_min = None
        try:
            search_conditions.rakusatsu_price_max = int(self.rakusatsu_price_max_var.get()) if self.rakusatsu_price_max_var.get() else None
        except ValueError:
            search_conditions.rakusatsu_price_max = None

        # 落札者名
        search_conditions.rakusatsu_name = self.rakusatsu_name_var.get()

        # オプション
        search_conditions.denshi = self.denshi_var.get()
        search_conditions.koukai = self.koukai_var.get()

        # 表示件数
        try:
            search_conditions.display_count = int(self.display_count_var.get())
        except ValueError:
            search_conditions.display_count = 20

        return self.config
