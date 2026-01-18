# -*- coding: utf-8 -*-

"""Logger Factory（安全なLogger生成）"""

import logging
import uuid
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler
from .logger import Logger
from ..models.config_model import LoggingConfig


class LoggerFactory:
    """Logger Factory（シングルトン）"""

    _instance: Optional['LoggerFactory'] = None
    _loggers: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初期化（1回だけ実行される）"""
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._configured_handlers = set()

    def create_logger(
        self, 
        config: Optional[LoggingConfig] = None,
        run_id: Optional[str] = None
    ) -> Logger:
        """Loggerを作成（重複防止）"""
        # run_idが指定されていない場合は生成
        if run_id is None:
            run_id = str(uuid.uuid4())[:8]

        # 既存のLoggerがあれば返す（configはhashableでないため、run_idのみで判定）
        cache_key = run_id
        if cache_key in self._loggers:
            return self._loggers[cache_key]

        # Loggerを作成
        logger = Logger(config)
        
        # run_idをLoggerに設定（カスタム属性として）
        logger.logger.setLevel(getattr(logging, config.level if config else "INFO"))
        
        # run_idをログフォーマットに追加
        if config:
            self._setup_handlers(logger, config, run_id)

        self._loggers[cache_key] = logger
        return logger

    def _setup_handlers(self, logger: Logger, config: LoggingConfig, run_id: str):
        """ハンドラーをセットアップ（重複防止）"""
        # 既に設定済みのハンドラーをクリアしない（他のLoggerに影響を与えない）
        if not logger.logger.handlers:
            # ファイルハンドラー
            log_path = Path(config.file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = RotatingFileHandler(
                config.file,
                maxBytes=config.max_bytes,
                backupCount=config.backup_count,
                encoding='utf-8'
            )
            
            # フォーマッターにrun_idを含める
            formatter = logging.Formatter(
                f'%(asctime)s - [run_id={run_id}] - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(formatter)
            logger.logger.addHandler(file_handler)

            # コンソールハンドラー
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.logger.addHandler(console_handler)
