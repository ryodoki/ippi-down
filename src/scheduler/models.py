# -*- coding: utf-8 -*-

"""Windowsタスクスケジューラ連携で共有する値オブジェクト。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


DEFAULT_SCHEDULE_ID = "default"


class ScheduleState(str, Enum):
    """GUI表示へ直接対応できる登録状態。"""

    DISABLED = "disabled"
    REGISTERED = "registered"
    UPDATE_REQUIRED = "update_required"
    REPAIR_REQUIRED = "repair_required"
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAITING = "retry_waiting"
    LAST_FAILED = "last_failed"
    EXTERNAL = "external"

    @property
    def display_name(self) -> str:
        return {
            self.DISABLED: "無効",
            self.REGISTERED: "登録済み",
            self.UPDATE_REQUIRED: "要更新",
            self.REPAIR_REQUIRED: "要修復",
            self.QUEUED: "待機中",
            self.RUNNING: "実行中",
            self.RETRY_WAITING: "再試行待機中",
            self.LAST_FAILED: "前回失敗",
            self.EXTERNAL: "別配置のタスク",
        }[self]


class ScheduleOrigin(str, Enum):
    """定期実行行を現在の登録台帳が管理しているかを表す。"""

    MANAGED = "managed"
    LEGACY_CANDIDATE = "legacy_candidate"
    EXTERNAL = "external"
    EXTERNAL_TASK = "external"  # 初期GUI実装向け互換alias


@dataclass(frozen=True)
class ScheduleCapabilities:
    """GUIが理由コードを推測せず操作可否を決めるための能力集合。"""

    can_edit: bool = False
    can_repair: bool = False
    can_run: bool = False
    can_delete: bool = False
    can_import: bool = False
    can_remove_external: bool = False

    @classmethod
    def managed(cls, *, repair: bool = False, runnable: bool = False) -> "ScheduleCapabilities":
        return cls(
            can_edit=True,
            can_repair=repair,
            can_run=runnable,
            can_delete=True,
        )

    @classmethod
    def external(cls, *, importable: bool, removable: bool) -> "ScheduleCapabilities":
        return cls(
            can_import=importable,
            can_remove_external=removable,
        )


@dataclass(frozen=True)
class ExternalScheduleImportCandidate:
    """別配置のWindowsタスクから安全に公開できる移行候補情報。"""

    external_id: str
    source_schedule_id: str
    task_name: str
    importable: bool
    reason_code: str
    reason: str
    display_name: str = ""
    snapshot_id: str = ""
    source_config_path: Optional[Path] = None
    source_config_dir: Optional[Path] = None
    source_profile_path: Optional[Path] = None
    source_revision: int = 0
    enabled: bool = False
    schedule: Any = None
    effective_save_path: Optional[Path] = None
    storage_key: str = ""
    storage_folder: str = ""
    requires_target_name: bool = False
    running: bool = False
    origin: ScheduleOrigin = ScheduleOrigin.LEGACY_CANDIDATE


@dataclass(frozen=True)
class ScheduleImportPlan:
    """利用者が承認する旧設定1件の移行内容。"""

    candidate: ExternalScheduleImportCandidate
    target_schedule_id: str
    target_name: str
    target_enabled: bool
    effective_save_path: Optional[Path]


@dataclass(frozen=True)
class ScheduleMigrationResult:
    """ownership移行の完了状態と、後処理警告を分離した結果。"""

    candidate: ExternalScheduleImportCandidate
    target_schedule_id: str
    target_name: str
    status: "ScheduleRegistrationStatus"
    success: bool = True
    warnings: tuple[str, ...] = ()
    reason_code: str = "EXTERNAL_IMPORT_SUCCESS"
    rollback_performed: bool = False
    history_imported: int = 0


@dataclass(frozen=True)
class InstallationRelocationPreview:
    """配置変更で更新される値を、書込み前に確定した結果。"""

    required: bool
    current_root: Path
    old_root: Optional[Path] = None
    affected_schedule_ids: tuple[str, ...] = ()
    config_changes: tuple[tuple[str, str, str], ...] = ()
    schedule_changes: tuple[tuple[str, str, str, str], ...] = ()
    reason_code: str = "INSTALLATION_CURRENT"
    message: str = ""
    blocked_reason: str = ""


@dataclass(frozen=True)
class InstallationRelocationResult:
    """確認済み配置移行の完了状態。"""

    success: bool
    preview: InstallationRelocationPreview
    migrated_schedule_ids: tuple[str, ...] = ()
    reason_code: str = "INSTALLATION_RELOCATION_SUCCESS"
    message: str = ""
    config: Any = None


@dataclass(frozen=True)
class ScheduledProfile:
    """タスクが参照する不変の設定スナップショット。"""

    profile_id: str
    path: Path
    fingerprint: str
    created_at: datetime
    schedule_id: str = DEFAULT_SCHEDULE_ID
    display_name: str = ""

    @property
    def snapshot_id(self) -> str:
        """不変スナップショットID。``profile_id``はv1互換名。"""

        return self.profile_id


@dataclass(frozen=True)
class ScheduleRegistration:
    """1つの論理スケジュールと、その有効なスナップショット。"""

    schedule_id: str
    name: str
    enabled: bool
    task_name: str
    snapshot_id: str
    snapshot_path: Path
    snapshot_fingerprint: str
    registered_at: Optional[datetime]
    schedule: Any
    command: Path
    arguments: tuple[str, ...] = ()
    working_directory: Optional[Path] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    condition_fingerprint: str = ""
    storage_key: str = ""
    storage_folder: str = ""

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def profile_id(self) -> str:
        """v1コード向けの互換alias。"""

        return self.snapshot_id

    @property
    def profile_path(self) -> Path:
        return self.snapshot_path

    @property
    def profile_fingerprint(self) -> str:
        return self.snapshot_fingerprint


# 公開仕様上は論理スケジュール定義。既存実装名も互換維持する。
ScheduleDefinition = ScheduleRegistration


@dataclass(frozen=True)
class ScheduleRegistry:
    """あるrevision時点の登録一覧。"""

    revision: int
    registrations: dict[str, ScheduleRegistration]


@dataclass(frozen=True)
class ScheduleRegistrySnapshot:
    """1件の更新を競合検出付きで復元するための退避情報。"""

    revision: int
    schedule_id: str
    registration: Optional[ScheduleRegistration]
    metadata: Optional[dict[str, Any]] = None
    task: Any = None


@dataclass
class ScheduledRunRecord:
    """1回の定期実行の診断情報。

    検索条件やCookieなどを持たせないことで、履歴ファイルを安全に保つ。
    """

    profile_id: str = ""
    schedule_id: str = DEFAULT_SCHEDULE_ID
    snapshot_id: Optional[str] = None
    run_id: str = ""
    trigger_kind: str = "scheduled"
    queue_wait_seconds: float = 0.0
    display_name: str = ""
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: str = "unknown"
    new_count: int = 0
    saved_count: int = 0
    existing_count: int = 0
    failed_count: int = 0
    retry_count: int = 0
    reason_code: str = ""
    exit_code: int = 0

    def __post_init__(self) -> None:
        if self.snapshot_id and self.profile_id and self.snapshot_id != self.profile_id:
            raise ValueError("snapshot_idとprofile_idが一致しません")
        identifier = self.snapshot_id or self.profile_id
        self.profile_id = identifier
        self.snapshot_id = identifier

    @property
    def checked_count(self) -> int:
        return self.saved_count + self.existing_count + self.failed_count

    @property
    def ended_at(self) -> Optional[datetime]:
        """旧GUI実装で使われる名称との互換alias。"""
        return self.finished_at

    def to_dict(self) -> dict[str, Any]:
        def iso(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() if value else None

        return {
            "schedule_id": self.schedule_id,
            "snapshot_id": self.snapshot_id,
            "profile_id": self.profile_id,
            "run_id": self.run_id,
            "trigger_kind": self.trigger_kind,
            "queue_wait_seconds": float(self.queue_wait_seconds),
            "display_name": self.display_name,
            "scheduled_at": iso(self.scheduled_at),
            "started_at": iso(self.started_at),
            "finished_at": iso(self.finished_at),
            "result": self.result,
            "new_count": int(self.new_count),
            "saved_count": int(self.saved_count),
            "existing_count": int(self.existing_count),
            "failed_count": int(self.failed_count),
            "retry_count": int(self.retry_count),
            "reason_code": self.reason_code,
            "exit_code": int(self.exit_code),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduledRunRecord":
        def parse(value: Any) -> Optional[datetime]:
            if not value:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value))

        return cls(
            profile_id=str(data.get("snapshot_id") or data.get("profile_id", "")),
            schedule_id=str(data.get("schedule_id") or DEFAULT_SCHEDULE_ID),
            snapshot_id=str(data.get("snapshot_id") or data.get("profile_id", "")),
            run_id=str(data.get("run_id") or ""),
            trigger_kind=str(data.get("trigger_kind") or "scheduled"),
            queue_wait_seconds=float(data.get("queue_wait_seconds", 0.0) or 0.0),
            display_name=str(data.get("display_name") or ""),
            scheduled_at=parse(data.get("scheduled_at")),
            started_at=parse(data.get("started_at")),
            finished_at=parse(data.get("finished_at") or data.get("ended_at")),
            result=str(data.get("result", "unknown")),
            new_count=int(data.get("new_count", 0) or 0),
            saved_count=int(data.get("saved_count", 0) or 0),
            existing_count=int(data.get("existing_count", 0) or 0),
            failed_count=int(data.get("failed_count", 0) or 0),
            retry_count=int(data.get("retry_count", 0) or 0),
            reason_code=str(data.get("reason_code", "")),
            exit_code=int(data.get("exit_code", 0) or 0),
        )


@dataclass
class ScheduleRegistrationStatus:
    """Windowsタスク、実行ファイル、スナップショットをまとめた状態。"""

    state: ScheduleState = ScheduleState.DISABLED
    registered: bool = False
    running: bool = False
    retry_waiting: bool = False
    next_run: Optional[datetime] = None
    last_run: Optional[datetime] = None
    last_result: Optional[str] = None
    definition_mismatch: bool = False
    repair_reason: Optional[str] = None
    reason_code: Optional[str] = None
    task_name: str = ""
    profile_id: Optional[str] = None
    profile_fingerprint: Optional[str] = None
    new_count: int = 0
    saved_count: int = 0
    existing_count: int = 0
    failed_count: int = 0
    task_exit_code: Optional[int] = None
    schedule_id: str = DEFAULT_SCHEDULE_ID
    name: str = "既存の定期実行"
    enabled: bool = False
    snapshot_id: Optional[str] = None
    condition_fingerprint: Optional[str] = None
    condition_duplicate_schedule_ids: tuple[str, ...] = ()
    storage_key: str = ""
    storage_folder: str = ""
    queued: bool = False
    queue_waiting: bool = False
    queue_position: Optional[int] = None
    queue_total: int = 0
    origin: ScheduleOrigin = ScheduleOrigin.MANAGED
    capabilities: Optional[ScheduleCapabilities] = None
    source_schedule_id: str = ""
    external_id: str = ""

    def __post_init__(self) -> None:
        if self.snapshot_id and self.profile_id and self.snapshot_id != self.profile_id:
            raise ValueError("snapshot_idとprofile_idが一致しません")
        identifier = self.snapshot_id or self.profile_id
        self.profile_id = identifier
        self.snapshot_id = identifier
        if self.capabilities is None:
            if self.origin is ScheduleOrigin.EXTERNAL_TASK:
                self.capabilities = ScheduleCapabilities.external(
                    importable=False,
                    removable=not self.running,
                )
            else:
                self.capabilities = ScheduleCapabilities.managed(
                    repair=self.state is ScheduleState.REPAIR_REQUIRED,
                    runnable=(
                        self.registered
                        and not self.running
                        and self.state
                        not in {ScheduleState.REPAIR_REQUIRED, ScheduleState.EXTERNAL}
                    ),
                )

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def status(self) -> ScheduleState:
        """``state`` の互換alias。"""
        return self.state

    @property
    def next_run_at(self) -> Optional[datetime]:
        return self.next_run

    @property
    def last_run_at(self) -> Optional[datetime]:
        return self.last_run

    @property
    def display_state_name(self) -> str:
        return self.state.display_name

    @property
    def status_display_name(self) -> str:
        return self.state.display_name


class ScheduleServiceError(RuntimeError):
    """登録操作を継続できないときの、理由コード付き例外。"""

    def __init__(self, message: str, reason_code: str = "SCHEDULE_ERROR") -> None:
        super().__init__(message)
        self.reason_code = reason_code
