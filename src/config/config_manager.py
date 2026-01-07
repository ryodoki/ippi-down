"""設定ファイルの読み込み・保存を行うクラス"""

import yaml
from pathlib import Path
from typing import Tuple, List
from ..models.config_model import (
    AppConfig,
    DownloadConditions,
    SearchConditions,
    SavePaths,
    ScheduleConfig,
    LoggingConfig,
    BoxConfig,
)
from ..utils.logger import Logger
from .config_validator import ConfigValidator


class ConfigManager:
    """設定ファイルの読み込み・保存を行うクラス"""

    def __init__(self, config_path: str = "config/config.yaml", logger: Logger = None):
        """初期化"""
        self.config_path = Path(config_path)
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
                self.logger.warning(f"設定ファイルに問題があります: {', '.join(errors)}")
                self.logger.info("デフォルト設定を使用します")
                return self.get_default_config()

            self.logger.info(f"設定ファイルを読み込みました: {self.config_path}")
            return config

        except Exception as e:
            self.logger.error(f"設定ファイルの読み込みエラー: {str(e)}")
            self.logger.info("デフォルト設定を使用します")
            return self.get_default_config()

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

            # YAMLファイルに保存
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(config_dict, f, allow_unicode=True, default_flow_style=False)

            self.logger.info(f"設定ファイルを保存しました: {self.config_path}")
            return True

        except Exception as e:
            self.logger.error(f"設定ファイルの保存エラー: {str(e)}")
            return False

    def validate_config(self, config: AppConfig) -> Tuple[bool, List[str]]:
        """設定を検証する"""
        return self.validator.validate_config(config)

    def get_default_config(self) -> AppConfig:
        """デフォルト設定を取得する"""
        return AppConfig()

    def _dict_to_config(self, config_dict: dict) -> AppConfig:
        """辞書をAppConfigに変換"""
        # ネストされた設定を処理
        download_conditions = DownloadConditions(
            file_types=config_dict.get("download_conditions", {}).get("file_types", [".pdf", ".xlsx", ".docx"]),
            keywords=config_dict.get("download_conditions", {}).get("keywords", []),
            date_range=config_dict.get("download_conditions", {}).get("date_range"),
        )

        save_paths = SavePaths(
            local=config_dict.get("save_paths", {}).get("local", "./downloads"),
            box=config_dict.get("save_paths", {}).get("box", {"enabled": False, "folder_id": None}),
        )

        schedule = ScheduleConfig(
            enabled=config_dict.get("schedule", {}).get("enabled", False),
            interval=config_dict.get("schedule", {}).get("interval", "daily"),
            time=config_dict.get("schedule", {}).get("time", "09:00"),
            cron=config_dict.get("schedule", {}).get("cron"),
        )

        logging_config = LoggingConfig(
            level=config_dict.get("logging", {}).get("level", "INFO"),
            file=config_dict.get("logging", {}).get("file", "./logs/app.log"),
            max_bytes=config_dict.get("logging", {}).get("max_bytes", 10485760),
            backup_count=config_dict.get("logging", {}).get("backup_count", 5),
        )

        box_config = BoxConfig(
            client_id=config_dict.get("box", {}).get("client_id", ""),
            client_secret=config_dict.get("box", {}).get("client_secret", ""),
            access_token=config_dict.get("box", {}).get("access_token", ""),
            refresh_token=config_dict.get("box", {}).get("refresh_token", ""),
        )

        # 検索条件
        search_dict = config_dict.get("search_conditions", {})
        search_conditions = SearchConditions(
            hachu_daibunrui=search_dict.get("hachu_daibunrui", ""),
            hachu_chubunrui=search_dict.get("hachu_chubunrui", ""),
            hachu_shoubunrui=search_dict.get("hachu_shoubunrui", ""),
            hachu_saibunrui=search_dict.get("hachu_saibunrui", ""),
            hachu_multi=search_dict.get("hachu_multi", []),
            koji_name=search_dict.get("koji_name", ""),
            place_search_type=search_dict.get("place_search_type", "list"),
            place_chihou=search_dict.get("place_chihou", ""),
            place_todofuken=search_dict.get("place_todofuken", ""),
            place_shichouson=search_dict.get("place_shichouson", ""),
            place_text=search_dict.get("place_text", ""),
            contract_types=search_dict.get(
                "contract_types",
                [
                    "一般競争入札",
                    "公募型指名競争入札",
                    "指名競争入札",
                    "随意契約",
                    "その他方式",
                ],
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
        )

        return AppConfig(
            target_urls=config_dict.get("target_urls", []),
            download_conditions=download_conditions,
            search_conditions=search_conditions,
            save_paths=save_paths,
            naming_rule=config_dict.get("naming_rule", "{category}_{title}_{date}_{index}"),
            schedule=schedule,
            logging=logging_config,
            box=box_config,
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
                "box": config.save_paths.box,
            },
            "naming_rule": config.naming_rule,
            "schedule": {
                "enabled": config.schedule.enabled,
                "interval": config.schedule.interval,
                "time": config.schedule.time,
                "cron": config.schedule.cron,
            },
            "logging": {
                "level": config.logging.level,
                "file": config.logging.file,
                "max_bytes": config.logging.max_bytes,
                "backup_count": config.logging.backup_count,
            },
            "box": {
                "client_id": config.box.client_id,
                "client_secret": config.box.client_secret,
                "access_token": config.box.access_token,
                "refresh_token": config.box.refresh_token,
            },
        }

