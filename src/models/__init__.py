"""データモデルモジュール"""

from .file_info import FileInfo
from .download_task import DownloadTask
from .download_result import DownloadResult
from .config_model import (
    AppConfig,
    DownloadConditions,
    SearchConditions,
    SavePaths,
    ScheduleConfig,
    LoggingConfig,
    BoxConfig,
)

__all__ = [
    "FileInfo",
    "DownloadTask",
    "DownloadResult",
    "AppConfig",
    "DownloadConditions",
    "SearchConditions",
    "SavePaths",
    "ScheduleConfig",
    "LoggingConfig",
    "BoxConfig",
]

