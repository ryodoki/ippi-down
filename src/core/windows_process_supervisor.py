# -*- coding: utf-8 -*-

"""Windows Job Objectでブラウザーの全プロセスを監視する。"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence


CancelCheck = Optional[Callable[[], bool]]
ProcessEvent = Optional[Callable[[str, dict[str, object]], None]]


@dataclass(frozen=True)
class SupervisedProcessResult:
    state: str
    exit_code: Optional[int]
    root_pid: int = 0
    peak_process_count: int = 0
    stderr_tail: str = ""
    elapsed_seconds: float = 0.0
    supervision_error: str = ""


class _SupervisionUnavailable(RuntimeError):
    pass


class WindowsJobProcessSupervisor:
    """プロセスを停止状態でJobへ入れてから実行する。"""

    def __init__(
        self,
        *,
        poll_interval: float = 0.1,
        stderr_max_bytes: int = 4096,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.poll_interval = max(0.02, float(poll_interval))
        self.stderr_max_bytes = max(256, int(stderr_max_bytes))
        self._clock = clock
        self._sleep = sleeper

    @staticmethod
    def available() -> bool:
        if os.name != "nt":
            return False
        try:
            import win32job  # noqa: F401
            import win32process  # noqa: F401
        except ImportError:
            return False
        return True

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        cancel_check: CancelCheck = None,
        event_callback: ProcessEvent = None,
    ) -> SupervisedProcessResult:
        started = self._clock()
        if not self.available():
            return SupervisedProcessResult(
                "supervision_unavailable",
                None,
                elapsed_seconds=0.0,
                supervision_error="pywin32_unavailable",
            )

        import msvcrt
        import win32api
        import win32con
        import win32event
        import win32job
        import win32process

        cwd = Path(cwd)
        cwd.mkdir(parents=True, exist_ok=True)
        initial_fd, stderr_name = tempfile.mkstemp(
            prefix="ippi-edge-stderr-",
            suffix=".log",
            dir=str(cwd),
        )
        os.close(initial_fd)
        stderr_path = Path(stderr_name)
        stdin_fd = stdout_fd = stderr_fd = -1
        job = process_handle = thread_handle = None
        root_pid = 0
        peak_count = 0
        state = "start_failed"
        exit_code: Optional[int] = None
        supervision_error = ""
        try:
            stdin_fd = os.open(os.devnull, os.O_RDONLY | os.O_BINARY)
            stdout_fd = os.open(os.devnull, os.O_WRONLY | os.O_BINARY)
            stderr_fd = os.open(
                stderr_path,
                os.O_WRONLY | os.O_BINARY | os.O_TRUNC,
            )
            for descriptor in (stdin_fd, stdout_fd, stderr_fd):
                os.set_handle_inheritable(msvcrt.get_osfhandle(descriptor), True)

            startup = win32process.STARTUPINFO()
            startup.dwFlags |= win32process.STARTF_USESTDHANDLES
            startup.dwFlags |= win32process.STARTF_USESHOWWINDOW
            startup.wShowWindow = win32con.SW_HIDE
            startup.hStdInput = msvcrt.get_osfhandle(stdin_fd)
            startup.hStdOutput = msvcrt.get_osfhandle(stdout_fd)
            startup.hStdError = msvcrt.get_osfhandle(stderr_fd)

            job = win32job.CreateJobObject(None, "")
            limits = win32job.QueryInformationJobObject(
                job,
                win32job.JobObjectExtendedLimitInformation,
            )
            limits["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                job,
                win32job.JobObjectExtendedLimitInformation,
                limits,
            )

            flags = win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW
            process_handle, thread_handle, root_pid, _thread_id = (
                win32process.CreateProcess(
                    None,
                    subprocess.list2cmdline([str(value) for value in command]),
                    None,
                    None,
                    True,
                    flags,
                    None,
                    str(cwd),
                    startup,
                )
            )
            try:
                win32job.AssignProcessToJobObject(job, process_handle)
            except Exception as exc:
                win32process.TerminateProcess(process_handle, 1)
                win32event.WaitForSingleObject(process_handle, 2000)
                supervision_error = type(exc).__name__
                state = "supervision_unavailable"
                raise _SupervisionUnavailable from exc
            win32process.ResumeThread(thread_handle)
            self._emit(
                event_callback, "process_started", root_pid=root_pid, process_count=1
            )

            deadline = started + max(0.1, float(timeout_seconds))
            last_count = -1
            last_heartbeat = started
            while True:
                info = win32job.QueryInformationJobObject(
                    job,
                    win32job.JobObjectBasicAccountingInformation,
                )
                count = int(info.get("ActiveProcesses", 0))
                peak_count = max(peak_count, count)
                now = self._clock()
                if count != last_count:
                    self._emit(
                        event_callback,
                        "process_count_changed",
                        root_pid=root_pid,
                        process_count=count,
                        peak_process_count=peak_count,
                    )
                    last_count = count
                elif now - last_heartbeat >= 5.0:
                    self._emit(
                        event_callback,
                        "process_heartbeat",
                        root_pid=root_pid,
                        process_count=count,
                        peak_process_count=peak_count,
                        elapsed_seconds=round(now - started, 3),
                    )
                    last_heartbeat = now
                if cancel_check is not None and cancel_check():
                    state = "cancelled"
                    win32job.TerminateJobObject(job, 2)
                    break
                if count == 0:
                    state = "completed"
                    break
                if now >= deadline:
                    state = "timeout"
                    win32job.TerminateJobObject(job, 3)
                    break
                self._sleep(min(self.poll_interval, max(0.01, deadline - now)))

            if state in {"cancelled", "timeout"}:
                cleanup_deadline = self._clock() + 5.0
                while self._clock() < cleanup_deadline:
                    info = win32job.QueryInformationJobObject(
                        job,
                        win32job.JobObjectBasicAccountingInformation,
                    )
                    if int(info.get("ActiveProcesses", 0)) == 0:
                        break
                    self._sleep(self.poll_interval)
            wait_result = win32event.WaitForSingleObject(process_handle, 0)
            if wait_result == win32con.WAIT_OBJECT_0:
                raw_exit = int(win32process.GetExitCodeProcess(process_handle))
                exit_code = (
                    raw_exit if raw_exit < 0x80000000 else raw_exit - 0x100000000
                )
            self._emit(
                event_callback,
                "process_finished",
                root_pid=root_pid,
                process_count=0,
                peak_process_count=peak_count,
                exit_code=exit_code,
                exit_code_hex=(
                    f"0x{(exit_code & 0xFFFFFFFF):08X}" if exit_code is not None else ""
                ),
                state=state,
            )
        except _SupervisionUnavailable:
            pass
        except Exception as exc:
            supervision_error = type(exc).__name__
            state = "start_failed"
            if job is not None:
                try:
                    win32job.TerminateJobObject(job, 4)
                except Exception:
                    pass
        finally:
            for descriptor in (stdin_fd, stdout_fd, stderr_fd):
                if descriptor >= 0:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
            for handle in (thread_handle, process_handle, job):
                if handle is not None:
                    try:
                        win32api.CloseHandle(handle)
                    except Exception:
                        pass

        stderr_tail = self._read_tail(stderr_path)
        try:
            stderr_path.unlink(missing_ok=True)
        except OSError:
            pass
        return SupervisedProcessResult(
            state,
            exit_code,
            root_pid=root_pid,
            peak_process_count=peak_count,
            stderr_tail=stderr_tail,
            elapsed_seconds=max(0.0, self._clock() - started),
            supervision_error=supervision_error,
        )

    def _read_tail(self, path: Path) -> str:
        try:
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - self.stderr_max_bytes))
                value = stream.read()
        except OSError:
            return ""
        return re.sub(
            r"[\r\n\t]+",
            " ",
            value.decode("utf-8", errors="replace"),
        ).strip()[-4096:]

    @staticmethod
    def _emit(callback: ProcessEvent, event: str, **values: object) -> None:
        if callback is None:
            return
        try:
            callback(event, values)
        except Exception:
            pass
