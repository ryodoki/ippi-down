# -*- coding: utf-8 -*-

"""PDF変換監査ログを、全件常駐させずGUIで確認する。"""

from __future__ import annotations

import json
import os
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from .window_layout import fit_to_screen
from typing import Sequence


_AUDIT_FILE_RE = re.compile(
    r"^pdf-conversions-(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:-(?P<part>\d+))?\.jsonl$"
)
_CONVERSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class PdfConversionHistoryRecord:
    timestamp: str
    run_id: str
    conversion_id: str
    project_name: str
    document_name: str
    renderer: str
    status: str
    reason_code: str
    elapsed_seconds: float
    recovery_artifact: bool


def _tail_lines(path: Path, maximum_bytes: int) -> Sequence[str]:
    """JSONLの末尾だけを読み、途中行を除外して返す。"""

    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            start = max(0, size - max(1024, int(maximum_bytes)))
            stream.seek(start)
            payload = stream.read()
    except OSError:
        return ()
    if start > 0:
        separator = payload.find(b"\n")
        payload = payload[separator + 1 :] if separator >= 0 else b""
    return payload.decode("utf-8", errors="replace").splitlines()


def load_pdf_conversion_history(
    logs_dir: Path,
    *,
    limit: int = 200,
    maximum_file_bytes: int = 2 * 1024 * 1024,
) -> tuple[PdfConversionHistoryRecord, ...]:
    """新しい監査ファイルから完了レコードだけを最大件数まで読む。"""

    root = Path(logs_dir)
    try:
        managed_paths: list[tuple[str, int, Path]] = []
        for path in root.iterdir():
            match = _AUDIT_FILE_RE.fullmatch(path.name)
            if match is None or not path.is_file() or path.is_symlink():
                continue
            managed_paths.append(
                (
                    match.group("date"),
                    int(match.group("part") or 0),
                    path,
                )
            )
        paths = [
            item[2]
            for item in sorted(
                managed_paths,
                key=lambda item: (item[0], item[1]),
                reverse=True,
            )
        ]
    except OSError:
        return ()

    records: list[PdfConversionHistoryRecord] = []
    bounded_limit = max(1, min(int(limit), 1000))
    for path in paths:
        for line in reversed(_tail_lines(path, maximum_file_bytes)):
            try:
                value = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if (
                not isinstance(value, dict)
                or value.get("event") != "conversion_finished"
            ):
                continue
            conversion_id = str(value.get("conversion_id") or "").casefold()
            if not _CONVERSION_ID_RE.fullmatch(conversion_id):
                continue
            try:
                elapsed = max(0.0, float(value.get("elapsed_seconds") or 0.0))
            except (TypeError, ValueError):
                elapsed = 0.0
            records.append(
                PdfConversionHistoryRecord(
                    timestamp=str(value.get("timestamp_utc") or ""),
                    run_id=str(value.get("run_id") or ""),
                    conversion_id=conversion_id,
                    project_name=str(value.get("project_name") or ""),
                    document_name=str(value.get("document_name") or ""),
                    renderer=str(value.get("renderer") or ""),
                    status=str(value.get("status") or ""),
                    reason_code=str(value.get("reason_code") or ""),
                    elapsed_seconds=elapsed,
                    recovery_artifact=bool(value.get("recovery_artifact", False)),
                )
            )
            if len(records) >= bounded_limit:
                return tuple(records)
    return tuple(records)


def _display_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y/%m/%d %H:%M:%S")
    except ValueError:
        return value or "-"


class PdfConversionHistoryDialog:
    """直近のPDF変換と、失敗時の相関IDを一覧表示する。"""

    def __init__(self, parent: tk.Misc, logs_dir: Path) -> None:
        self.logs_dir = Path(logs_dir)
        self.window = tk.Toplevel(parent)
        self.window.title("PDF変換履歴（直近200件）")
        fit_to_screen(
            self.window, 1120, 520, minimum_width=600, minimum_height=380
        )
        self.window.transient(parent)

        frame = ttk.Frame(self.window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frame,
            text=(
                "実行中はプロセス数・heartbeatも日別JSONLへ記録されます。"
                "失敗時は相関IDで再変換用データを確認できます。"
            ),
        ).pack(anchor=tk.W, pady=(0, 8))

        columns = (
            "time",
            "project",
            "document",
            "renderer",
            "status",
            "reason",
            "seconds",
            "artifact",
            "conversion_id",
        )
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        headings = {
            "time": "完了日時",
            "project": "案件名",
            "document": "文書名",
            "renderer": "生成方式",
            "status": "結果",
            "reason": "理由コード",
            "seconds": "秒",
            "artifact": "障害資料",
            "conversion_id": "変換ID",
        }
        widths = {
            "time": 135,
            "project": 190,
            "document": 130,
            "renderer": 115,
            "status": 75,
            "reason": 175,
            "seconds": 55,
            "artifact": 65,
            "conversion_id": 210,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], stretch=column == "project")
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill=tk.BOTH, expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscrollbar = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=scrollbar.set, xscrollcommand=xscrollbar.set
        )
        self.tree.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.E, tk.W))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        xscrollbar.grid(row=1, column=0, sticky=(tk.E, tk.W))

        actions = ttk.Frame(self.window, padding=(10, 0, 10, 10))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="再読み込み", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(actions, text="ログフォルダーを開く", command=self.open_logs).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(
            actions, text="選択した障害資料を開く", command=self.open_artifact
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="閉じる", command=self.window.destroy).pack(
            side=tk.RIGHT
        )
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for record in load_pdf_conversion_history(self.logs_dir):
            self.tree.insert(
                "",
                tk.END,
                iid=record.conversion_id,
                values=(
                    _display_timestamp(record.timestamp),
                    record.project_name or "-",
                    record.document_name or "-",
                    record.renderer or "-",
                    "成功" if record.status == "SUCCESS" else "失敗",
                    record.reason_code or "-",
                    f"{record.elapsed_seconds:.1f}",
                    "あり" if record.recovery_artifact else "-",
                    record.conversion_id,
                ),
            )

    def open_logs(self) -> None:
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.logs_dir))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror(
                "PDF変換履歴", f"ログフォルダーを開けません: {exc}", parent=self.window
            )

    def open_artifact(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(
                "PDF変換履歴", "履歴を選択してください。", parent=self.window
            )
            return
        conversion_id = str(selection[0]).casefold()
        if not _CONVERSION_ID_RE.fullmatch(conversion_id):
            return
        target = self.logs_dir / "pdf-failures" / conversion_id
        if not target.is_dir() or target.is_symlink():
            messagebox.showinfo(
                "PDF変換履歴",
                "この変換の障害資料はありません（成功または保存期限経過）。",
                parent=self.window,
            )
            return
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror(
                "PDF変換履歴", f"障害資料を開けません: {exc}", parent=self.window
            )
