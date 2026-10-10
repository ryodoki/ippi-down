# -*- coding: utf-8 -*-

"""Windowsタスクからの実行要求をプロセス間FIFOで直列化する。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Callable, Iterator, Optional
import uuid

from .run_guard import (
    DOWNLOAD_RUN_GUARD,
    RunGuard,
    make_schedule_run_guard,
)


DEFAULT_QUEUE_WAIT_SECONDS = 2 * 60 * 60
DEFAULT_PROCESSING_SECONDS = 2 * 60 * 60
DEFAULT_QUEUE_POLL_SECONDS = 0.25
DEFAULT_TEMP_STALE_SECONDS = 5 * 60
_STATE_LOCK_TIMEOUT_SECONDS = 10.0
_SCHEDULE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_OWNED_TEMP_FILE = re.compile(
    r"^\.[0-9a-f]{32}-p(?P<pid>[1-9][0-9]*)-"
    r"c(?P<created>[0-9]+)-.*\.tmp$"
)
_LEGACY_TEMP_FILE = re.compile(r"^\.[0-9a-f]{32}-.+\.tmp$")


class RunQueueError(RuntimeError):
    """キュー状態を安全に更新できないときの例外。"""


@dataclass(frozen=True)
class QueueTicket:
    """秘密情報を持たない、1回の実行要求を表す永続ticket。"""

    ticket_id: str
    run_id: str
    schedule_id: str
    snapshot_id: str
    pid: int
    order: int
    enqueued_at: datetime
    config_path: str = ""
    detached: bool = False
    state: str = "queued"
    dispatcher_pid: int = 0
    started_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "ticket_id": self.ticket_id,
            "run_id": self.run_id,
            "schedule_id": self.schedule_id,
            "snapshot_id": self.snapshot_id,
            "pid": self.pid,
            "order": self.order,
            "enqueued_at": self.enqueued_at.isoformat(),
            "detached": self.detached,
            "state": self.state,
            "dispatcher_pid": self.dispatcher_pid,
            "started_at": (
                self.started_at.isoformat() if self.started_at else None
            ),
            "scheduled_at": (
                self.scheduled_at.isoformat() if self.scheduled_at else None
            ),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "QueueTicket":
        if not isinstance(value, dict):
            raise ValueError("ticketはmappingである必要があります")
        enqueued_at = datetime.fromisoformat(str(value["enqueued_at"]))
        if enqueued_at.tzinfo is None:
            enqueued_at = enqueued_at.replace(tzinfo=timezone.utc)

        def parse_optional_datetime(raw: object) -> Optional[datetime]:
            if not raw:
                return None
            parsed = datetime.fromisoformat(str(raw))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        state = str(value.get("state") or "queued").casefold()
        if state not in {"queued", "running", "retry_waiting"}:
            raise ValueError("ticket stateが不正です")
        return cls(
            ticket_id=str(value["ticket_id"]),
            run_id=str(value["run_id"]),
            schedule_id=validate_schedule_id(str(value["schedule_id"])),
            snapshot_id=str(value.get("snapshot_id", "") or ""),
            pid=int(value["pid"]),
            order=int(value["order"]),
            enqueued_at=enqueued_at.astimezone(timezone.utc),
            config_path=str(value.get("config_path") or ""),
            detached=bool(value.get("detached", False)),
            state=state,
            dispatcher_pid=int(value.get("dispatcher_pid", 0) or 0),
            started_at=parse_optional_datetime(value.get("started_at")),
            scheduled_at=parse_optional_datetime(value.get("scheduled_at")),
        )


@dataclass(frozen=True)
class QueueTurn:
    """キュー待機結果。acquired=Trueのcontext中だけ実処理を行える。"""

    acquired: bool
    wait_seconds: float
    reason_code: str = ""
    ticket_id: str = ""


@dataclass(frozen=True)
class ScheduleQueueStatus:
    """GUIへ返す、特定スケジュールの待機状況。"""

    schedule_id: str
    waiting: bool
    position: Optional[int]
    total_waiting: int
    run_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    enqueued_at: Optional[datetime] = None
    running: bool = False
    retry_waiting: bool = False


def validate_schedule_id(schedule_id: str) -> str:
    """ファイル名やmutex名へ直接展開できるIDだけを許可する。"""

    value = str(schedule_id).strip()
    if not _SCHEDULE_ID.fullmatch(value):
        raise ValueError(
            "schedule_idは英数字で始まる英数字、ハイフン、"
            "アンダースコアの1～64文字で指定してください"
        )
    return value


def _default_queue_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        app_data_root = Path(local_app_data) / "ippi-down"
        install_id_path = app_data_root / "install-id"
        install_id = _load_or_create_install_id(install_id_path)
        return app_data_root / "run-queue" / install_id
    return Path(tempfile.gettempdir()) / "ippi-down" / "run-queue"


def _load_or_create_install_id(path: Path) -> str:
    """scheduler backendと同じユーザー単位install-idを安全に得る。"""

    def validate(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise RunQueueError("install-idが不正です")
        return value

    try:
        if path.exists():
            return validate(path.read_text(encoding="utf-8").strip())
        legacy_path = Path(__file__).resolve().parents[2] / "config" / "install-id"
        install_id = uuid.uuid4().hex[:12]
        if legacy_path != path and legacy_path.exists():
            install_id = validate(
                legacy_path.read_text(encoding="utf-8").strip()
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(install_id + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return install_id
        except FileExistsError:
            for _ in range(10):
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return validate(value)
                time.sleep(0.02)
            raise RunQueueError("install-idを読み込めません")
    except (OSError, UnicodeError) as exc:
        raise RunQueueError(f"install-idを読み書きできません: {exc}") from exc


def _default_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    wait_for_single = kernel32.WaitForSingleObject
    wait_for_single.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait_for_single.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = open_process(synchronize, False, pid)
    if not handle:
        # アクセス拒否はPIDが存在することを示す。その他は終了済みとして扱う。
        return ctypes.get_last_error() == 5
    try:
        return wait_for_single(handle, 0) == wait_timeout
    finally:
        close_handle(handle)


class RunQueue:
    """ticketファイルと短時間mutexで構成するプロセス間FIFO。"""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        global_guard: RunGuard = DOWNLOAD_RUN_GUARD,
        guard_factory: Callable[[str], RunGuard] = RunGuard,
        schedule_guard_factory: Callable[[str], RunGuard] = (
            make_schedule_run_guard
        ),
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        process_alive: Callable[[int], bool] = _default_process_alive,
        poll_seconds: float = DEFAULT_QUEUE_POLL_SECONDS,
        stale_after_seconds: float = DEFAULT_QUEUE_WAIT_SECONDS + 300,
        state_lock_timeout_seconds: float = _STATE_LOCK_TIMEOUT_SECONDS,
        dispatcher_guard: Optional[RunGuard] = None,
    ) -> None:
        self.root = Path(root or _default_queue_root()).resolve(strict=False)
        canonical = os.path.normcase(str(self.root))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        self._state_guard = guard_factory(
            rf"Local\ippi-down.RunQueueState.{digest}"
        )
        self._dispatcher_guard = dispatcher_guard or RunGuard(
            rf"Local\ippi-down.RunQueueDispatcher.{digest}"
        )
        self._global_guard = global_guard
        self._schedule_guard_factory = schedule_guard_factory
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._process_alive = process_alive
        self._poll_seconds = max(0.001, float(poll_seconds))
        self._stale_after_seconds = max(0.0, float(stale_after_seconds))
        self._state_lock_timeout_seconds = max(
            0.001, float(state_lock_timeout_seconds)
        )
        self._last_temp_sweep = float("-inf")

    @contextmanager
    def dispatcher_lease(
        self,
        *,
        handoff_seconds: float = 0.0,
    ) -> Iterator[bool]:
        """install-idごとにdispatcherを1プロセスだけに限定する。

        enqueueと既存dispatcher終了が競合した場合だけ短時間再試行し、
        永続ticketが次回起動まで取り残される窓を狭める。
        """

        deadline = self._clock() + max(0.0, float(handoff_seconds))
        while True:
            with self._dispatcher_guard.try_acquire() as acquired:
                if acquired:
                    yield True
                    return
            if self._clock() >= deadline:
                yield False
                return
            self._sleep(
                min(
                    self._poll_seconds,
                    max(0.0, deadline - self._clock()),
                )
            )

    @contextmanager
    def schedule_lease(self, schedule_id: str) -> Iterator[bool]:
        """同じ論理スケジュールの実行を1つに限定する。"""

        identifier = validate_schedule_id(schedule_id)
        guard = self._schedule_guard_factory(identifier)
        with guard.try_acquire() as acquired:
            yield acquired

    @contextmanager
    def wait_for_turn(
        self,
        schedule_id: str,
        run_id: str,
        *,
        snapshot_id: str = "",
        timeout_seconds: float = DEFAULT_QUEUE_WAIT_SECONDS,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Iterator[QueueTurn]:
        """FIFOの先頭でglobal実行枠を得るまで待つ。"""

        identifier = validate_schedule_id(schedule_id)
        ticket = self._enqueue(
            identifier,
            str(run_id),
            snapshot_id=str(snapshot_id),
        )
        wait_started = self._clock()
        global_context = None
        acquired = False
        result = QueueTurn(False, 0.0, "QUEUE_TIMEOUT", ticket.ticket_id)
        try:
            while True:
                elapsed = max(0.0, self._clock() - wait_started)
                if cancel_check is not None and cancel_check():
                    result = QueueTurn(
                        False, elapsed, "CANCELLED", ticket.ticket_id
                    )
                    break
                if elapsed >= max(0.0, float(timeout_seconds)):
                    result = QueueTurn(
                        False, elapsed, "QUEUE_TIMEOUT", ticket.ticket_id
                    )
                    break

                with self._state_lock():
                    tickets = self._read_tickets_locked(
                        protected_ticket_ids={ticket.ticket_id}
                    )
                    is_head = bool(
                        tickets and tickets[0].ticket_id == ticket.ticket_id
                    )
                    if is_head:
                        candidate = self._global_guard.try_acquire()
                        got_global = candidate.__enter__()
                        if got_global:
                            global_context = candidate
                            acquired = True
                            self._delete_ticket_locked(ticket.ticket_id)
                        else:
                            candidate.__exit__(None, None, None)
                if acquired:
                    elapsed = max(0.0, self._clock() - wait_started)
                    result = QueueTurn(
                        True, elapsed, "", ticket.ticket_id
                    )
                    break
                remaining = max(0.0, float(timeout_seconds) - elapsed)
                self._sleep(min(self._poll_seconds, remaining))

            yield result
        finally:
            if acquired and global_context is not None:
                global_context.__exit__(None, None, None)
            self._remove_ticket(ticket.ticket_id)

    @contextmanager
    def try_acquire_manual(self) -> Iterator[bool]:
        """待機ticketがない場合だけGUI/手動実行へglobal枠を渡す。"""

        global_context = None
        acquired = False
        try:
            try:
                with self._state_lock():
                    if not self._read_tickets_locked():
                        candidate = self._global_guard.try_acquire()
                        acquired = bool(candidate.__enter__())
                        if acquired:
                            global_context = candidate
                        else:
                            candidate.__exit__(None, None, None)
            except RunQueueError:
                # 状態を確認できない場合、待機ジョブを追い越さない。
                acquired = False
            yield acquired
        finally:
            if acquired and global_context is not None:
                global_context.__exit__(None, None, None)

    def list_queue(self) -> list[QueueTicket]:
        """現在有効な待機ticketをFIFO順で返す。"""

        with self._state_lock():
            return list(self._read_tickets_locked())

    def has_waiting_jobs(self) -> bool:
        """GUIの手動実行可否判定向けの軽量照会。"""

        try:
            return bool(self.list_queue())
        except RunQueueError:
            # 照会不能時に手動実行を許すとFIFOを破るため安全側へ倒す。
            return True

    def status_for(self, schedule_id: str) -> ScheduleQueueStatus:
        """指定スケジュールの先頭ticketと待ち順位を返す。"""

        identifier = validate_schedule_id(schedule_id)
        tickets = self.list_queue()
        queued = [ticket for ticket in tickets if ticket.state == "queued"]
        for ticket in tickets:
            if ticket.schedule_id == identifier:
                position = (
                    queued.index(ticket) + 1 if ticket in queued else None
                )
                return ScheduleQueueStatus(
                    schedule_id=identifier,
                    waiting=ticket.state == "queued",
                    position=position,
                    total_waiting=len(queued),
                    run_id=ticket.run_id,
                    snapshot_id=ticket.snapshot_id,
                    enqueued_at=ticket.enqueued_at,
                    running=ticket.state in {"running", "retry_waiting"},
                    retry_waiting=ticket.state == "retry_waiting",
                )
        return ScheduleQueueStatus(
            schedule_id=identifier,
            waiting=False,
            position=None,
            total_waiting=len(queued),
        )

    def enqueue_dispatch_request(
        self,
        schedule_id: str,
        run_id: str,
        *,
        snapshot_id: str,
        config_path: str | Path,
        scheduled_at: Optional[datetime] = None,
    ) -> Optional[QueueTicket]:
        """dispatcherへ渡す要求を保存する。同じ設定の重複は拒否する。"""

        identifier = validate_schedule_id(schedule_id)
        # 設定ファイルは呼出側ですでに検証済み。ticketには検索条件や
        # ユーザーパスを保存せず、snapshot_idから共通profile格納先を
        # dispatcher側で解決する。
        Path(config_path).expanduser().resolve(strict=False)
        if not run_id:
            raise ValueError("run_idは空にできません")
        with self._state_lock():
            existing = self._read_tickets_locked()
            if any(item.schedule_id == identifier for item in existing):
                return None
            ticket = self._new_ticket(
                identifier,
                run_id,
                snapshot_id=snapshot_id,
                existing=existing,
                detached=True,
                scheduled_at=scheduled_at,
            )
            self._write_ticket_locked(ticket)
            return ticket

    def claim_next_dispatch_request(self) -> Optional[QueueTicket]:
        """FIFO先頭をrunningへ原子的に変更してdispatcherへ渡す。"""

        with self._state_lock():
            tickets = self._read_tickets_locked()
            if any(
                item.state in {"running", "retry_waiting"}
                for item in tickets
            ):
                return None
            ticket = next(
                (
                    item
                    for item in tickets
                    if item.detached and item.state == "queued"
                ),
                None,
            )
            if ticket is None:
                return None
            claimed = replace(
                ticket,
                state="running",
                dispatcher_pid=os.getpid(),
                started_at=datetime.fromtimestamp(
                    self._wall_clock(), timezone.utc
                ),
            )
            self._write_ticket_locked(claimed)
            return claimed

    def complete_dispatch_request(self, ticket_id: str) -> None:
        """dispatcherが処理済みの要求を削除する。"""

        with self._state_lock():
            self._delete_ticket_locked(str(ticket_id))

    def set_dispatch_state(self, ticket_id: str, state: str) -> None:
        """実行中ticketの状態を診断表示のため原子的に更新する。"""

        next_state = str(state).casefold()
        if next_state not in {"running", "retry_waiting"}:
            raise ValueError("実行中ticketの状態が不正です")
        with self._state_lock():
            tickets = self._read_tickets_locked()
            target = next(
                (item for item in tickets if item.ticket_id == str(ticket_id)),
                None,
            )
            if target is None:
                raise RunQueueError("更新対象の実行ticketが見つかりません")
            if target.state not in {"running", "retry_waiting"}:
                raise RunQueueError("待機中ticketの実行状態は変更できません")
            self._write_ticket_locked(replace(target, state=next_state))

    @contextmanager
    def dispatch_turn(
        self,
        ticket: QueueTicket,
        *,
        timeout_seconds: float = DEFAULT_QUEUE_WAIT_SECONDS,
    ) -> Iterator[QueueTurn]:
        """dispatcher自身は追加ticketを作らずglobal実行枠を待つ。"""

        wait_started = self._clock()
        already_waited = max(
            0.0,
            self._wall_clock() - ticket.enqueued_at.timestamp(),
        )
        global_context = None
        acquired = False
        result = QueueTurn(
            False, already_waited, "QUEUE_TIMEOUT", ticket.ticket_id
        )
        try:
            while True:
                elapsed = already_waited + max(
                    0.0, self._clock() - wait_started
                )
                if elapsed >= max(0.0, float(timeout_seconds)):
                    result = QueueTurn(
                        False,
                        elapsed,
                        "QUEUE_TIMEOUT",
                        ticket.ticket_id,
                    )
                    break
                with self._state_lock():
                    tickets = self._read_tickets_locked(
                        protected_ticket_ids={ticket.ticket_id}
                    )
                    is_head = bool(
                        tickets and tickets[0].ticket_id == ticket.ticket_id
                    )
                    if is_head:
                        candidate = self._global_guard.try_acquire()
                        got_global = bool(candidate.__enter__())
                        if got_global:
                            global_context = candidate
                            acquired = True
                        else:
                            candidate.__exit__(None, None, None)
                if acquired:
                    result = QueueTurn(
                        True, elapsed, "", ticket.ticket_id
                    )
                    break
                remaining = max(0.0, float(timeout_seconds) - elapsed)
                self._sleep(min(self._poll_seconds, remaining))
            yield result
        finally:
            if acquired and global_context is not None:
                global_context.__exit__(None, None, None)

    def _enqueue(
        self,
        schedule_id: str,
        run_id: str,
        *,
        snapshot_id: str = "",
    ) -> QueueTicket:
        if not run_id:
            raise ValueError("run_idは空にできません")
        with self._state_lock():
            existing = self._read_tickets_locked()
            ticket = self._new_ticket(
                schedule_id,
                run_id,
                snapshot_id=snapshot_id,
                existing=existing,
            )
            self._write_ticket_locked(ticket)
            return ticket

    def _new_ticket(
        self,
        schedule_id: str,
        run_id: str,
        *,
        snapshot_id: str,
        existing: list[QueueTicket],
        config_path: str = "",
        detached: bool = False,
        scheduled_at: Optional[datetime] = None,
    ) -> QueueTicket:
        base_order = int(self._wall_clock() * 1_000_000)
        order = max(
            base_order,
            max((item.order for item in existing), default=base_order - 1)
            + 1,
        )
        return QueueTicket(
            ticket_id=uuid.uuid4().hex,
            run_id=run_id,
            schedule_id=schedule_id,
            snapshot_id=snapshot_id,
            pid=os.getpid(),
            order=order,
            enqueued_at=datetime.fromtimestamp(
                self._wall_clock(), timezone.utc
            ),
            config_path=config_path,
            detached=detached,
            scheduled_at=(
                scheduled_at.astimezone(timezone.utc)
                if scheduled_at is not None
                else None
            ),
        )

    @contextmanager
    def _state_lock(self) -> Iterator[None]:
        deadline = self._clock() + self._state_lock_timeout_seconds
        while True:
            with self._state_guard.try_acquire() as acquired:
                if acquired:
                    yield
                    return
            if self._clock() >= deadline:
                raise RunQueueError(
                    "実行キューのプロセス間ロックを取得できません"
                )
            self._sleep(
                min(
                    self._poll_seconds,
                    max(0.0, deadline - self._clock()),
                )
            )

    def _read_tickets_locked(
        self,
        *,
        protected_ticket_ids: set[str] | None = None,
    ) -> list[QueueTicket]:
        protected = protected_ticket_ids or set()
        self._sweep_temporary_files_locked()
        try:
            if not self.root.exists():
                return []
            paths = list(self.root.glob("*.json"))
        except OSError as exc:
            raise RunQueueError(
                f"実行キューを読み込めません: {exc}"
            ) from exc
        tickets: list[QueueTicket] = []
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                ticket = QueueTicket.from_mapping(payload)
                if path.stem != ticket.ticket_id:
                    raise ValueError("ticket_idとファイル名が一致しません")
            except (OSError, UnicodeError, ValueError, KeyError, TypeError):
                self._safe_unlink(path)
                continue
            if (
                ticket.detached
                and ticket.state in {"running", "retry_waiting"}
                and (
                    ticket.dispatcher_pid <= 0
                    or not self._is_process_alive(ticket.dispatcher_pid)
                )
            ):
                # dispatcher異常終了後は同じticketを次のdispatcherが
                # 再取得する。設定内容はsnapshot側で不変性を検証する。
                ticket = replace(
                    ticket,
                    state="queued",
                    dispatcher_pid=0,
                    started_at=None,
                )
                self._write_ticket_locked(ticket)
            if (
                ticket.ticket_id not in protected
                and self._is_stale(ticket)
            ):
                self._safe_unlink(path)
                continue
            tickets.append(ticket)
        return sorted(tickets, key=lambda item: (item.order, item.ticket_id))

    def _is_stale(self, ticket: QueueTicket) -> bool:
        age = max(
            0.0,
            self._wall_clock() - ticket.enqueued_at.timestamp(),
        )
        if ticket.detached:
            # enqueue元はticket保存後すぐ終了してよい。生存判定は
            # running状態のdispatcherに対してだけ上で行う。待機上限を
            # 超えたticketも次のdispatcherが履歴へQUEUE_TIMEOUTを記録
            # できるよう、ここでは削除しない。
            return False
        if age > self._stale_after_seconds:
            return True
        try:
            return not self._process_alive(ticket.pid)
        except OSError:
            # PID照会そのものに失敗した場合は、経過時間でのみ回収する。
            return False

    def _is_process_alive(self, pid: int) -> bool:
        try:
            return bool(self._process_alive(pid))
        except OSError:
            # 照会不能時は使用中として扱い、期限による回収へ委ねる。
            return True

    def _sweep_temporary_files_locked(self) -> None:
        """中断された原子的書込みの古い.tmpだけを回収する。"""

        now = self._clock()
        if now - self._last_temp_sweep < 60.0:
            return
        self._last_temp_sweep = now
        if not self.root.exists():
            return
        wall_now = self._wall_clock()
        try:
            paths = tuple(self.root.glob(".*.tmp"))
        except OSError:
            return
        for path in paths:
            try:
                modified_age = max(0.0, wall_now - path.stat().st_mtime)
            except OSError:
                continue
            match = _OWNED_TEMP_FILE.fullmatch(path.name)
            if match is None:
                # 旧版が残したticket-id付きtmpだけはmtimeで回収する。
                # 出所不明のtmpへは触れない。
                expired = bool(
                    _LEGACY_TEMP_FILE.fullmatch(path.name)
                    and modified_age >= DEFAULT_TEMP_STALE_SECONDS
                )
            else:
                owner_pid = int(match.group("pid"))
                created_age = max(
                    0.0,
                    wall_now - float(match.group("created")),
                )
                expired = (
                    modified_age >= DEFAULT_TEMP_STALE_SECONDS
                    and created_age >= DEFAULT_TEMP_STALE_SECONDS
                    and not self._is_process_alive(owner_pid)
                )
            if expired:
                self._safe_unlink(path)

    def _write_ticket_locked(self, ticket: QueueTicket) -> None:
        target = self.root / f"{ticket.ticket_id}.json"
        temporary: Optional[Path] = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=(
                    f".{ticket.ticket_id}-p{os.getpid()}-"
                    f"c{int(self._wall_clock())}-"
                ),
                suffix=".tmp",
                dir=self.root,
                delete=False,
            ) as stream:
                json.dump(
                    ticket.to_mapping(),
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            os.replace(temporary, target)
        except OSError as exc:
            if temporary is not None:
                self._safe_unlink(temporary)
            raise RunQueueError(
                f"実行キューへticketを保存できません: {exc}"
            ) from exc

    def _delete_ticket_locked(self, ticket_id: str) -> None:
        self._safe_unlink(self.root / f"{ticket_id}.json")

    def _remove_ticket(self, ticket_id: str) -> None:
        try:
            with self._state_lock():
                self._delete_ticket_locked(ticket_id)
        except RunQueueError:
            # 所有PIDと期限による次回照会時の回収に委ねる。
            return

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return


_DEFAULT_QUEUE: Optional[RunQueue] = None
_DEFAULT_QUEUE_LOCK = threading.Lock()


def get_default_run_queue() -> RunQueue:
    """プロセス内で共有する既定キューを遅延生成する。"""

    global _DEFAULT_QUEUE
    with _DEFAULT_QUEUE_LOCK:
        if _DEFAULT_QUEUE is None:
            _DEFAULT_QUEUE = RunQueue()
        return _DEFAULT_QUEUE


def list_queue() -> list[QueueTicket]:
    return get_default_run_queue().list_queue()


def has_waiting_jobs() -> bool:
    return get_default_run_queue().has_waiting_jobs()


def status_for(schedule_id: str) -> ScheduleQueueStatus:
    return get_default_run_queue().status_for(schedule_id)


@contextmanager
def manual_run_slot() -> Iterator[bool]:
    """GUIが待機中のタスクを追い越さずに実行枠を得る。"""

    with get_default_run_queue().try_acquire_manual() as acquired:
        yield acquired


__all__ = [
    "DEFAULT_PROCESSING_SECONDS",
    "DEFAULT_QUEUE_POLL_SECONDS",
    "DEFAULT_QUEUE_WAIT_SECONDS",
    "QueueTicket",
    "QueueTurn",
    "RunQueue",
    "RunQueueError",
    "ScheduleQueueStatus",
    "get_default_run_queue",
    "has_waiting_jobs",
    "list_queue",
    "manual_run_slot",
    "status_for",
    "validate_schedule_id",
]
