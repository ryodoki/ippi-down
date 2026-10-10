# -*- coding: utf-8 -*-

"""複数のWindowsタスク登録を原子的に管理するv2レジストリ。"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Iterator, Mapping, Optional

from ..app.run_guard import RunGuard
from ..utils.file_utils import FileUtils
from .models import DEFAULT_SCHEDULE_ID, ScheduleServiceError


REGISTRATION_SCHEMA_VERSION = 2
LEGACY_REGISTRATION_SCHEMA_VERSION = 1
DEFAULT_SCHEDULE_NAME = "定期実行"
STORAGE_KEY_PATTERN = re.compile(r"S([0-9]{3,})")


def validate_schedule_id(schedule_id: str) -> str:
    """タスク名・ファイル内キーへ安全に使用できる安定IDを検証する。"""

    value = str(schedule_id or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ScheduleServiceError(
            f"スケジュールIDが不正です: {value}",
            "SCHEDULE_ID_INVALID",
        )
    return value


def next_storage_key(registry: Mapping[str, Any]) -> str:
    """registryの高水位から、次の単調な固定保存キーを返す。"""

    try:
        sequence = int(registry.get("next_storage_sequence", 1) or 1)
    except (TypeError, ValueError) as exc:
        raise ScheduleServiceError(
            "定期実行の固定保存キー採番情報が不正です",
            "REGISTRATION_METADATA_INVALID",
        ) from exc
    if sequence < 1:
        raise ScheduleServiceError(
            "定期実行の固定保存キー採番情報が不正です",
            "REGISTRATION_METADATA_INVALID",
        )
    registrations = registry.get("registrations", {})
    if isinstance(registrations, Mapping):
        for entry in registrations.values():
            if not isinstance(entry, Mapping):
                continue
            match = STORAGE_KEY_PATTERN.fullmatch(str(entry.get("storage_key") or ""))
            if match:
                sequence = max(sequence, int(match.group(1)) + 1)
    return f"S{sequence:03d}"


def make_storage_folder(storage_key: str, display_name: str) -> str:
    """初回表示名からWindowsで安全な固定保存フォルダー名を作る。"""

    match = STORAGE_KEY_PATTERN.fullmatch(str(storage_key or ""))
    if not match:
        raise ScheduleServiceError(
            "定期実行の固定保存キーが不正です",
            "STORAGE_KEY_INVALID",
        )
    safe_name = FileUtils.sanitize_filename(str(display_name or ""), max_length=80)
    return f"{storage_key}_{safe_name}"


class ScheduleRegistrationStore:
    """v1を安全に包み、v2の登録集合をプロセス間で直列化する。"""

    _LOCK_TIMEOUT_SECONDS = 30.0
    _LOCK_POLL_SECONDS = 0.05

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=False)
        canonical = os.path.normcase(str(self.path))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        self._process_guard = RunGuard(
            rf"Local\ippi-down.ScheduleRegistry.{digest}"
        )
        self._lock = threading.RLock()
        self._local = threading.local()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """タスク操作とregistry更新をまとめられる再入可能ロック。"""

        with self._lock:
            depth = int(getattr(self._local, "depth", 0))
            if depth:
                self._local.depth = depth + 1
                try:
                    yield
                finally:
                    self._local.depth -= 1
                return

            deadline = time.monotonic() + self._LOCK_TIMEOUT_SECONDS
            while True:
                with self._process_guard.try_acquire() as acquired:
                    if acquired:
                        self._local.depth = 1
                        try:
                            yield
                        finally:
                            self._local.depth = 0
                        return
                if time.monotonic() >= deadline:
                    raise ScheduleServiceError(
                        "定期実行の登録情報が別のプロセスで更新中です",
                        "REGISTRATION_LOCK_TIMEOUT",
                    )
                time.sleep(self._LOCK_POLL_SECONDS)

    def read(self) -> dict[str, Any]:
        with self.transaction():
            return deepcopy(self.read_unlocked())

    def read_unlocked(self) -> dict[str, Any]:
        """transaction内でregistryを読み、v1なら直ちに原子的に移行する。"""

        if not self.path.exists():
            return self.empty_document()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleServiceError(
                "定期実行の登録情報が壊れています",
                "REGISTRATION_METADATA_INVALID",
            ) from exc
        if not isinstance(data, dict):
            raise ScheduleServiceError(
                "定期実行の登録情報が壊れています",
                "REGISTRATION_METADATA_INVALID",
            )

        version = data.get("schema_version")
        if version == LEGACY_REGISTRATION_SCHEMA_VERSION:
            migrated = self._migrate_v1(data)
            # os.replace完了まではv1ファイルを一切変更しない。
            self.write_unlocked(migrated, increment_revision=False)
            return migrated
        if version != REGISTRATION_SCHEMA_VERSION:
            raise ScheduleServiceError(
                "未対応の定期実行登録情報です",
                "REGISTRATION_METADATA_INVALID",
            )
        return self._validate_v2(data)

    def write(self, document: Mapping[str, Any]) -> dict[str, Any]:
        with self.transaction():
            return self.write_unlocked(document)

    def write_unlocked(
        self,
        document: Mapping[str, Any],
        *,
        increment_revision: bool = True,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        payload = deepcopy(dict(document))
        payload["schema_version"] = REGISTRATION_SCHEMA_VERSION
        registrations = payload.setdefault("registrations", {})
        payload.setdefault("retained_snapshots", [])
        if not isinstance(registrations, dict):
            raise ScheduleServiceError(
                "定期実行の登録一覧が不正です",
                "REGISTRATION_METADATA_INVALID",
            )
        for schedule_id, entry in list(registrations.items()):
            validated_id = validate_schedule_id(str(schedule_id))
            if validated_id != schedule_id or not isinstance(entry, Mapping):
                raise ScheduleServiceError(
                    "定期実行の登録一覧が不正です",
                    "REGISTRATION_METADATA_INVALID",
                )
            registrations[schedule_id] = self._normalise_entry(schedule_id, entry)
        self._validate_unique_storage_keys(registrations)
        payload["next_storage_sequence"] = self._next_storage_sequence(
            payload,
            registrations,
        )
        revision = int(payload.get("revision", 0) or 0)
        if expected_revision is not None and revision != int(expected_revision):
            raise ScheduleServiceError(
                "定期実行の登録情報が別の画面またはプロセスで更新されました",
                "REGISTRATION_CONFLICT",
            )
        payload["revision"] = revision + 1 if increment_revision else max(1, revision)
        self._atomic_write(payload)
        return payload

    def put(
        self,
        schedule_id: str,
        entry: Mapping[str, Any],
        *,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        """最新registryを再読込し、対象1件だけを競合検出付きで更新する。"""

        identifier = validate_schedule_id(schedule_id)
        with self.transaction():
            document = self.read_unlocked()
            revision = int(document.get("revision", 0) or 0)
            if expected_revision is not None and revision != int(expected_revision):
                raise ScheduleServiceError(
                    "定期実行の登録情報が別の画面またはプロセスで更新されました",
                    "REGISTRATION_CONFLICT",
                )
            document["registrations"][identifier] = self._normalise_entry(
                identifier, entry
            )
            return self.write_unlocked(document, expected_revision=revision)

    def remove(
        self,
        schedule_id: str,
        *,
        expected_revision: Optional[int] = None,
    ) -> tuple[dict[str, Any], bool]:
        """最新registryから対象1件だけを削除する。"""

        identifier = validate_schedule_id(schedule_id)
        with self.transaction():
            document = self.read_unlocked()
            revision = int(document.get("revision", 0) or 0)
            if expected_revision is not None and revision != int(expected_revision):
                raise ScheduleServiceError(
                    "定期実行の登録情報が別の画面またはプロセスで更新されました",
                    "REGISTRATION_CONFLICT",
                )
            existed = document["registrations"].pop(identifier, None) is not None
            if existed:
                document = self.write_unlocked(document, expected_revision=revision)
            return document, existed

    @staticmethod
    def empty_document() -> dict[str, Any]:
        return {
            "schema_version": REGISTRATION_SCHEMA_VERSION,
            "revision": 0,
            "registrations": {},
            "retained_snapshots": [],
            "next_storage_sequence": 1,
        }

    def _validate_v2(self, data: Mapping[str, Any]) -> dict[str, Any]:
        registrations = data.get("registrations")
        if not isinstance(registrations, Mapping):
            raise ScheduleServiceError(
                "定期実行の登録一覧が不正です",
                "REGISTRATION_METADATA_INVALID",
            )
        normalised = deepcopy(dict(data))
        normalised["registrations"] = {
            validate_schedule_id(str(schedule_id)): self._normalise_entry(
                str(schedule_id), entry
            )
            for schedule_id, entry in registrations.items()
            if isinstance(entry, Mapping)
        }
        if len(normalised["registrations"]) != len(registrations):
            raise ScheduleServiceError(
                "定期実行の登録一覧が不正です",
                "REGISTRATION_METADATA_INVALID",
            )
        self._validate_unique_storage_keys(normalised["registrations"])
        try:
            normalised["revision"] = int(normalised.get("revision", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ScheduleServiceError(
                "定期実行の登録世代が不正です",
                "REGISTRATION_METADATA_INVALID",
            ) from exc
        retained = normalised.get("retained_snapshots", [])
        if not isinstance(retained, list) or not all(
            isinstance(item, Mapping) for item in retained
        ):
            raise ScheduleServiceError(
                "定期実行の保留スナップショット情報が不正です",
                "REGISTRATION_METADATA_INVALID",
            )
        normalised["retained_snapshots"] = [dict(item) for item in retained]
        normalised["next_storage_sequence"] = self._next_storage_sequence(
            normalised,
            normalised["registrations"],
        )
        return normalised

    def _migrate_v1(self, data: Mapping[str, Any]) -> dict[str, Any]:
        snapshot_id = str(data.get("snapshot_id") or data.get("profile_id") or "")
        if not snapshot_id:
            raise ScheduleServiceError(
                "旧定期実行登録にプロファイルIDがありません",
                "REGISTRATION_METADATA_INVALID",
            )
        schedule = data.get("schedule")
        if not isinstance(schedule, Mapping):
            raise ScheduleServiceError(
                "旧定期実行登録のスケジュールが不正です",
                "REGISTRATION_METADATA_INVALID",
            )
        entry = dict(data)
        entry.pop("schema_version", None)
        entry.update(
            {
                "schedule_id": DEFAULT_SCHEDULE_ID,
                "name": str(data.get("name") or "既存の定期実行"),
                "enabled": bool(schedule.get("enabled", True)),
                "snapshot_id": snapshot_id,
                "snapshot_path": str(
                    data.get("snapshot_path") or data.get("profile_path") or ""
                ),
                "snapshot_fingerprint": str(
                    data.get("snapshot_fingerprint")
                    or data.get("profile_fingerprint")
                    or ""
                ),
                # 正規のv1 fingerprintは検索・保存条件fingerprintだった。
                "condition_fingerprint": str(
                    data.get("condition_fingerprint")
                    or data.get("profile_fingerprint")
                    or ""
                ),
                "created_at": str(data.get("created_at") or data.get("registered_at") or ""),
                "updated_at": str(data.get("updated_at") or data.get("registered_at") or ""),
            }
        )
        return {
            "schema_version": REGISTRATION_SCHEMA_VERSION,
            "revision": 1,
            "migrated_from": LEGACY_REGISTRATION_SCHEMA_VERSION,
            "retained_snapshots": [],
            "next_storage_sequence": 1,
            "registrations": {
                DEFAULT_SCHEDULE_ID: self._normalise_entry(
                    DEFAULT_SCHEDULE_ID, entry
                )
            },
        }

    @staticmethod
    def _normalise_entry(
        schedule_id: str,
        entry: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = deepcopy(dict(entry))
        snapshot_id = str(
            result.get("snapshot_id") or result.get("profile_id") or ""
        )
        result.update(
            {
                "schedule_id": schedule_id,
                "name": str(result.get("name") or DEFAULT_SCHEDULE_NAME),
                "enabled": bool(result.get("enabled", True)),
                "snapshot_id": snapshot_id,
                "snapshot_path": str(
                    result.get("snapshot_path") or result.get("profile_path") or ""
                ),
                "snapshot_fingerprint": str(
                    result.get("snapshot_fingerprint")
                    or result.get("profile_fingerprint")
                    or ""
                ),
                "condition_fingerprint": str(
                    result.get("condition_fingerprint") or ""
                ),
                "storage_key": str(result.get("storage_key") or ""),
                "storage_folder": str(result.get("storage_folder") or ""),
                "created_at": str(
                    result.get("created_at") or result.get("registered_at") or ""
                ),
                "updated_at": str(
                    result.get("updated_at")
                    or result.get("registered_at")
                    or result.get("created_at")
                    or ""
                ),
            }
        )
        # v2永続形式では曖昧なv1キーを残さない。
        result.pop("profile_id", None)
        result.pop("profile_path", None)
        result.pop("profile_fingerprint", None)
        ScheduleRegistrationStore._validate_storage_identity(result)
        return result

    @staticmethod
    def _validate_storage_identity(entry: Mapping[str, Any]) -> None:
        key = str(entry.get("storage_key") or "")
        folder = str(entry.get("storage_folder") or "")
        if not key and not folder:
            return
        if not key or not folder or not STORAGE_KEY_PATTERN.fullmatch(key):
            raise ScheduleServiceError(
                "定期実行の固定保存情報が不正です",
                "REGISTRATION_METADATA_INVALID",
            )
        if (
            not folder.startswith(f"{key}_")
            or FileUtils.sanitize_filename(folder, max_length=200) != folder
        ):
            raise ScheduleServiceError(
                "定期実行の固定保存フォルダーが不正です",
                "REGISTRATION_METADATA_INVALID",
            )

    @staticmethod
    def _next_storage_sequence(
        document: Mapping[str, Any],
        registrations: Mapping[str, Any],
    ) -> int:
        try:
            sequence = int(document.get("next_storage_sequence", 1) or 1)
        except (TypeError, ValueError) as exc:
            raise ScheduleServiceError(
                "定期実行の固定保存キー採番情報が不正です",
                "REGISTRATION_METADATA_INVALID",
            ) from exc
        if sequence < 1:
            raise ScheduleServiceError(
                "定期実行の固定保存キー採番情報が不正です",
                "REGISTRATION_METADATA_INVALID",
            )
        for entry in registrations.values():
            if not isinstance(entry, Mapping):
                continue
            match = STORAGE_KEY_PATTERN.fullmatch(str(entry.get("storage_key") or ""))
            if match:
                sequence = max(sequence, int(match.group(1)) + 1)
        return sequence

    @staticmethod
    def _validate_unique_storage_keys(registrations: Mapping[str, Any]) -> None:
        seen: set[str] = set()
        for entry in registrations.values():
            if not isinstance(entry, Mapping):
                continue
            key = str(entry.get("storage_key") or "")
            if not key:
                continue
            if key in seen:
                raise ScheduleServiceError(
                    "定期実行の固定保存キーが重複しています",
                    "REGISTRATION_METADATA_INVALID",
                )
            seen.add(key)

    def _atomic_write(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                suffix=".tmp",
                prefix=".schedule-registration-",
                dir=self.path.parent,
                delete=False,
            ) as stream:
                json.dump(
                    document,
                    stream,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ScheduleServiceError(
                "定期実行の登録情報を保存できません",
                "REGISTRATION_METADATA_WRITE_FAILED",
            ) from exc


__all__ = [
    "DEFAULT_SCHEDULE_NAME",
    "LEGACY_REGISTRATION_SCHEMA_VERSION",
    "REGISTRATION_SCHEMA_VERSION",
    "ScheduleRegistrationStore",
    "make_storage_folder",
    "next_storage_key",
    "validate_schedule_id",
]
