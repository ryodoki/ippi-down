"""pytest実行中のファイルログ隔離を検証する。"""

import logging.handlers
from pathlib import Path
from uuid import uuid4

from src.models.config_model import LoggingConfig
from src.utils.logger import Logger
from src.utils import logger_factory as logger_factory_module


def test_explicit_relative_log_path_is_redirected_outside_project():
    filename = f"isolation-{uuid4().hex}.log"
    configured_path = Path("logs") / filename
    logger = Logger(LoggingConfig(file=str(configured_path)))
    logger.info("pytest log isolation")

    file_handlers = [
        handler
        for handler in logger.logger.handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    actual_path = Path(file_handlers[0].baseFilename).resolve()
    project_log_path = (
        Path(__file__).parent.parent / configured_path
    ).resolve()

    assert actual_path != project_log_path
    assert actual_path.name == filename
    assert actual_path.is_file()
    assert not project_log_path.exists()
    assert (
        logger_factory_module.resolve_app_path(configured_path).resolve()
        == actual_path
    )
