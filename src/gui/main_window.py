# -*- coding: utf-8 -*-

"""メインウィンドウクラス"""

import tkinter as tk
import tkinter.font
from tkinter import ttk, filedialog, messagebox, scrolledtext
from typing import Optional, Callable
from threading import Thread, Event
from ..models.config_model import AppConfig, SearchConditions
from ..utils.logger import Logger
from ..gui.event_handler import EventHandler
from ..utils.http_client import HTTPClient
from ..config.config_manager import ConfigManager
from ..app.lookup_service import LookupService
from ..gui.widgets.search_conditions_frame import SearchConditionsFrame


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

    def setup_ui(self):
        """UIをセットアップ"""
        self.root.title("ippi-down - ppi.jp入札情報ダウンローダー")
        self.root.geometry("1200x800")

        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # ツールバー
        toolbar = ttk.Frame(main_frame)
        toolbar.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

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

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # SearchConditionsFrame を配置
        self.search_frame = SearchConditionsFrame(
            scrollable_frame,
            self.config.search_conditions,
            self._get_lookup_service,
            self.logger,
        )

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
        main_frame.rowconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)

    # ------------------------------------------------------------------
    # LookupService（遅延初期化）
    # ------------------------------------------------------------------

    def _get_lookup_service(self) -> LookupService:
        """LookupService を取得（遅延初期化）"""
        if self._lookup_service is None:
            if self._http_client is None:
                self._http_client = HTTPClient(
                    self.logger, network_config=getattr(self.config, "network", None)
                )
            self._lookup_service = LookupService(self._http_client, self.logger, self._search_url)
        return self._lookup_service

    # ------------------------------------------------------------------
    # Config ↔ UI
    # ------------------------------------------------------------------

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

    def set_download_callback(self, callback: Callable):
        """ダウンロードコールバックを設定"""
        self.download_callback = callback

    def on_download_start(self):
        """ダウンロード開始ボタンのハンドラ"""
        if not self.download_callback:
            messagebox.showwarning("警告", "ダウンロード機能が設定されていません")
            return

        self.cancel_flag.clear()
        self.btn_download.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress_bar["value"] = 0
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

    # ------------------------------------------------------------------
    # メッセージ / クリア
    # ------------------------------------------------------------------

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
