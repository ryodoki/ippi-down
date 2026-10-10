# -*- coding: utf-8 -*-

"""配置フォルダーの移動を検出するための永続情報とパス操作。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import ScheduleServiceError


INSTALLATION_LOCATION_SCHEMA_VERSION = 1
INSTALLATION_LOCATION_FILENAME = "install-location.json"
INSTALLATION_RELOCATION_JOURNAL_SCHEMA_VERSION = 1
INSTALLATION_RELOCATION_JOURNAL_FILENAME = "installation-relocation-journal.json"


@dataclass(frozen=True)
class InstallationLocation:
    """最後に利用者が確認した配置場所。"""

    task_namespace_id: str
    app_root: Path
    updated_at: str = ""
    status: str = "active"
    moved_to: Optional[Path] = None


@dataclass(frozen=True)
class InstallationRelocationJournal:
    """配置移行を安全に再開するための最小限の永続記録。"""

    task_namespace_id: str
    old_root: Path
    current_root: Path
    started_at: str = ""


class InstallationLocationStore:
    """配置場所を、config配下へ原子的に保存する。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=False)

    def read(self) -> Optional[InstallationLocation]:
        if not self.path.exists():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleServiceError(
                "配置場所の管理情報が壊れています",
                "INSTALLATION_LOCATION_INVALID",
            ) from exc
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ScheduleServiceError(
                "未対応の配置場所管理情報です",
                "INSTALLATION_LOCATION_INVALID",
            )
        namespace = str(document.get("task_namespace_id") or "").strip()
        raw_root = str(document.get("app_root") or "").strip()
        root = Path(raw_root).expanduser()
        status = str(document.get("status") or "active").strip().casefold()
        raw_moved_to = str(document.get("moved_to") or "").strip()
        moved_to = Path(raw_moved_to).expanduser() if raw_moved_to else None
        if (
            not namespace
            or not raw_root
            or not root.is_absolute()
            or status not in {"active", "retired"}
            or (status == "retired" and (moved_to is None or not moved_to.is_absolute()))
        ):
            raise ScheduleServiceError(
                "配置場所の管理情報に必要な値がありません",
                "INSTALLATION_LOCATION_INVALID",
            )
        return InstallationLocation(
            task_namespace_id=namespace,
            app_root=root.resolve(strict=False),
            updated_at=str(document.get("updated_at") or ""),
            status=status,
            moved_to=(moved_to.resolve(strict=False) if moved_to else None),
        )

    def write(self, task_namespace_id: str, app_root: str | Path) -> None:
        namespace = str(task_namespace_id or "").strip()
        root = Path(app_root).expanduser().resolve(strict=False)
        if not namespace or not root.is_absolute():
            raise ScheduleServiceError(
                "配置場所の管理情報を保存できません",
                "INSTALLATION_LOCATION_INVALID",
            )
        payload = {
            "schema_version": INSTALLATION_LOCATION_SCHEMA_VERSION,
            "task_namespace_id": namespace,
            "app_root": str(root),
            "status": "active",
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        self._atomic_write(payload)

    def write_retired(
        self,
        task_namespace_id: str,
        app_root: str | Path,
        moved_to: str | Path,
    ) -> None:
        """本版が旧配置で起動された場合に停止できる廃止情報を保存する。"""

        namespace = str(task_namespace_id or "").strip()
        root = Path(app_root).expanduser().resolve(strict=False)
        target = Path(moved_to).expanduser().resolve(strict=False)
        if not namespace or not root.is_absolute() or not target.is_absolute():
            raise ScheduleServiceError(
                "旧配置の廃止情報を保存できません",
                "INSTALLATION_LOCATION_INVALID",
            )
        self._atomic_write(
            {
                "schema_version": INSTALLATION_LOCATION_SCHEMA_VERSION,
                "task_namespace_id": namespace,
                "app_root": str(root),
                "status": "retired",
                "moved_to": str(target),
                "updated_at": datetime.now().astimezone().isoformat(),
            }
        )

    def _atomic_write(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                suffix=".tmp",
                prefix=".install-location-",
                dir=self.path.parent,
                delete=False,
            ) as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise ScheduleServiceError(
                f"配置場所の管理情報を保存できません: {exc}",
                "INSTALLATION_LOCATION_WRITE_FAILED",
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass


class InstallationRelocationJournalStore:
    """配置移行の開始からcommitまで残す原子的な回復記録。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=False)

    def read(self) -> Optional[InstallationRelocationJournal]:
        if not self.path.exists():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScheduleServiceError(
                "配置移行の回復記録が壊れています",
                "INSTALLATION_RELOCATION_JOURNAL_INVALID",
            ) from exc
        if not isinstance(document, dict) or set(document) != {
            "schema_version",
            "task_namespace_id",
            "old_root",
            "current_root",
            "started_at",
        }:
            raise ScheduleServiceError(
                "配置移行の回復記録の形式が不正です",
                "INSTALLATION_RELOCATION_JOURNAL_INVALID",
            )
        namespace = str(document.get("task_namespace_id") or "").strip()
        old_root = Path(str(document.get("old_root") or "")).expanduser()
        current_root = Path(str(document.get("current_root") or "")).expanduser()
        if (
            document.get("schema_version")
            != INSTALLATION_RELOCATION_JOURNAL_SCHEMA_VERSION
            or not namespace
            or not old_root.is_absolute()
            or not current_root.is_absolute()
            or paths_equal(old_root, current_root)
        ):
            raise ScheduleServiceError(
                "配置移行の回復記録の値が不正です",
                "INSTALLATION_RELOCATION_JOURNAL_INVALID",
            )
        return InstallationRelocationJournal(
            task_namespace_id=namespace,
            old_root=old_root.resolve(strict=False),
            current_root=current_root.resolve(strict=False),
            started_at=str(document.get("started_at") or ""),
        )

    def write(
        self,
        task_namespace_id: str,
        old_root: str | Path,
        current_root: str | Path,
    ) -> None:
        namespace = str(task_namespace_id or "").strip()
        source = Path(old_root).expanduser().resolve(strict=False)
        target = Path(current_root).expanduser().resolve(strict=False)
        if not namespace or not source.is_absolute() or paths_equal(source, target):
            raise ScheduleServiceError(
                "配置移行の回復記録を保存できません",
                "INSTALLATION_RELOCATION_JOURNAL_INVALID",
            )
        payload = {
            "schema_version": INSTALLATION_RELOCATION_JOURNAL_SCHEMA_VERSION,
            "task_namespace_id": namespace,
            "old_root": str(source),
            "current_root": str(target),
            "started_at": datetime.now().astimezone().isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                suffix=".tmp",
                prefix=".installation-relocation-journal-",
                dir=self.path.parent,
                delete=False,
            ) as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise ScheduleServiceError(
                "配置移行の回復記録を保存できません",
                "INSTALLATION_RELOCATION_JOURNAL_WRITE_FAILED",
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise ScheduleServiceError(
                "配置移行の回復記録を削除できません",
                "INSTALLATION_RELOCATION_JOURNAL_CLEANUP_FAILED",
            ) from exc


def normalise_path(value: str | Path) -> Path:
    """存在の有無に依存せず、比較用の絶対パスへ正規化する。"""

    return Path(value).expanduser().resolve(strict=False)


def paths_equal(left: str | Path, right: str | Path) -> bool:
    """Windowsの大文字小文字差を含め、OSの規則でパスを比較する。"""

    return os.path.normcase(str(normalise_path(left))) == os.path.normcase(
        str(normalise_path(right))
    )


def relative_path_within(value: str | Path, root: str | Path) -> Optional[Path]:
    """絶対パスがroot内なら相対部分を返す。文字列前方一致は使わない。"""

    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        return None
    resolved = candidate.resolve(strict=False)
    resolved_root = normalise_path(root)
    try:
        common = Path(os.path.commonpath((str(resolved), str(resolved_root))))
    except ValueError:
        return None
    if not paths_equal(common, resolved_root):
        return None
    relative = Path(os.path.relpath(str(resolved), str(resolved_root)))
    if str(relative) in {"", "."}:
        return Path()
    return relative


def rebase_internal_path(
    value: str | Path,
    old_root: str | Path,
    new_root: str | Path,
) -> Optional[str]:
    """旧配置内の絶対パスだけを、新配置基準の可搬相対パスへ変換する。"""

    relative = relative_path_within(value, old_root)
    if relative is None:
        return None
    # new_rootでも同じ相対位置が配置内に収まることを二重に確認する。
    target = normalise_path(new_root) / relative
    if relative_path_within(target, new_root) is None:
        return None
    suffix = str(relative).replace("/", "\\")
    return "." if not suffix or suffix == "." else f".\\{suffix}"
