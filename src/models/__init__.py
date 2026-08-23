<<<<<<< HEAD
﻿"""データモデルモジュール"""
=======
# -*- coding: utf-8 -*-

"""データモデルモジュール"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

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
]

