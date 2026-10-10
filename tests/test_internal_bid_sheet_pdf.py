# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pypdf import PdfReader
from bs4 import BeautifulSoup

from src.core.bid_sheet_pdf import (
    InternalBidSheetPdfRenderer,
    default_font_path,
    parse_bid_sheet_document,
)
from src.core.html_to_pdf import validate_and_sanitize_bid_sheet_html
from src.core.pdf_conversion_audit import (
    PdfConversionAudit,
    PdfConversionContext,
)


SOURCE_URL = (
    "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet"
    "?AnkenKanriNo=021020002025412000000566&BunshoKanriId=40"
)
PROJECT_NAME = "志津地すべり排水トンネル第３期工事"


def _prepared_fixture() -> str:
    source = Path("tests/fixtures/id40_bid_sheet.html").read_text(encoding="utf-8")
    prepared = validate_and_sanitize_bid_sheet_html(
        source,
        source_url=SOURCE_URL,
        document_name="入札調書",
        project_name=PROJECT_NAME,
    )
    assert prepared.success
    return prepared.sanitized_html


def test_internal_renderer_creates_a4_pdf_with_all_bid_rows(tmp_path):
    html = _prepared_fixture()
    document = parse_bid_sheet_document(html, project_name=PROJECT_NAME)
    detail = next(table for table in document.tables if table.detail)
    assert len(detail.rows) == 14

    output = tmp_path / "bid-sheet.pdf.part"
    renderer = InternalBidSheetPdfRenderer(
        font_path=default_font_path(),
        timeout_seconds=10,
    )
    result = renderer.render(html, output, project_name=PROJECT_NAME)

    assert result.success
    assert result.bytes_written == output.stat().st_size
    assert result.page_count >= 1
    reader = PdfReader(str(output), strict=True)
    extracted = "".join(page.extract_text() or "" for page in reader.pages)
    assert PROJECT_NAME in extracted
    assert "村本建設株式会社" in extracted
    assert "1,727,700,000円" in extracted
    assert "落札" in extracted


def test_model_preserves_variable_columns_and_spans():
    soup = BeautifulSoup(_prepared_fixture(), "html.parser")
    summary_header = soup.find("th", class_="list_th3")
    assert summary_header is not None
    summary_header["colspan"] = "2"
    html = str(soup)
    document = parse_bid_sheet_document(html, project_name=PROJECT_NAME)
    detail = next(table for table in document.tables if table.detail)
    assert detail.rows[0][-1].colspan == 2


def test_pdf_audit_and_failure_artifact_are_readable_after_restart(tmp_path):
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    audit = PdfConversionAudit(tmp_path, clock=lambda: now.timestamp())
    context = PdfConversionContext(
        run_id="run-1",
        conversion_id="a" * 32,
        project_name=PROJECT_NAME,
        document_name="入札調書",
        document_id="40",
    )
    audit.record(context, "conversion_started", renderer="internal")
    artifact = audit.store_failure(
        context,
        "<html><body>sanitized</body></html>",
        {"reason_code": "TEST_FAILURE"},
    )

    assert artifact is not None
    record = json.loads(
        (tmp_path / "pdf-conversions-2026-09-14.jsonl").read_text(encoding="utf-8")
    )
    assert record["run_id"] == "run-1"
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["expires_at_utc"].startswith("2026-10-14")
    assert (artifact / "input.sanitized.html").is_file()

    expired_time = now + timedelta(days=31)
    restarted = PdfConversionAudit(tmp_path, clock=lambda: expired_time.timestamp())
    assert restarted.purge_expired() == (0, 1)
    assert not artifact.exists()
