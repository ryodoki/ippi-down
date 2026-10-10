# -*- coding: utf-8 -*-

"""データモデルモジュール"""

from .file_info import FileInfo
from .agency import (
    AgencyCatalogSnapshot,
    AgencyLevel,
    AgencyOption,
    AgencyOptionSource,
    AgencyOptionsError,
    AgencyOptionsErrorCode,
    AgencyOptionsResult,
    AgencyPath,
    AgencyPathKey,
    AgencyPathResolution,
    AgencyResolutionReasonCode,
    AgencyResolutionStatus,
    agency_path_key,
)
from .download_task import DownloadTask
from .download_result import DownloadResult
from .search_target import SearchTarget
from .download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadMode,
    DownloadStage,
    IssueSeverity,
    RedownloadPolicy,
)
from .config_model import (
    AppConfig,
    DownloadConditions,
    SearchConditions,
    SavePaths,
    ScheduleConfig,
    ScheduleNotificationPolicy,
    LoggingConfig,
)

__all__ = [
    "FileInfo",
    "AgencyCatalogSnapshot",
    "AgencyLevel",
    "AgencyOption",
    "AgencyOptionSource",
    "AgencyOptionsError",
    "AgencyOptionsErrorCode",
    "AgencyOptionsResult",
    "AgencyPath",
    "AgencyPathKey",
    "AgencyPathResolution",
    "AgencyResolutionReasonCode",
    "AgencyResolutionStatus",
    "agency_path_key",
    "DownloadTask",
    "DownloadResult",
    "SearchTarget",
    "DownloadIssue",
    "DownloadIssueCode",
    "DownloadMode",
    "DownloadStage",
    "IssueSeverity",
    "RedownloadPolicy",
    "AppConfig",
    "DownloadConditions",
    "SearchConditions",
    "SavePaths",
    "ScheduleConfig",
    "ScheduleNotificationPolicy",
    "LoggingConfig",
]
