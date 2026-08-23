# -*- coding: utf-8 -*-

"""ログ管理を行うクラス"""

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional
from ..models.config_model import LoggingConfig
from .path_utils import get_logs_path


class Logger:
    """ログ管理を行うクラス"""

    def __init__(self, config: Optional[LoggingConfig] = None):
        """初期化
        
        Args:
            config: ログ設定。Noneの場合はデフォルト設定を使用。
                    デフォルトのログファイルパスはexeの場所を基準にする。
        """
        if config is None:
            # デフォルト設定（exe配布時も正しいパスを使用）
            config = LoggingConfig(file=str(get_logs_path("app.log")))
        self.config = config
        
        self.logger = logging.getLogger("ppi_file_downloader")
        self.logger.setLevel(getattr(logging, self.config.level.upper(), logging.INFO))
        # handlers.clear() を削除（他のLoggerインスタンスに影響を与えないようにする）
        # 既にハンドラーが設定されている場合は追加しない（二重出力を防ぐ）
        if not self.logger.handlers:
            # コンソールハンドラー
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)

            # ファイルハンドラー
            self.setup_file_handler()

    def setup_file_handler(self):
        """ファイルハンドラーを設定"""
        # 既にファイルハンドラーが設定されている場合は追加しない（二重出力を防ぐ）
        if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in self.logger.handlers):
            return
        
        log_file = Path(self.config.file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self.config.max_bytes,
            backupCount=self.config.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, self.config.level.upper(), logging.INFO))
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

    def debug(self, message: str):
        """DEBUGレベルのログを出力"""
        self.logger.debug(message)

    def info(self, message: str):
        """INFOレベルのログを出力"""
        self.logger.info(message)

    def warning(self, message: str):
        """WARNINGレベルのログを出力"""
        self.logger.warning(message)

    def error(self, message: str, exc_info: bool = False):
        """ERRORレベルのログを出力"""
        self.logger.error(message, exc_info=exc_info)

