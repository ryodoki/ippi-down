"""設定検証を行うクラス"""

from typing import Tuple, List
from urllib.parse import urlparse
from ..models.config_model import AppConfig
from ..utils.logger import Logger


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

        # 命名規則の検証
        if not config.naming_rule:
            errors.append("命名規則が指定されていません")

        # スケジュール設定の検証
        if config.schedule.enabled:
            if config.schedule.interval == "custom" and not config.schedule.cron:
                errors.append("カスタムスケジュールの場合、cron形式を指定してください")
            elif config.schedule.interval != "custom" and not config.schedule.time:
                errors.append("スケジュール時間が指定されていません")

        return len(errors) == 0, errors

    def _is_valid_url(self, url: str) -> bool:
        """URLが有効かどうかをチェック"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

