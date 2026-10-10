# -*- coding: utf-8 -*-

"""定期実行履歴の追記専用JSONL台帳。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator, Optional

from ..app.run_guard import RunGuard
from .models import ScheduledRunRecord


class ScheduleRunLedger:
    """実行履歴を保存し、壊れた行を無視して直近履歴を返す。"""

    _PROCESS_LOCK_TIMEOUT_SECONDS = 10.0
    _PROCESS_LOCK_POLL_SECONDS = 0.025
    _REVERSE_READ_CHUNK_BYTES = 64 * 1024

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        canonical_path = os.path.normcase(
            str(self.path.resolve(strict=False))
        )
        path_digest = hashlib.sha256(
            canonical_path.encode("utf-8")
        ).hexdigest()[:24]
        self._process_guard = RunGuard(
            rf"Local\ippi-down.ScheduleRunLedger.{path_digest}"
        )

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        """同じJSONLを使う別プロセスの追記・読取りを直列化する。"""
        deadline = time.monotonic() + self._PROCESS_LOCK_TIMEOUT_SECONDS
        while True:
            # yield中の例外でもRunGuardのfinallyでmutexは必ず解放される。
            with self._process_guard.try_acquire() as acquired:
                if acquired:
                    yield
                    return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "定期実行履歴のプロセス間ロックを取得できません"
                )
            time.sleep(self._PROCESS_LOCK_POLL_SECONDS)

    def append(self, record: ScheduledRunRecord) -> None:
        payload = json.dumps(
            record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self._lock:
            with self._process_lock():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open(
                    "a", encoding="utf-8", newline="\n"
                ) as stream:
                    # 1レコードを1回のwriteで渡し、途中行の発生範囲を抑える。
                    stream.write(payload + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())

    write = append

    @classmethod
    def _iter_lines_reverse(cls, stream: BinaryIO) -> Iterator[bytes]:
        """JSONLを末尾から行単位で返し、ファイル全体を常駐させない。"""

        stream.seek(0, os.SEEK_END)
        position = stream.tell()
        remainder = b""
        while position > 0:
            read_size = min(cls._REVERSE_READ_CHUNK_BYTES, position)
            position -= read_size
            stream.seek(position)
            block = stream.read(read_size)
            parts = (block + remainder).split(b"\n")
            remainder = parts[0]
            for line in reversed(parts[1:]):
                yield line.removesuffix(b"\r")
        if remainder:
            yield remainder.removesuffix(b"\r")

    @staticmethod
    def _record_from_line(line: bytes) -> Optional[ScheduledRunRecord]:
        if not line.strip():
            return None
        try:
            data = json.loads(line.decode("utf-8"))
            if not isinstance(data, dict):
                return None
            return ScheduledRunRecord.from_dict(data)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            # 末尾への書込み中に電源断しても、それ以前の履歴は表示する。
            return None

    def recent(
        self,
        limit: int = 20,
        *,
        profile_id: Optional[str] = None,
        schedule_id: Optional[str] = None,
        snapshot_id: Optional[str] = None,
    ) -> list[ScheduledRunRecord]:
        if limit <= 0:
            return []
        records: list[ScheduledRunRecord] = []
        with self._lock:
            try:
                with self._process_lock():
                    if not self.path.exists():
                        return []
                    with self.path.open("rb") as stream:
                        for line in self._iter_lines_reverse(stream):
                            record = self._record_from_line(line)
                            if record is None:
                                continue
                            wanted_snapshot = snapshot_id or profile_id
                            if (
                                wanted_snapshot is not None
                                and record.snapshot_id != wanted_snapshot
                            ):
                                continue
                            if (
                                schedule_id is not None
                                and record.schedule_id != schedule_id
                            ):
                                continue
                            records.append(record)
                            if len(records) >= limit:
                                break
            except (OSError, TimeoutError):
                return []
        return records

    read_recent = recent

    def latest(
        self,
        profile_id: Optional[str] = None,
        *,
        schedule_id: Optional[str] = None,
        snapshot_id: Optional[str] = None,
    ) -> Optional[ScheduledRunRecord]:
        records = self.recent(
            1,
            profile_id=profile_id,
            schedule_id=schedule_id,
            snapshot_id=snapshot_id,
        )
        return records[0] if records else None

    last = latest

    def latest_many(
        self,
        schedule_ids: Iterable[str],
    ) -> dict[str, Optional[ScheduledRunRecord]]:
        """複数scheduleの最新レコードをJSONLの1回の逆走査で返す。"""

        identifiers = tuple(dict.fromkeys(str(value) for value in schedule_ids))
        results: dict[str, Optional[ScheduledRunRecord]] = {
            identifier: None for identifier in identifiers
        }
        remaining = set(identifiers)
        if not remaining:
            return results

        with self._lock:
            try:
                with self._process_lock():
                    if not self.path.exists():
                        return results
                    with self.path.open("rb") as stream:
                        for line in self._iter_lines_reverse(stream):
                            record = self._record_from_line(line)
                            if record is None or record.schedule_id not in remaining:
                                continue
                            results[record.schedule_id] = record
                            remaining.remove(record.schedule_id)
                            if not remaining:
                                break
            except (OSError, TimeoutError):
                return results
        return results

    def merge_from(
        self,
        source_path: str | Path,
        *,
        schedule_id: str,
    ) -> int:
        """別配置の履歴をrun_id（旧行は内容hash）で重複排除して追記する。"""

        source = ScheduleRunLedger(source_path)
        target_resolved = self.path.resolve(strict=False)
        source_resolved = source.path.resolve(strict=False)
        if os.path.normcase(str(target_resolved)) == os.path.normcase(
            str(source_resolved)
        ):
            return 0
        if not source.path.is_file():
            return 0

        ledgers = sorted(
            (self, source),
            key=lambda item: os.path.normcase(
                str(item.path.resolve(strict=False))
            ),
        )
        with ExitStack() as stack:
            for ledger in ledgers:
                stack.enter_context(ledger._lock)
            for ledger in ledgers:
                stack.enter_context(ledger._process_lock())

            known: set[str] = set()
            if self.path.is_file():
                with self.path.open("rb") as target_stream:
                    for line in target_stream:
                        record = self._record_from_line(line)
                        if record is not None:
                            known.add(self._record_identity(record))

            pending: list[str] = []
            with source.path.open("rb") as source_stream:
                for line in source_stream:
                    record = self._record_from_line(line)
                    if record is None or record.schedule_id != schedule_id:
                        continue
                    identity = self._record_identity(record)
                    if identity in known:
                        continue
                    known.add(identity)
                    pending.append(
                        json.dumps(
                            record.to_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
            if not pending:
                return 0
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write("\n".join(pending) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return len(pending)

    @staticmethod
    def _record_identity(record: ScheduledRunRecord) -> str:
        if record.run_id:
            return "run:" + record.run_id
        payload = json.dumps(
            record.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "legacy:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
