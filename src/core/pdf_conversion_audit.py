# -*- coding: utf-8 -*-

"""PDF変換の追跡ログと、再処理用の無害化済み障害資料。"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional

from ..utils.log_sanitizer import sanitize_log_text
from ..utils.path_utils import get_logs_path


_CONVERSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_AUDIT_FILE_RE = re.compile(r"^pdf-conversions-(\d{4}-\d{2}-\d{2})(?:-\d+)?\.jsonl$")


def new_conversion_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class PdfConversionContext:
    """ログ相関に使う、秘密情報を含まない変換単位の文脈。"""

    run_id: str = ""
    conversion_id: str = field(default_factory=new_conversion_id)
    project_name: str = ""
    document_name: str = ""
    document_id: str = ""


class PdfConversionAudit:
    """日別JSONLを追記し、保存期限を安全に適用する。"""

    schema_version = 1
    _lock = threading.RLock()

    def __init__(
        self,
        logs_dir: Optional[Path] = None,
        *,
        log_retention_days: int = 90,
        artifact_retention_days: int = 30,
        max_file_bytes: int = 10 * 1024 * 1024,
        clock=time.time,
    ) -> None:
        self.logs_dir = (
            Path(logs_dir) if logs_dir is not None else Path(get_logs_path()).parent
        )
        self.log_retention_days = max(1, int(log_retention_days))
        self.artifact_retention_days = max(1, int(artifact_retention_days))
        self.max_file_bytes = max(1024, int(max_file_bytes))
        self._clock = clock

    def record(
        self,
        context: PdfConversionContext,
        event: str,
        **values: object,
    ) -> None:
        now = datetime.fromtimestamp(self._clock(), timezone.utc)
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "timestamp_utc": now.isoformat(timespec="milliseconds"),
            "run_id": self._safe(context.run_id, 128),
            "conversion_id": self._safe(context.conversion_id, 64),
            "project_name": self._safe(context.project_name, 500),
            "document_name": self._safe(context.document_name, 300),
            "document_id": self._safe(context.document_id, 200),
            "event": self._safe(event, 100),
        }
        for key, value in values.items():
            if value is None:
                payload[key] = None
            elif isinstance(value, (bool, int, float)):
                payload[key] = value
            else:
                payload[key] = self._safe(value, 4096)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        try:
            with self._lock:
                self.logs_dir.mkdir(parents=True, exist_ok=True)
                path = self._current_path(now)
                with path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(line)
                    stream.flush()
        except OSError:
            # 診断ログ障害でダウンロード結果を変更しない。
            return

    def store_failure(
        self,
        context: PdfConversionContext,
        sanitized_html: str,
        manifest: Mapping[str, object],
        *,
        stderr_tail: str = "",
    ) -> Optional[Path]:
        conversion_id = context.conversion_id.casefold()
        if not _CONVERSION_ID_RE.fullmatch(conversion_id):
            return None
        root = self.logs_dir / "pdf-failures"
        final_path = root / conversion_id
        staging = root / f".{conversion_id}.{uuid.uuid4().hex}.tmp"
        now = datetime.fromtimestamp(self._clock(), timezone.utc)
        expires = now + timedelta(days=self.artifact_retention_days)
        safe_manifest = {
            "schema_version": 1,
            "conversion_id": conversion_id,
            "run_id": self._safe(context.run_id, 128),
            "project_name": self._safe(context.project_name, 500),
            "document_name": self._safe(context.document_name, 300),
            "document_id": self._safe(context.document_id, 200),
            "created_at_utc": now.isoformat(timespec="seconds"),
            "expires_at_utc": expires.isoformat(timespec="seconds"),
        }
        for key, value in manifest.items():
            if isinstance(value, (bool, int, float)) or value is None:
                safe_manifest[str(key)] = value
            else:
                safe_manifest[str(key)] = self._safe(value, 4096)
        try:
            with self._lock:
                root.mkdir(parents=True, exist_ok=True)
                if final_path.exists():
                    return final_path if final_path.is_dir() else None
                staging.mkdir()
                (staging / "input.sanitized.html").write_text(
                    sanitized_html,
                    encoding="utf-8",
                    newline="\n",
                )
                (staging / "manifest.json").write_text(
                    json.dumps(
                        safe_manifest, ensure_ascii=False, sort_keys=True, indent=2
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
                (staging / "stderr-tail.txt").write_text(
                    self._safe(stderr_tail, 4096),
                    encoding="utf-8",
                    newline="\n",
                )
                (staging / "events.jsonl").write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "timestamp_utc": now.isoformat(timespec="milliseconds"),
                            "conversion_id": conversion_id,
                            "event": "RECOVERY_ARTIFACT_STORED",
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                os.replace(staging, final_path)
                return final_path
        except OSError:
            try:
                if staging.is_dir() and not staging.is_symlink():
                    shutil.rmtree(staging)
            except OSError:
                pass
            return None

    def purge_expired(self) -> tuple[int, int]:
        """管理対象だけを削除し、(ログ数, 障害資料数)を返す。"""

        now = datetime.fromtimestamp(self._clock(), timezone.utc)
        log_cutoff = (now - timedelta(days=self.log_retention_days)).date()
        logs_removed = 0
        artifacts_removed = 0
        try:
            candidates = tuple(self.logs_dir.iterdir())
        except OSError:
            candidates = ()
        for path in candidates:
            match = _AUDIT_FILE_RE.fullmatch(path.name)
            if not match or not path.is_file() or path.is_symlink():
                continue
            try:
                if datetime.strptime(match.group(1), "%Y-%m-%d").date() < log_cutoff:
                    path.unlink()
                    logs_removed += 1
            except (OSError, ValueError):
                continue

        failure_root = self.logs_dir / "pdf-failures"
        try:
            artifact_paths = tuple(failure_root.iterdir())
        except OSError:
            artifact_paths = ()
        for path in artifact_paths:
            if (
                not _CONVERSION_ID_RE.fullmatch(path.name)
                or not path.is_dir()
                or path.is_symlink()
            ):
                continue
            manifest_path = path / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                expires = datetime.fromisoformat(str(manifest["expires_at_utc"]))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= now:
                    shutil.rmtree(path)
                    artifacts_removed += 1
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return logs_removed, artifacts_removed

    def _current_path(self, now: datetime) -> Path:
        stem = f"pdf-conversions-{now:%Y-%m-%d}"
        path = self.logs_dir / f"{stem}.jsonl"
        try:
            if not path.exists() or path.stat().st_size < self.max_file_bytes:
                return path
        except OSError:
            return path
        for index in range(1, 1000):
            candidate = self.logs_dir / f"{stem}-{index}.jsonl"
            try:
                if (
                    not candidate.exists()
                    or candidate.stat().st_size < self.max_file_bytes
                ):
                    return candidate
            except OSError:
                return candidate
        return self.logs_dir / f"{stem}-999.jsonl"

    @staticmethod
    def _safe(value: object, maximum: int) -> str:
        return sanitize_log_text(value).replace("\x00", "")[:maximum]
