# -*- coding: utf-8 -*-

"""設定ダイアログクラス"""

import tkinter as tk
import tkinter.font
import inspect
from queue import Empty, Queue
from threading import Thread
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import date, datetime
from typing import Callable, Optional, Tuple, List
from copy import deepcopy
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
from .schedule_editor_dialog import (
    ScheduleEditorDialog,
    format_schedule_notification_policy,
    normalise_schedule_notification_policy,
)
from .option_load_coordinator import OptionLoadCoordinator
from .search_conditions_form import bind_search_comboboxes_to_canvas
from .schedule_management import (
    ScheduleServiceAdapter,
    ScheduleTreeRow,
    ScheduleView,
    aggregate_schedule_counts,
    duplicate_condition_names,
    format_storage_preview,
    history_display_name,
    reconcile_schedule_tree,
    schedule_value,
    trigger_kind_display,
)
from .reclassification_dialog import ReclassificationDialog
from .window_layout import WrapButtonBar, fit_to_screen, make_vertical_scroll_area
from ..storage.layout import RunKind
from ..core.search_profiles import get_search_profile


def _display_value(value: object, fallback: str = "指定なし") -> str:
    """設定値を読み取り専用の日本語要約へ整形する。"""
    if value is None or value == "" or value == []:
        return fallback
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(item) for item in value) or fallback
    if isinstance(value, bool):
        return "対象のみ" if value else "指定なし"
    return str(value)


def _format_schedule_result(value: object) -> str:
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


_SCHEDULE_REASON_MESSAGES = {
    "SUCCESS": "成功",
    "NO_MATCH": "該当なし",
    "PARTIAL_FAILURE": "一部のファイル取得に失敗",
    "RUN_FAILED": "定期実行に失敗",
    "ALREADY_RUNNING": "他の処理を実行中",
    "QUEUE_TIMEOUT": "キュー待機時間超過",
    "RUN_TIMEOUT": "実行時間超過",
    "CANCELLED": "キャンセル",
    "CONFIG_INVALID": "設定が不正",
    "RATE_LIMIT": "アクセス制限",
    "HTTP_STATUS": "HTTP応答エラー",
    "HTTP_4XX": "HTTPクライアントエラー",
    "HTTP_5XX": "サーバーエラー",
    "NETWORK_TIMEOUT": "通信タイムアウト",
    "NETWORK_ERROR": "通信エラー",
    "CONTENT_LENGTH_MISSING": "ファイルサイズ情報なし",
    "CONTENT_LENGTH_INVALID": "ファイルサイズ情報が不正",
    "CONTENT_LENGTH_MISMATCH": "ファイルサイズが応答と不一致",
    "CONTENT_TYPE_MISMATCH": "ファイル形式が応答と不一致",
    "UNEXPECTED_HTML": "想定外のHTML応答",
    "HTML_PARSE_FAILED": "HTML解析に失敗",
    "HTML_STRUCTURE_INVALID": "HTML構造が不正",
    "PROJECT_NAME_MISMATCH": "工事名が不一致",
    "EXTERNAL_RESOURCE_BLOCKED": "外部リソースを遮断",
    "PAYLOAD_SIGNATURE_MISMATCH": "ファイル署名が不一致",
    "OOXML_INVALID": "Officeファイル構造が不正",
    "EDGE_NOT_FOUND": "Microsoft Edgeが見つからない",
    "EDGE_START_FAILED": "Microsoft Edgeを起動できない",
    "EDGE_SUPERVISION_UNAVAILABLE": "Edgeのプロセス監視を利用できない",
    "EDGE_PROCESS_CRASH": "Edgeのプロセスが異常終了",
    "EDGE_GPU_PROCESS_CRASH": "EdgeのGPUプロセスが異常終了",
    "EDGE_OUTPUT_NOT_PRODUCED": "EdgeがPDFを生成しないまま終了",
    "CONVERSION_TIMEOUT": "PDF変換が時間超過",
    "CONVERSION_EXIT_ERROR": "PDF変換が異常終了",
    "OUTPUT_MISSING": "変換結果が見つからない",
    "OUTPUT_EMPTY": "変換結果が空",
    "OUTPUT_INVALID_PDF": "変換結果がPDFではない",
    "PDF_INTERNAL_RENDER_FAILED": "内蔵PDF生成に失敗",
    "PDF_CONTENT_VALIDATION_FAILED": "生成PDFの内容検証に失敗",
    "PDF_ALL_RENDERERS_FAILED": "すべてのPDF生成方式に失敗",
    "PDF_RECOVERY_ARTIFACT_STORED": "再変換用データを保管",
    "SAVE_FAILED": "ファイル保存に失敗",
    "TEMP_CLEANUP_FAILED": "一時データの後処理に失敗",
    "HISTORY_INVALID": "保存履歴または既存ファイルが不正",
    "UNKNOWN": "原因不明のエラー",
}


def format_schedule_reason(value: object) -> str:
    """安定した理由コードを、日本語理由を伴う表示へ変換する。"""
    raw = getattr(value, "value", value)
    code = str(raw or "").strip().upper()
    if not code:
        return "-"
    reason = _SCHEDULE_REASON_MESSAGES.get(code, "実行結果の詳細はログを確認")
    return f"{reason} [{code}]"


def format_schedule_condition_summary(config: AppConfig) -> str:
    """定期実行へ固定する検索条件を、機密値を増やさず要約する。"""
    search = config.search_conditions
    profile = get_search_profile(search.target)
    organisation = " / ".join(
        value
        for value in (
            search.hachu_daibunrui,
            search.hachu_chubunrui,
            search.hachu_shoubunrui,
            search.hachu_saibunrui,
        )
        if value
    )
    if search.place_search_type == "text":
        place = search.place_text
    else:
        place = " / ".join(
            value
            for value in (
                search.place_chihou,
                search.place_todofuken,
                search.place_shichouson,
            )
            if value
        )

    date_parts: list[str] = []
    if search.update_date_type == "past" and search.update_date_days:
        date_parts.append(f"最終更新: 過去{search.update_date_days}日")
    for label, mode, start, end in (
        (
            "公告日",
            search.koukoku_date_type,
            search.koukoku_date_start,
            search.koukoku_date_end,
        ),
        (
            "開札日",
            search.kaisatsu_date_type,
            search.kaisatsu_date_start,
            search.kaisatsu_date_end,
        ),
        (
            "契約日",
            search.keiyaku_date_type,
            search.keiyaku_date_start,
            search.keiyaku_date_end,
        ),
    ):
        if mode == "range":
            date_parts.append(f"{label}: {start or '指定なし'} ～ {end or '指定なし'}")

    document_date_range = config.download_conditions.date_range or {}
    document_dates = (
        f"{document_date_range.get('start') or '指定なし'} ～ "
        f"{document_date_range.get('end') or '指定なし'}"
        if isinstance(document_date_range, dict)
        else _display_value(document_date_range)
    )
    legacy_storage = int(config.save_paths.layout_version or 2) < 3
    storage_key = (
        "旧構成（固定キーなし）"
        if legacy_storage
        else config.save_paths.schedule_storage_key or "登録時に自動割当"
    )
    storage_folder = (
        "旧構成（データルート直下）"
        if legacy_storage
        else config.save_paths.schedule_storage_folder or "登録時に自動割当"
    )

    return "\n".join(
        (
            f"検索対象: {profile.display_label}",
            f"発注機関: {_display_value(organisation)}",
            f"{profile.project_label}: {_display_value(search.effective_project_name)}",
            f"場所: {_display_value(place)}",
            (
                "工事種別: "
                f"{_display_value(search.koji_shubetsu)} / "
                f"業種: {_display_value(search.koji_gyoushu)}"
                if profile.target.value == "koji_keika"
                else f"業務区分: {_display_value(search.gyomu_kubun)}"
            ),
            f"日付条件: {_display_value(date_parts)}",
            f"公開条件: {'公開中のみ' if search.koukai else '指定なし'}",
            f"文書種別: {_display_value(config.download_conditions.file_types)}",
            f"キーワード: {_display_value(config.download_conditions.keywords)}",
            f"文書日付範囲: {document_dates}",
            f"データルート: {_display_value(config.save_paths.local)}",
            f"保存先: {_display_value(config.save_paths.local)}（旧表示互換）",
            f"定期実行の保存予定: {format_storage_preview(config, RunKind.SCHEDULED)}",
            f"固定保存キー: {storage_key}",
            f"固定保存フォルダー: {storage_folder}",
            f"命名規則: {_display_value(config.naming_rule)}",
        )
    )


def _record_value(record: object, *names: str, default: object = None) -> object:
    """履歴のdataclassと旧dict形式を同じように扱う。"""
    for name in names:
        if isinstance(record, dict) and name in record:
            return record[name]
        value = getattr(record, name, None)
        if value is not None:
            return value
    return default


def _format_datetime(value: object) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, (datetime, date)):
        return (
            value.astimezone().strftime("%Y/%m/%d %H:%M")
            if isinstance(value, datetime) and value.tzinfo
            else value.strftime("%Y/%m/%d %H:%M")
        )
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return text


class SettingsDialog:
    """設定ダイアログクラス"""

    def __init__(
        self,
        parent: tk.Tk,
        config: AppConfig,
        config_manager: ConfigManager,
        logger: Optional[Logger] = None,
        schedule_service: Optional[object] = None,
        current_config_provider: Optional[Callable[[], AppConfig]] = None,
        schedule_config_validator: Optional[
            Callable[[AppConfig], tuple[bool, list[str]]]
        ] = None,
        search_options_provider: Optional[Callable[[], dict[str, tuple]]] = None,
        search_option_loader: Optional[Callable[..., list[object]]] = None,
        search_options_reloader: Optional[Callable[[], None]] = None,
        option_load_coordinator: Optional[OptionLoadCoordinator] = None,
        initial_tab: str = "basic",
        reclassification_service: Optional[object] = None,
        reclassification_block_reason_provider: Optional[Callable[[], str]] = None,
    ):
        """初期化"""
        self.parent = parent
        self.config = config
        self.config_manager = config_manager
        self.logger = logger or Logger()
        self.validator = ConfigValidator(self.logger)
        self.schedule_service = schedule_service
        self._schedule_adapter = (
            ScheduleServiceAdapter(schedule_service)
            if schedule_service is not None
            else None
        )
        self._multi_schedule_mode = bool(
            self._schedule_adapter and self._schedule_adapter.supports_multiple
        )
        self.current_config_provider = current_config_provider
        self.schedule_config_validator = schedule_config_validator
        self.search_options_provider = search_options_provider
        self.search_option_loader = search_option_loader
        self.search_options_reloader = search_options_reloader
        self.option_load_coordinator = option_load_coordinator
        self.initial_tab = initial_tab
        self.reclassification_service = reclassification_service
        self.reclassification_block_reason_provider = (
            reclassification_block_reason_provider
        )
        self._reclassification_dialog: Optional[ReclassificationDialog] = None
        self.result = None  # 保存された設定
        self._loaded_target_urls = tuple(config.target_urls)
        # 検索条件はMainWindowを唯一の編集画面とし、このダイアログでは
        # 見えない値を保存時にそのまま引き継ぐ。
        self._loaded_search_conditions = deepcopy(config.search_conditions)
        self._loaded_save_paths = deepcopy(config.save_paths)
        self._schedule_profile_config = deepcopy(config)
        self._schedule_manager_queue: Queue = Queue()
        self._schedule_manager_query_running = False
        self._schedule_manager_refresh_pending = False
        self._schedule_manager_generation = 0
        self._schedule_detail_generation = 0
        self._schedule_manager_action_running = False
        self._schedule_manager_after_id = None
        self._schedule_manager_refresh_after_id = None
        self._schedule_manager_closed = False
        self._schedule_action_retry_editor = None
        self._schedule_editor_reopen_after_refresh = None
        self._schedule_test_notification_running = False
        self._schedule_views: list[ScheduleView] = []
        self._schedule_views_by_id: dict[str, ScheduleView] = {}
        self._external_schedule_views_by_id: dict[str, ScheduleView] = {}
        self._schedule_configs_by_id: dict[str, AppConfig] = {}
        self._selected_schedule_id: Optional[str] = None
        self._selected_external_schedule_id: Optional[str] = None
        self._selected_schedule_config: Optional[AppConfig] = None
        self._schedule_selected_history: list[object] = []
        self._schedule_all_history: list[object] = []
        self._external_import_candidates: dict[str, object] = {}
        self._external_import_source_dir: Optional[str] = None

        # ダイアログを作成
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("設定")
        dialog_width = 1000 if self._multi_schedule_mode else 800
        dialog_height = 760 if self._multi_schedule_mode else 700
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_cancel)

        # 日本語フォントの設定
        self.setup_font()

        fit_to_screen(self.dialog, dialog_width, dialog_height)

        self.setup_ui()
        self.load_config_to_ui()

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
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 基本設定タブ
        basic_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(basic_tab, text="基本設定")
        self.setup_basic_tab(basic_tab)

        # 定期実行は通常設定から独立させ、登録状態と固定条件を同じ場所で扱う。
        schedule_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(schedule_tab, text="定期実行")
        if self._multi_schedule_mode:
            self._pinned_schedule_actions = WrapButtonBar(schedule_tab)
            self._pinned_schedule_actions.grid(
                row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 6)
            )
            schedule_scroll_host = ttk.Frame(schedule_tab)
            schedule_scroll_host.grid(
                row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S)
            )
            schedule_tab.columnconfigure(0, weight=1)
            schedule_tab.rowconfigure(1, weight=1)
            _, schedule_content = make_vertical_scroll_area(schedule_scroll_host)
        else:
            _, schedule_content = make_vertical_scroll_area(schedule_tab)
        self.setup_schedule_tab(schedule_content)

        # 詳細設定タブ
        advanced_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(advanced_tab, text="詳細設定")
        self.setup_advanced_tab(advanced_tab)

        if self.initial_tab == "schedule":
            self.notebook.select(schedule_tab)

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

        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, width=event.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)

        # 対象URL
        url_frame = ttk.LabelFrame(scrollable_frame, text="対象URL", padding="5")
        url_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            url_frame,
            text="通信先は公式の入札情報サービスに固定されています。",
            foreground="#666666",
        ).pack(anchor=tk.W, pady=(0, 5))

        # URLリスト
        list_frame = ttk.Frame(url_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.url_listbox = tk.Listbox(
            list_frame,
            height=2,
            state=tk.DISABLED,
            takefocus=False,
        )
        self.url_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        url_scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.url_listbox.yview
        )
        url_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.url_listbox.configure(yscrollcommand=url_scrollbar.set)

        # データルートと実行種別ごとの保存構成
        save_frame = ttk.LabelFrame(scrollable_frame, text="データルート", padding="5")
        save_frame.pack(fill=tk.X, pady=(0, 10))

        self.save_path_var = tk.StringVar()
        save_input_frame = ttk.Frame(save_frame)
        save_input_frame.pack(fill=tk.X)
        save_entry = ttk.Entry(
            save_input_frame, textvariable=self.save_path_var, width=60
        )
        save_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(save_input_frame, text="参照", command=self.on_browse_path).pack(
            side=tk.LEFT
        )
        self.storage_preview_var = tk.StringVar()
        ttk.Label(
            save_frame,
            textvariable=self.storage_preview_var,
            justify=tk.LEFT,
            foreground="#555555",
        ).pack(fill=tk.X, pady=(6, 0))
        self.save_path_var.trace_add("write", self._refresh_storage_preview)

        reclassification_frame = ttk.Frame(save_frame)
        reclassification_frame.pack(fill=tk.X, pady=(8, 0))
        self.btn_reclassify_saved = ttk.Button(
            reclassification_frame,
            text="保存済みファイルを再分類...",
            command=self._open_reclassification_dialog,
        )
        self.btn_reclassify_saved.pack(side=tk.LEFT)
        self.reclassification_status_var = tk.StringVar()
        ttk.Label(
            reclassification_frame,
            textvariable=self.reclassification_status_var,
            foreground="#666666",
        ).pack(side=tk.LEFT, padx=(8, 0))
        self._refresh_reclassification_availability()

        # ファイル命名規則
        naming_frame = ttk.LabelFrame(
            scrollable_frame, text="ファイル命名規則", padding="5"
        )
        naming_frame.pack(fill=tk.X, pady=(0, 10))

        self.naming_rule_var = tk.StringVar()
        ttk.Entry(naming_frame, textvariable=self.naming_rule_var, width=60).pack(
            fill=tk.X, pady=(0, 5)
        )
        ttk.Label(
            naming_frame,
            text=(
                "使用可能変数: {category}, {title}, {date}, {index}, {filename}, "
                "{file_type}, {daibunrui}, {chubunrui}, {shoubunrui}, "
                "{saibunrui}, {koji_name}, {document_name}, "
                "{document_updated_at}, {document_id}, {document_status}, "
                "{document_expires_at}, {document_section}"
            ),
            font=("", 8),
            wraplength=720,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        # ダウンロード条件
        conditions_frame = ttk.LabelFrame(
            scrollable_frame, text="ダウンロード条件", padding="5"
        )
        conditions_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(conditions_frame, text="ファイル種別（カンマ区切り）:").pack(
            anchor=tk.W
        )
        self.file_types_var = tk.StringVar()
        ttk.Entry(conditions_frame, textvariable=self.file_types_var, width=60).pack(
            fill=tk.X, pady=(0, 5)
        )
        ttk.Label(
            conditions_frame,
            text="例: .pdf, .xlsx, .docx",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, pady=(0, 5))

        ttk.Label(
            conditions_frame, text="キーワード（カンマ区切り、空欄は全件）:"
        ).pack(anchor=tk.W)
        self.keywords_var = tk.StringVar()
        ttk.Entry(conditions_frame, textvariable=self.keywords_var, width=60).pack(
            fill=tk.X, pady=(0, 5)
        )

        date_input_frame = ttk.Frame(conditions_frame)
        date_input_frame.pack(fill=tk.X)
        ttk.Label(date_input_frame, text="取得日:").pack(side=tk.LEFT, padx=(0, 5))
        self.download_date_start_var = tk.StringVar()
        ttk.Entry(
            date_input_frame, textvariable=self.download_date_start_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(date_input_frame, text="から").pack(side=tk.LEFT, padx=(0, 5))
        self.download_date_end_var = tk.StringVar()
        ttk.Entry(
            date_input_frame, textvariable=self.download_date_end_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(date_input_frame, text="まで（YYYY-MM-DD）").pack(side=tk.LEFT)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def setup_schedule_tab(self, parent: ttk.Frame):
        """Windowsタスクスケジューラ用の設定と診断を表示する。"""
        if getattr(self, "_multi_schedule_mode", False):
            self._setup_multi_schedule_tab(parent)
            return
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        status_frame = ttk.LabelFrame(parent, text="登録状態", padding="8")
        status_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        self.schedule_registration_var = tk.StringVar(value="状態を確認しています...")
        self.schedule_registration_label = ttk.Label(
            status_frame,
            textvariable=self.schedule_registration_var,
            justify=tk.LEFT,
        )
        self.schedule_registration_label.pack(anchor=tk.W)
        ttk.Label(
            status_frame,
            text=(
                "Windowsタスクスケジューラへ登録後はGUIを閉じても実行できます。"
                "現在のユーザーがWindowsへログオン中である必要があります。"
            ),
            foreground="gray",
            wraplength=710,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

        schedule_frame = ttk.LabelFrame(parent, text="実行設定", padding="8")
        schedule_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        schedule_frame.columnconfigure(1, weight=1)

        self.schedule_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(
            schedule_frame,
            text="定期実行を有効にする",
            variable=self.schedule_enabled_var,
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 5))

        ttk.Label(schedule_frame, text="実行間隔:").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 5), pady=2
        )
        self.schedule_interval_var = tk.StringVar()
        interval_combo = ttk.Combobox(
            schedule_frame,
            textvariable=self.schedule_interval_var,
            values=["毎日", "毎週", "毎月"],
            state="readonly",
            width=10,
        )
        interval_combo.grid(row=1, column=1, sticky=tk.W, pady=2)
        interval_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._update_schedule_fields(),
        )

        ttk.Label(schedule_frame, text="実行時刻:").grid(
            row=1, column=2, sticky=tk.W, padx=(20, 5), pady=2
        )
        self.schedule_time_var = tk.StringVar()
        ttk.Entry(schedule_frame, textvariable=self.schedule_time_var, width=8).grid(
            row=1, column=3, sticky=tk.W, pady=2
        )
        ttk.Label(schedule_frame, text="HH:MM").grid(
            row=1, column=4, sticky=tk.W, padx=(5, 0), pady=2
        )

        ttk.Label(schedule_frame, text="曜日:").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 5), pady=2
        )
        self.schedule_weekday_var = tk.StringVar()
        self.schedule_weekday_combo = ttk.Combobox(
            schedule_frame,
            textvariable=self.schedule_weekday_var,
            values=[
                "月曜日",
                "火曜日",
                "水曜日",
                "木曜日",
                "金曜日",
                "土曜日",
                "日曜日",
            ],
            state="readonly",
            width=10,
        )
        self.schedule_weekday_combo.grid(row=2, column=1, sticky=tk.W, pady=2)

        ttk.Label(schedule_frame, text="毎月の実行日:").grid(
            row=2, column=2, sticky=tk.W, padx=(20, 5), pady=2
        )
        self.schedule_day_of_month_var = tk.StringVar()
        self.schedule_day_of_month_spinbox = ttk.Spinbox(
            schedule_frame,
            textvariable=self.schedule_day_of_month_var,
            from_=1,
            to=28,
            width=5,
        )
        self.schedule_day_of_month_spinbox.grid(row=2, column=3, sticky=tk.W, pady=2)
        ttk.Label(schedule_frame, text="日（1～28）").grid(
            row=2, column=4, sticky=tk.W, padx=(5, 0), pady=2
        )

        self.schedule_start_when_available_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            schedule_frame,
            text="実行漏れ時にPC起動後1回だけ実行",
            variable=self.schedule_start_when_available_var,
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=2)
        self.schedule_wake_to_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            schedule_frame,
            text="スリープを解除して実行",
            variable=self.schedule_wake_to_run_var,
        ).grid(row=3, column=3, columnspan=2, sticky=tk.W, pady=2)

        retry_frame = ttk.Frame(schedule_frame)
        retry_frame.grid(row=4, column=0, columnspan=5, sticky=tk.W, pady=(4, 0))
        ttk.Label(retry_frame, text="一時障害の再試行:").pack(side=tk.LEFT)
        self.schedule_retry_count_var = tk.StringVar(value="2")
        ttk.Spinbox(
            retry_frame,
            textvariable=self.schedule_retry_count_var,
            from_=0,
            to=10,
            width=4,
        ).pack(side=tk.LEFT, padx=(5, 2))
        ttk.Label(retry_frame, text="回 / 間隔").pack(side=tk.LEFT)
        self.schedule_retry_interval_var = tk.StringVar(value="15")
        ttk.Spinbox(
            retry_frame,
            textvariable=self.schedule_retry_interval_var,
            from_=1,
            to=1440,
            width=5,
        ).pack(side=tk.LEFT, padx=(5, 2))
        ttk.Label(retry_frame, text="分").pack(side=tk.LEFT)
        ttk.Label(
            schedule_frame,
            text="タイムゾーン: 日本標準時（Asia/Tokyo）",
        ).grid(row=5, column=0, columnspan=5, sticky=tk.W, pady=(6, 0))

        ttk.Label(schedule_frame, text="完了通知:").grid(
            row=6, column=0, sticky=tk.W, pady=(7, 0)
        )
        self.schedule_notification_policy_var = tk.StringVar(value="通知しない")
        self.schedule_notification_policy_combo = ttk.Combobox(
            schedule_frame,
            textvariable=self.schedule_notification_policy_var,
            values=(
                "通知しない",
                "重要な結果のみ（新規保存・失敗など）",
                "すべての実行結果",
                "失敗時のみ",
            ),
            state="readonly",
            width=36,
        )
        self.schedule_notification_policy_combo.grid(
            row=6, column=1, columnspan=3, sticky=tk.W, pady=(7, 0)
        )
        self.btn_schedule_test_notification = ttk.Button(
            schedule_frame,
            text="テスト通知",
            command=self._on_test_schedule_notification,
        )
        self.btn_schedule_test_notification.grid(
            row=6, column=4, sticky=tk.W, padx=(8, 0), pady=(7, 0)
        )

        condition_frame = ttk.LabelFrame(
            parent, text="定期実行に使用する検索条件", padding="8"
        )
        condition_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        condition_frame.columnconfigure(0, weight=1)
        self.schedule_condition_var = tk.StringVar()
        ttk.Label(
            condition_frame,
            textvariable=self.schedule_condition_var,
            justify=tk.LEFT,
            wraplength=690,
        ).grid(row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(
            condition_frame,
            text="現在の検索条件を使用",
            command=self.on_use_current_search_conditions,
        ).grid(row=0, column=1, sticky=tk.NE, padx=(10, 0))

        history_frame = ttk.LabelFrame(parent, text="直近20回の実行履歴", padding="8")
        history_frame.grid(
            row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 4)
        )
        history_frame.columnconfigure(0, weight=1)
        history_frame.rowconfigure(0, weight=1)
        columns = ("start", "end", "result", "counts", "retry", "reason")
        self.schedule_history_tree = ttk.Treeview(
            history_frame, columns=columns, show="headings", height=6
        )
        headings = {
            "start": "開始日時",
            "end": "終了日時",
            "result": "結果",
            "counts": "新規/保存済/失敗",
            "retry": "再試行",
            "reason": "理由（コード）",
        }
        widths = {
            "start": 120,
            "end": 120,
            "result": 80,
            "counts": 110,
            "retry": 55,
            "reason": 150,
        }
        for column in columns:
            self.schedule_history_tree.heading(column, text=headings[column])
            self.schedule_history_tree.column(
                column, width=widths[column], stretch=column == "reason"
            )
        self.schedule_history_tree.grid(
            row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S)
        )
        history_scroll = ttk.Scrollbar(
            history_frame,
            orient="vertical",
            command=self.schedule_history_tree.yview,
        )
        history_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.schedule_history_tree.configure(yscrollcommand=history_scroll.set)

        self.refresh_schedule_status()

    def _setup_multi_schedule_tab(self, parent: ttk.Frame) -> None:
        """複数の保存条件を1件ずつ安全に管理する画面を作る。"""

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=3)
        parent.rowconfigure(2, weight=2)

        list_frame = ttk.LabelFrame(parent, text="保存済み定期実行条件", padding="8")
        list_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(2, weight=1)
        self.schedule_registration_var = tk.StringVar(value="状態を確認しています...")
        self.schedule_registration_label = ttk.Label(
            list_frame, textvariable=self.schedule_registration_var
        )
        self.schedule_registration_label.grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            list_frame,
            text=(
                "有効な設定はGUIを閉じても実行できます。Windowsへのログオンが必要です。"
            ),
            foreground="#666666",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(3, 0))

        columns = ("enabled", "name", "state", "cadence", "next", "result")
        self.schedule_manager_tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            height=5,
            selectmode="browse",
        )
        headings = {
            "enabled": "有効",
            "name": "条件名",
            "state": "状態",
            "cadence": "実行予定",
            "next": "次回実行",
            "result": "前回結果",
        }
        widths = {
            "enabled": 45,
            "name": 170,
            "state": 75,
            "cadence": 125,
            "next": 125,
            "result": 80,
        }
        for column in columns:
            self.schedule_manager_tree.heading(column, text=headings[column])
            self.schedule_manager_tree.column(
                column,
                width=widths[column],
                stretch=column == "name",
                anchor=tk.CENTER if column != "name" else tk.W,
            )
        self.schedule_manager_tree.grid(
            row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(6, 0)
        )
        tree_scroll = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.schedule_manager_tree.yview,
        )
        tree_scroll.grid(row=2, column=1, sticky=(tk.N, tk.S), pady=(6, 0))
        self.schedule_manager_tree.configure(yscrollcommand=tree_scroll.set)
        self.schedule_manager_tree.bind(
            "<<TreeviewSelect>>", self._on_multi_schedule_selected
        )

        actions = getattr(self, "_pinned_schedule_actions", None)
        if actions is None:
            actions = WrapButtonBar(list_frame)
            actions.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        self.btn_schedule_add = ttk.Button(
            actions, text="追加", command=self.on_schedule_add
        )
        actions.add(self.btn_schedule_add)
        self.btn_schedule_duplicate = ttk.Button(
            actions, text="複製", command=self.on_schedule_duplicate
        )
        actions.add(self.btn_schedule_duplicate)
        self.btn_schedule_edit = ttk.Button(
            actions, text="編集", command=self.on_schedule_edit
        )
        actions.add(self.btn_schedule_edit)
        self.btn_schedule_delete = ttk.Button(
            actions, text="削除", command=self.on_schedule_delete
        )
        actions.add(self.btn_schedule_delete)
        self.btn_schedule_toggle = ttk.Button(
            actions, text="有効化", command=self.on_schedule_toggle_enabled
        )
        actions.add(self.btn_schedule_toggle)
        self.btn_schedule_repair = ttk.Button(
            actions, text="修復", command=self.on_schedule_repair
        )
        actions.add(self.btn_schedule_repair)
        self.btn_schedule_manager_run = ttk.Button(
            actions, text="今すぐ実行", command=self.on_schedule_manager_run_now
        )
        actions.add(self.btn_schedule_manager_run)

        external_frame = ttk.LabelFrame(
            list_frame,
            text="管理外の旧Windowsタスク（通常の保存条件とは別管理）",
            padding="6",
        )
        external_frame.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky=(tk.W, tk.E),
            pady=(8, 0),
        )
        external_frame.columnconfigure(0, weight=1)
        self.external_schedule_tree = ttk.Treeview(
            external_frame,
            columns=("name", "state", "task"),
            show="headings",
            height=2,
            selectmode="browse",
        )
        for column, heading, width in (
            ("name", "旧設定／タスク", 220),
            ("state", "取り込み可否", 130),
            ("task", "Windowsタスク名", 360),
        ):
            self.external_schedule_tree.heading(column, text=heading)
            self.external_schedule_tree.column(
                column,
                width=width,
                stretch=column in {"name", "task"},
            )
        self.external_schedule_tree.grid(row=0, column=0, sticky=(tk.W, tk.E))
        self.external_schedule_tree.bind(
            "<<TreeviewSelect>>", self._on_external_schedule_selected
        )
        external_actions = ttk.Frame(external_frame)
        external_actions.grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        self.btn_schedule_import = ttk.Button(
            external_actions,
            text="旧設定を取り込む...",
            command=self.on_schedule_import_external,
        )
        self.btn_schedule_import.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_schedule_remove_external = ttk.Button(
            external_actions,
            text="選択した外部タスクを解除",
            command=self.on_schedule_remove_external,
            state="disabled",
        )
        self.btn_schedule_remove_external.pack(side=tk.LEFT)

        detail_frame = ttk.LabelFrame(parent, text="選択中の登録内容", padding="8")
        detail_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        self.schedule_condition_var = tk.StringVar(value="保存条件を選択してください。")
        self.schedule_condition_text = tk.Text(
            detail_frame, height=7, wrap=tk.WORD, state=tk.DISABLED, takefocus=False
        )
        self.schedule_condition_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        detail_scroll = ttk.Scrollbar(
            detail_frame, orient=tk.VERTICAL, command=self.schedule_condition_text.yview
        )
        detail_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.schedule_condition_text.configure(yscrollcommand=detail_scroll.set)

        def refresh_condition_text(*_args: object) -> None:
            text = self.schedule_condition_text
            text.configure(state=tk.NORMAL)
            text.delete("1.0", tk.END)
            text.insert("1.0", self.schedule_condition_var.get())
            text.configure(state=tk.DISABLED)

        self.schedule_condition_var.trace_add("write", refresh_condition_text)
        refresh_condition_text()

        history_frame = ttk.LabelFrame(parent, text="直近20回の実行履歴", padding="8")
        history_frame.grid(
            row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 4)
        )
        history_frame.columnconfigure(0, weight=1)
        history_frame.rowconfigure(1, weight=1)
        history_filter = ttk.Frame(history_frame)
        history_filter.grid(row=0, column=0, columnspan=2, sticky=tk.W)
        ttk.Label(history_filter, text="表示:").pack(side=tk.LEFT)
        self.schedule_history_filter_var = tk.StringVar(value="選択設定")
        history_filter_combo = ttk.Combobox(
            history_filter,
            textvariable=self.schedule_history_filter_var,
            values=("選択設定", "全設定"),
            state="readonly",
            width=10,
        )
        history_filter_combo.pack(side=tk.LEFT, padx=(4, 0))
        history_filter_combo.bind(
            "<<ComboboxSelected>>", self._on_schedule_history_filter_changed
        )
        columns = (
            "name",
            "scheduled",
            "start",
            "end",
            "trigger",
            "queue",
            "result",
            "counts",
            "retry",
            "reason",
        )
        self.schedule_history_tree = ttk.Treeview(
            history_frame, columns=columns, show="headings", height=5
        )
        headings = {
            "name": "設定名",
            "scheduled": "予定日時",
            "start": "開始日時",
            "end": "終了日時",
            "trigger": "起動種別",
            "queue": "待機時間",
            "result": "結果",
            "counts": "新規/保存済/失敗",
            "retry": "再試行",
            "reason": "理由（コード）",
        }
        widths = {
            "name": 145,
            "scheduled": 120,
            "start": 120,
            "end": 120,
            "trigger": 85,
            "queue": 70,
            "result": 80,
            "counts": 110,
            "retry": 55,
            "reason": 150,
        }
        for column in columns:
            self.schedule_history_tree.heading(column, text=headings[column])
            self.schedule_history_tree.column(
                column, width=widths[column], stretch=column == "reason"
            )
        self.schedule_history_tree.grid(
            row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(5, 0)
        )
        history_scroll = ttk.Scrollbar(
            history_frame,
            orient="vertical",
            command=self.schedule_history_tree.yview,
        )
        history_scroll.grid(row=1, column=1, sticky=(tk.N, tk.S), pady=(5, 0))
        history_xscroll = ttk.Scrollbar(
            history_frame,
            orient="horizontal",
            command=self.schedule_history_tree.xview,
        )
        history_xscroll.grid(row=2, column=0, sticky=(tk.W, tk.E))
        self.schedule_history_tree.configure(
            yscrollcommand=history_scroll.set,
            xscrollcommand=history_xscroll.set,
        )

        self._set_multi_schedule_action_state(False)
        self._schedule_manager_after_id = self.dialog.after(
            100, self._poll_schedule_manager_queue
        )
        self.request_multi_schedule_refresh()

    @staticmethod
    def _format_schedule_cadence(view: ScheduleView) -> str:
        schedule = schedule_value(view.definition, "schedule")
        if schedule is None and isinstance(view.config, AppConfig):
            schedule = view.config.schedule
        if schedule is None:
            return "-（台帳欠落）"
        interval = str(schedule_value(schedule, "interval", default="daily"))
        time_value = str(schedule_value(schedule, "time", default="09:00"))
        if interval == "weekly":
            weekday = str(schedule_value(schedule, "weekday", default="monday"))
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
            day = schedule_value(schedule, "day_of_month", default=1)
            return f"毎月{day}日 {time_value}"
        return f"毎日 {time_value}"

    @staticmethod
    def _format_external_candidate_cadence(candidate: object) -> str:
        summary = schedule_value(candidate, "schedule_summary", "cadence", default="")
        if summary:
            return str(summary)
        schedule = schedule_value(candidate, "schedule", default=candidate)
        interval = str(schedule_value(schedule, "interval", default="") or "")
        time_value = str(schedule_value(schedule, "time", default="") or "")
        if interval == "weekly":
            weekday = str(schedule_value(schedule, "weekday", default="") or "")
            names = {
                "monday": "月",
                "tuesday": "火",
                "wednesday": "水",
                "thursday": "木",
                "friday": "金",
                "saturday": "土",
                "sunday": "日",
            }
            return f"毎週{names.get(weekday, weekday)}曜 {time_value}".strip()
        if interval == "monthly":
            day = schedule_value(schedule, "day_of_month", default="")
            return f"毎月{day}日 {time_value}".strip()
        if interval == "daily":
            return f"毎日 {time_value}".strip()
        return "-"

    def request_multi_schedule_refresh(self) -> None:
        if getattr(self, "_schedule_manager_closed", False):
            return
        self._schedule_manager_generation = (
            getattr(self, "_schedule_manager_generation", 0) + 1
        )
        generation = self._schedule_manager_generation
        if getattr(self, "_schedule_manager_query_running", False):
            self._schedule_manager_refresh_pending = True
            return
        adapter = getattr(self, "_schedule_adapter", None)
        if adapter is None:
            return
        selected_id = getattr(self, "_selected_schedule_id", None)
        try:
            current_config = self._get_current_main_config()
        except (TypeError, ValueError):
            current_config = deepcopy(self.config)
        self._schedule_manager_query_running = True
        self._schedule_manager_refresh_pending = False

        def worker() -> None:
            try:
                views = adapter.list_views(current_config)
                target_id = selected_id
                if target_id not in {view.schedule_id for view in views}:
                    target_id = views[0].schedule_id if views else None
                selected_config = None
                selected_history: list[object] = []
                all_history = adapter.history(None, 20)
                configs_by_id: dict[str, AppConfig] = {}
                for view in views:
                    if view.is_external:
                        continue
                    registered_config = adapter.registered_config(view.schedule_id)
                    if isinstance(registered_config, AppConfig):
                        configs_by_id[view.schedule_id] = registered_config
                        view.config = registered_config
                if target_id is not None:
                    selected_config = configs_by_id.get(target_id)
                    selected_history = adapter.history(target_id, 20)
                payload = (
                    "refresh",
                    generation,
                    views,
                    target_id,
                    selected_config,
                    configs_by_id,
                    selected_history,
                    all_history,
                    None,
                )
            except Exception as exc:
                payload = (
                    "refresh",
                    generation,
                    [],
                    selected_id,
                    None,
                    {},
                    [],
                    [],
                    exc,
                )
            self._schedule_manager_queue.put(payload)

        Thread(
            target=worker,
            name="ippi-schedule-manager-status",
            daemon=True,
        ).start()

    def _poll_schedule_manager_queue(self) -> None:
        if getattr(self, "_schedule_manager_closed", False):
            return
        try:
            while True:
                payload = self._schedule_manager_queue.get_nowait()
                if payload[0] == "refresh":
                    self._apply_multi_schedule_refresh(*payload[1:])
                elif payload[0] == "detail":
                    self._apply_multi_schedule_detail(*payload[1:])
                elif payload[0] == "external-preview":
                    self._finish_external_import_preview(*payload[1:])
                elif payload[0] == "action":
                    self._finish_multi_schedule_action(*payload[1:])
        except Empty:
            pass
        try:
            self._schedule_manager_after_id = self.dialog.after(
                100, self._poll_schedule_manager_queue
            )
        except tk.TclError:
            self._schedule_manager_closed = True

    def _apply_multi_schedule_refresh(
        self,
        generation: int,
        views: list[ScheduleView],
        selected_id: Optional[str],
        selected_config: Optional[AppConfig],
        configs_by_id: dict[str, AppConfig],
        selected_history: list[object],
        all_history: list[object],
        error: Optional[Exception],
    ) -> None:
        self._schedule_manager_query_running = False
        if generation != getattr(self, "_schedule_manager_generation", generation):
            self._schedule_manager_refresh_pending = False
            self.dialog.after(0, self.request_multi_schedule_refresh)
            return
        payload_selected_id = selected_id
        current_selected_id = getattr(self, "_selected_schedule_id", None)
        if error is None:
            self._schedule_views = list(views)
            managed_views = [
                view for view in self._schedule_views if not view.is_external
            ]
            external_views = [view for view in self._schedule_views if view.is_external]
            self._schedule_views_by_id = {
                view.schedule_id: view for view in managed_views
            }
            self._external_schedule_views_by_id = {
                view.schedule_id: view for view in external_views
            }
            external_selected_id = getattr(self, "_selected_external_schedule_id", None)
            if external_selected_id not in self._external_schedule_views_by_id:
                external_selected_id = None
                self._selected_external_schedule_id = None
            if external_selected_id is not None:
                selected_id = None
            elif current_selected_id in self._schedule_views_by_id:
                selected_id = current_selected_id
            elif selected_id not in self._schedule_views_by_id:
                selected_id = managed_views[0].schedule_id if managed_views else None
            self._selected_schedule_id = selected_id
            self._selected_schedule_config = configs_by_id.get(selected_id or "")
            self._schedule_configs_by_id = dict(configs_by_id)
            if payload_selected_id == selected_id:
                self._schedule_selected_history = list(selected_history)
            self._schedule_all_history = list(all_history)
        else:
            views = list(getattr(self, "_schedule_views", []))

        managed_views = [view for view in views if not view.is_external]
        external_views = [view for view in views if view.is_external]

        counts = aggregate_schedule_counts(managed_views)
        text = f"保存条件 {counts['total']}件 / 有効 {counts['enabled']}件"
        if counts["running"]:
            text += f" / 実行中 {counts['running']}件"
        if counts["queued"]:
            text += f" / 順番待ち {counts['queued']}件"
        if counts["repair"]:
            text += f" / 要修復 {counts['repair']}件"
        if external_views:
            text += f" / 管理外の旧タスク {len(external_views)}件"
        if error is not None:
            text += f" / 状態確認失敗 [STATUS_QUERY_FAILED]: {error}"
            colour = "#cf222e"
        elif counts["repair"]:
            colour = "#cf222e"
        elif counts["failed"] or counts["update"]:
            colour = "#9a6700"
        else:
            colour = "#1a7f37" if counts["enabled"] else "#666666"
        self.schedule_registration_var.set(text)
        self.schedule_registration_label.configure(foreground=colour)

        tree = self.schedule_manager_tree
        rows: list[ScheduleTreeRow] = []
        for view in managed_views:
            status_label, status_colour = self._status_presentation(view.status)
            queue_position = schedule_value(view.status, "queue_position")
            if status_label == "順番待ち" and queue_position:
                status_label = f"順番待ち ({queue_position}番)"
            tag = f"schedule-{view.schedule_id}"
            tree.tag_configure(tag, foreground=status_colour)
            rows.append(
                ScheduleTreeRow(
                    item_id=view.schedule_id,
                    tags=(tag,),
                    values=(
                        "はい" if view.enabled else "いいえ",
                        view.name,
                        status_label,
                        self._format_schedule_cadence(view),
                        _format_datetime(schedule_value(view.status, "next_run")),
                        _format_schedule_result(
                            schedule_value(view.status, "last_result", default="-")
                        ),
                    ),
                )
            )
        reconcile_schedule_tree(tree, rows, selected_id=selected_id)

        external_rows: list[ScheduleTreeRow] = []
        for view in external_views:
            reason_code = str(
                schedule_value(view.status, "reason_code", default="") or ""
            ).upper()
            state_text = "取り込み可能" if view.allows("import") else "取り込み不可"
            if reason_code == "EXTERNAL_TASK_RUNNING":
                state_text = "実行中"
            external_rows.append(
                ScheduleTreeRow(
                    item_id=view.schedule_id,
                    values=(
                        view.name,
                        state_text,
                        schedule_value(view.status, "task_name", default="-"),
                    ),
                    tags=("external-task",),
                )
            )
        self.external_schedule_tree.tag_configure("external-task", foreground="#9a6700")
        reconcile_schedule_tree(
            self.external_schedule_tree,
            external_rows,
            selected_id=getattr(self, "_selected_external_schedule_id", None),
        )

        selected_config = self._schedule_configs_by_id.get(selected_id or "")
        self._update_multi_schedule_detail(selected_id, selected_config)
        self._populate_schedule_history(self._history_records_for_filter())
        self._update_multi_schedule_action_state()
        self._refresh_reclassification_availability()

        pending_editor = getattr(self, "_schedule_editor_reopen_after_refresh", None)
        if error is None and pending_editor is not None:
            self._schedule_editor_reopen_after_refresh = None
            self.dialog.after(
                0,
                lambda draft=pending_editor: self._reopen_schedule_editor_draft(draft),
            )

        if self._schedule_manager_refresh_pending:
            self._schedule_manager_refresh_pending = False
            self.dialog.after(0, self.request_multi_schedule_refresh)
            return
        running = self._schedule_manager_action_running or any(
            bool(schedule_value(view.status, "running", default=False))
            or bool(schedule_value(view.status, "retry_waiting", default=False))
            or bool(
                schedule_value(view.status, "queue_waiting", "queued", default=False)
            )
            or str(
                getattr(
                    schedule_value(view.status, "state", default=""),
                    "value",
                    schedule_value(view.status, "state", default=""),
                )
            ).lower()
            in {"queued", "queue_waiting", "waiting", "retry_waiting", "retry_wait"}
            for view in managed_views
        )
        if getattr(self, "_schedule_manager_refresh_after_id", None) is not None:
            try:
                self.dialog.after_cancel(self._schedule_manager_refresh_after_id)
            except tk.TclError:
                pass
        self._schedule_manager_refresh_after_id = self.dialog.after(
            5000 if running else 60000,
            self.request_multi_schedule_refresh,
        )

    @staticmethod
    def _status_presentation(status: object) -> tuple[str, str]:
        state_value = schedule_value(status, "state", default="")
        state = str(getattr(state_value, "value", state_value) or "").lower()
        if bool(
            schedule_value(status, "queue_waiting", "queued", default=False)
        ) or state in {"queued", "queue_waiting", "waiting"}:
            return "順番待ち", "#8250df"
        if bool(schedule_value(status, "retry_waiting", default=False)) or state in {
            "retry_waiting",
            "retry_wait",
        }:
            return "再試行待機中", "#9a6700"
        if bool(schedule_value(status, "running", default=False)):
            return "実行中", "#0969da"
        if schedule_value(status, "repair_reason") or state in {
            "repair_required",
            "needs_repair",
        }:
            return "要修復", "#cf222e"
        if bool(
            schedule_value(status, "definition_mismatch", default=False)
        ) or state in {
            "update_required",
            "needs_update",
        }:
            return "要更新", "#9a6700"
        result = str(schedule_value(status, "last_result", default="")).lower()
        if state in {"last_failed", "failed"} or result in {
            "failed",
            "failure",
            "partial",
            "partial_failure",
            "error",
            "queue_timeout",
            "run_timeout",
            "config_invalid",
        }:
            return "前回失敗", "#cf222e"
        if bool(schedule_value(status, "registered", default=False)):
            return "登録済み", "#1a7f37"
        return "無効", "#666666"

    def _update_multi_schedule_detail(
        self,
        schedule_id: Optional[str],
        config: Optional[AppConfig],
    ) -> None:
        view = self._schedule_views_by_id.get(schedule_id or "")
        if view is None:
            self.schedule_condition_var.set("保存条件を追加してください。")
            return
        status = view.status
        task_name = schedule_value(status, "task_name", default="-")
        repair = schedule_value(status, "repair_reason")
        reason_code = schedule_value(status, "reason_code")
        lines = [
            f"条件名: {view.name}",
            f"実行予定: {self._format_schedule_cadence(view)}",
            f"Windowsタスク: {task_name}",
            f"固定保存キー: {view.storage_key or '旧構成／未割当'}",
        ]
        schedule = schedule_value(view.definition, "schedule")
        if schedule is None and isinstance(config, AppConfig):
            schedule = config.schedule
        if schedule is not None:
            wake_to_run = bool(schedule_value(schedule, "wake_to_run", default=False))
            notification_policy = schedule_value(
                schedule,
                "notification_policy",
                default="off",
            )
            registered = bool(schedule_value(status, "registered", default=False))
            task_enabled = bool(schedule_value(status, "enabled", default=registered))
            runtime_available = (
                registered
                and task_enabled
                and not bool(schedule_value(status, "repair_reason"))
            )
            background_text = (
                "GUI終了後も実行可（Windowsへのログオンが必要）"
                if runtime_available
                else "不可（有効なWindowsタスクの登録・修復が必要）"
            )
            lines.extend(
                (
                    f"バックグラウンド実行: {background_text}",
                    f"スリープ解除: {'ON' if wake_to_run else 'OFF'}",
                    "完了通知: "
                    f"{format_schedule_notification_policy(notification_policy)}",
                )
            )
        if repair or reason_code:
            lines.append(
                f"診断: {repair or '詳細はログを確認'}"
                + (f" [{reason_code}]" if reason_code else "")
            )
        if str(reason_code or "").upper() == "TASK_REGISTRY_MISSING":
            lines.append(
                "この行は登録台帳にないWindowsタスクです。変更操作はできません。"
                "元の設定・登録台帳を戻すか、Windowsのタスク管理画面で確認してください。"
            )
        queue_position = schedule_value(status, "queue_position")
        queue_total = schedule_value(status, "queue_total")
        if queue_position:
            lines.append(
                f"実行待ち: {queue_position}番目"
                + (f" / 待機中 {queue_total}件" if queue_total else "")
            )
        if isinstance(config, AppConfig):
            lines.append(format_schedule_condition_summary(config))
        self.schedule_condition_var.set("\n".join(lines))

    def _history_records_for_filter(self) -> list[object]:
        if (
            getattr(
                getattr(self, "schedule_history_filter_var", None),
                "get",
                lambda: "選択設定",
            )()
            == "全設定"
        ):
            return list(getattr(self, "_schedule_all_history", []) or [])
        return list(getattr(self, "_schedule_selected_history", []) or [])

    def _on_schedule_history_filter_changed(self, _event=None) -> None:
        self._populate_schedule_history(self._history_records_for_filter())

    def _populate_schedule_history(self, records: list[object]) -> None:
        tree = self.schedule_history_tree
        for item in tree.get_children():
            tree.delete(item)
        current_names = {
            view.schedule_id: view.name for view in getattr(self, "_schedule_views", [])
        }
        for record in records or []:
            new_count = _record_value(record, "new_count", "saved", default=0)
            existing_count = _record_value(
                record, "existing_count", "saved_count", "reused", default=0
            )
            failed_count = _record_value(record, "failed_count", "failed", default=0)
            queue_wait = _record_value(record, "queue_wait_seconds", default=0)
            try:
                queue_wait_text = f"{float(queue_wait or 0):.1f}秒"
            except (TypeError, ValueError):
                queue_wait_text = str(queue_wait or "-")
            tree.insert(
                "",
                tk.END,
                values=(
                    history_display_name(record, current_names),
                    _format_datetime(_record_value(record, "scheduled_at")),
                    _format_datetime(_record_value(record, "started_at")),
                    _format_datetime(_record_value(record, "finished_at", "ended_at")),
                    trigger_kind_display(
                        _record_value(record, "trigger_kind", default="")
                    ),
                    queue_wait_text,
                    _format_schedule_result(_record_value(record, "result", "outcome")),
                    f"{new_count}/{existing_count}/{failed_count}",
                    _record_value(record, "retry_count", default=0),
                    format_schedule_reason(_record_value(record, "reason_code")),
                ),
            )

    def _on_multi_schedule_selected(self, _event=None) -> None:
        selection = self.schedule_manager_tree.selection()
        if not selection:
            return
        schedule_id = str(selection[0])
        if schedule_id == self._selected_schedule_id:
            return
        self._selected_schedule_id = schedule_id
        self._selected_external_schedule_id = None
        external_tree = getattr(self, "external_schedule_tree", None)
        if external_tree is not None:
            external_selection = tuple(external_tree.selection())
            if external_selection:
                external_tree.selection_remove(*external_selection)
        view = self._schedule_views_by_id.get(schedule_id)
        if view is not None:
            config = self._schedule_configs_by_id.get(schedule_id) or view.config
            self._selected_schedule_config = config
            self._update_multi_schedule_detail(schedule_id, config)
        self._populate_schedule_history(self._history_records_for_filter())
        self._update_multi_schedule_action_state()
        self._request_multi_schedule_detail_refresh(schedule_id)

    def _request_multi_schedule_detail_refresh(self, schedule_id: str) -> None:
        """選択した1件の条件・履歴を一覧とは別世代で取得する。"""

        adapter = getattr(self, "_schedule_adapter", None)
        if adapter is None:
            return
        self._schedule_detail_generation += 1
        generation = self._schedule_detail_generation

        def worker() -> None:
            try:
                config = adapter.registered_config(schedule_id)
                history = adapter.history(schedule_id, 20)
                error = None
            except Exception as exc:
                config, history, error = None, [], exc
            self._schedule_manager_queue.put(
                ("detail", generation, schedule_id, config, history, error)
            )

        Thread(
            target=worker,
            name="ippi-schedule-manager-detail",
            daemon=True,
        ).start()

    def _apply_multi_schedule_detail(
        self,
        generation: int,
        schedule_id: str,
        config: Optional[AppConfig],
        history: list[object],
        error: Optional[Exception],
    ) -> None:
        if generation != self._schedule_detail_generation:
            return
        if schedule_id != self._selected_schedule_id:
            return
        if error is not None:
            self.schedule_registration_var.set(
                f"選択中の条件を読み込めません [SCHEDULE_DETAIL_FAILED]: {error}"
            )
            self.schedule_registration_label.configure(foreground="#cf222e")
            return
        if isinstance(config, AppConfig):
            self._schedule_configs_by_id[schedule_id] = config
            self._selected_schedule_config = config
            view = self._schedule_views_by_id.get(schedule_id)
            if view is not None:
                view.config = config
        self._schedule_selected_history = list(history)
        self._update_multi_schedule_detail(schedule_id, config)
        self._populate_schedule_history(self._history_records_for_filter())

    def _on_external_schedule_selected(self, _event=None) -> None:
        selection = self.external_schedule_tree.selection()
        if not selection:
            self.btn_schedule_remove_external.configure(state="disabled")
            return
        external_id = str(selection[0])
        self._selected_external_schedule_id = external_id
        managed_selection = tuple(self.schedule_manager_tree.selection())
        if managed_selection:
            self.schedule_manager_tree.selection_remove(*managed_selection)
        self._selected_schedule_id = None
        self._selected_schedule_config = None
        view = self._external_schedule_views_by_id.get(external_id)
        if view is None:
            self.btn_schedule_remove_external.configure(state="disabled")
            return
        reason = schedule_value(view.status, "repair_reason", "reason", default="")
        reason_code = schedule_value(view.status, "reason_code", default="")
        task_name = schedule_value(view.status, "task_name", default="-")
        self.schedule_condition_var.set(
            f"管理外の旧Windowsタスク: {view.name}\n"
            f"Windowsタスク: {task_name}\n"
            f"診断: {reason or 'このアプリの保存条件には含まれません'}"
            + (f" [{reason_code}]" if reason_code else "")
        )
        self._update_multi_schedule_action_state()
        running = bool(
            schedule_value(view.status, "running", default=False)
            or schedule_value(view.status, "retry_waiting", default=False)
        )
        self.btn_schedule_remove_external.configure(
            state=(
                "normal"
                if view.allows("remove_external") and not running
                else "disabled"
            )
        )

    def _selected_multi_schedule(self) -> Optional[ScheduleView]:
        return self._schedule_views_by_id.get(self._selected_schedule_id or "")

    def _set_multi_schedule_action_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for name in (
            "btn_schedule_duplicate",
            "btn_schedule_edit",
            "btn_schedule_delete",
            "btn_schedule_toggle",
            "btn_schedule_repair",
            "btn_schedule_manager_run",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state=state)

    def _update_multi_schedule_action_state(self) -> None:
        view = self._selected_multi_schedule()
        busy = bool(self._schedule_manager_action_running)
        self.btn_schedule_add.configure(state="disabled" if busy else "normal")
        if hasattr(self, "btn_schedule_import"):
            self.btn_schedule_import.configure(state="disabled" if busy else "normal")
        if hasattr(self, "btn_schedule_remove_external"):
            external_selection = (
                tuple(getattr(self, "external_schedule_tree", None).selection())
                if getattr(self, "external_schedule_tree", None) is not None
                else ()
            )
            external_view = (
                self._external_schedule_views_by_id.get(str(external_selection[0]))
                if external_selection
                else None
            )
            external_running = bool(
                schedule_value(
                    getattr(external_view, "status", None),
                    "running",
                    default=False,
                )
            )
            self.btn_schedule_remove_external.configure(
                state=(
                    "normal"
                    if not busy
                    and external_view is not None
                    and external_view.allows("remove_external")
                    and not external_running
                    else "disabled"
                )
            )
        self._set_multi_schedule_action_state(view is not None and not busy)
        if view is None or busy:
            return
        self.btn_schedule_toggle.configure(text="無効化" if view.enabled else "有効化")
        self.btn_schedule_repair.configure(
            text="修復不可" if view.is_external else "修復"
        )
        running = bool(
            schedule_value(view.status, "running", default=False)
            or schedule_value(view.status, "retry_waiting", default=False)
        )
        queued = bool(
            schedule_value(view.status, "queue_waiting", "queued", default=False)
        )
        registered = bool(schedule_value(view.status, "registered", default=False))
        editable = view.allows("edit")
        self.btn_schedule_duplicate.configure(
            state="normal" if editable else "disabled"
        )
        self.btn_schedule_edit.configure(
            state="normal" if editable else "disabled"
        )
        self.btn_schedule_delete.configure(
            state=(
                "normal"
                if view.allows("delete")
                else "disabled"
            )
        )
        self.btn_schedule_toggle.configure(
            state="normal" if editable else "disabled"
        )
        self.btn_schedule_manager_run.configure(
            state=(
                "normal"
                if registered and view.allows("run") and not running and not queued
                else "disabled"
            )
        )
        self.btn_schedule_repair.configure(
            state="normal" if view.allows("repair") else "disabled"
        )

    def _open_multi_schedule_editor(
        self,
        *,
        schedule_id: Optional[str] = None,
        initial_config: Optional[AppConfig] = None,
        initial_name: Optional[str] = None,
    ) -> None:
        if initial_config is not None:
            initial = deepcopy(initial_config)
            name = initial_name or "新しい定期実行"
            title = (
                f"定期実行条件の編集 - {name}"
                if schedule_id is not None
                else "定期実行条件の追加"
            )
        elif schedule_id is None:
            try:
                initial = self._get_current_main_config()
            except (TypeError, ValueError) as exc:
                messagebox.showerror("検索条件エラー", str(exc), parent=self.dialog)
                return
            initial.schedule.enabled = False
            # モデルの既定は旧設定互換のOFF。GUIから新規作成する設定だけは
            # 計画どおり「重要な結果のみ」を既定にする。
            setattr(initial.schedule, "notification_policy", "important_only")
            name = "新しい定期実行"
            title = "定期実行条件の追加"
        else:
            view = self._schedule_views_by_id.get(schedule_id)
            initial = self._selected_schedule_config
            if view is None or not isinstance(initial, AppConfig):
                messagebox.showwarning(
                    "定期実行",
                    "登録済み条件を読み込み中です。少し待ってから再実行してください。",
                    parent=self.dialog,
                )
                return
            name = view.name
            title = f"定期実行条件の編集 - {name}"

        editor = ScheduleEditorDialog(
            self.dialog,
            initial,
            name=name,
            title=title,
            current_config_provider=self._get_current_main_config,
            validator=self.config_manager.validate_config,
            dynamic_validator=self.schedule_config_validator,
            search_options_provider=self.search_options_provider,
            search_option_loader=self.search_option_loader,
            search_options_reloader=self.search_options_reloader,
            summary_formatter=format_schedule_condition_summary,
            option_load_coordinator=self.option_load_coordinator,
        )
        result = editor.show()
        if result is None:
            return
        retry_editor = (
            schedule_id,
            result.name,
            deepcopy(result.config),
        )
        duplicates = duplicate_condition_names(
            result.config,
            self._schedule_views,
            self._schedule_configs_by_id,
            exclude_schedule_id=schedule_id,
        )
        if duplicates and not messagebox.askyesno(
            "同じ実行条件があります",
            "次の設定と検索・文書・保存条件が同じです:\n"
            + "\n".join(f"・{name}" for name in duplicates)
            + "\n\nこのまま保存しますか？",
            parent=self.dialog,
        ):
            self.dialog.after(
                0,
                lambda draft=retry_editor: self._reopen_schedule_editor_draft(draft),
            )
            return
        if schedule_id is None:
            self._start_multi_schedule_action(
                "追加",
                lambda: self._schedule_adapter.create(
                    result.name,
                    result.config,
                    expected_revision=self._schedule_adapter.registry_revision,
                ),
                retry_editor=retry_editor,
            )
        else:
            self._start_multi_schedule_action(
                "更新",
                lambda: self._schedule_adapter.update(
                    schedule_id,
                    result.name,
                    result.config,
                    expected_revision=self._schedule_adapter.registry_revision,
                ),
                retry_editor=retry_editor,
            )

    def _reopen_schedule_editor_draft(
        self, draft: tuple[Optional[str], str, AppConfig]
    ) -> None:
        schedule_id, name, config = draft
        self._open_multi_schedule_editor(
            schedule_id=schedule_id,
            initial_config=config,
            initial_name=name,
        )

    def on_schedule_add(self) -> None:
        self._open_multi_schedule_editor()

    def on_schedule_edit(self) -> None:
        view = self._selected_multi_schedule()
        if view is None:
            return
        running_or_queued = bool(
            schedule_value(view.status, "running", default=False)
            or schedule_value(view.status, "retry_waiting", default=False)
            or schedule_value(view.status, "queue_waiting", "queued", default=False)
        )
        if running_or_queued and not messagebox.askyesno(
            "実行中の定期実行を編集",
            "開始済みまたは待機済みの実行は、登録時のスナップショットで"
            "継続します。次回以降の条件を編集しますか？",
            parent=self.dialog,
        ):
            return
        self._open_multi_schedule_editor(schedule_id=view.schedule_id)

    def on_schedule_duplicate(self) -> None:
        view = self._selected_multi_schedule()
        if view is None:
            return
        name = simpledialog.askstring(
            "定期実行条件の複製",
            "複製後の条件名:",
            initialvalue=f"{view.name} のコピー",
            parent=self.dialog,
        )
        if not name or not name.strip():
            return
        self._start_multi_schedule_action(
            "複製",
            lambda: self._schedule_adapter.duplicate(
                view.schedule_id,
                name.strip(),
                expected_revision=self._schedule_adapter.registry_revision,
            ),
        )

    def on_schedule_delete(self) -> None:
        view = self._selected_multi_schedule()
        if view is None:
            return
        running_or_queued = bool(
            schedule_value(view.status, "running", default=False)
            or schedule_value(view.status, "retry_waiting", default=False)
            or schedule_value(view.status, "queue_waiting", "queued", default=False)
        )
        continuation = (
            "\n開始済みまたは待機済みの実行は、登録時のスナップショットで継続します。"
            if running_or_queued
            else ""
        )
        if not messagebox.askyesno(
            "定期実行条件の削除",
            f"「{view.name}」を削除しますか？\n"
            "Windowsタスクは削除されますが、実行履歴ログは保持されます。"
            f"{continuation}",
            parent=self.dialog,
        ):
            return
        self._start_multi_schedule_action(
            "削除",
            lambda: self._schedule_adapter.delete(
                view.schedule_id,
                expected_revision=self._schedule_adapter.registry_revision,
            ),
        )

    def on_schedule_toggle_enabled(self) -> None:
        view = self._selected_multi_schedule()
        if view is None:
            return
        enabled = not view.enabled
        label = "有効化" if enabled else "無効化"
        running_or_queued = bool(
            schedule_value(view.status, "running", default=False)
            or schedule_value(view.status, "retry_waiting", default=False)
            or schedule_value(view.status, "queue_waiting", "queued", default=False)
        )
        continuation = (
            "\n開始済みまたは待機済みの実行は、登録時のスナップショットで継続します。"
            if not enabled and running_or_queued
            else ""
        )
        if not messagebox.askyesno(
            f"定期実行の{label}",
            f"「{view.name}」を{label}しますか？{continuation}",
            parent=self.dialog,
        ):
            return
        self._start_multi_schedule_action(
            label,
            lambda: self._schedule_adapter.set_enabled(
                view.schedule_id,
                enabled,
                expected_revision=self._schedule_adapter.registry_revision,
            ),
        )

    def on_schedule_repair(self) -> None:
        view = self._selected_multi_schedule()
        if view is None:
            return
        if not view.allows("repair"):
            messagebox.showwarning(
                "修復できない定期実行",
                "この項目は修復対象ではありません。管理外の旧タスクは、"
                "旧設定の取り込みまたは外部タスクの解除を使用してください。",
                parent=self.dialog,
            )
            return
        self._start_multi_schedule_action(
            "修復",
            lambda: self._schedule_adapter.repair(
                view.schedule_id,
                expected_revision=self._schedule_adapter.registry_revision,
            ),
        )

    def on_schedule_import_external(self) -> None:
        """旧configを選び、安全に検証できた候補だけをpreviewする。"""

        source_dir = filedialog.askdirectory(
            title="旧定期実行のconfigフォルダーを選択",
            parent=self.dialog,
            mustexist=True,
        )
        if not source_dir:
            return
        adapter = getattr(self, "_schedule_adapter", None)
        if adapter is None or self._schedule_manager_action_running:
            return
        self._schedule_manager_action_running = True
        self.schedule_registration_var.set("旧設定を検査しています...")
        self._update_multi_schedule_action_state()
        self._refresh_reclassification_availability()

        def worker() -> None:
            try:
                candidates = adapter.external_candidates(source_dir)
                error = None
            except Exception as exc:
                candidates, error = [], exc
            self._schedule_manager_queue.put(
                ("external-preview", source_dir, candidates, error)
            )

        Thread(
            target=worker,
            name="ippi-schedule-import-preview",
            daemon=True,
        ).start()

    def _finish_external_import_preview(
        self,
        source_dir: str,
        candidates: list[object],
        error: Optional[Exception],
    ) -> None:
        self._schedule_manager_action_running = False
        self._update_multi_schedule_action_state()
        self._refresh_reclassification_availability()
        if error is not None:
            code = getattr(error, "reason_code", "EXTERNAL_IMPORT_PREVIEW_FAILED")
            self.schedule_registration_var.set(
                f"旧設定の検査に失敗しました [{code}]: {error}"
            )
            self.schedule_registration_label.configure(foreground="#cf222e")
            messagebox.showerror(
                "旧設定を検査できません",
                f"{error}\n理由コード: {code}",
                parent=self.dialog,
            )
            return
        if not candidates:
            self.schedule_registration_var.set("取り込み候補は見つかりませんでした。")
            messagebox.showinfo(
                "旧設定の取り込み",
                "選択したconfigフォルダーに、検証可能な定期実行設定はありません。",
                parent=self.dialog,
            )
            return
        self._show_external_import_preview(source_dir, candidates)

    def _show_external_import_preview(
        self,
        source_dir: str,
        candidates: list[object],
    ) -> None:
        preview = tk.Toplevel(self.dialog)
        preview.title("旧定期実行設定の取り込み確認")
        fit_to_screen(preview, 860, 420, minimum_width=560, minimum_height=340)
        preview.transient(self.dialog)
        preview.grab_set()
        ttk.Label(
            preview,
            text=(
                f"選択元: {source_dir}\n"
                "内容と可否を確認し、取り込む設定を1件選択してください。"
                "取り込み後の有効／無効状態は旧設定を引き継ぎます。"
            ),
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=10, pady=(10, 6))
        table_frame = ttk.Frame(preview)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        tree = ttk.Treeview(
            table_frame,
            columns=(
                "name",
                "enabled",
                "cadence",
                "save_path",
                "state",
                "task",
                "reason",
            ),
            show="headings",
            selectmode="browse",
            height=10,
        )
        for column, heading, width in (
            ("name", "設定名", 150),
            ("enabled", "有効", 55),
            ("cadence", "実行予定", 120),
            ("save_path", "実効保存先", 220),
            ("state", "可否", 90),
            ("task", "Windowsタスク", 220),
            ("reason", "診断", 240),
        ):
            tree.heading(column, text=heading)
            tree.column(column, width=width, stretch=column in {"task", "reason"})
        tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        xscroll = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=tree.xview,
        )
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        tree.configure(xscrollcommand=xscroll.set)
        candidate_by_id: dict[str, object] = {}
        first_importable: Optional[str] = None
        for candidate in candidates:
            external_id = str(
                schedule_value(
                    candidate,
                    "external_id",
                    "schedule_id",
                    default="",
                )
                or ""
            )
            if not external_id or external_id in candidate_by_id:
                continue
            importable = bool(schedule_value(candidate, "importable", default=False))
            reason_code = str(
                schedule_value(candidate, "reason_code", default="") or ""
            ).upper()
            name_conflict = reason_code in {
                "EXTERNAL_NAME_CONFLICT",
                "EXTERNAL_SCHEDULE_NAME_CONFLICT",
            } or bool(schedule_value(candidate, "requires_target_name", default=False))
            candidate_by_id[external_id] = candidate
            if (importable or name_conflict) and first_importable is None:
                first_importable = external_id
            tree.insert(
                "",
                tk.END,
                iid=external_id,
                values=(
                    schedule_value(
                        candidate,
                        "display_name",
                        "name",
                        default=external_id,
                    ),
                    (
                        "はい"
                        if bool(schedule_value(candidate, "enabled", default=False))
                        else "いいえ"
                    ),
                    self._format_external_candidate_cadence(candidate),
                    schedule_value(
                        candidate,
                        "effective_save_path",
                        "save_path",
                        "storage_path",
                        default="-",
                    ),
                    (
                        "要改名"
                        if name_conflict
                        else ("取り込み可能" if importable else "取り込み不可")
                    ),
                    schedule_value(candidate, "task_name", default="-"),
                    schedule_value(
                        candidate,
                        "reason",
                        "reason_code",
                        default="-",
                    ),
                ),
            )
        if first_importable is not None:
            tree.selection_set(first_importable)
            tree.focus(first_importable)

        name_frame = ttk.Frame(preview)
        name_frame.pack(fill=tk.X, padx=10, pady=(7, 0))
        ttk.Label(name_frame, text="取り込み後の設定名:").pack(side=tk.LEFT)
        import_name_var = tk.StringVar(value="")
        import_name_entry = ttk.Entry(
            name_frame,
            textvariable=import_name_var,
            width=45,
        )
        import_name_entry.pack(side=tk.LEFT, padx=(5, 0))

        def update_import_name(_event=None) -> None:
            selection = tree.selection()
            if not selection:
                import_name_var.set("")
                return
            candidate = candidate_by_id.get(str(selection[0]))
            import_name_var.set(
                str(
                    schedule_value(
                        candidate,
                        "display_name",
                        "name",
                        default="",
                    )
                    or ""
                )
            )

        tree.bind("<<TreeviewSelect>>", update_import_name)
        update_import_name()

        actions = ttk.Frame(preview)
        actions.pack(fill=tk.X, padx=10, pady=10)

        def import_selected() -> None:
            selection = tree.selection()
            if not selection:
                messagebox.showwarning(
                    "旧設定の取り込み",
                    "取り込む設定を選択してください。",
                    parent=preview,
                )
                return
            external_id = str(selection[0])
            candidate = candidate_by_id.get(external_id)
            reason_code = str(
                schedule_value(candidate, "reason_code", default="") or ""
            ).upper()
            original_name = str(
                schedule_value(candidate, "display_name", "name", default="") or ""
            )
            import_name = import_name_var.get().strip()
            name_conflict = reason_code in {
                "EXTERNAL_NAME_CONFLICT",
                "EXTERNAL_SCHEDULE_NAME_CONFLICT",
            } or bool(schedule_value(candidate, "requires_target_name", default=False))
            if import_name and not 1 <= len(import_name) <= 80:
                messagebox.showwarning(
                    "設定名が不正です",
                    "設定名は1～80文字で入力してください。",
                    parent=preview,
                )
                return
            can_import = (
                bool(import_name) and import_name.casefold() != original_name.casefold()
                if name_conflict
                else bool(schedule_value(candidate, "importable", default=False))
            )
            if not can_import:
                messagebox.showwarning(
                    "取り込みできない設定",
                    (
                        "同名の設定があるため、別の設定名を入力してください。"
                        if name_conflict
                        else "この候補は台帳・snapshot・識別情報を検証できないため取り込めません。"
                    ),
                    parent=preview,
                )
                return
            if not import_name:
                messagebox.showwarning(
                    "設定名が必要です",
                    "取り込み後の設定名を入力してください。",
                    parent=preview,
                )
                return
            preview.destroy()
            self._start_multi_schedule_action(
                "旧設定の取り込み",
                lambda: self._schedule_adapter.import_external(
                    external_id,
                    source_config_dir=source_dir,
                    name=(import_name if import_name != original_name else None),
                    expected_revision=self._schedule_adapter.registry_revision,
                ),
            )

        ttk.Button(
            actions, text="選択した設定を取り込む", command=import_selected
        ).pack(side=tk.LEFT)
        ttk.Button(actions, text="キャンセル", command=preview.destroy).pack(
            side=tk.RIGHT
        )

    def on_schedule_remove_external(self) -> None:
        selection = self.external_schedule_tree.selection()
        if not selection:
            return
        external_id = str(selection[0])
        view = self._external_schedule_views_by_id.get(external_id)
        if view is None or not view.allows("remove_external"):
            return
        task_name = str(schedule_value(view.status, "task_name", default="") or "")
        if not messagebox.askyesno(
            "管理外Windowsタスクの解除",
            "このアプリの登録台帳にはないWindowsタスクを解除します。\n\n"
            f"対象: {task_name}\n\n"
            "旧config、ダウンロード済みファイル、実行履歴は削除しません。"
            "この操作を続けますか？",
            parent=self.dialog,
        ):
            return
        self._start_multi_schedule_action(
            "外部タスクの解除",
            lambda: self._schedule_adapter.remove_external(external_id),
        )

    def on_schedule_manager_run_now(self) -> None:
        view = self._selected_multi_schedule()
        if view is None:
            return
        self._start_multi_schedule_action(
            "実行開始",
            lambda: self._schedule_adapter.run_now(view.schedule_id),
        )

    def _start_multi_schedule_action(
        self,
        label: str,
        operation: Callable[[], object],
        *,
        retry_editor: Optional[tuple[Optional[str], str, AppConfig]] = None,
    ) -> None:
        if self._schedule_manager_action_running:
            return
        self._schedule_manager_action_running = True
        self._schedule_action_retry_editor = retry_editor
        logger = getattr(self, "logger", None)
        if logger is not None:
            logger.info(f"定期実行操作開始: operation={label}")
        self.schedule_registration_var.set(f"{label}処理中...")
        self._update_multi_schedule_action_state()
        self._refresh_reclassification_availability()

        def worker() -> None:
            try:
                result = operation()
                if (
                    result is False
                    or schedule_value(result, "success", default=True) is False
                ):
                    failure = RuntimeError(
                        str(
                            schedule_value(
                                result,
                                "message",
                                "reason",
                                default=f"{label}処理を完了できませんでした",
                            )
                        )
                    )
                    failure.reason_code = str(
                        schedule_value(
                            result,
                            "reason_code",
                            default="SCHEDULE_OPERATION_FAILED",
                        )
                    )
                    raise failure
                error = None
            except Exception as exc:
                result, error = None, exc
            self._schedule_manager_queue.put(("action", label, result, error))

        Thread(
            target=worker,
            name="ippi-schedule-manager-action",
            daemon=True,
        ).start()

    def _finish_multi_schedule_action(
        self, label: str, result: object, error: Optional[Exception]
    ) -> None:
        self._schedule_manager_action_running = False
        self._refresh_reclassification_availability()
        retry_editor = getattr(self, "_schedule_action_retry_editor", None)
        self._schedule_action_retry_editor = None
        if error is not None:
            code = getattr(error, "reason_code", "SCHEDULE_OPERATION_FAILED")
            if code == "REGISTRATION_CONFLICT":
                message = (
                    "別の画面で定期実行設定が更新されました。"
                    "最新状態を再読み込みします。内容を確認して、"
                    "もう一度操作してください。"
                )
            else:
                message = str(error)
            self.schedule_registration_var.set(f"{label}失敗 [{code}]: {message}")
            self.schedule_registration_label.configure(foreground="#cf222e")
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.error(
                    f"定期実行操作失敗: operation={label}, reason_code={code}, "
                    f"reason={message}"
                )
            messagebox.showerror(
                f"定期実行の{label}失敗",
                f"{message}\n理由コード: {code}",
                parent=self.dialog,
            )
            self._update_multi_schedule_action_state()
            if code == "REGISTRATION_CONFLICT":
                self._schedule_editor_reopen_after_refresh = retry_editor
                self.request_multi_schedule_refresh()
            elif retry_editor is not None:
                self.dialog.after(
                    0,
                    lambda draft=retry_editor: self._reopen_schedule_editor_draft(
                        draft
                    ),
                )
            return
        result_code = str(schedule_value(result, "reason_code", default="") or "")
        if result_code == "EXTERNAL_TASK_CLEANUP_PENDING":
            result_status = schedule_value(result, "status")
            warnings = schedule_value(result, "warnings", default=()) or ()
            warning = str(
                schedule_value(
                    result,
                    "repair_reason",
                    default=schedule_value(
                        result_status,
                        "repair_reason",
                        default=(
                            "、".join(str(item) for item in warnings)
                            or "旧Windowsタスクの解除が残っています"
                        ),
                    ),
                )
            )
            self.schedule_registration_var.set(
                f"{label}完了（後処理警告） [{result_code}]: {warning}"
            )
            self.schedule_registration_label.configure(foreground="#9a6700")
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning(
                    f"定期実行操作完了（警告）: operation={label}, "
                    f"reason_code={result_code}, reason={warning}"
                )
            messagebox.showwarning(
                f"定期実行の{label}完了（警告）",
                f"{warning}\n理由コード: {result_code}",
                parent=self.dialog,
            )
        else:
            self.schedule_registration_var.set(f"{label}が完了しました。")
            self.schedule_registration_label.configure(foreground="#1a7f37")
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.info(f"定期実行操作成功: operation={label}")
        self.request_multi_schedule_refresh()

    def _update_schedule_fields(self):
        """選択中のスケジュール方式に必要な入力だけを有効にする。"""
        interval = self.schedule_interval_var.get()
        self.schedule_weekday_combo.configure(
            state="readonly" if interval in {"1週間", "毎週"} else "disabled"
        )
        self.schedule_day_of_month_spinbox.configure(
            state="normal" if interval in {"1か月", "毎月"} else "disabled"
        )

    def _on_test_schedule_notification(self) -> None:
        """旧単一設定画面でもTkを停止させずに通知を確認する。"""

        if self._schedule_test_notification_running:
            return
        self._schedule_test_notification_running = True
        self.btn_schedule_test_notification.configure(state="disabled")

        def worker() -> None:
            try:
                result = ScheduleEditorDialog._send_test_notification()
                error = None
            except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
                result, error = None, str(exc)
            if getattr(self, "_schedule_manager_closed", False):
                return
            try:
                self.dialog.after(
                    0,
                    self._finish_test_schedule_notification,
                    result,
                    error,
                )
            except tk.TclError:
                pass

        Thread(
            target=worker,
            name="ippi-test-notification",
            daemon=True,
        ).start()

    def _finish_test_schedule_notification(
        self,
        result: object,
        error: Optional[str] = None,
    ) -> None:
        self._schedule_test_notification_running = False
        if getattr(self, "_schedule_manager_closed", False):
            return
        self.btn_schedule_test_notification.configure(state="normal")
        if error or not ScheduleEditorDialog._test_notification_succeeded(result):
            reason_code = str(
                getattr(result, "reason_code", "NOTIFICATION_FAILED")
                or "NOTIFICATION_FAILED"
            )
            detail = error or str(
                getattr(result, "reason", "通知を表示できませんでした")
            )
            messagebox.showwarning(
                "テスト通知",
                f"{detail} [{reason_code}]\n実行結果はログから確認できます。",
                parent=self.dialog,
            )
            return
        messagebox.showinfo(
            "テスト通知",
            "テスト通知を送信しました。",
            parent=self.dialog,
        )

    def _get_current_main_config(self) -> AppConfig:
        """メイン画面のTk変数をメインスレッドでスナップショット化する。"""
        if self.current_config_provider is None:
            return deepcopy(self.config)
        current = self.current_config_provider()
        if not isinstance(current, AppConfig):
            raise ValueError("現在の検索条件を取得できませんでした")
        return deepcopy(current)

    def on_use_current_search_conditions(self):
        """現在表示中の検索条件を登録候補へ明示的に取り込む。"""
        try:
            current = self._get_current_main_config()
            valid, errors = self.config_manager.validate_config(current)
            if not valid:
                messagebox.showerror(
                    "検索条件エラー",
                    "現在の検索条件を定期実行へ使用できません:\n"
                    + "\n".join(f"・{error}" for error in errors),
                    parent=self.dialog,
                )
                return
            self._schedule_profile_config = current
            self._loaded_search_conditions = deepcopy(current.search_conditions)
            self.schedule_condition_var.set(format_schedule_condition_summary(current))
            self.schedule_registration_var.set(
                "現在の検索条件を取り込みました。保存するとWindowsタスクへ反映します。"
            )
        except (TypeError, ValueError) as exc:
            messagebox.showerror("検索条件エラー", str(exc), parent=self.dialog)

    def _get_schedule_status(self, config: Optional[AppConfig] = None) -> object:
        if self.schedule_service is None:
            return None
        get_status = getattr(self.schedule_service, "get_status", None)
        if not callable(get_status):
            return None
        target = config or self.config
        try:
            return get_status(config=target, current_config=target)
        except TypeError:
            try:
                return get_status(target)
            except TypeError:
                return get_status()

    @staticmethod
    def _status_registered(status: object) -> bool:
        if status is None:
            return False
        if isinstance(status, bool):
            return status
        if isinstance(status, dict):
            return bool(status.get("registered"))
        return bool(getattr(status, "registered", False))

    def _status_requires_cleanup(self, status: object) -> bool:
        """無効保存前に、タスクまたは登録メタデータの除去が必要か判定する。"""
        if self._status_registered(status):
            return True
        state_value = (
            status.get("state", "")
            if isinstance(status, dict)
            else getattr(status, "state", "")
        )
        state = str(getattr(state_value, "value", state_value)).lower()
        if state in {
            "registered",
            "update_required",
            "repair_required",
            "running",
            "last_failed",
        }:
            return True
        for name in ("repair_reason", "reason_code", "profile_id"):
            value = (
                status.get(name)
                if isinstance(status, dict)
                else getattr(status, name, None)
            )
            if value:
                return True
        schedule = self.config.schedule
        return bool(schedule.enabled or getattr(schedule, "active_profile_id", None))

    def refresh_schedule_status(self):
        """登録状態と履歴を設定タブへ反映する。"""
        if not hasattr(self, "schedule_registration_var"):
            return
        try:
            status = self._get_schedule_status()
            if status is None:
                backend = getattr(self.config.schedule, "backend", "legacy")
                requires_migration = bool(
                    getattr(self.config.schedule, "requires_migration", False)
                )
                if requires_migration or (
                    self.config.schedule.enabled and backend != "windows_task_scheduler"
                ):
                    text = "Windowsタスクへ移行が必要です。設定を確認して保存してください。"
                    colour = "#9a6700"
                else:
                    text = "無効（Windowsタスクは登録されていません）"
                    colour = "#666666"
            else:
                value = (
                    status.get("state")
                    if isinstance(status, dict)
                    else getattr(status, "state", "")
                )
                state = getattr(value, "value", value)
                running = bool(
                    status.get("running", False)
                    if isinstance(status, dict)
                    else getattr(status, "running", False)
                )
                mismatch = bool(
                    status.get("definition_mismatch", False)
                    if isinstance(status, dict)
                    else getattr(status, "definition_mismatch", False)
                )
                repair = (
                    status.get("repair_reason")
                    if isinstance(status, dict)
                    else getattr(status, "repair_reason", None)
                )
                next_run = (
                    status.get("next_run")
                    if isinstance(status, dict)
                    else getattr(status, "next_run", None)
                )
                reason_code = (
                    status.get("reason_code")
                    if isinstance(status, dict)
                    else getattr(status, "reason_code", None)
                )
                last_result_value = (
                    status.get("last_result")
                    if isinstance(status, dict)
                    else getattr(status, "last_result", None)
                )
                state_key = str(state).lower()
                last_result_key = str(
                    getattr(last_result_value, "value", last_result_value) or ""
                ).lower()
                if running:
                    label, colour = "実行中", "#0969da"
                elif repair or state_key in {"repair_required", "needs_repair"}:
                    label, colour = "要修復", "#cf222e"
                elif mismatch or state_key in {"update_required", "needs_update"}:
                    label, colour = "要更新", "#9a6700"
                elif state_key in {"last_failed", "failed"} or last_result_key in {
                    "partial",
                    "partial_failure",
                    "failed",
                    "failure",
                    "error",
                }:
                    label, colour = "前回失敗", "#cf222e"
                elif self._status_registered(status):
                    label, colour = "登録済み", "#1a7f37"
                else:
                    label, colour = "無効", "#666666"
                detail = repair or reason_code
                text = f"{label} / 次回実行: {_format_datetime(next_run)}"
                if detail:
                    text += f" / {detail}"
            if bool(getattr(self.config.schedule, "requires_migration", False)):
                text = (
                    "Windowsタスクへ移行が必要です。"
                    "検索条件を確認して保存してください。"
                )
                colour = "#9a6700"
            self.schedule_registration_var.set(text)
            self.schedule_registration_label.configure(foreground=colour)
            self._show_registered_condition_summary(status)
        except Exception as exc:  # schtasksの診断失敗も画面を閉じない
            self.logger.warning(f"定期実行の登録状態を確認できません: {exc}")
            self.schedule_registration_var.set(
                f"要修復 / 状態確認に失敗しました [STATUS_QUERY_FAILED]: {exc}"
            )
            self.schedule_registration_label.configure(foreground="#cf222e")

        self._refresh_schedule_history()

    def _show_registered_condition_summary(self, status: object) -> None:
        """画面入力ではなく、タスクが実際に参照する固定条件を表示する。"""

        if not self._status_registered(status):
            return
        getter = getattr(
            getattr(self, "schedule_service", None),
            "get_registered_config",
            None,
        )
        if not callable(getter):
            return
        registered = getter()
        if not isinstance(registered, AppConfig):
            return
        self._schedule_profile_config = deepcopy(registered)
        self.schedule_condition_var.set(
            "登録済みスナップショット:\n"
            + format_schedule_condition_summary(registered)
        )

    def _refresh_schedule_history(self):
        if not hasattr(self, "schedule_history_tree"):
            return
        for item in self.schedule_history_tree.get_children():
            self.schedule_history_tree.delete(item)
        if self.schedule_service is None:
            return
        history = getattr(self.schedule_service, "history", None)
        if not callable(history):
            return
        try:
            records = history(limit=20)
        except TypeError:
            records = history(20)
        except Exception as exc:
            self.logger.warning(f"定期実行履歴を読み込めません: {exc}")
            return
        for record in records or []:
            new_count = _record_value(record, "new_count", "saved", default=0)
            existing_count = _record_value(
                record, "existing_count", "saved_count", "reused", default=0
            )
            failed_count = _record_value(record, "failed_count", "failed", default=0)
            self.schedule_history_tree.insert(
                "",
                tk.END,
                values=(
                    _format_datetime(_record_value(record, "started_at")),
                    _format_datetime(_record_value(record, "finished_at", "ended_at")),
                    _format_schedule_result(_record_value(record, "result", "outcome")),
                    f"{new_count}/{existing_count}/{failed_count}",
                    _record_value(record, "retry_count", default=0),
                    format_schedule_reason(_record_value(record, "reason_code")),
                ),
            )

    def setup_search_tab(self, parent: ttk.Frame):
        """検索条件タブをセットアップ（i-ppi.jpの検索条件を網羅）"""
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

        # 発注機関（リスト検索）
        hachu_frame = ttk.LabelFrame(
            scrollable_frame, text="発注機関（リスト検索）", padding="5"
        )
        hachu_frame.pack(fill=tk.X, pady=(0, 10))

        hachu_input_frame = ttk.Frame(hachu_frame)
        hachu_input_frame.pack(fill=tk.X)

        ttk.Label(hachu_input_frame, text="大分類:").pack(side=tk.LEFT, padx=(0, 5))
        self.hachu_daibunrui_var = tk.StringVar()
        ttk.Combobox(
            hachu_input_frame,
            textvariable=self.hachu_daibunrui_var,
            # 発注機関は公式サイト取得結果だけを表示する。固定候補は持たない。
            values=[],
            state="readonly",
            width=25,
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(hachu_input_frame, text="中分類:").pack(side=tk.LEFT, padx=(0, 5))
        self.hachu_chubunrui_var = tk.StringVar()
        ttk.Combobox(
            hachu_input_frame,
            textvariable=self.hachu_chubunrui_var,
            values=[],
            state="readonly",
            width=25,
        ).pack(side=tk.LEFT)

        # 工事名（文字列検索）
        koji_name_frame = ttk.LabelFrame(
            scrollable_frame, text="工事名（文字列検索）", padding="5"
        )
        koji_name_frame.pack(fill=tk.X, pady=(0, 10))

        self.koji_name_var = tk.StringVar()
        ttk.Entry(koji_name_frame, textvariable=self.koji_name_var, width=60).pack(
            fill=tk.X
        )
        ttk.Label(
            koji_name_frame,
            text="※条件の複数指定はできません。",
            font=("", 8),
            foreground="gray",
        ).pack(anchor=tk.W, pady=(5, 0))

        # 工事場所（リスト検索）
        koji_place_list_frame = ttk.LabelFrame(
            scrollable_frame, text="工事場所（リスト検索）", padding="5"
        )
        koji_place_list_frame.pack(fill=tk.X, pady=(0, 10))

        place_list_input_frame = ttk.Frame(koji_place_list_frame)
        place_list_input_frame.pack(fill=tk.X)

        self.place_list_radio_var = tk.StringVar(value="list")
        ttk.Radiobutton(
            place_list_input_frame,
            text="リスト検索",
            variable=self.place_list_radio_var,
            value="list",
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(place_list_input_frame, text="地方:").pack(side=tk.LEFT, padx=(0, 5))
        self.place_chihou_var = tk.StringVar()
        ttk.Combobox(
            place_list_input_frame,
            textvariable=self.place_chihou_var,
            values=[
                "",
                "北海道",
                "東北",
                "関東",
                "北陸",
                "中部",
                "近畿",
                "中国",
                "四国",
                "九州・沖縄",
            ],
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(place_list_input_frame, text="都道府県:").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.place_todofuken_var = tk.StringVar()
        ttk.Combobox(
            place_list_input_frame,
            textvariable=self.place_todofuken_var,
            values=[],
            state="readonly",
            width=15,
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(place_list_input_frame, text="市町村:").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.place_shichouson_var = tk.StringVar()
        ttk.Combobox(
            place_list_input_frame,
            textvariable=self.place_shichouson_var,
            values=[],
            state="readonly",
            width=15,
        ).pack(side=tk.LEFT)

        # 工事場所（文字列検索）
        koji_place_text_frame = ttk.LabelFrame(
            scrollable_frame, text="工事場所（文字列検索）", padding="5"
        )
        koji_place_text_frame.pack(fill=tk.X, pady=(0, 10))

        place_text_input_frame = ttk.Frame(koji_place_text_frame)
        place_text_input_frame.pack(fill=tk.X)

        ttk.Radiobutton(
            place_text_input_frame,
            text="文字列検索",
            variable=self.place_list_radio_var,
            value="text",
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.place_text_var = tk.StringVar()
        place_text_entry = ttk.Entry(
            place_text_input_frame, textvariable=self.place_text_var, width=40
        )
        place_text_entry.pack(side=tk.LEFT)
        place_text_entry.config(state="disabled")

        def on_place_radio_change():
            if self.place_list_radio_var.get() == "text":
                place_text_entry.config(state="normal")
            else:
                place_text_entry.config(state="disabled")

        self.place_list_radio_var.trace("w", lambda *args: on_place_radio_change())

        # 入札契約方式
        contract_frame = ttk.LabelFrame(
            scrollable_frame, text="入札契約方式", padding="5"
        )
        contract_frame.pack(fill=tk.X, pady=(0, 10))

        self.contract_vars = {}
        contract_types = [
            "一般競争入札",
            "公募型指名競争入札",
            "指名競争入札",
            "随意契約",
            "その他方式",
        ]
        for contract_type in contract_types:
            var = tk.BooleanVar(value=True)
            self.contract_vars[contract_type] = var
            ttk.Checkbutton(contract_frame, text=contract_type, variable=var).pack(
                anchor=tk.W
            )

        # 最終更新日
        update_date_frame = ttk.LabelFrame(
            scrollable_frame, text="最終更新日", padding="5"
        )
        update_date_frame.pack(fill=tk.X, pady=(0, 10))

        self.update_date_radio_var = tk.StringVar(value="none")
        ttk.Radiobutton(
            update_date_frame,
            text="指定なし",
            variable=self.update_date_radio_var,
            value="none",
        ).pack(anchor=tk.W)

        update_date_input_frame = ttk.Frame(update_date_frame)
        update_date_input_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Radiobutton(
            update_date_input_frame,
            text="過去",
            variable=self.update_date_radio_var,
            value="past",
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.update_date_days_var = tk.StringVar()
        update_date_entry = ttk.Entry(
            update_date_input_frame, textvariable=self.update_date_days_var, width=5
        )
        update_date_entry.pack(side=tk.LEFT, padx=(0, 5))
        update_date_entry.config(state="disabled")
        ttk.Label(update_date_input_frame, text="日以内").pack(side=tk.LEFT)

        def on_update_date_radio_change():
            if self.update_date_radio_var.get() == "past":
                update_date_entry.config(state="normal")
            else:
                update_date_entry.config(state="disabled")

        self.update_date_radio_var.trace(
            "w", lambda *args: on_update_date_radio_change()
        )

        # 公告日
        koukoku_date_frame = ttk.LabelFrame(
            scrollable_frame, text="公告日", padding="5"
        )
        koukoku_date_frame.pack(fill=tk.X, pady=(0, 10))

        self.koukoku_date_radio_var = tk.StringVar(value="none")
        ttk.Radiobutton(
            koukoku_date_frame,
            text="指定なし",
            variable=self.koukoku_date_radio_var,
            value="none",
        ).pack(anchor=tk.W)

        koukoku_date_input_frame = ttk.Frame(koukoku_date_frame)
        koukoku_date_input_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Radiobutton(
            koukoku_date_input_frame,
            text="期間指定",
            variable=self.koukoku_date_radio_var,
            value="range",
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(koukoku_date_input_frame, text="から").pack(side=tk.LEFT, padx=(0, 5))
        self.koukoku_date_start_var = tk.StringVar()
        ttk.Entry(
            koukoku_date_input_frame, textvariable=self.koukoku_date_start_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(koukoku_date_input_frame, text="(YYYY-MM-DD)").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        ttk.Label(koukoku_date_input_frame, text="まで").pack(side=tk.LEFT, padx=(0, 5))
        self.koukoku_date_end_var = tk.StringVar()
        ttk.Entry(
            koukoku_date_input_frame, textvariable=self.koukoku_date_end_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(koukoku_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # 開札日
        kaisatsu_date_frame = ttk.LabelFrame(
            scrollable_frame, text="開札日", padding="5"
        )
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

        ttk.Label(kaisatsu_date_input_frame, text="から").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.kaisatsu_date_start_var = tk.StringVar()
        ttk.Entry(
            kaisatsu_date_input_frame,
            textvariable=self.kaisatsu_date_start_var,
            width=12,
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(kaisatsu_date_input_frame, text="(YYYY-MM-DD)").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        ttk.Label(kaisatsu_date_input_frame, text="まで").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.kaisatsu_date_end_var = tk.StringVar()
        ttk.Entry(
            kaisatsu_date_input_frame, textvariable=self.kaisatsu_date_end_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(kaisatsu_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # 契約日
        keiyaku_date_frame = ttk.LabelFrame(
            scrollable_frame, text="契約日", padding="5"
        )
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
        ttk.Label(keiyaku_date_input_frame, text="(YYYY-MM-DD)").pack(
            side=tk.LEFT, padx=(0, 10)
        )

        ttk.Label(keiyaku_date_input_frame, text="まで").pack(side=tk.LEFT, padx=(0, 5))
        self.keiyaku_date_end_var = tk.StringVar()
        ttk.Entry(
            keiyaku_date_input_frame, textvariable=self.keiyaku_date_end_var, width=12
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(keiyaku_date_input_frame, text="(YYYY-MM-DD)").pack(side=tk.LEFT)

        # 工事種別
        koji_shubetsu_frame = ttk.LabelFrame(
            scrollable_frame, text="工事種別", padding="5"
        )
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
        koji_gyoushu_frame = ttk.LabelFrame(
            scrollable_frame, text="工事の業種", padding="5"
        )
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
        yotei_price_frame = ttk.LabelFrame(
            scrollable_frame, text="予定価格（範囲指定）", padding="5"
        )
        yotei_price_frame.pack(fill=tk.X, pady=(0, 10))

        price_input_frame = ttk.Frame(yotei_price_frame)
        price_input_frame.pack(fill=tk.X)

        self.yotei_price_min_var = tk.StringVar()
        ttk.Entry(
            price_input_frame, textvariable=self.yotei_price_min_var, width=15
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(price_input_frame, text="（円）～").pack(side=tk.LEFT, padx=(0, 5))
        self.yotei_price_max_var = tk.StringVar()
        ttk.Entry(
            price_input_frame, textvariable=self.yotei_price_max_var, width=15
        ).pack(side=tk.LEFT, padx=(0, 5))
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
            rakusatsu_price_input_frame,
            textvariable=self.rakusatsu_price_min_var,
            width=15,
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(rakusatsu_price_input_frame, text="（円）～").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.rakusatsu_price_max_var = tk.StringVar()
        ttk.Entry(
            rakusatsu_price_input_frame,
            textvariable=self.rakusatsu_price_max_var,
            width=15,
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(rakusatsu_price_input_frame, text="（円）").pack(side=tk.LEFT)

        # 落札者名／契約者名（文字列検索）
        rakusatsu_name_frame = ttk.LabelFrame(
            scrollable_frame, text="落札者名／契約者名（文字列検索）", padding="5"
        )
        rakusatsu_name_frame.pack(fill=tk.X, pady=(0, 10))

        self.rakusatsu_name_var = tk.StringVar()
        ttk.Entry(
            rakusatsu_name_frame, textvariable=self.rakusatsu_name_var, width=60
        ).pack(fill=tk.X)
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
        ttk.Checkbutton(
            denshi_frame, text="対象案件のみ", variable=self.denshi_var
        ).pack(anchor=tk.W)

        # 公開文書
        koukai_frame = ttk.LabelFrame(scrollable_frame, text="公開文書", padding="5")
        koukai_frame.pack(fill=tk.X, pady=(0, 10))

        self.koukai_var = tk.BooleanVar()
        ttk.Checkbutton(koukai_frame, text="公開中のみ", variable=self.koukai_var).pack(
            anchor=tk.W
        )

        # 一覧画面の表示件数
        display_count_frame = ttk.LabelFrame(
            scrollable_frame, text="一覧画面の表示件数", padding="5"
        )
        display_count_frame.pack(fill=tk.X, pady=(0, 10))

        self.display_count_var = tk.StringVar(value="20")
        ttk.Combobox(
            display_count_frame,
            textvariable=self.display_count_var,
            values=["20", "30", "50", "100"],
            state="readonly",
            width=10,
        ).pack(anchor=tk.W)

        bind_search_comboboxes_to_canvas(scrollable_frame, canvas)
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
        ttk.Button(log_file_frame, text="参照", command=self.on_browse_log_file).pack(
            side=tk.LEFT
        )

        log_size_frame = ttk.Frame(log_frame)
        log_size_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(log_size_frame, text="最大ファイルサイズ:").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.log_max_bytes_var = tk.StringVar()
        ttk.Entry(log_size_frame, textvariable=self.log_max_bytes_var, width=10).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Label(log_size_frame, text="MB").pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(log_size_frame, text="バックアップファイル数:").pack(
            side=tk.LEFT, padx=(0, 5)
        )
        self.log_backup_count_var = tk.StringVar()
        ttk.Entry(log_size_frame, textvariable=self.log_backup_count_var, width=5).pack(
            side=tk.LEFT
        )

    def load_config_to_ui(self, config: Optional[AppConfig] = None):
        """設定をUIに読み込む"""
        if config is None:
            config = self.config

        # 対象URL
        self._loaded_target_urls = tuple(config.target_urls)
        self.url_listbox.configure(state=tk.NORMAL)
        self.url_listbox.delete(0, tk.END)
        for url in config.target_urls:
            self.url_listbox.insert(tk.END, url)
        self.url_listbox.configure(state=tk.DISABLED)

        # データルート
        self._loaded_save_paths = deepcopy(config.save_paths)
        self.save_path_var.set(config.save_paths.local)
        self._refresh_storage_preview()

        # ファイル命名規則
        self.naming_rule_var.set(config.naming_rule)

        # ダウンロード条件
        conditions = config.download_conditions
        self.file_types_var.set(", ".join(conditions.file_types or []))
        self.keywords_var.set(", ".join(conditions.keywords or []))
        date_range = conditions.date_range or {}
        self.download_date_start_var.set(date_range.get("start") or "")
        self.download_date_end_var.set(date_range.get("end") or "")

        # 複数スケジュールはタブ内で1件ずつ即時保存する。旧単一形式だけ
        # SettingsDialog全体の保存対象として扱う。
        if getattr(self, "_multi_schedule_mode", False):
            self.request_multi_schedule_refresh()
        else:
            self.schedule_enabled_var.set(config.schedule.enabled)
            interval_map = {
                "daily": "毎日",
                "weekly": "毎週",
                "monthly": "毎月",
            }
            self.schedule_interval_var.set(
                interval_map.get(config.schedule.interval, "毎日")
            )
            self.schedule_time_var.set(config.schedule.time)
            weekday_map = {
                "monday": "月曜日",
                "tuesday": "火曜日",
                "wednesday": "水曜日",
                "thursday": "木曜日",
                "friday": "金曜日",
                "saturday": "土曜日",
                "sunday": "日曜日",
            }
            self.schedule_weekday_var.set(
                weekday_map.get(config.schedule.weekday, "月曜日")
            )
            self.schedule_day_of_month_var.set(str(config.schedule.day_of_month))
            self.schedule_start_when_available_var.set(
                bool(getattr(config.schedule, "start_when_available", True))
            )
            self.schedule_wake_to_run_var.set(
                bool(getattr(config.schedule, "wake_to_run", False))
            )
            self.schedule_retry_count_var.set(
                str(getattr(config.schedule, "retry_count", 2))
            )
            self.schedule_retry_interval_var.set(
                str(getattr(config.schedule, "retry_interval_minutes", 15))
            )
            self.schedule_notification_policy_var.set(
                format_schedule_notification_policy(
                    getattr(config.schedule, "notification_policy", "off")
                )
            )
            self._update_schedule_fields()
            self._schedule_profile_config = deepcopy(config)
            self.schedule_condition_var.set(format_schedule_condition_summary(config))
            self.refresh_schedule_status()

        # ログ設定
        self.log_level_var.set(config.logging.level)
        self.log_file_var.set(config.logging.file)
        self.log_max_bytes_var.set(
            str(config.logging.max_bytes // 1048576)
        )  # バイトからMBに変換
        self.log_backup_count_var.set(str(config.logging.backup_count))

    def _schedule_backend_for_save(self, enabled: bool) -> str:
        """明示登録前の旧backendを、単なる無効保存では移行済みにしない。"""
        current_schedule = self.config.schedule
        if not enabled and getattr(current_schedule, "requires_migration", False):
            return str(getattr(current_schedule, "backend", "legacy_process"))
        return "windows_task_scheduler"

    def get_config_from_ui(self) -> AppConfig:
        """UIから設定を取得"""
        # 対象URL
        target_urls = list(self._loaded_target_urls)

        # ダウンロード条件
        file_types = self._parse_list_setting(
            self.file_types_var.get(), normalize_extensions=True
        )
        keywords = self._parse_list_setting(self.keywords_var.get())
        date_start = self.download_date_start_var.get().strip()
        date_end = self.download_date_end_var.get().strip()
        date_range = (
            {"start": date_start or None, "end": date_end or None}
            if date_start or date_end
            else None
        )
        download_conditions = DownloadConditions(
            file_types=file_types,
            keywords=keywords,
            date_range=date_range,
        )

        # データルート以外の保存構成は画面に表示しつつ不変に保つ。
        save_paths = deepcopy(getattr(self, "_loaded_save_paths", None) or SavePaths())
        save_paths.local = self.save_path_var.get()

        # 複数スケジュールは管理タブで個別保存済みなので、一般設定保存では
        # 旧互換フィールドを変更しない。
        if getattr(self, "_multi_schedule_mode", False):
            schedule = deepcopy(self.config.schedule)
        else:
            interval_map = {
                "1日": "daily",
                "1週間": "weekly",
                "1か月": "monthly",
                "毎日": "daily",
                "毎週": "weekly",
                "毎月": "monthly",
            }
            weekday_map = {
                "月曜日": "monday",
                "火曜日": "tuesday",
                "水曜日": "wednesday",
                "木曜日": "thursday",
                "金曜日": "friday",
                "土曜日": "saturday",
                "日曜日": "sunday",
            }
            try:
                day_of_month = int(self.schedule_day_of_month_var.get())
            except ValueError as exc:
                raise ValueError("毎月の実行日は1～28の整数で指定してください") from exc
            try:
                retry_count = int(self.schedule_retry_count_var.get())
                retry_interval = int(self.schedule_retry_interval_var.get())
            except ValueError as exc:
                raise ValueError("再試行回数と間隔は整数で指定してください") from exc
            if retry_count < 0:
                raise ValueError("再試行回数は0以上で指定してください")
            if retry_interval < 1:
                raise ValueError("再試行間隔は1分以上で指定してください")

            schedule_enabled = self.schedule_enabled_var.get()
            schedule_backend = self._schedule_backend_for_save(schedule_enabled)
            schedule_values = {
                "enabled": schedule_enabled,
                "interval": interval_map.get(self.schedule_interval_var.get(), "daily"),
                "time": self.schedule_time_var.get(),
                "weekday": weekday_map.get(self.schedule_weekday_var.get(), "monday"),
                "day_of_month": day_of_month,
                "backend": schedule_backend,
                "timezone": "Asia/Tokyo",
                "start_when_available": (self.schedule_start_when_available_var.get()),
                "wake_to_run": self.schedule_wake_to_run_var.get(),
                "retry_count": retry_count,
                "retry_interval_minutes": retry_interval,
                "notification_policy": normalise_schedule_notification_policy(
                    self.schedule_notification_policy_var.get()
                ),
                "active_profile_id": getattr(
                    self.config.schedule, "active_profile_id", None
                ),
            }
            # モデル更新と並行するブランチでも動くよう利用可能な引数だけ渡す。
            parameters = inspect.signature(ScheduleConfig).parameters
            schedule = ScheduleConfig(
                **{
                    name: value
                    for name, value in schedule_values.items()
                    if name in parameters
                }
            )

        # ログ設定
        try:
            max_bytes = (
                int(self.log_max_bytes_var.get()) * 1048576
            )  # MBからバイトに変換
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

        # 検索条件はMainWindowでのみ編集し、設定ダイアログ保存では保持する。
        search_conditions = deepcopy(self._loaded_search_conditions)

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
        loaded = getattr(self, "_loaded_search_conditions", SearchConditions())

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
        def safe_int(value: str, label: str) -> Optional[int]:
            try:
                return int(value) if value.strip() else None
            except ValueError as exc:
                raise ValueError(f"{label}は整数で指定してください") from exc

        return SearchConditions(
            hachu_daibunrui=self.hachu_daibunrui_var.get(),
            hachu_chubunrui=self.hachu_chubunrui_var.get(),
            hachu_shoubunrui=loaded.hachu_shoubunrui,
            hachu_saibunrui=loaded.hachu_saibunrui,
            hachu_multi=list(loaded.hachu_multi or []),
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
            yotei_price_min=safe_int(self.yotei_price_min_var.get(), "予定価格の下限"),
            yotei_price_max=safe_int(self.yotei_price_max_var.get(), "予定価格の上限"),
            rakusatsu_price_min=safe_int(
                self.rakusatsu_price_min_var.get(), "落札価格の下限"
            ),
            rakusatsu_price_max=safe_int(
                self.rakusatsu_price_max_var.get(), "落札価格の上限"
            ),
            rakusatsu_name=self.rakusatsu_name_var.get(),
            denshi=self.denshi_var.get(),
            koukai=self.koukai_var.get(),
            display_count=int(self.display_count_var.get())
            if self.display_count_var.get()
            else 20,
        )

    @staticmethod
    def _parse_list_setting(
        value: str, normalize_extensions: bool = False
    ) -> List[str]:
        """カンマ区切りの入力を、順序を保った重複なしリストへ変換する。"""
        items: List[str] = []
        seen = set()
        for raw_item in value.replace("、", ",").replace("\n", ",").split(","):
            item = raw_item.strip()
            if not item:
                continue
            if normalize_extensions:
                item = item.lower()
                if not item.startswith("."):
                    item = f".{item}"
            identity = item.casefold()
            if identity not in seen:
                seen.add(identity)
                items.append(item)
        return items

    def validate_config(self) -> Tuple[bool, List[str]]:
        """設定を検証"""
        try:
            config = self.get_config_from_ui()
        except (TypeError, ValueError) as exc:
            return False, [str(exc)]
        return self.validator.validate_config(config)

    @staticmethod
    def _status_detail(status: object, fallback_code: str) -> tuple[str, str]:
        if isinstance(status, dict):
            reason = status.get("repair_reason") or status.get("message")
            code = status.get("reason_code") or fallback_code
        else:
            reason = getattr(status, "repair_reason", None) or getattr(
                status, "message", None
            )
            code = getattr(status, "reason_code", None) or fallback_code
        return str(reason or "Windowsタスクの操作に失敗しました"), str(code)

    def _register_windows_task(self, config: AppConfig) -> object:
        service = getattr(self, "schedule_service", None)
        if service is None:
            raise RuntimeError(
                "定期実行サービスを利用できません [SCHEDULE_SERVICE_UNAVAILABLE]"
            )
        register = getattr(service, "register", None) or getattr(
            service, "update", None
        )
        if not callable(register):
            raise RuntimeError(
                "Windowsタスクの登録機能を利用できません "
                "[SCHEDULE_REGISTER_UNAVAILABLE]"
            )
        return register(config)

    def _unregister_windows_task(self) -> bool:
        service = getattr(self, "schedule_service", None)
        if service is None:
            raise RuntimeError(
                "定期実行サービスを利用できません [SCHEDULE_SERVICE_UNAVAILABLE]"
            )
        unregister = getattr(service, "unregister", None) or getattr(
            service, "delete", None
        )
        if not callable(unregister):
            raise RuntimeError(
                "Windowsタスクの解除機能を利用できません [SCHEDULE_DELETE_UNAVAILABLE]"
            )
        result = unregister()
        return result is not False

    def _capture_schedule_registration(self) -> object:
        service = getattr(self, "schedule_service", None)
        capture = getattr(service, "capture_registration_state", None)
        return capture() if callable(capture) else None

    def _rollback_schedule_registration(
        self, was_registered: bool, backup: object = None
    ):
        """設定ファイル保存失敗時に、可能な範囲で以前のタスクへ戻す。"""
        try:
            restore = getattr(
                getattr(self, "schedule_service", None),
                "restore_registration_state",
                None,
            )
            if backup is not None and callable(restore):
                restore(backup)
                return
            if was_registered:
                self._register_windows_task(deepcopy(self.config))
            else:
                self._unregister_windows_task()
        except Exception as exc:
            self.logger.error(f"定期実行登録のロールバックに失敗しました: {exc}")

    def _confirm_storage_layout_v4(self, config: AppConfig) -> bool:
        """v3を黙って再解釈せず、今後分だけをv4へ切り替える。"""

        try:
            layout_version = int(config.save_paths.layout_version)
        except (TypeError, ValueError):
            return False
        if layout_version != 3:
            return False
        accepted = messagebox.askyesno(
            "保存フォルダーの分離",
            "今後ダウンロードする文書を、データルート直下で\n"
            "「工事の検索（入札の経過）」と\n"
            "「業務の検索（入札の経過）」に分けますか？\n\n"
            "既存のファイルと履歴は移動・変更しません。\n"
            "同じ文書が新しい保存先へ再取得される場合があります。",
            parent=self.dialog,
        )
        if accepted:
            config.save_paths.layout_version = 4
        return accepted

    def _migrate_registered_schedule_layouts(self) -> dict[str, object]:
        adapter = getattr(self, "_schedule_adapter", None)
        if adapter is None:
            return {"migrated": (), "unchanged": (), "failed": {}}
        return adapter.migrate_storage_layout_v4()

    def on_save(self):
        """保存ボタンのハンドラ"""
        # 検証
        is_valid, errors = self.validate_config()
        if not is_valid:
            error_message = "設定にエラーがあります:\n" + "\n".join(
                f"・{error}" for error in errors
            )
            messagebox.showerror("設定エラー", error_message)
            return

        if getattr(self, "_multi_schedule_mode", False):
            try:
                config = self.get_config_from_ui()
                layout_upgraded = self._confirm_storage_layout_v4(config)
                if not self.config_manager.save_config(config):
                    raise RuntimeError("設定の保存に失敗しました [CONFIG_SAVE_FAILED]")
                migration = (
                    self._migrate_registered_schedule_layouts()
                    if layout_upgraded
                    else {"migrated": (), "failed": {}}
                )
                self.result = config
                failed = dict(migration.get("failed", {}) or {})
                if failed:
                    detail = "\n".join(
                        f"・{schedule_id}: {reason}"
                        for schedule_id, reason in failed.items()
                    )
                    messagebox.showwarning(
                        "定期実行の保存先更新",
                        "一般設定は保存しましたが、一部の定期実行はv3の"
                        "保存先を維持しています。定期実行一覧で「現在の条件を使用」"
                        f"して保存し直してください。\n{detail}",
                        parent=self.dialog,
                    )
                messagebox.showinfo(
                    "設定",
                    "一般設定を保存しました。定期実行条件は一覧の操作ごとに保存済みです。"
                    + (
                        f"\n{len(tuple(migration.get('migrated', ()) or ()))}件の"
                        "定期実行を新しい保存構成へ更新しました。"
                        if layout_upgraded
                        else ""
                    ),
                    parent=self.dialog,
                )
                self._close_schedule_manager_poll()
                self.dialog.destroy()
            except Exception as exc:
                messagebox.showerror("設定エラー", str(exc), parent=self.dialog)
            return

        # Windowsタスクを先に確定し、失敗時は有効に見える設定を保存しない。
        try:
            config = self.get_config_from_ui()
            self._confirm_storage_layout_v4(config)
            previous_status = self._get_schedule_status(self.config)
            was_registered = self._status_registered(previous_status)
            cleanup_required = self._status_requires_cleanup(previous_status)
            registration_backup = (
                self._capture_schedule_registration()
                if config.schedule.enabled or cleanup_required
                else None
            )
            registration_changed = False
            registration_status: object = None
            operation_label = "登録"

            if config.schedule.enabled:
                # 登録直前にMainWindowから再取得し、画面に見えている検索条件を
                # スナップショットへ固定する。設定ダイアログ内の保存先等は保持する。
                current = self._get_current_main_config()
                current.search_conditions = deepcopy(current.search_conditions)
                config.search_conditions = current.search_conditions
                valid, current_errors = self.config_manager.validate_config(config)
                if not valid:
                    messagebox.showerror(
                        "検索条件エラー",
                        "現在の検索条件を定期実行へ使用できません:\n"
                        + "\n".join(f"・{error}" for error in current_errors),
                        parent=self.dialog,
                    )
                    return
                self._schedule_profile_config = deepcopy(config)
                self.schedule_condition_var.set(
                    format_schedule_condition_summary(config)
                )
                if not messagebox.askyesno(
                    "定期実行の登録",
                    "現在表示している検索条件を固定して、Windowsタスクを登録・更新しますか？",
                    parent=self.dialog,
                ):
                    self.schedule_registration_var.set(
                        "登録・更新を取り消しました。設定はまだ保存されていません。"
                    )
                    return
                registration_status = self._register_windows_task(config)
                if not self._status_registered(registration_status):
                    reason, code = self._status_detail(
                        registration_status, "TASK_REGISTER_FAILED"
                    )
                    self.schedule_registration_var.set(f"登録失敗 [{code}]: {reason}")
                    self.schedule_registration_label.configure(foreground="#cf222e")
                    messagebox.showerror(
                        "定期実行の登録失敗",
                        f"{reason}\n理由コード: {code}",
                        parent=self.dialog,
                    )
                    return
                registration_changed = True
                profile_id = (
                    registration_status.get("profile_id")
                    if isinstance(registration_status, dict)
                    else getattr(registration_status, "profile_id", None)
                )
                if profile_id and hasattr(config.schedule, "active_profile_id"):
                    config.schedule.active_profile_id = profile_id
            elif cleanup_required:
                operation_label = "解除"
                if not self._unregister_windows_task():
                    code = "TASK_DELETE_FAILED"
                    self.schedule_registration_var.set(
                        f"解除失敗 [{code}]: 登録済みタスクを削除できませんでした"
                    )
                    self.schedule_registration_label.configure(foreground="#cf222e")
                    messagebox.showerror(
                        "定期実行の解除失敗",
                        "登録済みWindowsタスクを削除できませんでした。\n"
                        f"理由コード: {code}",
                        parent=self.dialog,
                    )
                    return
                registration_changed = True
                if hasattr(config.schedule, "active_profile_id"):
                    config.schedule.active_profile_id = None

            if not config.schedule.enabled and hasattr(
                config.schedule, "active_profile_id"
            ):
                config.schedule.active_profile_id = None

            try:
                saved = self.config_manager.save_config(config)
            except Exception:
                if registration_changed:
                    self._rollback_schedule_registration(
                        was_registered, registration_backup
                    )
                raise
            if saved:
                self.result = config
                if config.schedule.enabled:
                    next_run = (
                        registration_status.get("next_run")
                        if isinstance(registration_status, dict)
                        else getattr(registration_status, "next_run", None)
                    )
                    message = (
                        "設定を保存し、Windowsタスクへ登録しました。\n"
                        f"次回実行: {_format_datetime(next_run)}"
                    )
                else:
                    message = "設定を保存しました。定期実行は無効です。"
                messagebox.showinfo("設定", message, parent=self.dialog)
                self._close_schedule_manager_poll()
                self.dialog.destroy()
            else:
                if registration_changed:
                    self._rollback_schedule_registration(
                        was_registered, registration_backup
                    )
                messagebox.showerror(
                    "エラー",
                    "設定の保存に失敗しました [CONFIG_SAVE_FAILED]",
                    parent=self.dialog,
                )
        except (TypeError, ValueError) as exc:
            messagebox.showerror("設定エラー", str(exc), parent=self.dialog)
        except Exception as exc:
            self.logger.error(f"定期実行設定の保存に失敗しました: {exc}")
            reason_code = getattr(exc, "reason_code", "TASK_OPERATION_FAILED")
            self.schedule_registration_var.set(
                f"{locals().get('operation_label', '登録')}失敗 [{reason_code}]: {exc}"
            )
            self.schedule_registration_label.configure(foreground="#cf222e")
            messagebox.showerror(
                "定期実行エラー",
                f"{exc}\n理由コード: {reason_code}",
                parent=self.dialog,
            )

    def on_cancel(self):
        """キャンセルボタンのハンドラ"""
        self._close_schedule_manager_poll()
        self.dialog.destroy()

    def _close_schedule_manager_poll(self) -> None:
        self._schedule_manager_closed = True
        reclassification = getattr(self, "_reclassification_dialog", None)
        if reclassification is not None:
            try:
                reclassification.close()
            except tk.TclError:
                pass
            self._reclassification_dialog = None
        for attribute in (
            "_schedule_manager_after_id",
            "_schedule_manager_refresh_after_id",
        ):
            after_id = getattr(self, attribute, None)
            if after_id is None:
                continue
            try:
                self.dialog.after_cancel(after_id)
            except tk.TclError:
                pass
            setattr(self, attribute, None)

    def on_reset(self):
        """デフォルトに戻すボタンのハンドラ"""
        if messagebox.askyesno("確認", "すべての設定をデフォルト値に戻しますか？"):
            default_config = self.config_manager.get_default_config()
            self.load_config_to_ui(default_config)

    def on_add_url(self):
        """旧呼び出しとの互換用。対象URLは編集させない。"""

        messagebox.showinfo("対象URL", "対象URLは公式検索画面に固定されています")

    def on_remove_url(self):
        """旧呼び出しとの互換用。対象URLは編集させない。"""

        messagebox.showinfo("対象URL", "対象URLは公式検索画面に固定されています")

    def on_browse_path(self):
        """データルート参照ボタンのハンドラ"""
        path = filedialog.askdirectory(initialdir=self.save_path_var.get())
        if path:
            self.save_path_var.set(path)

    def _reclassification_block_reason(self) -> str:
        """実行中・順番待ちなど、再分類を開始できない理由を返す。"""

        if bool(getattr(self, "_schedule_manager_action_running", False)):
            return "定期実行設定を更新中のため、完了後に再分類してください"

        provider = getattr(
            self,
            "reclassification_block_reason_provider",
            None,
        )
        if provider is not None:
            try:
                reason = str(provider() or "").strip()
            except Exception as exc:
                return f"実行状態を確認できません: {exc}"
            if reason:
                return reason

        # 設定画面が取得済みの状態も補助的に確認する。最終的な排他は
        # 再分類サービス側で再検証する。
        for view in getattr(self, "_schedule_views", ()):
            status = getattr(view, "status", None)
            state = (
                str(
                    getattr(
                        schedule_value(status, "state", "status", default=""),
                        "value",
                        schedule_value(status, "state", "status", default=""),
                    )
                    or ""
                )
                .strip()
                .lower()
            )
            queued = bool(
                schedule_value(
                    status,
                    "queue_waiting",
                    "queued",
                    default=False,
                )
            )
            running = bool(
                schedule_value(status, "running", "is_running", default=False)
                or schedule_value(status, "retry_waiting", default=False)
            ) or state in {"running", "実行中", "retry_waiting", "retry_wait"}
            if queued or state in {"queued", "queue_waiting", "waiting", "順番待ち"}:
                return "定期実行が順番待ちのため、完了後に再分類してください"
            if running:
                if state in {"retry_waiting", "retry_wait"} or bool(
                    schedule_value(status, "retry_waiting", default=False)
                ):
                    return "定期実行が再試行待機中のため、完了後に再分類してください"
                return "定期実行中のため、完了後に再分類してください"
        return ""

    def _refresh_reclassification_availability(self) -> None:
        """サービス注入状態と実行状態をデータルート欄へ反映する。"""

        button = getattr(self, "btn_reclassify_saved", None)
        variable = getattr(self, "reclassification_status_var", None)
        if button is None or variable is None:
            return
        if getattr(self, "reclassification_service", None) is None:
            button.configure(state="disabled")
            variable.set("再分類機能を利用できません")
            return
        reason = self._reclassification_block_reason()
        button.configure(state="disabled" if reason else "normal")
        variable.set(reason or "実行前に移動候補を確認します")

    def _open_reclassification_dialog(self) -> None:
        """保存済みファイルを変更せずにプレビュー画面を開く。"""

        service = getattr(self, "reclassification_service", None)
        if service is None:
            messagebox.showwarning(
                "再分類できません",
                "再分類機能を利用できません。アプリを再起動してください。",
                parent=self.dialog,
            )
            return
        reason = self._reclassification_block_reason()
        if reason:
            self._refresh_reclassification_availability()
            messagebox.showwarning(
                "再分類できません",
                reason,
                parent=self.dialog,
            )
            return

        current = getattr(self, "_reclassification_dialog", None)
        if current is not None:
            try:
                if current.window.winfo_exists():
                    current.window.deiconify()
                    current.window.lift()
                    return
            except tk.TclError:
                pass
        try:
            scan_config = self.get_config_from_ui()
        except (TypeError, ValueError) as exc:
            messagebox.showerror(
                "保存構成エラー",
                f"現在のデータルートを確認してください。\n{exc}",
                parent=self.dialog,
            )
            return
        self.logger.info("保存済みファイル再分類のプレビューを開始します")
        self._reclassification_dialog = ReclassificationDialog(
            self.dialog,
            service,
            scan_config,
            block_reason_provider=self._reclassification_block_reason,
            logger=self.logger,
        )

    def _refresh_storage_preview(self, *_args) -> None:
        """通常実行と定期実行の解決予定パスを常時表示する。"""

        variable = getattr(self, "storage_preview_var", None)
        if variable is None:
            return
        preview_config = deepcopy(getattr(self, "config", AppConfig()))
        preview_config.save_paths = deepcopy(
            getattr(self, "_loaded_save_paths", preview_config.save_paths)
        )
        preview_config.save_paths.local = self.save_path_var.get().strip()
        try:
            normal = format_storage_preview(preview_config, RunKind.MANUAL)
            scheduled = format_storage_preview(preview_config, RunKind.SCHEDULED)
            variable.set("通常ダウンロード: " + normal + "\n定期実行: " + scheduled)
        except (TypeError, ValueError) as exc:
            variable.set(f"保存構成を確認してください: {exc}")

    def on_browse_log_file(self):
        """ログファイル参照ボタンのハンドラ"""
        path = filedialog.asksaveasfilename(
            initialdir=".",
            defaultextension=".log",
            filetypes=[("ログファイル", "*.log"), ("すべてのファイル", "*.*")],
        )
        if path:
            self.log_file_var.set(path)

    def show(self) -> Optional[AppConfig]:
        """ダイアログを表示して結果を返す"""
        self.dialog.wait_window()
        return self.result
