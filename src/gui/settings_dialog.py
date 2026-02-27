# -*- coding: utf-8 -*-

"""設定ダイアログクラス"""

import tkinter as tk
import tkinter.font
from tkinter import ttk, filedialog, messagebox
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
from ..models.config_model import (
    AppConfig,
    DownloadConditions,
    SavePaths,
    ScheduleConfig,
    LoggingConfig,
)
from ..config.config_manager import ConfigManager
from ..config.config_validator import ConfigValidator
from ..utils.logger import Logger
from ..utils.http_client import HTTPClient
from ..app.lookup_service import LookupService
from ..gui.widgets.settings_search_tab import SettingsSearchTab


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
        self._http_client = None
        self._lookup_service = None
        self._search_url = (
            config.target_urls[0]
            if (getattr(config, "target_urls", None) and config.target_urls)
            else "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        )

        # ダイアログを作成
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("設定")
        self.dialog.geometry("800x700")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # 日本語フォントの設定
        self.setup_font()

        # 中央に配置
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (800 // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (700 // 2)
        self.dialog.geometry(f"800x700+{x}+{y}")

        self.setup_ui()
        self.load_config_to_ui()
        # 発注機関・工事場所のオプションを動的ロード（遅延実行）
        self.dialog.after(100, self.search_tab.load_daibunrui_options)

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

    def setup_ui(self):
        """UIをセットアップ"""
        # メインフレーム
        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # タブを作成
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 基本設定タブ
        basic_tab = ttk.Frame(notebook, padding="10")
        notebook.add(basic_tab, text="基本設定")
        self.setup_basic_tab(basic_tab)

        # 検索条件タブ（ppi.jpの検索条件を網羅）
        search_tab = ttk.Frame(notebook, padding="10")
        notebook.add(search_tab, text="検索条件")
        self.search_tab = SettingsSearchTab(
            search_tab, self.dialog, self._get_lookup_service, self.logger,
            on_hachu_multi_select=self.on_hachu_multi_select,
        )

        # 詳細設定タブ
        advanced_tab = ttk.Frame(notebook, padding="10")
        notebook.add(advanced_tab, text="詳細設定")
        self.setup_advanced_tab(advanced_tab)

        # ボタンフレーム
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        ttk.Button(button_frame, text="デフォルトに戻す", command=self.on_reset).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(button_frame, text="キャンセル", command=self.on_cancel).pack(
            side=tk.RIGHT, padx=(5, 0)
        )
        ttk.Button(button_frame, text="保存", command=self.on_save).pack(side=tk.RIGHT)

    def setup_basic_tab(self, parent: ttk.Frame):
        """基本設定タブをセットアップ"""
        # スクロール可能なフレーム
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # 対象URL
        url_frame = ttk.LabelFrame(scrollable_frame, text="対象URL", padding="5")
        url_frame.pack(fill=tk.X, pady=(0, 10))

        url_input_frame = ttk.Frame(url_frame)
        url_input_frame.pack(fill=tk.X, pady=(0, 5))

        self.url_entry = ttk.Entry(url_input_frame)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(url_input_frame, text="追加", command=self.on_add_url).pack(side=tk.LEFT)

        # URLリスト
        list_frame = ttk.Frame(url_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.url_listbox = tk.Listbox(list_frame, height=4)
        self.url_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        url_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.url_listbox.yview)
        url_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.url_listbox.configure(yscrollcommand=url_scrollbar.set)

        ttk.Button(url_frame, text="削除", command=self.on_remove_url).pack(pady=(5, 0))

        # 保存先
        save_frame = ttk.LabelFrame(scrollable_frame, text="保存先", padding="5")
        save_frame.pack(fill=tk.X, pady=(0, 10))

        self.save_path_var = tk.StringVar()
        save_entry = ttk.Entry(save_frame, textvariable=self.save_path_var, width=60)
        save_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(save_frame, text="参照", command=self.on_browse_path).pack(side=tk.LEFT)

        run_folder_frame = ttk.Frame(save_frame)
        run_folder_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(run_folder_frame, text="実行単位のルートフォルダ:").pack(side=tk.LEFT, padx=(0, 5))
        self.run_subfolder_mode_var = tk.StringVar(value="none")
        run_combo = ttk.Combobox(
            run_folder_frame,
            textvariable=self.run_subfolder_mode_var,
            values=("none", "datetime", "search"),
            state="readonly",
            width=12,
        )
        run_combo.pack(side=tk.LEFT)
        ttk.Label(
            run_folder_frame,
            text="(none=作成しない / datetime=日時 / search=検索条件)",
            font=("", 8),
        ).pack(side=tk.LEFT, padx=(5, 0))

        # 発注機関ごとのルートフォルダ
        agency_frame = ttk.LabelFrame(scrollable_frame, text="発注機関フォルダ構造", padding="5")
        agency_frame.pack(fill=tk.X, pady=(0, 10))
        self.enable_agency_root_folders_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            agency_frame,
            text="発注機関ごとにルートフォルダを作成（大分類/中分類/小分類/細分類で枝分かれ）",
            variable=self.enable_agency_root_folders_var,
        ).pack(anchor=tk.W, pady=(0, 3))
        self.include_search_tab_folder_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            agency_frame,
            text="工事/業務でフォルダを分ける",
            variable=self.include_search_tab_folder_var,
        ).pack(anchor=tk.W, pady=(0, 3))
        date_partition_frame = ttk.Frame(agency_frame)
        date_partition_frame.pack(fill=tk.X, pady=(0, 3))
        ttk.Label(date_partition_frame, text="日付フォルダ分割:").pack(side=tk.LEFT, padx=(0, 5))
        self.date_partition_var = tk.StringVar(value="none")
        date_partition_combo = ttk.Combobox(
            date_partition_frame,
            textvariable=self.date_partition_var,
            values=("none", "yyyy", "yyyy_mm", "yyyy_mm_dd"),
            state="readonly",
            width=14,
        )
        date_partition_combo.pack(side=tk.LEFT)
        ttk.Label(date_partition_frame, text="(なし/年/年_月/年_月_日)", font=("", 8)).pack(side=tk.LEFT, padx=(5, 0))

        # ファイル命名規則
        naming_frame = ttk.LabelFrame(scrollable_frame, text="ファイル命名規則", padding="5")
        naming_frame.pack(fill=tk.X, pady=(0, 10))

        self.naming_rule_var = tk.StringVar()
        ttk.Entry(naming_frame, textvariable=self.naming_rule_var, width=60).pack(
            fill=tk.X, pady=(0, 5)
        )
        ttk.Label(
            naming_frame,
            text="使用可能変数: {category}, {title}, {date}, {index}, {filename}, {file_type}, {ext}, {koji_name}, {daibunrui}, {chubunrui}, {shoubunrui}, {saibunrui}",
            font=("", 8),
        ).pack(anchor=tk.W)

        # スケジュール設定
        schedule_frame = ttk.LabelFrame(scrollable_frame, text="スケジュール設定", padding="5")
        schedule_frame.pack(fill=tk.X, pady=(0, 10))

        self.schedule_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            schedule_frame,
            text="スケジュールを有効にする",
            variable=self.schedule_enabled_var,
        ).pack(anchor=tk.W, pady=(0, 5))

        schedule_input_frame = ttk.Frame(schedule_frame)
        schedule_input_frame.pack(fill=tk.X)

        ttk.Label(schedule_input_frame, text="実行間隔:").pack(side=tk.LEFT, padx=(0, 5))
        self.schedule_interval_var = tk.StringVar()
        interval_combo = ttk.Combobox(
            schedule_input_frame,
            textvariable=self.schedule_interval_var,
            values=["1日", "1週間", "1か月"],
            state="readonly",
            width=10,
        )
        interval_combo.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(schedule_input_frame, text="実行時間:").pack(side=tk.LEFT, padx=(0, 5))
        self.schedule_time_var = tk.StringVar()
        ttk.Entry(schedule_input_frame, textvariable=self.schedule_time_var, width=8).pack(
            side=tk.LEFT
        )
        ttk.Label(schedule_input_frame, text="(HH:MM形式)").pack(side=tk.LEFT, padx=(5, 0))

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
        ).pack(side=tk.LEFT)

        ttk.Label(log_frame, text="ログファイル:").pack(anchor=tk.W, pady=(0, 5))
        log_file_frame = ttk.Frame(log_frame)
        log_file_frame.pack(fill=tk.X, pady=(0, 10))

        self.log_file_var = tk.StringVar()
        ttk.Entry(log_file_frame, textvariable=self.log_file_var, width=50).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5)
        )
        ttk.Button(log_file_frame, text="参照", command=self.on_browse_log_file).pack(side=tk.LEFT)

        log_size_frame = ttk.Frame(log_frame)
        log_size_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(log_size_frame, text="最大ファイルサイズ:").pack(side=tk.LEFT, padx=(0, 5))
        self.log_max_bytes_var = tk.StringVar()
        ttk.Entry(log_size_frame, textvariable=self.log_max_bytes_var, width=10).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Label(log_size_frame, text="MB").pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(log_size_frame, text="バックアップファイル数:").pack(side=tk.LEFT, padx=(0, 5))
        self.log_backup_count_var = tk.StringVar()
        ttk.Entry(log_size_frame, textvariable=self.log_backup_count_var, width=5).pack(side=tk.LEFT)

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
        if hasattr(self, "run_subfolder_mode_var"):
            self.run_subfolder_mode_var.set(getattr(config.save_paths, "run_subfolder_mode", "none"))
        if hasattr(self, "enable_agency_root_folders_var"):
            self.enable_agency_root_folders_var.set(getattr(config.save_paths, "enable_agency_root_folders", True))
        if hasattr(self, "include_search_tab_folder_var"):
            self.include_search_tab_folder_var.set(getattr(config.save_paths, "include_search_tab_folder", True))
        if hasattr(self, "date_partition_var"):
            self.date_partition_var.set(getattr(config.save_paths, "date_partition", "none"))

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
            self.search_tab.load_from_config(config.search_conditions)

    def _get_lookup_service(self) -> LookupService:
        if self._lookup_service is None:
            if self._http_client is None:
                self._http_client = HTTPClient(self.logger)
            self._lookup_service = LookupService(self._http_client, self.logger, self._search_url)
        return self._lookup_service

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
        run_mode = getattr(self, "run_subfolder_mode_var", None)
        run_mode_val = run_mode.get() if run_mode else getattr(self.config.save_paths, "run_subfolder_mode", "none")
        sp = self.config.save_paths
        save_paths = SavePaths(
            local=self.save_path_var.get(),
            use_subfolders=getattr(sp, "use_subfolders", True),
            run_subfolder_mode=run_mode_val,
            enable_hash_check=getattr(sp, "enable_hash_check", False),
            keep_part_on_cancel=getattr(sp, "keep_part_on_cancel", True),
            enable_agency_root_folders=self.enable_agency_root_folders_var.get() if getattr(self, "enable_agency_root_folders_var", None) else getattr(sp, "enable_agency_root_folders", True),
            agency_root_label=getattr(sp, "agency_root_label", "発注機関"),
            agency_folder_levels=getattr(sp, "agency_folder_levels", ["daibunrui", "chubunrui", "shoubunrui", "saibunrui"]),
            include_search_tab_folder=self.include_search_tab_folder_var.get() if getattr(self, "include_search_tab_folder_var", None) else getattr(sp, "include_search_tab_folder", True),
            search_tab_labels=getattr(sp, "search_tab_labels", {"works": "工事_入札公告等", "services": "業務_入札公告等"}),
            date_partition=self.date_partition_var.get() if getattr(self, "date_partition_var", None) else getattr(sp, "date_partition", "none"),
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
        existing_sc = getattr(self.config, "search_conditions", None)
        search_conditions = self.search_tab.write_to_search_conditions(existing_sc)

        return AppConfig(
            target_urls=target_urls,
            download_conditions=download_conditions,
            search_conditions=search_conditions,
            save_paths=save_paths,
            naming_rule=self.naming_rule_var.get(),
            schedule=schedule,
            logging=logging_config,
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

    def on_hachu_multi_select(self):
        """発注機関複数選択ボタンのハンドラ"""
        messagebox.showinfo("情報", "発注機関の複数選択機能は今後実装予定です")

    def show(self) -> Optional[AppConfig]:
        """ダイアログを表示して結果を返す"""
        self.dialog.wait_window()
        return self.result

