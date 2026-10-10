# -*- coding: utf-8 -*-

"""メインウィンドウクラス"""

import tkinter as tk
import tkinter.font
import os
import json
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tkinter import ttk, messagebox, scrolledtext
from typing import Any, Optional, Callable
from copy import deepcopy
from threading import Event, Lock, Thread, get_ident
from ..models.config_model import AppConfig, SearchConditions
from ..models.search_target import SearchTarget
from ..models.agency import AgencyOption, AgencyPath
from ..models.download_diagnostics import RedownloadPolicy
from ..models.download_result import RunOutcome
from ..utils.logger import Logger
from ..gui.event_handler import EventHandler
from ..gui.option_load_coordinator import OptionLoadCoordinator
from ..gui.project_documents_dialog import (
    ProjectDocumentsDialog,
    ProjectView,
    format_search_summary,
    normalise_project,
    normalise_projects,
    payload_value,
)
from ..gui.schedule_management import (
    ScheduleServiceAdapter,
    ScheduleTreeRow,
    ScheduleView,
    aggregate_schedule_counts,
    format_storage_preview,
    history_display_name,
    reconcile_schedule_tree,
    schedule_identifier,
    trigger_kind_display,
)
from ..gui.schedule_editor_dialog import format_schedule_notification_policy
from ..gui.pdf_conversion_history_dialog import PdfConversionHistoryDialog
from .window_layout import WrapButtonBar, fit_to_screen
from ..storage.layout import RunKind
from ..app.service import format_search_conditions
from ..gui.search_conditions_form import (
    DynamicOptionRequestToken,
    HACHU_DAIBUNRUI_FALLBACK_OPTIONS,
    KOJI_GYOUSHU_OPTIONS,
    KOJI_SHUBETSU_OPTIONS,
    PLACE_CHIHOU_OPTIONS,
    SearchConditionOptionModel,
    bind_search_comboboxes_to_canvas,
    validate_search_condition_structure,
)
from ..utils.http_client import HTTPClient
from ..core.scraper import Scraper
from ..core.search_profiles import get_search_profile, search_profiles
from ..config.config_manager import ConfigManager
from ..utils.path_utils import get_logs_path


def _schedule_value(value: object, *names: str, default: object = None) -> object:
    """スケジュールAPIのdataclass/dictを後方互換で読み取る。"""
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        item = getattr(value, name, None)
        if item is not None:
            return item
    return default


def _format_schedule_datetime(value: object) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, (datetime, date)):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if isinstance(parsed, datetime) and parsed.tzinfo:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y/%m/%d %H:%M")


def _format_schedule_result(value: object) -> str:
    """内部結果コードをGUI向けの日本語へ変換する。"""
    raw = getattr(value, "value", value)
    key = str(raw or "").strip().lower()
    return {
        "success": "成功",
        "no_match": "該当なし",
        "partial": "一部失敗",
        "partial_failure": "一部失敗",
        "failed": "失敗",
        "failure": "失敗",
        "error": "失敗",
        "cancelled": "キャンセル",
        "busy": "他の処理を実行中",
        "queue_timeout": "キュー待機時間超過",
        "run_timeout": "実行時間超過",
        "config_invalid": "設定エラー",
        "unknown": "未実行",
    }.get(key, str(raw) if raw not in {None, ""} else "-")


def _schedule_status_presentation(status: object) -> tuple[str, str]:
    """登録状態を文字と色の二重表現へ変換する。"""
    if status is None:
        return "無効", "#666666"
    state_value = _schedule_value(status, "state", default="")
    state = str(getattr(state_value, "value", state_value)).lower()
    registered = bool(_schedule_value(status, "registered", default=False))
    running = bool(_schedule_value(status, "running", default=False))
    mismatch = bool(_schedule_value(status, "definition_mismatch", default=False))
    repair = _schedule_value(status, "repair_reason")
    last_result_value = _schedule_value(status, "last_result", default="")
    last_result = str(getattr(last_result_value, "value", last_result_value)).lower()
    if bool(
        _schedule_value(status, "queue_waiting", "queued", default=False)
    ) or state in {"queued", "queue_waiting", "waiting", "順番待ち"}:
        return "順番待ち", "#8250df"
    if bool(_schedule_value(status, "retry_waiting", default=False)) or state in {
        "retry_waiting",
        "retry_wait",
        "再試行待機中",
    }:
        return "再試行待機中", "#9a6700"
    if running or state in {"running", "実行中"}:
        return "実行中", "#0969da"
    if repair or state in {"repair_required", "needs_repair", "要修復"}:
        return "要修復", "#cf222e"
    if mismatch or state in {"update_required", "needs_update", "要更新"}:
        return "要更新", "#9a6700"
    if state in {"last_failed", "failed", "前回失敗"} or last_result in {
        "failed",
        "failure",
        "partial_failure",
        "error",
        "queue_timeout",
        "run_timeout",
        "config_invalid",
        "失敗",
        "一部失敗",
    }:
        return "前回失敗", "#cf222e"
    if registered or state in {"registered", "ready", "登録済み"}:
        return "登録済み", "#1a7f37"
    return "無効", "#666666"


@dataclass
class _AgencyOptionFlight:
    """同じ発注機関枝への並行要求を1通信へまとめる。"""

    done: Event
    cancel_check: Optional[Callable[[], bool]] = None
    options: tuple[AgencyOption, ...] = ()
    error: Optional[Exception] = None


class MainWindow:
    """メインウィンドウクラス"""

    _GUI_LOG_MAX_LINES = 5_000
    _GUI_LOG_MAX_BYTES = 2 * 1024 * 1024
    _GUI_LOG_TRIM_LINES = 4_500
    _GUI_LOG_TRIM_BYTES = 1_800 * 1024

    _AGENCY_FIELDS = (
        "hachu_daibunrui",
        "hachu_chubunrui",
        "hachu_shoubunrui",
        "hachu_saibunrui",
    )
    _AGENCY_FIELD_LABELS = {
        "hachu_daibunrui": "大分類",
        "hachu_chubunrui": "中分類",
        "hachu_shoubunrui": "小分類",
        "hachu_saibunrui": "細分類",
    }
    _DYNAMIC_OPTION_FIELDS = (
        "place_chihou",
        "place_todofuken",
        "place_shichouson",
        "koji_shubetsu",
        "koji_gyoushu",
        "gyomu_kubun",
    )
    _DYNAMIC_OPTION_PARENTS = {
        "place_chihou": (),
        "place_todofuken": ("place_chihou",),
        "place_shichouson": ("place_chihou", "place_todofuken"),
        "koji_shubetsu": (),
        "koji_gyoushu": (),
        "gyomu_kubun": (),
    }
    _DYNAMIC_OPTION_LABELS = {
        "place_chihou": "地方",
        "place_todofuken": "都道府県",
        "place_shichouson": "市区町村",
        "koji_shubetsu": "工事種別",
        "koji_gyoushu": "工事の業種",
        "gyomu_kubun": "業務区分",
    }

    def __init__(
        self,
        root: tk.Tk,
        config: AppConfig,
        config_manager: ConfigManager,
        logger: Optional[Logger] = None,
        schedule_service: Optional[object] = None,
        reclassification_service: Optional[object] = None,
    ):
        """初期化"""
        self.root = root
        self.config = config
        self.config_manager = config_manager
        self.logger = logger or Logger()
        self.download_callback: Optional[Callable] = None
        self.schedule_change_callback: Optional[Callable] = None
        self.close_callback: Optional[Callable] = None
        self.schedule_service = schedule_service
        self.reclassification_service = reclassification_service
        self._multiple_schedule_mode = bool(
            schedule_service is not None
            and ScheduleServiceAdapter(schedule_service).supports_multiple
        )
        self._schedule_status_query_running = False
        self._schedule_poll_after_id = None
        self._last_schedule_status = None
        self._last_schedule_record = None
        self._last_schedule_records: list[object] = []
        self._last_schedule_history_id: Optional[str] = None
        self._schedule_views: list[ScheduleView] = []
        self._schedule_views_by_id: dict[str, ScheduleView] = {}
        self._selected_schedule_id: Optional[str] = None
        self._schedule_refresh_pending = False
        self._schedule_refresh_generation = 0
        self._schedule_detail_generation = 0
        self._schedule_action_running = False
        self._schedule_queue_blocks_manual = False
        self._installation_relocation_pending = False
        self._installation_relocation_running = False
        self._ui_thread_id = get_ident()
        if config.search_conditions.hachu_multi:
            self.logger.warning(
                "複数発注機関の旧設定は現在サポートされないため使用しません"
            )

        # ダウンロードキャンセル用のフラグ
        self.cancel_flag = Event()
        self.download_thread: Optional[Thread] = None
        self._last_run_outcome: Optional[RunOutcome] = None
        self._pending_option_loads = 0
        self._closing = False
        self._search_summary = None
        self._active_search_generation: Optional[int] = None
        self._project_document_projects: tuple[ProjectView, ...] = ()
        self._project_document_projects_by_id: dict[str, ProjectView] = {}
        self._project_documents_dialog: Optional[ProjectDocumentsDialog] = None
        self._schedule_history_dialog: Optional[tk.Toplevel] = None
        self._schedule_log_dialog: Optional[tk.Toplevel] = None
        self._pdf_conversion_history_dialog: Optional[tk.Toplevel] = None
        self._schedule_log_schedule_id: Optional[str] = None
        self._schedule_history_load_running = False
        self._schedule_log_load_running = False
        self._gui_log_entries: deque[tuple[int, int]] = deque()
        self._gui_log_lines = 0
        self._gui_log_bytes = 0
        self._mousewheel_bind_id: Optional[str] = None
        self._search_canvas_hovered = False
        self._agency_reload_running = False
        self._agency_reload_pending = False
        self._agency_catalog_refresh_error = ""
        self._option_load_coordinator = OptionLoadCoordinator()
        active_target = config.search_conditions.target
        self._active_search_target = active_target
        self._target_drafts = {
            target.value: SearchConditions.for_target(target) for target in SearchTarget
        }
        self._target_drafts[active_target.value] = deepcopy(config.search_conditions)

        # 発注機関候補はプロセス内だけで共有する。HTMLやCookieは保持しない。
        self._agency_option_cache: dict[
            tuple[int, tuple[str, ...]], tuple[AgencyOption, ...]
        ] = {}
        self._agency_option_flights: dict[
            tuple[int, tuple[str, ...]], _AgencyOptionFlight
        ] = {}
        self._agency_option_guard = Lock()
        self._agency_cache_epoch = 0
        self._agency_catalog_epoch = -1
        self._agency_generations = {
            field: 0
            for field in (
                "hachu_daibunrui",
                "hachu_chubunrui",
                "hachu_shoubunrui",
                "hachu_saibunrui",
            )
        }
        self._agency_loading_fields: set[str] = set()
        self._agency_invalid_fields: set[str] = set()
        self._agency_cancel_events: dict[str, Event] = {}
        self._agency_request_parents: dict[str, tuple[str, ...]] = {}
        self._initial_search_option_cache: dict[str, tuple[object, ...]] = {}
        self._search_option_model = SearchConditionOptionModel(
            config.search_conditions,
            {
                "place_chihou": PLACE_CHIHOU_OPTIONS,
                "koji_shubetsu": KOJI_SHUBETSU_OPTIONS,
                "koji_gyoushu": KOJI_GYOUSHU_OPTIONS,
                "gyomu_kubun": (),
            },
        )
        self._dynamic_option_generations = {
            field: 0 for field in self._DYNAMIC_OPTION_FIELDS
        }
        self._dynamic_user_revisions = {
            field: 0 for field in self._DYNAMIC_OPTION_FIELDS
        }
        self._dynamic_invalid_fields: set[str] = set()

        # 階層ドロップダウン用のHTTPClientとScraper（遅延初期化）
        self._http_client = None
        self._scraper = None
        self._scraper_request_lock = Lock()
        self._search_url = get_search_profile(active_target).search_url

        # 日本語フォントの設定
        self.setup_font()
        self.setup_ui()
        self.setup_bindings()

        # イベントハンドラーを初期化（スレッドセーフなUI更新用）
        self.event_handler = EventHandler(root, self)
        self.event_handler.start_polling()
        self._schedule_poll_after_id = self.root.after(300, self._poll_schedule_status)

        # 初期化時に大分類のオプションを取得（遅延実行：root.afterでGUI表示後に実行）
        # import時にHTTPリクエストが送られないようにするため
        self.root.after(100, self.load_hachu_daibunrui_options)
        self.root.after(150, self.load_initial_search_options)

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
        self.root.title("ippi-down - i-ppi.jp入札情報ダウンローダー")
        fit_to_screen(self.root, 1200, 800, minimum_width=620, minimum_height=440)

        # メインフレーム
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # ツールバー
        toolbar = WrapButtonBar(main_frame)
        toolbar.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        self.btn_settings = ttk.Button(
            toolbar, text="設定", command=self.on_settings_open
        )
        toolbar.add(self.btn_settings)

        self.btn_download = ttk.Button(
            toolbar, text="ダウンロード開始", command=self.on_download_start
        )
        toolbar.add(self.btn_download)

        self.btn_cancel = ttk.Button(
            toolbar,
            text="キャンセル",
            command=self.on_download_cancel,
            state="disabled",
        )
        toolbar.add(self.btn_cancel)

        self.redownload_existing_var = tk.BooleanVar(value=False)
        self.chk_redownload_existing = ttk.Checkbutton(
            toolbar,
            text="保存済みファイルも今回だけ再取得",
            variable=self.redownload_existing_var,
        )
        toolbar.add(self.chk_redownload_existing)

        self.btn_clear = ttk.Button(toolbar, text="クリア", command=self.on_clear_log)
        toolbar.add(self.btn_clear)
        ttk.Button(
            toolbar,
            text="PDF変換履歴",
            command=self.show_pdf_conversion_history,
        )
        toolbar.add(toolbar.winfo_children()[-1])
        self.manual_storage_var = tk.StringVar()
        ttk.Label(
            toolbar,
            textvariable=self.manual_storage_var,
            foreground="#555555",
        )
        toolbar.add(toolbar.winfo_children()[-1])
        self._refresh_manual_storage_preview()

        # GUIを閉じても継続するWindowsタスクの状態を常時確認できる欄。
        schedule_frame = ttk.LabelFrame(
            main_frame, text="定期実行（Windowsタスク）", padding="6"
        )
        schedule_frame.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky=(tk.W, tk.E),
            pady=(0, 10),
        )
        schedule_frame.columnconfigure(1, weight=1)
        schedule_frame.rowconfigure(1, weight=1)
        self.schedule_aggregate_var = tk.StringVar(value="保存条件: 0件 / 有効: 0件")
        ttk.Label(
            schedule_frame,
            textvariable=self.schedule_aggregate_var,
        ).grid(row=0, column=0, sticky=tk.W)
        self.schedule_status_var = tk.StringVar(value="無効")
        self.schedule_status_label = ttk.Label(
            schedule_frame,
            textvariable=self.schedule_status_var,
            foreground="#666666",
        )
        self.schedule_status_label.grid(row=0, column=1, sticky=tk.W, padx=(14, 0))

        self.schedule_timing_var = tk.StringVar(value="次回: - / 前回: - / 結果: -")
        ttk.Label(schedule_frame, textvariable=self.schedule_timing_var).grid(
            row=0, column=2, sticky=tk.W, padx=(14, 0)
        )

        # Keep task actions separate from the status text.  This gives the
        # buttons a full row and lets the bar wrap on a narrow display.
        action_frame = WrapButtonBar(schedule_frame)
        action_frame.grid(
            row=1, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=(5, 0)
        )
        ttk.Button(
            action_frame,
            text="定期実行設定",
            command=self.on_schedule_settings_open,
        )
        action_frame.add(action_frame.winfo_children()[-1])
        self.btn_schedule_run_now = ttk.Button(
            action_frame,
            text="今すぐ実行",
            command=self.on_schedule_run_now,
            state="disabled",
        )
        action_frame.add(self.btn_schedule_run_now)
        ttk.Button(
            action_frame,
            text="実行履歴",
            command=self.show_schedule_history,
        )
        action_frame.add(action_frame.winfo_children()[-1])
        ttk.Button(
            action_frame,
            text="ログを開く",
            command=self.open_schedule_log,
        )
        action_frame.add(action_frame.winfo_children()[-1])

        columns = (
            "enabled",
            "state",
            "name",
            "cadence",
            "next",
            "result",
            "counts",
        )
        self.schedule_tree = ttk.Treeview(
            schedule_frame,
            columns=columns,
            show="headings",
            height=4,
            selectmode="browse",
        )
        headings = {
            "enabled": "有効",
            "state": "状態",
            "name": "設定名",
            "cadence": "予定",
            "next": "次回",
            "result": "前回結果",
            "counts": "新規・保存済み・失敗",
        }
        widths = {
            "enabled": 45,
            "state": 75,
            "name": 170,
            "cadence": 115,
            "next": 125,
            "result": 85,
            "counts": 130,
        }
        for column in columns:
            self.schedule_tree.heading(column, text=headings[column])
            self.schedule_tree.column(
                column,
                width=widths[column],
                stretch=column == "name",
                anchor=tk.CENTER if column != "name" else tk.W,
            )
        self.schedule_tree.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky=(tk.W, tk.E),
            pady=(6, 0),
        )
        schedule_tree_scroll = ttk.Scrollbar(
            schedule_frame,
            orient="vertical",
            command=self.schedule_tree.yview,
        )
        schedule_tree_scroll.grid(
            row=2,
            column=4,
            sticky=(tk.N, tk.S),
            pady=(6, 0),
        )
        self.schedule_tree.configure(yscrollcommand=schedule_tree_scroll.set)
        self.schedule_tree.bind("<<TreeviewSelect>>", self._on_schedule_tree_selected)

        self.schedule_counts_var = tk.StringVar(
            value="新規保存: - / 保存済み確認: - / 失敗: -"
        )
        ttk.Label(schedule_frame, textvariable=self.schedule_counts_var).grid(
            row=3, column=0, columnspan=3, sticky=tk.W, pady=(3, 0)
        )
        self.schedule_runtime_var = tk.StringVar(
            value=(
                "GUI終了後の実行: Windowsタスク登録後に利用可"
                "（Windowsへのログオンが必要） / "
                "スリープ解除: - / 完了通知: -"
            )
        )
        ttk.Label(
            schedule_frame,
            textvariable=self.schedule_runtime_var,
            foreground="#555555",
        ).grid(row=4, column=0, columnspan=4, sticky=tk.W, pady=(3, 0))
        self.schedule_warning_var = tk.StringVar(value="")
        self.schedule_warning_label = ttk.Label(
            schedule_frame,
            textvariable=self.schedule_warning_var,
            foreground="#9a6700",
        )
        self.schedule_warning_label.grid(
            row=5, column=0, columnspan=4, sticky=tk.W, pady=(3, 0)
        )

        # 検索条件フレーム（スクロール可能にする）
        search_frame = ttk.LabelFrame(main_frame, text="検索条件", padding="5")
        search_frame.grid(
            row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10)
        )

        # スクロール可能なキャンバス
        canvas = tk.Canvas(search_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(search_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window(
            (0, 0), window=scrollable_frame, anchor="nw"
        )

        def configure_canvas_width(event):
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)

        canvas.bind("<Configure>", configure_canvas_width)
        canvas.configure(yscrollcommand=scrollbar.set)

        # bind_allをEnterごとに追加するとTcl commandが蓄積するため、
        # アプリ全体では一度だけ登録し、対象領域内かをフラグで判定する。
        self._search_canvas = canvas
        canvas.bind(
            "<Enter>",
            lambda _event: setattr(self, "_search_canvas_hovered", True),
        )
        canvas.bind(
            "<Leave>",
            lambda _event: setattr(self, "_search_canvas_hovered", False),
        )
        if self._mousewheel_bind_id is None:
            self._mousewheel_bind_id = self.root.bind_all(
                "<MouseWheel>", self._on_search_mousewheel, add="+"
            )

        # 検索条件を配置
        self.setup_search_conditions(scrollable_frame)
        bind_search_comboboxes_to_canvas(scrollable_frame, canvas)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 進捗
        progress_frame = ttk.LabelFrame(main_frame, text="進捗", padding="5")
        progress_frame.grid(
            row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10)
        )

        self.progress_var = tk.StringVar(value="待機中...")
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(anchor=tk.W)

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(5, 0))

        # ダウンロード進捗とは独立させ、検索後も確定集計を残す。
        summary_frame = ttk.Frame(progress_frame)
        summary_frame.pack(fill=tk.X, pady=(7, 0))
        self.summary_var = tk.StringVar(value="検索集計：未実行")
        ttk.Label(
            summary_frame,
            textvariable=self.summary_var,
            justify=tk.LEFT,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, anchor=tk.W)
        self.btn_project_documents = ttk.Button(
            summary_frame,
            text="案件・文書内訳",
            command=self.show_project_documents,
            state="disabled",
        )
        self.btn_project_documents.pack(side=tk.RIGHT, padx=(10, 0))

        # ログ表示
        log_frame = ttk.LabelFrame(main_frame, text="ログ", padding="5")
        log_frame.grid(
            row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10)
        )

        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=100)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # グリッドの重み設定
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)  # 検索条件フレーム
        main_frame.rowconfigure(4, weight=1)  # ログフレーム

    def _on_search_mousewheel(self, event) -> None:
        """検索条件領域にポインターがある場合だけCanvasをスクロールする。"""
        if not getattr(self, "_search_canvas_hovered", False):
            return
        canvas = getattr(self, "_search_canvas", None)
        if canvas is None:
            return
        delta = int(getattr(event, "delta", 0) or 0)
        if delta:
            canvas.yview_scroll(int(-1 * (delta / 120)), "units")

    def _unbind_search_mousewheel(self) -> None:
        bind_id = getattr(self, "_mousewheel_bind_id", None)
        if bind_id is None:
            return
        try:
            self.root.unbind_class("all", "<MouseWheel>", bind_id)
        except (tk.TclError, TypeError):
            pass
        self._mousewheel_bind_id = None

    @staticmethod
    def _target_from_display(value: str) -> SearchTarget:
        for profile in search_profiles():
            if value in {profile.display_label, profile.target.value}:
                return profile.target
        return SearchTarget.KOJI_KEIKA

    def _render_contract_options(self, selected: object = ()) -> None:
        frame = getattr(self, "contract_frame", None)
        if frame is None:
            return
        selected_values = {str(value) for value in (selected or ())}
        for child in frame.winfo_children():
            child.destroy()
        profile = get_search_profile(self._active_search_target)
        self.contract_type_vars = {}
        for index, contract_type in enumerate(profile.default_contract_types):
            variable = tk.BooleanVar(value=contract_type in selected_values)
            self.contract_type_vars[contract_type] = variable
            ttk.Checkbutton(frame, text=contract_type, variable=variable).grid(
                row=index // 3,
                column=index % 3,
                sticky=tk.W,
                padx=5,
                pady=2,
            )

    def _refresh_target_labels(self) -> None:
        profile = get_search_profile(self._active_search_target)
        self.project_name_frame.configure(text=f"{profile.project_label}（文字列検索）")
        self.project_name_label.configure(text=f"{profile.project_label}:")
        self.place_list_frame.configure(text=f"{profile.place_label}（リスト検索）")
        self.place_text_frame.configure(text=f"{profile.place_label}（文字列検索）")
        self.place_text_label.configure(text=f"{profile.place_label}:")
        if profile.target == SearchTarget.GYOMU_KEIKA:
            self.koji_shubetsu_frame.grid_remove()
            self.koji_gyoushu_frame.grid_remove()
            self.gyomu_kubun_frame.grid()
        else:
            self.koji_shubetsu_frame.grid()
            self.koji_gyoushu_frame.grid()
            self.gyomu_kubun_frame.grid_remove()

    def _on_search_target_changed(self, _event=None) -> None:
        new_target = self._target_from_display(self.search_target_var.get())
        if new_target == self._active_search_target:
            return

        # Comboboxはイベント時点で新値になっている。旧表示へ一時的に戻して
        # 現在の入力を旧対象draftへ保存し、その後で新対象draftを復元する。
        requested_label = self.search_target_var.get()
        old_target = self._active_search_target
        self.search_target_var.set(get_search_profile(old_target).display_label)
        try:
            self._target_drafts[old_target.value] = (
                self.get_config_from_ui().search_conditions
            )
        finally:
            self.search_target_var.set(requested_label)

        draft = deepcopy(self._target_drafts[new_target.value])
        draft.search_target = new_target.value
        profile = get_search_profile(new_target)
        self._active_search_target = new_target
        self._search_url = profile.search_url
        self.config.search_conditions = draft
        self.config.target_urls = [profile.search_url]

        with self._agency_option_guard:
            self._agency_cache_epoch += 1
            self._agency_catalog_epoch = -1
            self._agency_option_cache.clear()
        self._initial_search_option_cache.clear()
        self._search_option_model = SearchConditionOptionModel(
            draft,
            {
                "place_chihou": PLACE_CHIHOU_OPTIONS,
                "koji_shubetsu": KOJI_SHUBETSU_OPTIONS,
                "koji_gyoushu": KOJI_GYOUSHU_OPTIONS,
                "gyomu_kubun": (),
            },
        )
        self._prepare_agency_reload_ui()
        self._refresh_target_labels()
        self._render_contract_options(draft.contract_types)
        self.load_config_to_ui()
        self.load_initial_search_options()

    def setup_search_conditions(self, parent: ttk.Frame):
        """検索条件UIをセットアップ"""
        search_conditions = self.config.search_conditions
        row = 0
        self._dynamic_status_vars = {
            field: tk.StringVar(value="") for field in self._DYNAMIC_OPTION_FIELDS
        }

        # 親フレームの列の重みを設定
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        target_frame = ttk.LabelFrame(parent, text="検索対象", padding="5")
        target_frame.grid(
            row=row,
            column=0,
            columnspan=2,
            sticky=(tk.W, tk.E),
            pady=(0, 5),
            padx=5,
        )
        target_labels = [profile.display_label for profile in search_profiles()]
        self.search_target_var = tk.StringVar(
            value=get_search_profile(search_conditions.target).display_label
        )
        self.search_target_combo = ttk.Combobox(
            target_frame,
            textvariable=self.search_target_var,
            values=target_labels,
            state="readonly",
            width=28,
        )
        self.search_target_combo.pack(side=tk.LEFT, padx=5)
        self.search_target_combo.bind(
            "<<ComboboxSelected>>", self._on_search_target_changed
        )
        row += 1

        # 発注機関（リスト検索）
        hachu_frame = ttk.LabelFrame(parent, text="発注機関（リスト検索）", padding="5")
        hachu_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        hachu_frame.columnconfigure(1, weight=1)
        hachu_frame.columnconfigure(2, minsize=145)
        self._agency_status_vars = {
            field: tk.StringVar(value="")
            for field in (
                "hachu_daibunrui",
                "hachu_chubunrui",
                "hachu_shoubunrui",
                "hachu_saibunrui",
            )
        }
        row += 1

        # 大分類、中分類、小分類、細分類（プルダウン）
        ttk.Label(hachu_frame, text="大分類:").grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=2
        )
        self.hachu_daibunrui_var = tk.StringVar(value=search_conditions.hachu_daibunrui)
        self.hachu_daibunrui_combo = ttk.Combobox(
            hachu_frame,
            textvariable=self.hachu_daibunrui_var,
            values=[],  # 動的読み込み
            state="readonly",
            width=30,
        )
        self.hachu_daibunrui_combo.grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=2
        )
        ttk.Label(
            hachu_frame,
            textvariable=self._agency_status_vars["hachu_daibunrui"],
            foreground="#666666",
        ).grid(row=0, column=2, sticky=tk.W, padx=5)
        self.hachu_daibunrui_combo.bind(
            "<<ComboboxSelected>>", self.on_hachu_daibunrui_changed
        )

        ttk.Label(hachu_frame, text="中分類:").grid(
            row=1, column=0, sticky=tk.W, padx=5, pady=2
        )
        self.hachu_chubunrui_var = tk.StringVar(value=search_conditions.hachu_chubunrui)
        self.hachu_chubunrui_combo = ttk.Combobox(
            hachu_frame,
            textvariable=self.hachu_chubunrui_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        )
        self.hachu_chubunrui_combo.grid(
            row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=2
        )
        ttk.Label(
            hachu_frame,
            textvariable=self._agency_status_vars["hachu_chubunrui"],
            foreground="#666666",
        ).grid(row=1, column=2, sticky=tk.W, padx=5)
        self.hachu_chubunrui_combo.bind(
            "<<ComboboxSelected>>", self.on_hachu_chubunrui_changed
        )

        ttk.Label(hachu_frame, text="小分類:").grid(
            row=2, column=0, sticky=tk.W, padx=5, pady=2
        )
        self.hachu_shoubunrui_var = tk.StringVar(
            value=search_conditions.hachu_shoubunrui
        )
        self.hachu_shoubunrui_combo = ttk.Combobox(
            hachu_frame,
            textvariable=self.hachu_shoubunrui_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        )
        self.hachu_shoubunrui_combo.grid(
            row=2, column=1, sticky=(tk.W, tk.E), padx=5, pady=2
        )
        ttk.Label(
            hachu_frame,
            textvariable=self._agency_status_vars["hachu_shoubunrui"],
            foreground="#666666",
        ).grid(row=2, column=2, sticky=tk.W, padx=5)
        self.hachu_shoubunrui_combo.bind(
            "<<ComboboxSelected>>", self.on_hachu_shoubunrui_changed
        )

        ttk.Label(hachu_frame, text="細分類:").grid(
            row=3, column=0, sticky=tk.W, padx=5, pady=2
        )
        self.hachu_saibunrui_var = tk.StringVar(value=search_conditions.hachu_saibunrui)
        self.hachu_saibunrui_combo = ttk.Combobox(
            hachu_frame,
            textvariable=self.hachu_saibunrui_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        )
        self.hachu_saibunrui_combo.grid(
            row=3, column=1, sticky=(tk.W, tk.E), padx=5, pady=2
        )
        self.hachu_saibunrui_combo.bind(
            "<<ComboboxSelected>>", self.on_hachu_saibunrui_changed
        )
        ttk.Label(
            hachu_frame,
            textvariable=self._agency_status_vars["hachu_saibunrui"],
            foreground="#666666",
        ).grid(row=3, column=2, sticky=tk.W, padx=5)
        self.btn_reload_agency = ttk.Button(
            hachu_frame,
            text="候補を再読み込み",
            command=self.reload_agency_options,
        )
        self.btn_reload_agency.grid(row=4, column=1, sticky=tk.W, padx=5, pady=(4, 2))

        # 工事名（文字列検索）
        koji_name_frame = ttk.LabelFrame(
            parent, text="工事名（文字列検索）", padding="5"
        )
        self.project_name_frame = koji_name_frame
        koji_name_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.koji_name_var = tk.StringVar(
            value=search_conditions.effective_project_name
        )
        self.project_name_label = ttk.Label(koji_name_frame, text="工事名:")
        self.project_name_label.pack(side=tk.LEFT, padx=5)
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
        self.place_list_frame = place_frame
        place_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        place_frame.columnconfigure(1, weight=1)
        row += 1

        self.place_search_type_var = tk.StringVar(
            value=search_conditions.place_search_type
            if search_conditions.place_search_type in ("list", "text")
            else "list"
        )
        ttk.Radiobutton(
            place_frame,
            text="リスト検索を使用",
            variable=self.place_search_type_var,
            value="list",
            command=self._update_place_search_mode,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)

        # 地方、都道府県、市町村（プルダウン）
        place_chihou_options = ["", *PLACE_CHIHOU_OPTIONS]
        ttk.Label(place_frame, text="地方:").grid(
            row=1, column=0, sticky=tk.W, padx=5, pady=2
        )
        # 初期値を明示的に空文字列に設定（検索条件が空文字列でない場合のみ設定）
        initial_place_chihou = (
            search_conditions.place_chihou if search_conditions.place_chihou else ""
        )
        if initial_place_chihou and initial_place_chihou not in place_chihou_options:
            # サイト変更後の保存値を黙って空欄へ置き換えない。
            place_chihou_options.append(initial_place_chihou)
        self.place_chihou_var = tk.StringVar(value=initial_place_chihou)
        self.place_chihou_combobox = ttk.Combobox(
            place_frame,
            textvariable=self.place_chihou_var,
            values=place_chihou_options,
            state="readonly",
            width=30,
        )
        self.place_chihou_combobox.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        self.place_chihou_combobox.bind(
            "<<ComboboxSelected>>", self.on_place_chihou_changed
        )
        ttk.Label(
            place_frame,
            textvariable=self._dynamic_status_vars["place_chihou"],
            foreground="#9a6700",
        ).grid(row=1, column=2, sticky=tk.W, padx=5)
        self.place_chihou_var.set(initial_place_chihou)

        ttk.Label(place_frame, text="都道府県:").grid(
            row=2, column=0, sticky=tk.W, padx=5, pady=2
        )
        self.place_todofuken_var = tk.StringVar(value=search_conditions.place_todofuken)
        self.place_todofuken_combobox = ttk.Combobox(
            place_frame,
            textvariable=self.place_todofuken_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        )
        self.place_todofuken_combobox.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        self.place_todofuken_combobox.bind(
            "<<ComboboxSelected>>", self.on_place_todofuken_changed
        )
        ttk.Label(
            place_frame,
            textvariable=self._dynamic_status_vars["place_todofuken"],
            foreground="#9a6700",
        ).grid(row=2, column=2, sticky=tk.W, padx=5)

        ttk.Label(place_frame, text="市町村:").grid(
            row=3, column=0, sticky=tk.W, padx=5, pady=2
        )
        self.place_shichouson_var = tk.StringVar(
            value=search_conditions.place_shichouson
        )
        self.place_shichouson_combobox = ttk.Combobox(
            place_frame,
            textvariable=self.place_shichouson_var,
            values=[],  # 動的読み込み対応のため空
            state="readonly",
            width=30,
        )
        self.place_shichouson_combobox.grid(
            row=3, column=1, sticky=tk.W, padx=5, pady=2
        )
        self.place_shichouson_combobox.bind(
            "<<ComboboxSelected>>",
            lambda event: self._on_dynamic_option_selected("place_shichouson", event),
        )
        ttk.Label(
            place_frame,
            textvariable=self._dynamic_status_vars["place_shichouson"],
            foreground="#9a6700",
        ).grid(row=3, column=2, sticky=tk.W, padx=5)

        # 工事場所（文字列検索）
        place_text_frame = ttk.LabelFrame(
            parent, text="工事場所（文字列検索）", padding="5"
        )
        self.place_text_frame = place_text_frame
        place_text_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.place_text_var = tk.StringVar(value=search_conditions.place_text)
        ttk.Radiobutton(
            place_text_frame,
            text="文字列検索を使用",
            variable=self.place_search_type_var,
            value="text",
            command=self._update_place_search_mode,
        ).pack(side=tk.LEFT, padx=5)
        self.place_text_label = ttk.Label(place_text_frame, text="工事場所:")
        self.place_text_label.pack(side=tk.LEFT, padx=5)
        self.place_text_entry = ttk.Entry(
            place_text_frame, textvariable=self.place_text_var, width=60
        )
        self.place_text_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Label(
            place_text_frame,
            text="※条件の複数指定はできません。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))
        self._update_place_search_mode()

        # 入札契約方式
        contract_frame = ttk.LabelFrame(parent, text="入札契約方式", padding="5")
        self.contract_frame = contract_frame
        contract_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        # 入札契約方式はWebページでは複数の選択肢が並んでいるが、実際の動作は不明
        # 一旦チェックボックスで実装（Webページの表示通りに並べる）
        self.contract_type_vars = {}
        self._render_contract_options(search_conditions.contract_types)

        # 最終更新日
        update_date_frame = ttk.LabelFrame(parent, text="最終更新日", padding="5")
        update_date_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.update_date_type_var = tk.StringVar(
            value="none" if search_conditions.update_date_type == "none" else "past"
        )
        ttk.Radiobutton(
            update_date_frame,
            text="指定なし",
            variable=self.update_date_type_var,
            value="none",
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            update_date_frame,
            text="過去",
            variable=self.update_date_type_var,
            value="past",
        ).pack(side=tk.LEFT, padx=5)
        self.update_date_days_var = tk.StringVar(
            value=str(search_conditions.update_date_days)
            if search_conditions.update_date_days
            else "30"
        )
        ttk.Entry(
            update_date_frame, textvariable=self.update_date_days_var, width=5
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(update_date_frame, text="日以内").pack(side=tk.LEFT)

        # 公告日
        koukoku_frame = ttk.LabelFrame(parent, text="公告日", padding="5")
        koukoku_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.koukoku_date_type_var = tk.StringVar(
            value=search_conditions.koukoku_date_type
        )
        ttk.Radiobutton(
            koukoku_frame,
            text="指定なし",
            variable=self.koukoku_date_type_var,
            value="none",
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            koukoku_frame,
            text="期間指定",
            variable=self.koukoku_date_type_var,
            value="range",
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(koukoku_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.koukoku_date_start_var = tk.StringVar(
            value=search_conditions.koukoku_date_start or ""
        )
        ttk.Entry(
            koukoku_frame, textvariable=self.koukoku_date_start_var, width=12
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(koukoku_frame, text="～").pack(side=tk.LEFT, padx=2)
        self.koukoku_date_end_var = tk.StringVar(
            value=search_conditions.koukoku_date_end or ""
        )
        ttk.Entry(koukoku_frame, textvariable=self.koukoku_date_end_var, width=12).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(koukoku_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)

        # 開札日
        kaisatsu_frame = ttk.LabelFrame(parent, text="開札日", padding="5")
        kaisatsu_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.kaisatsu_date_type_var = tk.StringVar(
            value=search_conditions.kaisatsu_date_type
        )
        ttk.Radiobutton(
            kaisatsu_frame,
            text="指定なし",
            variable=self.kaisatsu_date_type_var,
            value="none",
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            kaisatsu_frame,
            text="期間指定",
            variable=self.kaisatsu_date_type_var,
            value="range",
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(kaisatsu_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.kaisatsu_date_start_var = tk.StringVar(
            value=search_conditions.kaisatsu_date_start or ""
        )
        ttk.Entry(
            kaisatsu_frame, textvariable=self.kaisatsu_date_start_var, width=12
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(kaisatsu_frame, text="～").pack(side=tk.LEFT, padx=2)
        self.kaisatsu_date_end_var = tk.StringVar(
            value=search_conditions.kaisatsu_date_end or ""
        )
        ttk.Entry(
            kaisatsu_frame, textvariable=self.kaisatsu_date_end_var, width=12
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(kaisatsu_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)

        # 契約日
        keiyaku_frame = ttk.LabelFrame(parent, text="契約日", padding="5")
        keiyaku_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.keiyaku_date_type_var = tk.StringVar(
            value=search_conditions.keiyaku_date_type
        )
        ttk.Radiobutton(
            keiyaku_frame,
            text="指定なし",
            variable=self.keiyaku_date_type_var,
            value="none",
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            keiyaku_frame,
            text="期間指定",
            variable=self.keiyaku_date_type_var,
            value="range",
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(keiyaku_frame, text="から").pack(side=tk.LEFT, padx=5)
        self.keiyaku_date_start_var = tk.StringVar(
            value=search_conditions.keiyaku_date_start or ""
        )
        ttk.Entry(
            keiyaku_frame, textvariable=self.keiyaku_date_start_var, width=12
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(keiyaku_frame, text="～").pack(side=tk.LEFT, padx=2)
        self.keiyaku_date_end_var = tk.StringVar(
            value=search_conditions.keiyaku_date_end or ""
        )
        ttk.Entry(keiyaku_frame, textvariable=self.keiyaku_date_end_var, width=12).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(keiyaku_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=2)

        # 工事種別（プルダウン）
        koji_shubetsu_frame = ttk.LabelFrame(parent, text="工事種別", padding="5")
        self.koji_shubetsu_frame = koji_shubetsu_frame
        koji_shubetsu_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        koji_shubetsu_options = list(
            self._search_option_model.widget_values(
                "koji_shubetsu", search_conditions.koji_shubetsu
            )
        )
        koji_shubetsu_input_frame = ttk.Frame(koji_shubetsu_frame)
        koji_shubetsu_input_frame.pack(fill=tk.X)
        self.koji_shubetsu_var = tk.StringVar(value=search_conditions.koji_shubetsu)
        ttk.Label(koji_shubetsu_input_frame, text="▽以下から選択").pack(
            side=tk.LEFT, padx=5
        )
        self.koji_shubetsu_combobox = ttk.Combobox(
            koji_shubetsu_input_frame,
            textvariable=self.koji_shubetsu_var,
            values=koji_shubetsu_options,
            state="readonly",
            width=40,
        )
        self.koji_shubetsu_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.koji_shubetsu_combobox.bind(
            "<<ComboboxSelected>>",
            lambda event: self._on_dynamic_option_selected("koji_shubetsu", event),
        )
        ttk.Label(
            koji_shubetsu_frame,
            text="※国土交通省及び内閣府沖縄総合事務局の区分。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))
        ttk.Label(
            koji_shubetsu_frame,
            textvariable=self._dynamic_status_vars["koji_shubetsu"],
            foreground="#9a6700",
        ).pack(anchor=tk.W, padx=5)

        # 工事の業種（プルダウン）
        koji_gyoushu_frame = ttk.LabelFrame(parent, text="工事の業種", padding="5")
        self.koji_gyoushu_frame = koji_gyoushu_frame
        koji_gyoushu_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        koji_gyoushu_options = list(
            self._search_option_model.widget_values(
                "koji_gyoushu", search_conditions.koji_gyoushu
            )
        )
        koji_gyoushu_input_frame = ttk.Frame(koji_gyoushu_frame)
        koji_gyoushu_input_frame.pack(fill=tk.X)
        self.koji_gyoushu_var = tk.StringVar(value=search_conditions.koji_gyoushu)
        ttk.Label(koji_gyoushu_input_frame, text="▽以下から選択").pack(
            side=tk.LEFT, padx=5
        )
        self.koji_gyoushu_combobox = ttk.Combobox(
            koji_gyoushu_input_frame,
            textvariable=self.koji_gyoushu_var,
            values=koji_gyoushu_options,
            state="readonly",
            width=40,
        )
        self.koji_gyoushu_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.koji_gyoushu_combobox.bind(
            "<<ComboboxSelected>>",
            lambda event: self._on_dynamic_option_selected("koji_gyoushu", event),
        )
        ttk.Label(
            koji_gyoushu_frame,
            text="※建設業法（別表第一）準拠。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))
        ttk.Label(
            koji_gyoushu_frame,
            textvariable=self._dynamic_status_vars["koji_gyoushu"],
            foreground="#9a6700",
        ).pack(anchor=tk.W, padx=5)

        # 業務区分（業務対象でだけ表示）
        gyomu_kubun_frame = ttk.LabelFrame(parent, text="業務区分", padding="5")
        self.gyomu_kubun_frame = gyomu_kubun_frame
        gyomu_kubun_frame.grid(
            row=row,
            column=0,
            columnspan=2,
            sticky=(tk.W, tk.E),
            pady=(0, 5),
            padx=5,
        )
        row += 1
        gyomu_input = ttk.Frame(gyomu_kubun_frame)
        gyomu_input.pack(fill=tk.X)
        ttk.Label(gyomu_input, text="▽以下から選択").pack(side=tk.LEFT, padx=5)
        self.gyomu_kubun_var = tk.StringVar(value=search_conditions.gyomu_kubun)
        self.gyomu_kubun_combobox = ttk.Combobox(
            gyomu_input,
            textvariable=self.gyomu_kubun_var,
            values=self._search_option_model.widget_values(
                "gyomu_kubun", search_conditions.gyomu_kubun
            ),
            state="readonly",
            width=40,
        )
        self.gyomu_kubun_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.gyomu_kubun_combobox.bind(
            "<<ComboboxSelected>>",
            lambda event: self._on_dynamic_option_selected("gyomu_kubun", event),
        )
        ttk.Label(
            gyomu_kubun_frame,
            textvariable=self._dynamic_status_vars["gyomu_kubun"],
            foreground="#9a6700",
        ).pack(anchor=tk.W, padx=5)
        if search_conditions.target != SearchTarget.GYOMU_KEIKA:
            gyomu_kubun_frame.grid_remove()

        # 予定価格（範囲指定）
        yotei_price_frame = ttk.LabelFrame(
            parent, text="予定価格（範囲指定）", padding="5"
        )
        yotei_price_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.yotei_price_min_var = tk.StringVar(
            value=str(search_conditions.yotei_price_min)
            if search_conditions.yotei_price_min
            else ""
        )
        self.yotei_price_max_var = tk.StringVar(
            value=str(search_conditions.yotei_price_max)
            if search_conditions.yotei_price_max
            else ""
        )
        ttk.Label(yotei_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)
        ttk.Entry(
            yotei_price_frame, textvariable=self.yotei_price_min_var, width=15
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(yotei_price_frame, text="～").pack(side=tk.LEFT, padx=5)
        ttk.Entry(
            yotei_price_frame, textvariable=self.yotei_price_max_var, width=15
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(yotei_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)

        # 落札価格／契約価格（範囲指定）
        rakusatsu_price_frame = ttk.LabelFrame(
            parent, text="落札価格／契約価格（範囲指定）", padding="5"
        )
        rakusatsu_price_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.rakusatsu_price_min_var = tk.StringVar(
            value=str(search_conditions.rakusatsu_price_min)
            if search_conditions.rakusatsu_price_min
            else ""
        )
        self.rakusatsu_price_max_var = tk.StringVar(
            value=str(search_conditions.rakusatsu_price_max)
            if search_conditions.rakusatsu_price_max
            else ""
        )
        ttk.Label(rakusatsu_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)
        ttk.Entry(
            rakusatsu_price_frame, textvariable=self.rakusatsu_price_min_var, width=15
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(rakusatsu_price_frame, text="～").pack(side=tk.LEFT, padx=5)
        ttk.Entry(
            rakusatsu_price_frame, textvariable=self.rakusatsu_price_max_var, width=15
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(rakusatsu_price_frame, text="（円）").pack(side=tk.LEFT, padx=5)

        # 落札者名／契約者名（文字列検索）
        rakusatsu_name_frame = ttk.LabelFrame(
            parent, text="落札者名／契約者名（文字列検索）", padding="5"
        )
        rakusatsu_name_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.rakusatsu_name_var = tk.StringVar(value=search_conditions.rakusatsu_name)
        ttk.Label(rakusatsu_name_frame, text="落札者名／契約者名:").pack(
            side=tk.LEFT, padx=5
        )
        ttk.Entry(
            rakusatsu_name_frame, textvariable=self.rakusatsu_name_var, width=50
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Label(
            rakusatsu_name_frame,
            text="※条件の複数指定はできません。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, padx=5, pady=(5, 0))

        # 電子入札・公開文書
        option_frame = ttk.LabelFrame(parent, text="オプション", padding="5")
        option_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )
        row += 1

        self.denshi_var = tk.BooleanVar(value=search_conditions.denshi)
        ttk.Checkbutton(
            option_frame, text="電子入札：対象案件のみ", variable=self.denshi_var
        ).pack(side=tk.LEFT, padx=5)

        self.koukai_var = tk.BooleanVar(value=search_conditions.koukai)
        ttk.Checkbutton(
            option_frame, text="公開文書：公開中のみ", variable=self.koukai_var
        ).pack(side=tk.LEFT, padx=5)

        # 表示件数
        display_count_frame = ttk.LabelFrame(
            parent, text="一覧画面の表示件数", padding="5"
        )
        display_count_frame.grid(
            row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), padx=5
        )

        self.display_count_var = tk.StringVar(
            value=str(search_conditions.display_count)
        )
        for count in ["20", "30", "50", "100"]:
            ttk.Radiobutton(
                display_count_frame,
                text=f"{count}件",
                variable=self.display_count_var,
                value=count,
            ).pack(side=tk.LEFT, padx=5)
        self._refresh_target_labels()

    def setup_bindings(self):
        """イベントバインディングをセットアップ"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Map>", lambda _event: self.request_schedule_status_refresh())

    def on_close(self):
        """通信を停止してからウィンドウを閉じる。"""
        if self._closing:
            return
        self._closing = True
        if getattr(self, "_schedule_poll_after_id", None) is not None:
            try:
                self.root.after_cancel(self._schedule_poll_after_id)
            except tk.TclError:
                pass
            self._schedule_poll_after_id = None
        self.cancel_flag.set()
        for cancel_event in getattr(self, "_agency_cancel_events", {}).values():
            cancel_event.set()
        coordinator = getattr(self, "_option_load_coordinator", None)
        if coordinator is not None:
            coordinator.stop(cancel_pending=True)
        self._unbind_search_mousewheel()
        event_handler = getattr(self, "event_handler", None)
        if event_handler is not None:
            event_handler.stop()
        project_dialog = getattr(self, "_project_documents_dialog", None)
        if project_dialog is not None and project_dialog.is_alive():
            project_dialog.close()
        for name in ("_schedule_history_dialog", "_schedule_log_dialog"):
            dialog = getattr(self, name, None)
            try:
                if dialog is not None and dialog.winfo_exists():
                    dialog.destroy()
            except tk.TclError:
                pass
            setattr(self, name, None)
        if hasattr(self, "btn_download"):
            self.btn_download.config(state="disabled")
        if hasattr(self, "btn_cancel"):
            self.btn_cancel.config(state="disabled")
        if self.close_callback:
            self.close_callback()
        if self._has_active_background_work():
            if hasattr(self, "progress_var"):
                self.progress_var.set("通信をキャンセルして終了しています...")
            self.root.after(100, self._finish_close_when_idle)
            return
        self._finalize_close()

    def _has_active_background_work(self) -> bool:
        if self.download_thread and self.download_thread.is_alive():
            return True
        coordinator = getattr(self, "_option_load_coordinator", None)
        return bool(coordinator is not None and not coordinator.is_idle)

    def _finalize_close(self) -> None:
        """Session所有ワーカー終了後にHTTP資源とTkを破棄する。"""
        coordinator = getattr(self, "_option_load_coordinator", None)
        if coordinator is not None:
            coordinator.join(0.1)
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
            self._scraper = None
        self._project_document_projects = ()
        self._project_document_projects_by_id = {}
        self.root.destroy()

    def _finish_close_when_idle(self):
        """実行スレッドの終了を待ち、Tk破棄後のUI操作を防ぐ。"""
        if self._has_active_background_work():
            self.root.after(100, self._finish_close_when_idle)
            return
        self._finalize_close()

    def _update_place_search_mode(self):
        """工事場所の検索方式に応じて入力欄を切り替える。"""
        use_list = self.place_search_type_var.get() == "list"
        list_state = "readonly" if use_list else "disabled"
        for combo in (
            self.place_chihou_combobox,
            self.place_todofuken_combobox,
            self.place_shichouson_combobox,
        ):
            combo.configure(state=list_state)
        self.place_text_entry.configure(state="disabled" if use_list else "normal")

    def _ensure_dynamic_option_state(self) -> None:
        """__new__を使う単体テストを含め、動的候補状態を遅延初期化する。"""

        if not hasattr(self, "_dynamic_option_generations"):
            self._dynamic_option_generations = {
                field: 0 for field in self._DYNAMIC_OPTION_FIELDS
            }
        if not hasattr(self, "_dynamic_user_revisions"):
            self._dynamic_user_revisions = {
                field: 0 for field in self._DYNAMIC_OPTION_FIELDS
            }
        if not hasattr(self, "_dynamic_invalid_fields"):
            self._dynamic_invalid_fields = set()
        if not hasattr(self, "_search_option_model"):
            initial = getattr(
                getattr(self, "config", None),
                "search_conditions",
                AppConfig().search_conditions,
            )
            self._search_option_model = SearchConditionOptionModel(initial)

    def _dynamic_option_variable(self, field: str):
        return getattr(self, f"{field}_var")

    def _dynamic_option_combo(self, field: str):
        suffix = "_combobox"
        return getattr(self, f"{field}{suffix}")

    def _dynamic_parent_values(self, field: str) -> tuple[str, ...]:
        return tuple(
            self._dynamic_option_variable(parent).get().strip()
            for parent in self._DYNAMIC_OPTION_PARENTS[field]
        )

    def _new_dynamic_option_token(
        self,
        field: str,
        parent_values: Optional[tuple[str, ...]] = None,
    ) -> DynamicOptionRequestToken:
        self._ensure_dynamic_option_state()
        generation = self._dynamic_option_generations.get(field, 0) + 1
        self._dynamic_option_generations[field] = generation
        return DynamicOptionRequestToken(
            field=field,
            generation=generation,
            parent_values=(
                self._dynamic_parent_values(field)
                if parent_values is None
                else tuple(parent_values)
            ),
            user_revision=self._dynamic_user_revisions.get(field, 0),
        )

    def _dynamic_option_token_is_current(
        self, token: DynamicOptionRequestToken
    ) -> bool:
        self._ensure_dynamic_option_state()
        return bool(
            token.generation == self._dynamic_option_generations.get(token.field, 0)
            and token.user_revision == self._dynamic_user_revisions.get(token.field, 0)
            and token.parent_values == self._dynamic_parent_values(token.field)
        )

    def _refresh_dynamic_option_status(self, field: str) -> None:
        status_vars = getattr(self, "_dynamic_status_vars", {})
        status = status_vars.get(field)
        if status is not None:
            status.set(
                "再選択が必要"
                if field in getattr(self, "_dynamic_invalid_fields", set())
                else ""
            )

    def _apply_dynamic_options(
        self,
        field: str,
        options: list,
        token: Optional[DynamicOptionRequestToken] = None,
    ) -> bool:
        """最新要求だけを適用し、現在の選択値は黙って変更しない。"""

        self._ensure_dynamic_option_state()
        if token is not None and not self._dynamic_option_token_is_current(token):
            return False
        variable = self._dynamic_option_variable(field)
        current = variable.get().strip()
        result = self._search_option_model.reconcile(field, current, options)
        if not result.applied:
            return False
        self._dynamic_option_combo(field)["values"] = list(result.widget_values)
        # values更新時のTk実装差にかかわらず、利用者が見ていた値を保持する。
        variable.set(result.selected_value)
        if result.invalid:
            self._dynamic_invalid_fields.add(field)
        else:
            self._dynamic_invalid_fields.discard(field)
        self._refresh_dynamic_option_status(field)
        return True

    def _on_dynamic_option_selected(self, field: str, _event=None) -> None:
        """利用者の明示選択を記録し、最新候補と再照合する。"""

        self._ensure_dynamic_option_state()
        self._dynamic_user_revisions[field] = (
            self._dynamic_user_revisions.get(field, 0) + 1
        )
        current = self._dynamic_option_variable(field).get().strip()
        if current and not self._search_option_model.contains(field, current):
            # 候補末尾に表示した保存済み旧値を選び直しても、
            # 公式候補にない限り「確認済み」とは扱わない。
            self._dynamic_invalid_fields.add(field)
        else:
            self._dynamic_invalid_fields.discard(field)
        self._refresh_dynamic_option_status(field)

    def _clear_dynamic_descendants(self, fields: tuple[str, ...]) -> None:
        """親を明示変更した場合だけ、依存する下位選択を消去する。"""

        self._ensure_dynamic_option_state()
        for field in fields:
            self._dynamic_option_generations[field] = (
                self._dynamic_option_generations.get(field, 0) + 1
            )
            self._dynamic_user_revisions[field] = (
                self._dynamic_user_revisions.get(field, 0) + 1
            )
            self._dynamic_invalid_fields.discard(field)
            self._dynamic_option_variable(field).set("")
            self._dynamic_option_combo(field)["values"] = []
            self._search_option_model.update(field, ())
            self._refresh_dynamic_option_status(field)

    def _restore_dynamic_option_value(self, field: str, value: str) -> None:
        """設定値を候補番号ではなく表示値で復元し、不明値も保持する。"""

        self._ensure_dynamic_option_state()
        normalized = self._search_option_model.display_value(field, value)
        combo = self._dynamic_option_combo(field)
        widget_values = list(self._combobox_option_values(combo))
        if "" not in widget_values:
            widget_values.insert(0, "")
        if normalized and normalized not in widget_values:
            widget_values.append(normalized)
        combo["values"] = widget_values
        self._dynamic_option_variable(field).set(normalized)
        # 進行中の旧設定向け応答は、親値が同じでも適用させない。
        self._dynamic_option_generations[field] = (
            self._dynamic_option_generations.get(field, 0) + 1
        )
        known_options = self._search_option_model.options(field)
        if (
            normalized
            and known_options
            and not self._search_option_model.contains(field, normalized)
        ):
            self._dynamic_invalid_fields.add(field)
        elif not normalized or self._search_option_model.contains(field, normalized):
            self._dynamic_invalid_fields.discard(field)
        self._refresh_dynamic_option_status(field)

    def load_initial_search_options(self):
        """検索初期ページを1回取得し、独立した候補をまとめて反映する。"""

        tokens = {
            field: self._new_dynamic_option_token(field, ())
            for field in (
                "place_chihou",
                "koji_shubetsu",
                "koji_gyoushu",
                "gyomu_kubun",
            )
        }
        self._begin_option_load()

        def load_in_thread():
            try:
                values = self._call_scraper_method(
                    "get_initial_search_option_pairs", self._search_url
                )
                self.event_handler.call_soon(
                    self._update_initial_search_options,
                    dict(values or {}),
                    tokens,
                )
            except Exception as exc:
                self.logger.error(f"検索初期候補の読み込みエラー: {exc}")
                self.event_handler.call_soon(
                    self._option_load_failed,
                    "地域・対象区分",
                    str(exc),
                )

        self._submit_option_task(
            "initial-search-options",
            load_in_thread,
            priority=OptionLoadCoordinator.PREFETCH_PRIORITY,
        )

    def _update_initial_search_options(
        self,
        values: dict[str, list[str]],
        tokens: Optional[dict[str, DynamicOptionRequestToken]] = None,
    ):
        """1回の検索ページ取得結果を各Comboboxへ反映する。"""

        try:
            place = list(values.get("place_chihou") or [])
            shubetsu = list(values.get("koji_shubetsu") or [])
            gyoushu = list(values.get("koji_gyoushu") or [])
            gyomu_kubun = list(values.get("gyomu_kubun") or [])
            applied_place = False
            if place:
                applied_place = self._apply_dynamic_options(
                    "place_chihou",
                    place,
                    (tokens or {}).get("place_chihou"),
                )
                if applied_place:
                    self._initial_search_option_cache["place_chihou"] = tuple(place)
            if shubetsu:
                if self._apply_dynamic_options(
                    "koji_shubetsu",
                    shubetsu,
                    (tokens or {}).get("koji_shubetsu"),
                ):
                    self._initial_search_option_cache["koji_shubetsu"] = tuple(shubetsu)
            if gyoushu:
                if self._apply_dynamic_options(
                    "koji_gyoushu",
                    gyoushu,
                    (tokens or {}).get("koji_gyoushu"),
                ):
                    self._initial_search_option_cache["koji_gyoushu"] = tuple(gyoushu)
            if gyomu_kubun:
                if self._apply_dynamic_options(
                    "gyomu_kubun",
                    gyomu_kubun,
                    (tokens or {}).get("gyomu_kubun"),
                ):
                    self._initial_search_option_cache["gyomu_kubun"] = tuple(
                        gyomu_kubun
                    )
            if applied_place and self.place_chihou_var.get():
                self.on_place_chihou_changed()
        finally:
            self._finish_option_load()

    def load_place_chihou_options(self):
        """対象サイトから地方の選択肢を読み込む。"""
        token = self._new_dynamic_option_token("place_chihou", ())
        self._begin_option_load()

        def load_in_thread():
            try:
                options = self._call_scraper_method(
                    "get_search_dropdown_option_pairs",
                    self._search_url,
                    get_search_profile(self._active_search_target).place_district_field,
                )
                self.event_handler.call_soon(
                    self._update_place_chihou_options, options, token
                )
            except Exception as exc:
                self.logger.error(f"地方オプション読み込みエラー: {exc}")
                self.event_handler.call_soon(
                    self._option_load_failed,
                    "地方オプション",
                    str(exc),
                )

        self._submit_option_task("place-regions", load_in_thread)

    def _update_place_chihou_options(
        self,
        options: list,
        token: Optional[DynamicOptionRequestToken] = None,
    ):
        """地方の選択肢を更新する。"""
        try:
            if not options:
                return
            if self._apply_dynamic_options("place_chihou", options, token):
                self._initial_search_option_cache["place_chihou"] = tuple(options)
        finally:
            self._finish_option_load()

    def on_place_chihou_changed(self, event=None):
        """地方変更時に都道府県を再取得する。"""
        chihou = self.place_chihou_var.get()
        self.place_search_type_var.set("list")
        self._update_place_search_mode()
        if event is not None:
            self._on_dynamic_option_selected("place_chihou", event)
            self._clear_dynamic_descendants(("place_todofuken", "place_shichouson"))
        if not chihou:
            return

        token = self._new_dynamic_option_token("place_todofuken", (chihou,))
        self._begin_option_load()

        def load_in_thread():
            try:
                options = self._call_scraper_method(
                    "get_place_todofuken_option_pairs",
                    self._search_url,
                    chihou,
                )
                self.event_handler.call_soon(
                    self._update_place_todofuken_options,
                    chihou,
                    options,
                    token,
                )
            except Exception as exc:
                self.logger.error(f"都道府県オプション読み込みエラー: {exc}")
                self.event_handler.call_soon(
                    self._option_load_failed,
                    "都道府県オプション",
                    str(exc),
                )

        self._submit_option_task(f"place-prefectures:{chihou}", load_in_thread)

    def _update_place_todofuken_options(
        self,
        requested_chihou: str,
        options: list,
        token: Optional[DynamicOptionRequestToken] = None,
    ):
        """都道府県の選択肢を更新する。"""
        try:
            if requested_chihou != self.place_chihou_var.get():
                return
            applied = self._apply_dynamic_options("place_todofuken", options, token)
            if applied and self.place_todofuken_var.get():
                self.on_place_todofuken_changed()
        finally:
            self._finish_option_load()

    def on_place_todofuken_changed(self, event=None):
        """都道府県変更時に市区町村を再取得する。"""
        chihou = self.place_chihou_var.get()
        todofuken = self.place_todofuken_var.get()
        self.place_search_type_var.set("list")
        self._update_place_search_mode()
        if event is not None:
            self._on_dynamic_option_selected("place_todofuken", event)
            self._clear_dynamic_descendants(("place_shichouson",))
        if not chihou or not todofuken:
            return

        token = self._new_dynamic_option_token("place_shichouson", (chihou, todofuken))
        self._begin_option_load()

        def load_in_thread():
            try:
                options = self._call_scraper_method(
                    "get_place_shichouson_option_pairs",
                    self._search_url,
                    chihou,
                    todofuken,
                )
                self.event_handler.call_soon(
                    self._update_place_shichouson_options,
                    chihou,
                    todofuken,
                    options,
                    token,
                )
            except Exception as exc:
                self.logger.error(f"市区町村オプション読み込みエラー: {exc}")
                self.event_handler.call_soon(
                    self._option_load_failed,
                    "市区町村オプション",
                    str(exc),
                )

        self._submit_option_task(f"place-cities:{chihou}:{todofuken}", load_in_thread)

    def _update_place_shichouson_options(
        self,
        requested_chihou: str,
        requested_todofuken: str,
        options: list,
        token: Optional[DynamicOptionRequestToken] = None,
    ):
        """市区町村の選択肢を更新する。"""
        try:
            if (
                requested_chihou != self.place_chihou_var.get()
                or requested_todofuken != self.place_todofuken_var.get()
            ):
                return
            self._apply_dynamic_options("place_shichouson", options, token)
        finally:
            self._finish_option_load()

    def _get_scraper(self):
        """Scraperインスタンスを取得（遅延初期化）"""
        if self._scraper is None:
            if self._http_client is None:
                self._http_client = HTTPClient(self.logger)
            self._scraper = Scraper(self._http_client, self.logger)
        return self._scraper

    def _call_scraper_method(self, method_name: str, *args):
        """共有SessionへのGUI候補取得を直列化する。"""
        with self._scraper_request_lock:
            method = getattr(self._get_scraper(), method_name)
            return method(*args)

    def _submit_option_task(
        self,
        key: str,
        callback: Callable[[], None],
        *,
        priority: int = OptionLoadCoordinator.USER_PRIORITY,
        finish_on_discard: bool = True,
    ) -> bool:
        """候補取得を単一ワーカーへ渡し、同一の未開始要求を統合する。"""
        coordinator = getattr(self, "_option_load_coordinator", None)
        if coordinator is None:
            # __new__で構築する既存の単体テストとの互換用。
            Thread(target=callback, daemon=True).start()
            return True

        on_discard = None
        if finish_on_discard:

            def finish_discarded_load() -> None:
                self.event_handler.call_soon(self._finish_option_load)

            on_discard = finish_discarded_load
        accepted = coordinator.submit(
            key,
            callback,
            priority=priority,
            on_discard=on_discard,
        )
        if not accepted and finish_on_discard:
            self.event_handler.call_soon(self._finish_option_load)
        return accepted

    def _begin_option_load(self):
        """検索候補の非同期取得中は実行スナップショットを作らせない。"""
        self._pending_option_loads += 1
        self._refresh_download_button_state()
        if hasattr(self, "progress_var"):
            self.progress_var.set("検索条件の候補を読み込み中...")

    def _finish_option_load(self):
        self._pending_option_loads = max(0, self._pending_option_loads - 1)
        self._refresh_download_button_state()
        if (
            self._pending_option_loads == 0
            and self.download_thread is None
            and hasattr(self, "progress_var")
        ):
            self.progress_var.set("待機中...")

    def _option_load_failed(self, label: str, error: str):
        self._finish_option_load()
        self.show_message(f"{label}の読み込みに失敗しました: {error}", "error")

    def _refresh_download_button_state(self):
        if not hasattr(self, "btn_download"):
            return
        running = bool(self.download_thread and self.download_thread.is_alive())
        state = (
            "disabled"
            if (
                running
                or self._pending_option_loads > 0
                or bool(getattr(self, "_schedule_queue_blocks_manual", False))
                or bool(getattr(self, "_installation_relocation_pending", False))
            )
            else "normal"
        )
        self.btn_download.config(state=state)

    def load_search_type_options(self):
        """工事種別・業種を対象サイトから読み込む。"""
        tokens = {
            field: self._new_dynamic_option_token(field, ())
            for field in ("koji_shubetsu", "koji_gyoushu")
        }
        self._begin_option_load()

        def load_in_thread():
            try:
                shubetsu = self._call_scraper_method(
                    "get_search_dropdown_option_pairs",
                    self._search_url,
                    "drpKojiKbn",
                )
                gyoushu = self._call_scraper_method(
                    "get_search_dropdown_option_pairs",
                    self._search_url,
                    "drpKojiGyosyu",
                )
                self.event_handler.call_soon(
                    self._update_search_type_options,
                    shubetsu,
                    gyoushu,
                    tokens,
                )
            except Exception as exc:
                self.logger.error(f"工事種別・業種の読み込みエラー: {exc}")
                self.event_handler.call_soon(
                    self._option_load_failed,
                    "工事種別・業種",
                    str(exc),
                )

        self._submit_option_task("search-types", load_in_thread)

    def _update_search_type_options(
        self,
        shubetsu: list,
        gyoushu: list,
        tokens: Optional[dict[str, DynamicOptionRequestToken]] = None,
    ):
        """サイト取得に成功した候補だけを表示名として反映する。"""
        try:
            if shubetsu:
                if self._apply_dynamic_options(
                    "koji_shubetsu",
                    shubetsu,
                    (tokens or {}).get("koji_shubetsu"),
                ):
                    self._initial_search_option_cache["koji_shubetsu"] = tuple(shubetsu)
            if gyoushu:
                if self._apply_dynamic_options(
                    "koji_gyoushu",
                    gyoushu,
                    (tokens or {}).get("koji_gyoushu"),
                ):
                    self._initial_search_option_cache["koji_gyoushu"] = tuple(gyoushu)
        finally:
            self._finish_option_load()

    def load_hachu_daibunrui_options(self):
        """公式ツリーを起動時に1回展開し、大分類を表示する。"""

        self._request_agency_options("hachu_daibunrui", ())

    def _update_hachu_daibunrui_options(self, options: list):
        """後方互換の更新入口。保存済み未知値は消さない。"""

        normalized = self._normalise_agency_options(options, AgencyPath())
        self._apply_agency_options(
            "hachu_daibunrui",
            self._agency_generations.get("hachu_daibunrui", 0),
            (),
            normalized,
            None,
            finish_load=True,
        )

    def on_hachu_daibunrui_changed(self, event=None):
        """大分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        self._invalidate_agency_descendants("hachu_daibunrui", event is not None)
        if not daibunrui_value:
            return
        self._request_agency_options("hachu_chubunrui", (daibunrui_value,))

    def _update_hachu_chubunrui_options(self, requested_daibunrui: str, options: list):
        """後方互換の中分類更新入口。"""

        parent = self._agency_path_from_labels((requested_daibunrui,))
        normalized = self._normalise_agency_options(options, parent)
        self._apply_agency_options(
            "hachu_chubunrui",
            self._agency_generations.get("hachu_chubunrui", 0),
            (requested_daibunrui,),
            normalized,
            None,
            finish_load=True,
        )

    def on_hachu_chubunrui_changed(self, event=None):
        """中分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        chubunrui_value = self.hachu_chubunrui_var.get()
        self._invalidate_agency_descendants("hachu_chubunrui", event is not None)
        if not chubunrui_value or not daibunrui_value:
            return
        self._request_agency_options(
            "hachu_shoubunrui", (daibunrui_value, chubunrui_value)
        )

    def _update_hachu_shoubunrui_options(
        self,
        requested_daibunrui: str,
        requested_chubunrui: str,
        options: list,
    ):
        """後方互換の小分類更新入口。"""

        labels = (requested_daibunrui, requested_chubunrui)
        parent = self._agency_path_from_labels(labels)
        normalized = self._normalise_agency_options(options, parent)
        self._apply_agency_options(
            "hachu_shoubunrui",
            self._agency_generations.get("hachu_shoubunrui", 0),
            labels,
            normalized,
            None,
            finish_load=True,
        )

    def on_hachu_shoubunrui_changed(self, event=None):
        """小分類が変更されたときの処理"""
        daibunrui_value = self.hachu_daibunrui_var.get()
        chubunrui_value = self.hachu_chubunrui_var.get()
        shoubunrui_value = self.hachu_shoubunrui_var.get()
        self._invalidate_agency_descendants("hachu_shoubunrui", event is not None)
        if not shoubunrui_value or not chubunrui_value or not daibunrui_value:
            return
        self._request_agency_options(
            "hachu_saibunrui",
            (daibunrui_value, chubunrui_value, shoubunrui_value),
        )

    def _update_hachu_saibunrui_options(
        self,
        requested_daibunrui: str,
        requested_chubunrui: str,
        requested_shoubunrui: str,
        options: list,
    ):
        """後方互換の細分類更新入口。"""

        labels = (
            requested_daibunrui,
            requested_chubunrui,
            requested_shoubunrui,
        )
        parent = self._agency_path_from_labels(labels)
        normalized = self._normalise_agency_options(options, parent)
        self._apply_agency_options(
            "hachu_saibunrui",
            self._agency_generations.get("hachu_saibunrui", 0),
            labels,
            normalized,
            None,
            finish_load=True,
        )

    def on_hachu_saibunrui_changed(self, event=None):
        """細分類を明示選択したら最新候補と再照合する。"""

        if event is not None:
            self._reconcile_agency_field_validity("hachu_saibunrui")

    def _agency_variable(self, field: str):
        return getattr(self, f"{field}_var")

    def _agency_combo(self, field: str):
        return getattr(self, f"{field}_combo")

    def _current_agency_parent_labels(self, field: str) -> tuple[str, ...]:
        depth = self._AGENCY_FIELDS.index(field)
        return tuple(
            self._agency_variable(parent).get().strip()
            for parent in self._AGENCY_FIELDS[:depth]
        )

    def _agency_cache_key(self, labels: tuple[str, ...]) -> tuple[int, tuple[str, ...]]:
        return self._agency_cache_epoch, tuple(labels)

    def _cached_agency_options(
        self, labels: tuple[str, ...]
    ) -> Optional[tuple[AgencyOption, ...]]:
        with self._agency_option_guard:
            return self._agency_option_cache.get(self._agency_cache_key(labels))

    def _reconcile_agency_field_validity(self, field: str) -> bool:
        """表示中の値がその親パスの取得済み候補にあるか照合する。"""

        current = self._agency_variable(field).get().strip()
        if not current:
            self._agency_invalid_fields.discard(field)
            self._set_agency_field_state(field)
            return True
        options = self._cached_agency_options(self._current_agency_parent_labels(field))
        valid = bool(
            options is not None and any(option.label == current for option in options)
        )
        if valid:
            self._agency_invalid_fields.discard(field)
        else:
            self._agency_invalid_fields.add(field)
        self._set_agency_field_state(field)
        return valid

    def _agency_path_from_labels(self, labels: tuple[str, ...]) -> AgencyPath:
        """メモリ候補を辿り、表示名をコード付きパスへ解決する。"""

        path = AgencyPath()
        for label in labels:
            if not label:
                break
            cached = self._cached_agency_options(path.labels)
            selected = next(
                (option for option in (cached or ()) if option.label == label),
                None,
            )
            if selected is None:
                # 保存済み値の検証前でも階層構造を保つ。実取得時には
                # コア側が表示名で照合し、見つからなければ明示エラーにする。
                level = path.next_level
                if level is None:
                    break
                selected = AgencyOption(
                    level=level,
                    code="",
                    label=label,
                    parent_path=path,
                )
            path = path.append(selected)
        return path

    @staticmethod
    def _normalise_agency_options(
        values: Any, parent: AgencyPath
    ) -> tuple[AgencyOption, ...]:
        raw_options = getattr(values, "options", values) or ()
        result: list[AgencyOption] = []
        seen: set[tuple[str, str]] = set()
        for raw in raw_options:
            if isinstance(raw, AgencyOption):
                option = raw
            else:
                label = str(getattr(raw, "label", raw) or "").strip()
                code = str(getattr(raw, "code", "") or "").strip()
                if not label or parent.next_level is None:
                    continue
                option = AgencyOption(
                    level=parent.next_level,
                    code=code,
                    label=label,
                    parent_path=parent,
                )
            key = (option.code, option.label)
            if key not in seen:
                seen.add(key)
                result.append(option)
        return tuple(result)

    def _bootstrap_agency_catalog(
        self, cancel_check: Optional[Callable[[], bool]] = None
    ) -> None:
        """利用可能なら公式複数選択ツリーをメモリへ展開する。"""

        scraper = self._get_scraper()
        method = getattr(scraper, "bootstrap_agency_catalog", None)
        if callable(method):
            method(self._search_url, cancel_check=cancel_check)

    def _fetch_agency_children(
        self,
        parent: AgencyPath,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> tuple[AgencyOption, ...]:
        """コアの構造化APIだけを使用して候補を取得する。"""

        scraper = self._get_scraper()
        method = getattr(scraper, "get_agency_children_result", None)
        if callable(method):
            raw = method(
                self._search_url,
                parent,
                cancel_check=cancel_check,
            )
            error = getattr(raw, "error", None)
            if error and not getattr(raw, "ok", False):
                code_value = getattr(getattr(error, "code", None), "value", "")
                message = str(getattr(error, "message", error) or "")
                prefix = f"[{code_value}] " if code_value else ""
                raise RuntimeError(f"{prefix}{message}")
            source = getattr(getattr(raw, "source", None), "value", "")
            self.logger.debug(
                "発注機関候補を取得しました: "
                f"depth={len(parent.segments)} source={source or '-'} "
                f"HTTP={getattr(raw, 'request_count', 0)}回 "
                f"経過={getattr(raw, 'elapsed_seconds', 0.0):.3f}秒"
            )
        else:
            # 1リリース互換。旧表示名専用APIへは戻さない。
            raw = scraper.get_agency_children(
                self._search_url,
                parent,
                cancel_check=cancel_check,
            )
        return self._normalise_agency_options(raw, parent)

    def _get_agency_children_singleflight(
        self,
        parent: AgencyPath,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> tuple[AgencyOption, ...]:
        """同じ親パスへのmain/schedule要求を1回へ統合する。"""

        key = self._agency_cache_key(parent.labels)
        with self._agency_option_guard:
            cached = self._agency_option_cache.get(key)
            if cached is not None:
                return cached
            flight = self._agency_option_flights.get(key)
            if flight is not None and self._agency_cancelled(flight.cancel_check):
                # A→B→Aのように最初のAが取消済みなら、その完了を新しいAへ
                # 共有しない。旧ownerはfinallyで新flightを削除しない。
                flight = None
            owner = flight is None
            if flight is None:
                flight = _AgencyOptionFlight(Event(), cancel_check)
                self._agency_option_flights[key] = flight

        if owner:
            try:
                with self._scraper_request_lock:
                    if self._agency_cancelled(cancel_check):
                        raise RuntimeError("発注機関候補の取得をキャンセルしました")
                    if self._agency_catalog_epoch != self._agency_cache_epoch:
                        try:
                            self._bootstrap_agency_catalog(cancel_check)
                        except Exception as exc:
                            # 公式ツリー障害時もリスト検索の取得経路を残す。
                            self.logger.warning(
                                f"発注機関一括候補を利用できません: {exc}"
                            )
                        self._agency_catalog_epoch = self._agency_cache_epoch
                    options = self._fetch_agency_children(parent, cancel_check)
                    if self._agency_cancelled(cancel_check):
                        raise RuntimeError("発注機関候補の取得をキャンセルしました")
                flight.options = options
                with self._agency_option_guard:
                    self._agency_option_cache[key] = options
            except Exception as exc:
                flight.error = exc
            finally:
                with self._agency_option_guard:
                    if self._agency_option_flights.get(key) is flight:
                        self._agency_option_flights.pop(key, None)
                flight.done.set()
        else:
            while not flight.done.wait(0.1):
                if cancel_check is not None and cancel_check():
                    raise RuntimeError("発注機関候補の取得をキャンセルしました")

        if flight.error is not None:
            raise flight.error
        return flight.options

    @staticmethod
    def _agency_cancelled(
        cancel_check: Optional[Callable[[], bool]],
    ) -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception:
            return False

    def _resolve_agency_path(
        self,
        labels: tuple[str, ...],
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgencyPath:
        """各階層の候補を順に照合し、コード付きパスを返す。"""

        path = AgencyPath()
        for label in labels:
            options = self._get_agency_children_singleflight(path, cancel_check)
            matches = [option for option in options if option.label == label]
            if len(matches) != 1:
                raise ValueError(f"発注機関「{label}」を候補から解決できません")
            path = path.append(matches[0])
        return path

    def _request_agency_options(
        self, field: str, parent_labels: tuple[str, ...]
    ) -> None:
        """候補を非同期取得し、世代が一致する応答だけを反映する。"""

        if getattr(self, "_closing", False):
            return
        generation = self._agency_generations.get(field, 0) + 1
        self._agency_generations[field] = generation
        previous_cancel = self._agency_cancel_events.pop(field, None)
        previous_parent = self._agency_request_parents.get(field)
        same_request = previous_cancel is not None and previous_parent == parent_labels
        if previous_cancel is not None and not same_request:
            previous_cancel.set()
        cached = self._cached_agency_options(parent_labels)
        if cached is not None:
            self._agency_request_parents.pop(field, None)
            self._apply_agency_options(
                field, generation, parent_labels, cached, None, finish_load=False
            )
            return

        self._agency_loading_fields.add(field)
        request_cancel = previous_cancel if same_request else Event()
        self._agency_cancel_events[field] = request_cancel
        self._agency_request_parents[field] = parent_labels
        self._set_agency_field_state(field)
        self._begin_option_load()

        def worker():
            try:
                parent = self._resolve_agency_path(parent_labels, request_cancel.is_set)
                options = self._get_agency_children_singleflight(
                    parent, request_cancel.is_set
                )
                error = None
            except Exception as exc:
                options, error = (), str(exc)
            self.event_handler.call_soon(
                self._apply_agency_options,
                field,
                generation,
                parent_labels,
                options,
                error,
                True,
            )

        self._submit_option_task(f"agency:{field}", worker)

    def _set_agency_field_state(self, field: str) -> None:
        combo = self._agency_combo(field)
        status_vars = getattr(self, "_agency_status_vars", {})
        status_var = status_vars.get(field)
        parents = self._current_agency_parent_labels(field)
        parent_missing = bool(parents) and any(not value for value in parents)
        if field in self._agency_loading_fields or parent_missing:
            combo.configure(state="disabled")
            if status_var is not None:
                status_var.set(
                    "読み込み中…" if field in self._agency_loading_fields else ""
                )
        else:
            combo.configure(state="readonly")
            if status_var is not None:
                status_var.set(
                    "再選択が必要" if field in self._agency_invalid_fields else ""
                )

    def _apply_agency_options(
        self,
        field: str,
        generation: int,
        parent_labels: tuple[str, ...],
        options: tuple[AgencyOption, ...],
        error: Optional[str],
        finish_load: bool = True,
    ) -> None:
        """Tkスレッドで候補を適用し、保存済み選択を順に復元する。"""

        try:
            if generation != self._agency_generations.get(field):
                return
            if parent_labels != self._current_agency_parent_labels(field):
                return
            self._agency_loading_fields.discard(field)
            self._agency_cancel_events.pop(field, None)
            self._agency_request_parents.pop(field, None)
            if error:
                if self._agency_variable(field).get().strip():
                    self._mark_agency_branch_invalid(field)
                self._set_agency_field_state(field)
                label = self._AGENCY_FIELD_LABELS[field]
                self.logger.error(f"{label}オプション読み込みエラー: {error}")
                self.show_message(
                    f"{label}候補を取得できませんでした: {error}", "error"
                )
                return

            labels = [option.label for option in options]
            variable = self._agency_variable(field)
            current = variable.get().strip()
            widget_values = ["", *labels]
            if current and current not in labels:
                # サイト変更で消えた保存値を黙って条件なしへ変えない。
                widget_values.append(current)
                self._mark_agency_branch_invalid(field)
            else:
                self._agency_invalid_fields.discard(field)
            self._agency_combo(field)["values"] = widget_values
            self._set_agency_field_state(field)

            if current and current in labels:
                next_field = {
                    "hachu_daibunrui": "hachu_chubunrui",
                    "hachu_chubunrui": "hachu_shoubunrui",
                    "hachu_shoubunrui": "hachu_saibunrui",
                }.get(field)
                if next_field is not None:
                    next_labels = (*parent_labels, current)
                    self._request_agency_options(next_field, next_labels)
        finally:
            if finish_load:
                self._finish_option_load()

    def _mark_agency_branch_invalid(self, field: str) -> None:
        """候補外になった親と、保持中の全子孫を無効として表示する。"""

        depth = self._AGENCY_FIELDS.index(field)
        self._agency_invalid_fields.add(field)
        for descendant in self._AGENCY_FIELDS[depth + 1 :]:
            if self._agency_variable(descendant).get().strip():
                self._agency_invalid_fields.add(descendant)
                self._set_agency_field_state(descendant)

    def _invalidate_agency_descendants(self, field: str, clear_values: bool) -> None:
        depth = self._AGENCY_FIELDS.index(field)
        if clear_values:
            # 利用者の明示操作でも、候補末尾に保持した旧値を
            # 選び直しただけで候補内とは判定しない。
            self._reconcile_agency_field_validity(field)
        else:
            self._set_agency_field_state(field)
        for descendant in self._AGENCY_FIELDS[depth + 1 :]:
            self._agency_generations[descendant] = (
                self._agency_generations.get(descendant, 0) + 1
            )
            self._agency_loading_fields.discard(descendant)
            cancel_event = self._agency_cancel_events.pop(descendant, None)
            if cancel_event is not None:
                cancel_event.set()
            self._agency_request_parents.pop(descendant, None)
            self._agency_invalid_fields.discard(descendant)
            if clear_values:
                self._agency_variable(descendant).set("")
            self._agency_combo(descendant)["values"] = []
            self._set_agency_field_state(descendant)

    def reload_agency_options(self) -> None:
        """公式候補を取り直し、成功時だけ対象の表示候補を置換する。"""

        if self._agency_reload_running:
            self._agency_reload_pending = True
            return
        self._agency_reload_running = True
        self._agency_reload_pending = False
        if hasattr(self, "btn_reload_agency"):
            self.btn_reload_agency.configure(state="disabled")

        self._prepare_agency_reload_ui()

        def refresh_core_cache():
            try:
                self._refresh_agency_cache_sync()
                error = None
            except Exception as exc:
                error = str(exc)
            self.event_handler.call_soon(self._finish_agency_reload, error)

        if not self._submit_option_task(
            "agency-reload",
            refresh_core_cache,
            finish_on_discard=False,
        ):
            self._finish_agency_reload("候補ワーカーは終了済みです")

    def _finish_agency_reload(self, error: Optional[str]) -> None:
        self._agency_reload_running = False
        if hasattr(self, "btn_reload_agency"):
            self.btn_reload_agency.configure(state="normal")
        if error:
            self._agency_catalog_refresh_error = str(error)
            for field in self._AGENCY_FIELDS:
                if self._agency_variable(field).get().strip():
                    self._agency_invalid_fields.add(field)
                status = self._agency_status_vars.get(field)
                if status is not None:
                    status.set("更新失敗・最新性未確認")
            self.show_message(
                "発注機関候補の再読み込みに失敗しました: "
                f"[AGENCY_CATALOG_REFRESH_FAILED] {error}",
                "error",
            )
        else:
            self._agency_catalog_refresh_error = ""
            self.load_hachu_daibunrui_options()
            self.load_initial_search_options()
        if self._agency_reload_pending and not self._closing:
            self._agency_reload_pending = False
            self.reload_agency_options()

    def _clear_agency_cache_sync(self) -> None:
        """GUIとコアの候補キャッシュを同期的に破棄する（通信はしない）。"""

        with self._agency_option_guard:
            self._agency_cache_epoch += 1
            self._agency_catalog_epoch = -1
            self._agency_option_cache.clear()

        with self._scraper_request_lock:
            scraper = self._get_scraper()
            method = getattr(scraper, "clear_agency_cache", None)
            if callable(method):
                method()
            else:
                service = getattr(scraper, "_agency_hierarchy_service", None)
                if service is not None:
                    service.clear_cache()

    def _refresh_agency_cache_sync(self, search_target: object = None) -> None:
        """新カタログ取得成功後に限りGUI側の対象cacheも切り替える。"""

        active_target = getattr(self, "_active_search_target", SearchTarget.KOJI_KEIKA)
        target = SearchTarget.coerce(search_target or active_target)
        search_url = get_search_profile(target).search_url
        with self._scraper_request_lock:
            scraper = self._get_scraper()
            method = getattr(scraper, "refresh_agency_catalog", None)
            if not callable(method):
                raise RuntimeError("発注機関候補の安全な再読み込みに未対応です")
            snapshot = method(search_url)
            error = getattr(snapshot, "error", None)
            if error is not None or not getattr(snapshot, "is_valid", False):
                code = getattr(getattr(error, "code", None), "value", "")
                message = str(getattr(error, "message", error) or "")
                raise RuntimeError(
                    f"[{code or 'AGENCY_CATALOG_REFRESH_FAILED'}] {message}"
                )

        if target == active_target:
            with self._agency_option_guard:
                self._agency_cache_epoch += 1
                self._agency_catalog_epoch = self._agency_cache_epoch
                self._agency_option_cache.clear()
            self._initial_search_option_cache.clear()

    def _prepare_agency_reload_ui(self) -> None:
        """Tkスレッドで進行中要求を無効化し、表示値は保持する。"""

        for cancel_event in self._agency_cancel_events.values():
            cancel_event.set()
        self._agency_cancel_events.clear()
        self._agency_request_parents.clear()
        for field in self._AGENCY_FIELDS:
            self._agency_generations[field] = self._agency_generations.get(field, 0) + 1
            self._agency_loading_fields.discard(field)
            self._agency_invalid_fields.discard(field)
            self._set_agency_field_state(field)

    def _reload_agency_options_for_schedule(
        self, *, search_target: object = None
    ) -> None:
        """定期実行編集画面からの再読込要求を共通サービスへ反映する。"""

        self._refresh_agency_cache_sync(search_target)
        self.event_handler.call_soon(self._finish_schedule_agency_reload)

    def _finish_schedule_agency_reload(self) -> None:
        self._prepare_agency_reload_ui()
        self.load_hachu_daibunrui_options()

    def set_download_callback(self, callback: Callable):
        """ダウンロードコールバックを設定"""
        self.download_callback = callback

    def set_schedule_change_callback(self, callback: Callable):
        """旧プロセス内スケジューラーとの後方互換コールバック。"""
        self.schedule_change_callback = callback

    def set_schedule_service(self, service: object):
        """Windowsタスク連携サービスを注入し、直ちに状態を更新する。"""
        self.schedule_service = service
        self._multiple_schedule_mode = bool(
            service is not None and ScheduleServiceAdapter(service).supports_multiple
        )
        preview_method = getattr(service, "preview_installation_relocation", None)
        if callable(preview_method):
            try:
                preview = preview_method(deepcopy(self.config))
            except Exception as exc:
                self._installation_relocation_pending = True
                self.logger.error(f"配置フォルダーを確認できません: {exc}")
                self.root.after(
                    0,
                    lambda exc=exc: messagebox.showerror(
                        "配置フォルダーの確認",
                        "配置フォルダーを確認できません。ダウンロードと設定保存を"
                        f"停止します。\n{exc}",
                        parent=self.root,
                    ),
                )
            else:
                self._installation_relocation_pending = bool(
                    getattr(preview, "required", False)
                )
                if self._installation_relocation_pending:
                    self.root.after(
                        0,
                        self._prompt_installation_relocation,
                        preview,
                    )
                else:
                    confirm = getattr(service, "confirm_current_installation", None)
                    if callable(confirm):
                        result = confirm()
                        if not bool(getattr(result, "success", False)):
                            self._installation_relocation_pending = True
                            message = str(getattr(result, "message", "") or "")
                            self.logger.error(
                                f"配置場所の管理情報を保存できません: {message}"
                            )
                            self.root.after(
                                0,
                                lambda message=message: messagebox.showerror(
                                    "配置フォルダーの確認",
                                    "配置場所の管理情報を保存できません。"
                                    "ダウンロードと設定保存を停止します。\n"
                                    f"{message}",
                                    parent=self.root,
                                ),
                            )
        self._refresh_download_button_state()
        self.request_schedule_status_refresh()

    def _prompt_installation_relocation(self, preview: object) -> None:
        """配置差分を明示し、承認後だけバックグラウンドで付け替える。"""

        if getattr(self, "_closing", False):
            return
        blocked = str(getattr(preview, "blocked_reason", "") or "")
        if blocked:
            messagebox.showerror(
                "配置フォルダーの確認",
                "配置フォルダーの変更を安全に処理できません。\n"
                f"{blocked}\n\nダウンロードと設定保存を停止します。",
                parent=self.root,
            )
            return
        old_root = str(getattr(preview, "old_root", "") or "-")
        current_root = str(getattr(preview, "current_root", "") or "-")
        schedule_count = len(tuple(getattr(preview, "affected_schedule_ids", ()) or ()))
        accepted = messagebox.askyesno(
            "配置フォルダーの変更",
            "配置フォルダーの変更を検出しました。\n\n"
            f"変更前: {old_root}\n"
            f"変更後: {current_root}\n"
            f"更新する定期実行: {schedule_count}件\n\n"
            "旧配置内を指す保存先とログだけを現在配置へ付け替えます。\n"
            "既存ファイル、履歴、旧フォルダーは移動・削除しません。\n"
            "現在配置へ付け替えますか？",
            parent=self.root,
        )
        if not accepted:
            self.logger.warning(
                "配置フォルダーの付け替えが承認されていないため実行を停止します"
            )
            self._refresh_download_button_state()
            return
        self._installation_relocation_running = True
        self._refresh_download_button_state()
        service = self.schedule_service

        def worker() -> None:
            try:
                result = service.apply_installation_relocation(
                    deepcopy(self.config),
                    self.config_manager,
                )
            except Exception as exc:
                result = exc
            self.event_handler.call_soon(
                self._finish_installation_relocation,
                result,
            )

        Thread(
            target=worker,
            name="ippi-installation-relocation",
            daemon=True,
        ).start()

    def _finish_installation_relocation(self, result: object) -> None:
        self._installation_relocation_running = False
        success = bool(getattr(result, "success", False))
        if not success:
            self._installation_relocation_pending = True
            code = str(
                getattr(result, "reason_code", "") or "INSTALLATION_RELOCATION_FAILED"
            )
            message = str(getattr(result, "message", "") or result)
            self.logger.error(
                f"配置フォルダーの付け替えに失敗しました [{code}]: {message}"
            )
            messagebox.showerror(
                "配置フォルダーの変更",
                "配置フォルダーを付け替えられませんでした。\n"
                f"理由コード: {code}\n{message}\n\n"
                "ダウンロードと設定保存を停止します。",
                parent=self.root,
            )
            self._refresh_download_button_state()
            self.request_schedule_status_refresh()
            return
        relocated_config = getattr(result, "config", None)
        if isinstance(relocated_config, AppConfig):
            self.config = relocated_config
            self.load_config_to_ui()
            # 共有logging.Loggerのhandlerも新しい配置基準へ直ちに切り替える。
            self.logger = Logger(self.config.logging)
        self._installation_relocation_pending = False
        migrated = len(tuple(getattr(result, "migrated_schedule_ids", ()) or ()))
        self.logger.info(
            f"配置フォルダーを現在位置へ付け替えました: 定期実行{migrated}件"
        )
        messagebox.showinfo(
            "配置フォルダーの変更",
            "現在の配置へ付け替えました。\n"
            f"更新した定期実行: {migrated}件\n"
            "旧フォルダーは自動削除していません。今後は起動しないでください。",
            parent=self.root,
        )
        self._refresh_download_button_state()
        self.request_schedule_status_refresh()

    def set_reclassification_service(self, service: object) -> None:
        """保存済みファイル再分類サービスを設定画面へ引き渡す。"""

        self.reclassification_service = service

    def _reclassification_block_reason(self) -> str:
        """通常・定期実行と競合する再分類をGUIで事前に拒否する。"""

        if bool(getattr(self, "_installation_relocation_pending", False)):
            return "配置フォルダーの付け替えが完了していません"

        thread = getattr(self, "download_thread", None)
        if thread is not None and thread.is_alive():
            return "通常ダウンロード実行中のため、完了後に再分類してください"
        if bool(getattr(self, "_schedule_queue_blocks_manual", False)):
            return "定期実行が実行中または順番待ちのため、完了後に再分類してください"
        counts = aggregate_schedule_counts(getattr(self, "_schedule_views", ()))
        if int(counts.get("queued", 0) or 0) > 0:
            return "定期実行が順番待ちのため、完了後に再分類してください"
        if int(counts.get("running", 0) or 0) > 0:
            return "定期実行中のため、完了後に再分類してください"
        return ""

    def _current_schedule_config_snapshot(self) -> AppConfig:
        """状態照会用。入力途中なら保存済み設定へ安全にフォールバックする。"""
        try:
            return deepcopy(self.get_config_from_ui())
        except (TypeError, ValueError):
            return deepcopy(self.config)

    def _current_schedule_registration_config(self) -> AppConfig:
        """登録用。画面上の不正値を旧設定へ置換せず明示的に拒否する。"""
        if getattr(self, "_pending_option_loads", 0) > 0:
            raise ValueError(
                "検索条件の候補を読み込み中です。完了してから登録してください"
            )
        selection_error = self._validate_dynamic_search_selections()
        if selection_error:
            raise ValueError(selection_error)
        # 変換エラーは呼出し側へ伝え、見えている条件と異なる登録を防ぐ。
        config = deepcopy(self.get_config_from_ui())
        is_valid, errors = self.config_manager.validate_config(config)
        if not is_valid:
            raise ValueError(
                "現在の検索条件を定期実行へ使用できません:\n"
                + "\n".join(f"・{error}" for error in errors)
            )
        return config

    def _validate_schedule_profile_dynamic_config(
        self, config: AppConfig
    ) -> tuple[bool, list[str]]:
        """候補画面に依存しない階層整合性を共通モデルで検証する。"""

        errors = validate_search_condition_structure(config.search_conditions)
        return (not errors, errors)

    @staticmethod
    def _combobox_option_values(combo: object) -> tuple[str, ...]:
        values = combo.cget("values") if combo is not None else ()
        if isinstance(values, str):
            return tuple(item for item in values.split() if item)
        return tuple(str(item) for item in values if str(item).strip())

    def _schedule_search_options_snapshot(self) -> dict[str, tuple[object, ...]]:
        """保持用に追加した旧値を除き、取得済み公式候補だけを複製する。"""

        values: dict[str, tuple[object, ...]] = {}
        for field in self._AGENCY_FIELDS:
            parents = self._current_agency_parent_labels(field)
            values[field] = tuple(self._cached_agency_options(parents) or ())
        for field in self._DYNAMIC_OPTION_FIELDS:
            values[field] = tuple(self._search_option_model.options(field))

        values["hachu_daibunrui"] = values["hachu_daibunrui"] or tuple(
            HACHU_DAIBUNRUI_FALLBACK_OPTIONS
        )
        values["place_chihou"] = values["place_chihou"] or tuple(PLACE_CHIHOU_OPTIONS)
        values["koji_shubetsu"] = values["koji_shubetsu"] or tuple(
            KOJI_SHUBETSU_OPTIONS
        )
        values["koji_gyoushu"] = values["koji_gyoushu"] or tuple(KOJI_GYOUSHU_OPTIONS)
        values["gyomu_kubun"] = values.get("gyomu_kubun", ())
        return values

    def _load_schedule_search_options(
        self,
        field: str,
        parents: tuple[str, ...] = (),
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        search_target: object = None,
    ) -> list[object]:
        """編集モーダル用候補を共有Scraper経由で取得する。Tk操作はしない。"""

        active_target = getattr(self, "_active_search_target", SearchTarget.KOJI_KEIKA)
        target = SearchTarget.coerce(search_target or active_target)
        profile = get_search_profile(target)
        search_url = profile.search_url
        agency_depths = {
            "hachu_daibunrui": 0,
            "hachu_chubunrui": 1,
            "hachu_shoubunrui": 2,
            "hachu_saibunrui": 3,
        }
        if field in agency_depths:
            required = agency_depths[field]
            selected = tuple(str(value).strip() for value in parents[:required])
            if len(selected) < required or any(not value for value in selected):
                return []
            if search_target is None:
                parent = self._resolve_agency_path(selected, cancel_check)
                return list(
                    self._get_agency_children_singleflight(parent, cancel_check)
                )
            parent = AgencyPath()
            with self._scraper_request_lock:
                scraper = self._get_scraper()
                getter = getattr(scraper, "get_agency_children_result")
                for label in selected:
                    result = getter(
                        search_url,
                        parent,
                        cancel_check=cancel_check,
                    )
                    error = getattr(result, "error", None)
                    if error is not None:
                        raise RuntimeError(str(error))
                    option = next(
                        (
                            item
                            for item in getattr(result, "options", ())
                            if item.label == label
                        ),
                        None,
                    )
                    if option is None:
                        raise ValueError(
                            "保存済みの発注機関は最新候補にありません "
                            "[AGENCY_SELECTION_REMOVED]"
                        )
                    parent = parent.append(option)
                result = getter(
                    search_url,
                    parent,
                    cancel_check=cancel_check,
                )
                error = getattr(result, "error", None)
                if error is not None:
                    raise RuntimeError(str(error))
                return list(getattr(result, "options", ()) or ())

        cached_initial = (
            self._initial_search_option_cache.get(field)
            if target == self._active_search_target
            else None
        )
        if cached_initial is not None:
            return list(cached_initial)

        category_fields = dict(profile.category_fields)
        method_and_args = {
            "place_chihou": (
                "get_search_dropdown_option_pairs",
                (search_url, profile.place_district_field),
            ),
            "place_todofuken": (
                "get_place_todofuken_option_pairs",
                (search_url, *parents[:1]),
            ),
            "place_shichouson": (
                "get_place_shichouson_option_pairs",
                (search_url, *parents[:2]),
            ),
            "koji_shubetsu": (
                "get_search_dropdown_option_pairs",
                (search_url, category_fields.get("koji_shubetsu", "")),
            ),
            "koji_gyoushu": (
                "get_search_dropdown_option_pairs",
                (search_url, category_fields.get("koji_gyoushu", "")),
            ),
            "gyomu_kubun": (
                "get_search_dropdown_option_pairs",
                (search_url, category_fields.get("gyomu_kubun", "")),
            ),
        }
        if field not in method_and_args:
            raise ValueError(f"未対応の検索候補です: {field}")
        method_name, args = method_and_args[field]
        if args[-1] == "":
            return []
        required_parents = {
            "place_todofuken": 1,
            "place_shichouson": 2,
        }.get(field, 0)
        if len(parents) < required_parents or any(
            not str(parent).strip() for parent in parents[:required_parents]
        ):
            return []
        return list(self._call_scraper_method(method_name, *args) or [])

    def request_schedule_status_refresh(self):
        """状態照会をバックグラウンドで開始する。"""
        if getattr(self, "_closing", False) or getattr(
            self, "_schedule_poll_suspended", False
        ):
            return
        self._schedule_refresh_generation = (
            getattr(self, "_schedule_refresh_generation", 0) + 1
        )
        generation = self._schedule_refresh_generation
        if getattr(self, "_schedule_status_query_running", False):
            self._schedule_refresh_pending = True
            return
        service = getattr(self, "schedule_service", None)
        if service is None:
            self._apply_schedule_status(None, None)
            return
        current_config = self._current_schedule_config_snapshot()
        self._schedule_status_query_running = True
        self._schedule_refresh_pending = False
        Thread(
            target=self._query_schedule_status_worker,
            args=(
                service,
                current_config,
                getattr(self, "_selected_schedule_id", None),
                generation,
            ),
            name="ippi-schedule-status",
            daemon=True,
        ).start()

    @staticmethod
    def _service_status(service: object, current_config: AppConfig) -> object:
        get_status = getattr(service, "get_status", None)
        if not callable(get_status):
            raise RuntimeError("登録状態の照会機能がありません")
        try:
            return get_status(config=current_config, current_config=current_config)
        except TypeError:
            try:
                return get_status(current_config)
            except TypeError:
                return get_status()

    @staticmethod
    def _service_history(service: object, limit: int = 20) -> list:
        history = getattr(service, "history", None)
        if not callable(history):
            return []
        try:
            return list(history(limit=limit) or [])
        except TypeError:
            return list(history(limit) or [])

    def _query_schedule_status_worker(
        self,
        service: object,
        current_config: AppConfig,
        selected_schedule_id: Optional[str] = None,
        generation: int = 0,
    ):
        try:
            adapter = ScheduleServiceAdapter(service)
            views = adapter.list_views(current_config)
            selected_id = selected_schedule_id
            if selected_id not in {view.schedule_id for view in views}:
                selected_id = next(
                    (view.schedule_id for view in views if not view.is_external),
                    None,
                )
            if selected_id is not None:
                records = adapter.history(selected_id, 20)
            else:
                records = []
            error = None
        except Exception as exc:
            views, records, error = [], [], str(exc)
        self.event_handler.call_soon(
            self._apply_schedule_collection,
            views,
            records,
            error,
            generation,
        )

    @staticmethod
    def _schedule_aggregate_text(views: list[ScheduleView]) -> str:
        counts = aggregate_schedule_counts(views)
        text = f"保存条件: {counts['total']}件 / 有効: {counts['enabled']}件"
        details = []
        if counts["running"]:
            details.append(f"実行中 {counts['running']}")
        if counts["queued"]:
            details.append(f"順番待ち {counts['queued']}")
        if counts["repair"]:
            details.append(f"要修復 {counts['repair']}")
        if counts["failed"]:
            details.append(f"前回失敗 {counts['failed']}")
        if counts["update"]:
            details.append(f"要更新 {counts['update']}")
        if details:
            text += " / " + " / ".join(details)
        next_candidates: list[tuple[float, ScheduleView, object]] = []
        for view in views:
            value = _schedule_value(view.status, "next_run")
            if value in {None, ""}:
                continue
            parsed = value
            if not isinstance(parsed, datetime):
                try:
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except ValueError:
                    continue
            try:
                order = parsed.timestamp()
            except (OSError, OverflowError, ValueError):
                continue
            next_candidates.append((order, view, value))
        if next_candidates:
            _, next_view, next_value = min(
                next_candidates, key=lambda candidate: candidate[0]
            )
            text += (
                f" / 最短次回: {next_view.name} {_format_schedule_datetime(next_value)}"
            )
        return text

    @staticmethod
    def _format_schedule_cadence(view: ScheduleView) -> str:
        schedule = _schedule_value(view.definition, "schedule")
        if schedule is None and isinstance(view.config, AppConfig):
            schedule = view.config.schedule
        if schedule is None:
            return "-（台帳欠落）"
        interval = str(_schedule_value(schedule, "interval", default="daily"))
        time_value = str(_schedule_value(schedule, "time", default="09:00"))
        if interval == "weekly":
            weekday = str(_schedule_value(schedule, "weekday", default="monday"))
            names = {
                "monday": "月",
                "tuesday": "火",
                "wednesday": "水",
                "thursday": "木",
                "friday": "金",
                "saturday": "土",
                "sunday": "日",
            }
            return f"毎週{names.get(weekday, weekday)}曜 {time_value}"
        if interval == "monthly":
            day = _schedule_value(schedule, "day_of_month", default=1)
            return f"毎月{day}日 {time_value}"
        return f"毎日 {time_value}"

    @staticmethod
    def _record_for_schedule_view(view: ScheduleView, records: list) -> object:
        for record in records:
            record_schedule_id = schedule_identifier(record, default="")
            if record_schedule_id and record_schedule_id == view.schedule_id:
                return record
        return MainWindow._record_for_schedule_status(view.status, records)

    def _apply_schedule_collection(
        self,
        views: list[ScheduleView],
        records: Optional[list] = None,
        error: Optional[str] = None,
        generation: Optional[int] = None,
    ) -> None:
        """複数登録の照会結果を1回のTk更新で一覧へ反映する。"""

        self._schedule_status_query_running = False
        if generation is not None and generation != getattr(
            self, "_schedule_refresh_generation", generation
        ):
            self._schedule_refresh_pending = False
            if not getattr(self, "_closing", False):
                self.root.after(0, self.request_schedule_status_refresh)
            return
        records = list(records or [])
        if error:
            # 一時的な照会失敗で正常だった一覧を消さない。
            views = list(getattr(self, "_schedule_views", []) or [])
        else:
            self._schedule_views = list(views)
            self._schedule_views_by_id = {
                view.schedule_id: view for view in self._schedule_views
            }
            self._last_schedule_records = records

        managed_views = [view for view in views if not view.is_external]
        external_count = len(views) - len(managed_views)
        if hasattr(self, "schedule_aggregate_var"):
            aggregate = self._schedule_aggregate_text(managed_views)
            if external_count:
                aggregate += f" / 管理外の旧タスク: {external_count}件"
            if error:
                aggregate += " / 状態確認失敗"
            self.schedule_aggregate_var.set(aggregate)

        selected_id = getattr(self, "_selected_schedule_id", None)
        known_ids = {view.schedule_id for view in managed_views}
        if selected_id not in known_ids:
            selected_id = next(
                (view.schedule_id for view in managed_views if view.enabled),
                managed_views[0].schedule_id if managed_views else None,
            )
        self._selected_schedule_id = selected_id
        if not error:
            self._last_schedule_history_id = selected_id

        tree = getattr(self, "schedule_tree", None)
        if tree is not None:
            rows: list[ScheduleTreeRow] = []
            for view in managed_views:
                status = view.status
                label, colour = _schedule_status_presentation(status)
                queue_position = _schedule_value(status, "queue_position")
                if label == "順番待ち" and queue_position:
                    label = f"順番待ち ({queue_position}番)"
                next_run = _schedule_value(status, "next_run")
                result = _format_schedule_result(
                    _schedule_value(status, "last_result", default="-")
                )
                new_count = _schedule_value(status, "new_count", default=0)
                existing_count = _schedule_value(
                    status, "existing_count", "saved_count", default=0
                )
                failed_count = _schedule_value(status, "failed_count", default=0)
                tag = f"schedule-{view.schedule_id}"
                tree.tag_configure(tag, foreground=colour)
                rows.append(
                    ScheduleTreeRow(
                        item_id=view.schedule_id,
                        tags=(tag,),
                        values=(
                            "はい" if view.enabled else "いいえ",
                            label,
                            view.name,
                            self._format_schedule_cadence(view),
                            _format_schedule_datetime(next_run),
                            result,
                            f"{new_count}/{existing_count}/{failed_count}",
                        ),
                    )
                )
            reconcile_schedule_tree(tree, rows, selected_id=selected_id)

        selected_view = (
            self._schedule_views_by_id.get(selected_id) if selected_id else None
        )
        if selected_view is None:
            self._apply_schedule_status(
                None,
                None,
                error,
                records,
                arm_poll=False,
            )
        else:
            record = self._record_for_schedule_view(selected_view, records)
            self._apply_schedule_status(
                selected_view.status,
                record,
                error,
                records,
                arm_poll=False,
            )

        # 待機中の定期実行を通常ダウンロードが追い越さないようにする。
        counts = aggregate_schedule_counts(managed_views)
        self._schedule_queue_blocks_manual = counts["queued"] > 0
        self._refresh_download_button_state()
        if self._schedule_queue_blocks_manual:
            queue_warning = "定期実行が順番待ちのため、通常ダウンロードを開始できません"
            current_warning = self.schedule_warning_var.get().strip()
            if queue_warning not in current_warning:
                self.schedule_warning_var.set(
                    f"{current_warning} / {queue_warning}"
                    if current_warning
                    else queue_warning
                )

        pending = bool(getattr(self, "_schedule_refresh_pending", False))
        self._schedule_refresh_pending = False
        if pending and not getattr(self, "_closing", False):
            self.root.after(0, self.request_schedule_status_refresh)
            return
        running = bool(getattr(self, "_schedule_action_running", False)) or any(
            bool(_schedule_value(view.status, "running", default=False))
            or bool(_schedule_value(view.status, "retry_waiting", default=False))
            or bool(
                _schedule_value(view.status, "queue_waiting", "queued", default=False)
            )
            or str(
                getattr(
                    _schedule_value(view.status, "state", default=""),
                    "value",
                    _schedule_value(view.status, "state", default=""),
                )
            ).lower()
            in {"queued", "queue_waiting", "waiting", "retry_waiting", "retry_wait"}
            for view in managed_views
        )
        self._arm_schedule_status_poll(5000 if running else 60000)

    def _on_schedule_tree_selected(self, _event=None) -> None:
        tree = getattr(self, "schedule_tree", None)
        if tree is None:
            return
        selection = tree.selection()
        if not selection:
            return
        schedule_id = str(selection[0])
        if schedule_id == getattr(self, "_selected_schedule_id", None):
            return
        self._selected_schedule_id = schedule_id
        view = getattr(self, "_schedule_views_by_id", {}).get(schedule_id)
        if view is not None:
            records = getattr(self, "_last_schedule_records", [])
            self._apply_schedule_status(
                view.status,
                self._record_for_schedule_view(view, records),
                records=records,
                arm_poll=False,
            )
        self._request_schedule_detail_refresh(schedule_id)

    def _request_schedule_detail_refresh(self, schedule_id: str) -> None:
        """選択行の履歴だけを取得し、一覧の世代や並び順へ影響させない。"""

        service = getattr(self, "schedule_service", None)
        if service is None:
            return
        self._schedule_detail_generation += 1
        generation = self._schedule_detail_generation

        def worker() -> None:
            try:
                records = ScheduleServiceAdapter(service).history(schedule_id, 20)
            except Exception:
                records = []
            self.event_handler.call_soon(
                self._apply_schedule_detail_records,
                schedule_id,
                records,
                generation,
            )

        Thread(
            target=worker,
            name="ippi-schedule-detail",
            daemon=True,
        ).start()

    def _apply_schedule_detail_records(
        self,
        schedule_id: str,
        records: list[object],
        generation: int,
    ) -> None:
        if generation != self._schedule_detail_generation:
            return
        if schedule_id != getattr(self, "_selected_schedule_id", None):
            return
        self._last_schedule_records = list(records)
        view = self._schedule_views_by_id.get(schedule_id)
        if view is not None:
            self._apply_schedule_status(
                view.status,
                self._record_for_schedule_view(view, records),
                records=records,
                arm_poll=False,
            )

    @staticmethod
    def _record_for_schedule_status(status: object, records: list) -> object:
        profile_id = _schedule_value(status, "profile_id", default="")
        if profile_id:
            return next(
                (
                    record
                    for record in records
                    if _schedule_value(record, "profile_id", default="") == profile_id
                ),
                None,
            )
        return records[0] if records else None

    def _poll_schedule_status(self):
        self._schedule_poll_after_id = None
        if getattr(self, "_closing", False):
            return
        self.request_schedule_status_refresh()

    def _arm_schedule_status_poll(self, delay_ms: int) -> None:
        """実行中は短く、待機中は低頻度になるよう次回照会を1件だけ予約する。"""

        if getattr(self, "_closing", False) or getattr(
            self, "_schedule_poll_suspended", False
        ):
            return
        if getattr(self, "root", None) is None:
            return
        current = getattr(self, "_schedule_poll_after_id", None)
        if current is not None:
            try:
                self.root.after_cancel(current)
            except tk.TclError:
                pass
        self._schedule_poll_after_id = self.root.after(
            delay_ms, self._poll_schedule_status
        )

    def _suspend_schedule_status_poll(self) -> None:
        """設定画面が同じserviceを照会する間はMain側のpollerを止める。"""

        self._schedule_poll_suspended = True
        after_id = getattr(self, "_schedule_poll_after_id", None)
        if after_id is None:
            return
        try:
            self.root.after_cancel(after_id)
        except tk.TclError:
            pass
        self._schedule_poll_after_id = None

    def _resume_schedule_status_poll(self) -> None:
        """設定画面を閉じた後、Main側の一括照会を1回だけ再開する。"""

        self._schedule_poll_suspended = False
        if not getattr(self, "_closing", False):
            self.request_schedule_status_refresh()

    def _apply_schedule_status(
        self,
        status: object,
        record: object = None,
        error: Optional[str] = None,
        records: Optional[list] = None,
        *,
        arm_poll: bool = True,
    ):
        """照会結果をメインスレッドでステータス欄へ反映する。"""
        if arm_poll:
            self._schedule_status_query_running = False
        self._last_schedule_status = status
        self._last_schedule_record = record
        if records is not None:
            self._last_schedule_records = records

        label, colour = _schedule_status_presentation(status)
        if error:
            label, colour = "要修復", "#cf222e"
        self.schedule_status_var.set(label)
        self.schedule_status_label.configure(foreground=colour)

        next_run = _schedule_value(status, "next_run")
        last_run = _schedule_value(status, "last_run") or _schedule_value(
            record, "finished_at", "ended_at"
        )
        last_result = _schedule_value(status, "last_result") or _schedule_value(
            record, "result", "outcome", default="-"
        )
        last_result = _format_schedule_result(last_result)
        self.schedule_timing_var.set(
            f"次回: {_format_schedule_datetime(next_run)} / "
            f"前回: {_format_schedule_datetime(last_run)} / "
            f"結果: {last_result}"
        )

        count_source = record if record is not None else status
        new_count = _schedule_value(count_source, "new_count", "saved", default="-")
        existing_count = _schedule_value(
            count_source,
            "existing_count",
            "saved_count",
            "reused",
            default="-",
        )
        failed_count = _schedule_value(
            count_source, "failed_count", "failed", default="-"
        )
        self.schedule_counts_var.set(
            f"新規保存: {new_count} / 保存済み確認: {existing_count} / "
            f"失敗: {failed_count}"
        )

        selected_view = getattr(self, "_schedule_views_by_id", {}).get(
            getattr(self, "_selected_schedule_id", None)
        )
        schedule = (
            _schedule_value(selected_view.definition, "schedule")
            if isinstance(selected_view, ScheduleView)
            else None
        )
        if schedule is None and isinstance(
            getattr(selected_view, "config", None), AppConfig
        ):
            schedule = selected_view.config.schedule
        if hasattr(self, "schedule_runtime_var"):
            if schedule is None:
                wake_text = notification_text = "-"
            else:
                wake_text = (
                    "ON"
                    if bool(_schedule_value(schedule, "wake_to_run", default=False))
                    else "OFF"
                )
                notification_text = format_schedule_notification_policy(
                    _schedule_value(schedule, "notification_policy", default="off")
                )
            registered_for_runtime = bool(
                _schedule_value(status, "registered", default=False)
            )
            enabled_for_runtime = bool(
                _schedule_value(status, "enabled", default=registered_for_runtime)
            )
            repair_for_runtime = bool(
                _schedule_value(status, "repair_reason", default="")
            )
            runtime_available = (
                registered_for_runtime
                and enabled_for_runtime
                and not repair_for_runtime
            )
            runtime_text = (
                "GUI終了後も実行可"
                if runtime_available
                else "GUI終了後の実行: 不可（有効なWindowsタスクなし）"
            )
            self.schedule_runtime_var.set(
                f"{runtime_text}（Windowsへのログオンが必要） / "
                f"スリープ解除: {wake_text} / 完了通知: {notification_text}"
            )

        warning = ""
        if error:
            warning = f"状態を確認できません [STATUS_QUERY_FAILED]: {error}"
        else:
            repair = _schedule_value(status, "repair_reason")
            reason_code = _schedule_value(status, "reason_code")
            mismatch = bool(
                _schedule_value(status, "definition_mismatch", default=False)
            )
            if repair:
                warning = f"要修復: {repair}"
                if reason_code:
                    warning += f" [{reason_code}]"
            elif mismatch and not bool(getattr(self, "_multiple_schedule_mode", False)):
                warning = "定期実行に未反映の変更があります"
            elif bool(getattr(self.config.schedule, "requires_migration", False)) or (
                self.config.schedule.enabled
                and getattr(self.config.schedule, "backend", "legacy")
                != "windows_task_scheduler"
            ):
                warning = "旧スケジュール設定です。Windowsタスクへ移行してください"
        self.schedule_warning_var.set(warning)

        registered = bool(_schedule_value(status, "registered", default=False))
        retry_waiting = bool(_schedule_value(status, "retry_waiting", default=False))
        running = (
            bool(_schedule_value(status, "running", default=False)) or retry_waiting
        )
        queued = bool(_schedule_value(status, "queue_waiting", "queued", default=False))
        repair_required = bool(_schedule_value(status, "repair_reason", default=""))
        can_run = (
            selected_view.allows("run")
            if isinstance(selected_view, ScheduleView)
            else registered and not repair_required
        )
        self.btn_schedule_run_now.configure(
            state=(
                "normal"
                if registered and can_run and not running and not queued
                else "disabled"
            )
        )
        # 外部タスクの開始も検出できるよう待機中は1分ごと、実行中は要件
        # どおり5秒ごとに確認する。
        if arm_poll:
            self._arm_schedule_status_poll(5000 if running or retry_waiting else 60000)

    def on_schedule_run_now(self):
        """登録済みスナップショットをWindowsタスク経由で開始する。"""
        service = getattr(self, "schedule_service", None)
        schedule_id = getattr(self, "_selected_schedule_id", None)
        if service is None or schedule_id is None:
            messagebox.showwarning(
                "定期実行",
                "実行する保存条件を選択してください。",
                parent=self.root,
            )
            return
        self.btn_schedule_run_now.configure(state="disabled")
        self.schedule_status_var.set("開始要求中")
        self._schedule_action_running = True

        def worker():
            try:
                success = ScheduleServiceAdapter(service).run_now(schedule_id)
                error = None
            except Exception as exc:
                success, error = False, str(exc)
            self.event_handler.call_soon(self._finish_schedule_run_now, success, error)

        Thread(
            target=worker,
            name="ippi-schedule-run-now",
            daemon=True,
        ).start()

    def _finish_schedule_run_now(self, success: object, error: Optional[str] = None):
        self._schedule_action_running = False
        if success is False or error:
            messagebox.showerror(
                "定期実行",
                f"Windowsタスクを開始できませんでした。\n"
                f"理由コード: TASK_START_FAILED\n{error or ''}",
                parent=self.root,
            )
        else:
            self.show_message("定期実行の開始をWindowsへ要求しました", "info")
        self.request_schedule_status_refresh()
        if success is not False and not error:
            # /Run直後はWindows側の状態反映にわずかな遅延がある。
            self.root.after(1000, self.request_schedule_status_refresh)

    def show_schedule_history(self):
        """選択設定または全設定の直近20回を別画面で表示する。"""
        schedule_id = getattr(self, "_selected_schedule_id", None)
        if schedule_id is None:
            messagebox.showwarning(
                "実行履歴", "保存条件を選択してください。", parent=self.root
            )
            return
        service = getattr(self, "schedule_service", None)
        if service is None:
            return
        existing = getattr(self, "_schedule_history_dialog", None)
        try:
            if (
                existing is not None
                and existing.winfo_exists()
                and self._last_schedule_history_id == schedule_id
            ):
                existing.deiconify()
                existing.lift()
                return
        except tk.TclError:
            self._schedule_history_dialog = None
        if self._schedule_history_load_running:
            return
        self._schedule_history_load_running = True

        def worker():
            try:
                adapter = ScheduleServiceAdapter(service)
                selected_records = adapter.history(schedule_id, 20)
                all_records = adapter.history(None, 20)
                error = None
            except Exception as exc:
                selected_records, all_records, error = [], [], str(exc)
            self.event_handler.call_soon(
                self._finish_schedule_history_load,
                schedule_id,
                selected_records,
                all_records,
                error,
            )

        Thread(
            target=worker,
            name="ippi-schedule-history",
            daemon=True,
        ).start()

    def _finish_schedule_history_load(
        self,
        schedule_id: str,
        selected_records: list,
        all_records: list,
        error: Optional[str] = None,
    ) -> None:
        self._schedule_history_load_running = False
        if error:
            messagebox.showerror(
                "実行履歴", f"履歴を読み込めません: {error}", parent=self.root
            )
            return
        self._last_schedule_history_id = schedule_id
        self._last_schedule_records = list(selected_records)
        self._open_schedule_history_dialog(
            selected_records,
            all_records,
            schedule_id,
        )

    def _open_schedule_history_dialog(
        self,
        selected_records: list,
        all_records: list,
        schedule_id: str,
    ) -> None:
        from ..gui.settings_dialog import format_schedule_reason

        view = getattr(self, "_schedule_views_by_id", {}).get(schedule_id)
        name = view.name if view is not None else schedule_id
        previous = getattr(self, "_schedule_history_dialog", None)
        try:
            if previous is not None and previous.winfo_exists():
                previous.destroy()
        except tk.TclError:
            pass
        dialog = tk.Toplevel(self.root)
        self._schedule_history_dialog = dialog
        dialog.title(f"定期実行履歴 - {name}（直近20回）")
        fit_to_screen(dialog, 1250, 460, minimum_width=600, minimum_height=360)
        frame = ttk.Frame(dialog, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        filter_frame = ttk.Frame(frame)
        filter_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(filter_frame, text="表示:").pack(side=tk.LEFT)
        filter_var = tk.StringVar(value="選択設定")
        filter_combo = ttk.Combobox(
            filter_frame,
            textvariable=filter_var,
            values=("選択設定", "全設定"),
            state="readonly",
            width=10,
        )
        filter_combo.pack(side=tk.LEFT, padx=(4, 0))

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill=tk.BOTH, expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = (
            "name",
            "scheduled",
            "started",
            "finished",
            "trigger",
            "queue",
            "result",
            "counts",
            "retry",
            "reason",
            "exit",
        )
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        headings = (
            "設定名",
            "予定日時",
            "開始日時",
            "終了日時",
            "起動種別",
            "待機時間",
            "結果",
            "新規/保存済/失敗",
            "再試行",
            "理由（コード）",
            "終了コード",
        )
        widths = (145, 120, 120, 120, 85, 70, 85, 125, 55, 150, 65)
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, stretch=column == "reason")
        current_names = {
            view.schedule_id: view.name for view in getattr(self, "_schedule_views", [])
        }
        if not getattr(self, "_multiple_schedule_mode", False):
            current_names.setdefault("", name)

        def populate(records: list) -> None:
            for item in tree.get_children():
                tree.delete(item)
            for record in records[:20]:
                new_count = _schedule_value(record, "new_count", "saved", default=0)
                existing_count = _schedule_value(
                    record,
                    "existing_count",
                    "saved_count",
                    "reused",
                    default=0,
                )
                failed_count = _schedule_value(
                    record, "failed_count", "failed", default=0
                )
                queue_wait = _schedule_value(record, "queue_wait_seconds", default=0)
                try:
                    queue_wait_text = f"{float(queue_wait or 0):.1f}秒"
                except (TypeError, ValueError):
                    queue_wait_text = str(queue_wait or "-")
                tree.insert(
                    "",
                    tk.END,
                    values=(
                        history_display_name(record, current_names),
                        _format_schedule_datetime(
                            _schedule_value(record, "scheduled_at")
                        ),
                        _format_schedule_datetime(
                            _schedule_value(record, "started_at")
                        ),
                        _format_schedule_datetime(
                            _schedule_value(record, "finished_at", "ended_at")
                        ),
                        trigger_kind_display(
                            _schedule_value(record, "trigger_kind", default="")
                        ),
                        queue_wait_text,
                        _format_schedule_result(
                            _schedule_value(record, "result", "outcome", default="-")
                        ),
                        f"{new_count}/{existing_count}/{failed_count}",
                        _schedule_value(record, "retry_count", default=0),
                        format_schedule_reason(
                            _schedule_value(record, "reason_code", default="")
                        ),
                        _schedule_value(record, "exit_code", default="-"),
                    ),
                )

        def on_filter_changed(_event=None) -> None:
            populate(all_records if filter_var.get() == "全設定" else selected_records)

        filter_combo.bind("<<ComboboxSelected>>", on_filter_changed)
        populate(selected_records)
        tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        xscrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        xscrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
        tree.configure(
            yscrollcommand=scrollbar.set,
            xscrollcommand=xscrollbar.set,
        )

        def close_dialog() -> None:
            try:
                tree.delete(*tree.get_children())
                dialog.destroy()
            finally:
                if self._schedule_history_dialog is dialog:
                    self._schedule_history_dialog = None

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    def open_schedule_log(self):
        """選択中の保存条件に対応するJSONLレコードだけを表示する。"""
        service = getattr(self, "schedule_service", None)
        path = _schedule_value(service, "history_path", "log_path")
        if path is None and service is not None:
            ledger = getattr(service, "ledger", None)
            path = _schedule_value(ledger, "path", "file_path")
        target = Path(path) if path else Path(get_logs_path("schedule-runs.jsonl"))
        schedule_id = getattr(self, "_selected_schedule_id", None)
        if schedule_id is None:
            target = target if target.exists() else target.parent
            try:
                os.startfile(str(target))
            except (AttributeError, OSError) as exc:
                messagebox.showerror(
                    "ログ",
                    f"ログを開けませんでした:\n{target}\n{exc}",
                    parent=self.root,
                )
            return

        view = getattr(self, "_schedule_views_by_id", {}).get(schedule_id)
        profile_id = view.profile_id if view is not None else ""
        existing = getattr(self, "_schedule_log_dialog", None)
        try:
            if existing is not None and existing.winfo_exists():
                if self._schedule_log_schedule_id == schedule_id:
                    existing.deiconify()
                    existing.lift()
                    return
                existing.destroy()
                self._schedule_log_dialog = None
                self._schedule_log_schedule_id = None
        except tk.TclError:
            self._schedule_log_dialog = None
        if self._schedule_log_load_running:
            return
        self._schedule_log_load_running = True

        def worker() -> None:
            try:
                lines = self._read_schedule_log_tail(target, schedule_id, profile_id)
                error = None
            except (OSError, UnicodeError) as exc:
                lines, error = [], str(exc)
            self.event_handler.call_soon(
                self._show_selected_schedule_log,
                schedule_id,
                lines,
                target,
                error,
            )

        Thread(
            target=worker,
            name="ippi-schedule-log",
            daemon=True,
        ).start()

    @staticmethod
    def _read_schedule_log_tail(
        target: Path,
        schedule_id: str,
        profile_id: str = "",
        *,
        max_records: int = 200,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> list[str]:
        """JSONL末尾だけを読み、選択設定の直近レコードを返す。"""
        if not target.exists() or max_records <= 0 or max_bytes <= 0:
            return []
        with target.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            position = stream.tell()
            remaining = min(position, max_bytes)
            buffer = b""
            while position > 0 and remaining > 0:
                chunk_size = min(64 * 1024, position, remaining)
                position -= chunk_size
                stream.seek(position)
                buffer = stream.read(chunk_size) + buffer
                remaining -= chunk_size

        matched: list[str] = []
        formatted_bytes = 0
        for raw_line in reversed(buffer.splitlines()):
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            if record.get("schedule_id") == schedule_id or (
                not record.get("schedule_id")
                and profile_id
                and record.get("profile_id") == profile_id
            ):
                formatted = json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                item_bytes = len(formatted.encode("utf-8"))
                separator_bytes = 2 if matched else 0
                if formatted_bytes + separator_bytes + item_bytes > max_bytes:
                    break
                matched.append(formatted)
                formatted_bytes += separator_bytes + item_bytes
                if len(matched) >= max_records:
                    break
        matched.reverse()
        return matched

    def _show_selected_schedule_log(
        self,
        schedule_id: str,
        lines: list[str],
        target: Path,
        error: Optional[str] = None,
    ) -> None:
        self._schedule_log_load_running = False
        if error:
            messagebox.showerror(
                "ログ",
                f"ログを読み込めませんでした:\n{target}\n{error}",
                parent=self.root,
            )
            return
        view = getattr(self, "_schedule_views_by_id", {}).get(schedule_id)
        name = view.name if view is not None else schedule_id
        previous = getattr(self, "_schedule_log_dialog", None)
        try:
            if previous is not None and previous.winfo_exists():
                previous.destroy()
        except tk.TclError:
            pass
        dialog = tk.Toplevel(self.root)
        self._schedule_log_dialog = dialog
        self._schedule_log_schedule_id = schedule_id
        dialog.title(f"定期実行ログ - {name}")
        fit_to_screen(dialog, 900, 560, minimum_width=560, minimum_height=380)
        text_widget = scrolledtext.ScrolledText(
            dialog, wrap=tk.NONE, font=("Consolas", 9)
        )
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(
            "1.0",
            "\n\n".join(lines)
            if lines
            else f"{target}\n\n選択した条件の実行ログはまだありません。",
        )
        text_widget.configure(state="disabled")

        def close_dialog() -> None:
            try:
                text_widget.configure(state="normal")
                text_widget.delete("1.0", tk.END)
                dialog.destroy()
            finally:
                if self._schedule_log_dialog is dialog:
                    self._schedule_log_dialog = None
                    self._schedule_log_schedule_id = None

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    def set_close_callback(self, callback: Callable):
        """ウィンドウ終了時のリソース解放処理を設定する。"""
        self.close_callback = callback

    def on_download_start(self):
        """ダウンロード開始ボタンのハンドラ"""
        if bool(getattr(self, "_installation_relocation_pending", False)):
            messagebox.showwarning(
                "配置フォルダーの確認",
                "配置フォルダーの付け替えが完了するまでダウンロードできません。",
                parent=self.root,
            )
            return
        if bool(getattr(self, "_schedule_queue_blocks_manual", False)):
            messagebox.showwarning(
                "定期実行を待機中",
                "定期実行が順番待ちです。完了後に通常ダウンロードを開始してください。",
                parent=self.root,
            )
            return
        if not self.download_callback:
            messagebox.showwarning("警告", "ダウンロード機能が設定されていません")
            return
        if self.download_thread and self.download_thread.is_alive():
            messagebox.showwarning("警告", "ダウンロードは既に実行中です")
            return
        if self._pending_option_loads > 0:
            messagebox.showwarning(
                "検索条件を確認中",
                "検索条件の候補を読み込み中です。完了してから開始してください。",
            )
            return
        selection_error = self._validate_dynamic_search_selections()
        if selection_error:
            messagebox.showerror("検索条件エラー", selection_error)
            return

        # Tk変数はメインスレッドで読み、ワーカースレッドにはスナップショットだけを渡す。
        try:
            config_snapshot = deepcopy(self.get_config_from_ui())
        except (TypeError, ValueError) as exc:
            messagebox.showerror("入力エラー", str(exc))
            return
        is_valid, errors = self.config_manager.validate_config(config_snapshot)
        if not is_valid:
            messagebox.showerror(
                "入力エラー",
                "\n".join(f"・{error}" for error in errors),
            )
            return
        condition_summary = format_search_conditions(config_snapshot.search_conditions)
        condition_message = f"今回の実行条件: {condition_summary}"
        self.logger.info(condition_message)
        self.show_message(condition_message, "info")
        window_was_visible = bool(self.root.winfo_viewable())
        redownload_policy = (
            RedownloadPolicy.FORCE_REFRESH
            if self.redownload_existing_var.get()
            else RedownloadPolicy.REUSE_VERIFIED
        )

        # キャンセルフラグをリセット
        self.cancel_flag.clear()
        self._last_run_outcome = None

        # UIを更新
        self.btn_download.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.chk_redownload_existing.config(state="disabled")
        self._begin_search_summary()
        self._set_search_progress_mode("検索を開始しています...")

        # 別スレッドでダウンロードを実行
        self.download_thread = Thread(
            target=self._download_thread,
            args=(
                config_snapshot,
                window_was_visible,
                redownload_policy,
                condition_summary,
            ),
        )
        self.download_thread.daemon = True
        self.download_thread.start()

    def _validate_dynamic_search_selections(self) -> str:
        """表示中の階層値が現在の候補集合と整合することを確認する。"""
        has_agency_selection = any(
            self._agency_variable(field).get().strip() for field in self._AGENCY_FIELDS
        )
        if getattr(self, "_agency_reload_running", False) and has_agency_selection:
            return (
                "[AGENCY_CATALOG_REFRESH_FAILED] 発注機関候補を再読み込み中です。"
                "完了してから実行してください"
            )
        refresh_error = str(getattr(self, "_agency_catalog_refresh_error", "") or "")
        if refresh_error and has_agency_selection:
            return (
                "[AGENCY_CATALOG_REFRESH_FAILED] 発注機関候補の最新性を"
                "確認できません。候補を再読み込みしてください"
            )
        invalid_agency = getattr(self, "_agency_invalid_fields", set())
        if invalid_agency:
            field = next(item for item in self._AGENCY_FIELDS if item in invalid_agency)
            value = self._agency_variable(field).get().strip()
            return (
                "[AGENCY_SELECTION_REMOVED] "
                f"{self._AGENCY_FIELD_LABELS[field]}「{value}」は最新の発注機関候補に"
                "ありません。候補から選択し直してください"
            )

        invalid_dynamic = set(getattr(self, "_dynamic_invalid_fields", set()))
        if self.place_search_type_var.get() != "list":
            # 文字列検索時の地域リスト値は送信されない。値自体は
            # 画面に保持しつつ、非使用条件の候補外警告で実行を止めない。
            invalid_dynamic.difference_update(
                {"place_chihou", "place_todofuken", "place_shichouson"}
            )
        active_target = getattr(self, "_active_search_target", SearchTarget.KOJI_KEIKA)
        if active_target == SearchTarget.GYOMU_KEIKA:
            invalid_dynamic.difference_update({"koji_shubetsu", "koji_gyoushu"})
        else:
            invalid_dynamic.discard("gyomu_kubun")
        if invalid_dynamic:
            field = next(
                item for item in self._DYNAMIC_OPTION_FIELDS if item in invalid_dynamic
            )
            value = self._dynamic_option_variable(field).get().strip()
            label = self._DYNAMIC_OPTION_LABELS[field]
            return (
                f"{label}「{value}」は最新の候補にありません。"
                "候補から選択し直してください"
            )

        hierarchy = (
            ("大分類", "hachu_daibunrui", self.hachu_daibunrui_var),
            ("中分類", "hachu_chubunrui", self.hachu_chubunrui_var),
            ("小分類", "hachu_shoubunrui", self.hachu_shoubunrui_var),
            ("細分類", "hachu_saibunrui", self.hachu_saibunrui_var),
        )
        parent_selected = True
        for label, field, variable in hierarchy:
            value = variable.get().strip()
            if value and not parent_selected:
                return f"{label}の上位分類を選択してください"
            if value:
                options = self._cached_agency_options(
                    self._current_agency_parent_labels(field)
                )
                if options is None:
                    return (
                        f"{label}「{value}」の最新候補を確認できません。"
                        "候補を再読み込みしてください"
                    )
                if not any(option.label == value for option in options):
                    return (
                        f"{label}「{value}」は現在の候補にありません。"
                        "選択し直してください"
                    )
            parent_selected = parent_selected and bool(value)

        category_fields = (
            (("業務区分", "gyomu_kubun", self.gyomu_kubun_var),)
            if active_target == SearchTarget.GYOMU_KEIKA
            else (
                ("工事種別", "koji_shubetsu", self.koji_shubetsu_var),
                ("工事の業種", "koji_gyoushu", self.koji_gyoushu_var),
            )
        )
        for label, field, variable in category_fields:
            value = variable.get().strip()
            if value and not self._search_option_model.options(field):
                return (
                    f"{label}「{value}」の最新候補を確認できません。"
                    "候補を再読み込みしてください"
                )
            if value and not self._search_option_model.contains(field, value):
                return (
                    f"{label}「{value}」は現在の候補にありません。選択し直してください"
                )

        if self.place_search_type_var.get() == "list":
            place_parent_selected = True
            for label, field, variable in (
                ("地方", "place_chihou", self.place_chihou_var),
                (
                    "都道府県",
                    "place_todofuken",
                    self.place_todofuken_var,
                ),
                (
                    "市区町村",
                    "place_shichouson",
                    self.place_shichouson_var,
                ),
            ):
                value = variable.get().strip()
                if value and not place_parent_selected:
                    return f"{label}の上位地域を選択してください"
                if value:
                    options = self._search_option_model.options(field)
                    if not options:
                        return (
                            f"{label}「{value}」の最新候補を確認できません。"
                            "候補を再読み込みしてください"
                        )
                    if not self._search_option_model.contains(field, value):
                        return (
                            f"{label}「{value}」は現在の候補にありません。"
                            "選択し直してください"
                        )
                place_parent_selected = place_parent_selected and bool(value)
        return ""

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

    def _download_thread(
        self,
        config_snapshot: AppConfig,
        window_was_visible: bool,
        redownload_policy: RedownloadPolicy,
        expected_condition_summary: str = "",
    ):
        """ダウンロードスレッド"""
        try:
            actual_condition_summary = format_search_conditions(
                config_snapshot.search_conditions
            )
            if (
                expected_condition_summary
                and actual_condition_summary != expected_condition_summary
            ):
                raise ValueError(
                    "検索条件スナップショットが開始前に変更されたため、"
                    "安全のため実行を中止しました"
                )
            if self.download_callback:
                self.download_callback(
                    self,
                    config_snapshot,
                    window_was_visible,
                    redownload_policy,
                )
        except Exception as e:
            if not self.cancel_flag.is_set():
                self.logger.error(f"ダウンロードエラー: {str(e)}")
                self.event_handler.call_soon(
                    self.show_message, f"ダウンロードエラー: {str(e)}", "error"
                )
        finally:
            # 通常イベントキューが満杯でも、実行ボタンと一回限り設定は
            # 必ず元へ戻す。
            self.event_handler.call_soon_critical(self._reset_download_ui)

    def _reset_download_ui(self):
        """ダウンロードUIをリセット"""
        self.download_thread = None
        self._refresh_download_button_state()
        self.btn_cancel.config(state="disabled")
        self.redownload_existing_var.set(False)
        self.chk_redownload_existing.config(state="normal")
        if self._last_run_outcome is None:
            fallback = (
                RunOutcome.CANCELLED if self.cancel_flag.is_set() else RunOutcome.FAILED
            )
            self.set_run_outcome(fallback)

    def set_run_outcome(
        self,
        outcome: RunOutcome,
        current: int = 0,
        total: int = 0,
        all_reused: bool = False,
    ):
        """RunOutcomeをGUIの終端表示へ一対一で反映する。"""
        if get_ident() != self._ui_thread_id:
            self.event_handler.call_soon(
                self.set_run_outcome,
                outcome,
                current,
                total,
                all_reused,
            )
            return
        try:
            normalized = (
                outcome if isinstance(outcome, RunOutcome) else RunOutcome(outcome)
            )
        except ValueError:
            normalized = RunOutcome.FAILED
        self._last_run_outcome = normalized
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        labels = {
            RunOutcome.SUCCESS: "成功",
            RunOutcome.PARTIAL: "一部失敗",
            RunOutcome.FAILED: "失敗",
            RunOutcome.CANCELLED: "キャンセル",
            RunOutcome.NO_MATCH: "該当なし",
        }
        if normalized == RunOutcome.SUCCESS and all_reused:
            labels[RunOutcome.SUCCESS] = f"完了（{total}件すべて保存済み）"
        if total > 0:
            self.progress_bar["value"] = min(100.0, max(0.0, (current / total) * 100))
        elif normalized in {RunOutcome.SUCCESS, RunOutcome.PARTIAL}:
            self.progress_bar["value"] = 100
        self.progress_var.set(labels[normalized])

    def update_progress(self, current: int, total: int, filename: str = ""):
        """進捗を更新"""
        if get_ident() != self._ui_thread_id:
            self.event_handler.call_soon(self.update_progress, current, total, filename)
            return
        if total > 0:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            percentage = (current / total) * 100
            self.progress_bar["value"] = percentage
            self.progress_var.set(f"{current}/{total} ({percentage:.1f}%) - {filename}")

    def _set_search_progress_mode(self, message: str):
        """総数が未確定の検索段階を不定プログレスで表示する。"""
        self.progress_bar.stop()
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start(12)
        self.progress_var.set(message)

    def update_search_progress(self, metadata: dict):
        """検索ページ・案件・候補数をメインスレッドで表示する。"""
        if get_ident() != self._ui_thread_id:
            self.event_handler.call_soon(self.update_search_progress, metadata)
            return
        self._consume_search_metadata(metadata)
        search_phase = str(metadata.get("search_phase", "")).lower()
        if search_phase in {
            "summary",
            "complete",
            "completed",
            "finished",
            "plan",
        }:
            summary = metadata.get("search_summary")
            complete = bool(
                payload_value(
                    summary,
                    "complete",
                    "is_complete",
                    "final",
                    default=(search_phase != "summary"),
                )
            )
            self._set_search_progress_mode(
                "検索解析完了。ダウンロード対象を確認しています..."
                if complete
                else "検索結果の途中集計を更新しています..."
            )
            return
        page = int(metadata.get("page", 0) or 0)
        row = int(metadata.get("row", 0) or 0)
        rows_on_page = int(metadata.get("rows_on_page", 0) or 0)
        projects = int(metadata.get("projects_scanned", 0) or 0)
        files = int(metadata.get("files_discovered", 0) or 0)
        if metadata.get("search_phase") == "detail" and rows_on_page:
            detail = f"{row}/{rows_on_page}案件"
        else:
            detail = f"{rows_on_page}案件"
        self._set_search_progress_mode(
            f"検索中: {page}ページ目・{detail}・累計{projects}案件・候補{files}件"
        )

    def _begin_search_summary(self):
        """新しい手動実行に備えて前回の案件内訳を切り替える。"""
        if get_ident() != self._ui_thread_id:
            self.event_handler.call_soon(self._begin_search_summary)
            return
        self._search_summary = None
        self._active_search_generation = None
        self._project_document_projects = ()
        self._project_document_projects_by_id = {}
        if hasattr(self, "summary_var"):
            self.summary_var.set("検索集計：解析中...")
        if hasattr(self, "btn_project_documents"):
            self.btn_project_documents.config(state="disabled")
        dialog = getattr(self, "_project_documents_dialog", None)
        if dialog is not None and dialog.is_alive():
            dialog.update_data((), "検索集計：解析中...")

    def _consume_search_metadata(self, metadata: dict):
        """検索イベントに含まれる集計と工事内訳を取り込む。"""
        if not metadata:
            return
        generation = metadata.get("generation")
        if generation not in (None, 0):
            active_generation = getattr(self, "_active_search_generation", None)
            if active_generation not in (None, generation):
                self._project_document_projects = ()
                self._project_document_projects_by_id = {}
            self._active_search_generation = generation
        summary = metadata.get("search_summary")
        projects = metadata.get("projects")
        if projects is None:
            projects = metadata.get("project_summaries")
        if projects is None and summary is not None:
            projects = payload_value(
                summary, "projects", "project_summaries", default=None
            )

        summary_keys = {
            "projects_matched",
            "matched_projects",
            "public_documents",
            "expired_only_projects",
            "target_documents",
        }
        if summary is None and summary_keys.intersection(metadata):
            summary = metadata
        project_deltas = metadata.get("project_deltas")
        if project_deltas is None:
            project_delta = metadata.get("project_delta")
            project_deltas = None if project_delta is None else [project_delta]
        if summary is None and projects is None and not project_deltas:
            return

        search_phase = str(metadata.get("search_phase", "")).lower()
        complete = metadata.get("summary_complete")
        if complete is None and search_phase in {
            "complete",
            "completed",
            "finished",
            "plan",
        }:
            complete = True
        self.update_search_summary(
            summary,
            projects,
            complete=complete,
            project_deltas=project_deltas,
            snapshot_kind=metadata.get("snapshot_kind"),
        )

    def update_search_summary(
        self,
        summary,
        projects=None,
        *,
        complete: Optional[bool] = None,
        project_deltas=None,
        snapshot_kind: Optional[str] = None,
    ):
        """検索集計と工事別文書一覧をメインスレッドで更新する。"""
        if get_ident() != self._ui_thread_id:
            if project_deltas is None and snapshot_kind is None:
                self.event_handler.call_soon(
                    self.update_search_summary,
                    summary,
                    projects,
                    complete=complete,
                )
            else:
                self.event_handler.call_soon(
                    self.update_search_summary,
                    summary,
                    projects,
                    complete=complete,
                    project_deltas=project_deltas,
                    snapshot_kind=snapshot_kind,
                )
            return

        if summary is not None:
            self._search_summary = summary
        if projects is not None:
            normalised = normalise_projects(projects)
            self._project_document_projects = normalised
            self._project_document_projects_by_id = {
                project.project_id: project for project in normalised
            }
        normalised_deltas: tuple[ProjectView, ...] = ()
        if project_deltas:
            normalised_deltas = tuple(
                normalise_project(project, index)
                for index, project in enumerate(project_deltas)
            )
            if not hasattr(self, "_project_document_projects_by_id"):
                self._project_document_projects_by_id = {
                    project.project_id: project
                    for project in getattr(self, "_project_document_projects", ())
                }
            for project in normalised_deltas:
                self._project_document_projects_by_id[project.project_id] = project
        elif not hasattr(self, "_project_document_projects"):
            self._project_document_projects = ()

        summary_payload = getattr(self, "_search_summary", None)
        project_views = self._project_document_projects if projects is not None else ()
        summary_text = format_search_summary(
            summary_payload,
            project_views,
            complete=complete,
        )
        if hasattr(self, "summary_var"):
            self.summary_var.set(summary_text)
        if hasattr(self, "btn_project_documents"):
            self.btn_project_documents.config(
                state=(
                    "normal"
                    if (
                        self._project_document_projects_by_id
                        or self._project_document_projects
                    )
                    else "disabled"
                )
            )

        dialog = getattr(self, "_project_documents_dialog", None)
        if dialog is not None and dialog.is_alive():
            if projects is not None or str(snapshot_kind or "").lower() in {
                "page",
                "final",
                "full",
            }:
                dialog.update_data(self._current_project_document_views(), summary_text)
            elif normalised_deltas:
                dialog.apply_deltas(normalised_deltas, summary_text)

    def _current_project_document_views(self) -> tuple[ProjectView, ...]:
        mapping = getattr(self, "_project_document_projects_by_id", {})
        if mapping:
            return tuple(mapping.values())
        return tuple(getattr(self, "_project_document_projects", ()))

    def show_project_documents(self):
        """工事ごとの公開文書内訳を非モーダル画面で表示する。"""
        projects = self._current_project_document_views()
        if not projects:
            messagebox.showinfo(
                "案件・文書内訳",
                "表示できる案件情報はまだありません。",
            )
            return
        summary_text = self.summary_var.get() if hasattr(self, "summary_var") else ""
        dialog = getattr(self, "_project_documents_dialog", None)
        if dialog is None or not dialog.is_alive():
            dialog = ProjectDocumentsDialog(
                self.root,
                projects,
                summary_text,
                on_close=self._on_project_documents_dialog_closed,
            )
            self._project_documents_dialog = dialog
        else:
            dialog.update_data(projects, summary_text)
        dialog.show()

    def _on_project_documents_dialog_closed(self) -> None:
        self._project_documents_dialog = None

    def show_message(self, message: str, level: str = "info"):
        """メッセージを表示"""
        if get_ident() != self._ui_thread_id:
            self.event_handler.call_soon(self.show_message, message, level)
            return
        text = f"[{level.upper()}] {message}\n"
        self.log_text.insert(tk.END, text)
        entries = getattr(self, "_gui_log_entries", None)
        if entries is None:
            entries = deque()
            self._gui_log_entries = entries
            self._gui_log_lines = 0
            self._gui_log_bytes = 0
        line_count = max(1, text.count("\n"))
        byte_count = len(text.encode("utf-8", errors="replace"))
        entries.append((line_count, byte_count))
        self._gui_log_lines += line_count
        self._gui_log_bytes += byte_count
        self._trim_gui_log()
        self.log_text.see(tk.END)

    def _trim_gui_log(self) -> None:
        """画面ログだけを上限内へ戻し、完全ログはファイルへ残す。"""
        if (
            self._gui_log_lines <= self._GUI_LOG_MAX_LINES
            and self._gui_log_bytes <= self._GUI_LOG_MAX_BYTES
        ):
            return
        removed_lines = 0
        while self._gui_log_entries and (
            self._gui_log_lines > self._GUI_LOG_TRIM_LINES
            or self._gui_log_bytes > self._GUI_LOG_TRIM_BYTES
        ):
            lines, byte_count = self._gui_log_entries.popleft()
            removed_lines += lines
            self._gui_log_lines -= lines
            self._gui_log_bytes -= byte_count
        if removed_lines:
            self.log_text.delete("1.0", f"{removed_lines + 1}.0")

    def show_pdf_conversion_history(self) -> None:
        """日別監査ログから直近のPDF変換結果を表示する。"""

        current = self._pdf_conversion_history_dialog
        if current is not None:
            try:
                if current.winfo_exists():
                    current.lift()
                    current.focus_set()
                    return
            except tk.TclError:
                pass
        dialog = PdfConversionHistoryDialog(
            self.root,
            get_logs_path().parent,
        )
        self._pdf_conversion_history_dialog = dialog.window

        def close_dialog() -> None:
            self._pdf_conversion_history_dialog = None
            dialog.window.destroy()

        dialog.window.protocol("WM_DELETE_WINDOW", close_dialog)

    def on_clear_log(self):
        """ログをクリア"""
        self.log_text.delete(1.0, tk.END)
        self._gui_log_entries.clear()
        self._gui_log_lines = 0
        self._gui_log_bytes = 0
        self.show_message("ログをクリアしました", "info")

    def on_schedule_settings_open(self):
        """設定画面の定期実行タブを直接開く。"""
        self.on_settings_open(initial_tab="schedule")

    def on_settings_open(self, initial_tab: str = "basic"):
        """設定画面を開く"""
        from ..gui.settings_dialog import SettingsDialog

        if bool(getattr(self, "_installation_relocation_pending", False)):
            messagebox.showwarning(
                "配置フォルダーの確認",
                "配置フォルダーの付け替えが完了するまで設定を保存できません。",
                parent=self.root,
            )
            return

        # 未保存の検索条件も定期実行タブの要約へ渡す。
        try:
            current_config = deepcopy(self.get_config_from_ui())
        except (TypeError, ValueError) as exc:
            messagebox.showerror(
                "検索条件エラー",
                f"現在の検索条件を設定画面へ引き継げません。\n{exc}",
                parent=self.root,
            )
            return
        # 設定画面は同じScheduleServiceで状態を一括照会する。モーダル表示中は
        # Main側のpollerを止め、同じWindowsタスクを二重照会しない。
        self._suspend_schedule_status_poll()
        try:
            dialog = SettingsDialog(
                self.root,
                current_config,
                self.config_manager,
                self.logger,
                schedule_service=getattr(self, "schedule_service", None),
                reclassification_service=getattr(
                    self, "reclassification_service", None
                ),
                reclassification_block_reason_provider=(
                    self._reclassification_block_reason
                ),
                current_config_provider=self._current_schedule_registration_config,
                schedule_config_validator=(
                    self._validate_schedule_profile_dynamic_config
                ),
                search_options_provider=self._schedule_search_options_snapshot,
                search_option_loader=self._load_schedule_search_options,
                search_options_reloader=self._reload_agency_options_for_schedule,
                option_load_coordinator=self._option_load_coordinator,
                initial_tab=initial_tab,
            )
            result = dialog.show()
        finally:
            self._resume_schedule_status_poll()

        if result:
            # 設定が保存された場合、メインウィンドウの設定を更新
            self.config = result
            self.load_config_to_ui()
            if (
                getattr(self, "schedule_service", None) is None
                and self.schedule_change_callback
            ):
                self.schedule_change_callback(deepcopy(result.schedule))
            # finallyで再開時の照会を予約済み。

    def load_config_to_ui(self):
        """設定をUIに反映"""
        self._refresh_manual_storage_preview()
        # 検索条件をUIに反映
        search_conditions = self.config.search_conditions
        target = search_conditions.target
        self._active_search_target = target
        profile = get_search_profile(target)
        self._search_url = profile.search_url
        self.search_target_var.set(profile.display_label)
        self._target_drafts[target.value] = deepcopy(search_conditions)
        self._refresh_target_labels()
        self._render_contract_options(search_conditions.contract_types)
        self._ensure_dynamic_option_state()
        self._search_option_model.set_initial(search_conditions)

        # 発注機関（リスト検索）
        self.hachu_daibunrui_var.set(search_conditions.hachu_daibunrui)
        self.hachu_chubunrui_var.set(search_conditions.hachu_chubunrui)
        self.hachu_shoubunrui_var.set(search_conditions.hachu_shoubunrui)
        self.hachu_saibunrui_var.set(search_conditions.hachu_saibunrui)

        # 複数発注機関の旧値は設定モデル内だけで保持する。
        if search_conditions.hachu_multi:
            self.logger.warning(
                "複数発注機関の旧設定は現在サポートされないため使用しません"
            )

        # 案件名
        self.koji_name_var.set(search_conditions.effective_project_name)

        # 動的候補の順番ではなく表示名で復元する。不明値も保持し、
        # 次の候補照合で「再選択が必要」と判定する。
        self._restore_dynamic_option_value(
            "place_chihou", search_conditions.place_chihou
        )
        self._restore_dynamic_option_value(
            "place_todofuken", search_conditions.place_todofuken
        )
        self._restore_dynamic_option_value(
            "place_shichouson", search_conditions.place_shichouson
        )
        self.place_text_var.set(search_conditions.place_text)
        self.place_search_type_var.set(search_conditions.place_search_type)
        self._update_place_search_mode()

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
        self.koukoku_date_end_var.set(search_conditions.koukoku_date_end or "")

        self.kaisatsu_date_type_var.set(search_conditions.kaisatsu_date_type)
        self.kaisatsu_date_start_var.set(search_conditions.kaisatsu_date_start or "")
        self.kaisatsu_date_end_var.set(search_conditions.kaisatsu_date_end or "")

        self.keiyaku_date_type_var.set(search_conditions.keiyaku_date_type)
        self.keiyaku_date_start_var.set(search_conditions.keiyaku_date_start or "")
        self.keiyaku_date_end_var.set(search_conditions.keiyaku_date_end or "")

        # 工事種別、工事の業種
        self._restore_dynamic_option_value(
            "koji_shubetsu", search_conditions.koji_shubetsu
        )
        self._restore_dynamic_option_value(
            "koji_gyoushu", search_conditions.koji_gyoushu
        )
        self._restore_dynamic_option_value("gyomu_kubun", search_conditions.gyomu_kubun)

        # 価格
        self.yotei_price_min_var.set(
            str(search_conditions.yotei_price_min)
            if search_conditions.yotei_price_min is not None
            else ""
        )
        self.yotei_price_max_var.set(
            str(search_conditions.yotei_price_max)
            if search_conditions.yotei_price_max is not None
            else ""
        )
        self.rakusatsu_price_min_var.set(
            str(search_conditions.rakusatsu_price_min)
            if search_conditions.rakusatsu_price_min is not None
            else ""
        )
        self.rakusatsu_price_max_var.set(
            str(search_conditions.rakusatsu_price_max)
            if search_conditions.rakusatsu_price_max is not None
            else ""
        )

        # 落札者名
        self.rakusatsu_name_var.set(search_conditions.rakusatsu_name)

        # オプション
        self.denshi_var.set(search_conditions.denshi)
        self.koukai_var.set(search_conditions.koukai)

        # 表示件数
        self.display_count_var.set(str(search_conditions.display_count))
        self._request_agency_options("hachu_daibunrui", ())
        if search_conditions.place_chihou:
            self.on_place_chihou_changed()

    def _refresh_manual_storage_preview(self) -> None:
        """現在の通常ダウンロード解決先をメイン画面へ表示する。"""

        variable = getattr(self, "manual_storage_var", None)
        if variable is None:
            return
        try:
            path = format_storage_preview(self.config, RunKind.MANUAL)
            variable.set(f"通常ダウンロード先: {path}")
        except (TypeError, ValueError) as exc:
            variable.set(f"通常ダウンロード先を確認してください: {exc}")

    def get_config_from_ui(self) -> AppConfig:
        """UIから設定を取得"""
        # 検索条件を取得
        # 画面入力は実行用コピーへ反映し、保存済み設定（特に旧設定値）を
        # 手動実行だけで破壊しない。
        search_conditions = deepcopy(self.config.search_conditions)
        target = self._target_from_display(self.search_target_var.get())
        profile = get_search_profile(target)
        search_conditions.search_target = target.value

        # 発注機関（リスト検索）
        search_conditions.hachu_daibunrui = self.hachu_daibunrui_var.get()
        search_conditions.hachu_chubunrui = self.hachu_chubunrui_var.get()
        search_conditions.hachu_shoubunrui = self.hachu_shoubunrui_var.get()
        search_conditions.hachu_saibunrui = self.hachu_saibunrui_var.get()

        # 発注機関（複数選択検索）
        search_conditions.hachu_multi = []

        # 共通案件名。koji_nameは工事互換別名としてのみ保存する。
        search_conditions.project_name = self.koji_name_var.get()
        search_conditions.koji_name = (
            self.koji_name_var.get() if target == SearchTarget.KOJI_KEIKA else ""
        )

        # 工事場所
        search_conditions.place_chihou = self.place_chihou_var.get()
        search_conditions.place_todofuken = self.place_todofuken_var.get()
        search_conditions.place_shichouson = self.place_shichouson_var.get()
        search_conditions.place_text = self.place_text_var.get()
        search_conditions.place_search_type = self.place_search_type_var.get()

        # 入札契約方式
        search_conditions.contract_types = [
            ct for ct, var in self.contract_type_vars.items() if var.get()
        ]

        # 最終更新日
        search_conditions.update_date_type = self.update_date_type_var.get()
        update_days_text = self.update_date_days_var.get().strip()
        if update_days_text:
            try:
                search_conditions.update_date_days = int(update_days_text)
            except ValueError as exc:
                raise ValueError(
                    "最終更新日の過去日数は整数で指定してください"
                ) from exc
        else:
            search_conditions.update_date_days = None

        # 公告日、開札日、契約日
        search_conditions.koukoku_date_type = self.koukoku_date_type_var.get()
        search_conditions.koukoku_date_start = self.koukoku_date_start_var.get() or None
        search_conditions.koukoku_date_end = self.koukoku_date_end_var.get() or None

        search_conditions.kaisatsu_date_type = self.kaisatsu_date_type_var.get()
        search_conditions.kaisatsu_date_start = (
            self.kaisatsu_date_start_var.get() or None
        )
        search_conditions.kaisatsu_date_end = self.kaisatsu_date_end_var.get() or None

        search_conditions.keiyaku_date_type = self.keiyaku_date_type_var.get()
        search_conditions.keiyaku_date_start = self.keiyaku_date_start_var.get() or None
        search_conditions.keiyaku_date_end = self.keiyaku_date_end_var.get() or None

        # 工事種別、工事の業種（単一選択）
        search_conditions.koji_shubetsu = self.koji_shubetsu_var.get()
        search_conditions.koji_gyoushu = self.koji_gyoushu_var.get()
        search_conditions.gyomu_kubun = self.gyomu_kubun_var.get()
        if target == SearchTarget.GYOMU_KEIKA:
            search_conditions.koji_shubetsu = ""
            search_conditions.koji_gyoushu = ""
        else:
            search_conditions.gyomu_kubun = ""

        # 価格
        def parse_optional_int(value: str, label: str) -> Optional[int]:
            text = value.strip()
            if not text:
                return None
            try:
                return int(text)
            except ValueError as exc:
                raise ValueError(f"{label}は整数で指定してください") from exc

        search_conditions.yotei_price_min = parse_optional_int(
            self.yotei_price_min_var.get(), "予定価格の下限"
        )
        search_conditions.yotei_price_max = parse_optional_int(
            self.yotei_price_max_var.get(), "予定価格の上限"
        )
        search_conditions.rakusatsu_price_min = parse_optional_int(
            self.rakusatsu_price_min_var.get(), "落札価格の下限"
        )
        search_conditions.rakusatsu_price_max = parse_optional_int(
            self.rakusatsu_price_max_var.get(), "落札価格の上限"
        )

        # 落札者名
        search_conditions.rakusatsu_name = self.rakusatsu_name_var.get()

        # オプション
        search_conditions.denshi = self.denshi_var.get()
        search_conditions.koukai = self.koukai_var.get()

        # 表示件数
        try:
            search_conditions.display_count = int(self.display_count_var.get())
        except ValueError as exc:
            raise ValueError("一覧画面の表示件数は整数で指定してください") from exc

        runtime_config = deepcopy(self.config)
        runtime_config.search_conditions = search_conditions
        runtime_config.target_urls = [profile.search_url]
        self._target_drafts[target.value] = deepcopy(search_conditions)
        return runtime_config
