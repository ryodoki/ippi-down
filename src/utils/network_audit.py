# -*- coding: utf-8 -*-

"""外向きHTTP通信の安全な追記専用監査ログ。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Mapping, Optional
from urllib.parse import parse_qsl, urlsplit

from ..app.run_guard import RunGuard
from .path_utils import get_logs_path, resolve_verified_local_path


class NetworkAuditLedger:
    """query値やHTTP本文を残さず、通信ポリシー判定をJSONLへ記録する。

    監査ログは診断情報であり、保存失敗によってポリシー判定や本来の
    ダウンロードを失敗させてはならない。そのため、I/O例外と短時間の
    プロセス間競合は警告へ変換して呼出元へ返さない。
    """

    DEFAULT_MAX_BYTES = 5 * 1024 * 1024
    DEFAULT_BACKUP_COUNT = 5

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ) -> None:
        self.path = Path(path) if path is not None else get_logs_path(
            "network-audit.jsonl"
        )
        self.max_bytes = max(1024, int(max_bytes))
        self.backup_count = max(0, int(backup_count))
        self._lock = threading.RLock()
        self._process_guard = RunGuard(
            r"Local\ippi-down.NetworkAuditLedger"
        )

    def record(
        self,
        *,
        method: str,
        url: str,
        allowed: bool,
        endpoint_id: str = "",
        purpose: object = "",
        reason_code: object = "",
        is_redirect: bool = False,
        status_code: Optional[int] = None,
        phase: str = "policy",
        extra: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        """監査行を保存する。保存できた場合だけTrueを返す。"""

        target = self._safe_target(url)
        if not allowed and not endpoint_id:
            # 未知host/pathは攻撃者が値を埋め込めるため、監査には分類だけを
            # 残して具体的なpathを保存しない。hostは接続先診断のため保持する。
            target["path"] = "<blocked>"
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "phase": str(phase),
            "allowed": bool(allowed),
            "method": str(method or "").upper(),
            "endpoint_id": str(endpoint_id or ""),
            "purpose": self._enum_value(purpose),
            "reason_code": self._enum_value(reason_code),
            "scheme": target["scheme"],
            "host": target["host"],
            "path": target["path"],
            "query_names": target["query_names"],
            "redirect_hop": bool(is_redirect),
            "http_status": (
                int(status_code) if status_code is not None else None
            ),
        }
        if extra:
            # 呼出元が値や本文を追加できないよう、固定された低リスク項目だけ
            # を許可する。
            for key in ("attempt", "elapsed_ms"):
                value = extra.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    payload[key] = value
        line = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        return self._append(line)

    @staticmethod
    def _enum_value(value: object) -> str:
        raw = getattr(value, "value", value)
        return "" if raw is None else str(raw)

    @staticmethod
    def _safe_target(url: str) -> dict[str, Any]:
        """userinfo、query値、fragmentを監査データへ入れずに分解する。"""

        try:
            parsed = urlsplit(str(url or ""))
            query_names = sorted(
                {
                    key
                    for key, _value in parse_qsl(
                        parsed.query,
                        keep_blank_values=True,
                        max_num_fields=32,
                    )
                    if key
                }
            )
            return {
                "scheme": parsed.scheme.casefold(),
                "host": (parsed.hostname or "").casefold(),
                "path": parsed.path,
                "query_names": query_names,
            }
        except (TypeError, ValueError):
            return {
                "scheme": "",
                "host": "",
                "path": "",
                "query_names": [],
            }

    def _append(self, line: str) -> bool:
        try:
            with self._lock:
                with self._process_guard.try_acquire() as acquired:
                    if not acquired:
                        self._warn(
                            "通信監査ログのプロセス間ロックを取得できないため、"
                            "今回の監査行を保存できません"
                        )
                        return False
                    safe_path = resolve_verified_local_path(self.path)
                    safe_path.parent.mkdir(parents=True, exist_ok=True)
                    encoded_size = len(line.encode("utf-8"))
                    current_size = (
                        safe_path.stat().st_size if safe_path.exists() else 0
                    )
                    if current_size and current_size + encoded_size > self.max_bytes:
                        self._rotate(safe_path)
                    with safe_path.open(
                        "a", encoding="utf-8", newline="\n"
                    ) as stream:
                        stream.write(line)
                        stream.flush()
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            self._warn(f"通信監査ログを保存できません: {exc}")
            return False

    def _rotate(self, path: Path) -> None:
        if self.backup_count <= 0:
            path.unlink(missing_ok=True)
            return
        oldest = path.with_name(
            f"{path.name}.{self.backup_count}"
        )
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            if source.exists():
                source.replace(
                    path.with_name(f"{path.name}.{index + 1}")
                )
        if path.exists():
            path.replace(path.with_name(f"{path.name}.1"))

    @staticmethod
    def _warn(message: str) -> None:
        logging.getLogger("ppi_file_downloader").warning(message)


__all__ = ["NetworkAuditLedger"]
