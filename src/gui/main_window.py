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
from ..models.config_model import AppConfig, SearchConditions
from ..utils.logger import Logger
from ..gui.event_handler import EventHandler
from ..utils.http_client import HTTPClient
from ..config.config_manager import ConfigManager
from ..app.lookup_service import LookupService
from ..gui.widgets.search_conditions_frame import SearchConditionsFrame

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

        # ダウンロード関連
        self.download_callback: Optional[Callable] = None
        self.cancel_flag = Event()
        self.download_thread: Optional[Thread] = None

        default_search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        self._search_url = (config.target_urls[0] if (config.target_urls and config.target_urls[0]) else default_search_url)

        # 階層ドロップダウン用のHTTPClientとLookupService（遅延初期化）
        self._http_client = None
        self._lookup_service = None

        self.setup_font()
        self.setup_ui()

        self.event_handler = EventHandler(root, self)
        self.event_handler.start_polling()

        self.load_config_to_ui()
        self.search_frame.load_daibunrui_options()

    # ------------------------------------------------------------------
    # フォント
    # ------------------------------------------------------------------

    def setup_font(self):
        """日本語フォントをセットアップ"""
        import platform
        system = platform.system()
        if system == "Windows":
            font_family = "Yu Gothic UI"
        elif system == "Darwin":
            font_family = "Hiragino Sans"
        else:
            font_family = "Noto Sans CJK JP"

        default_font = tkinter.font.nametofont("TkDefaultFont")
        default_font.configure(family=font_family, size=10)
        text_font = tkinter.font.nametofont("TkTextFont")
        text_font.configure(family=font_family, size=10)
        fixed_font = tkinter.font.nametofont("TkFixedFont")
        fixed_font.configure(family=font_family, size=10)

<<<<<<< HEAD
        style = ttk.Style()
        style.configure(".", font=(font_family, 10))
        style.configure("TButton", font=(font_family, 10))
        style.configure("TLabel", font=(font_family, 10))
        style.configure("TCheckbutton", font=(font_family, 10))
        style.configure("TRadiobutton", font=(font_family, 10))
        style.configure("TLabelframe.Label", font=(font_family, 10))

    # ------------------------------------------------------------------
    # UI レイアウト
    # ------------------------------------------------------------------
=======
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
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0

    def setup_ui(self):
        """UIをセットアップ"""
        self.root.title("ippi-down - ppi.jp入札情報ダウンローダー")
        self.root.geometry("1200x800")

<<<<<<< HEAD
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
=======
        # メインフレーム（CustomTkinter）
        main_frame = ctk.CTkFrame(self.root, corner_radius=0)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=6, pady=6)
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0

        # ツールバー（CustomTkinterボタン）- コンパクト
        toolbar = ctk.CTkFrame(main_frame, fg_color="transparent")
        toolbar.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 2))

<<<<<<< HEAD
        self.btn_settings = ttk.Button(toolbar, text="設定", command=self.on_settings_open)
        self.btn_settings.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_download = ttk.Button(toolbar, text="ダウンロード開始", command=self.on_download_start)
        self.btn_download.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_cancel = ttk.Button(toolbar, text="キャンセル", command=self.on_download_cancel, state="disabled")
        self.btn_cancel.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_clear = ttk.Button(toolbar, text="クリア", command=self.on_clear_log)
        self.btn_clear.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_clear_search = ttk.Button(toolbar, text="検索条件クリア", command=self.on_clear_search_conditions)
        self.btn_clear_search.pack(side=tk.LEFT)

        # 検索条件フレーム（スクロール可能）
        search_label_frame = ttk.LabelFrame(main_frame, text="検索条件", padding="5")
        search_label_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))

        canvas = tk.Canvas(search_label_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(search_label_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
=======
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
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # SearchConditionsFrame を配置
        self.search_frame = SearchConditionsFrame(
            scrollable_frame,
            self.config.search_conditions,
            self._get_lookup_service,
            self.logger,
        )

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
<<<<<<< HEAD
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(anchor=tk.W)
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(5, 0))
=======
        self.progress_status_label = ctk.CTkLabel(progress_header, textvariable=self.progress_var, font=ctk.CTkFont(size=13))
        self.progress_status_label.pack(side=tk.LEFT, padx=(8, 0))

        self.progress_bar = ctk.CTkProgressBar(progress_frame, mode="determinate", height=16, corner_radius=3)
        self.progress_bar.pack(fill=tk.X, pady=(4, 0))
        self.progress_bar.set(0)  # 初期値0
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0

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
<<<<<<< HEAD
        main_frame.rowconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)

    # ------------------------------------------------------------------
    # LookupService（遅延初期化）
    # ------------------------------------------------------------------

    def _get_lookup_service(self) -> LookupService:
        """LookupService を取得（遅延初期化）"""
        if self._lookup_service is None:
=======
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
<<<<<<< HEAD
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
=======
        ttk.Label(place_text_frame, text="工事場所:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(place_text_frame, textvariable=self.place_text_var, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5
        )
        ttk.Label(
            place_text_frame,
            text="※条件の複数指定はできません。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))

        # 入札契約方式
        contract_frame = ttk.LabelFrame(parent, text="入札契約方式", padding="5")
        contract_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        # 入札契約方式はWebページでは複数の選択肢が並んでいるが、実際の動作は不明
        # 一旦チェックボックスで実装（Webページの表示通りに並べる）
        contract_types = ["一般競争入札", "公募型指名競争入札", "指名競争入札", "随意契約", "その他方式"]
        self.contract_type_vars = {}
        for i, contract_type in enumerate(contract_types):
            var = tk.BooleanVar(value=contract_type in search_conditions.contract_types)
            self.contract_type_vars[contract_type] = var
            ttk.Checkbutton(contract_frame, text=contract_type, variable=var).grid(
                row=i // 3, column=i % 3, sticky=tk.W, padx=5, pady=2
            )

        # 最終更新日
        update_date_frame = ttk.LabelFrame(parent, text="最終更新日", padding="5")
        update_date_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.update_date_type_var = tk.StringVar(
            value="none" if search_conditions.update_date_type == "none" else "past"
        )
        ttk.Radiobutton(update_date_frame, text="指定なし", variable=self.update_date_type_var, value="none").pack(
            side=tk.LEFT, padx=5
        )
        ttk.Radiobutton(update_date_frame, text="過去", variable=self.update_date_type_var, value="past").pack(
            side=tk.LEFT, padx=5
        )
        self.update_date_days_var = tk.StringVar(
            value=str(search_conditions.update_date_days) if search_conditions.update_date_days else "30"
        )
        ttk.Entry(update_date_frame, textvariable=self.update_date_days_var, width=5).pack(side=tk.LEFT, padx=5)
        ttk.Label(update_date_frame, text="日以内").pack(side=tk.LEFT)

        # 公告日
        koukoku_frame = ttk.LabelFrame(parent, text="公告日", padding="5")
        koukoku_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.koukoku_date_type_var = tk.StringVar(value=search_conditions.koukoku_date_type)
        ttk.Radiobutton(koukoku_frame, text="指定なし", variable=self.koukoku_date_type_var, value="none").pack(
            side=tk.LEFT, padx=5
        )
        ttk.Radiobutton(koukoku_frame, text="期間指定", variable=self.koukoku_date_type_var, value="range").pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(koukoku_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.koukoku_date_start_var = tk.StringVar(
            value=search_conditions.koukoku_date_start or ""
        )
        ttk.Entry(koukoku_frame, textvariable=self.koukoku_date_start_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(koukoku_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)
        # Webページでは「まで」は表示されていないため削除

        # 開札日
        kaisatsu_frame = ttk.LabelFrame(parent, text="開札日", padding="5")
        kaisatsu_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.kaisatsu_date_type_var = tk.StringVar(value=search_conditions.kaisatsu_date_type)
        ttk.Radiobutton(kaisatsu_frame, text="指定なし", variable=self.kaisatsu_date_type_var, value="none").pack(
            side=tk.LEFT, padx=5
        )
        ttk.Radiobutton(kaisatsu_frame, text="期間指定", variable=self.kaisatsu_date_type_var, value="range").pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(kaisatsu_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.kaisatsu_date_start_var = tk.StringVar(
            value=search_conditions.kaisatsu_date_start or ""
        )
        ttk.Entry(kaisatsu_frame, textvariable=self.kaisatsu_date_start_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(kaisatsu_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)
        # Webページでは「まで」は表示されていないため削除

        # 契約日
        keiyaku_frame = ttk.LabelFrame(parent, text="契約日", padding="5")
        keiyaku_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.keiyaku_date_type_var = tk.StringVar(value=search_conditions.keiyaku_date_type)
        ttk.Radiobutton(keiyaku_frame, text="指定なし", variable=self.keiyaku_date_type_var, value="none").pack(
            side=tk.LEFT, padx=5
        )
        ttk.Radiobutton(keiyaku_frame, text="期間指定", variable=self.keiyaku_date_type_var, value="range").pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(keiyaku_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.keiyaku_date_start_var = tk.StringVar(
            value=search_conditions.keiyaku_date_start or ""
        )
        ttk.Entry(keiyaku_frame, textvariable=self.keiyaku_date_start_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(keiyaku_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)
        # Webページでは「まで」は表示されていないため削除

        # 工事種別（プルダウン）
        koji_shubetsu_frame = ttk.LabelFrame(parent, text="工事種別", padding="5")
        koji_shubetsu_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        # 工事種別のオプションを一元管理された定義から取得
        koji_shubetsu_options = get_labels("koji_shubetsu")
        koji_shubetsu_input_frame = ttk.Frame(koji_shubetsu_frame)
        koji_shubetsu_input_frame.pack(fill=tk.X)
        # コードまたはラベルをラベルに変換して表示
        display_value = code_to_label("koji_shubetsu", search_conditions.koji_shubetsu, self.logger)
        self.koji_shubetsu_var = tk.StringVar(value=display_value)
        ttk.Label(koji_shubetsu_input_frame, text="▽以下から選択").pack(side=tk.LEFT, padx=5)
        ttk.Combobox(
            koji_shubetsu_input_frame,
            textvariable=self.koji_shubetsu_var,
            values=koji_shubetsu_options,
            state="readonly",
            width=40,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Label(
            koji_shubetsu_frame,
            text="※国土交通省及び内閣府沖縄総合事務局の区分。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))

        # 工事の業種（プルダウン）
        koji_gyoushu_frame = ttk.LabelFrame(parent, text="工事の業種", padding="5")
        koji_gyoushu_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        # 工事の業種のオプションを一元管理された定義から取得
        koji_gyoushu_options = get_labels("koji_gyoushu")
        koji_gyoushu_input_frame = ttk.Frame(koji_gyoushu_frame)
        koji_gyoushu_input_frame.pack(fill=tk.X)
        # コードまたはラベルをラベルに変換して表示
        display_value = code_to_label("koji_gyoushu", search_conditions.koji_gyoushu, self.logger)
        self.koji_gyoushu_var = tk.StringVar(value=display_value)
        ttk.Label(koji_gyoushu_input_frame, text="▽以下から選択").pack(side=tk.LEFT, padx=5)
        ttk.Combobox(
            koji_gyoushu_input_frame,
            textvariable=self.koji_gyoushu_var,
            values=koji_gyoushu_options,
            state="readonly",
            width=40,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Label(
            koji_gyoushu_frame,
            text="※建設業法（別表第一）準拠。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))

        # 予定価格（範囲指定）
        yotei_price_frame = ttk.LabelFrame(parent, text="予定価格（範囲指定）", padding="5")
        yotei_price_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.yotei_price_min_var = tk.StringVar(
            value=str(search_conditions.yotei_price_min) if search_conditions.yotei_price_min else ""
        )
        self.yotei_price_max_var = tk.StringVar(
            value=str(search_conditions.yotei_price_max) if search_conditions.yotei_price_max else ""
        )
        ttk.Label(yotei_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)
        ttk.Entry(yotei_price_frame, textvariable=self.yotei_price_min_var, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(yotei_price_frame, text="～").pack(side=tk.LEFT, padx=5)
        ttk.Entry(yotei_price_frame, textvariable=self.yotei_price_max_var, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(yotei_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)

        # 落札価格／契約価格（範囲指定）
        rakusatsu_price_frame = ttk.LabelFrame(parent, text="落札価格／契約価格（範囲指定）", padding="5")
        rakusatsu_price_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.rakusatsu_price_min_var = tk.StringVar(
            value=str(search_conditions.rakusatsu_price_min) if search_conditions.rakusatsu_price_min else ""
        )
        self.rakusatsu_price_max_var = tk.StringVar(
            value=str(search_conditions.rakusatsu_price_max) if search_conditions.rakusatsu_price_max else ""
        )
        ttk.Label(rakusatsu_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)
        ttk.Entry(rakusatsu_price_frame, textvariable=self.rakusatsu_price_min_var, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(rakusatsu_price_frame, text="～").pack(side=tk.LEFT, padx=5)
        ttk.Entry(rakusatsu_price_frame, textvariable=self.rakusatsu_price_max_var, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(rakusatsu_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)

        # 落札者名／契約者名（文字列検索）
        rakusatsu_name_frame = ttk.LabelFrame(parent, text="落札者名／契約者名（文字列検索）", padding="5")
        rakusatsu_name_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

>>>>>>> 44d78a093e6bf3e7a6997a5b9c4c1d188ad04c11
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
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0
            if self._http_client is None:
                self._http_client = HTTPClient(
                    self.logger, network_config=getattr(self.config, "network", None)
                )
            self._lookup_service = LookupService(self._http_client, self.logger, self._search_url)
        return self._lookup_service

    # ------------------------------------------------------------------
    # Config ↔ UI
    # ------------------------------------------------------------------

<<<<<<< HEAD
    def load_config_to_ui(self):
        """設定をUIに反映"""
        self.search_frame.load_from_config(self.config.search_conditions)

    def get_config_from_ui(self) -> AppConfig:
        """UIから設定を取得"""
        self.search_frame.write_to_config(self.config.search_conditions)
        return self.config

    # ------------------------------------------------------------------
    # ダウンロード
    # ------------------------------------------------------------------
=======
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
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0

    def set_download_callback(self, callback: Callable):
        """ダウンロードコールバックを設定"""
        self.download_callback = callback

    def on_download_start(self):
        """ダウンロード開始ボタンのハンドラ"""
        if not self.download_callback:
            messagebox.showwarning("警告", "ダウンロード機能が設定されていません")
            return

        self.cancel_flag.clear()
<<<<<<< HEAD
        self.btn_download.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress_bar["value"] = 0
=======

        # UIを更新
        self.btn_download.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress_bar.set(0)  # CTkProgressBarは0-1の範囲
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0
        self.progress_var.set("ダウンロードを開始しています...")

        self.download_thread = Thread(target=self._download_thread)
        self.download_thread.daemon = True
        self.download_thread.start()

    def on_download_cancel(self):
        """ダウンロードキャンセルボタンのハンドラ"""
        if self.cancel_flag.is_set():
            return
        self.cancel_flag.set()
        self.logger.info("ダウンロードをキャンセルしました")
        self.show_message("ダウンロードをキャンセルしました", "warning")
        self.progress_var.set("キャンセル中...")
<<<<<<< HEAD
        self.btn_cancel.config(state="disabled")
=======
        
        # UIを更新
        self.btn_cancel.configure(state="disabled")
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0

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

    # ------------------------------------------------------------------
    # メッセージ / クリア
    # ------------------------------------------------------------------

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

    def on_clear_search_conditions(self):
        """検索条件を既定値に戻し、UIとconfigを同期する"""
        self.config.search_conditions = SearchConditions()
        self.load_config_to_ui()
        if self.config_manager.save_config(self.config):
            self.logger.info("検索条件をクリアし、設定を保存しました")
            self.show_message("検索条件をクリアしました", "info")
        else:
            self.show_message("検索条件をクリアしました（設定ファイルの保存に失敗しました）", "warning")

    # ------------------------------------------------------------------
    # 設定ダイアログ
    # ------------------------------------------------------------------

    def on_settings_open(self):
        """設定画面を開く"""
        from ..gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.root, self.config, self.config_manager, self.logger)
        result = dialog.show()

        if result:
            self.config = result
            default_search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
            self._search_url = (result.target_urls[0] if (result.target_urls and result.target_urls[0]) else default_search_url)
            if self._lookup_service is not None:
                self._lookup_service.search_url = self._search_url
            self.load_config_to_ui()
            self.root.after(100, self.search_frame.load_daibunrui_options)
