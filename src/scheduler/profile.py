# -*- coding: utf-8 -*-

"""定期実行用の不変な設定スナップショット。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import yaml

from ..models.config_model import AppConfig, ScheduleNotificationPolicy
from .models import ScheduleServiceError, ScheduledProfile


PROFILE_SCHEMA_VERSION = 4
PROFILE_SCHEMA_VERSION_V3 = 3
PREVIOUS_PROFILE_SCHEMA_VERSION = 2
LEGACY_PROFILE_SCHEMA_VERSION = 1
PROFILE_METADATA_KEY = "_schedule_profile"
_PROFILE_TEMP_PREFIX = ".ippi-profile-"
_PROFILE_TEMP_STALE_SECONDS = 24 * 60 * 60


def _condition_payload(
    config: AppConfig | Mapping[str, Any],
    *,
    schema_version: int = PROFILE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """検索・保存条件だけを安定した辞書にする。"""

    raw: Mapping[str, Any]
    if isinstance(config, AppConfig):
        raw = asdict(config)
    else:
        raw = config
    save_paths = raw.get("save_paths", {})
    if isinstance(save_paths, Mapping):
        save_paths = dict(save_paths)
        # 固定保存IDはスケジュールごとに必ず異なる管理値であり、検索・取得
        # 条件の重複判定には含めない。profile本体のfingerprintには含まれる。
        save_paths.pop("schedule_storage_key", None)
        save_paths.pop("schedule_storage_folder", None)
    search_conditions = raw.get("search_conditions", {})
    if isinstance(search_conditions, Mapping):
        search_conditions = dict(search_conditions)
        if schema_version < PROFILE_SCHEMA_VERSION:
            # v1～v3の署名は、新設した業務対応フィールドを含まない。
            # raw mappingの署名を検証してからConfigManagerが既定値を補う。
            for key in ("search_target", "project_name", "gyomu_kubun"):
                search_conditions.pop(key, None)
    return {
        "target_urls": raw.get("target_urls", []),
        "download_conditions": raw.get("download_conditions", {}),
        "search_conditions": search_conditions,
        "save_paths": save_paths,
        "naming_rule": raw.get("naming_rule", ""),
    }


def _profile_payload(
    config: AppConfig | Mapping[str, Any],
    *,
    schema_version: int = PROFILE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """スナップショットの全実行条件を安定した辞書にする。

    v3以降では通知方針も実行条件として封印する。v1/v2の検証時は
    旧projectionを使い、後方互換性を保つ。
    """

    raw: Mapping[str, Any]
    if isinstance(config, AppConfig):
        raw = asdict(config)
    else:
        raw = config
    schedule = raw.get("schedule", {})
    if not isinstance(schedule, Mapping):
        schedule = {}
    payload = _condition_payload(raw, schema_version=schema_version)
    # condition fingerprintでは固定保存IDを除外するが、不変snapshot本体の
    # fingerprintではsave_pathsを全項目封印し、保存先の改変を検知する。
    payload["save_paths"] = raw.get("save_paths", {})
    payload["schedule"] = {
        "backend": schedule.get("backend", "windows_task_scheduler"),
        "timezone": schedule.get("timezone", "Asia/Tokyo"),
        "interval": schedule.get("interval", "daily"),
        "time": schedule.get("time", "09:00"),
        "weekday": schedule.get("weekday", "monday"),
        "day_of_month": schedule.get("day_of_month", 1),
        "start_when_available": schedule.get("start_when_available", True),
        "wake_to_run": schedule.get("wake_to_run", False),
        "retry_count": schedule.get("retry_count", 2),
        "retry_interval_minutes": schedule.get("retry_interval_minutes", 15),
    }
    if schema_version >= PROFILE_SCHEMA_VERSION_V3:
        notification_policy = schedule.get(
            "notification_policy",
            ScheduleNotificationPolicy.OFF.value,
        )
        if isinstance(notification_policy, ScheduleNotificationPolicy):
            notification_policy = notification_policy.value
        payload["schedule"]["notification_policy"] = str(notification_policy)
    return payload


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calculate_profile_fingerprint(
    config: AppConfig | Mapping[str, Any],
    *,
    schema_version: int = PROFILE_SCHEMA_VERSION,
) -> str:
    """実行条件全体のSHA-256フィンガープリントを返す。"""

    return _fingerprint(_profile_payload(config, schema_version=schema_version))


def calculate_condition_fingerprint(
    config: AppConfig | Mapping[str, Any],
) -> str:
    """GUIの検索条件未反映警告に使う、schedule非依存fingerprint。"""

    return _fingerprint(_condition_payload(config))


def _profile_integrity_fingerprint(
    *,
    snapshot_id: str,
    schedule_id: str,
    display_name: str,
    condition_fingerprint: str,
    profile_fingerprint: str,
) -> str:
    """設定本体では検知できない所有者情報を含めて封印する。"""

    return _fingerprint(
        {
            "snapshot_id": snapshot_id,
            "schedule_id": schedule_id,
            "display_name": display_name,
            "condition_fingerprint": condition_fingerprint,
            "profile_fingerprint": profile_fingerprint,
        }
    )


# 呼び出し側で自然に読める名称も公開する。
profile_fingerprint = calculate_profile_fingerprint


class ScheduleProfileStore:
    """スナップショットを同一ボリューム上で原子的に保存する。"""

    def __init__(self, root: str | Path, *, recover_stale: bool = True) -> None:
        self.root = Path(root).resolve(strict=False)
        # 前回の強制終了で残った、このStore自身が作成した一時ファイルだけ
        # を安全に回収する。他用途の.tmpや所有者不明のファイルには触れない。
        if recover_stale:
            self.recover_stale_temporary_files()

    def recover_stale_temporary_files(
        self,
        *,
        stale_after_seconds: float = _PROFILE_TEMP_STALE_SECONDS,
        now: Optional[float] = None,
        process_alive: Optional[Callable[[int], bool]] = None,
    ) -> tuple[Path, ...]:
        """未使用かつ期限切れのprofile原子的書込み一時ファイルを回収する。

        一時名に作成PIDとUNIX時刻を含めるため、mtimeだけに頼らない。
        PIDの状態を取得できない場合は使用中として残す安全側の動作にする。
        """

        if not self.root.exists():
            return ()
        current = float(now) if now is not None else datetime.now().timestamp()
        is_alive = process_alive or _profile_process_alive
        removed: list[Path] = []
        try:
            paths = tuple(self.root.glob(f"{_PROFILE_TEMP_PREFIX}*.tmp"))
        except OSError:
            return ()
        for path in paths:
            metadata = _parse_profile_temp_name(path.name)
            if metadata is None:
                continue
            owner_pid, created_at = metadata
            if current - created_at < max(0.0, float(stale_after_seconds)):
                continue
            try:
                if is_alive(owner_pid):
                    continue
            except OSError:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            removed.append(path)
        return tuple(removed)

    def path_for(self, profile_id: str) -> Path:
        safe_id = self._validate_profile_id(profile_id)
        return self.root / f"{safe_id}.yaml"

    def create(
        self,
        config: AppConfig,
        profile_id: Optional[str] = None,
        *,
        snapshot_id: Optional[str] = None,
        schedule_id: str = "default",
        display_name: str = "",
        created_at: Optional[datetime] = None,
    ) -> ScheduledProfile:
        """新しい一意なスナップショットを作る。

        既存ファイルは上書きしない。タスク更新に失敗した場合、呼び出し側は
        ``delete`` でこの新規ファイルだけを安全に破棄できる。
        """

        if profile_id and snapshot_id and profile_id != snapshot_id:
            raise ScheduleServiceError(
                "profile_idとsnapshot_idが一致しません",
                "PROFILE_ID_INVALID",
            )
        identifier = self._validate_profile_id(
            snapshot_id or profile_id or uuid.uuid4().hex
        )
        owner_id = self._validate_profile_id(schedule_id)
        path = self.path_for(identifier)
        if path.exists():
            raise ScheduleServiceError(
                f"同じプロファイルIDが既に存在します: {identifier}",
                "PROFILE_ALREADY_EXISTS",
            )

        timestamp = created_at or datetime.now().astimezone()
        fingerprint = calculate_profile_fingerprint(config)
        condition_fingerprint = calculate_condition_fingerprint(config)
        resolved_display_name = str(display_name or "")
        document = asdict(config)
        document[PROFILE_METADATA_KEY] = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "snapshot_id": identifier,
            # v1 runtimeとのローリング更新中も実行できるよう互換名を残す。
            "profile_id": identifier,
            "schedule_id": owner_id,
            "display_name": resolved_display_name,
            "fingerprint": fingerprint,
            "condition_fingerprint": condition_fingerprint,
            "integrity_fingerprint": _profile_integrity_fingerprint(
                snapshot_id=identifier,
                schedule_id=owner_id,
                display_name=resolved_display_name,
                condition_fingerprint=condition_fingerprint,
                profile_fingerprint=fingerprint,
            ),
            "created_at": timestamp.isoformat(),
        }
        self._atomic_write_yaml(path, document)
        return ScheduledProfile(
            profile_id=identifier,
            path=path,
            fingerprint=fingerprint,
            created_at=timestamp,
            schedule_id=owner_id,
            display_name=resolved_display_name,
        )

    def read(self, profile_or_path: str | Path) -> dict[str, Any]:
        """スナップショット全体を読み、形式と改ざんを検証する。"""

        path = self._resolve_profile_or_path(profile_or_path)
        try:
            with path.open("r", encoding="utf-8") as stream:
                document = yaml.safe_load(stream)
        except OSError as exc:
            raise ScheduleServiceError(
                f"定期実行の検索条件を読み込めません: {path}",
                "PROFILE_NOT_FOUND",
            ) from exc
        except yaml.YAMLError as exc:
            raise ScheduleServiceError(
                f"定期実行の検索条件が壊れています: {path}",
                "PROFILE_INVALID",
            ) from exc

        if not isinstance(document, dict):
            raise ScheduleServiceError(
                f"定期実行の検索条件の形式が不正です: {path}",
                "PROFILE_INVALID",
            )
        metadata = document.get(PROFILE_METADATA_KEY)
        if not isinstance(metadata, dict):
            raise ScheduleServiceError(
                f"定期実行の検索条件に管理情報がありません: {path}",
                "PROFILE_INVALID",
            )
        if metadata.get("schema_version") not in {
            LEGACY_PROFILE_SCHEMA_VERSION,
            PREVIOUS_PROFILE_SCHEMA_VERSION,
            PROFILE_SCHEMA_VERSION_V3,
            PROFILE_SCHEMA_VERSION,
        }:
            raise ScheduleServiceError(
                "未対応の定期実行プロファイルです",
                "PROFILE_VERSION_UNSUPPORTED",
            )
        version = metadata.get("schema_version")
        if version in {
            PREVIOUS_PROFILE_SCHEMA_VERSION,
            PROFILE_SCHEMA_VERSION_V3,
            PROFILE_SCHEMA_VERSION,
        }:
            raw_snapshot_id = metadata.get("snapshot_id")
            raw_profile_id = metadata.get("profile_id")
            if raw_snapshot_id and raw_profile_id and str(raw_snapshot_id) != str(
                raw_profile_id
            ):
                raise ScheduleServiceError(
                    "定期実行プロファイルのIDが一致しません",
                    "PROFILE_ID_MISMATCH",
                )
            identifier = self._validate_profile_id(
                str(raw_snapshot_id or raw_profile_id or "")
            )
            if path.stem != identifier:
                raise ScheduleServiceError(
                    "定期実行プロファイルのファイル名とIDが一致しません",
                    "PROFILE_PATH_MISMATCH",
                )
            owner_id = self._validate_profile_id(
                str(metadata.get("schedule_id") or "")
            )
            actual_condition_fingerprint = calculate_condition_fingerprint(document)
            recorded_condition_fingerprint = str(
                metadata.get("condition_fingerprint") or ""
            )
            if (
                recorded_condition_fingerprint
                and recorded_condition_fingerprint
                != actual_condition_fingerprint
            ):
                raise ScheduleServiceError(
                    "定期実行の検索条件が登録後に変更されています",
                    "PROFILE_FINGERPRINT_MISMATCH",
                )
            recorded_integrity = str(metadata.get("integrity_fingerprint") or "")
            if recorded_integrity:
                expected_integrity = _profile_integrity_fingerprint(
                    snapshot_id=identifier,
                    schedule_id=owner_id,
                    display_name=str(metadata.get("display_name") or ""),
                    condition_fingerprint=(
                        recorded_condition_fingerprint
                        or actual_condition_fingerprint
                    ),
                    profile_fingerprint=str(metadata.get("fingerprint") or ""),
                )
                if recorded_integrity != expected_integrity:
                    raise ScheduleServiceError(
                        "定期実行プロファイルの管理情報が変更されています",
                        "PROFILE_INTEGRITY_MISMATCH",
                    )
        if version == LEGACY_PROFILE_SCHEMA_VERSION:
            actual_values = {
                calculate_condition_fingerprint(document),
                calculate_profile_fingerprint(
                    document,
                    schema_version=PREVIOUS_PROFILE_SCHEMA_VERSION,
                ),
                # ローリング更新中に現行helperで生成されたv1 fixtureも許容する。
                calculate_profile_fingerprint(document),
            }
        elif version == PREVIOUS_PROFILE_SCHEMA_VERSION:
            actual_values = {
                calculate_profile_fingerprint(
                    document,
                    schema_version=PREVIOUS_PROFILE_SCHEMA_VERSION,
                )
            }
        elif version == PROFILE_SCHEMA_VERSION_V3:
            actual_values = {
                calculate_profile_fingerprint(
                    document,
                    schema_version=PROFILE_SCHEMA_VERSION_V3,
                )
            }
        else:
            actual_values = {calculate_profile_fingerprint(document)}
        if metadata.get("fingerprint") not in actual_values:
            raise ScheduleServiceError(
                "定期実行の検索条件が登録後に変更されています",
                "PROFILE_FINGERPRINT_MISMATCH",
            )
        if version in {
            LEGACY_PROFILE_SCHEMA_VERSION,
            PREVIOUS_PROFILE_SCHEMA_VERSION,
        }:
            # 通知方針はv3からfingerprintで封印された。旧形式に
            # 未封印のキーが後付けされても実行せず、必ずOFFとする。
            schedule = document.get("schedule")
            if isinstance(schedule, dict):
                schedule["notification_policy"] = (
                    ScheduleNotificationPolicy.OFF.value
                )
        return document

    def get(self, profile_id: str) -> ScheduledProfile:
        path = self.path_for(profile_id)
        document = self.read(path)
        metadata = document[PROFILE_METADATA_KEY]
        try:
            created_at = datetime.fromisoformat(str(metadata["created_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ScheduleServiceError(
                "定期実行プロファイルの作成日時が不正です",
                "PROFILE_INVALID",
            ) from exc
        identifier = str(metadata.get("snapshot_id") or metadata.get("profile_id") or "")
        if not identifier:
            raise ScheduleServiceError(
                "定期実行プロファイルにスナップショットIDがありません",
                "PROFILE_INVALID",
            )
        return ScheduledProfile(
            profile_id=identifier,
            path=path,
            fingerprint=str(metadata["fingerprint"]),
            created_at=created_at,
            schedule_id=str(metadata.get("schedule_id") or "default"),
            display_name=str(metadata.get("display_name") or ""),
        )

    load = get

    def matches_config(
        self,
        profile: ScheduledProfile | str,
        config: AppConfig | Mapping[str, Any],
    ) -> bool:
        """保存時のschemaと同じprojectionで現在設定を比較する。"""

        profile_id = (
            profile.profile_id if isinstance(profile, ScheduledProfile) else profile
        )
        document = self.read(profile_id)
        metadata = document[PROFILE_METADATA_KEY]
        version = int(metadata.get("schema_version", 0) or 0)
        recorded = str(metadata.get("fingerprint") or "")
        if version == LEGACY_PROFILE_SCHEMA_VERSION:
            candidates = {
                calculate_condition_fingerprint(config),
                calculate_profile_fingerprint(
                    config,
                    schema_version=PREVIOUS_PROFILE_SCHEMA_VERSION,
                ),
                calculate_profile_fingerprint(config),
            }
        elif version == PREVIOUS_PROFILE_SCHEMA_VERSION:
            candidates = {
                calculate_profile_fingerprint(
                    config,
                    schema_version=PREVIOUS_PROFILE_SCHEMA_VERSION,
                )
            }
        elif version == PROFILE_SCHEMA_VERSION_V3:
            candidates = {
                calculate_profile_fingerprint(
                    config,
                    schema_version=PROFILE_SCHEMA_VERSION_V3,
                )
            }
        else:
            candidates = {calculate_profile_fingerprint(config)}
        return recorded in candidates

    def list(self, *, schedule_id: Optional[str] = None) -> list[ScheduledProfile]:
        """保存済みスナップショットを新しい順で返す。"""

        if schedule_id is not None:
            self._validate_profile_id(schedule_id)
        if not self.root.exists():
            return []
        profiles: list[ScheduledProfile] = []
        for path in self.root.glob("*.yaml"):
            try:
                profile = self.get(path.stem)
            except ScheduleServiceError:
                continue
            if schedule_id is None or profile.schedule_id == schedule_id:
                profiles.append(profile)
        return sorted(profiles, key=lambda item: item.created_at, reverse=True)

    def delete(self, profile: ScheduledProfile | str) -> None:
        profile_id = profile.profile_id if isinstance(profile, ScheduledProfile) else profile
        path = self.path_for(profile_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise ScheduleServiceError(
                f"新しいプロファイルを破棄できません: {path}",
                "PROFILE_DELETE_FAILED",
            ) from exc

    def _resolve_profile_or_path(self, value: str | Path) -> Path:
        candidate = Path(value)
        if candidate.suffix.lower() in {".yaml", ".yml"} or candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise ScheduleServiceError(
                    "プロファイル格納先の外側は読み込めません",
                    "PROFILE_PATH_INVALID",
                ) from exc
            return resolved
        return self.path_for(str(value))

    @staticmethod
    def _validate_profile_id(profile_id: str) -> str:
        value = str(profile_id)
        if not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in value):
            raise ScheduleServiceError(
                f"プロファイルIDが不正です: {value}",
                "PROFILE_ID_INVALID",
            )
        return value

    def _atomic_write_yaml(self, path: Path, document: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                suffix=".tmp",
                prefix=(
                    f"{_PROFILE_TEMP_PREFIX}{path.stem}-p{os.getpid()}-"
                    f"c{int(datetime.now().timestamp())}-"
                ),
                dir=self.root,
                delete=False,
            ) as stream:
                yaml.safe_dump(
                    document,
                    stream,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ScheduleServiceError(
                f"定期実行の検索条件を保存できません: {path}",
                "PROFILE_WRITE_FAILED",
            ) from exc


def _parse_profile_temp_name(filename: str) -> Optional[tuple[int, float]]:
    """このversionが作成したtmp名から所有PIDと作成時刻を得る。"""

    match = re.match(
        r"^\.ippi-profile-[A-Za-z0-9_-]+-p(\d+)-c(\d+)-.+\.tmp$",
        filename,
    )
    if match is None:
        return None
    try:
        return int(match.group(1)), float(match.group(2))
    except ValueError:
        return None


def _profile_process_alive(pid: int) -> bool:
    """PIDを安全側で照会する。照会不能なら削除しない。"""

    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True
