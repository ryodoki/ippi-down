# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import time

import pytest

from src.core.windows_process_supervisor import WindowsJobProcessSupervisor


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object test")
def test_job_supervisor_waits_for_child_after_launcher_exits(tmp_path):
    supervisor = WindowsJobProcessSupervisor(poll_interval=0.02)
    if not supervisor.available():
        pytest.skip("pywin32 is not available")
    events: list[tuple[str, dict[str, object]]] = []
    started = time.monotonic()
    result = supervisor.run(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys; "
                "subprocess.Popen([sys.executable,'-c',"
                "'import time; time.sleep(0.35)'])"
            ),
        ],
        cwd=tmp_path,
        timeout_seconds=5,
        event_callback=lambda event, values: events.append((event, values)),
    )

    assert result.state == "completed"
    assert result.exit_code == 0
    assert result.peak_process_count >= 2
    assert time.monotonic() - started >= 0.25
    assert events[0][0] == "process_started"
    assert events[-1][0] == "process_finished"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object test")
def test_job_supervisor_terminates_entire_tree_on_timeout(tmp_path):
    supervisor = WindowsJobProcessSupervisor(poll_interval=0.02)
    if not supervisor.available():
        pytest.skip("pywin32 is not available")
    result = supervisor.run(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c',"
                "'import time; time.sleep(30)']); time.sleep(30)"
            ),
        ],
        cwd=tmp_path,
        timeout_seconds=0.3,
    )

    assert result.state == "timeout"
    assert result.peak_process_count >= 1
    assert result.elapsed_seconds < 5
