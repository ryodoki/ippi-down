# -*- coding: utf-8 -*-

"""複数スケジュールをGUIから扱うための後方互換アダプタ。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Iterable, Mapping, Optional

from ..models.config_model import AppConfig
from ..scheduler.profile import calculate_condition_fingerprint
from ..storage.layout import RunKind, resolve_run_root, target_storage_folder


def schedule_value(value: object, *names: str, default: object = None) -> object:
    """dict/dataclass双方から最初に見つかった属性を返す。"""

    for name in names:
        if isinstance(value, Mapping) and name in value:
            item = value[name]
        else:
            item = getattr(value, name, None)
        if item is not None:
            return item
    return default


def schedule_identifier(value: object, default: str = "default") -> str:
    """利用者が管理する安定IDを取り出す。"""

    return str(
        schedule_value(
            value,
            "schedule_id",
            "id",
            default=default,
        )
        or default
    )


def snapshot_identifier(value: object) -> str:
    """不変スナップショットIDを旧profile_id込みで取り出す。"""

    return str(
        schedule_value(
            value,
            "snapshot_id",
            "profile_id",
            "active_profile_id",
            default="",
        )
        or ""
    )


@dataclass
class ScheduleView:
    """GUI一覧用に正規化した1件分の表示モデル。"""

    schedule_id: str
    name: str
    enabled: bool
    definition: object = None
    status: object = None
    config: Optional[AppConfig] = None

    @property
    def origin(self) -> str:
        """サービスの所有権表現をGUI用の安定した文字列へ正規化する。"""

        raw = schedule_value(self.status, "origin", default="")
        value = str(getattr(raw, "value", raw) or "").strip().lower()
        if value in {
            "external_task",
            "external",
            "legacy_candidate",
            "orphan",
            "unmanaged",
        }:
            return "external_task"
        # 旧サービスでも、台帳外を通常の修復対象として扱わない。
        reason_code = str(
            schedule_value(self.status, "reason_code", default="") or ""
        ).upper()
        if reason_code in {
            "TASK_REGISTRY_MISSING",
            "EXTERNAL_TASK_IMPORTABLE",
            "EXTERNAL_TASK_NOT_IMPORTABLE",
        }:
            return "external_task"
        return "managed"

    @property
    def is_external(self) -> bool:
        return self.origin == "external_task"

    def allows(self, action: str) -> bool:
        """backendのcapabilitiesを優先し、旧statusへ安全にフォールバックする。"""

        capabilities = schedule_value(self.status, "capabilities")
        capability_name = f"can_{action}"
        explicit = schedule_value(capabilities, capability_name, default=None)
        if explicit is not None:
            return bool(explicit)
        if self.is_external:
            if action == "import":
                return str(
                    schedule_value(self.status, "reason_code", default="") or ""
                ).upper() == "EXTERNAL_TASK_IMPORTABLE"
            return action == "remove_external"
        if action in {"edit", "delete"}:
            return True
        if action == "repair":
            return bool(schedule_value(self.status, "repair_reason", default="")) or bool(
                schedule_value(self.status, "definition_mismatch", default=False)
            )
        if action == "run":
            return bool(
                schedule_value(self.status, "registered", default=False)
            ) and not bool(schedule_value(self.status, "repair_reason", default=""))
        return False

    @property
    def profile_id(self) -> str:
        return snapshot_identifier(self.status) or snapshot_identifier(self.definition)

    @property
    def storage_key(self) -> str:
        value = schedule_value(
            self.definition,
            "storage_key",
            default=schedule_value(self.status, "storage_key", default=""),
        )
        if not value and self.config is not None:
            value = self.config.save_paths.schedule_storage_key
        return str(value or "")

    @property
    def storage_folder(self) -> str:
        value = schedule_value(
            self.definition,
            "storage_folder",
            default=schedule_value(self.status, "storage_folder", default=""),
        )
        if not value and self.config is not None:
            value = self.config.save_paths.schedule_storage_folder
        return str(value or "")


def format_storage_preview(config: AppConfig, run_kind: RunKind | str) -> str:
    """GUI向けに、未採番の定期実行も含む保存予定パスを返す。"""

    save_paths = config.save_paths
    kind = run_kind if isinstance(run_kind, RunKind) else RunKind(str(run_kind).upper())
    if (
        kind is RunKind.SCHEDULED
        and int(getattr(save_paths, "layout_version", 2) or 2) >= 3
        and not str(getattr(save_paths, "schedule_storage_folder", "") or "")
    ):
        parts = [Path(save_paths.local)]
        if int(getattr(save_paths, "layout_version", 2) or 2) >= 4:
            parts.append(
                Path(target_storage_folder(config.search_conditions.target))
            )
        parts.extend(
            (
                Path(save_paths.scheduled_folder),
                Path("<登録時に自動割当>"),
            )
        )
        path = parts[0]
        for part in parts[1:]:
            path /= part
        return str(path)
    return str(
        resolve_run_root(
            save_paths,
            kind,
            config.search_conditions.target,
        )
    )


@dataclass(frozen=True)
class _QueueStatusOverlay:
    """backend状態へ実行キューの待機情報を非破壊で重ねる。"""

    base: object
    queue_waiting: bool
    queue_position: Optional[int]
    queue_total: int

    def __getattr__(self, name: str) -> object:
        if isinstance(self.base, Mapping) and name in self.base:
            return self.base[name]
        return getattr(self.base, name, None)


def _overlay_queue_status(status: object, schedule_id: str) -> object:
    try:
        from ..app.run_queue import status_for

        queue_status = status_for(schedule_id)
    except (ImportError, OSError, RuntimeError, ValueError):
        return status
    return _QueueStatusOverlay(
        base=status,
        queue_waiting=bool(getattr(queue_status, "waiting", False)),
        queue_position=getattr(queue_status, "position", None),
        queue_total=int(getattr(queue_status, "total_waiting", 0) or 0),
    )


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, (str, bytes)):
        return []
    try:
        return list(value)  # type: ignore[arg-type]
    except TypeError:
        return [value]


def normalise_schedule_views(
    definitions: Iterable[object], statuses: object = None
) -> list[ScheduleView]:
    """backend DTOとdictを安定した一覧へまとめる。"""

    status_by_id: dict[str, object] = {}
    if isinstance(statuses, Mapping):
        status_by_id = {str(key): value for key, value in statuses.items()}
    else:
        for status in _as_list(statuses):
            status_by_id[schedule_identifier(status)] = status

    views: list[ScheduleView] = []
    seen: set[str] = set()
    for definition in definitions:
        schedule_id = schedule_identifier(definition)
        status = status_by_id.get(schedule_id) or schedule_value(
            definition, "registration_status", "status_detail"
        )
        schedule = schedule_value(definition, "schedule")
        enabled = bool(
            schedule_value(
                definition,
                "enabled",
                default=schedule_value(schedule, "enabled", default=False),
            )
        )
        name = str(
            schedule_value(
                definition,
                "name",
                "display_name",
                default=schedule_value(status, "name", "display_name", default=""),
            )
            or schedule_id
        )
        config = schedule_value(
            definition,
            "config",
            "app_config",
            "snapshot_config",
        )
        views.append(
            ScheduleView(
                schedule_id=schedule_id,
                name=name,
                enabled=enabled,
                definition=definition,
                status=status,
                config=config if isinstance(config, AppConfig) else None,
            )
        )
        seen.add(schedule_id)

    # 状態だけ返すbackendでも一覧を失わない。
    for schedule_id, status in status_by_id.items():
        if schedule_id in seen:
            continue
        views.append(
            ScheduleView(
                schedule_id=schedule_id,
                name=str(
                    schedule_value(status, "name", "display_name", default=schedule_id)
                ),
                enabled=bool(
                    schedule_value(
                        status,
                        "enabled",
                        default=schedule_value(status, "registered", default=False),
                    )
                ),
                status=status,
            )
        )

    # Task Scheduler列挙順やdict構築順に依存させない。管理対象を先に、
    # 外部タスクを後に固定することで、更新のたびに行が移動するのを防ぐ。
    managed = [item for item in views if not item.is_external]
    external = sorted(
        (item for item in views if item.is_external),
        key=lambda item: (item.name.casefold(), item.schedule_id),
    )
    return [*managed, *external]


@dataclass(frozen=True)
class ScheduleTreeRow:
    """Treeview差分更新用の、安定IDを持つ1行。"""

    item_id: str
    values: tuple[object, ...]
    tags: tuple[str, ...] = ()


def reconcile_schedule_tree(
    tree: object,
    rows: Iterable[ScheduleTreeRow],
    *,
    selected_id: Optional[str] = None,
) -> Optional[str]:
    """全削除を行わずTreeviewを同期し、選択・focus・表示位置を維持する。"""

    materialized = list(rows)
    desired_ids = [row.item_id for row in materialized]
    desired_set = set(desired_ids)
    previous_selection = tuple(str(value) for value in tree.selection())
    try:
        yview = tuple(tree.yview())
        y_fraction = float(yview[0]) if yview else 0.0
    except (AttributeError, TypeError, ValueError):
        y_fraction = 0.0

    for item_id in tuple(str(value) for value in tree.get_children()):
        if item_id not in desired_set:
            tree.delete(item_id)

    for index, row in enumerate(materialized):
        if tree.exists(row.item_id):
            tree.item(row.item_id, values=row.values, tags=row.tags)
            tree.move(row.item_id, "", index)
        else:
            tree.insert(
                "",
                "end",
                iid=row.item_id,
                values=row.values,
                tags=row.tags,
            )

    target = selected_id if selected_id in desired_set else None
    if target is None:
        target = next((item for item in previous_selection if item in desired_set), None)
    if target is not None:
        tree.selection_set(target)
        tree.focus(target)
        tree.see(target)
    elif hasattr(tree, "selection_remove"):
        current = tuple(tree.selection())
        if current:
            tree.selection_remove(*current)
    try:
        tree.yview_moveto(y_fraction)
    except (AttributeError, TypeError, ValueError):
        pass
    return target


def aggregate_schedule_counts(views: Iterable[ScheduleView]) -> dict[str, int]:
    """メイン画面の集約表示に用いる件数を返す。"""

    counts = {
        "total": 0,
        "enabled": 0,
        "running": 0,
        "queued": 0,
        "repair": 0,
        "failed": 0,
        "update": 0,
    }
    for view in views:
        counts["total"] += 1
        counts["enabled"] += int(view.enabled)
        status = view.status
        state_value = schedule_value(status, "state", default="")
        state = str(getattr(state_value, "value", state_value) or "").lower()
        running = bool(schedule_value(status, "running", default=False))
        queued = bool(
            schedule_value(status, "queue_waiting", "queued", default=False)
        ) or state in {"queued", "queue_waiting", "waiting"}
        repair = bool(schedule_value(status, "repair_reason", default="")) or state in {
            "repair_required",
            "needs_repair",
        }
        update = bool(
            schedule_value(status, "definition_mismatch", default=False)
        ) or state in {"update_required", "needs_update"}
        last_result_value = schedule_value(status, "last_result", default="")
        last_result = str(
            getattr(last_result_value, "value", last_result_value) or ""
        ).lower()
        failed = state in {"last_failed", "failed"} or last_result in {
            "failed",
            "failure",
            "partial",
            "partial_failure",
            "error",
            "queue_timeout",
            "run_timeout",
            "config_invalid",
        }
        counts["running"] += int(running and not queued)
        counts["queued"] += int(queued)
        counts["repair"] += int(repair)
        counts["update"] += int(update)
        counts["failed"] += int(failed)
    return counts


def duplicate_condition_names(
    candidate: AppConfig,
    views: Iterable[ScheduleView],
    configs_by_id: Mapping[str, AppConfig],
    *,
    exclude_schedule_id: Optional[str] = None,
) -> list[str]:
    """検索・文書・保存条件が一致する別設定の表示名を返す。"""

    fingerprint = calculate_condition_fingerprint(candidate)
    duplicates: list[str] = []
    for view in views:
        if view.schedule_id == exclude_schedule_id:
            continue
        existing = configs_by_id.get(view.schedule_id) or view.config
        if not isinstance(existing, AppConfig):
            continue
        if calculate_condition_fingerprint(existing) == fingerprint:
            duplicates.append(view.name)
    return duplicates


def history_display_name(record: object, current_names: Mapping[str, str]) -> str:
    """削除済み定義も判別できる履歴上の表示名を返す。"""

    schedule_id = schedule_identifier(record, default="")
    recorded_name = str(
        schedule_value(
            record,
            "display_name",
            "name",
            "schedule_name",
            default="",
        )
        or ""
    )
    if schedule_id in current_names:
        return recorded_name or current_names[schedule_id]
    label = recorded_name or schedule_id or "不明"
    return f"削除済み設定: {label}"


def trigger_kind_display(value: object) -> str:
    raw = str(getattr(value, "value", value) or "").strip().lower()
    return {
        "scheduled": "定期実行",
        "task_scheduler": "定期実行",
        "windows_task": "Windowsタスク",
        "run_now": "今すぐ実行",
        "manual_gui": "今すぐ実行",
        "manual_cli": "CLI単発",
        "run_once": "CLI単発",
        "background": "旧互換実行",
    }.get(raw, str(value) if value not in {None, ""} else "-")


class ScheduleServiceAdapter:
    """新しい複数APIを優先し、旧単一APIへ安全にフォールバックする。"""

    def __init__(self, service: object) -> None:
        self.service = service
        # 複数の設定画面が同時に開かれても、古い一覧を基に上書きしないための
        # 楽観ロック値。list_views() のたびに台帳から取り直す。
        self.registry_revision: Optional[int] = None

    @property
    def supports_multiple(self) -> bool:
        return callable(getattr(self.service, "list_schedules", None))

    @staticmethod
    def _try_calls(calls: Iterable[tuple[object, tuple, dict]]) -> object:
        last_type_error: Optional[TypeError] = None
        for callable_object, args, kwargs in calls:
            if not callable(callable_object):
                continue
            try:
                signature = inspect.signature(callable_object)
            except (TypeError, ValueError):
                signature = None
            if signature is not None:
                try:
                    signature.bind(*args, **kwargs)
                except TypeError as exc:
                    last_type_error = exc
                    continue
                # 呼び出し本体のTypeErrorは実装エラーなので別シグネチャで
                # 再実行しない。mutationの二重適用を防ぐ。
                return callable_object(*args, **kwargs)
            try:
                return callable_object(*args, **kwargs)  # type: ignore[operator]
            except TypeError as exc:
                last_type_error = exc
        if last_type_error is not None:
            raise last_type_error
        raise AttributeError("対応する定期実行APIがありません")

    def _mutation_revision(self, expected_revision: Optional[int]) -> Optional[int]:
        return (
            self.registry_revision if expected_revision is None else expected_revision
        )

    def _run_mutation(self, calls: Iterable[tuple[object, tuple, dict]]) -> object:
        result = self._try_calls(calls)
        # 次の一覧再読込まで、古いrevisionを再利用しない。
        self.registry_revision = None
        return result

    def list_views(
        self, current_config: Optional[AppConfig] = None
    ) -> list[ScheduleView]:
        list_schedules = getattr(self.service, "list_schedules", None)
        if callable(list_schedules):
            get_registry = getattr(self.service, "get_registry", None)
            if callable(get_registry):
                registry = get_registry()
                revision = schedule_value(registry, "revision")
                self.registry_revision = int(revision) if revision is not None else None
            definitions = _as_list(list_schedules())
            statuses_method = getattr(self.service, "get_statuses", None) or getattr(
                self.service, "list_statuses", None
            )
            statuses: object = None
            if callable(statuses_method):
                calls = [
                    (statuses_method, (), {"current_configs": None}),
                    (statuses_method, (), {}),
                ]
                statuses = self._try_calls(calls)
            views = normalise_schedule_views(definitions, statuses)
            for view in views:
                if view.status is None:
                    view.status = self.status(view.schedule_id)
                else:
                    view.status = _overlay_queue_status(view.status, view.schedule_id)
            return views

        # 旧APIはdefault 1件として公開する。
        status = self.status(None, current_config=current_config)
        registered_config = self.registered_config(None)
        schedule = getattr(registered_config or current_config, "schedule", None)
        enabled = bool(
            schedule_value(
                status,
                "enabled",
                default=schedule_value(schedule, "enabled", default=False),
            )
        )
        schedule_id = schedule_identifier(status)
        if schedule_id == "default":
            schedule_id = str(
                schedule_value(schedule, "schedule_id", default="default") or "default"
            )
        return [
            ScheduleView(
                schedule_id=schedule_id,
                name=str(
                    schedule_value(
                        status,
                        "name",
                        "display_name",
                        default="既存の定期実行",
                    )
                    or "既存の定期実行"
                ),
                enabled=enabled,
                definition=None,
                status=_overlay_queue_status(status, schedule_id),
                config=registered_config,
            )
        ]

    def status(
        self,
        schedule_id: Optional[str],
        *,
        current_config: Optional[AppConfig] = None,
    ) -> object:
        method = getattr(self.service, "get_schedule_status", None)
        if callable(method) and schedule_id is not None:
            status = self._try_calls(
                [
                    (method, (schedule_id,), {"current_config": current_config}),
                    (method, (schedule_id,), {}),
                ]
            )
            return _overlay_queue_status(status, schedule_id)
        method = getattr(self.service, "get_status", None) or getattr(
            self.service, "status", None
        )
        status = self._try_calls(
            [
                (
                    method,
                    (),
                    {"config": current_config, "current_config": current_config},
                ),
                (method, (current_config,), {}),
                (method, (), {}),
            ]
        )
        return _overlay_queue_status(status, schedule_id or "default")

    def registered_config(self, schedule_id: Optional[str]) -> Optional[AppConfig]:
        methods = (
            getattr(self.service, "get_registered_config", None),
            getattr(self.service, "get_schedule_config", None),
            getattr(self.service, "get_snapshot_config", None),
        )
        for method in methods:
            if not callable(method):
                continue
            calls = []
            if schedule_id is not None:
                calls.append((method, (schedule_id,), {}))
            calls.append((method, (), {}))
            try:
                value = self._try_calls(calls)
            except (AttributeError, TypeError, KeyError):
                continue
            if isinstance(value, AppConfig):
                return deepcopy(value)
        if schedule_id is not None:
            getter = getattr(self.service, "get_schedule", None)
            if callable(getter):
                definition = getter(schedule_id)
                value = schedule_value(
                    definition, "config", "app_config", "snapshot_config"
                )
                if isinstance(value, AppConfig):
                    return deepcopy(value)
        return None

    def history(self, schedule_id: Optional[str], limit: int = 20) -> list[object]:
        method = getattr(self.service, "history_for_schedule", None)
        if callable(method) and schedule_id is not None:
            return list(
                self._try_calls(
                    [
                        (method, (schedule_id,), {"limit": limit}),
                        (method, (schedule_id, limit), {}),
                    ]
                )
                or []
            )
        method = getattr(self.service, "history", None) or getattr(
            self.service, "get_history", None
        )
        records = list(
            self._try_calls(
                [
                    (method, (), {"schedule_id": schedule_id, "limit": limit}),
                    (method, (), {"limit": limit}),
                    (method, (limit,), {}),
                ]
            )
            or []
        )
        if schedule_id and self.supports_multiple:
            records = [
                record
                for record in records
                if schedule_identifier(record, default="") == schedule_id
            ]
        return records[:limit]

    def run_now(self, schedule_id: Optional[str]) -> object:
        method = getattr(self.service, "run_schedule_now", None)
        if callable(method) and schedule_id is not None:
            return method(schedule_id)
        method = getattr(self.service, "run_now", None) or getattr(
            self.service, "run", None
        )
        return self._try_calls(
            [
                (method, (schedule_id,), {})
                if schedule_id is not None
                else (None, (), {}),
                (method, (), {}),
            ]
        )

    def create(
        self,
        name: str,
        config: AppConfig,
        *,
        expected_revision: Optional[int] = None,
    ) -> object:
        expected_revision = self._mutation_revision(expected_revision)
        method = getattr(self.service, "create_schedule", None)
        if callable(method):
            return self._run_mutation(
                [
                    (
                        method,
                        (config,),
                        {
                            "name": name,
                            "expected_revision": expected_revision,
                        },
                    ),
                    (method, (config,), {"name": name}),
                    (method, (name, config), {}),
                    (method, (), {"config": config, "name": name}),
                ]
            )
        # 旧APIでは唯一の登録を更新する。
        method = getattr(self.service, "register", None) or getattr(
            self.service, "update", None
        )
        result = method(config)
        self.registry_revision = None
        return result

    def update(
        self,
        schedule_id: str,
        name: str,
        config: AppConfig,
        *,
        expected_revision: Optional[int] = None,
    ) -> object:
        expected_revision = self._mutation_revision(expected_revision)
        method = getattr(self.service, "update_schedule", None)
        if callable(method):
            return self._run_mutation(
                [
                    (
                        method,
                        (schedule_id, config),
                        {
                            "name": name,
                            "expected_revision": expected_revision,
                        },
                    ),
                    (method, (schedule_id, config), {"name": name}),
                    (method, (schedule_id, name, config), {}),
                    (
                        method,
                        (),
                        {"schedule_id": schedule_id, "config": config, "name": name},
                    ),
                ]
            )
        return self.create(name, config, expected_revision=expected_revision)

    def migrate_storage_layout_v4(self) -> dict[str, object]:
        """管理中のv3定期実行を対象別保存レイアウトへ更新する。"""

        method = getattr(self.service, "migrate_storage_layout_v4", None)
        if not callable(method):
            return {
                "migrated": (),
                "unchanged": (),
                "failed": {"*": "定期実行の保存レイアウト更新に未対応です"},
            }
        result = method()
        self.registry_revision = None
        return dict(result or {})

    def duplicate(
        self,
        schedule_id: str,
        name: str,
        *,
        expected_revision: Optional[int] = None,
    ) -> object:
        expected_revision = self._mutation_revision(expected_revision)
        method = getattr(self.service, "duplicate_schedule", None)
        if not callable(method):
            raise AttributeError("定期実行条件の複製機能がありません")
        return self._run_mutation(
            [
                (
                    method,
                    (schedule_id,),
                    {"name": name, "expected_revision": expected_revision},
                ),
                (method, (schedule_id,), {"name": name}),
                (method, (schedule_id, name), {}),
                (method, (), {"source_id": schedule_id, "name": name}),
            ]
        )

    def delete(
        self,
        schedule_id: str,
        *,
        expected_revision: Optional[int] = None,
    ) -> object:
        expected_revision = self._mutation_revision(expected_revision)
        method = getattr(self.service, "delete_schedule", None)
        if callable(method):
            return self._run_mutation(
                [
                    (
                        method,
                        (schedule_id,),
                        {"expected_revision": expected_revision},
                    ),
                    (method, (schedule_id,), {}),
                ]
            )
        method = getattr(self.service, "unregister", None) or getattr(
            self.service, "delete", None
        )
        return self._run_mutation([(method, (), {}), (method, (schedule_id,), {})])

    def set_enabled(
        self,
        schedule_id: str,
        enabled: bool,
        *,
        expected_revision: Optional[int] = None,
    ) -> object:
        expected_revision = self._mutation_revision(expected_revision)
        method = getattr(self.service, "set_enabled", None)
        if callable(method):
            return self._run_mutation(
                [
                    (
                        method,
                        (schedule_id, enabled),
                        {"expected_revision": expected_revision},
                    ),
                    (method, (schedule_id, enabled), {}),
                ]
            )
        method_name = "enable_schedule" if enabled else "disable_schedule"
        method = getattr(self.service, method_name, None)
        if callable(method):
            return self._run_mutation(
                [
                    (
                        method,
                        (schedule_id,),
                        {"expected_revision": expected_revision},
                    ),
                    (method, (schedule_id,), {}),
                ]
            )
        if not enabled:
            return self.delete(schedule_id)
        config = self.registered_config(schedule_id)
        if config is None:
            raise AttributeError("有効化に使用する登録済み条件がありません")
        config.schedule.enabled = True
        return self.create(
            schedule_id,
            config,
            expected_revision=expected_revision,
        )

    def repair(
        self,
        schedule_id: str,
        *,
        expected_revision: Optional[int] = None,
    ) -> object:
        expected_revision = self._mutation_revision(expected_revision)
        method = getattr(self.service, "repair_schedule", None)
        if callable(method):
            return self._run_mutation(
                [
                    (
                        method,
                        (schedule_id,),
                        {"expected_revision": expected_revision},
                    ),
                    (method, (schedule_id,), {}),
                ]
            )
        config = self.registered_config(schedule_id)
        if config is None:
            raise AttributeError("修復に使用する登録済み条件がありません")
        return self.update(
            schedule_id,
            schedule_id,
            config,
            expected_revision=expected_revision,
        )

    def external_candidates(
        self,
        source_config_dir: Optional[str | Path] = None,
    ) -> list[object]:
        """管理外タスクまたは指定した旧configの移行候補を検査する。"""

        methods = (
            getattr(self.service, "preview_external_imports", None),
            getattr(self.service, "list_external_schedule_candidates", None),
            getattr(self.service, "discover_external_schedules", None),
        )
        for method in methods:
            if not callable(method):
                continue
            calls: list[tuple[object, tuple, dict]] = []
            if source_config_dir is not None:
                calls.extend(
                    [
                        (method, (Path(source_config_dir),), {}),
                        (method, (), {"source_config_dir": Path(source_config_dir)}),
                    ]
                )
            calls.append((method, (), {}))
            try:
                return _as_list(self._try_calls(calls))
            except TypeError:
                continue
        raise AttributeError("旧定期実行設定の検査機能がありません")

    def import_external(
        self,
        external_id: str,
        *,
        source_config_dir: Optional[str | Path] = None,
        name: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> object:
        expected_revision = self._mutation_revision(expected_revision)
        methods = (
            getattr(self.service, "import_external_schedule", None),
            getattr(self.service, "import_legacy_schedule", None),
        )
        for method in methods:
            if not callable(method):
                continue
            kwargs: dict[str, object] = {"expected_revision": expected_revision}
            if source_config_dir is not None:
                kwargs["source_config_dir"] = Path(source_config_dir)
            target_kwargs = dict(kwargs)
            legacy_kwargs = dict(kwargs)
            if name is not None:
                target_kwargs["target_name"] = name
                legacy_kwargs["name"] = name
            calls = [
                (method, (external_id,), target_kwargs),
                (method, (external_id,), legacy_kwargs),
                (method, (external_id,), {"expected_revision": expected_revision}),
                (method, (external_id,), {}),
            ]
            return self._run_mutation(calls)
        raise AttributeError("旧定期実行設定の取り込み機能がありません")

    def remove_external(self, external_id: str) -> object:
        method = getattr(self.service, "remove_external_task", None) or getattr(
            self.service, "delete_external_task", None
        )
        if not callable(method):
            raise AttributeError("管理外Windowsタスクの解除機能がありません")
        return self._run_mutation([(method, (external_id,), {})])


__all__ = [
    "ScheduleServiceAdapter",
    "ScheduleTreeRow",
    "ScheduleView",
    "aggregate_schedule_counts",
    "duplicate_condition_names",
    "format_storage_preview",
    "history_display_name",
    "normalise_schedule_views",
    "reconcile_schedule_tree",
    "schedule_identifier",
    "schedule_value",
    "snapshot_identifier",
    "trigger_kind_display",
]
