<<<<<<< HEAD
﻿"""設定検証を行うクラス"""
=======
# -*- coding: utf-8 -*-

"""設定検証を行うクラス"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

from typing import Tuple, List
from urllib.parse import urlparse
from ..models.config_model import AppConfig
from ..utils.logger import Logger
from ..core.naming import NAMING_TEMPLATE_VARIABLES


class ConfigValidator:
    """設定検証を行うクラス"""

    def __init__(self, logger: Logger = None):
        """初期化"""
        self.logger = logger or Logger()

    def validate_config(self, config: AppConfig) -> Tuple[bool, List[str]]:
        """設定を検証する"""
        errors = []

        # 対象URLの検証
        if not config.target_urls:
            errors.append("対象URLが指定されていません")
        else:
            for url in config.target_urls:
                if not self._is_valid_url(url):
                    errors.append(f"無効なURL: {url}")

        # 保存先の検証
        if not config.save_paths.local:
            errors.append("ローカル保存先が指定されていません")

        # ファイルタイプの検証
        if not config.download_conditions.file_types:
            errors.append("ファイルタイプが指定されていません")

        # 命名規則の検証（空でない場合、テンプレート変数をチェック）
        if config.naming_rule and config.naming_rule.strip():
            naming_errors = self.validate_naming_rule(config.naming_rule)
            errors.extend(naming_errors)

        # 発注機関フォルダ設定の検証（enable 時のみ）
        if getattr(config.save_paths, "enable_agency_root_folders", False):
            allowed_levels = {"daibunrui", "chubunrui", "shoubunrui", "saibunrui"}
            levels = getattr(config.save_paths, "agency_folder_levels", None) or []
            for lev in levels:
                if lev not in allowed_levels:
                    errors.append(
                        f"発注機関フォルダの階層に未知のキー '{lev}' が含まれています。"
                        f"使用可能: {', '.join(sorted(allowed_levels))}"
                    )
            dp = getattr(config.save_paths, "date_partition", "none") or "none"
            if dp not in ("none", "yyyy", "yyyy_mm", "yyyy_mm_dd"):
                errors.append(
                    f"日付フォルダ分割 date_partition は none / yyyy / yyyy_mm / yyyy_mm_dd のいずれかにしてください: {dp}"
                )
            label = getattr(config.save_paths, "agency_root_label", "").strip()
            if label == "" and getattr(config.save_paths, "agency_root_label", None) is not None:
                pass  # 空の場合は config_manager で既定値に補正される

        # スケジュール設定の検証
        if config.schedule.enabled:
            if config.schedule.interval == "custom" and not config.schedule.cron:
                errors.append("カスタムスケジュールの場合、cron形式を指定してください")
            elif config.schedule.interval != "custom" and not config.schedule.time:
                errors.append("スケジュール時間が指定されていません")

        return len(errors) == 0, errors

    def validate_naming_rule(self, naming_rule: str) -> List[str]:
        """命名規則テンプレートを検証する。未知キーがあればエラーメッセージを返す。"""
        errors = []
        # format_map 用のダミーコンテキスト（使用可能な変数のみ）
        dummy = {k: "0" for k in NAMING_TEMPLATE_VARIABLES}
        try:
            naming_rule.format_map(dummy)
        except KeyError as e:
            key = str(e).strip("'")
            valid = ", ".join("{" + k + "}" for k in NAMING_TEMPLATE_VARIABLES)
            errors.append(
                f"命名規則に未知の変数 '{key}' が含まれています。"
                f"使用可能: {valid}"
            )
        except Exception as e:
            errors.append(f"命名規則の形式が不正です: {e}")
        return errors

    def _is_valid_url(self, url: str) -> bool:
        """URLが有効かどうかをチェック"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

