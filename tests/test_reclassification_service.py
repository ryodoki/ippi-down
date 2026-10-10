# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.downloader import DownloadHistory
from src.storage.layout import RunKind
from src.storage.reclassification import (
    ReclassificationApplyResult,
    ReclassificationApplyStatus,
    ReclassificationCandidateState,
    ReclassificationResult,
    ReclassificationService,
)


PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_approved_result_name_keeps_initial_name_compatible():
    assert ReclassificationResult is ReclassificationApplyResult


class _Logger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def info(self, message: object) -> None:
        self.infos.append(str(message))

    def warning(self, message: object) -> None:
        self.warnings.append(str(message))

    def error(self, message: object) -> None:
        self.errors.append(str(message))


class _Guard:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.entries = 0

    @contextmanager
    def try_acquire(self):
        self.entries += 1
        yield self.acquired


def _config(data_root: Path, *, layout_version: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        save_paths=SimpleNamespace(
            local=str(data_root),
            layout_version=layout_version,
            normal_folder="01_通常ダウンロード",
            scheduled_folder="02_定期実行",
        )
    )


def _segments(*, include_fine: bool = True) -> list[dict[str, str]]:
    values = [
        {"level": "daibunrui", "label": "国の機関", "code": "01"},
        {
            "level": "chubunrui",
            "label": "国土交通省",
            "code": "02",
        },
        {
            "level": "shoubunrui",
            "label": "中部地方整備局",
            "code": "003",
        },
    ]
    if include_fine:
        values.append(
            {
                "level": "saibunrui",
                "label": "飯田国道事務所",
                "code": "000007",
            }
        )
    return values


def _append_download(
    run_root: Path,
    *,
    url: str,
    include_fine: bool = True,
    payload: bytes = PDF_BYTES,
    recorded_payload: bytes | None = None,
    storage_key: str = "",
    document_id: str = "40",
    agency_path_version: int = 2,
    include_office_fallback: bool | None = None,
    agency_id: str = "0102003000",
    office_name: str = "飯田国道事務所",
    layout_version: int = 3,
    search_target: str = "",
) -> tuple[Path, dict[str, object]]:
    segments = _segments(include_fine=include_fine)
    labels = [str(segment["label"]) for segment in segments]
    if include_office_fallback is None:
        include_office_fallback = (
            not include_fine and agency_path_version >= 2
        )
    stored_agency_labels = list(labels)
    if include_office_fallback:
        stored_agency_labels.append(office_name)
    relative = Path(
        "99_分類未解決",
        *stored_agency_labels,
        "令和6年度 テスト工事",
        "02_入札経過・その他",
        f"契約の内容_{document_id}.pdf",
    )
    source = run_root / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(payload)
    expected = payload if recorded_payload is None else recorded_payload
    record: dict[str, object] = {
        "schema_version": 2,
        "status": "SUCCESS",
        "url": url,
        "target_path": relative.as_posix(),
        "path": relative.as_posix(),
        "expected_format": ".pdf",
        "processing_mode": "DIRECT",
        "validation_kind": "PDF",
        "final_url": url,
        "size": len(expected),
        "sha256": hashlib.sha256(expected).hexdigest(),
        "completed_at": "2026-08-20T00:00:00+00:00",
        "document_name": "契約の内容",
        "document_id": document_id,
        "layout_version": layout_version,
        "run_kind": (
            RunKind.SCHEDULED.value if storage_key else RunKind.MANUAL.value
        ),
        "office_name": office_name,
        "agency_id": agency_id,
        "agency_path": {
            "version": agency_path_version,
            "segments": segments,
            "resolution": {
                "status": "unresolved",
                "method": "test",
                "reason": "test fixture",
                "reason_code": "AGENCY_FINE_NOT_FOUND",
            },
        },
    }
    if search_target:
        record["search_target"] = search_target
    if storage_key:
        record["storage_key"] = storage_key
        record["schedule_id"] = "schedule-1"
    history_path = run_root / DownloadHistory.FILE_NAME
    with history_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return source, record


def _service(*, resolver=None, acquired: bool = True):
    guard = _Guard(acquired)
    return ReclassificationService(
        logger=_Logger(),
        agency_resolver=resolver,
        run_guard=guard,
    ), guard


def test_scan_finds_manual_and_all_scheduled_roots_offline(tmp_path: Path):
    data_root = tmp_path / "downloads"
    normal = data_root / "01_通常ダウンロード"
    scheduled = data_root / "02_定期実行" / "abc123_日次"
    _append_download(normal, url="https://example.test/manual")
    _append_download(
        scheduled,
        url="https://example.test/scheduled",
        storage_key="abc123",
    )
    resolver_calls: list[object] = []

    def resolver(query):
        resolver_calls.append(query)
        return ()

    service, guard = _service(resolver=resolver)
    plan = service.scan(_config(data_root))

    assert not plan.cancelled
    assert not plan.issues
    assert plan.scanned_records == 2
    assert plan.actionable_count == 2
    assert {candidate.run_kind for candidate in plan.candidates} == {
        RunKind.MANUAL,
        RunKind.SCHEDULED,
    }
    assert {candidate.storage_key for candidate in plan.candidates} == {
        "",
        "abc123",
    }
    assert all(
        candidate.reason_code == "RECLASSIFICATION_READY_MOVE"
        for candidate in plan.candidates
    )
    assert resolver_calls == []
    assert guard.entries == 1


def test_scan_v4_keeps_koji_and_gyomu_run_roots_separate(tmp_path: Path):
    data_root = tmp_path / "downloads"
    koji = (
        data_root
        / "工事の検索（入札の経過）"
        / "01_通常ダウンロード"
    )
    gyomu = (
        data_root
        / "業務の検索（入札の経過）"
        / "01_通常ダウンロード"
    )
    _append_download(
        koji,
        url="https://example.test/koji",
        layout_version=4,
        search_target="koji_keika",
    )
    _append_download(
        gyomu,
        url="https://example.test/gyomu",
        layout_version=4,
        search_target="gyomu_keika",
    )
    service, _guard = _service(resolver=lambda _query: ())

    plan = service.scan(_config(data_root, layout_version=4))

    assert not plan.issues
    assert plan.scanned_records == 2
    assert {candidate.search_target for candidate in plan.candidates} == {
        "koji_keika",
        "gyomu_keika",
    }
    assert all(candidate.layout_version == 4 for candidate in plan.candidates)
    assert all(
        candidate.target_path.is_relative_to(candidate.run_root)
        for candidate in plan.candidates
    )
    assert all(
        candidate.reason_code == "RECLASSIFICATION_READY_MOVE"
        for candidate in plan.candidates
    )


def test_scan_v4_scopes_agency_resolver_cache_by_search_target(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    roots = {
        "koji_keika": (
            data_root
            / "工事の検索（入札の経過）"
            / "01_通常ダウンロード"
        ),
        "gyomu_keika": (
            data_root
            / "業務の検索（入札の経過）"
            / "01_通常ダウンロード"
        ),
    }
    for search_target, run_root in roots.items():
        _append_download(
            run_root,
            url=f"https://example.test/{search_target}",
            include_fine=False,
            layout_version=4,
            search_target=search_target,
        )
    resolved_targets: list[str] = []

    def resolver(query):
        resolved_targets.append(query.search_target)
        return ({"label": "飯田国道事務所", "code": "000007"},)

    service, _guard = _service(resolver=resolver)
    plan = service.scan(_config(data_root, layout_version=4))

    assert plan.actionable_count == 2
    assert resolved_targets == ["koji_keika", "gyomu_keika"]


def test_apply_moves_atomically_appends_history_and_new_path_is_reused(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, original = _append_download(
        run_root,
        url="https://example.test/document",
    )
    service, _ = _service()
    plan = service.scan(_config(data_root))
    candidate = plan.candidates[0]

    result = service.apply(plan)

    assert result.moved_count == 1
    assert result.failed_count == 0
    assert not source.exists()
    assert candidate.target_path.read_bytes() == PDF_BYTES
    assert not (run_root / "99_分類未解決").exists()
    assert not (run_root / service.JOURNAL_NAME).exists()

    records = [
        json.loads(line)
        for line in (run_root / DownloadHistory.FILE_NAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(records) == 2
    appended = records[-1]
    assert records[0] == original
    assert appended["path"] == candidate.target_path.relative_to(
        run_root
    ).as_posix()
    assert appended["reclassified_from_path"] == source.relative_to(
        run_root
    ).as_posix()
    assert appended["agency_path"]["version"] == 2
    assert (
        appended["agency_path"]["resolution"]["reason_code"]
        == "OFFICE_LABEL_MATCH"
    )

    history = DownloadHistory(run_root, _Logger(), layout_version=3)
    lookup = history.lookup(
        str(original["url"]),
        candidate.target_path,
        ".pdf",
        allow_legacy_alias=False,
    )
    assert lookup.match is not None
    assert lookup.match.path == candidate.target_path

    # append-onlyで残る旧成功行を、次回scanで欠損候補へ戻さない。
    second_plan = service.scan(_config(data_root))
    assert second_plan.candidates == ()


def test_three_level_path_uses_injected_resolver_only_on_unique_label(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    _append_download(
        run_root,
        url="https://example.test/three-level",
        include_fine=False,
    )
    received = []

    def unique_resolver(query):
        received.append(query)
        return (
            {
                "level": "saibunrui",
                "label": "飯田国道事務所",
                "code": "000007",
            },
            {
                "level": "saibunrui",
                "label": "名古屋国道事務所",
                "code": "000008",
            },
        )

    unique_service, _ = _service(resolver=unique_resolver)
    unique_plan = unique_service.scan(_config(data_root))

    assert unique_plan.actionable_count == 1
    assert unique_plan.candidates[0].new_agency_segments[-1].label == (
        "飯田国道事務所"
    )
    assert unique_plan.candidates[0].project_name == "令和6年度 テスト工事"
    assert (
        unique_plan.candidates[0].target_path.parts.count("飯田国道事務所")
        == 1
    )
    assert unique_plan.candidates[0].reason_code == (
        "RECLASSIFICATION_READY_MOVE"
    )
    assert received[0].office_name == "飯田国道事務所"
    assert len(received[0].parent_segments) == 3

    def ambiguous_resolver(_query):
        return (
            {"label": "飯田国道事務所", "code": "1"},
            {"label": "飯田国道事務所（本所）", "code": "2"},
        )

    ambiguous_service, _ = _service(resolver=ambiguous_resolver)
    ambiguous = ambiguous_service.scan(_config(data_root)).candidates[0]
    assert ambiguous.state is ReclassificationCandidateState.UNRESOLVED
    assert ambiguous.reason_code == "RECLASSIFICATION_OFFICE_NOT_UNIQUE"


def test_legacy_v1_three_level_layout_does_not_consume_project_as_office(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    _append_download(
        run_root,
        url="https://example.test/legacy-three-level",
        include_fine=False,
        agency_path_version=1,
        include_office_fallback=False,
    )

    service, _ = _service(
        resolver=lambda _query: (
            {"label": "飯田国道事務所", "code": "000007"},
        )
    )
    candidate = service.scan(_config(data_root)).candidates[0]

    assert candidate.actionable
    assert candidate.project_name == "令和6年度 テスト工事"
    assert candidate.target_path.parts.count("飯田国道事務所") == 1


def test_complete_path_does_not_compare_site_hachusha_id_to_tree_codes(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    _append_download(
        run_root,
        url="https://example.test/current-site-id",
        # Web treeの階層codeとHachushaIdは同じ体系とは限らない。
        agency_id="02105000",
    )
    service, _ = _service()

    candidate = service.scan(_config(data_root)).candidates[0]

    assert candidate.actionable


def test_complete_path_without_office_requires_exact_legacy_fine_id(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    matched_root = data_root / "01_通常ダウンロード"
    _append_download(
        matched_root,
        url="https://example.test/legacy-fine-id",
        office_name="",
        agency_id="000007",
    )
    service, _ = _service()

    matched = service.scan(_config(data_root)).candidates[0]

    assert matched.actionable
    applied = service.apply(
        service.scan(_config(data_root)),
        [matched.candidate_id],
    )
    assert applied.moved_count == 1
    appended = json.loads(
        (matched_root / DownloadHistory.FILE_NAME)
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert (
        appended["agency_path"]["resolution"]["reason_code"]
        == "LEGACY_ID_MATCH"
    )

    # 一致しないHachushaIdへ書き換えた別fixtureでは安全側に未解決とする。
    other_root = tmp_path / "other-downloads"
    _append_download(
        other_root / "01_通常ダウンロード",
        url="https://example.test/no-detail-match",
        office_name="",
        agency_id="02105000",
    )
    unresolved = service.scan(_config(other_root)).candidates[0]
    assert unresolved.state is ReclassificationCandidateState.UNRESOLVED
    assert unresolved.reason_code == "AGENCY_DETAIL_MISSING"


@pytest.mark.parametrize(
    ("payload", "recorded_payload"),
    [
        (PDF_BYTES + b"changed", PDF_BYTES),
        (b"<html>error</html>", None),
    ],
)
def test_scan_rejects_size_hash_or_signature_mismatch(
    tmp_path: Path,
    payload: bytes,
    recorded_payload: bytes | None,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/invalid",
        payload=payload,
        recorded_payload=recorded_payload,
    )
    service, _ = _service()

    candidate = service.scan(_config(data_root)).candidates[0]

    assert candidate.state is ReclassificationCandidateState.INVALID
    assert candidate.reason_code == "RECLASSIFICATION_SOURCE_INVALID"
    assert source.exists()


def test_identical_target_is_canonical_but_source_is_preserved(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/identical",
    )
    service, _ = _service()
    first_plan = service.scan(_config(data_root))
    target = first_plan.candidates[0].target_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PDF_BYTES)
    original_stat = target.stat()

    plan = service.scan(_config(data_root))
    candidate = plan.candidates[0]
    assert candidate.state is ReclassificationCandidateState.READY_TARGET_REUSE

    result = service.apply(plan)

    assert result.target_reused_count == 1
    assert result.reused_count == 1
    assert source.read_bytes() == PDF_BYTES
    assert target.read_bytes() == PDF_BYTES
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert "旧ファイルは削除せず保持" in result.outcomes[0].reason
    assert not (run_root / service.JOURNAL_NAME).exists()
    # targetの成功履歴を正本とし、保持した旧sourceは再候補にしない。
    assert service.scan(_config(data_root)).candidates == ()
    # 正本が後から失われた場合は、保持していた検証済みsourceを再び候補に
    # できる。履歴のSUCCESS文字列だけでは旧pathを抑止しない。
    target.unlink()
    recovered = service.scan(_config(data_root))
    assert recovered.actionable_count == 1
    assert recovered.candidates[0].source_path == source


def test_different_target_is_conflict_and_neither_file_is_changed(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/conflict",
    )
    service, _ = _service()
    target = service.scan(_config(data_root)).candidates[0].target_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4\ndifferent\n%%EOF\n")

    plan = service.scan(_config(data_root))
    candidate = plan.candidates[0]
    result = service.apply(plan, [candidate.candidate_id])

    assert candidate.state is ReclassificationCandidateState.CONFLICT
    assert result.conflict_count == 1
    assert source.read_bytes() == PDF_BYTES
    assert target.read_bytes() != PDF_BYTES


def test_cancel_after_move_rolls_file_back_and_removes_journal(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/cancel",
    )
    service, _ = _service()
    plan = service.scan(_config(data_root))
    target = plan.candidates[0].target_path
    checks = 0

    def cancel_check() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    result = service.apply(plan, cancel_check=cancel_check)

    assert result.cancelled
    assert result.cancelled_count == 1
    assert source.read_bytes() == PDF_BYTES
    assert not target.exists()
    assert not (run_root / service.JOURNAL_NAME).exists()


def test_history_append_failure_rolls_move_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/history-failure",
    )
    service, _ = _service()
    plan = service.scan(_config(data_root))
    target = plan.candidates[0].target_path

    def fail_append(*_args, **_kwargs):
        raise OSError("history unavailable")

    monkeypatch.setattr(DownloadHistory, "append_record", fail_append)
    result = service.apply(plan)

    assert result.failed_count == 1
    assert source.read_bytes() == PDF_BYTES
    assert not target.exists()
    assert not (run_root / service.JOURNAL_NAME).exists()


def test_prepared_journal_recovers_rename_done_before_state_update(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/recovery",
    )
    service, _ = _service()
    plan = service.scan(_config(data_root))
    candidate = plan.candidates[0]
    history = DownloadHistory(run_root, _Logger(), layout_version=3)
    transaction_id = "a" * 32
    record = service._reclassified_record(
        candidate,
        history,
        transaction_id,
    )
    journal = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "state": "PREPARED",
        "operation": "MOVE",
        "source_path": history.stored_path(source),
        "target_path": history.stored_path(candidate.target_path),
        "staging_path": "",
        "history_path": DownloadHistory.FILE_NAME,
        "history_record": record,
        "created_at": "2026-08-20T00:00:00+00:00",
    }
    service._write_journal(run_root, journal)
    candidate.target_path.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, candidate.target_path)

    recovered = service.scan(_config(data_root))

    assert source.read_bytes() == PDF_BYTES
    assert not candidate.target_path.exists()
    assert not (run_root / service.JOURNAL_NAME).exists()
    assert recovered.actionable_count == 1


def test_committed_history_finishes_stale_journal_on_next_scan(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/committed-recovery",
    )
    service, _ = _service()
    candidate = service.scan(_config(data_root)).candidates[0]
    history = DownloadHistory(run_root, _Logger(), layout_version=3)
    transaction_id = "b" * 32
    record = service._reclassified_record(
        candidate,
        history,
        transaction_id,
    )
    journal = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "state": "FILE_MOVED",
        "operation": "MOVE",
        "source_path": history.stored_path(source),
        "target_path": history.stored_path(candidate.target_path),
        "staging_path": "",
        "history_path": DownloadHistory.FILE_NAME,
        "history_record": record,
        "created_at": "2026-08-20T00:00:00+00:00",
    }
    service._write_journal(run_root, journal)
    candidate.target_path.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, candidate.target_path)
    history.append_record(record, durable=True)

    recovered = service.scan(_config(data_root))

    assert candidate.target_path.read_bytes() == PDF_BYTES
    assert not source.exists()
    assert not (run_root / service.JOURNAL_NAME).exists()
    assert recovered.candidates == ()


def test_execution_lock_and_scan_cancellation_do_not_modify_files(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/locked",
    )
    unlocked, _ = _service()
    plan = unlocked.scan(_config(data_root))

    locked, guard = _service(acquired=False)
    result = locked.apply(plan)
    cancelled = unlocked.scan(_config(data_root), cancel_check=lambda: True)

    assert result.outcomes[0].status is ReclassificationApplyStatus.LOCKED
    assert source.read_bytes() == PDF_BYTES
    assert cancelled.cancelled
    assert cancelled.candidates == ()
    assert guard.entries == 1


def test_candidate_outcome_and_summary_are_structured_without_error_duplication(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    _append_download(
        run_root,
        url="https://example.test/logging",
    )
    logger = _Logger()
    service = ReclassificationService(
        logger=logger,
        run_guard=_Guard(),
    )

    plan = service.scan(_config(data_root))
    result = service.apply(plan)

    assert result.moved_count == 1
    assert any(
        line.startswith("reclassification.scan.candidate ")
        and '"run_kind": "MANUAL"' in line
        and '"reason_code": "RECLASSIFICATION_READY_MOVE"' in line
        for line in logger.infos
    )
    assert any(
        line.startswith("reclassification.apply.outcome ")
        and '"source_preserved": false' in line
        and '"status": "MOVED"' in line
        for line in logger.infos
    )
    assert any(
        line.startswith("reclassification.apply.summary ")
        for line in logger.infos
    )
    assert logger.errors == []


def test_stale_plan_is_invalid_and_does_not_move_file(tmp_path: Path):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, record = _append_download(
        run_root,
        url="https://example.test/stale",
    )
    service, _ = _service()
    plan = service.scan(_config(data_root))
    target = plan.candidates[0].target_path
    newer = dict(record)
    newer.update(
        {
            "status": "FAILED",
            "reason_code": "SAVE_FAILED",
            "completed_at": "2026-08-20T01:00:00+00:00",
        }
    )
    with (run_root / DownloadHistory.FILE_NAME).open(
        "a", encoding="utf-8", newline="\n"
    ) as stream:
        stream.write(json.dumps(newer, ensure_ascii=False) + "\n")

    result = service.apply(plan)

    assert result.invalid_count == 1
    assert result.outcomes[0].reason_code == "STALE_PLAN"
    assert source.read_bytes() == PDF_BYTES
    assert not target.exists()
    assert not (run_root / service.JOURNAL_NAME).exists()


def test_stale_plan_detects_new_success_when_document_id_changed(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, record = _append_download(
        run_root,
        url="https://example.test/stale-document-id",
    )
    service, _ = _service()
    plan = service.scan(_config(data_root))
    target = plan.candidates[0].target_path
    newer = dict(record)
    newer.update(
        {
            "document_id": "changed-id",
            "document_name": "更新後の文書名",
            "completed_at": "2026-08-20T02:00:00+00:00",
        }
    )
    with (run_root / DownloadHistory.FILE_NAME).open(
        "a", encoding="utf-8", newline="\n"
    ) as stream:
        stream.write(json.dumps(newer, ensure_ascii=False) + "\n")

    result = service.apply(plan)

    assert result.invalid_count == 1
    assert result.outcomes[0].reason_code == "STALE_PLAN"
    assert source.read_bytes() == PDF_BYTES
    assert not target.exists()


def test_stale_plan_detects_other_process_target_reuse_record(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/stale-reuse",
    )
    service, _ = _service()
    plan = service.scan(_config(data_root))
    candidate = plan.candidates[0]
    candidate.target_path.parent.mkdir(parents=True, exist_ok=True)
    candidate.target_path.write_bytes(PDF_BYTES)
    history = DownloadHistory(run_root, _Logger(), layout_version=3)
    other_record = service._reclassified_record(
        candidate,
        history,
        "f" * 32,
    )
    history.append_record(other_record, durable=True)
    lines_before = len(
        history.path.read_text(encoding="utf-8").splitlines()
    )

    result = service.apply(plan)

    assert result.invalid_count == 1
    assert result.outcomes[0].reason_code == "STALE_PLAN"
    assert source.read_bytes() == PDF_BYTES
    assert candidate.target_path.read_bytes() == PDF_BYTES
    assert len(history.path.read_text(encoding="utf-8").splitlines()) == (
        lines_before
    )


def test_cancelled_preview_is_never_applied(tmp_path: Path):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/incomplete-plan",
    )
    service, guard = _service()
    complete = service.scan(_config(data_root))
    incomplete = replace(complete, cancelled=True)
    entries_before_apply = guard.entries

    result = service.apply(incomplete)

    assert result.cancelled
    assert result.skipped_count == 1
    assert result.issues[0].reason_code == (
        "RECLASSIFICATION_PLAN_INCOMPLETE"
    )
    assert source.read_bytes() == PDF_BYTES
    assert guard.entries == entries_before_apply


def test_resolver_is_single_flight_per_parent_within_each_scan(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    _append_download(
        run_root,
        url="https://example.test/office-1",
        include_fine=False,
        document_id="40",
        office_name="飯田国道事務所",
    )
    _append_download(
        run_root,
        url="https://example.test/office-2",
        include_fine=False,
        document_id="41",
        office_name="名古屋国道事務所",
    )
    calls = 0

    def resolver(_query):
        nonlocal calls
        calls += 1
        return (
            {"label": "飯田国道事務所", "code": "7"},
            {"label": "名古屋国道事務所", "code": "8"},
        )

    service, _ = _service(resolver=resolver)

    first = service.scan(_config(data_root))
    second = service.scan(_config(data_root))

    assert first.actionable_count == 2
    assert second.actionable_count == 2
    assert calls == 2  # 各scanで1回。scanをまたぐ永続cacheは作らない。


def test_resolver_failure_is_cached_for_same_parent_only_during_scan(
    tmp_path: Path,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    for index, office in enumerate(
        ("飯田国道事務所", "名古屋国道事務所"),
        start=1,
    ):
        _append_download(
            run_root,
            url=f"https://example.test/failure-{index}",
            include_fine=False,
            document_id=str(50 + index),
            office_name=office,
        )
    calls = 0

    def resolver(_query):
        nonlocal calls
        calls += 1
        raise RuntimeError("temporary catalog failure")

    service, _ = _service(resolver=resolver)
    plan = service.scan(_config(data_root))

    assert calls == 1
    assert len(plan.candidates) == 2
    assert all(
        candidate.reason_code == "RECLASSIFICATION_RESOLVER_FAILED"
        for candidate in plan.candidates
    )


@pytest.mark.parametrize(
    "broken_field",
    [
        "history_path",
        "reclassification_id",
        "target_path",
        "reclassified_from_path",
    ],
)
def test_invalid_journal_contract_is_retained_for_diagnosis(
    tmp_path: Path,
    broken_field: str,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url=f"https://example.test/journal-{broken_field}",
    )
    service, _ = _service()
    candidate = service.scan(_config(data_root)).candidates[0]
    history = DownloadHistory(run_root, _Logger(), layout_version=3)
    transaction_id = "c" * 32
    record = service._reclassified_record(
        candidate,
        history,
        transaction_id,
    )
    journal = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "state": "PREPARED",
        "operation": "MOVE",
        "source_path": history.stored_path(source),
        "target_path": history.stored_path(candidate.target_path),
        "staging_path": "",
        "history_path": DownloadHistory.FILE_NAME,
        "history_record": record,
        "created_at": "2026-08-20T00:00:00+00:00",
    }
    if broken_field == "history_path":
        journal["history_path"] = "other.jsonl"
    elif broken_field == "reclassification_id":
        record["reclassification_id"] = "d" * 32
    elif broken_field == "target_path":
        record["target_path"] = history.stored_path(source)
    else:
        record["reclassified_from_path"] = history.stored_path(
            candidate.target_path
        )
    service._write_journal(run_root, journal)

    plan = service.scan(_config(data_root))

    assert any(
        issue.reason_code == "RECLASSIFICATION_RECOVERY_FAILED"
        for issue in plan.issues
    )
    assert source.read_bytes() == PDF_BYTES
    assert (run_root / service.JOURNAL_NAME).is_file()


@pytest.mark.parametrize("state", ["corrupt_target", "both_exist"])
def test_ambiguous_or_invalid_rollback_keeps_journal_and_files(
    tmp_path: Path,
    state: str,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url=f"https://example.test/unsafe-rollback-{state}",
    )
    service, _ = _service()
    candidate = service.scan(_config(data_root)).candidates[0]
    history = DownloadHistory(run_root, _Logger(), layout_version=3)
    transaction_id = "e" * 32
    record = service._reclassified_record(
        candidate,
        history,
        transaction_id,
    )
    journal = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "state": "PREPARED",
        "operation": "MOVE",
        "source_path": history.stored_path(source),
        "target_path": history.stored_path(candidate.target_path),
        "staging_path": "",
        "history_path": DownloadHistory.FILE_NAME,
        "history_record": record,
        "created_at": "2026-08-20T00:00:00+00:00",
    }
    service._write_journal(run_root, journal)
    candidate.target_path.parent.mkdir(parents=True, exist_ok=True)
    if state == "corrupt_target":
        os.rename(source, candidate.target_path)
        candidate.target_path.write_bytes(b"not the recorded PDF")
    else:
        candidate.target_path.write_bytes(PDF_BYTES)

    recovered = service.scan(_config(data_root))

    assert any(
        issue.reason_code == "RECLASSIFICATION_RECOVERY_FAILED"
        for issue in recovered.issues
    )
    assert (run_root / service.JOURNAL_NAME).is_file()
    if state == "corrupt_target":
        assert not source.exists()
        assert candidate.target_path.read_bytes() == b"not the recorded PDF"
    else:
        assert source.read_bytes() == PDF_BYTES
        assert candidate.target_path.read_bytes() == PDF_BYTES


def test_reparse_source_or_target_is_rejected_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url="https://example.test/reparse",
    )
    service, _ = _service()
    plan = service.scan(_config(data_root))
    target = plan.candidates[0].target_path
    original_check = ReclassificationService._path_is_reparse

    def fake_reparse(path: Path) -> bool:
        return Path(path) == target or original_check(path)

    monkeypatch.setattr(
        ReclassificationService,
        "_path_is_reparse",
        staticmethod(fake_reparse),
    )

    result = service.apply(plan)

    assert result.failed_count == 1
    assert source.read_bytes() == PDF_BYTES
    assert not target.exists()
    assert not (run_root / service.JOURNAL_NAME).exists()


def test_unc_data_root_is_rejected_without_access():
    service, _ = _service()
    config = _config(Path(r"\\server\share\downloads"))

    plan = service.scan(config)

    assert plan.candidates == ()
    assert plan.issues[0].reason_code == "RECLASSIFICATION_CONFIG_INVALID"


@pytest.mark.parametrize("link_kind", ["source_file", "target_directory"])
def test_real_in_root_symlink_is_rejected_before_file_operation(
    tmp_path: Path,
    link_kind: str,
):
    data_root = tmp_path / "downloads"
    run_root = data_root / "01_通常ダウンロード"
    source, _ = _append_download(
        run_root,
        url=f"https://example.test/symlink-{link_kind}",
    )
    logger = _Logger()
    service = ReclassificationService(
        logger=logger,
        run_guard=_Guard(),
    )
    initial = service.scan(_config(data_root))
    target = initial.candidates[0].target_path

    try:
        if link_kind == "source_file":
            backing = source.with_name("verified-backing.pdf")
            os.rename(source, backing)
            source.symlink_to(backing)
        else:
            link = run_root / "国の機関"
            backing = run_root / "real-agency-root"
            backing.mkdir()
            link.symlink_to(backing, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"この環境ではsymlinkを作成できません: {exc}")

    plan = service.scan(_config(data_root))

    if link_kind == "source_file":
        assert plan.candidates == ()
        assert source.is_symlink()
    else:
        assert len(plan.candidates) == 1
        assert plan.candidates[0].state is (
            ReclassificationCandidateState.INVALID
        )
        assert plan.candidates[0].reason_code == (
            "RECLASSIFICATION_PATH_UNSAFE"
        )
        assert source.read_bytes() == PDF_BYTES
        assert not target.exists()
