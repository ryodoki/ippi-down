# -*- coding: utf-8 -*-

"""GUI・CLI・Windowsタスクをまたいでダウンロード実行を直列化する。"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
from threading import Lock
from typing import Any, Iterator, Optional, Protocol


DEFAULT_MUTEX_NAME = r"Local\ippi-down.DownloadRun"
SCHEDULE_MUTEX_PREFIX = r"Local\ippi-down.ScheduleRun"


class _ProcessMutex(Protocol):
    """OSレベルの非ブロッキングmutex実装。"""

    def try_acquire(self) -> Optional[Any]:
        """取得できた場合は解放用token、競合時はNoneを返す。"""

    def release(self, token: Any) -> None:
        """取得済みtokenを解放する。"""


class _WindowsNamedMutex:
    """Win32の名前付きmutexを最小限のctypes呼び出しで扱う。"""

    _ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._create_mutex = self._kernel32.CreateMutexW
        self._create_mutex.argtypes = (
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        self._create_mutex.restype = wintypes.HANDLE
        self._release_mutex = self._kernel32.ReleaseMutex
        self._release_mutex.argtypes = (wintypes.HANDLE,)
        self._release_mutex.restype = wintypes.BOOL
        self._close_handle = self._kernel32.CloseHandle
        self._close_handle.argtypes = (wintypes.HANDLE,)
        self._close_handle.restype = wintypes.BOOL
        self._name = name

    def try_acquire(self) -> Optional[Any]:
        self._ctypes.set_last_error(0)
        handle = self._create_mutex(None, True, self._name)
        if not handle:
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        if self._ctypes.get_last_error() == self._ERROR_ALREADY_EXISTS:
            # 既存mutexの所有権は得ていないため、handleだけ閉じる。
            self._close_handle(handle)
            return None
        return handle

    def release(self, token: Any) -> None:
        try:
            self._release_mutex(token)
        finally:
            self._close_handle(token)


class _PosixFileMutex:
    """非Windows環境で同じ非ブロッキング動作を保つfallback。"""

    def __init__(self, name: str) -> None:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
        self._path = Path(tempfile.gettempdir()) / f"ippi-down-{digest}.lock"

    def try_acquire(self) -> Optional[Any]:
        import fcntl

        stream = self._path.open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            return None
        except Exception:
            stream.close()
            raise
        return stream

    def release(self, token: Any) -> None:
        import fcntl

        try:
            fcntl.flock(token.fileno(), fcntl.LOCK_UN)
        finally:
            token.close()


def _create_process_mutex(name: str) -> _ProcessMutex:
    if os.name == "nt":
        return _WindowsNamedMutex(name)
    return _PosixFileMutex(name)


class RunGuard:
    """全実行経路の重複を防ぐ非ブロッキングロック。"""

    def __init__(
        self,
        name: str = DEFAULT_MUTEX_NAME,
        *,
        process_mutex: Optional[_ProcessMutex] = None,
    ) -> None:
        self.name = name
        self._lock = Lock()
        self._process_mutex = process_mutex or _create_process_mutex(name)

    @contextmanager
    def try_acquire(self) -> Iterator[bool]:
        local_acquired = self._lock.acquire(blocking=False)
        token: Optional[Any] = None
        acquired = False
        try:
            if local_acquired:
                try:
                    token = self._process_mutex.try_acquire()
                except OSError:
                    # 排他機構が壊れた状態で実行を始めるより安全側に倒す。
                    token = None
                acquired = token is not None
            yield acquired
        finally:
            if token is not None:
                self._process_mutex.release(token)
            if local_acquired:
                self._lock.release()


DOWNLOAD_RUN_GUARD = RunGuard()


def schedule_guard_name(schedule_id: str) -> str:
    """論理スケジュールIDから安全で固定長のmutex名を作る。"""

    value = str(schedule_id).strip()
    if not value:
        raise ValueError("schedule_idは空にできません")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return rf"{SCHEDULE_MUTEX_PREFIX}.{digest}"


def make_schedule_run_guard(schedule_id: str) -> RunGuard:
    """同じ論理スケジュールの重複起動だけを拒否するguardを返す。"""

    return RunGuard(schedule_guard_name(schedule_id))


__all__ = [
    "DEFAULT_MUTEX_NAME",
    "DOWNLOAD_RUN_GUARD",
    "RunGuard",
    "SCHEDULE_MUTEX_PREFIX",
    "make_schedule_run_guard",
    "schedule_guard_name",
]
