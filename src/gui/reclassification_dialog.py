# -*- coding: utf-8 -*-

"""保存済みファイルの再分類プレビューと実行画面。"""

from __future__ import annotations

import inspect
import tkinter as tk
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from tkinter import messagebox, ttk
from .window_layout import fit_to_screen
from .window_layout import WrapButtonBar
from typing import Callable, Optional

from ..models.config_model import AppConfig
from ..utils.logger import Logger


def _payload_value(payload: object, *names: str, default: object = None) -> object:
    """dictまたはdataclass風DTOから最初に存在する値を取り出す。"""

    for name in names:
        if isinstance(payload, Mapping) and name in payload:
            return payload[name]
        if hasattr(payload, name):
            value = getattr(payload, name)
            if value is not None:
                return value
    return default


def _enum_text(value: object) -> str:
    if isinstance(value, Enum):
        value = value.value
    return str(value or "").strip()


def _as_items(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return tuple(value.values())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return tuple(value)
    return ()


def _run_kind_label(value: object) -> str:
    key = _enum_text(value).upper()
    return {
        "MANUAL": "通常ダウンロード",
        "NORMAL": "通常ダウンロード",
        "SCHEDULED": "定期実行",
        "SCHEDULE": "定期実行",
    }.get(key, _enum_text(value) or "不明")


_CANDIDATE_STATE_LABELS = {
    "READY_MOVE": "再分類可能（移動）",
    "READY_TARGET_REUSE": "履歴更新のみ（旧ファイル保持）",
    "UNRESOLVED": "対象外（分類未解決）",
    "INVALID": "対象外（履歴・ファイル不正）",
    "CONFLICT": "対象外（移動先競合）",
}


@dataclass(frozen=True)
class ReclassificationCandidateView:
    """Treeviewへ表示する再分類候補。"""

    candidate_id: str
    run_kind: str
    schedule_name: str
    project_name: str
    document_name: str
    current_path: str
    target_path: str
    reason: str
    reason_code: str
    state: str
    applicable: bool
    selected: bool

    @property
    def applicability(self) -> str:
        return _CANDIDATE_STATE_LABELS.get(
            self.state,
            "再分類可能" if self.applicable else "対象外",
        )

    @property
    def reason_display(self) -> str:
        if self.reason_code and self.reason:
            return f"{self.reason} [{self.reason_code}]"
        return self.reason or self.reason_code or "－"


def normalise_reclassification_candidates(
    plan: object,
) -> tuple[ReclassificationCandidateView, ...]:
    """サービス固有DTOを、安定したGUI表示モデルへ変換する。"""

    raw_items = _payload_value(
        plan,
        "candidates",
        "items",
        "entries",
        "moves",
        default=plan if not isinstance(plan, (str, bytes)) else (),
    )
    result: list[ReclassificationCandidateView] = []
    for index, item in enumerate(_as_items(raw_items), start=1):
        candidate_id = str(
            _payload_value(
                item,
                "candidate_id",
                "id",
                "entry_id",
                "history_id",
                default=f"candidate-{index}",
            )
            or f"candidate-{index}"
        ).strip()
        current_path = str(
            _payload_value(
                item,
                "current_path",
                "source_path",
                "actual_path",
                "path",
                default="",
            )
            or ""
        )
        target_path = str(
            _payload_value(
                item,
                "target_path",
                "proposed_path",
                "destination_path",
                "planned_path",
                default="",
            )
            or ""
        )
        explicit_applicable = _payload_value(
            item,
            "actionable",
            "applicable",
            "can_apply",
            "eligible",
            "movable",
            default=None,
        )
        state = _enum_text(
            _payload_value(item, "state", "status", default="")
        ).upper()
        if explicit_applicable is not None:
            applicable = bool(explicit_applicable)
        elif state:
            applicable = state in {"READY_MOVE", "READY_TARGET_REUSE"}
        else:
            applicable = bool(
                current_path and target_path and current_path != target_path
            )
        explicit_selected = _payload_value(
            item,
            "selected",
            "default_selected",
            default=None,
        )
        selected = applicable if explicit_selected is None else bool(explicit_selected)
        raw_run_kind = _payload_value(
            item,
            "run_kind",
            "execution_kind",
            "scope",
        )
        run_kind = _run_kind_label(raw_run_kind)
        storage_key = str(_payload_value(item, "storage_key", default="") or "").strip()
        schedule_name = str(
            _payload_value(
                item,
                "schedule_name",
                "display_name",
                "profile_name",
                default="",
            )
            or ""
        ).strip()
        if not schedule_name and run_kind == "定期実行":
            run_root_name = Path(
                str(_payload_value(item, "run_root", default="") or "")
            ).name
            prefix = f"{storage_key}_" if storage_key else ""
            schedule_name = (
                run_root_name[len(prefix) :]
                if prefix and run_root_name.startswith(prefix)
                else run_root_name
            )
        if schedule_name and storage_key:
            schedule_name = f"{schedule_name} ({storage_key})"
        elif not schedule_name:
            schedule_name = storage_key or "－"
        result.append(
            ReclassificationCandidateView(
                candidate_id=candidate_id,
                run_kind=run_kind,
                schedule_name=schedule_name,
                project_name=str(
                    _payload_value(
                        item,
                        "project_name",
                        "koji_name",
                        "project",
                        default="－",
                    )
                    or "－"
                ),
                document_name=str(
                    _payload_value(
                        item,
                        "document_name",
                        "file_name",
                        "filename",
                        default="－",
                    )
                    or "－"
                ),
                current_path=current_path or "－",
                target_path=target_path or "－",
                reason=str(
                    _payload_value(
                        item,
                        "reason",
                        "message",
                        "diagnostic",
                        default="",
                    )
                    or ""
                ),
                reason_code=_enum_text(
                    _payload_value(item, "reason_code", "issue_code", "code")
                ).upper(),
                state=state,
                applicable=applicable,
                selected=selected and applicable,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class ReclassificationResultView:
    total: int
    moved: int
    reused: int
    conflict: int
    invalid: int
    skipped: int
    failed: int
    cancelled: int
    message: str
    reason_code: str = ""

    @property
    def summary(self) -> str:
        detail = (
            f"移動={self.moved} / 移動先を正本化・旧ファイル保持={self.reused} / "
            f"競合={self.conflict} / 不正={self.invalid} / "
            f"対象外・スキップ={self.skipped} / "
            f"失敗={self.failed} / キャンセル={self.cancelled}"
        )
        if self.message:
            detail += f"\n{self.message}"
        if self.reason_code:
            detail += f" [{self.reason_code}]"
        return detail


def normalise_reclassification_result(result: object) -> ReclassificationResultView:
    """apply結果の件数と診断をGUI向けに正規化する。"""

    def count(*names: str, default: int = 0) -> int:
        raw = _payload_value(result, *names, default=default)
        if isinstance(raw, bool):
            return default
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return default

    moved = count("moved_count", "moved", "applied", "success_count", "completed")
    reused = count("target_reused_count", "reused", "target_reused", "reuse_count")
    conflict = count("conflict_count", "conflict", "conflicts")
    invalid = count("invalid_count", "invalid")
    skipped = count("skipped_count", "skipped", "unchanged", "not_applicable")
    failed = count("failed_count", "failed", "failure_count", "errors")
    cancelled = count("cancelled_count", "cancelled")
    total = count(
        "total",
        "candidate_count",
        default=moved + reused + conflict + invalid + skipped + failed + cancelled,
    )
    issue_texts: list[str] = []
    for issue in _as_items(_payload_value(result, "issues", default=())):
        code = _enum_text(_payload_value(issue, "reason_code", "code")).upper()
        reason = str(_payload_value(issue, "reason", "message", default="") or "")
        text = reason or code
        if code and reason:
            text = f"{reason} [{code}]"
        if text:
            issue_texts.append(text)
    return ReclassificationResultView(
        total=total,
        moved=moved,
        reused=reused,
        conflict=conflict,
        invalid=invalid,
        skipped=skipped,
        failed=failed,
        cancelled=cancelled,
        message=(
            str(_payload_value(result, "message", "reason", default="") or "")
            or " / ".join(issue_texts[:3])
        ),
        reason_code=_enum_text(
            _payload_value(result, "reason_code", "issue_code", default="")
        ).upper(),
    )


class ReclassificationServiceAdapter:
    """再分類サービスの任意引数差をGUI境界で吸収する。"""

    def __init__(self, service: object):
        self.service = service

    @staticmethod
    def _invoke(method: Callable, *args: object, **kwargs: object) -> object:
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(*args, **kwargs)
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        filtered = {
            name: value
            for name, value in kwargs.items()
            if accepts_kwargs or name in parameters
        }
        return method(*args, **filtered)

    def scan(
        self,
        config: AppConfig,
        *,
        cancel_check: Callable[[], bool],
        progress_callback: Callable[..., None],
    ) -> object:
        method = getattr(self.service, "scan", None)
        if not callable(method):
            raise RuntimeError("再分類サービスにscan機能がありません")
        return self._invoke(
            method,
            config,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )

    def apply(
        self,
        plan: object,
        candidate_ids: tuple[str, ...],
        *,
        cancel_check: Callable[[], bool],
        progress_callback: Callable[..., None],
    ) -> object:
        method = getattr(self.service, "apply", None)
        if not callable(method):
            raise RuntimeError("再分類サービスにapply機能がありません")
        return self._invoke(
            method,
            plan,
            candidate_ids=candidate_ids,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )


class ReclassificationDialog:
    """既存ファイルを変更する前に必ず候補を確認するモーダル。"""

    def __init__(
        self,
        parent: tk.Misc,
        service: object,
        config: AppConfig,
        *,
        block_reason_provider: Optional[Callable[[], str]] = None,
        logger: Optional[Logger] = None,
    ) -> None:
        self.parent = parent
        self.config = config
        self.adapter = ReclassificationServiceAdapter(service)
        self.block_reason_provider = block_reason_provider
        self.logger = logger or Logger()
        self._plan: object = None
        self._candidates: dict[str, ReclassificationCandidateView] = {}
        self._selected_ids: set[str] = set()
        self._busy = ""
        self._cancel = Event()
        self._closed = False
        self._queue: Queue[tuple[str, object]] = Queue(maxsize=16)
        self._progress_lock = Lock()
        self._latest_progress: tuple[int, int, str] | None = None
        self._after_id: str | None = None

        self.window = tk.Toplevel(parent)
        self.window.title("保存済みファイルの再分類")
        fit_to_screen(
            self.window, 1280, 700, minimum_width=600, minimum_height=400
        )
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)

        explanation = (
            "通常ダウンロードと定期実行の履歴を検証し、現在位置と新しい保存仕様の"
            "差だけを表示します。確認して選択したファイル以外は変更しません。"
        )
        ttk.Label(
            self.window,
            text=explanation,
            wraplength=1180,
            justify=tk.LEFT,
            padding=(10, 10, 10, 4),
        ).grid(row=0, column=0, sticky=(tk.W, tk.E))

        status_frame = ttk.Frame(self.window, padding=(10, 2, 10, 6))
        status_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
        status_frame.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="候補を確認しています…")
        ttk.Label(status_frame, textvariable=self.status_var).grid(
            row=0, column=0, sticky=tk.W
        )
        self.progress = ttk.Progressbar(status_frame, mode="determinate", maximum=1)
        self.progress.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(4, 0))

        tree_frame = ttk.Frame(self.window, padding=(10, 0, 10, 6))
        tree_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        columns = (
            "selected",
            "run_kind",
            "schedule",
            "project",
            "document",
            "current",
            "target",
            "reason",
            "applicable",
        )
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "selected": "選択",
            "run_kind": "実行区分",
            "schedule": "定期実行設定",
            "project": "工事",
            "document": "文書",
            "current": "現在位置",
            "target": "移動先",
            "reason": "理由",
            "applicable": "可否",
        }
        widths = {
            "selected": 55,
            "run_kind": 110,
            "schedule": 140,
            "project": 210,
            "document": 170,
            "current": 280,
            "target": 280,
            "reason": 250,
            "applicable": 95,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(
                column,
                width=widths[column],
                minwidth=50,
                stretch=column in {"project", "current", "target", "reason"},
            )
        vertical = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(
            tree_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        vertical.grid(row=0, column=1, sticky=(tk.N, tk.S))
        horizontal.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.tree.bind("<Double-1>", self._toggle_selected)
        self.tree.bind("<space>", self._toggle_selected)

        buttons = WrapButtonBar(self.window, padding=(10, 4, 10, 10))
        buttons.grid(row=3, column=0, sticky=(tk.W, tk.E))
        self.btn_rescan = ttk.Button(buttons, text="再スキャン", command=self.start_scan)
        buttons.add(self.btn_rescan)
        self.btn_select_all = ttk.Button(
            buttons, text="すべて選択", command=lambda: self._select_all(True)
        )
        buttons.add(self.btn_select_all)
        self.btn_clear = ttk.Button(
            buttons, text="選択解除", command=lambda: self._select_all(False)
        )
        buttons.add(self.btn_clear)
        self.btn_close = ttk.Button(buttons, text="閉じる", command=self.close)
        buttons.add(self.btn_close, right=True)
        self.btn_cancel = ttk.Button(
            buttons, text="処理をキャンセル", command=self.cancel, state="disabled"
        )
        buttons.add(self.btn_cancel, right=True)
        self.btn_apply = ttk.Button(
            buttons,
            text="選択したファイルを再分類",
            command=self.apply_selected,
            state="disabled",
        )
        buttons.add(self.btn_apply, right=True)

        self._after_id = self.window.after(100, self._poll)
        self.window.after_idle(self.start_scan)

    def _block_reason(self) -> str:
        if self.block_reason_provider is None:
            return ""
        try:
            return str(self.block_reason_provider() or "")
        except Exception as exc:
            return f"実行状態を確認できません: {exc}"

    def start_scan(self) -> None:
        if self._busy or self._closed:
            return
        reason = self._block_reason()
        if reason:
            self.status_var.set(reason)
            messagebox.showwarning("再分類できません", reason, parent=self.window)
            return
        self._plan = None
        self._candidates.clear()
        self._selected_ids.clear()
        self.tree.delete(*self.tree.get_children())
        self._start_worker("scan", self._scan_worker)

    def _scan_worker(self) -> object:
        return self.adapter.scan(
            self.config,
            cancel_check=self._cancel.is_set,
            progress_callback=self._on_progress,
        )

    def apply_selected(self) -> None:
        if self._busy or self._plan is None:
            return
        reason = self._block_reason()
        if reason:
            messagebox.showwarning("再分類できません", reason, parent=self.window)
            return
        selected = tuple(
            candidate_id
            for candidate_id in self._selected_ids
            if self._candidates.get(candidate_id, None) is not None
            and self._candidates[candidate_id].applicable
        )
        if not selected:
            messagebox.showinfo(
                "再分類",
                "再分類するファイルを選択してください。",
                parent=self.window,
            )
            return
        if not messagebox.askyesno(
            "再分類の確認",
            f"選択した{len(selected)}件を表示された移動先へ再分類します。\n"
            "処理中に失敗したファイルは元の場所を維持します。実行しますか？",
            parent=self.window,
        ):
            return

        def worker() -> object:
            return self.adapter.apply(
                self._plan,
                selected,
                cancel_check=self._cancel.is_set,
                progress_callback=self._on_progress,
            )

        self._start_worker("apply", worker)

    def _start_worker(self, operation: str, callback: Callable[[], object]) -> None:
        self._busy = operation
        self._cancel = Event()
        self.progress.configure(maximum=1, value=0)
        self.status_var.set(
            "再分類候補を確認しています…"
            if operation == "scan"
            else "選択したファイルを再分類しています…"
        )
        self._refresh_buttons()

        def run() -> None:
            try:
                result = callback()
                self._put_terminal((f"{operation}_done", result))
            except Exception as exc:
                self._put_terminal((f"{operation}_error", exc))

        Thread(target=run, name=f"ippi-reclassification-{operation}", daemon=True).start()

    def _put_terminal(self, item: tuple[str, object]) -> None:
        try:
            self._queue.put_nowait(item)
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            try:
                self._queue.put_nowait(item)
            except Full:
                pass

    def _on_progress(self, *args: object, **kwargs: object) -> None:
        payload = args[0] if len(args) == 1 else None
        current = _payload_value(payload, "current", "processed", default=None)
        total = _payload_value(payload, "total", "candidate_count", default=None)
        message = _payload_value(payload, "message", "status", default=None)
        if current is None and args:
            current = args[0]
        if total is None and len(args) > 1:
            total = args[1]
        if message is None and len(args) > 2:
            message = args[2]
        current = kwargs.get("current", current)
        total = kwargs.get("total", total)
        message = kwargs.get("message", message)
        try:
            current_int = max(0, int(current or 0))
        except (TypeError, ValueError):
            current_int = 0
        try:
            total_int = max(0, int(total or 0))
        except (TypeError, ValueError):
            total_int = 0
        with self._progress_lock:
            self._latest_progress = (current_int, total_int, str(message or ""))

    def _poll(self) -> None:
        if self._closed:
            return
        with self._progress_lock:
            progress = self._latest_progress
            self._latest_progress = None
        if progress is not None:
            current, total, message = progress
            self.progress.configure(maximum=max(1, total), value=min(current, max(1, total)))
            if message:
                self.status_var.set(message)
        try:
            while True:
                event, payload = self._queue.get_nowait()
                if event == "scan_done":
                    self._finish_scan(payload)
                elif event == "apply_done":
                    self._finish_apply(payload)
                elif event.endswith("_error"):
                    self._finish_error(event.removesuffix("_error"), payload)
        except Empty:
            pass
        try:
            self._after_id = self.window.after(100, self._poll)
        except tk.TclError:
            self._closed = True

    def _finish_scan(self, plan: object) -> None:
        self._busy = ""
        candidates = normalise_reclassification_candidates(plan)
        self._candidates = {item.candidate_id: item for item in candidates}
        cancelled = bool(_payload_value(plan, "cancelled", default=False))
        self._plan = None if cancelled else plan
        self._selected_ids = (
            set()
            if cancelled
            else {
                item.candidate_id
                for item in candidates
                if item.selected and item.applicable
            }
        )
        self._render_candidates()
        applicable = sum(item.applicable for item in candidates)
        blocked = len(candidates) - applicable
        status_text = (
            (
                "候補確認をキャンセルしました。部分結果は適用できません。"
                "再スキャンしてください: "
                if cancelled
                else "確認完了: "
            )
            + f"候補{len(candidates)}件 / 再分類可能{applicable}件 / "
            f"対象外{blocked}件"
        )
        issues = _as_items(_payload_value(plan, "issues", default=()))
        if issues:
            first_issue = issues[0]
            code = _enum_text(
                _payload_value(first_issue, "reason_code", "code")
            ).upper()
            reason = str(
                _payload_value(first_issue, "reason", "message", default="")
                or ""
            )
            status_text += f" / {reason or code}"
            if code and reason:
                status_text += f" [{code}]"
        self.status_var.set(status_text)
        self.progress.configure(maximum=1, value=1)
        log_message = (
            "保存済みファイル再分類の候補確認キャンセル: "
            if cancelled
            else "保存済みファイル再分類の確認完了: "
        )
        log_message += (
            f"候補={len(candidates)}, 再分類可能={applicable}, 対象外={blocked}"
        )
        if cancelled:
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)
        self._refresh_buttons()

    def _finish_apply(self, result: object) -> None:
        self._busy = ""
        view = normalise_reclassification_result(result)
        self.status_var.set(view.summary.replace("\n", " / "))
        self.progress.configure(maximum=max(1, view.total), value=min(view.total, max(1, view.total)))
        self._invalidate_plan_after_apply()
        self._refresh_buttons()
        self.logger.info(f"保存済みファイル再分類完了: {view.summary.replace(chr(10), ' / ')}")
        if view.failed or view.conflict or view.invalid or view.cancelled:
            messagebox.showwarning("再分類結果", view.summary, parent=self.window)
        else:
            messagebox.showinfo("再分類結果", view.summary, parent=self.window)

    def _invalidate_plan_after_apply(self) -> None:
        """適用済みpreviewを再実行できないよう候補ごと破棄する。"""

        self._plan = None
        self._selected_ids.clear()
        self._candidates.clear()
        try:
            self.tree.delete(*self.tree.get_children())
        except tk.TclError:
            pass

    def _finish_error(self, operation: str, payload: object) -> None:
        self._busy = ""
        reason_code = _enum_text(getattr(payload, "reason_code", "")).upper()
        message = str(payload or "不明なエラー")
        suffix = f" [{reason_code}]" if reason_code else ""
        self.status_var.set(f"処理に失敗しました: {message}{suffix}")
        self._refresh_buttons()
        self.logger.error(
            f"保存済みファイル再分類{operation}失敗: {message}{suffix}"
        )
        messagebox.showerror(
            "再分類エラー",
            f"処理に失敗しました。\n{message}{suffix}",
            parent=self.window,
        )

    def _render_candidates(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for candidate in self._candidates.values():
            self.tree.insert(
                "",
                tk.END,
                iid=candidate.candidate_id,
                values=(
                    "☑" if candidate.candidate_id in self._selected_ids else "☐",
                    candidate.run_kind,
                    candidate.schedule_name,
                    candidate.project_name,
                    candidate.document_name,
                    candidate.current_path,
                    candidate.target_path,
                    candidate.reason_display,
                    candidate.applicability,
                ),
                tags=("blocked",) if not candidate.applicable else (),
            )
        self.tree.tag_configure("blocked", foreground="#777777")

    def _toggle_selected(self, _event: object = None) -> str:
        selected = self.tree.selection()
        if not selected:
            return "break"
        candidate_id = selected[0]
        candidate = self._candidates.get(candidate_id)
        if (
            candidate is None
            or not candidate.applicable
            or self._busy
            or self._plan is None
        ):
            return "break"
        if candidate_id in self._selected_ids:
            self._selected_ids.remove(candidate_id)
        else:
            self._selected_ids.add(candidate_id)
        self._render_candidates()
        try:
            self.tree.selection_set(candidate_id)
            self.tree.focus(candidate_id)
        except tk.TclError:
            pass
        self._refresh_buttons()
        return "break"

    def _select_all(self, selected: bool) -> None:
        if self._busy or self._plan is None:
            self._selected_ids.clear()
            self._render_candidates()
            self._refresh_buttons()
            return
        self._selected_ids = (
            {
                item.candidate_id
                for item in self._candidates.values()
                if item.applicable
            }
            if selected
            else set()
        )
        self._render_candidates()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        busy = bool(self._busy)
        has_plan = self._plan is not None
        self.btn_rescan.configure(state="disabled" if busy else "normal")
        selection_state = "normal" if not busy and has_plan else "disabled"
        self.btn_select_all.configure(state=selection_state)
        self.btn_clear.configure(state=selection_state)
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        self.btn_apply.configure(
            state=(
                "normal"
                if not busy and has_plan and self._selected_ids
                else "disabled"
            )
        )

    def cancel(self) -> None:
        if not self._busy:
            return
        self._cancel.set()
        self.status_var.set("キャンセルしています…")
        self.btn_cancel.configure(state="disabled")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel.set()
        if self._after_id is not None:
            try:
                self.window.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        try:
            self.tree.delete(*self.tree.get_children())
        except tk.TclError:
            pass
        self._candidates.clear()
        self._selected_ids.clear()
        self._plan = None
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()
        try:
            self.parent.grab_set()
        except tk.TclError:
            pass


__all__ = [
    "ReclassificationCandidateView",
    "ReclassificationDialog",
    "ReclassificationResultView",
    "ReclassificationServiceAdapter",
    "normalise_reclassification_candidates",
    "normalise_reclassification_result",
]
