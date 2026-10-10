# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from src.gui.pdf_conversion_history_dialog import (
    load_pdf_conversion_history,
)


def test_history_reads_only_bounded_completed_conversion_records(tmp_path):
    path = tmp_path / "pdf-conversions-2026-09-14.jsonl"
    rows = [
        {
            "timestamp_utc": "2026-09-14T01:00:00+00:00",
            "conversion_id": "1" * 32,
            "event": "process_heartbeat",
            "process_count": 3,
        },
        {
            "timestamp_utc": "2026-09-14T01:00:01+00:00",
            "conversion_id": "1" * 32,
            "event": "conversion_finished",
            "project_name": "A工事",
            "document_name": "入札調書",
            "renderer": "ippi-down internal PDF",
            "status": "SUCCESS",
            "elapsed_seconds": 1.25,
            "recovery_artifact": False,
        },
        {
            "timestamp_utc": "2026-09-14T02:00:01+00:00",
            "conversion_id": "2" * 32,
            "event": "conversion_finished",
            "project_name": "B工事",
            "document_name": "入札調書",
            "renderer": "Microsoft Edge",
            "status": "FAILED",
            "reason_code": "EDGE_GPU_PROCESS_CRASH",
            "elapsed_seconds": "2.5",
            "recovery_artifact": True,
        },
    ]
    path.write_text(
        "malformed\n"
        + "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    records = load_pdf_conversion_history(tmp_path, limit=1)

    assert len(records) == 1
    assert records[0].project_name == "B工事"
    assert records[0].reason_code == "EDGE_GPU_PROCESS_CRASH"
    assert records[0].recovery_artifact is True


def test_history_ignores_unmanaged_files_and_invalid_conversion_ids(tmp_path):
    (tmp_path / "app.log").write_text("secret", encoding="utf-8")
    (tmp_path / "pdf-conversions-2026-09-14.jsonl").write_text(
        json.dumps(
            {
                "event": "conversion_finished",
                "conversion_id": "../invalid",
                "status": "FAILED",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert load_pdf_conversion_history(tmp_path) == ()


def test_history_reads_highest_rotation_part_before_base_file(tmp_path):
    base = {
        "timestamp_utc": "2026-09-14T01:00:00+00:00",
        "conversion_id": "1" * 32,
        "event": "conversion_finished",
        "project_name": "古い案件",
        "status": "SUCCESS",
    }
    rotated = {
        **base,
        "timestamp_utc": "2026-09-14T02:00:00+00:00",
        "conversion_id": "2" * 32,
        "project_name": "新しい案件",
    }
    (tmp_path / "pdf-conversions-2026-09-14.jsonl").write_text(
        json.dumps(base, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "pdf-conversions-2026-09-14-1.jsonl").write_text(
        json.dumps(rotated, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    records = load_pdf_conversion_history(tmp_path, limit=1)

    assert records[0].project_name == "新しい案件"
