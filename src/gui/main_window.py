"""メインウィンドウクラス"""

import tkinter as tk
import tkinter.font
from tkinter import ttk, filedialog, messagebox, scrolledtext
from typing import Optional, Callable
from threading import Thread
import platform
from ..models.config_model import AppConfig
from ..utils.logger import Logger
from ..utils.http_client import HTTPClient
from ..core.scraper import Scraper
from ..config.config_manager import ConfigManager


class MainWindow:
    """メインウィンドウクラス"""

    def __init__(self, root: tk.Tk, config: AppConfig, config_manager: ConfigManager, logger: Optional[Logger] = None):
        """初期化"""
        self.root = root
        self.config = config
        self.config_manager = config_manager
        self.logger = logger or Logger()
        self.download_callback: Optional[Callable] = None

        # 階層ドロップダウン用のHTTPClientとScraper（遅延初期化）
        self._http_client = None
        self._scraper = None
        # tabパラメータなしのSearch.aspxを使用
        self._search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"

        # 日本語フォントの設定
        self.setup_font()
        self.setup_ui()
        self.setup_bindings()
        
        # 初期化時に大分類のオプションを取得
        self.load_hachu_daibunrui_options()

    def setup_font(self):
        """日本語フォントを設定"""
        if platform.system() == "Windows":
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

        self.btn_clear = ttk.Button(toolbar, text="クリア", command=self.on_clear_log)
        self.btn_clear.pack(side=tk.LEFT)

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
        self.place_chihou_var = tk.StringVar(value=search_conditions.place_chihou)
        ttk.Combobox(
            place_frame,
            textvariable=self.place_chihou_var,
            values=place_chihou_options,
            state="readonly",
            width=30,
        ).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(place_frame, text="都道府県:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.place_todofuken_var = tk.StringVar(value=search_conditions.place_todofuken)
        ttk.Combobox(
            place_frame,
            textvariable=self.place_todofuken_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        ).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(place_frame, text="市町村:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.place_shichouson_var = tk.StringVar(value=search_conditions.place_shichouson)
        ttk.Combobox(
            place_frame,
            textvariable=self.place_shichouson_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        ).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

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

        koji_shubetsu_options = [
            "",
            "一般土木工事", "アスファルト舗装工事", "鋼橋上部工事", "造園工事", "建築工事",
            "木造建築工事", "電気設備工事", "暖冷房衛生設備工事", "セメント・コンクリート舗装工事",
            "プレストレスト・コンクリート工事", "法面処理工事", "塗装工事", "維持修繕工事",
            "浚渫工事", "グラウト工事", "杭打工事", "さく井工事", "プレハブ建築工事",
            "機械設備工事", "通信設備工事", "受変電設備工事", "港湾土木工事", "農林土木工事",
            "農林建築工事", "橋梁補修工事", "その他"
        ]
        koji_shubetsu_input_frame = ttk.Frame(koji_shubetsu_frame)
        koji_shubetsu_input_frame.pack(fill=tk.X)
        self.koji_shubetsu_var = tk.StringVar(value=search_conditions.koji_shubetsu)
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

        koji_gyoushu_options = [
            "",
            "土木一式工事", "建築一式工事", "大工工事", "左官工事", "とび・土工・コンクリート工事",
            "石工事", "屋根工事", "電気工事", "管工事", "タイル・れんが・ブロック工事",
            "鋼構造物工事", "鉄筋工事", "舗装工事", "浚渫工事", "板金工事",
            "ガラス工事", "塗装工事", "防水工事", "内装仕上工事", "機械器具設置工事",
            "熱絶縁工事", "電気通信工事", "造園工事", "さく井工事", "建具工事",
            "水道施設工事", "消防施設工事", "清掃施設工事", "解体工事", "その他"
        ]
        koji_gyoushu_input_frame = ttk.Frame(koji_gyoushu_frame)
        koji_gyoushu_input_frame.pack(fill=tk.X)
        self.koji_gyoushu_var = tk.StringVar(value=search_conditions.koji_gyoushu)
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

    def on_hachu_daibunrui_changed(self, event=None):
        """大分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        if not daibunrui_value:
            # 大分類がクリアされた場合は、中分類以下もクリア
            self.hachu_chubunrui_combo['values'] = []
            self.hachu_chubunrui_var.set("")
            self.hachu_shoubunrui_combo['values'] = []
            self.hachu_shoubunrui_var.set("")
            self.hachu_saibunrui_combo['values'] = []
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
        self.hachu_shoubunrui_combo['values'] = []
        self.hachu_saibunrui_combo['values'] = []
        
        Thread(target=load_in_thread, daemon=True).start()

    def _update_hachu_chubunrui_options(self, options: list):
        """中分類のオプションを更新"""
        self.hachu_chubunrui_combo['values'] = [""] + options

    def on_hachu_chubunrui_changed(self, event=None):
        """中分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        chubunrui_value = self.hachu_chubunrui_var.get()
        if not chubunrui_value or not daibunrui_value:
            # 小分類以下をクリア
            self.hachu_shoubunrui_combo['values'] = []
            self.hachu_shoubunrui_var.set("")
            self.hachu_saibunrui_combo['values'] = []
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
        
        # 細分類をクリア
        self.hachu_saibunrui_var.set("")
        self.hachu_saibunrui_combo['values'] = []
        
        Thread(target=load_in_thread, daemon=True).start()

    def _update_hachu_shoubunrui_options(self, options: list):
        """小分類のオプションを更新"""
        self.hachu_shoubunrui_combo['values'] = [""] + options

    def on_hachu_shoubunrui_changed(self, event=None):
        """小分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        chubunrui_value = self.hachu_chubunrui_var.get()
        shoubunrui_value = self.hachu_shoubunrui_var.get()
        if not shoubunrui_value or not chubunrui_value or not daibunrui_value:
            # 細分類をクリア
            self.hachu_saibunrui_combo['values'] = []
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
        self.hachu_saibunrui_combo['values'] = [""] + options

    def set_download_callback(self, callback: Callable):
        """ダウンロードコールバックを設定"""
        self.download_callback = callback

    def on_download_start(self):
        """ダウンロード開始ボタンのハンドラ"""
        if not self.download_callback:
            messagebox.showwarning("警告", "ダウンロード機能が設定されていません")
            return

        # UIを無効化
        self.btn_download.config(state="disabled")
        self.progress_bar["value"] = 0
        self.progress_var.set("ダウンロードを開始しています...")

        # 別スレッドでダウンロードを実行
        thread = Thread(target=self._download_thread)
        thread.daemon = True
        thread.start()

    def _download_thread(self):
        """ダウンロードスレッド"""
        try:
            if self.download_callback:
                self.download_callback(self)
        except Exception as e:
            self.logger.error(f"ダウンロードエラー: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("エラー", f"ダウンロードエラー: {str(e)}"))
        finally:
            self.root.after(0, lambda: self.btn_download.config(state="normal"))

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

        # 工事場所
        self.place_chihou_var.set(search_conditions.place_chihou)
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
