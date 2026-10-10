# -*- coding: utf-8 -*-

"""スケジューリングモジュール"""

from .scheduler import Scheduler
from .ledger import ScheduleRunLedger
from .models import (
    DEFAULT_SCHEDULE_ID,
    ExternalScheduleImportCandidate,
    InstallationRelocationPreview,
    InstallationRelocationResult,
    ScheduleCapabilities,
    ScheduleDefinition,
    ScheduleImportPlan,
    ScheduleMigrationResult,
    ScheduleOrigin,
    ScheduleRegistration,
    ScheduleRegistrationStatus,
    ScheduleRegistry,
    ScheduleRegistrySnapshot,
    ScheduleServiceError,
    ScheduleState,
    ScheduledProfile,
    ScheduledRunRecord,
)
from .profile import (
    ScheduleProfileStore,
    calculate_condition_fingerprint,
    calculate_profile_fingerprint,
    profile_fingerprint,
)
from .registration import ScheduleRegistrationStore
from .service import ScheduleService, calculate_next_run, next_run_time
from .task_scheduler import (
    SchtasksClient,
    TaskQueryResult,
    TaskSchedulerClient,
    WindowsTaskScheduler,
    build_task_xml,
)

__all__ = [
    "Scheduler",
    "ScheduleRunLedger",
    "DEFAULT_SCHEDULE_ID",
    "ExternalScheduleImportCandidate",
    "InstallationRelocationPreview",
    "InstallationRelocationResult",
    "ScheduleCapabilities",
    "ScheduleDefinition",
    "ScheduleImportPlan",
    "ScheduleMigrationResult",
    "ScheduleOrigin",
    "ScheduleRegistration",
    "ScheduleRegistrationStatus",
    "ScheduleRegistry",
    "ScheduleRegistrySnapshot",
    "ScheduleServiceError",
    "ScheduleState",
    "ScheduledProfile",
    "ScheduledRunRecord",
    "ScheduleProfileStore",
    "ScheduleRegistrationStore",
    "calculate_condition_fingerprint",
    "calculate_profile_fingerprint",
    "profile_fingerprint",
    "ScheduleService",
    "calculate_next_run",
    "next_run_time",
    "SchtasksClient",
    "TaskQueryResult",
    "TaskSchedulerClient",
    "WindowsTaskScheduler",
    "build_task_xml",
]
