# -*- coding: utf-8 -*-

"""メインウィンドウクラス"""

import tkinter as tk
import tkinter.font
from tkinter import ttk, filedialog, messagebox, scrolledtext
from typing import Optional, Callable
from threading import Thread, Event
from ..models.config_model import AppConfig
from ..utils.logger import Logger
from ..gui.event_handler import EventHandler
from ..utils.http_client import HTTPClient
from ..core.scraper import Scraper
from ..config.config_manager import ConfigManager
from ..core.ppi_dropdowns import get_labels, code_to_label, label_to_code


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
        # 検索URL: config の target_urls[0] を優先し、無ければ tab=4(工事) をデフォルトに
        default_search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        self._search_url = (config.target_urls[0] if (config.target_urls and config.target_urls[0]) else default_search_url)

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
        # 工事場所の階層（地方→都道府県→市町村）も config に値があれば復元
        self.root.after(400, self._restore_place_hierarchy_from_values)

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

        # フォントが見つかった場合は設定
        if default_font:
            try:
                # ttkスタイルのデフォルトフォントを設定
                style = ttk.Style()
                style.configure(".", font=(default_font, 9))
                # tkウィジェットのデフォルトフォントも設定
                default_font_obj = tk.font.nametofont("TkDefaultFont")
                default_font_obj.configure(family=default_font, size=9)
            except Exception as e:
                self.logger.warning(f"フォント設定エラー: {str(e)}")

    def setup_ui(self):
        """UIをセットアップ"""
        self.root.title("ippi-down - ppi.jp入札情報ダウンローダー")
        self.root.geometry("1200x800")

        # メインフレーム
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # ツールバー
        toolbar = ttk.Frame(main_frame)
        toolbar.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        self.btn_settings = ttk.Button(toolbar, text="設定", command=self.on_settings_open)
        self.btn_settings.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_download = ttk.Button(
            toolbar, text="ダウンロード開始", command=self.on_download_start
        )
        self.btn_download.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_cancel = ttk.Button(
            toolbar, text="キャンセル", command=self.on_download_cancel, state="disabled"
        )
        self.btn_cancel.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_clear = ttk.Button(toolbar, text="クリア", command=self.on_clear_log)
        self.btn_clear.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_clear_search = ttk.Button(
            toolbar, text="検索条件クリア", command=self.on_clear_search_conditions
        )
        self.btn_clear_search.pack(side=tk.LEFT)

        # 検索条件フレーム（スクロール可能にする）
        search_frame = ttk.LabelFrame(main_frame, text="検索条件", padding="5")
        search_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))

        # スクロール可能なキャンバス
        canvas = tk.Canvas(search_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(search_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        def configure_canvas_width(event):
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)
        
        canvas.bind("<Configure>", configure_canvas_width)
        canvas.configure(yscrollcommand=scrollbar.set)

        # マウスホイールでのスクロールを有効化
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        def bind_mousewheel(event):
            canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        def unbind_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")
        
        canvas.bind("<Enter>", bind_mousewheel)
        canvas.bind("<Leave>", unbind_mousewheel)

        # 検索条件を配置
        self.setup_search_conditions(scrollable_frame)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 進捗
        progress_frame = ttk.LabelFrame(main_frame, text="進捗", padding="5")
        progress_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        self.progress_var = tk.StringVar(value="待機中...")
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(anchor=tk.W)

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(5, 0))

        # ログ表示
        log_frame = ttk.LabelFrame(main_frame, text="ログ", padding="5")
        log_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=100)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # グリッドの重み設定
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)  # 検索条件フレーム
        main_frame.rowconfigure(3, weight=1)  # ログフレーム

    def setup_search_conditions(self, parent: ttk.Frame):
        """検索条件UIをセットアップ"""
        search_conditions = self.config.search_conditions
        row = 0

        # 親フレームの列の重みを設定
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        # 発注機関（リスト検索）
        hachu_frame = ttk.LabelFrame(parent, text="発注機関（リスト検索）", padding="5")
        hachu_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        hachu_frame.columnconfigure(1, weight=1)
        row += 1

        # 大分類、中分類、小分類、細分類（プルダウン）
        ttk.Label(hachu_frame, text="大分類:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.hachu_daibunrui_var = tk.StringVar(value=search_conditions.hachu_daibunrui)
        self.hachu_daibunrui_combo = ttk.Combobox(
            hachu_frame,
            textvariable=self.hachu_daibunrui_var,
            values=[],  # 動的読み込み
            state="readonly",
            width=30,
        )
        self.hachu_daibunrui_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.hachu_daibunrui_combo.bind("<<ComboboxSelected>>", self.on_hachu_daibunrui_changed)

        ttk.Label(hachu_frame, text="中分類:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.hachu_chubunrui_var = tk.StringVar(value=search_conditions.hachu_chubunrui)
        self.hachu_chubunrui_combo = ttk.Combobox(
            hachu_frame,
            textvariable=self.hachu_chubunrui_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        )
        self.hachu_chubunrui_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.hachu_chubunrui_combo.bind("<<ComboboxSelected>>", self.on_hachu_chubunrui_changed)
        self.hachu_chubunrui_combo.bind("<FocusIn>", self._on_hachu_chubunrui_focusin)

        ttk.Label(hachu_frame, text="小分類:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.hachu_shoubunrui_var = tk.StringVar(value=search_conditions.hachu_shoubunrui)
        self.hachu_shoubunrui_combo = ttk.Combobox(
            hachu_frame,
            textvariable=self.hachu_shoubunrui_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        )
        self.hachu_shoubunrui_combo.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.hachu_shoubunrui_combo.bind("<<ComboboxSelected>>", self.on_hachu_shoubunrui_changed)
        self.hachu_shoubunrui_combo.bind("<FocusIn>", self._on_hachu_shoubunrui_focusin)

        ttk.Label(hachu_frame, text="細分類:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.hachu_saibunrui_var = tk.StringVar(value=search_conditions.hachu_saibunrui)
        self.hachu_saibunrui_combo = ttk.Combobox(
            hachu_frame,
            textvariable=self.hachu_saibunrui_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        )
        self.hachu_saibunrui_combo.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.hachu_saibunrui_combo.bind("<<ComboboxSelected>>", self.on_hachu_saibunrui_changed)
        self.hachu_saibunrui_combo.bind("<FocusIn>", self._on_hachu_saibunrui_focusin)

        # 発注機関（複数選択検索）
        hachu_multi_frame = ttk.LabelFrame(parent, text="発注機関（複数選択検索）", padding="5")
        hachu_multi_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        hachu_multi_frame.columnconfigure(0, weight=1)
        row += 1

        hachu_multi_input_frame = ttk.Frame(hachu_multi_frame)
        hachu_multi_input_frame.pack(fill=tk.X)
        self.hachu_multi_var = tk.StringVar()
        hachu_multi_entry = ttk.Entry(hachu_multi_input_frame, textvariable=self.hachu_multi_var, width=60)
        hachu_multi_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Label(hachu_multi_input_frame, text="(カンマ区切りで複数指定)").pack(side=tk.LEFT, padx=5)
        ttk.Label(
            hachu_multi_frame,
            text="※リスト検索と複数選択検索は同時に使用できません。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))

        # 工事名（文字列検索）
        koji_name_frame = ttk.LabelFrame(parent, text="工事名（文字列検索）", padding="5")
        koji_name_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.koji_name_var = tk.StringVar(value=search_conditions.koji_name)
        ttk.Label(koji_name_frame, text="工事名:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(koji_name_frame, textvariable=self.koji_name_var, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5
        )
        ttk.Label(
            koji_name_frame,
            text="※条件の複数指定はできません。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))

        # 工事場所（リスト検索）
        place_frame = ttk.LabelFrame(parent, text="工事場所（リスト検索）", padding="5")
        place_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        place_frame.columnconfigure(1, weight=1)
        row += 1

        # 地方、都道府県、市町村（プルダウン）
        place_chihou_options = ["", "北海道", "東北", "関東", "北陸", "中部", "近畿", "中国", "四国", "九州・沖縄"]
        ttk.Label(place_frame, text="地方:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        # 初期値を明示的に空文字列に設定（検索条件が空文字列でない場合のみ設定）
        initial_place_chihou = search_conditions.place_chihou if search_conditions.place_chihou else ""
        self.place_chihou_var = tk.StringVar(value=initial_place_chihou)
        self.place_chihou_combobox = ttk.Combobox(
            place_frame,
            textvariable=self.place_chihou_var,
            values=place_chihou_options,
            state="readonly",
            width=30,
        )
        self.place_chihou_combobox.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        self.place_chihou_combobox.bind("<<ComboboxSelected>>", self.on_place_chihou_changed)
        # readonlyのComboboxで空文字列を選択するには、current(0)を使用する必要がある
        if not initial_place_chihou:
            self.place_chihou_combobox.current(0)  # 最初の要素（空文字列）を選択
        else:
            # 検索条件に値が設定されている場合、その値のインデックスを探す
            try:
                index = place_chihou_options.index(initial_place_chihou)
                self.place_chihou_combobox.current(index)
            except ValueError:
                # 値が見つからない場合は空文字列を選択
                self.place_chihou_combobox.current(0)

        ttk.Label(place_frame, text="都道府県:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.place_todofuken_var = tk.StringVar(value=search_conditions.place_todofuken)
        self.place_todofuken_combobox = ttk.Combobox(
            place_frame,
            textvariable=self.place_todofuken_var,
            values=[""],  # 動的読み込み（地方選択で更新）。空配列だと固まるため最低 [""]
            state="readonly",
            width=30,
        )
        self.place_todofuken_combobox.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        self.place_todofuken_combobox.bind("<<ComboboxSelected>>", self.on_place_todofuken_changed)

        ttk.Label(place_frame, text="市町村:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.place_shichouson_var = tk.StringVar(value=search_conditions.place_shichouson)
        self.place_shichouson_combobox = ttk.Combobox(
            place_frame,
            textvariable=self.place_shichouson_var,
            values=[""],  # 動的読み込み（都道府県選択で更新）
            state="readonly",
            width=30,
        )
        self.place_shichouson_combobox.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        # 工事場所（文字列検索）
        place_text_frame = ttk.LabelFrame(parent, text="工事場所（文字列検索）", padding="5")
        place_text_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.place_text_var = tk.StringVar(value=search_conditions.place_text)
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
            value=str(search_conditions.update_date_days) if search_conditions.update_date_days else ""
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

        self.rakusatsu_name_var = tk.StringVar(value=search_conditions.rakusatsu_name)
        ttk.Label(rakusatsu_name_frame, text="落札者名／契約者名:").pack(side=tk.LEFT, padx=5)
        ttk.Entry(rakusatsu_name_frame, textvariable=self.rakusatsu_name_var, width=50).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5
        )
        ttk.Label(
            rakusatsu_name_frame,
            text="※条件の複数指定はできません。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))

        # 電子入札・公開文書
        option_frame = ttk.LabelFrame(parent, text="オプション", padding="5")
        option_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)
        row += 1

        self.denshi_var = tk.BooleanVar(value=search_conditions.denshi)
        ttk.Checkbutton(option_frame, text="電子入札：対象案件のみ", variable=self.denshi_var).pack(
            side=tk.LEFT, padx=5
        )

        self.koukai_var = tk.BooleanVar(value=search_conditions.koukai)
        ttk.Checkbutton(option_frame, text="公開文書：公開中のみ", variable=self.koukai_var).pack(
            side=tk.LEFT, padx=5
        )

        # 表示件数
        display_count_frame = ttk.LabelFrame(parent, text="一覧画面の表示件数", padding="5")
        display_count_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5)

        self.display_count_var = tk.StringVar(value=str(search_conditions.display_count))
        for count in ["20", "30", "50", "100"]:
            ttk.Radiobutton(
                display_count_frame, text=f"{count}件", variable=self.display_count_var, value=count
            ).pack(side=tk.LEFT, padx=5)

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
            self.hachu_daibunrui_combo['values'] = [""] + options
        else:
            # フォールバック: 固定のオプション
            self.hachu_daibunrui_combo['values'] = ["", "国の機関", "地方公共団体（都道府県）", "地方公共団体（市区町村）", "テスト機関"]
        # 起動時/設定戻り時に現在値に基づいて中分類以下を復元（中分類以下が空で選べない問題を解消）
        self._restore_hachu_hierarchy_from_values()

    def _restore_hachu_hierarchy_from_values(self):
        """現在の大分類〜細分類の値に基づいて階層オプションをロードし、Combobox を選択可能にする。
        起動時・設定ダイアログから戻った後に呼ぶ。ユーザー操作の on_*_changed は使わず専用経路でクリアせずロードする。
        """
        d = (self.hachu_daibunrui_var.get() or "").strip()
        c = (self.hachu_chubunrui_var.get() or "").strip()
        s = (self.hachu_shoubunrui_var.get() or "").strip()
        a = (self.hachu_saibunrui_var.get() or "").strip()
        if not d:
            return

        def load_in_thread():
            results = {}
            try:
                scraper = self._get_scraper()
                results["chubunrui"] = scraper.get_hachu_chubunrui_options(self._search_url, d)
                if c:
                    results["shoubunrui"] = scraper.get_hachu_shoubunrui_options(self._search_url, d, c)
                if c and s:
                    results["saibunrui"] = scraper.get_hachu_saibunrui_options(self._search_url, d, c, s)
            except Exception as e:
                self.logger.error(f"発注機関階層復元エラー: {str(e)}")
            self.root.after(0, lambda: self._apply_restored_hachu_options(results, d, c, s, a))

        Thread(target=load_in_thread, daemon=True).start()

    def _apply_restored_hachu_options(
        self, results: dict, daibunrui_val: str, chubunrui_val: str, shoubunrui_val: str, saibunrui_val: str
    ):
        """スレッド取得したオプションを GUI に反映し、保存されていた値を current で選択する。空でも [""] で死なせない。"""
        try:
            if "chubunrui" in results:
                raw = results["chubunrui"] or []
                opts = [""] + raw
                self.hachu_chubunrui_combo["values"] = opts
                if not raw:
                    self.logger.warning("中分類オプション取得が空でした。大分類を再選択するかクリックで再読み込みできます。")
                elif chubunrui_val and chubunrui_val in raw:
                    idx = raw.index(chubunrui_val) + 1
                    self.hachu_chubunrui_combo.current(idx)
                elif chubunrui_val:
                    self.hachu_chubunrui_var.set("")
            if "shoubunrui" in results:
                raw = results["shoubunrui"] or []
                opts = [""] + raw
                self.hachu_shoubunrui_combo["values"] = opts
                if not raw:
                    self.logger.warning("小分類オプション取得が空でした。中分類を再選択するかクリックで再読み込みできます。")
                elif shoubunrui_val and shoubunrui_val in raw:
                    idx = raw.index(shoubunrui_val) + 1
                    self.hachu_shoubunrui_combo.current(idx)
                elif shoubunrui_val:
                    self.hachu_shoubunrui_var.set("")
            if "saibunrui" in results:
                raw = results["saibunrui"] or []
                opts = [""] + raw
                self.hachu_saibunrui_combo["values"] = opts
                if not raw:
                    self.logger.warning("細分類オプション取得が空でした。小分類を再選択するかクリックで再読み込みできます。")
                elif saibunrui_val and saibunrui_val in raw:
                    idx = raw.index(saibunrui_val) + 1
                    self.hachu_saibunrui_combo.current(idx)
                elif saibunrui_val:
                    self.hachu_saibunrui_var.set("")
        except Exception as e:
            self.logger.warning(f"発注機関階層反映エラー: {str(e)}")

    def on_hachu_daibunrui_changed(self, event=None):
        """大分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        if not daibunrui_value:
            # 大分類がクリアされた場合は、中分類以下もクリア（values は [""] で残して操作可能に）
            self.hachu_chubunrui_combo['values'] = [""]
            self.hachu_chubunrui_var.set("")
            self.hachu_shoubunrui_combo['values'] = [""]
            self.hachu_shoubunrui_var.set("")
            self.hachu_saibunrui_combo['values'] = [""]
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
        
        # 中分類以下をクリア（values は [""] で残す）
        self.hachu_chubunrui_var.set("")
        self.hachu_shoubunrui_var.set("")
        self.hachu_saibunrui_var.set("")
        self.hachu_shoubunrui_combo['values'] = [""]
        self.hachu_saibunrui_combo['values'] = [""]
        
        Thread(target=load_in_thread, daemon=True).start()

    def _update_hachu_chubunrui_options(self, options: list):
        """中分類のオプションを更新（空でも [""] にしてUIを死なせない）"""
        if options is None:
            options = []
        self.hachu_chubunrui_combo['values'] = [""] + options if options else [""]
        if not options:
            self.logger.warning("中分類オプションが空です。大分類を再選択するか、クリックで再読み込みできます。")

    def on_hachu_chubunrui_changed(self, event=None):
        """中分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        chubunrui_value = self.hachu_chubunrui_var.get()
        if not chubunrui_value or not daibunrui_value:
            # 小分類以下をクリア
            self.hachu_shoubunrui_combo['values'] = [""]
            self.hachu_shoubunrui_var.set("")
            self.hachu_saibunrui_combo['values'] = [""]
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
        self.hachu_shoubunrui_combo['values'] = [""]
        self.hachu_saibunrui_var.set("")
        self.hachu_saibunrui_combo['values'] = [""]
        
        Thread(target=load_in_thread, daemon=True).start()

    def _update_hachu_shoubunrui_options(self, options: list):
        """小分類のオプションを更新（空でも [""] にしてUIを死なせない）"""
        if options is None:
            options = []
        self.hachu_shoubunrui_combo['values'] = [""] + options if options else [""]
        if not options:
            self.logger.warning("小分類オプションが空です。中分類を再選択するか、クリックで再読み込みできます。")

    def on_hachu_shoubunrui_changed(self, event=None):
        """小分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        chubunrui_value = self.hachu_chubunrui_var.get()
        shoubunrui_value = self.hachu_shoubunrui_var.get()
        if not shoubunrui_value or not chubunrui_value or not daibunrui_value:
            # 細分類をクリア
            self.hachu_saibunrui_combo['values'] = [""]
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
        """細分類のオプションを更新（空でも [""] にしてUIを死なせない）"""
        if options is None:
            options = []
        self.hachu_saibunrui_combo['values'] = [""] + options if options else [""]
        if not options:
            self.logger.warning("細分類オプションが空です。小分類を再選択するか、クリックで再読み込みできます。")

    def on_hachu_saibunrui_changed(self, event=None):
        """細分類が変更されたとき（下位階層は無いため処理なし）"""
        pass

    def _is_values_effectively_empty(self, combo: ttk.Combobox) -> bool:
        """Combobox の values が実質空（選択肢がない）か"""
        try:
            v = list(combo["values"]) if combo["values"] else []
        except (tk.TclError, TypeError):
            v = []
        return len(v) == 0 or (len(v) == 1 and (v[0] == "" or v[0] is None))

    def _on_hachu_chubunrui_focusin(self, event=None):
        """中分類にフォーカスしたとき、オプションが空なら大分類に基づき再ロード"""
        if not self._is_values_effectively_empty(self.hachu_chubunrui_combo):
            return
        d = (self.hachu_daibunrui_var.get() or "").strip()
        if not d:
            return
        def load():
            try:
                scraper = self._get_scraper()
                options = scraper.get_hachu_chubunrui_options(self._search_url, d)
                self.root.after(0, lambda: self._update_hachu_chubunrui_options(options))
            except Exception as e:
                self.logger.warning(f"中分類再読み込みエラー: {e}")
        Thread(target=load, daemon=True).start()

    def _on_hachu_shoubunrui_focusin(self, event=None):
        """小分類にフォーカスしたとき、オプションが空なら中分類に基づき再ロード"""
        if not self._is_values_effectively_empty(self.hachu_shoubunrui_combo):
            return
        d = (self.hachu_daibunrui_var.get() or "").strip()
        c = (self.hachu_chubunrui_var.get() or "").strip()
        if not d or not c:
            return
        def load():
            try:
                scraper = self._get_scraper()
                options = scraper.get_hachu_shoubunrui_options(self._search_url, d, c)
                self.root.after(0, lambda: self._update_hachu_shoubunrui_options(options))
            except Exception as e:
                self.logger.warning(f"小分類再読み込みエラー: {e}")
        Thread(target=load, daemon=True).start()

    def _on_hachu_saibunrui_focusin(self, event=None):
        """細分類にフォーカスしたとき、オプションが空なら小分類に基づき再ロード"""
        if not self._is_values_effectively_empty(self.hachu_saibunrui_combo):
            return
        d = (self.hachu_daibunrui_var.get() or "").strip()
        c = (self.hachu_chubunrui_var.get() or "").strip()
        s = (self.hachu_shoubunrui_var.get() or "").strip()
        if not d or not c or not s:
            return
        def load():
            try:
                scraper = self._get_scraper()
                options = scraper.get_hachu_saibunrui_options(self._search_url, d, c, s)
                self.root.after(0, lambda: self._update_hachu_saibunrui_options(options))
            except Exception as e:
                self.logger.warning(f"細分類再読み込みエラー: {e}")
        Thread(target=load, daemon=True).start()

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
        self.btn_download.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress_bar["value"] = 0
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
        self.btn_cancel.config(state="disabled")

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
        self.btn_download.config(state="normal")
        self.btn_cancel.config(state="disabled")
        if not self.cancel_flag.is_set():
            self.progress_var.set("完了")

    def update_progress(self, current: int, total: int, filename: str = ""):
        """進捗を更新"""
        if total > 0:
            percentage = (current / total) * 100
            self.progress_bar["value"] = percentage
            self.progress_var.set(f"{current}/{total} ({percentage:.1f}%) - {filename}")

    def show_message(self, message: str, level: str = "info"):
        """メッセージを表示"""
        self.log_text.insert(tk.END, f"[{level.upper()}] {message}\n")
        self.log_text.see(tk.END)

    def on_clear_log(self):
        """ログをクリア"""
        self.log_text.delete(1.0, tk.END)
        self.show_message("ログをクリアしました", "info")

    def on_clear_search_conditions(self):
        """検索条件を既定値に戻し、UIとconfigを同期する"""
        from ..models.config_model import SearchConditions
        self.config.search_conditions = SearchConditions()
        self.load_config_to_ui()
        if self.config_manager.save_config(self.config):
            self.logger.info("検索条件をクリアし、設定を保存しました")
            self.show_message("検索条件をクリアしました", "info")
        else:
            self.show_message("検索条件をクリアしました（設定ファイルの保存に失敗しました）", "warning")

    def on_settings_open(self):
        """設定画面を開く"""
        from ..gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.root, self.config, self.config_manager, self.logger)
        result = dialog.show()

        if result:
            # 設定が保存された場合、メインウィンドウの設定を更新
            self.config = result
            default_search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
            self._search_url = (result.target_urls[0] if (result.target_urls and result.target_urls[0]) else default_search_url)
            self.load_config_to_ui()
            # 発注機関オプションを再ロード（設定でURLが変わった場合に備える）
            self.root.after(100, self.load_hachu_daibunrui_options)

    def load_config_to_ui(self):
        """設定をUIに反映"""
        # 検索条件をUIに反映
        search_conditions = self.config.search_conditions
        
        # 発注機関（リスト検索）（値がない場合は必ずクリア）
        self.hachu_daibunrui_var.set(search_conditions.hachu_daibunrui or "")
        self.hachu_chubunrui_var.set(search_conditions.hachu_chubunrui or "")
        self.hachu_shoubunrui_var.set(search_conditions.hachu_shoubunrui or "")
        self.hachu_saibunrui_var.set(search_conditions.hachu_saibunrui or "")

        # 発注機関（複数選択検索）
        if search_conditions.hachu_multi:
            self.hachu_multi_var.set(", ".join(search_conditions.hachu_multi))
        else:
            self.hachu_multi_var.set("")

        # 工事名（空のときはクリア）
        self.koji_name_var.set(search_conditions.koji_name or "")

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
        self.place_todofuken_var.set(search_conditions.place_todofuken or "")
        self.place_shichouson_var.set(search_conditions.place_shichouson or "")
        self.place_text_var.set(search_conditions.place_text or "")

        # 入札契約方式
        for contract_type, var in self.contract_type_vars.items():
            var.set(contract_type in search_conditions.contract_types)

        # 最終更新日（値がない場合は必ずクリア）
        self.update_date_type_var.set(search_conditions.update_date_type or "none")
        if search_conditions.update_date_days is not None:
            self.update_date_days_var.set(str(search_conditions.update_date_days))
        else:
            self.update_date_days_var.set("")

        # 公告日、開札日、契約日（値がない場合は必ずクリア）
        self.koukoku_date_type_var.set(search_conditions.koukoku_date_type or "none")
        self.koukoku_date_start_var.set(search_conditions.koukoku_date_start or "")
        
        self.kaisatsu_date_type_var.set(search_conditions.kaisatsu_date_type or "none")
        self.kaisatsu_date_start_var.set(search_conditions.kaisatsu_date_start or "")
        
        self.keiyaku_date_type_var.set(search_conditions.keiyaku_date_type or "none")
        self.keiyaku_date_start_var.set(search_conditions.keiyaku_date_start or "")

        # 工事種別、工事の業種（コードまたはラベルをラベルに変換して表示）
        self.koji_shubetsu_var.set(code_to_label("koji_shubetsu", search_conditions.koji_shubetsu, self.logger))
        self.koji_gyoushu_var.set(code_to_label("koji_gyoushu", search_conditions.koji_gyoushu, self.logger))

        # 価格（値がない場合は必ずクリア）
        if search_conditions.yotei_price_min is not None:
            self.yotei_price_min_var.set(str(search_conditions.yotei_price_min))
        else:
            self.yotei_price_min_var.set("")
        if search_conditions.yotei_price_max is not None:
            self.yotei_price_max_var.set(str(search_conditions.yotei_price_max))
        else:
            self.yotei_price_max_var.set("")
        if search_conditions.rakusatsu_price_min is not None:
            self.rakusatsu_price_min_var.set(str(search_conditions.rakusatsu_price_min))
        else:
            self.rakusatsu_price_min_var.set("")
        if search_conditions.rakusatsu_price_max is not None:
            self.rakusatsu_price_max_var.set(str(search_conditions.rakusatsu_price_max))
        else:
            self.rakusatsu_price_max_var.set("")

        # 落札者名（空のときはクリア）
        self.rakusatsu_name_var.set(search_conditions.rakusatsu_name or "")

        # オプション
        self.denshi_var.set(search_conditions.denshi)
        self.koukai_var.set(search_conditions.koukai)

        # 表示件数（値がない場合は既定値 20）
        self.display_count_var.set(
            str(search_conditions.display_count) if search_conditions.display_count is not None else "20"
        )
        # 設定ダイアログから戻った後、発注機関の階層オプションを現在値に基づいて復元する
        self.root.after(0, self._restore_hachu_hierarchy_from_values)
        # 工事場所（地方→都道府県→市町村）の階層オプションも復元
        self.root.after(200, self._restore_place_hierarchy_from_values)

    def on_place_chihou_changed(self, event=None):
        """地方が変更されたとき：都道府県オプションをロードし、都道府県・市町村をクリア"""
        chihou = (self.place_chihou_var.get() or "").strip()
        self.place_todofuken_var.set("")
        self.place_shichouson_var.set("")
        self.place_todofuken_combobox["values"] = [""]
        self.place_shichouson_combobox["values"] = [""]
        if not chihou:
            return
        def load():
            try:
                scraper = self._get_scraper()
                options = scraper.get_koji_prefecture_options(self._search_url, chihou)
                self.root.after(0, lambda: self._update_place_todofuken_options(options))
            except Exception as e:
                self.logger.warning(f"都道府県オプション読み込みエラー: {e}")
                self.root.after(0, lambda: self._update_place_todofuken_options([]))
        Thread(target=load, daemon=True).start()

    def _update_place_todofuken_options(self, options: list):
        """都道府県のオプションを更新"""
        if options is None:
            options = []
        self.place_todofuken_combobox["values"] = [""] + options if options else [""]
        if not options:
            self.logger.warning("都道府県オプションが空です。")

    def on_place_todofuken_changed(self, event=None):
        """都道府県が変更されたとき：市町村オプションをロード"""
        chihou = (self.place_chihou_var.get() or "").strip()
        todofuken = (self.place_todofuken_var.get() or "").strip()
        self.place_shichouson_var.set("")
        self.place_shichouson_combobox["values"] = [""]
        if not chihou or not todofuken:
            return
        def load():
            try:
                scraper = self._get_scraper()
                options = scraper.get_koji_city_options(self._search_url, chihou, todofuken)
                self.root.after(0, lambda: self._update_place_shichouson_options(options))
            except Exception as e:
                self.logger.warning(f"市町村オプション読み込みエラー: {e}")
                self.root.after(0, lambda: self._update_place_shichouson_options([]))
        Thread(target=load, daemon=True).start()

    def _update_place_shichouson_options(self, options: list):
        """市町村のオプションを更新"""
        if options is None:
            options = []
        self.place_shichouson_combobox["values"] = [""] + options if options else [""]
        if not options:
            self.logger.warning("市町村オプションが空です。")

    def _restore_place_hierarchy_from_values(self):
        """現在の地方・都道府県・市町村に基づいて階層オプションをロードし、選択可能にする"""
        chihou = (self.place_chihou_var.get() or "").strip()
        todofuken = (self.place_todofuken_var.get() or "").strip()
        shichouson = (self.place_shichouson_var.get() or "").strip()
        if not chihou:
            return
        def load():
            results = {}
            try:
                scraper = self._get_scraper()
                results["todofuken"] = scraper.get_koji_prefecture_options(self._search_url, chihou)
                if todofuken:
                    results["shichouson"] = scraper.get_koji_city_options(self._search_url, chihou, todofuken)
            except Exception as e:
                self.logger.warning(f"工事場所階層復元エラー: {e}")
            self.root.after(0, lambda: self._apply_restored_place_options(results, chihou, todofuken, shichouson))
        Thread(target=load, daemon=True).start()

    def _apply_restored_place_options(
        self, results: dict, chihou: str, todofuken: str, shichouson: str
    ):
        """工事場所の復元オプションをUIに反映"""
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

        # 工事場所（place_search_type を必ず設定：文字列が非空なら text、空なら list）
        place_text_raw = (self.place_text_var.get() or "").strip()
        if place_text_raw:
            search_conditions.place_search_type = "text"
            search_conditions.place_text = place_text_raw
            search_conditions.place_chihou = ""
            search_conditions.place_todofuken = ""
            search_conditions.place_shichouson = ""
        else:
            search_conditions.place_search_type = "list"
            search_conditions.place_text = ""
            search_conditions.place_chihou = self.place_chihou_var.get()
            search_conditions.place_todofuken = self.place_todofuken_var.get()
            search_conditions.place_shichouson = self.place_shichouson_var.get()

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

        # 公告日、開札日、契約日（UIに無い end は残さない＝None でクリア）
        search_conditions.koukoku_date_type = self.koukoku_date_type_var.get()
        search_conditions.koukoku_date_start = self.koukoku_date_start_var.get() or None
        search_conditions.koukoku_date_end = None

        search_conditions.kaisatsu_date_type = self.kaisatsu_date_type_var.get()
        search_conditions.kaisatsu_date_start = self.kaisatsu_date_start_var.get() or None
        search_conditions.kaisatsu_date_end = None

        search_conditions.keiyaku_date_type = self.keiyaku_date_type_var.get()
        search_conditions.keiyaku_date_start = self.keiyaku_date_start_var.get() or None
        search_conditions.keiyaku_date_end = None

        # 工事種別、工事の業種（単一選択）
        # GUIから取得したラベルをコードに変換して保存
        search_conditions.koji_shubetsu = label_to_code("koji_shubetsu", self.koji_shubetsu_var.get(), self.logger)
        search_conditions.koji_gyoushu = label_to_code("koji_gyoushu", self.koji_gyoushu_var.get(), self.logger)

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
