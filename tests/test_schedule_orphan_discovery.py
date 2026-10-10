# -*- coding: utf-8 -*-

"""登録台帳を失ったWindowsタスクの読み取り専用検出テスト。"""

from __future__ import annotations

import subprocess

import pytest

from src.gui.schedule_management import normalise_schedule_views
from src.scheduler.models import ScheduleOrigin, ScheduleServiceError, ScheduleState
from src.scheduler.service import ScheduleService
from src.scheduler.task_scheduler import (
    SchtasksClient,
    TaskQueryResult,
)


def _completed(command: list[str], *, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_task_name_discovery_only_accepts_exact_install_prefix_and_safe_ids():
    output = "\n".join(
        (
            '"\\ippi-down\\Download-install123","N/A","Ready"',
            '"\\ippi-down\\Download-install123-road_a","N/A","Ready"',
            '"\\IPPI-DOWN\\DOWNLOAD-INSTALL123-WEEKLY","N/A","Ready"',
            '"\\ippi-down\\Download-install123-unsafe id","N/A","Ready"',
            '"\\ippi-down\\Download-install123\\child","N/A","Ready"',
            '"\\ippi-down\\Download-other-road_a","N/A","Ready"',
            '"\\Other\\Download-install123-road_a","N/A","Ready"',
        )
    )
    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs):
        calls.append(command)
        return _completed(command, stdout=output)

    client = SchtasksClient(runner=runner)

    assert client.list_task_names(
        r"\ippi-down\Download-install123"
    ) == (
        r"\ippi-down\Download-install123",
        r"\ippi-down\Download-install123-road_a",
        r"\IPPI-DOWN\DOWNLOAD-INSTALL123-WEEKLY",
    )
    assert calls == [["schtasks.exe", "/Query", "/FO", "CSV", "/NH"]]


def test_task_name_discovery_rejects_unscoped_prefix_without_querying():
    runner = pytest.fail
    client = SchtasksClient(runner=runner)

    with pytest.raises(ScheduleServiceError) as captured:
        client.list_task_names(r"\ippi-down")

    assert captured.value.reason_code == "TASK_PREFIX_INVALID"


class _DiscoveringTaskClient:
    def __init__(self, tasks: dict[str, TaskQueryResult]) -> None:
        self.tasks = tasks
        self.list_calls: list[str] = []
        self.query_many_calls: list[tuple[str, ...]] = []

    def list_task_names(self, prefix: str) -> tuple[str, ...]:
        self.list_calls.append(prefix)
        return tuple(self.tasks)

    def query_many(self, task_names) -> dict[str, TaskQueryResult]:
        names = tuple(task_names)
        self.query_many_calls.append(names)
        return {name: self.tasks[name] for name in names}

    def query(self, task_name: str) -> TaskQueryResult:
        return self.tasks[task_name]

    def create_or_update(self, *_args, **_kwargs) -> None:
        raise AssertionError("orphan discovery must not create tasks")

    def delete(self, *_args, **_kwargs) -> None:
        raise AssertionError("orphan discovery must not delete tasks")


def test_service_exposes_registry_orphans_as_external_read_only_statuses(tmp_path):
    base = r"\ippi-down\Download-install123"
    tasks = {
        base: TaskQueryResult(
            exists=True,
            running=True,
            next_run=None,
            last_result=0x41301,
            enabled=True,
        ),
        f"{base}-road_a": TaskQueryResult(
            exists=True,
            running=False,
            last_result=2,
            enabled=False,
        ),
    }
    client = _DiscoveringTaskClient(tasks)
    service = ScheduleService(
        config_dir=tmp_path / "config",
        logs_dir=tmp_path / "logs",
        install_id="install123",
        task_client=client,
        app_root=tmp_path,
    )

    statuses = service.get_statuses()

    assert set(statuses) == {"default", "road_a"}
    assert all(
        status.state == ScheduleState.EXTERNAL
        and status.reason_code == "EXTERNAL_TASK_NOT_IMPORTABLE"
        and status.registered
        and status.origin is ScheduleOrigin.EXTERNAL
        and status.capabilities is not None
        and not status.capabilities.can_repair
        and not status.capabilities.can_import
        for status in statuses.values()
    )
    assert statuses["default"].running is True
    assert statuses["road_a"].enabled is False
    assert statuses["road_a"].last_result == "failed"
    assert client.list_calls == [base]
    assert set(client.query_many_calls[0]) == set(tasks)

    views = normalise_schedule_views(service.list_schedules(), statuses)
    assert {view.schedule_id for view in views} == {"default", "road_a"}
    assert all(view.definition is None for view in views)
