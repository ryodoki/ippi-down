# -*- coding: utf-8 -*-

"""保存済みファイル再分類GUIのDTO境界と実行拒否条件。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.gui.main_window import MainWindow
from src.gui.reclassification_dialog import (
    ReclassificationDialog,
    ReclassificationServiceAdapter,
    normalise_reclassification_candidates,
    normalise_reclassification_result,
)
from src.gui.settings_dialog import SettingsDialog
from src.models.config_model import AppConfig
from src.storage.layout import RunKind
from src.storage.reclassification import (
    ReclassificationApplyResult,
    ReclassificationApplyStatus,
    ReclassificationCandidate,
    ReclassificationCandidateState,
    ReclassificationOutcome,
    ReclassificationPlan,
)


def _candidate(state=ReclassificationCandidateState.READY_MOVE):
    return ReclassificationCandidate(
        candidate_id="candidate-1",
        run_kind=RunKind.SCHEDULED,
        storage_key="S003",
        run_root=Path("C:/data/scheduled/S003_test"),
        history_path=Path("C:/data/scheduled/S003_test/.history.jsonl"),
        source_path=Path("C:/data/99_分類未解決/工事/文書.pdf"),
        target_path=Path("C:/data/国の機関/国土交通省/工事/文書.pdf"),
        url="https://example.invalid/document.pdf",
        project_name="試験工事",
        document_name="入札公告",
        agency_segments=(),
        new_agency_segments=(),
        state=state,
        reason_code="AGENCY_PATH_RESOLVED",
        reason="細分類を一意に特定しました",
        size=100,
        sha256="a" * 64,
        expected_format="pdf",
    )


def test_reclassification_candidate_normalises_public_service_dto():
    plan = ReclassificationPlan(
        plan_id="plan-1",
        data_root=Path("C:/data"),
        created_at="2026-08-20T12:00:00+09:00",
        candidates=(_candidate(),),
    )

    (view,) = normalise_reclassification_candidates(plan)

    assert view.candidate_id == "candidate-1"
    assert view.run_kind == "定期実行"
    assert view.schedule_name == "test (S003)"
    assert view.project_name == "試験工事"
    assert view.document_name == "入札公告"
    assert view.applicable is True
    assert view.applicability == "再分類可能（移動）"
    assert "AGENCY_PATH_RESOLVED" in view.reason_display


def test_reclassification_non_actionable_state_is_not_selected():
    plan = SimpleNamespace(
        candidates=(
            _candidate(ReclassificationCandidateState.CONFLICT),
        )
    )

    (view,) = normalise_reclassification_candidates(plan)

    assert view.applicable is False
    assert view.selected is False
    assert view.applicability == "対象外（移動先競合）"


def test_existing_identical_target_explains_that_old_file_is_kept():
    plan = SimpleNamespace(
        candidates=(
            _candidate(ReclassificationCandidateState.READY_TARGET_REUSE),
        )
    )

    (view,) = normalise_reclassification_candidates(plan)

    assert view.applicable is True
    assert view.applicability == "履歴更新のみ（旧ファイル保持）"


def test_reclassification_result_uses_public_count_properties():
    source = Path("C:/data/source.pdf")
    target = Path("C:/data/target.pdf")
    statuses = (
        ReclassificationApplyStatus.MOVED,
        ReclassificationApplyStatus.TARGET_REUSED,
        ReclassificationApplyStatus.CONFLICT,
        ReclassificationApplyStatus.INVALID,
        ReclassificationApplyStatus.SKIPPED,
        ReclassificationApplyStatus.CANCELLED,
        ReclassificationApplyStatus.FAILED,
    )
    result = ReclassificationApplyResult(
        plan_id="plan-1",
        outcomes=tuple(
            ReclassificationOutcome(
                candidate_id=f"candidate-{index}",
                status=status,
                source_path=source,
                target_path=target,
            )
            for index, status in enumerate(statuses)
        ),
    )

    view = normalise_reclassification_result(result)

    assert view.total == 7
    assert view.moved == 1
    assert view.reused == 1
    assert view.conflict == 1
    assert view.invalid == 1
    assert view.skipped == 1
    assert view.cancelled == 1
    assert view.failed == 1
    assert "旧ファイル保持=1" in view.summary


def test_reclassification_adapter_keeps_old_minimal_signature_compatible():
    service = SimpleNamespace(
        scan=Mock(return_value="plan"),
        apply=Mock(return_value="result"),
    )
    adapter = ReclassificationServiceAdapter(service)
    config = AppConfig()

    assert adapter.scan(
        config,
        cancel_check=lambda: False,
        progress_callback=lambda *_args: None,
    ) == "plan"
    assert adapter.apply(
        "plan",
        ("candidate-1",),
        cancel_check=lambda: False,
        progress_callback=lambda *_args: None,
    ) == "result"


def test_settings_reclassification_prefers_shared_run_block_reason():
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog.reclassification_block_reason_provider = lambda: "通常実行中"
    dialog._schedule_views = ()

    assert dialog._reclassification_block_reason() == "通常実行中"


def test_main_window_reclassification_rejects_scheduled_queue():
    window = MainWindow.__new__(MainWindow)
    window.download_thread = None
    window._schedule_queue_blocks_manual = True
    window._schedule_views = ()

    assert "順番待ち" in window._reclassification_block_reason()


def test_applied_preview_is_invalidated_before_it_can_run_again():
    """適用後に古いplanと候補を選び直して再実行できない。"""

    dialog = ReclassificationDialog.__new__(ReclassificationDialog)
    dialog._plan = object()
    dialog._selected_ids = {"candidate-1"}
    dialog._candidates = {"candidate-1": object()}
    dialog.tree = Mock()
    dialog.tree.get_children.return_value = ("candidate-1",)

    dialog._invalidate_plan_after_apply()

    assert dialog._plan is None
    assert dialog._selected_ids == set()
    assert dialog._candidates == {}
    dialog.tree.delete.assert_called_once_with("candidate-1")


def test_cancelled_scan_plan_cannot_be_applied():
    """途中まで候補が得られても、キャンセル済みplanは受理しない。"""

    plan = ReclassificationPlan(
        plan_id="cancelled-plan",
        data_root=Path("C:/data"),
        created_at="2026-08-20T12:00:00+09:00",
        candidates=(_candidate(),),
        cancelled=True,
    )
    dialog = ReclassificationDialog.__new__(ReclassificationDialog)
    dialog._busy = "scan"
    dialog._plan = object()
    dialog._candidates = {}
    dialog._selected_ids = {"old-candidate"}
    dialog.status_var = Mock()
    dialog.progress = Mock()
    dialog.logger = Mock()
    dialog._render_candidates = Mock()
    dialog._refresh_buttons = Mock()

    dialog._finish_scan(plan)

    assert dialog._plan is None
    assert dialog._selected_ids == set()
    assert tuple(dialog._candidates) == ("candidate-1",)
    assert "部分結果は適用できません" in dialog.status_var.set.call_args.args[0]
    dialog.logger.warning.assert_called_once()
    dialog._refresh_buttons.assert_called_once()


def test_buttons_disable_apply_and_selection_without_accepted_plan():
    dialog = ReclassificationDialog.__new__(ReclassificationDialog)
    dialog._busy = ""
    dialog._plan = None
    dialog._selected_ids = {"partial-candidate"}
    dialog.btn_rescan = Mock()
    dialog.btn_select_all = Mock()
    dialog.btn_clear = Mock()
    dialog.btn_cancel = Mock()
    dialog.btn_apply = Mock()

    dialog._refresh_buttons()

    dialog.btn_rescan.configure.assert_called_once_with(state="normal")
    dialog.btn_select_all.configure.assert_called_once_with(state="disabled")
    dialog.btn_clear.configure.assert_called_once_with(state="disabled")
    dialog.btn_apply.configure.assert_called_once_with(state="disabled")
