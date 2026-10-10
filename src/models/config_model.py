# -*- coding: utf-8 -*-

"""設定データモデル"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .search_target import SearchTarget


IPPI_OFFICIAL_SEARCH_URL = (
    "https://www.i-ppi.jp/"
    "IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
)
IPPI_OFFICIAL_GYOMU_SEARCH_URL = (
    "https://www.i-ppi.jp/"
    "IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=7"
)

@dataclass
class SearchConditions:
    """i-ppi.jp検索条件"""

    # 発注機関（リスト検索）
    hachu_daibunrui: str = ""  # 大分類
    hachu_chubunrui: str = ""  # 中分類
    hachu_shoubunrui: str = ""  # 小分類
    hachu_saibunrui: str = ""  # 細分類
    # 発注機関（複数選択検索）
    hachu_multi: List[str] = field(default_factory=list)  # 複数選択

    # 工事名
    koji_name: str = ""  # 文字列検索

    # 工事場所
    place_search_type: str = "list"  # "list" or "text"
    place_chihou: str = ""  # 地方
    place_todofuken: str = ""  # 都道府県
    place_shichouson: str = ""  # 市町村
    place_text: str = ""  # 文字列検索

    # 入札契約方式
    contract_types: List[str] = field(
        default_factory=lambda: [
            "一般競争入札",
            "公募型指名競争入札",
            "指名競争入札",
            "随意契約",
            "その他方式",
        ]
    )

    # 最終更新日
    update_date_type: str = "none"  # "none" or "past"
    update_date_days: Optional[int] = None  # 過去日以内

    # 公告日
    koukoku_date_type: str = "none"  # "none" or "range"
    koukoku_date_start: Optional[str] = None  # YYYY-MM-DD
    koukoku_date_end: Optional[str] = None  # YYYY-MM-DD

    # 開札日
    kaisatsu_date_type: str = "none"  # "none" or "range"
    kaisatsu_date_start: Optional[str] = None  # YYYY-MM-DD
    kaisatsu_date_end: Optional[str] = None  # YYYY-MM-DD

    # 契約日
    keiyaku_date_type: str = "none"  # "none" or "range"
    keiyaku_date_start: Optional[str] = None  # YYYY-MM-DD
    keiyaku_date_end: Optional[str] = None  # YYYY-MM-DD

    # 工事種別（単一選択）
    koji_shubetsu: str = ""

    # 工事の業種（単一選択）
    koji_gyoushu: str = ""

    # 予定価格
    yotei_price_min: Optional[int] = None
    yotei_price_max: Optional[int] = None

    # 落札価格／契約価格
    rakusatsu_price_min: Optional[int] = None
    rakusatsu_price_max: Optional[int] = None

    # 落札者名／契約者名
    rakusatsu_name: str = ""

    # 電子入札
    denshi: bool = False  # 対象案件のみ

    # 公開文書
    koukai: bool = False  # 公開中のみ

    # 表示件数
    display_count: int = 20  # 20, 30, 50, 100

    # 検索対象。末尾追加により既存の位置引数との互換性を維持する。
    search_target: str = SearchTarget.KOJI_KEIKA.value

    # 工事・業務に共通する正規化済み案件名。旧設定はkoji_nameへfallbackする。
    project_name: str = ""

    # 業務区分（単一選択）
    gyomu_kubun: str = ""

    @property
    def effective_project_name(self) -> str:
        """工事用旧フィールドを含めた実効案件名を返す。"""

        return str(self.project_name or self.koji_name or "").strip()

    @property
    def target(self) -> SearchTarget:
        return SearchTarget.coerce(self.search_target)

    @classmethod
    def for_target(cls, target: object) -> "SearchConditions":
        """対象に合う契約方式を持つ既定条件を生成する。"""

        from ..core.search_profiles import get_search_profile

        profile = get_search_profile(target)
        return cls(
            search_target=profile.target.value,
            contract_types=list(profile.default_contract_types),
        )


@dataclass
class DownloadConditions:
    """ダウンロード条件"""

    file_types: List[str] = field(default_factory=lambda: [".pdf", ".xlsx", ".docx"])
    keywords: List[str] = field(default_factory=list)
    date_range: Optional[dict] = None  # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}


@dataclass
class SavePaths:
    """ダウンロードデータのルートと保存レイアウト。

    ``layout_version=2`` は ``local`` 自体を保存先として扱う旧形式、v3は
    通常実行と定期実行を分離する形式、v4はその上位で工事と業務を
    分離する形式である。旧YAMLのv2判定はConfigManagerが行う。
    """

    local: str = "./downloads"
    layout_version: int = 4
    normal_folder: str = "01_通常ダウンロード"
    scheduled_folder: str = "02_定期実行"
    schedule_storage_key: str = ""
    schedule_storage_folder: str = ""


class ScheduleNotificationPolicy(str, Enum):
    """定期実行の完了通知方針。"""

    OFF = "off"
    IMPORTANT_ONLY = "important_only"
    ALL_RESULTS = "all_results"
    FAILURES_ONLY = "failures_only"


@dataclass
class ScheduleConfig:
    """スケジュール設定"""

    enabled: bool = False
    # 新規設定はWindowsタスクスケジューラを使用する。``process`` は旧設定の
    # 移行判定専用で、バックグラウンド実行には使用しない。
    backend: str = "windows_task_scheduler"
    timezone: str = "Asia/Tokyo"
    interval: str = "daily"  # daily, weekly, monthly（customは旧設定の読込専用）
    time: str = "09:00"  # HH:MM形式
    weekday: str = "monday"  # weekly: monday ... sunday
    day_of_month: int = 1  # monthly: 1 ... 28
    start_when_available: bool = True
    wake_to_run: bool = False
    retry_count: int = 2
    retry_interval_minutes: int = 15
    # 旧設定とv1/v2スナップショットは通知なしとして読み込む。
    # 新規作成時のIMPORTANT_ONLY選択はGUI側が明示的に設定する。
    notification_policy: str = ScheduleNotificationPolicy.OFF.value
    active_profile_id: Optional[str] = None
    cron: Optional[str] = None  # 非推奨。旧custom設定との互換性のために保持

    def __post_init__(self):
        """初期化後の検証"""
        # customは旧設定を読み込んで明示警告するためだけに許容する。
        valid_intervals = ["daily", "weekly", "monthly", "custom"]
        if self.interval not in valid_intervals:
            raise ValueError(f"intervalは{valid_intervals}のいずれかである必要があります: {self.interval}")

        valid_backends = {"windows_task_scheduler", "process", "legacy_process"}
        if self.backend not in valid_backends:
            raise ValueError(
                f"backendは{sorted(valid_backends)}のいずれかである必要があります: "
                f"{self.backend}"
            )
        if self.timezone != "Asia/Tokyo":
            raise ValueError("timezoneはAsia/Tokyoを指定してください")
        if not isinstance(self.start_when_available, bool):
            raise ValueError("start_when_availableは真偽値で指定してください")
        if not isinstance(self.wake_to_run, bool):
            raise ValueError("wake_to_runは真偽値で指定してください")
        if isinstance(self.retry_count, bool) or not isinstance(self.retry_count, int):
            raise ValueError("retry_countは0以上の整数で指定してください")
        if not 0 <= self.retry_count <= 10:
            raise ValueError("retry_countは0から10の範囲で指定してください")
        if (
            isinstance(self.retry_interval_minutes, bool)
            or not isinstance(self.retry_interval_minutes, int)
            or not 1 <= self.retry_interval_minutes <= 1440
        ):
            raise ValueError(
                "retry_interval_minutesは1から1440の整数で指定してください"
            )
        raw_notification_policy = self.notification_policy
        if isinstance(raw_notification_policy, ScheduleNotificationPolicy):
            raw_notification_policy = raw_notification_policy.value
        try:
            self.notification_policy = ScheduleNotificationPolicy(
                str(raw_notification_policy).strip().lower()
            ).value
        except ValueError as exc:
            valid_policies = [policy.value for policy in ScheduleNotificationPolicy]
            raise ValueError(
                "notification_policyは"
                f"{valid_policies}のいずれかで指定してください: "
                f"{raw_notification_policy}"
            ) from exc

        if not self.enabled or self.interval == "custom":
            return

        if not self.time:
            raise ValueError(f"intervalが{self.interval}の場合、timeを指定してください")

        import re

        time_pattern = r"^([0-1][0-9]|2[0-3]):[0-5][0-9]$"
        if not re.match(time_pattern, self.time):
            raise ValueError(f"timeはHH:MM形式で指定してください: {self.time}")

        valid_weekdays = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        if self.weekday not in valid_weekdays:
            raise ValueError(f"weekdayは{valid_weekdays}のいずれかである必要があります: {self.weekday}")
        if not 1 <= self.day_of_month <= 28:
            raise ValueError(f"day_of_monthは1から28の範囲で指定してください: {self.day_of_month}")

    @property
    def is_supported(self) -> bool:
        """現在実行可能なスケジュール方式かどうか。"""
        return self.interval in {"daily", "weekly", "monthly"}

    @property
    def uses_windows_task_scheduler(self) -> bool:
        """Windowsタスクスケジューラへ登録可能な設定かどうか。"""
        return self.backend == "windows_task_scheduler" and self.is_supported

    @property
    def requires_migration(self) -> bool:
        """旧プロセス内設定から明示移行が必要かどうか。"""
        return self.backend in {"process", "legacy_process"}


@dataclass
class LoggingConfig:
    """ログ設定"""

    level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    file: str = "./logs/app.log"
    max_bytes: int = 10485760  # 10MB
    backup_count: int = 5


@dataclass
class AppConfig:
    """アプリケーション設定のデータモデル"""

    target_urls: List[str] = field(
        default_factory=lambda: [IPPI_OFFICIAL_SEARCH_URL]
    )
    download_conditions: DownloadConditions = field(default_factory=DownloadConditions)
    search_conditions: SearchConditions = field(default_factory=SearchConditions)  # i-ppi.jp検索条件
    save_paths: SavePaths = field(default_factory=SavePaths)
    naming_rule: str = "{document_name}_{document_updated_at}"
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
