# -*- coding: utf-8 -*-

"""設定データモデル"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchConditions:
    """ppi.jp検索条件"""

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


@dataclass
class DownloadConditions:
    """ダウンロード条件"""

    file_types: List[str] = field(default_factory=lambda: [".pdf", ".xlsx", ".docx"])
    keywords: List[str] = field(default_factory=list)
    date_range: Optional[dict] = None  # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}


@dataclass
class SavePaths:
    """保存先パス"""

    local: str = "./downloads"
    use_subfolders: bool = True  # サブフォルダ自動生成（FR-013、デフォルトはTrueで既存挙動を維持）
    enable_hash_check: bool = False  # ハッシュ判定を有効化（FR-008、オプション）
    keep_part_on_cancel: bool = True  # キャンセル時に.partファイルを残す（FR-006-1、デフォルトはTrue）


@dataclass
class ScheduleConfig:
    """スケジュール設定"""

    enabled: bool = False
    interval: str = "daily"  # daily, weekly, monthly, custom
    time: str = "09:00"  # HH:MM形式
    cron: Optional[str] = None  # cron形式（intervalがcustomの場合）

    def __post_init__(self):
        """初期化後の検証"""
        if self.enabled:
            # intervalの値チェック
            valid_intervals = ["daily", "weekly", "monthly", "custom"]
            if self.interval not in valid_intervals:
                raise ValueError(f"intervalは{valid_intervals}のいずれかである必要があります: {self.interval}")
            
            # intervalがcustomの場合、cronが必須
            if self.interval == "custom":
                if not self.cron:
                    raise ValueError("intervalがcustomの場合、cron形式を指定してください")
            else:
                # intervalがcustom以外の場合、timeが必須
                if not self.time:
                    raise ValueError(f"intervalが{self.interval}の場合、timeを指定してください")
                
                # timeの形式チェック（HH:MM形式）
                time_pattern = r"^([0-1][0-9]|2[0-3]):[0-5][0-9]$"
                import re
                if not re.match(time_pattern, self.time):
                    raise ValueError(f"timeはHH:MM形式で指定してください: {self.time}")


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
        default_factory=lambda: [
            "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        ]
    )
    download_conditions: DownloadConditions = field(default_factory=DownloadConditions)
    search_conditions: SearchConditions = field(default_factory=SearchConditions)  # ppi.jp検索条件
    save_paths: SavePaths = field(default_factory=SavePaths)
    naming_rule: str = "{category}_{title}_{date}_{index}"
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

