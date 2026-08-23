<<<<<<< HEAD
"""設定ダイアログクラス（CustomTkinter版）"""
=======
# -*- coding: utf-8 -*-

"""設定ダイアログクラス"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

import customtkinter as ctk
import tkinter as tk
import tkinter.font
from tkinter import filedialog, messagebox
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
from ..models.config_model import (
    AppConfig,
    DownloadConditions,
    SearchConditions,
    SavePaths,
    ScheduleConfig,
    LoggingConfig,
)
from ..config.config_manager import ConfigManager
from ..config.config_validator import ConfigValidator
from ..utils.logger import Logger


class SettingsDialog:
    """設定ダイアログクラス"""

    def __init__(
        self,
        parent: tk.Tk,
        config: AppConfig,
        config_manager: ConfigManager,
        logger: Optional[Logger] = None,
    ):
        """初期化"""
        self.parent = parent
        self.config = config
        self.config_manager = config_manager
        self.logger = logger or Logger()
        self.validator = ConfigValidator(self.logger)
        self.result = None  # 保存された設定

        # ダイアログを作成（CTkToplevel）
        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title("⚙️ 設定")
        self.dialog.geometry("900x750")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # 中央に配置
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (900 // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (750 // 2)
        self.dialog.geometry(f"900x750+{x}+{y}")

        self.setup_ui()
        self.load_config_to_ui()

<<<<<<< HEAD
=======
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
                if self.logger:
                    self.logger.warning(f"フォント設定エラー: {str(e)}")

>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33
    def setup_ui(self):
        """UIをセットアップ"""
        # メインフレーム
        main_frame = ctk.CTkFrame(self.dialog, corner_radius=0)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # タブビュー（CustomTkinter）
        self.tabview = ctk.CTkTabview(main_frame, corner_radius=10, segmented_button_fg_color="#3b3b3b", segmented_button_selected_color="#1f6aa5")
        self.tabview._segmented_button.configure(font=ctk.CTkFont(size=14, weight="bold"))
        self.tabview.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # 基本設定タブ
        self.tabview.add("📁 基本設定")
        self.setup_basic_tab(self.tabview.tab("📁 基本設定"))

<<<<<<< HEAD
        # 検索条件タブ
        self.tabview.add("🔍 検索条件")
        self.setup_search_tab(self.tabview.tab("🔍 検索条件"))
=======
        # 検索条件タブ（ppi.jpの検索条件を網羅）
        search_tab = ttk.Frame(notebook, padding="10")
        notebook.add(search_tab, text="検索条件")
        self.setup_search_tab(search_tab)
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

        # 詳細設定タブ
        self.tabview.add("⚙️ 詳細設定")
        self.setup_advanced_tab(self.tabview.tab("⚙️ 詳細設定"))

        # ボタンフレーム
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill=tk.X)

        ctk.CTkButton(
            button_frame, text="🔄 デフォルトに戻す", command=self.on_reset,
            width=160, height=36, corner_radius=4,
            fg_color="#e53e3e", hover_color="#fc8181",
            font=ctk.CTkFont(size=14)
        ).pack(side=tk.LEFT, padx=(0, 10))

        ctk.CTkButton(
            button_frame, text="❌ キャンセル", command=self.on_cancel,
            width=110, height=36, corner_radius=4,
            fg_color="#4a5568", hover_color="#718096",
            font=ctk.CTkFont(size=14)
        ).pack(side=tk.RIGHT, padx=(10, 0))

        ctk.CTkButton(
            button_frame, text="💾 保存", command=self.on_save,
            width=110, height=36, corner_radius=4,
            fg_color="#38a169", hover_color="#48bb78",
            font=ctk.CTkFont(size=14)
        ).pack(side=tk.RIGHT)

    def setup_basic_tab(self, parent):
        """基本設定タブをセットアップ"""
        # スクロール可能なフレーム
        scrollable_frame = ctk.CTkScrollableFrame(parent, corner_radius=5)
        scrollable_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 対象URL
        url_frame = ctk.CTkFrame(scrollable_frame, corner_radius=3, border_width=1, border_color="#555555")
        url_frame.pack(fill=tk.X, pady=(0, 4))

        ctk.CTkLabel(url_frame, text="🌐 対象URL", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor=tk.W, padx=10, pady=(6, 4))

        url_input_frame = ctk.CTkFrame(url_frame, fg_color="transparent")
        url_input_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        self.url_entry = ctk.CTkEntry(url_input_frame, width=400, height=36, corner_radius=4, placeholder_text="URLを入力...")
        self.url_entry.pack(side=tk.LEFT, padx=(0, 10))
        ctk.CTkButton(url_input_frame, text="➕ 追加", command=self.on_add_url, width=80, height=36, corner_radius=4).pack(side=tk.LEFT)

        # URLリスト
        list_frame = ctk.CTkFrame(url_frame, fg_color="transparent")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10)

        self.url_listbox = tk.Listbox(list_frame, height=4, bg="#2b2b2b", fg="white", selectbackground="#3182ce", font=("", 10))
        self.url_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        url_scrollbar = ctk.CTkScrollbar(list_frame, command=self.url_listbox.yview)
        url_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.url_listbox.configure(yscrollcommand=url_scrollbar.set)

        ctk.CTkButton(url_frame, text="🗑️ 削除", command=self.on_remove_url, width=80, height=36, corner_radius=4, fg_color="#e53e3e", hover_color="#fc8181").pack(padx=10, pady=(2, 4))

        # 保存先
        save_frame = ctk.CTkFrame(scrollable_frame, corner_radius=3, border_width=1, border_color="#555555")
        save_frame.pack(fill=tk.X, pady=(0, 4))

        ctk.CTkLabel(save_frame, text="📂 保存先", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor=tk.W, padx=10, pady=(4, 2))

        save_input_frame = ctk.CTkFrame(save_frame, fg_color="transparent")
        save_input_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        self.save_path_var = tk.StringVar()
        ctk.CTkEntry(save_input_frame, textvariable=self.save_path_var, width=500, height=36, corner_radius=4).pack(side=tk.LEFT, padx=(0, 10))
        ctk.CTkButton(save_input_frame, text="📁 参照", command=self.on_browse_path, width=80, height=36, corner_radius=4).pack(side=tk.LEFT)

        # ファイル命名規則
        naming_frame = ctk.CTkFrame(scrollable_frame, corner_radius=3, border_width=1, border_color="#555555")
        naming_frame.pack(fill=tk.X, pady=(0, 4))

        ctk.CTkLabel(naming_frame, text="📝 ファイル命名規則", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor=tk.W, padx=10, pady=(4, 2))

        self.naming_rule_var = tk.StringVar()
        ctk.CTkEntry(naming_frame, textvariable=self.naming_rule_var, width=500, height=36, corner_radius=4).pack(padx=10, fill=tk.X)
        ctk.CTkLabel(
            naming_frame,
            text="使用可能変数: {category}, {title}, {date}, {index}, {filename}, {file_type}",
            font=ctk.CTkFont(size=13),
            text_color="gray",
        ).pack(anchor=tk.W, padx=10, pady=(2, 4))

        # スケジュール設定
        schedule_frame = ctk.CTkFrame(scrollable_frame, corner_radius=3, border_width=1, border_color="#555555")
        schedule_frame.pack(fill=tk.X, pady=(0, 4))

        ctk.CTkLabel(schedule_frame, text="⏰ スケジュール設定", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor=tk.W, padx=10, pady=(4, 2))

        self.schedule_enabled_var = tk.BooleanVar()
        ctk.CTkCheckBox(
            schedule_frame,
            text="スケジュールを有効にする",
            variable=self.schedule_enabled_var,
            font=ctk.CTkFont(size=14),
            corner_radius=4
        ).pack(anchor=tk.W, padx=10, pady=(0, 8))

        schedule_input_frame = ctk.CTkFrame(schedule_frame, fg_color="transparent")
        schedule_input_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        ctk.CTkLabel(schedule_input_frame, text="実行間隔:", font=ctk.CTkFont(size=14)).pack(side=tk.LEFT, padx=(0, 5))
        self.schedule_interval_var = tk.StringVar()
        ctk.CTkComboBox(
            schedule_input_frame,
            variable=self.schedule_interval_var,
            values=["1日", "1週間", "1か月"],
            width=120,
            height=36,
            corner_radius=4,
        ).pack(side=tk.LEFT, padx=(0, 20))

        ctk.CTkLabel(schedule_input_frame, text="実行時間:", font=ctk.CTkFont(size=14)).pack(side=tk.LEFT, padx=(0, 5))
        self.schedule_time_var = tk.StringVar()
        ctk.CTkEntry(schedule_input_frame, textvariable=self.schedule_time_var, width=80, height=36, corner_radius=4, placeholder_text="HH:MM").pack(side=tk.LEFT)

    def setup_search_tab(self, parent):
        """検索条件タブをセットアップ（メイン画面に表示する項目を選択）"""
        # スクロール可能なフレーム
        scrollable_frame = ctk.CTkScrollableFrame(parent, corner_radius=5)
        scrollable_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # タイトル
        title_frame = ctk.CTkFrame(scrollable_frame, corner_radius=5, fg_color="#2b5797")
        title_frame.pack(fill=tk.X, pady=(0, 10))
        ctk.CTkLabel(
            title_frame, 
            text="📋 メイン画面に表示する検索条件項目を選択", 
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="white"
        ).pack(anchor=tk.W, padx=15, pady=10)

        # 説明
        ctk.CTkLabel(
            scrollable_frame,
            text="チェックを入れた項目のみがメイン画面の検索条件エリアに表示されます。",
            font=ctk.CTkFont(size=13),
            text_color="#aaaaaa"
        ).pack(anchor=tk.W, padx=5, pady=(0, 10))

        # 表示項目の選択変数を初期化
        self.visible_items = {}

        # 項目定義（キー, ラベル, デフォルト表示）
        items = [
            ("hachu_kikan", "🏢 発注機関（大分類/中分類/小分類/細分類）", True),
            ("koji_name", "🔨 工事名（文字列検索）", True),
            ("koji_place", "📍 工事場所（地方/県/市/文字列）", True),
            ("contract_type", "📋 入札契約方式", True),
            ("shubetsu_gyoushu", "🔧 工事種別・業種", True),
            ("date_update", "📅 最終更新日", False),
            ("date_koukoku", "📅 公告日", False),
            ("date_kaisatsu", "📅 開札日", False),
            ("date_keiyaku", "📅 契約日", False),
            ("price_yotei", "💰 予定価格（範囲）", False),
            ("price_rakusatsu", "💰 落札価格（範囲）", False),
            ("rakusatsu_name", "👤 落札者名", False),
            ("options", "⚙️ オプション（電子入札/公開中）", True),
            ("display_count", "📊 表示件数", True),
        ]

        # 一括選択ボタン
        button_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        button_frame.pack(fill=tk.X, pady=(0, 10))
        
        ctk.CTkButton(
            button_frame, text="✓ すべて選択", 
            command=lambda: self._select_all_items(True),
            width=120, height=32, corner_radius=4,
            fg_color="#4a9f4a", hover_color="#5cb85c",
            font=ctk.CTkFont(size=13)
        ).pack(side=tk.LEFT, padx=(0, 10))
<<<<<<< HEAD
        
        ctk.CTkButton(
            button_frame, text="✗ すべて解除", 
            command=lambda: self._select_all_items(False),
            width=120, height=32, corner_radius=4,
            fg_color="#666666", hover_color="#888888",
            font=ctk.CTkFont(size=13)
=======

        ttk.Label(koukoku_date_input_frame, text="から").pack(side=tk.LEFT, padx=(0, 5))
        self.koukoku_date_start_var = tk.StringVar()
        ttk.Entry(
            koukoku_date_input_frame, textvariable=self.koukoku_date_start_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(koukoku_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(koukoku_date_input_frame, text="まで").pack(side=tk.LEFT, padx=(0, 5))
        self.koukoku_date_end_var = tk.StringVar()
        ttk.Entry(
            koukoku_date_input_frame, textvariable=self.koukoku_date_end_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(koukoku_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # 開札日
        kaisatsu_date_frame = ttk.LabelFrame(scrollable_frame, text="開札日", padding="5")
        kaisatsu_date_frame.pack(fill=tk.X, pady=(0, 10))

        self.kaisatsu_date_radio_var = tk.StringVar(value="none")
        ttk.Radiobutton(
            kaisatsu_date_frame,
            text="指定なし",
            variable=self.kaisatsu_date_radio_var,
            value="none",
        ).pack(anchor=tk.W)

        kaisatsu_date_input_frame = ttk.Frame(kaisatsu_date_frame)
        kaisatsu_date_input_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Radiobutton(
            kaisatsu_date_input_frame,
            text="期間指定",
            variable=self.kaisatsu_date_radio_var,
            value="range",
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(kaisatsu_date_input_frame, text="から").pack(side=tk.LEFT, padx=(0, 5))
        self.kaisatsu_date_start_var = tk.StringVar()
        ttk.Entry(
            kaisatsu_date_input_frame, textvariable=self.kaisatsu_date_start_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(kaisatsu_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(kaisatsu_date_input_frame, text="まで").pack(side=tk.LEFT, padx=(0, 5))
        self.kaisatsu_date_end_var = tk.StringVar()
        ttk.Entry(
            kaisatsu_date_input_frame, textvariable=self.kaisatsu_date_end_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(kaisatsu_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # 契約日
        keiyaku_date_frame = ttk.LabelFrame(scrollable_frame, text="契約日", padding="5")
        keiyaku_date_frame.pack(fill=tk.X, pady=(0, 10))

        self.keiyaku_date_radio_var = tk.StringVar(value="none")
        ttk.Radiobutton(
            keiyaku_date_frame,
            text="指定なし",
            variable=self.keiyaku_date_radio_var,
            value="none",
        ).pack(anchor=tk.W)

        keiyaku_date_input_frame = ttk.Frame(keiyaku_date_frame)
        keiyaku_date_input_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Radiobutton(
            keiyaku_date_input_frame,
            text="期間指定",
            variable=self.keiyaku_date_radio_var,
            value="range",
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(keiyaku_date_input_frame, text="から").pack(side=tk.LEFT, padx=(0, 5))
        self.keiyaku_date_start_var = tk.StringVar()
        ttk.Entry(
            keiyaku_date_input_frame, textvariable=self.keiyaku_date_start_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(keiyaku_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(keiyaku_date_input_frame, text="まで").pack(side=tk.LEFT, padx=(0, 5))
        self.keiyaku_date_end_var = tk.StringVar()
        ttk.Entry(
            keiyaku_date_input_frame, textvariable=self.keiyaku_date_end_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(keiyaku_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # 工事種別
        koji_shubetsu_frame = ttk.LabelFrame(scrollable_frame, text="工事種別", padding="5")
        koji_shubetsu_frame.pack(fill=tk.X, pady=(0, 10))

        self.koji_shubetsu_var = tk.StringVar()
        koji_shubetsu_combo = ttk.Combobox(
            koji_shubetsu_frame,
            textvariable=self.koji_shubetsu_var,
            values=[
                "",
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
            ],
            state="readonly",
            width=40,
        )
        koji_shubetsu_combo.pack(fill=tk.X)

        # 工事の業種
        koji_gyoushu_frame = ttk.LabelFrame(scrollable_frame, text="工事の業種", padding="5")
        koji_gyoushu_frame.pack(fill=tk.X, pady=(0, 10))

        self.koji_gyoushu_var = tk.StringVar()
        koji_gyoushu_combo = ttk.Combobox(
            koji_gyoushu_frame,
            textvariable=self.koji_gyoushu_var,
            values=[
                "",
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
            ],
            state="readonly",
            width=40,
        )
        koji_gyoushu_combo.pack(fill=tk.X)

        # 予定価格（範囲指定）
        yotei_price_frame = ttk.LabelFrame(scrollable_frame, text="予定価格（範囲指定）", padding="5")
        yotei_price_frame.pack(fill=tk.X, pady=(0, 10))

        price_input_frame = ttk.Frame(yotei_price_frame)
        price_input_frame.pack(fill=tk.X)

        self.yotei_price_min_var = tk.StringVar()
        ttk.Entry(price_input_frame, textvariable=self.yotei_price_min_var, width=15).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Label(price_input_frame, text="（円）～").pack(side=tk.LEFT, padx=(0, 5))
        self.yotei_price_max_var = tk.StringVar()
        ttk.Entry(price_input_frame, textvariable=self.yotei_price_max_var, width=15).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Label(price_input_frame, text="（円）").pack(side=tk.LEFT)

        # 落札価格／契約価格（範囲指定）
        rakusatsu_price_frame = ttk.LabelFrame(
            scrollable_frame, text="落札価格／契約価格（範囲指定）", padding="5"
        )
        rakusatsu_price_frame.pack(fill=tk.X, pady=(0, 10))

        rakusatsu_price_input_frame = ttk.Frame(rakusatsu_price_frame)
        rakusatsu_price_input_frame.pack(fill=tk.X)

        self.rakusatsu_price_min_var = tk.StringVar()
        ttk.Entry(
            rakusatsu_price_input_frame, textvariable=self.rakusatsu_price_min_var, width=15
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(rakusatsu_price_input_frame, text="（円）～").pack(side=tk.LEFT, padx=(0, 5))
        self.rakusatsu_price_max_var = tk.StringVar()
        ttk.Entry(
            rakusatsu_price_input_frame, textvariable=self.rakusatsu_price_max_var, width=15
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(rakusatsu_price_input_frame, text="（円）").pack(side=tk.LEFT)

        # 落札者名／契約者名（文字列検索）
        rakusatsu_name_frame = ttk.LabelFrame(
            scrollable_frame, text="落札者名／契約者名（文字列検索）", padding="5"
        )
        rakusatsu_name_frame.pack(fill=tk.X, pady=(0, 10))

        self.rakusatsu_name_var = tk.StringVar()
        ttk.Entry(rakusatsu_name_frame, textvariable=self.rakusatsu_name_var, width=60).pack(fill=tk.X)
        ttk.Label(
            rakusatsu_name_frame,
            text="※条件の複数指定はできません。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, pady=(5, 0))

        # 電子入札
        denshi_frame = ttk.LabelFrame(scrollable_frame, text="電子入札", padding="5")
        denshi_frame.pack(fill=tk.X, pady=(0, 10))

        self.denshi_var = tk.BooleanVar()
        ttk.Checkbutton(denshi_frame, text="対象案件のみ", variable=self.denshi_var).pack(anchor=tk.W)

        # 公開文書
        koukai_frame = ttk.LabelFrame(scrollable_frame, text="公開文書", padding="5")
        koukai_frame.pack(fill=tk.X, pady=(0, 10))

        self.koukai_var = tk.BooleanVar()
        ttk.Checkbutton(koukai_frame, text="公開中のみ", variable=self.koukai_var).pack(anchor=tk.W)

        # 一覧画面の表示件数
        display_count_frame = ttk.LabelFrame(scrollable_frame, text="一覧画面の表示件数", padding="5")
        display_count_frame.pack(fill=tk.X, pady=(0, 10))

        self.display_count_var = tk.StringVar(value="20")
        ttk.Combobox(
            display_count_frame,
            textvariable=self.display_count_var,
            values=["20", "30", "50", "100"],
            state="readonly",
            width=10,
        ).pack(anchor=tk.W)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def setup_advanced_tab(self, parent: ttk.Frame):
        """詳細設定タブをセットアップ"""
        # ログ設定
        log_frame = ttk.LabelFrame(parent, text="ログ設定", padding="5")
        log_frame.pack(fill=tk.X, pady=(0, 10))

        log_input_frame = ttk.Frame(log_frame)
        log_input_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(log_input_frame, text="ログレベル:").pack(side=tk.LEFT, padx=(0, 10))
        self.log_level_var = tk.StringVar()
        ttk.Combobox(
            log_input_frame,
            textvariable=self.log_level_var,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            state="readonly",
            width=15,
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33
        ).pack(side=tk.LEFT)

        # チェックボックスリスト
        list_frame = ctk.CTkFrame(scrollable_frame, corner_radius=5, border_width=1, border_color="#555555")
        list_frame.pack(fill=tk.X, pady=(0, 10))

        for key, label, default in items:
            var = tk.BooleanVar(value=default)
            self.visible_items[key] = var
            
            item_frame = ctk.CTkFrame(list_frame, fg_color="transparent")
            item_frame.pack(fill=tk.X, padx=10, pady=5)
            
            ctk.CTkCheckBox(
                item_frame, 
                text=label, 
                variable=var, 
                font=ctk.CTkFont(size=14),
                corner_radius=4,
                checkbox_width=24,
                checkbox_height=24
            ).pack(side=tk.LEFT)

        # 注意事項
        note_frame = ctk.CTkFrame(scrollable_frame, corner_radius=5, fg_color="#3a3a3a")
        note_frame.pack(fill=tk.X, pady=(10, 0))
        ctk.CTkLabel(
            note_frame,
            text="💡 ヒント: 必要な項目だけを表示すると画面がスッキリします。\n"
                 "設定を保存後、メイン画面を再起動すると反映されます。",
            font=ctk.CTkFont(size=12),
            text_color="#aaaaaa",
            justify=tk.LEFT
        ).pack(anchor=tk.W, padx=15, pady=10)

    def _select_all_items(self, select: bool):
        """すべての表示項目を選択/解除"""
        for var in self.visible_items.values():
            var.set(select)

    def setup_advanced_tab(self, parent):
        """詳細設定タブをセットアップ"""
        # スクロール可能なフレーム
        scrollable_frame = ctk.CTkScrollableFrame(parent, corner_radius=5)
        scrollable_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ログ設定
        log_frame = ctk.CTkFrame(scrollable_frame, corner_radius=3, border_width=1, border_color="#555555")
        log_frame.pack(fill=tk.X, pady=(0, 4))

        ctk.CTkLabel(log_frame, text="📋 ログ設定", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor=tk.W, padx=10, pady=(4, 2))

        log_input_frame = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_input_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        ctk.CTkLabel(log_input_frame, text="ログレベル:", font=ctk.CTkFont(size=14)).pack(side=tk.LEFT, padx=(0, 10))
        self.log_level_var = tk.StringVar()
        ctk.CTkComboBox(
            log_input_frame,
            variable=self.log_level_var,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            width=150,
            height=36,
            corner_radius=4,
        ).pack(side=tk.LEFT)

        ctk.CTkLabel(log_frame, text="ログファイル:", font=ctk.CTkFont(size=14)).pack(anchor=tk.W, padx=10, pady=(0, 5))

        log_file_frame = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_file_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        self.log_file_var = tk.StringVar()
        ctk.CTkEntry(log_file_frame, textvariable=self.log_file_var, width=400, height=36, corner_radius=4).pack(side=tk.LEFT, padx=(0, 10))
        ctk.CTkButton(log_file_frame, text="📁 参照", command=self.on_browse_log_file, width=80, height=36, corner_radius=4).pack(side=tk.LEFT)

        log_size_frame = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_size_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        ctk.CTkLabel(log_size_frame, text="最大ファイルサイズ:", font=ctk.CTkFont(size=14)).pack(side=tk.LEFT, padx=(0, 5))
        self.log_max_bytes_var = tk.StringVar()
        ctk.CTkEntry(log_size_frame, textvariable=self.log_max_bytes_var, width=80, height=36, corner_radius=4).pack(side=tk.LEFT, padx=(0, 5))
        ctk.CTkLabel(log_size_frame, text="MB", font=ctk.CTkFont(size=14)).pack(side=tk.LEFT, padx=(0, 20))

        ctk.CTkLabel(log_size_frame, text="バックアップファイル数:", font=ctk.CTkFont(size=14)).pack(side=tk.LEFT, padx=(0, 5))
        self.log_backup_count_var = tk.StringVar()
        ctk.CTkEntry(log_size_frame, textvariable=self.log_backup_count_var, width=60, height=36, corner_radius=4).pack(side=tk.LEFT)

    def load_config_to_ui(self, config: Optional[AppConfig] = None):
        """設定をUIに読み込む"""
        if config is None:
            config = self.config

        # 対象URL
        self.url_listbox.delete(0, tk.END)
        for url in config.target_urls:
            self.url_listbox.insert(tk.END, url)

        # 保存先
        self.save_path_var.set(config.save_paths.local)

        # ファイル命名規則
        self.naming_rule_var.set(config.naming_rule)

        # スケジュール設定
        self.schedule_enabled_var.set(config.schedule.enabled)
        interval_map = {"daily": "1日", "weekly": "1週間", "monthly": "1か月"}
        self.schedule_interval_var.set(interval_map.get(config.schedule.interval, "1日"))
        self.schedule_time_var.set(config.schedule.time)

        # ログ設定
        self.log_level_var.set(config.logging.level)
        self.log_file_var.set(config.logging.file)
        self.log_max_bytes_var.set(str(config.logging.max_bytes // 1048576))  # バイトからMBに変換
        self.log_backup_count_var.set(str(config.logging.backup_count))

        # 検索条件の読み込み
        if hasattr(config, "search_conditions") and config.search_conditions:
            sc = config.search_conditions
            self.hachu_daibunrui_var.set(sc.hachu_daibunrui or "")
            self.hachu_chubunrui_var.set(sc.hachu_chubunrui or "")
            self.koji_name_var.set(sc.koji_name or "")
            self.place_list_radio_var.set(sc.place_search_type or "list")
            self.place_chihou_var.set(sc.place_chihou or "")
            self.place_todofuken_var.set(sc.place_todofuken or "")
            self.place_shichouson_var.set(sc.place_shichouson or "")
            self.place_text_var.set(sc.place_text or "")

            # 入札契約方式
            for contract_type, var in self.contract_vars.items():
                var.set(contract_type in (sc.contract_types or []))

            # 最終更新日
            self.update_date_radio_var.set(sc.update_date_type or "none")
            if sc.update_date_days:
                self.update_date_days_var.set(str(sc.update_date_days))

            # 公告日
            self.koukoku_date_radio_var.set(sc.koukoku_date_type or "none")
            if sc.koukoku_date_start:
                self.koukoku_date_start_var.set(sc.koukoku_date_start)
            if sc.koukoku_date_end:
                self.koukoku_date_end_var.set(sc.koukoku_date_end)

            # 開札日
            self.kaisatsu_date_radio_var.set(sc.kaisatsu_date_type or "none")
            if sc.kaisatsu_date_start:
                self.kaisatsu_date_start_var.set(sc.kaisatsu_date_start)
            if sc.kaisatsu_date_end:
                self.kaisatsu_date_end_var.set(sc.kaisatsu_date_end)

            # 契約日
            self.keiyaku_date_radio_var.set(sc.keiyaku_date_type or "none")
            if sc.keiyaku_date_start:
                self.keiyaku_date_start_var.set(sc.keiyaku_date_start)
            if sc.keiyaku_date_end:
                self.keiyaku_date_end_var.set(sc.keiyaku_date_end)

            # 工事種別・業種
            self.koji_shubetsu_var.set(sc.koji_shubetsu or "")
            self.koji_gyoushu_var.set(sc.koji_gyoushu or "")

            # 価格
            if sc.yotei_price_min:
                self.yotei_price_min_var.set(str(sc.yotei_price_min))
            if sc.yotei_price_max:
                self.yotei_price_max_var.set(str(sc.yotei_price_max))
            if sc.rakusatsu_price_min:
                self.rakusatsu_price_min_var.set(str(sc.rakusatsu_price_min))
            if sc.rakusatsu_price_max:
                self.rakusatsu_price_max_var.set(str(sc.rakusatsu_price_max))

            # 落札者名
            self.rakusatsu_name_var.set(sc.rakusatsu_name or "")

            # 電子入札・公開文書
            self.denshi_var.set(sc.denshi or False)
            self.koukai_var.set(sc.koukai or False)

            # 表示件数
            self.display_count_var.set(str(sc.display_count or 20))

    def get_config_from_ui(self) -> AppConfig:
        """UIから設定を取得"""
        # 対象URL
        target_urls = list(self.url_listbox.get(0, tk.END))

        # ダウンロード条件（基本設定のみ、検索条件は別途実装が必要）
        download_conditions = DownloadConditions(
            file_types=self.config.download_conditions.file_types,
            keywords=self.config.download_conditions.keywords,
            date_range=self.config.download_conditions.date_range,
        )

        # 保存先
        save_paths = SavePaths(
            local=self.save_path_var.get(),
        )

        # スケジュール設定
        interval_map = {"1日": "daily", "1週間": "weekly", "1か月": "monthly"}
        schedule = ScheduleConfig(
            enabled=self.schedule_enabled_var.get(),
            interval=interval_map.get(self.schedule_interval_var.get(), "daily"),
            time=self.schedule_time_var.get(),
        )

        # ログ設定
        try:
            max_bytes = int(self.log_max_bytes_var.get()) * 1048576  # MBからバイトに変換
        except ValueError:
            max_bytes = 10485760  # デフォルト10MB

        try:
            backup_count = int(self.log_backup_count_var.get())
        except ValueError:
            backup_count = 5

        logging_config = LoggingConfig(
            level=self.log_level_var.get(),
            file=self.log_file_var.get(),
            max_bytes=max_bytes,
            backup_count=backup_count,
        )

        # 検索条件の取得
        search_conditions = self.get_search_conditions_from_ui()

        return AppConfig(
            target_urls=target_urls,
            download_conditions=download_conditions,
            search_conditions=search_conditions,
            save_paths=save_paths,
            naming_rule=self.naming_rule_var.get(),
            schedule=schedule,
            logging=logging_config,
        )

    def get_search_conditions_from_ui(self) -> SearchConditions:
        """UIから検索条件を取得"""
        # 入札契約方式
        contract_types = [
            contract_type
            for contract_type, var in self.contract_vars.items()
            if var.get()
        ]

        # 最終更新日
        update_date_days = None
        if self.update_date_radio_var.get() == "past":
            try:
                update_date_days = int(self.update_date_days_var.get())
            except ValueError:
                pass

        # 価格（数値変換）
        def safe_int(value: str) -> Optional[int]:
            try:
                return int(value) if value.strip() else None
            except ValueError:
                return None

        return SearchConditions(
            hachu_daibunrui=self.hachu_daibunrui_var.get(),
            hachu_chubunrui=self.hachu_chubunrui_var.get(),
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
            koji_shubetsu=self.koji_shubetsu_var.get(),
            koji_gyoushu=self.koji_gyoushu_var.get(),
            yotei_price_min=safe_int(self.yotei_price_min_var.get()),
            yotei_price_max=safe_int(self.yotei_price_max_var.get()),
            rakusatsu_price_min=safe_int(self.rakusatsu_price_min_var.get()),
            rakusatsu_price_max=safe_int(self.rakusatsu_price_max_var.get()),
            rakusatsu_name=self.rakusatsu_name_var.get(),
            denshi=self.denshi_var.get(),
            koukai=self.koukai_var.get(),
            display_count=int(self.display_count_var.get()) if self.display_count_var.get() else 20,
        )

    def validate_config(self) -> Tuple[bool, List[str]]:
        """設定を検証"""
        config = self.get_config_from_ui()
        return self.validator.validate_config(config)

    def on_save(self):
        """保存ボタンのハンドラ"""
        # 検証
        is_valid, errors = self.validate_config()
        if not is_valid:
            error_message = "設定にエラーがあります:\n" + "\n".join(f"・{error}" for error in errors)
            messagebox.showerror("設定エラー", error_message)
            return

        # 保存
        config = self.get_config_from_ui()
        if self.config_manager.save_config(config):
            self.result = config
            messagebox.showinfo("設定", "設定を保存しました")
            self.dialog.destroy()
        else:
            messagebox.showerror("エラー", "設定の保存に失敗しました")

    def on_cancel(self):
        """キャンセルボタンのハンドラ"""
        self.dialog.destroy()

    def on_reset(self):
        """デフォルトに戻すボタンのハンドラ"""
        if messagebox.askyesno("確認", "すべての設定をデフォルト値に戻しますか？"):
            default_config = self.config_manager.get_default_config()
            self.load_config_to_ui(default_config)

    def on_add_url(self):
        """URL追加ボタンのハンドラ"""
        url = self.url_entry.get().strip()
        if url:
            if url not in self.url_listbox.get(0, tk.END):
                self.url_listbox.insert(tk.END, url)
                self.url_entry.delete(0, tk.END)
            else:
                messagebox.showwarning("警告", "このURLは既に追加されています")
        else:
            messagebox.showwarning("警告", "URLを入力してください")

    def on_remove_url(self):
        """URL削除ボタンのハンドラ"""
        selection = self.url_listbox.curselection()
        if selection:
            self.url_listbox.delete(selection[0])
        else:
            messagebox.showwarning("警告", "削除するURLを選択してください")

    def on_browse_path(self):
        """保存先参照ボタンのハンドラ"""
        path = filedialog.askdirectory(initialdir=self.save_path_var.get())
        if path:
            self.save_path_var.set(path)

    def on_browse_log_file(self):
        """ログファイル参照ボタンのハンドラ"""
        path = filedialog.asksaveasfilename(
            initialdir=".",
            defaultextension=".log",
            filetypes=[("ログファイル", "*.log"), ("すべてのファイル", "*.*")],
        )
        if path:
            self.log_file_var.set(path)

<<<<<<< HEAD
=======
    def on_hachu_multi_select(self):
        """発注機関複数選択ボタンのハンドラ"""
        messagebox.showinfo("情報", "発注機関の複数選択機能は今後実装予定です")

>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33
    def show(self) -> Optional[AppConfig]:
        """ダイアログを表示して結果を返す"""
        self.dialog.wait_window()
        return self.result
