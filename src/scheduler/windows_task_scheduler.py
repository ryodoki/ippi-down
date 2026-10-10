# -*- coding: utf-8 -*-

"""旧/外部import向けのWindowsタスクスケジューラAPI。"""

from .task_scheduler import (
    CommandResult,
    SchtasksClient,
    TaskQueryResult,
    TaskSchedulerClient,
    WindowsTaskScheduler,
    build_task_xml,
    quote_windows_arguments,
    task_definition_signature,
    task_definitions_match,
)

__all__ = [
    "CommandResult",
    "SchtasksClient",
    "TaskQueryResult",
    "TaskSchedulerClient",
    "WindowsTaskScheduler",
    "build_task_xml",
    "quote_windows_arguments",
    "task_definition_signature",
    "task_definitions_match",
]
