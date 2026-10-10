# -*- coding: utf-8 -*-

"""設定ファイルの読み込み・保存を行うクラス"""

import os
import tempfile
import yaml
from pathlib import Path
from typing import Tuple, List, Optional
from ..models.config_model import (
    AppConfig,
    DownloadConditions,
    SearchConditions,
    SavePaths,
    ScheduleConfig,
    LoggingConfig,
)
from ..models.search_target import SearchTarget
from ..core.search_profiles import get_search_profile
from ..utils.logger import Logger
from ..utils.path_utils import get_config_path, get_logs_path, get_downloads_path
from ..utils.naming_template import (
    DEFAULT_NAMING_RULE,
    LEGACY_DEFAULT_NAMING_RULE,
)
from .config_validator import ConfigValidator
from ..app.exceptions import ConfigError, FilesystemError


class ConfigManager:
    """設定ファイルの読み込み・保存を行うクラス"""

    def __init__(self, config_path: Optional[str] = None, logger: Logger = None):
        """初期化
        
        Args:
            config_path: 設定ファイルのパス。Noneの場合はデフォルトパスを使用。
            logger: ロガーインスタンス
        """
        if config_path:
            self.config_path = Path(config_path)
        else:
            # exe配布時も正しいパスを取得
            self.config_path = get_config_path("config.yaml")
        
        self.logger = logger or Logger()
        self.validator = ConfigValidator(self.logger)

    def load_config(self) -> AppConfig:
        """設定ファイルを読み込む"""
        if not self.config_path.exists():
            self.logger.warning(f"設定ファイルが見つかりません: {self.config_path}")
            self.logger.info("デフォルト設定を使用します")
            return self.get_default_config()

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config_dict = yaml.safe_load(f) or {}

            config = self._dict_to_config(config_dict)
            is_valid, errors = self.validator.validate_config(config)

            if not is_valid:
                message = "、".join(errors)
                self.logger.error(f"設定ファイルが不正です: {message}")
                raise ConfigError(
                    f"設定ファイルが不正です: {self.config_path}: {message}"
                )

            self.logger.info(f"設定ファイルを読み込みました: {self.config_path}")
            return config

        except (IOError, OSError) as e:
            self.logger.error(f"設定ファイルの読み込みエラー: {str(e)}")
            raise FilesystemError(f"設定ファイルの読み込みに失敗しました: {self.config_path} - {str(e)}")
        except ConfigError:
            raise
        except Exception as e:
            self.logger.error(f"設定ファイルの読み込みエラー: {str(e)}")
            raise ConfigError(f"設定ファイルの解析に失敗しました: {str(e)}")

    def save_config(self, config: AppConfig) -> bool:
        """設定ファイルを保存する"""
        try:
            # 設定ファイルのディレクトリを作成
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # 検証
            is_valid, errors = self.validator.validate_config(config)
            if not is_valid:
                self.logger.error(f"設定が無効です: {', '.join(errors)}")
                return False

            # 辞書に変換
            config_dict = self._config_to_dict(config)

            # 同一フォルダーの一時ファイルをfsyncしてから置換し、保存中断で
            # 既存設定を破損させない。
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="\n",
                    suffix=".tmp",
                    prefix=".config-",
                    dir=self.config_path.parent,
                    delete=False,
                ) as stream:
                    yaml.dump(
                        config_dict,
                        stream,
                        allow_unicode=True,
                        default_flow_style=False,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                    temporary_path = Path(stream.name)
                os.replace(temporary_path, self.config_path)
                temporary_path = None
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            self.logger.info(f"設定ファイルを保存しました: {self.config_path}")
            return True

        except (IOError, OSError) as e:
            self.logger.error(f"設定ファイルの保存エラー: {str(e)}")
            raise FilesystemError(f"設定ファイルの保存に失敗しました: {self.config_path} - {str(e)}")
        except Exception as e:
            self.logger.error(f"設定ファイルの保存エラー: {str(e)}")
            raise ConfigError(f"設定ファイルの保存に失敗しました: {str(e)}")

    def validate_config(self, config: AppConfig) -> Tuple[bool, List[str]]:
        """設定を検証する"""
        return self.validator.validate_config(config)

    def get_default_config(self) -> AppConfig:
        """デフォルト設定を取得する
        
        exe配布時も正しいパスをデフォルト値として使用。
        """
        return AppConfig(
            save_paths=SavePaths(local=str(get_downloads_path())),
            logging=LoggingConfig(file=str(get_logs_path("app.log"))),
        )

    def _dict_to_config(self, config_dict: dict) -> AppConfig:
        """辞書をAppConfigに変換"""
        if config_dict.get("box") or config_dict.get("save_paths", {}).get("box"):
            self.logger.warning(
                "Box設定は現在サポート対象外です。値は実行に使用されず、"
                "次回の設定保存時にローカル専用スキーマへ移行されます"
            )
        # ネストされた設定を処理
        download_conditions = DownloadConditions(
            file_types=config_dict.get("download_conditions", {}).get("file_types", [".pdf", ".xlsx", ".docx"]),
            keywords=config_dict.get("download_conditions", {}).get("keywords", []),
            date_range=config_dict.get("download_conditions", {}).get("date_range"),
        )

        # デフォルトのダウンロードパスはexeの場所を基準にする
        default_downloads = str(get_downloads_path())
        save_dict = config_dict.get("save_paths", {}) or {}
        save_paths = SavePaths(
            local=save_dict.get("local", default_downloads),
            # layout_versionを持たない設定・snapshotは、保存場所を変えない。
            layout_version=save_dict.get("layout_version", 2),
            normal_folder=save_dict.get(
                "normal_folder", "01_通常ダウンロード"
            ),
            scheduled_folder=save_dict.get(
                "scheduled_folder", "02_定期実行"
            ),
            schedule_storage_key=save_dict.get("schedule_storage_key", ""),
            schedule_storage_folder=save_dict.get(
                "schedule_storage_folder", ""
            ),
        )

        schedule_dict = config_dict.get("schedule", {})
        schedule_interval = schedule_dict.get("interval", "daily")
        schedule_enabled = schedule_dict.get("enabled", False)
        schedule_backend = schedule_dict.get("backend")
        if schedule_enabled and schedule_backend is None:
            self.logger.warning(
                "旧プロセス内スケジュール設定を検出しました。自動ではWindowsタスクへ"
                "登録せず無効化します。設定画面から『Windowsタスクへ移行』を実行してください"
            )
            schedule_enabled = False
            schedule_backend = "legacy_process"
        elif schedule_backend is None:
            schedule_backend = "windows_task_scheduler"
        if schedule_interval == "custom":
            self.logger.warning(
                "schedule.interval=custom はサポート対象外です。"
                "スケジュールは無効として扱われます。daily/weekly/monthly のいずれかを指定してください"
            )
            schedule_enabled = False
        schedule = ScheduleConfig(
            enabled=schedule_enabled,
            backend=schedule_backend,
            timezone=schedule_dict.get("timezone", "Asia/Tokyo"),
            interval=schedule_interval,
            time=schedule_dict.get("time", "09:00"),
            weekday=schedule_dict.get("weekday", "monday"),
            day_of_month=schedule_dict.get("day_of_month", 1),
            start_when_available=schedule_dict.get("start_when_available", True),
            wake_to_run=schedule_dict.get("wake_to_run", False),
            retry_count=schedule_dict.get("retry_count", 2),
            retry_interval_minutes=schedule_dict.get("retry_interval_minutes", 15),
            notification_policy=schedule_dict.get("notification_policy", "off"),
            active_profile_id=schedule_dict.get("active_profile_id"),
            cron=schedule_dict.get("cron"),
        )

        # デフォルトのログパスはexeの場所を基準にする
        default_log_file = str(get_logs_path("app.log"))
        logging_config = LoggingConfig(
            level=config_dict.get("logging", {}).get("level", "INFO"),
            file=config_dict.get("logging", {}).get("file", default_log_file),
            max_bytes=config_dict.get("logging", {}).get("max_bytes", 10485760),
            backup_count=config_dict.get("logging", {}).get("backup_count", 5),
        )

        # 検索条件
        search_dict = config_dict.get("search_conditions", {})
        raw_target = search_dict.get(
            "search_target", SearchTarget.KOJI_KEIKA.value
        )
        try:
            search_profile = get_search_profile(raw_target)
            default_contract_types = list(
                search_profile.default_contract_types
            )
        except ValueError:
            # 不正な対象はValidatorで利用者向けエラーにする。
            default_contract_types = list(
                get_search_profile(
                    SearchTarget.KOJI_KEIKA
                ).default_contract_types
            )
        legacy_koji_name = search_dict.get("koji_name", "")
        project_name = search_dict.get("project_name")
        if project_name is None:
            project_name = legacy_koji_name
        search_conditions = SearchConditions(
            hachu_daibunrui=search_dict.get("hachu_daibunrui", ""),
            hachu_chubunrui=search_dict.get("hachu_chubunrui", ""),
            hachu_shoubunrui=search_dict.get("hachu_shoubunrui", ""),
            hachu_saibunrui=search_dict.get("hachu_saibunrui", ""),
            hachu_multi=search_dict.get("hachu_multi", []),
            koji_name=legacy_koji_name,
            place_search_type=search_dict.get("place_search_type", "list"),
            place_chihou=search_dict.get("place_chihou", ""),
            place_todofuken=search_dict.get("place_todofuken", ""),
            place_shichouson=search_dict.get("place_shichouson", ""),
            place_text=search_dict.get("place_text", ""),
            contract_types=search_dict.get(
                "contract_types",
                default_contract_types,
            ),
            update_date_type=search_dict.get("update_date_type", "none"),
            update_date_days=search_dict.get("update_date_days"),
            koukoku_date_type=search_dict.get("koukoku_date_type", "none"),
            koukoku_date_start=search_dict.get("koukoku_date_start"),
            koukoku_date_end=search_dict.get("koukoku_date_end"),
            kaisatsu_date_type=search_dict.get("kaisatsu_date_type", "none"),
            kaisatsu_date_start=search_dict.get("kaisatsu_date_start"),
            kaisatsu_date_end=search_dict.get("kaisatsu_date_end"),
            keiyaku_date_type=search_dict.get("keiyaku_date_type", "none"),
            keiyaku_date_start=search_dict.get("keiyaku_date_start"),
            keiyaku_date_end=search_dict.get("keiyaku_date_end"),
            koji_shubetsu=search_dict.get("koji_shubetsu", ""),
            koji_gyoushu=search_dict.get("koji_gyoushu", ""),
            yotei_price_min=search_dict.get("yotei_price_min"),
            yotei_price_max=search_dict.get("yotei_price_max"),
            rakusatsu_price_min=search_dict.get("rakusatsu_price_min"),
            rakusatsu_price_max=search_dict.get("rakusatsu_price_max"),
            rakusatsu_name=search_dict.get("rakusatsu_name", ""),
            denshi=search_dict.get("denshi", False),
            koukai=search_dict.get("koukai", False),
            display_count=search_dict.get("display_count", 20),
            search_target=raw_target,
            project_name=project_name,
            gyomu_kubun=search_dict.get("gyomu_kubun", ""),
        )
        if search_conditions.hachu_multi:
            self.logger.warning(
                "search_conditions.hachu_multi は現在サポート対象外です。"
                "値は移行用に保持しますが、実行時には使用できません"
            )

        naming_rule = config_dict.get("naming_rule", DEFAULT_NAMING_RULE)
        if naming_rule == LEGACY_DEFAULT_NAMING_RULE:
            self.logger.warning(
                "旧既定の命名規則を文書名・最終更新日時を使う新しい既定値へ"
                "移行します。独自の命名規則は変更しません"
            )
            naming_rule = DEFAULT_NAMING_RULE

        return AppConfig(
            target_urls=config_dict.get("target_urls", []),
            download_conditions=download_conditions,
            search_conditions=search_conditions,
            save_paths=save_paths,
            naming_rule=naming_rule,
            schedule=schedule,
            logging=logging_config,
        )

    def _config_to_dict(self, config: AppConfig) -> dict:
        """AppConfigを辞書に変換"""
        sc = config.search_conditions
        return {
            "target_urls": config.target_urls,
            "download_conditions": {
                "file_types": config.download_conditions.file_types,
                "keywords": config.download_conditions.keywords,
                "date_range": config.download_conditions.date_range,
            },
            "search_conditions": {
                "search_target": sc.search_target,
                "project_name": sc.project_name,
                "hachu_daibunrui": sc.hachu_daibunrui,
                "hachu_chubunrui": sc.hachu_chubunrui,
                "hachu_shoubunrui": sc.hachu_shoubunrui,
                "hachu_saibunrui": sc.hachu_saibunrui,
                "hachu_multi": sc.hachu_multi,
                "koji_name": sc.koji_name,
                "place_search_type": sc.place_search_type,
                "place_chihou": sc.place_chihou,
                "place_todofuken": sc.place_todofuken,
                "place_shichouson": sc.place_shichouson,
                "place_text": sc.place_text,
                "contract_types": sc.contract_types,
                "update_date_type": sc.update_date_type,
                "update_date_days": sc.update_date_days,
                "koukoku_date_type": sc.koukoku_date_type,
                "koukoku_date_start": sc.koukoku_date_start,
                "koukoku_date_end": sc.koukoku_date_end,
                "kaisatsu_date_type": sc.kaisatsu_date_type,
                "kaisatsu_date_start": sc.kaisatsu_date_start,
                "kaisatsu_date_end": sc.kaisatsu_date_end,
                "keiyaku_date_type": sc.keiyaku_date_type,
                "keiyaku_date_start": sc.keiyaku_date_start,
                "keiyaku_date_end": sc.keiyaku_date_end,
                "koji_shubetsu": sc.koji_shubetsu,
                "koji_gyoushu": sc.koji_gyoushu,
                "gyomu_kubun": sc.gyomu_kubun,
                "yotei_price_min": sc.yotei_price_min,
                "yotei_price_max": sc.yotei_price_max,
                "rakusatsu_price_min": sc.rakusatsu_price_min,
                "rakusatsu_price_max": sc.rakusatsu_price_max,
                "rakusatsu_name": sc.rakusatsu_name,
                "denshi": sc.denshi,
                "koukai": sc.koukai,
                "display_count": sc.display_count,
            },
            "save_paths": {
                "local": config.save_paths.local,
                "layout_version": config.save_paths.layout_version,
                "normal_folder": config.save_paths.normal_folder,
                "scheduled_folder": config.save_paths.scheduled_folder,
                "schedule_storage_key": config.save_paths.schedule_storage_key,
                "schedule_storage_folder": (
                    config.save_paths.schedule_storage_folder
                ),
            },
            "naming_rule": config.naming_rule,
            "schedule": {
                "enabled": config.schedule.enabled,
                "backend": config.schedule.backend,
                "timezone": config.schedule.timezone,
                "interval": config.schedule.interval,
                "time": config.schedule.time,
                "weekday": config.schedule.weekday,
                "day_of_month": config.schedule.day_of_month,
                "start_when_available": config.schedule.start_when_available,
                "wake_to_run": config.schedule.wake_to_run,
                "retry_count": config.schedule.retry_count,
                "retry_interval_minutes": config.schedule.retry_interval_minutes,
                "notification_policy": config.schedule.notification_policy,
                "active_profile_id": config.schedule.active_profile_id,
                "cron": config.schedule.cron,
            },
            "logging": {
                "level": config.logging.level,
                "file": config.logging.file,
                "max_bytes": config.logging.max_bytes,
                "backup_count": config.logging.backup_count,
            },
        }
