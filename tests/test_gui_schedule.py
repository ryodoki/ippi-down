# -*- coding: utf-8 -*-

"""Windowsタスク定期実行GUIのheadless回帰テスト。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.main_window import (
    MainWindow,
    _format_schedule_result,
    _schedule_status_presentation,
)
from src.gui.schedule_editor_dialog import (
    ScheduleEditorDialog,
    format_schedule_notification_policy,
    normalise_schedule_notification_policy,
)
from src.gui.schedule_management import (
    ScheduleServiceAdapter,
    ScheduleTreeRow,
    ScheduleView,
    aggregate_schedule_counts,
    duplicate_condition_names,
    format_storage_preview,
    history_display_name,
    normalise_schedule_views,
    reconcile_schedule_tree,
    trigger_kind_display,
)
from src.storage.layout import RunKind
from src.gui.search_conditions_form import (
    DynamicOptionRequestToken,
    SearchConditionOptionModel,
    normalise_search_options,
    validate_search_condition_structure,
)
from src.gui.settings_dialog import (
    SettingsDialog,
    format_schedule_condition_summary,
    format_schedule_reason,
)
from src.models.config_model import AppConfig, ScheduleConfig, SearchConditions
from src.models.search_target import SearchTarget
from src.scheduler import (
    ScheduledRunRecord,
    ScheduleServiceError,
    ScheduleRegistrationStatus,
    ScheduleState,
)
from src.scheduler.service import ScheduleService
from src.scheduler.task_scheduler import TaskQueryResult


class _Variable:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Widget:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)

    config = configure


class _TextValue:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value


class _Tree:
    def __init__(self, rows=(), selection=(), focus="", yview=(0.25, 0.75)):
        self.rows = {
            item_id: {"values": values, "tags": ()} for item_id, values in rows
        }
        self.order = [item_id for item_id, _values in rows]
        self._selection = tuple(selection)
        self._focus = focus
        self._yview = yview
        self.deleted = []

    def selection(self):
        return self._selection

    def focus(self, value=None):
        if value is not None:
            self._focus = value
        return self._focus

    def yview(self):
        return self._yview

    def yview_moveto(self, value):
        self._yview = (value, self._yview[1])

    def get_children(self):
        return tuple(self.order)

    def exists(self, item_id):
        return item_id in self.rows

    def delete(self, item_id):
        self.deleted.append(item_id)
        self.order.remove(item_id)
        self.rows.pop(item_id)

    def item(self, item_id, **kwargs):
        self.rows[item_id].update(kwargs)

    def move(self, item_id, _parent, index):
        self.order.remove(item_id)
        self.order.insert(index, item_id)

    def insert(self, _parent, _where, *, iid, values, tags):
        self.rows[iid] = {"values": values, "tags": tags}
        self.order.append(iid)

    def selection_set(self, item_id):
        self._selection = (item_id,)

    def selection_remove(self, *item_ids):
        self._selection = tuple(
            item for item in self._selection if item not in item_ids
        )

    def see(self, _item_id):
        return None

    def tag_configure(self, *_args, **_kwargs):
        return None


def test_schedule_condition_summary_contains_registration_scope():
    config = AppConfig(
        search_conditions=SearchConditions(
            hachu_daibunrui="国の機関",
            hachu_chubunrui="関東地方整備局",
            koji_name="橋梁",
            place_search_type="list",
            place_chihou="関東",
            place_todofuken="東京都",
            koji_shubetsu="一般土木",
            koukai=True,
        )
    )
    config.save_paths.local = r"C:\downloads"
    config.download_conditions.keywords = ["仕様書", "図面"]
    config.download_conditions.date_range = {
        "start": "2026-08-01",
        "end": "2026-08-31",
    }
    config.naming_rule = "{project_name}_{document_name}"

    summary = format_schedule_condition_summary(config)

    assert "発注機関: 国の機関 / 関東地方整備局" in summary
    assert "工事名: 橋梁" in summary
    assert "場所: 関東 / 東京都" in summary
    assert "公開条件: 公開中のみ" in summary
    assert r"保存先: C:\downloads" in summary
    assert "キーワード: 仕様書、図面" in summary
    assert "文書日付範囲:" in summary
    assert "命名規則: {project_name}_{document_name}" in summary


def test_schedule_notification_policy_display_is_backward_compatible():
    assert normalise_schedule_notification_policy(None) == "off"
    assert normalise_schedule_notification_policy("IMPORTANT_ONLY") == (
        "important_only"
    )
    assert normalise_schedule_notification_policy(
        "すべての実行結果"
    ) == "all_results"
    assert format_schedule_notification_policy("failures_only") == "失敗時のみ"
    assert format_schedule_notification_policy("unknown-legacy-value") == (
        "通知しない"
    )


def test_storage_preview_separates_manual_and_scheduled_roots():
    config = AppConfig()
    config.save_paths.local = r"C:\ippi-data"

    assert format_storage_preview(config, RunKind.MANUAL) == (
        r"C:\ippi-data\工事の検索（入札の経過）\01_通常ダウンロード"
    )
    assert format_storage_preview(config, RunKind.SCHEDULED) == (
        r"C:\ippi-data\工事の検索（入札の経過）\02_定期実行\<登録時に自動割当>"
    )

    config.save_paths.schedule_storage_key = "S007"
    config.save_paths.schedule_storage_folder = "S007_道路案件"
    assert format_storage_preview(config, RunKind.SCHEDULED) == (
        r"C:\ippi-data\工事の検索（入札の経過）\02_定期実行\S007_道路案件"
    )

    config.search_conditions = SearchConditions.for_target(
        SearchTarget.GYOMU_KEIKA
    )
    assert format_storage_preview(config, RunKind.MANUAL) == (
        r"C:\ippi-data\業務の検索（入札の経過）\01_通常ダウンロード"
    )


def test_storage_layout_v3_requires_confirmation_before_v4(monkeypatch):
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.dialog = object()
    config = AppConfig()
    config.save_paths.layout_version = 3
    confirmations = []
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.askyesno",
        lambda *args, **kwargs: confirmations.append((args, kwargs)) or True,
    )

    upgraded = dialog._confirm_storage_layout_v4(config)

    assert upgraded
    assert config.save_paths.layout_version == 4
    assert len(confirmations) == 1


def test_storage_layout_v3_decline_keeps_existing_layout(monkeypatch):
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.dialog = object()
    config = AppConfig()
    config.save_paths.layout_version = 3
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.askyesno",
        lambda *args, **kwargs: False,
    )

    upgraded = dialog._confirm_storage_layout_v4(config)

    assert not upgraded
    assert config.save_paths.layout_version == 3


def test_schedule_status_presentation_covers_user_visible_states():
    assert _schedule_status_presentation(None)[0] == "無効"
    assert (
        _schedule_status_presentation(
            ScheduleRegistrationStatus(state=ScheduleState.REGISTERED, registered=True)
        )[0]
        == "登録済み"
    )
    assert (
        _schedule_status_presentation(
            ScheduleRegistrationStatus(
                state=ScheduleState.UPDATE_REQUIRED,
                registered=True,
                definition_mismatch=True,
            )
        )[0]
        == "要更新"
    )
    assert (
        _schedule_status_presentation(
            ScheduleRegistrationStatus(
                state=ScheduleState.REPAIR_REQUIRED,
                repair_reason="実行ファイルがありません",
            )
        )[0]
        == "要修復"
    )
    assert (
        _schedule_status_presentation(
            ScheduleRegistrationStatus(
                state=ScheduleState.RUNNING, registered=True, running=True
            )
        )[0]
        == "実行中"
    )
    assert (
        _schedule_status_presentation(
            SimpleNamespace(
                state="retry_waiting",
                registered=True,
                retry_waiting=True,
            )
        )[0]
        == "再試行待機中"
    )
    assert (
        SettingsDialog._status_presentation(
            SimpleNamespace(
                state="retry_waiting",
                registered=True,
                retry_waiting=True,
            )
        )[0]
        == "再試行待機中"
    )
    assert (
        _schedule_status_presentation(
            ScheduleRegistrationStatus(
                state=ScheduleState.LAST_FAILED,
                registered=True,
                last_result="failed",
            )
        )[0]
        == "前回失敗"
    )


def test_main_status_shows_unapplied_condition_change_and_counts():
    window = MainWindow.__new__(MainWindow)
    window.config = AppConfig()
    window._schedule_status_query_running = True
    window.schedule_status_var = _Variable()
    window.schedule_status_label = _Widget()
    window.schedule_timing_var = _Variable()
    window.schedule_counts_var = _Variable()
    window.schedule_warning_var = _Variable()
    window.btn_schedule_run_now = _Widget()
    status = ScheduleRegistrationStatus(
        state=ScheduleState.UPDATE_REQUIRED,
        registered=True,
        definition_mismatch=True,
        next_run=datetime(2026, 8, 4, 9, 0),
    )
    record = ScheduledRunRecord(
        profile_id="profile-1",
        started_at=datetime(2026, 8, 3, 9, 0),
        finished_at=datetime(2026, 8, 3, 9, 5),
        result="success",
        new_count=3,
        existing_count=7,
        failed_count=1,
    )

    window._apply_schedule_status(status, record)

    assert window.schedule_status_var.get() == "要更新"
    assert window.schedule_warning_var.get() == ("定期実行に未反映の変更があります")
    assert window.schedule_counts_var.get() == (
        "新規保存: 3 / 保存済み確認: 7 / 失敗: 1"
    )
    assert window.btn_schedule_run_now.options["state"] == "normal"


def test_main_status_shows_background_requirements_for_selected_schedule():
    window = MainWindow.__new__(MainWindow)
    window.config = AppConfig()
    window._multiple_schedule_mode = True
    window._selected_schedule_id = "nightly"
    schedule = ScheduleConfig(
        enabled=True,
        wake_to_run=True,
        notification_policy="all_results",
    )
    view = ScheduleView(
        "nightly",
        "夜間取得",
        True,
        definition=SimpleNamespace(schedule=schedule),
        status=ScheduleRegistrationStatus(registered=True, enabled=True),
    )
    window._schedule_views_by_id = {"nightly": view}
    window.schedule_status_var = _Variable()
    window.schedule_status_label = _Widget()
    window.schedule_timing_var = _Variable()
    window.schedule_counts_var = _Variable()
    window.schedule_runtime_var = _Variable()
    window.schedule_warning_var = _Variable()
    window.btn_schedule_run_now = _Widget()

    window._apply_schedule_status(view.status, arm_poll=False)

    assert "GUI終了後も実行可" in window.schedule_runtime_var.get()
    assert "Windowsへのログオンが必要" in window.schedule_runtime_var.get()
    assert "スリープ解除: ON" in window.schedule_runtime_var.get()
    assert "完了通知: すべての実行結果" in window.schedule_runtime_var.get()


def test_multi_schedule_status_does_not_compare_main_screen_conditions():
    window = MainWindow.__new__(MainWindow)
    window.config = AppConfig()
    window._multiple_schedule_mode = True
    window.schedule_status_var = _Variable()
    window.schedule_status_label = _Widget()
    window.schedule_timing_var = _Variable()
    window.schedule_counts_var = _Variable()
    window.schedule_warning_var = _Variable()
    window.btn_schedule_run_now = _Widget()
    status = ScheduleRegistrationStatus(
        state=ScheduleState.UPDATE_REQUIRED,
        registered=True,
        definition_mismatch=True,
    )

    window._apply_schedule_status(status, arm_poll=False)

    assert window.schedule_warning_var.get() == ""


def test_multi_status_worker_keeps_batch_status_authoritative():
    received = []

    def get_schedule_status(schedule_id, *, current_config=None):
        received.append((schedule_id, current_config))
        return SimpleNamespace(schedule_id=schedule_id, registered=True)

    service = SimpleNamespace(
        list_schedules=lambda: [
            SimpleNamespace(schedule_id="job", name="保存条件", enabled=True)
        ],
        get_statuses=lambda current_configs=None: {
            "job": SimpleNamespace(schedule_id="job", registered=True)
        },
        get_schedule_status=get_schedule_status,
        history_for_schedule=lambda schedule_id, limit=20: [],
    )
    window = MainWindow.__new__(MainWindow)
    window.event_handler = SimpleNamespace(call_soon=Mock())

    window._query_schedule_status_worker(service, AppConfig(), "job", 1)

    assert received == []


def test_schedule_tree_reconcile_updates_in_place_and_keeps_selection_and_scroll():
    tree = _Tree(
        rows=(("a", ("old-a",)), ("b", ("old-b",))),
        selection=("b",),
        focus="b",
    )

    selected = reconcile_schedule_tree(
        tree,
        (
            ScheduleTreeRow("a", ("new-a",)),
            ScheduleTreeRow("b", ("new-b",)),
        ),
        selected_id="b",
    )

    assert selected == "b"
    assert tree.deleted == []
    assert tree.order == ["a", "b"]
    assert tree.rows["a"]["values"] == ("new-a",)
    assert tree.selection() == ("b",)
    assert tree.focus() == "b"
    assert tree.yview()[0] == 0.25


def test_schedule_tree_reconcile_has_stable_order_when_rows_change():
    tree = _Tree(
        rows=(("b", ("b",)), ("removed", ("old",)), ("a", ("a",))),
        selection=("a",),
        focus="a",
    )

    reconcile_schedule_tree(
        tree,
        (
            ScheduleTreeRow("a", ("a2",)),
            ScheduleTreeRow("b", ("b2",)),
            ScheduleTreeRow("c", ("c",)),
        ),
        selected_id="a",
    )

    assert tree.order == ["a", "b", "c"]
    assert tree.deleted == ["removed"]
    assert tree.selection() == ("a",)


def test_main_schedule_selection_loads_detail_without_refreshing_list():
    window = MainWindow.__new__(MainWindow)
    window.schedule_tree = _Tree(
        rows=(("a", ("a",)), ("b", ("b",))), selection=("b",), focus="b"
    )
    window._selected_schedule_id = "a"
    view = ScheduleView("b", "B", True, status=SimpleNamespace(registered=True))
    window._schedule_views_by_id = {"b": view}
    window._last_schedule_records = []
    window._apply_schedule_status = Mock()
    window._request_schedule_detail_refresh = Mock()
    window.request_schedule_status_refresh = Mock()

    window._on_schedule_tree_selected()

    assert window._selected_schedule_id == "b"
    window._request_schedule_detail_refresh.assert_called_once_with("b")
    window.request_schedule_status_refresh.assert_not_called()


def test_main_schedule_poll_is_suspended_while_settings_owns_status_refresh():
    window = MainWindow.__new__(MainWindow)
    window.root = SimpleNamespace(after_cancel=Mock())
    window._closing = False
    window._schedule_poll_after_id = "after-1"
    window.request_schedule_status_refresh = Mock()

    MainWindow._suspend_schedule_status_poll(window)

    assert window._schedule_poll_suspended is True
    assert window._schedule_poll_after_id is None
    window.root.after_cancel.assert_called_once_with("after-1")

    MainWindow._resume_schedule_status_poll(window)

    assert window._schedule_poll_suspended is False
    window.request_schedule_status_refresh.assert_called_once_with()


def test_suspended_main_schedule_poll_does_not_start_query_or_timer():
    window = MainWindow.__new__(MainWindow)
    window._closing = False
    window._schedule_poll_suspended = True
    window._schedule_refresh_generation = 7
    window.root = SimpleNamespace(after=Mock())

    MainWindow.request_schedule_status_refresh(window)
    MainWindow._arm_schedule_status_poll(window, 5000)

    assert window._schedule_refresh_generation == 7
    window.root.after.assert_not_called()


def test_settings_schedule_selection_uses_separate_detail_generation():
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.schedule_manager_tree = _Tree(rows=(("b", ("b",)),), selection=("b",))
    dialog.external_schedule_tree = _Tree()
    dialog._selected_schedule_id = "a"
    config = AppConfig()
    view = ScheduleView("b", "B", True, config=config)
    dialog._schedule_views_by_id = {"b": view}
    dialog._schedule_configs_by_id = {"b": config}
    dialog._update_multi_schedule_detail = Mock()
    dialog._populate_schedule_history = Mock()
    dialog._history_records_for_filter = Mock(return_value=[])
    dialog._update_multi_schedule_action_state = Mock()
    dialog._request_multi_schedule_detail_refresh = Mock()
    dialog.request_multi_schedule_refresh = Mock()

    dialog._on_multi_schedule_selected()

    assert dialog._selected_schedule_id == "b"
    dialog._request_multi_schedule_detail_refresh.assert_called_once_with("b")
    dialog.request_multi_schedule_refresh.assert_not_called()


def test_settings_schedule_detail_shows_background_and_notification_policy():
    dialog = SettingsDialog.__new__(SettingsDialog)
    config = AppConfig(
        schedule=ScheduleConfig(
            enabled=True,
            wake_to_run=False,
            notification_policy="important_only",
        )
    )
    view = ScheduleView(
        "job",
        "東北トンネル",
        True,
        definition=SimpleNamespace(schedule=config.schedule),
        status=SimpleNamespace(
            task_name=r"\ippi-down\Download-job",
            registered=True,
        ),
        config=config,
    )
    dialog._schedule_views_by_id = {"job": view}
    dialog.schedule_condition_var = _Variable()

    dialog._update_multi_schedule_detail("job", config)

    detail = dialog.schedule_condition_var.get()
    assert "GUI終了後も実行可" in detail
    assert "Windowsへのログオンが必要" in detail
    assert "スリープ解除: OFF" in detail
    assert "完了通知: 重要な結果のみ" in detail


def test_list_response_does_not_revert_newer_settings_selection():
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog._schedule_manager_query_running = True
    dialog._schedule_manager_generation = 1
    dialog._schedule_manager_refresh_pending = False
    dialog._schedule_manager_action_running = False
    dialog._schedule_manager_refresh_after_id = None
    dialog._selected_schedule_id = "b"
    dialog._selected_external_schedule_id = None
    dialog._schedule_selected_history = ["newer-b-history"]
    dialog._schedule_all_history = []
    dialog._schedule_views = []
    dialog._schedule_views_by_id = {}
    dialog._external_schedule_views_by_id = {}
    dialog._schedule_configs_by_id = {}
    dialog.schedule_manager_tree = _Tree(
        rows=(("a", ("a",)), ("b", ("b",))), selection=("b",), focus="b"
    )
    dialog.external_schedule_tree = _Tree()
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = SimpleNamespace(after=Mock(), after_cancel=Mock())
    dialog._update_multi_schedule_detail = Mock()
    dialog._populate_schedule_history = Mock()
    dialog._history_records_for_filter = Mock(return_value=[])
    dialog._update_multi_schedule_action_state = Mock()
    views = [
        ScheduleView("a", "A", True, status=SimpleNamespace(registered=True)),
        ScheduleView("b", "B", True, status=SimpleNamespace(registered=True)),
    ]

    dialog._apply_multi_schedule_refresh(
        1,
        views,
        "a",
        AppConfig(),
        {"a": AppConfig(), "b": AppConfig()},
        ["old-a-history"],
        [],
        None,
    )

    assert dialog._selected_schedule_id == "b"
    assert dialog.schedule_manager_tree.selection() == ("b",)
    assert dialog._schedule_selected_history == ["newer-b-history"]


def test_external_schedule_origin_and_capabilities_are_not_repairable():
    view = ScheduleView(
        "external-abc",
        "旧CLIタスク",
        True,
        status=SimpleNamespace(
            origin="external_task",
            reason_code="EXTERNAL_TASK_IMPORTABLE",
            capabilities=SimpleNamespace(
                can_edit=False,
                can_repair=False,
                can_run=False,
                can_delete=False,
                can_import=True,
                can_remove_external=True,
            ),
        ),
    )

    assert view.is_external is True
    assert view.allows("repair") is False
    assert view.allows("run") is False
    assert view.allows("import") is True
    assert view.allows("remove_external") is True


def test_schedule_adapter_supports_config_folder_preview_import_and_remove(tmp_path):
    calls = []
    candidate = SimpleNamespace(external_id="external-abc", importable=True)

    def list_candidates(source_config_dir=None):
        calls.append(("preview", source_config_dir))
        return [candidate]

    def import_external(
        external_id,
        *,
        source_config_dir=None,
        expected_revision=None,
        target_name=None,
    ):
        calls.append(
            (
                "import",
                external_id,
                source_config_dir,
                expected_revision,
                target_name,
            )
        )
        return True

    def remove_external(external_id):
        calls.append(("remove", external_id))
        return True

    adapter = ScheduleServiceAdapter(
        SimpleNamespace(
            list_external_schedule_candidates=list_candidates,
            import_external_schedule=import_external,
            remove_external_task=remove_external,
        )
    )
    adapter.registry_revision = 9

    assert adapter.external_candidates(tmp_path) == [candidate]
    assert (
        adapter.import_external(
            "external-abc", source_config_dir=tmp_path, name="移行後"
        )
        is True
    )
    assert adapter.remove_external("external-abc") is True
    assert calls == [
        ("preview", tmp_path),
        ("import", "external-abc", tmp_path, 9, "移行後"),
        ("remove", "external-abc"),
    ]


def test_schedule_modal_dynamic_validation_is_not_tied_to_main_selection():
    window = MainWindow.__new__(MainWindow)
    config = AppConfig()
    config.search_conditions.hachu_daibunrui = "別の大分類"
    config.search_conditions.hachu_chubunrui = "別の中分類"

    valid, errors = window._validate_schedule_profile_dynamic_config(config)

    assert valid is True
    assert errors == []


def test_main_status_uses_history_for_active_profile_only():
    status = ScheduleRegistrationStatus(registered=True, profile_id="current")
    old = ScheduledRunRecord(profile_id="old", result="failed")
    current = ScheduledRunRecord(profile_id="current", result="success")

    assert MainWindow._record_for_schedule_status(status, [old, current]) is current


def test_registration_snapshot_rejects_dynamic_selection_error():
    window = MainWindow.__new__(MainWindow)
    window._pending_option_loads = 0
    window._validate_dynamic_search_selections = Mock(
        return_value="工事種別「旧候補」は現在の候補にありません"
    )
    window.get_config_from_ui = Mock(return_value=AppConfig())
    window.config_manager = Mock()

    with pytest.raises(ValueError, match="現在の候補にありません"):
        window._current_schedule_registration_config()

    window.get_config_from_ui.assert_not_called()


def test_registration_snapshot_does_not_fallback_on_input_error():
    window = MainWindow.__new__(MainWindow)
    window._pending_option_loads = 0
    window._validate_dynamic_search_selections = Mock(return_value="")
    window.get_config_from_ui = Mock(
        side_effect=ValueError("予定価格の下限は整数で指定してください")
    )
    window.config = AppConfig()
    window.config_manager = Mock()

    with pytest.raises(ValueError, match="予定価格の下限"):
        window._current_schedule_registration_config()


def test_schedule_reason_includes_japanese_text_and_stable_code():
    assert format_schedule_reason("NETWORK_TIMEOUT") == (
        "通信タイムアウト [NETWORK_TIMEOUT]"
    )
    assert format_schedule_reason("CUSTOM_CODE") == (
        "実行結果の詳細はログを確認 [CUSTOM_CODE]"
    )
    assert format_schedule_reason("QUEUE_TIMEOUT") == (
        "キュー待機時間超過 [QUEUE_TIMEOUT]"
    )
    assert _format_schedule_result("queue_timeout") == "キュー待機時間超過"


def test_settings_status_displays_last_failure():
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.config = AppConfig()
    dialog._get_schedule_status = Mock(
        return_value=ScheduleRegistrationStatus(
            state=ScheduleState.LAST_FAILED,
            registered=True,
            last_result="failed",
        )
    )
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog._refresh_schedule_history = Mock()
    dialog.logger = Mock()

    dialog.refresh_schedule_status()

    assert dialog.schedule_registration_var.get().startswith("前回失敗")
    assert dialog.schedule_registration_label.options["foreground"] == ("#cf222e")


def test_disabled_legacy_backend_is_preserved_until_explicit_enable():
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.config = AppConfig(
        schedule=ScheduleConfig(
            enabled=False,
            backend="legacy_process",
        )
    )

    assert dialog._schedule_backend_for_save(False) == "legacy_process"
    assert dialog._schedule_backend_for_save(True) == ("windows_task_scheduler")


def test_settings_save_registers_current_main_search_snapshot(monkeypatch):
    original = AppConfig(schedule=ScheduleConfig(enabled=False))
    edited = deepcopy(original)
    edited.schedule.enabled = True
    current = deepcopy(original)
    current.search_conditions.koji_name = "画面で変更した工事名"
    registered = {}

    class _Service:
        def get_status(self, *args, **kwargs):
            return ScheduleRegistrationStatus()

        def register(self, config):
            registered["config"] = deepcopy(config)
            return ScheduleRegistrationStatus(
                state=ScheduleState.REGISTERED,
                registered=True,
                next_run=datetime(2026, 8, 4, 9, 0),
                profile_id="profile-new",
            )

    manager = SimpleNamespace(
        validate_config=lambda config: (True, []),
        save_config=Mock(return_value=True),
    )
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.config = original
    dialog.config_manager = manager
    dialog.schedule_service = _Service()
    dialog.current_config_provider = lambda: current
    dialog.get_config_from_ui = Mock(return_value=edited)
    dialog.validate_config = Mock(return_value=(True, []))
    dialog._schedule_profile_config = deepcopy(original)
    dialog.schedule_condition_var = _Variable()
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = SimpleNamespace(destroy=Mock())
    dialog.logger = Mock()
    dialog.result = None
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.askyesno", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showinfo", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showerror", lambda *a, **k: None
    )

    dialog.on_save()

    assert registered["config"].search_conditions.koji_name == ("画面で変更した工事名")
    assert registered["config"].schedule.backend == ("windows_task_scheduler")
    assert dialog.result.schedule.active_profile_id == "profile-new"
    manager.save_config.assert_called_once()
    dialog.dialog.destroy.assert_called_once()


def test_settings_does_not_register_when_visible_search_input_is_invalid(
    monkeypatch,
):
    original = AppConfig(schedule=ScheduleConfig(enabled=False))
    edited = deepcopy(original)
    edited.schedule.enabled = True
    register = Mock()
    manager = SimpleNamespace(
        validate_config=lambda config: (True, []),
        save_config=Mock(return_value=True),
    )
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.config = original
    dialog.config_manager = manager
    dialog.schedule_service = SimpleNamespace(
        get_status=lambda *a, **k: ScheduleRegistrationStatus(),
        register=register,
    )
    dialog.current_config_provider = Mock(
        side_effect=ValueError("予定価格の下限は整数で指定してください")
    )
    dialog.get_config_from_ui = Mock(return_value=edited)
    dialog.validate_config = Mock(return_value=(True, []))
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = SimpleNamespace(destroy=Mock())
    dialog.logger = Mock()
    dialog.result = None
    errors = []
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showerror",
        lambda *args, **kwargs: errors.append(args),
    )

    dialog.on_save()

    register.assert_not_called()
    manager.save_config.assert_not_called()
    dialog.dialog.destroy.assert_not_called()
    assert "予定価格の下限" in errors[0][1]


def test_disable_does_not_save_when_windows_task_delete_fails(monkeypatch):
    original = AppConfig(schedule=ScheduleConfig(enabled=True))
    edited = deepcopy(original)
    edited.schedule.enabled = False

    class _Service:
        def get_status(self, *args, **kwargs):
            return ScheduleRegistrationStatus(
                state=ScheduleState.REGISTERED, registered=True
            )

        def unregister(self):
            return False

    manager = SimpleNamespace(save_config=Mock(return_value=True))
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.config = original
    dialog.config_manager = manager
    dialog.schedule_service = _Service()
    dialog.get_config_from_ui = Mock(return_value=edited)
    dialog.validate_config = Mock(return_value=(True, []))
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = SimpleNamespace(destroy=Mock())
    dialog.logger = Mock()
    dialog.result = None
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showerror", lambda *a, **k: None
    )

    dialog.on_save()

    manager.save_config.assert_not_called()
    dialog.dialog.destroy.assert_not_called()
    assert "TASK_DELETE_FAILED" in dialog.schedule_registration_var.get()


def test_disable_cleans_registration_metadata_when_task_is_missing(monkeypatch):
    original = AppConfig(schedule=ScheduleConfig(enabled=True))
    edited = deepcopy(original)
    edited.schedule.enabled = False
    unregister = Mock(return_value=True)

    class _Service:
        def get_status(self, *args, **kwargs):
            return ScheduleRegistrationStatus(
                state=ScheduleState.REPAIR_REQUIRED,
                registered=False,
                repair_reason="登録済みWindowsタスクが見つかりません",
                reason_code="TASK_NOT_FOUND",
                profile_id="profile-old",
            )

        def unregister(self):
            return unregister()

    manager = SimpleNamespace(save_config=Mock(return_value=True))
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.config = original
    dialog.config_manager = manager
    dialog.schedule_service = _Service()
    dialog.get_config_from_ui = Mock(return_value=edited)
    dialog.validate_config = Mock(return_value=(True, []))
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = SimpleNamespace(destroy=Mock())
    dialog.logger = Mock()
    dialog.result = None
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showinfo", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showerror", lambda *a, **k: None
    )

    dialog.on_save()

    unregister.assert_called_once()
    manager.save_config.assert_called_once()
    assert dialog.result.schedule.enabled is False
    assert dialog.result.schedule.active_profile_id is None


def test_config_save_failure_restores_exact_registration_backup(monkeypatch):
    original = AppConfig(schedule=ScheduleConfig(enabled=False))
    edited = deepcopy(original)
    edited.schedule.enabled = True
    backup = {"opaque": "previous-task-and-profile"}
    restore = Mock()

    class _Service:
        def get_status(self, *args, **kwargs):
            return ScheduleRegistrationStatus()

        def capture_registration_state(self):
            return backup

        def restore_registration_state(self, state):
            restore(state)

        def register(self, config):
            return ScheduleRegistrationStatus(
                state=ScheduleState.REGISTERED,
                registered=True,
                profile_id="profile-new",
            )

    manager = SimpleNamespace(
        validate_config=lambda config: (True, []),
        save_config=Mock(return_value=False),
    )
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.config = original
    dialog.config_manager = manager
    dialog.schedule_service = _Service()
    dialog.current_config_provider = lambda: deepcopy(original)
    dialog.get_config_from_ui = Mock(return_value=edited)
    dialog.validate_config = Mock(return_value=(True, []))
    dialog.schedule_condition_var = _Variable()
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = SimpleNamespace(destroy=Mock())
    dialog.logger = Mock()
    dialog.result = None
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.askyesno", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showerror", lambda *a, **k: None
    )

    dialog.on_save()

    restore.assert_called_once_with(backup)
    dialog.dialog.destroy.assert_not_called()


def test_registered_condition_summary_uses_immutable_profile():
    current = AppConfig()
    current.search_conditions.koji_name = "画面で変更中"
    registered = AppConfig()
    registered.search_conditions.koji_name = "登録済み条件"
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.schedule_service = SimpleNamespace(get_registered_config=lambda: registered)
    dialog.schedule_condition_var = _Variable()
    dialog._schedule_profile_config = current

    dialog._show_registered_condition_summary(
        ScheduleRegistrationStatus(registered=True)
    )

    assert "登録済み条件" in dialog.schedule_condition_var.get()
    assert "画面で変更中" not in dialog.schedule_condition_var.get()


def test_schedule_views_normalise_multiple_backend_dtos():
    definitions = [
        SimpleNamespace(schedule_id="alpha", name="関東", enabled=True),
        SimpleNamespace(schedule_id="beta", display_name="東北", enabled=False),
    ]
    statuses = {
        "alpha": SimpleNamespace(schedule_id="alpha", registered=True),
        "beta": SimpleNamespace(schedule_id="beta", registered=False),
    }

    views = normalise_schedule_views(definitions, statuses)

    assert [(view.schedule_id, view.name, view.enabled) for view in views] == [
        ("alpha", "関東", True),
        ("beta", "東北", False),
    ]
    assert views[0].status is statuses["alpha"]


def test_schedule_aggregate_and_presenter_include_queue_waiting():
    queued = SimpleNamespace(
        state="queued",
        registered=True,
        running=True,
        queue_waiting=True,
    )
    views = [
        ScheduleView("queued-job", "待機中", True, status=queued),
        ScheduleView(
            "repair-job",
            "修復対象",
            True,
            status=SimpleNamespace(repair_reason="タスクなし"),
        ),
    ]

    counts = aggregate_schedule_counts(views)

    assert counts["queued"] == 1
    assert counts["running"] == 0
    assert counts["repair"] == 1
    assert MainWindow._schedule_aggregate_text(views) == (
        "保存条件: 2件 / 有効: 2件 / 順番待ち 1 / 要修復 1"
    )
    assert _schedule_status_presentation(queued)[0] == "順番待ち"
    assert SettingsDialog._status_presentation(queued)[0] == "順番待ち"


def test_main_aggregate_shows_shortest_next_run_and_cadence():
    daily = AppConfig(schedule=ScheduleConfig(time="09:00"))
    monthly = AppConfig(
        schedule=ScheduleConfig(interval="monthly", day_of_month=28, time="08:30")
    )
    views = [
        ScheduleView(
            "daily",
            "日次",
            True,
            status=SimpleNamespace(next_run="2026-08-05T09:00:00+09:00"),
            config=daily,
        ),
        ScheduleView(
            "monthly",
            "月末確認",
            True,
            status=SimpleNamespace(next_run="2026-08-04T08:30:00+09:00"),
            config=monthly,
        ),
    ]

    aggregate = MainWindow._schedule_aggregate_text(views)

    assert "最短次回: 月末確認 2026/08/04 08:30" in aggregate
    assert MainWindow._format_schedule_cadence(views[1]) == "毎月28日 08:30"


def test_orphan_schedule_has_no_invented_cadence():
    status = SimpleNamespace(
        schedule_id="orphan",
        display_name="台帳外タスク",
        registered=True,
        reason_code="TASK_REGISTRY_MISSING",
    )
    views = normalise_schedule_views([], {"orphan": status})
    orphan = views[0]

    assert (orphan.schedule_id, orphan.name, orphan.definition) == (
        "orphan",
        "台帳外タスク",
        None,
    )
    assert MainWindow._format_schedule_cadence(orphan) == "-（台帳欠落）"
    assert SettingsDialog._format_schedule_cadence(orphan) == "-（台帳欠落）"


def test_orphan_schedule_is_read_only_in_settings_manager():
    orphan = ScheduleView(
        "orphan",
        "台帳外タスク",
        True,
        status=SimpleNamespace(
            registered=False,
            repair_reason="登録台帳が見つかりません",
            reason_code="TASK_REGISTRY_MISSING",
        ),
    )
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog._schedule_manager_action_running = False
    dialog._schedule_views_by_id = {"orphan": orphan}
    dialog._selected_schedule_id = "orphan"
    dialog.btn_schedule_add = _Widget()
    dialog.btn_schedule_duplicate = _Widget()
    dialog.btn_schedule_edit = _Widget()
    dialog.btn_schedule_delete = _Widget()
    dialog.btn_schedule_toggle = _Widget()
    dialog.btn_schedule_repair = _Widget()
    dialog.btn_schedule_manager_run = _Widget()

    dialog._update_multi_schedule_action_state()

    assert dialog.btn_schedule_add.options["state"] == "normal"
    for widget in (
        dialog.btn_schedule_duplicate,
        dialog.btn_schedule_edit,
        dialog.btn_schedule_delete,
        dialog.btn_schedule_toggle,
        dialog.btn_schedule_repair,
        dialog.btn_schedule_manager_run,
    ):
        assert widget.options["state"] == "disabled"
    assert dialog.btn_schedule_repair.options["text"] == "修復不可"


@pytest.mark.parametrize(
    "status",
    (
        SimpleNamespace(registered=True, running=True),
        SimpleNamespace(registered=True, queue_waiting=True),
        SimpleNamespace(registered=True, retry_waiting=True),
    ),
    ids=("running", "queue_waiting", "retry_waiting"),
)
def test_settings_manager_keeps_management_actions_available_while_scheduled_run_active(
    status,
):
    view = ScheduleView("managed", "管理対象", True, status=status)
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog._schedule_manager_action_running = False
    dialog._schedule_views_by_id = {"managed": view}
    dialog._selected_schedule_id = "managed"
    dialog.btn_schedule_add = _Widget()
    dialog.btn_schedule_duplicate = _Widget()
    dialog.btn_schedule_edit = _Widget()
    dialog.btn_schedule_delete = _Widget()
    dialog.btn_schedule_toggle = _Widget()
    dialog.btn_schedule_repair = _Widget()
    dialog.btn_schedule_manager_run = _Widget()

    dialog._update_multi_schedule_action_state()

    for widget in (
        dialog.btn_schedule_duplicate,
        dialog.btn_schedule_edit,
        dialog.btn_schedule_delete,
        dialog.btn_schedule_toggle,
    ):
        assert widget.options["state"] == "normal"
    assert dialog.btn_schedule_manager_run.options["state"] == "disabled"


def test_manual_download_button_is_disabled_while_schedule_is_queued():
    window = MainWindow.__new__(MainWindow)
    window.btn_download = _Widget()
    window.download_thread = None
    window._pending_option_loads = 0
    window._schedule_queue_blocks_manual = True

    window._refresh_download_button_state()

    assert window.btn_download.options["state"] == "disabled"
    window._schedule_queue_blocks_manual = False
    window._refresh_download_button_state()
    assert window.btn_download.options["state"] == "normal"


def test_manual_download_button_is_disabled_while_relocation_is_pending():
    window = MainWindow.__new__(MainWindow)
    window.btn_download = _Widget()
    window.download_thread = None
    window._pending_option_loads = 0
    window._schedule_queue_blocks_manual = False
    window._installation_relocation_pending = True

    window._refresh_download_button_state()

    assert window.btn_download.options["state"] == "disabled"


def test_relocation_success_reconfigures_logger_to_current_path(monkeypatch):
    from src.gui import main_window as main_window_module

    window = MainWindow.__new__(MainWindow)
    window._installation_relocation_running = True
    window._installation_relocation_pending = True
    window.root = object()
    window.logger = Mock()
    window.load_config_to_ui = Mock()
    window._refresh_download_button_state = Mock()
    window.request_schedule_status_refresh = Mock()
    relocated = AppConfig()
    relocated.logging.file = r".\logs\app.log"
    result = SimpleNamespace(
        success=True,
        config=relocated,
        migrated_schedule_ids=("schedule-a",),
    )
    replacement_logger = Mock()
    logger_factory = Mock(return_value=replacement_logger)
    monkeypatch.setattr(main_window_module, "Logger", logger_factory)
    monkeypatch.setattr(main_window_module.messagebox, "showinfo", Mock())

    window._finish_installation_relocation(result)

    assert window.config is relocated
    assert window.logger is replacement_logger
    logger_factory.assert_called_once_with(relocated.logging)
    assert window._installation_relocation_pending is False


def test_manual_download_handler_refuses_to_start_while_queued(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._schedule_queue_blocks_manual = True
    window.root = object()
    window.download_callback = Mock()
    warnings = []
    monkeypatch.setattr(
        "src.gui.main_window.messagebox.showwarning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    window.on_download_start()

    window.download_callback.assert_not_called()
    assert "順番待ち" in warnings[0][0][1]


def test_manual_download_handler_refuses_to_start_before_relocation(monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window._installation_relocation_pending = True
    window.root = object()
    window.download_callback = Mock()
    warnings = []
    monkeypatch.setattr(
        "src.gui.main_window.messagebox.showwarning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    window.on_download_start()

    window.download_callback.assert_not_called()
    assert "付け替え" in warnings[0][0][1]


def test_stale_main_schedule_refresh_is_discarded():
    window = MainWindow.__new__(MainWindow)
    window._schedule_status_query_running = True
    window._schedule_refresh_generation = 2
    window._schedule_refresh_pending = True
    window._closing = False
    current_view = ScheduleView("current", "現行", True)
    window._schedule_views = [current_view]
    window.root = SimpleNamespace(after=Mock())
    window.request_schedule_status_refresh = Mock()

    window._apply_schedule_collection([], generation=1)

    assert window._schedule_status_query_running is False
    assert window._schedule_views == [current_view]
    window.root.after.assert_called_once_with(0, window.request_schedule_status_refresh)


def test_stale_settings_schedule_refresh_is_discarded():
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog._schedule_manager_query_running = True
    dialog._schedule_manager_generation = 2
    dialog._schedule_manager_refresh_pending = True
    current_view = ScheduleView("current", "現行", True)
    dialog._schedule_views = [current_view]
    dialog.dialog = SimpleNamespace(after=Mock())
    dialog.request_multi_schedule_refresh = Mock()

    dialog._apply_multi_schedule_refresh(
        1,
        [],
        None,
        None,
        {},
        [],
        [],
        None,
    )

    assert dialog._schedule_manager_query_running is False
    assert dialog._schedule_views == [current_view]
    dialog.dialog.after.assert_called_once_with(
        0, dialog.request_multi_schedule_refresh
    )


def test_duplicate_conditions_ignore_schedule_timing_and_exclude_self():
    original = AppConfig(schedule=ScheduleConfig(time="09:00"))
    candidate = deepcopy(original)
    candidate.schedule.interval = "weekly"
    candidate.schedule.time = "17:30"
    views = [
        ScheduleView("same", "同一条件", True, config=original),
        ScheduleView("self", "編集中", True, config=candidate),
    ]

    assert duplicate_condition_names(
        candidate,
        views,
        {"same": original, "self": candidate},
        exclude_schedule_id="self",
    ) == ["同一条件"]


def test_history_labels_deleted_schedule_and_trigger_kind():
    record = SimpleNamespace(
        schedule_id="removed", display_name="旧関東", trigger_kind="windows_task"
    )

    assert history_display_name(record, {"active": "現行"}) == ("削除済み設定: 旧関東")
    assert trigger_kind_display(record.trigger_kind) == "Windowsタスク"


def test_settings_history_filter_switches_between_selected_and_all():
    dialog = SettingsDialog.__new__(SettingsDialog)
    selected = [SimpleNamespace(schedule_id="selected")]
    all_records = selected + [SimpleNamespace(schedule_id="other")]
    dialog._schedule_selected_history = selected
    dialog._schedule_all_history = all_records
    dialog.schedule_history_filter_var = _Variable("選択設定")

    assert dialog._history_records_for_filter() == selected
    dialog.schedule_history_filter_var.set("全設定")
    assert dialog._history_records_for_filter() == all_records


def test_registration_conflict_is_localised_and_refreshes(monkeypatch):
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog._schedule_manager_action_running = True
    draft = (None, "編集中", AppConfig())
    dialog._schedule_action_retry_editor = draft
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = object()
    dialog._update_multi_schedule_action_state = Mock()
    dialog.request_multi_schedule_refresh = Mock()
    shown = []
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showerror",
        lambda *args, **kwargs: shown.append((args, kwargs)),
    )
    error = RuntimeError("registry changed")
    error.reason_code = "REGISTRATION_CONFLICT"

    dialog._finish_multi_schedule_action("更新", None, error)

    assert "別の画面" in dialog.schedule_registration_var.get()
    assert "REGISTRATION_CONFLICT" in dialog.schedule_registration_var.get()
    assert "最新状態を再読み込み" in shown[0][0][1]
    assert dialog._schedule_editor_reopen_after_refresh == draft
    dialog.request_multi_schedule_refresh.assert_called_once_with()


def test_registration_failure_reopens_submitted_editor_draft(monkeypatch):
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog._schedule_manager_action_running = True
    draft = (None, "編集中", AppConfig())
    dialog._schedule_action_retry_editor = draft
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = SimpleNamespace(after=Mock())
    dialog._update_multi_schedule_action_state = Mock()
    dialog._reopen_schedule_editor_draft = Mock()
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showerror", lambda *args, **kwargs: None
    )
    error = RuntimeError("task registration failed")
    error.reason_code = "TASK_REGISTER_FAILED"

    dialog._finish_multi_schedule_action("追加", None, error)

    delay, callback = dialog.dialog.after.call_args.args
    assert delay == 0
    callback()
    dialog._reopen_schedule_editor_draft.assert_called_once_with(draft)


def test_external_import_cleanup_warning_is_logged_and_shown(monkeypatch):
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog._schedule_manager_action_running = True
    dialog._schedule_action_retry_editor = None
    dialog.schedule_registration_var = _Variable()
    dialog.schedule_registration_label = _Widget()
    dialog.dialog = object()
    dialog.logger = Mock()
    dialog.request_multi_schedule_refresh = Mock()
    dialog._update_multi_schedule_action_state = Mock()
    shown = []
    monkeypatch.setattr(
        "src.gui.settings_dialog.messagebox.showwarning",
        lambda *args, **kwargs: shown.append((args, kwargs)),
    )
    result = SimpleNamespace(
        reason_code="EXTERNAL_TASK_CLEANUP_PENDING",
        status=SimpleNamespace(repair_reason="旧タスクを削除できません"),
        warnings=("旧タスク削除を再実行してください",),
    )

    dialog._finish_multi_schedule_action("旧設定の取り込み", result, None)

    assert "後処理警告" in dialog.schedule_registration_var.get()
    assert "EXTERNAL_TASK_CLEANUP_PENDING" in dialog.schedule_registration_var.get()
    assert shown
    dialog.logger.warning.assert_called_once()
    dialog.request_multi_schedule_refresh.assert_called_once_with()


def test_schedule_adapter_overlays_runtime_queue_status(monkeypatch):
    service = SimpleNamespace(
        list_schedules=lambda: [
            SimpleNamespace(schedule_id="waiting-job", name="待機", enabled=True)
        ],
        get_statuses=lambda current_configs=None: {
            "waiting-job": SimpleNamespace(schedule_id="waiting-job", registered=True)
        },
    )
    monkeypatch.setattr(
        "src.app.run_queue.status_for",
        lambda schedule_id: SimpleNamespace(
            schedule_id=schedule_id,
            waiting=True,
            position=2,
            total_waiting=3,
        ),
    )

    view = ScheduleServiceAdapter(service).list_views()[0]

    assert view.status.queue_waiting is True
    assert view.status.queue_position == 2
    assert aggregate_schedule_counts([view])["queued"] == 1


def test_schedule_adapter_forwards_registry_revision_to_mutation():
    received = {}

    def create_schedule(config, *, name=None, expected_revision=None):
        received.update(name=name, revision=expected_revision, config=config)
        return SimpleNamespace(schedule_id="new")

    service = SimpleNamespace(
        get_registry=lambda: SimpleNamespace(revision=7),
        list_schedules=lambda: [],
        get_statuses=lambda current_configs=None: {},
        create_schedule=create_schedule,
    )
    adapter = ScheduleServiceAdapter(service)

    adapter.list_views()
    adapter.create("新規", AppConfig())

    assert received["revision"] == 7
    assert received["name"] == "新規"
    assert adapter.registry_revision is None


def test_schedule_adapter_does_not_retry_internal_type_error():
    calls = []

    def create_schedule(config, *, name=None, expected_revision=None):
        calls.append((config, name, expected_revision))
        raise TypeError("implementation failure")

    adapter = ScheduleServiceAdapter(
        SimpleNamespace(
            list_schedules=lambda: [],
            create_schedule=create_schedule,
        )
    )

    with pytest.raises(TypeError, match="implementation failure"):
        adapter.create("新規", AppConfig(), expected_revision=3)

    assert len(calls) == 1


def test_schedule_adapter_keeps_single_service_fallback(monkeypatch):
    run_now = Mock(return_value=True)

    def legacy_run_now():
        return run_now()

    registered = AppConfig(schedule=ScheduleConfig(enabled=True))
    service = SimpleNamespace(
        get_status=lambda *args, **kwargs: ScheduleRegistrationStatus(
            state=ScheduleState.REGISTERED,
            registered=True,
            profile_id="legacy-snapshot",
        ),
        get_registered_config=lambda: registered,
        history=lambda limit=20: [
            ScheduledRunRecord(profile_id="legacy-snapshot", result="success")
        ],
        run_now=legacy_run_now,
    )
    monkeypatch.setattr(
        "src.app.run_queue.status_for",
        lambda schedule_id: SimpleNamespace(
            schedule_id=schedule_id,
            waiting=False,
            position=None,
            total_waiting=0,
        ),
    )
    adapter = ScheduleServiceAdapter(service)

    views = adapter.list_views(AppConfig())

    assert adapter.supports_multiple is False
    assert len(views) == 1
    assert views[0].name == "既存の定期実行"
    assert views[0].profile_id == "legacy-snapshot"
    assert adapter.history("default", 20)[0].result == "success"
    assert adapter.run_now("default") is True
    run_now.assert_called_once_with()


def test_schedule_editor_round_trips_all_search_condition_groups():
    dialog = ScheduleEditorDialog.__new__(ScheduleEditorDialog)
    dialog._config = AppConfig()
    dialog.name_var = _Variable("全国案件")
    dialog.target_urls_text = _TextValue("https://example.test/search\n")
    dialog.file_types_var = _Variable("pdf、xlsx")
    dialog.keywords_var = _Variable("仕様書, 図面")
    dialog.download_date_start_var = _Variable("2026-07-01")
    dialog.download_date_end_var = _Variable("2026-07-31")
    dialog.save_path_var = _Variable(r"C:\downloads")
    dialog.naming_rule_var = _Variable("{document_name}")
    dialog.enabled_var = _Variable(True)
    dialog.interval_var = _Variable("毎月")
    dialog.time_var = _Variable("08:30")
    dialog.weekday_var = _Variable("火曜日")
    dialog.day_var = _Variable("28")
    dialog.start_when_available_var = _Variable(True)
    dialog.wake_to_run_var = _Variable(False)
    dialog.retry_count_var = _Variable("2")
    dialog.retry_interval_var = _Variable("15")
    dialog.notification_policy_var = _Variable(
        "重要な結果のみ（新規保存・失敗など）"
    )
    values = {
        "hachu_daibunrui_var": "国の機関",
        "hachu_chubunrui_var": "関東地方整備局",
        "hachu_shoubunrui_var": "東京",
        "hachu_saibunrui_var": "本局",
        "hachu_multi_var": "機関A、機関B",
        "koji_name_var": "橋梁",
        "place_search_type_var": "text",
        "place_chihou_var": "関東",
        "place_todofuken_var": "東京都",
        "place_shichouson_var": "新宿区",
        "place_text_var": "都内",
        "contract_types_var": "一般競争入札、随意契約",
        "update_date_type_var": "past",
        "update_date_days_var": "7",
        "koukoku_date_type_var": "range",
        "koukoku_date_start_var": "2026-08-01",
        "koukoku_date_end_var": "2026-08-31",
        "kaisatsu_date_type_var": "range",
        "kaisatsu_date_start_var": "2026-09-01",
        "kaisatsu_date_end_var": "2026-09-30",
        "keiyaku_date_type_var": "range",
        "keiyaku_date_start_var": "2026-10-01",
        "keiyaku_date_end_var": "2026-10-31",
        "koji_shubetsu_var": "一般土木",
        "koji_gyoushu_var": "土木一式",
        "yotei_price_min_var": "100",
        "yotei_price_max_var": "200",
        "rakusatsu_price_min_var": "80",
        "rakusatsu_price_max_var": "180",
        "rakusatsu_name_var": "建設会社",
        "display_count_var": "100",
    }
    for attribute, value in values.items():
        setattr(dialog, attribute, _Variable(value))
    dialog.denshi_var = _Variable(True)
    dialog.koukai_var = _Variable(True)

    config = dialog._config_from_ui()
    search = config.search_conditions

    assert config.target_urls == AppConfig().target_urls
    assert search.hachu_multi == ["機関A", "機関B"]
    assert search.contract_types == ["一般競争入札", "随意契約"]
    assert (search.update_date_type, search.update_date_days) == ("past", 7)
    assert (search.koukoku_date_start, search.keiyaku_date_end) == (
        "2026-08-01",
        "2026-10-31",
    )
    assert (search.yotei_price_min, search.rakusatsu_price_max) == (100, 180)
    assert (search.denshi, search.koukai, search.display_count) == (
        True,
        True,
        100,
    )
    assert config.download_conditions.file_types == [".pdf", ".xlsx"]
    assert config.download_conditions.date_range == {
        "start": "2026-07-01",
        "end": "2026-07-31",
    }
    assert config.schedule.interval == "monthly"
    assert config.schedule.day_of_month == 28
    assert config.schedule.notification_policy == "important_only"

    dialog.name_var.set("長" * 81)
    with pytest.raises(ValueError, match="80文字以内"):
        dialog._config_from_ui()


def test_test_notification_result_uses_structured_delivery_result():
    submitted = SimpleNamespace(
        submitted=True,
        reason_code="NOTIFICATION_SUBMITTED",
    )
    unavailable = SimpleNamespace(
        submitted=False,
        reason_code="NOTIFICATION_UNAVAILABLE",
    )

    assert ScheduleEditorDialog._test_notification_succeeded(submitted) is True
    assert ScheduleEditorDialog._test_notification_succeeded(unavailable) is False


def test_schedule_editor_dynamic_key_ignores_free_text_fields():
    base = SearchConditions(
        hachu_daibunrui="国の機関",
        koji_name="橋梁",
    )
    free_text_changed = deepcopy(base)
    free_text_changed.koji_name = "道路"
    dynamic_changed = deepcopy(base)
    dynamic_changed.hachu_daibunrui = "地方公共団体"

    assert ScheduleEditorDialog._dynamic_search_key(base) == (
        ScheduleEditorDialog._dynamic_search_key(free_text_changed)
    )
    assert ScheduleEditorDialog._dynamic_search_key(base) != (
        ScheduleEditorDialog._dynamic_search_key(dynamic_changed)
    )


def test_shared_search_option_model_maps_codes_and_rejects_unknown_value():
    initial = SearchConditions(
        place_chihou="legacy-code",
        koji_shubetsu="99",
    )
    model = SearchConditionOptionModel(
        initial,
        {
            "place_chihou": [("3", "関東")],
            "koji_shubetsu": [{"value": "01", "label": "一般土木工事"}],
        },
    )

    assert normalise_search_options([("3", "関東")])[0].code == "3"
    assert model.widget_values("place_chihou", "legacy-code") == (
        "",
        "関東",
        "legacy-code",
    )
    validation_errors = "\n".join(model.validate(initial))
    assert "最新候補にありません" in validation_errors
    assert "選択し直してください" in validation_errors
    assert "保存済みの未知値" in "\n".join(model.warnings(initial))

    changed = deepcopy(initial)
    changed.place_chihou = "関東"
    changed.koji_shubetsu = "01"
    assert model.validate(changed) == []
    changed.koji_shubetsu = "入力した未知値"
    assert "対象サイトの最新候補にありません" in "\n".join(
        model.validate(changed)
    )


def test_shared_search_structure_rejects_child_without_parent():
    errors = validate_search_condition_structure(
        SearchConditions(hachu_chubunrui="関東地方整備局")
    )

    assert "上位項目" in errors[0]


def test_schedule_editor_parent_change_clears_children_and_loads_next():
    dialog = ScheduleEditorDialog.__new__(ScheduleEditorDialog)
    dialog._config = AppConfig()
    dialog._search_option_model = SearchConditionOptionModel(
        SearchConditions(),
        {
            "hachu_chubunrui": ["旧中分類"],
            "hachu_shoubunrui": ["旧小分類"],
            "hachu_saibunrui": ["旧細分類"],
        },
    )
    dialog._dynamic_combos = {
        field: _Widget()
        for field in (
            "hachu_daibunrui",
            "hachu_chubunrui",
            "hachu_shoubunrui",
            "hachu_saibunrui",
        )
    }
    dialog._option_generations = {}
    dialog._option_loading = set()
    dialog._option_errors = {}
    dialog.place_search_type_var = _Variable("list")
    dialog.hachu_daibunrui_var = _Variable("国の機関")
    dialog.hachu_chubunrui_var = _Variable("旧中分類")
    dialog.hachu_shoubunrui_var = _Variable("旧小分類")
    dialog.hachu_saibunrui_var = _Variable("旧細分類")
    dialog._request_option_load = Mock()
    dialog._refresh_dynamic_option_status = Mock()

    dialog._on_dynamic_option_selected("hachu_daibunrui")

    assert dialog.hachu_chubunrui_var.get() == ""
    assert dialog.hachu_shoubunrui_var.get() == ""
    assert dialog.hachu_saibunrui_var.get() == ""
    dialog._request_option_load.assert_called_once_with("hachu_chubunrui")


def test_schedule_editor_discards_stale_option_response():
    dialog = ScheduleEditorDialog.__new__(ScheduleEditorDialog)
    model = SearchConditionOptionModel(
        SearchConditions(), {"koji_shubetsu": ["現行候補"]}
    )
    dialog._search_option_model = model
    dialog._option_queue = Queue()
    dialog._option_queue.put(("koji_shubetsu", 1, ["古い候補"], None))
    dialog._option_generations = {"koji_shubetsu": 2}
    dialog._option_loading = set()
    dialog._option_errors = {}
    dialog._closed = False
    dialog.dialog = SimpleNamespace(after=Mock())
    dialog._refresh_dynamic_combo = Mock()
    dialog._refresh_dynamic_option_status = Mock()

    dialog._poll_option_queue()

    assert model.options("koji_shubetsu")[0].label == "現行候補"
    dialog._refresh_dynamic_combo.assert_not_called()


def test_schedule_editor_discards_response_after_user_edit_revision():
    dialog = ScheduleEditorDialog.__new__(ScheduleEditorDialog)
    model = SearchConditionOptionModel(
        SearchConditions(), {"koji_shubetsu": ["現行候補"]}
    )
    dialog._search_option_model = model
    dialog._option_queue = Queue()
    dialog._option_queue.put(
        (
            "koji_shubetsu",
            DynamicOptionRequestToken(
                field="koji_shubetsu",
                generation=1,
                parent_values=(),
                user_revision=0,
            ),
            ["遅延候補"],
            None,
        )
    )
    dialog._option_generations = {"koji_shubetsu": 1}
    dialog._option_user_revisions = {"koji_shubetsu": 1}
    dialog._option_loading = {"koji_shubetsu"}
    dialog._option_errors = {}
    dialog._closed = False
    dialog.dialog = SimpleNamespace(after=Mock())
    dialog._parents_for_option = Mock(return_value=())
    dialog._refresh_dynamic_combo = Mock()
    dialog._refresh_dynamic_option_status = Mock()

    dialog._poll_option_queue()

    assert model.options("koji_shubetsu")[0].label == "現行候補"
    dialog._refresh_dynamic_combo.assert_called_once_with("koji_shubetsu")
    assert not dialog._option_loading


@pytest.mark.parametrize(
    ("interval", "weekday_state", "day_state"),
    [
        ("毎日", "disabled", "disabled"),
        ("毎週", "readonly", "disabled"),
        ("毎月", "disabled", "normal"),
    ],
)
def test_schedule_editor_enables_only_fields_for_selected_cadence(
    interval,
    weekday_state,
    day_state,
):
    dialog = ScheduleEditorDialog.__new__(ScheduleEditorDialog)
    dialog.interval_var = _Variable(interval)
    dialog.weekday_combo = _Widget()
    dialog.day_spinbox = _Widget()

    dialog._update_schedule_fields()

    assert dialog.weekday_combo.options["state"] == weekday_state
    assert dialog.day_spinbox.options["state"] == day_state


def test_schedule_editor_cancel_confirms_unsaved_changes(monkeypatch):
    dialog = ScheduleEditorDialog.__new__(ScheduleEditorDialog)
    dialog._initial_ui_fingerprint = "before"
    dialog._state_fingerprint = Mock(return_value="after")
    dialog.dialog = SimpleNamespace(destroy=Mock())
    monkeypatch.setattr(
        "src.gui.schedule_editor_dialog.messagebox.askyesno",
        lambda *args, **kwargs: False,
    )

    dialog._on_cancel()

    dialog.dialog.destroy.assert_not_called()


class _MultiTaskClient:
    def __init__(self):
        self.tasks = {}
        self.run_calls = []

    def query(self, task_name):
        xml = self.tasks.get(task_name)
        return TaskQueryResult(
            exists=xml is not None,
            running=False,
            xml=xml,
            enabled=True if xml is not None else None,
        )

    def query_many(self, task_names):
        return {task_name: self.query(task_name) for task_name in task_names}

    def create_or_update(self, task_name, xml):
        self.tasks[task_name] = xml

    def delete(self, task_name, missing_ok=False):
        return self.tasks.pop(task_name, None) is not None

    def run(self, task_name):
        self.run_calls.append(task_name)
        return task_name in self.tasks


def test_gui_adapter_crud_uses_real_multi_schedule_service(tmp_path):
    executable = tmp_path / "ippi-down.exe"
    executable.write_bytes(b"stub")
    client = _MultiTaskClient()
    service = ScheduleService(
        config_dir=tmp_path / "config",
        logs_dir=tmp_path / "logs",
        install_id="gui-test",
        task_client=client,
        executable=executable,
        app_root=tmp_path,
        now_provider=lambda: datetime(
            2026,
            8,
            3,
            10,
            0,
            tzinfo=timezone(timedelta(hours=9)),
        ),
    )
    adapter = ScheduleServiceAdapter(service)
    first = AppConfig(schedule=ScheduleConfig(enabled=True, time="09:00"))
    second = AppConfig(schedule=ScheduleConfig(enabled=False, time="10:00"))

    created_first = adapter.create("関東", first)
    created_second = adapter.create("東北", second)
    first_id = created_first.schedule_id
    second_id = created_second.schedule_id

    assert {view.name for view in adapter.list_views()} == {"関東", "東北"}
    assert adapter.run_now(first_id) is True
    assert client.run_calls[-1].endswith(first_id)

    second.search_conditions.koji_name = "道路"
    second.schedule.enabled = True
    adapter.update(second_id, "東北道路", second)
    copied = adapter.duplicate(second_id, "東北道路 のコピー")
    adapter.set_enabled(second_id, False)

    with pytest.raises(ScheduleServiceError) as disabled_run:
        adapter.run_now(second_id)
    assert disabled_run.value.reason_code == "SCHEDULE_DISABLED"

    registrations = {item.schedule_id: item for item in service.list_schedules()}
    assert registrations[second_id].name == "東北道路"
    assert registrations[second_id].enabled is False
    assert registrations[copied.schedule_id].enabled is False

    adapter.delete(first_id)
    assert service.get_schedule(first_id) is None
