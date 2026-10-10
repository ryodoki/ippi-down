# -*- coding: utf-8 -*-

"""検証済み入札調書をブラウザーに依存せずPDFへ変換する。"""

from __future__ import annotations

import hashlib
import html as html_module
import multiprocessing
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from bs4 import BeautifulSoup

from ..models.download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadStage,
)


CancelCheck = Optional[Callable[[], bool]]
_A4_WIDTH = 595.275590551
_A4_HEIGHT = 841.88976378


def _normalise(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _bounded_span(value: object) -> int:
    try:
        return max(1, min(int(str(value or "1")), 32))
    except (TypeError, ValueError):
        return 1


@dataclass(frozen=True)
class BidSheetCell:
    """入札調書の1セル。"""

    text: str
    header: bool = False
    rowspan: int = 1
    colspan: int = 1


@dataclass(frozen=True)
class BidSheetTable:
    """元HTMLの並びとセル結合を保持した表。"""

    rows: Tuple[Tuple[BidSheetCell, ...], ...]
    detail: bool = False


@dataclass(frozen=True)
class BidSheetDocument:
    """PDF描画に渡す、実行可能要素を持たない入札調書モデル。"""

    title: str
    project_name: str
    tables: Tuple[BidSheetTable, ...]
    notes: Tuple[str, ...]
    source_sha256: str

    @property
    def validation_tokens(self) -> Tuple[str, ...]:
        """PDFへ必ず現れるべき文字列を重複なしで返す。"""

        tokens: list[str] = []
        seen: set[str] = set()
        for value in (
            self.title,
            self.project_name,
            *(cell.text for table in self.tables for row in table.rows for cell in row),
            *self.notes,
        ):
            token = _normalise(value)
            if token and token not in seen:
                seen.add(token)
                tokens.append(token)
        return tuple(tokens)


@dataclass(frozen=True)
class InternalPdfResult:
    """内蔵PDF生成器の終端結果。"""

    success: bool
    cancelled: bool = False
    elapsed_seconds: float = 0.0
    bytes_written: int = 0
    sha256: str = ""
    page_count: int = 0
    issue: Optional[DownloadIssue] = None


class BidSheetModelError(ValueError):
    """既知の入札調書モデルへ安全に変換できない。"""


def parse_bid_sheet_document(
    sanitized_html: str,
    *,
    project_name: str,
    max_tables: int = 32,
    max_rows: int = 5000,
    max_cells: int = 20000,
) -> BidSheetDocument:
    """無害化済みHTMLを可変行・可変列の帳票モデルへ変換する。"""

    soup = BeautifulSoup(sanitized_html, "html.parser")
    heading = soup.find("h1")
    title = heading.get_text(" ", strip=True) if heading else ""
    if "入札調書" not in _normalise(title):
        raise BidSheetModelError("入札調書の見出しを取得できません")

    tables: list[BidSheetTable] = []
    row_count = 0
    cell_count = 0
    for table_tag in soup.find_all("table"):
        rows: list[Tuple[BidSheetCell, ...]] = []
        for row_tag in table_tag.find_all("tr"):
            # 入れ子表の行を親表で二重に数えない。
            if row_tag.find_parent("table") is not table_tag:
                continue
            cells: list[BidSheetCell] = []
            for cell_tag in row_tag.find_all(["th", "td"], recursive=False):
                cells.append(
                    BidSheetCell(
                        text=cell_tag.get_text(" ", strip=True),
                        header=cell_tag.name.casefold() == "th",
                        rowspan=_bounded_span(cell_tag.get("rowspan")),
                        colspan=_bounded_span(cell_tag.get("colspan")),
                    )
                )
            if cells:
                rows.append(tuple(cells))
                row_count += 1
                cell_count += len(cells)
            if row_count > max_rows or cell_count > max_cells:
                raise BidSheetModelError("入札調書の表が処理上限を超えています")
        if not rows:
            continue
        header_text = _normalise("".join(cell.text for cell in rows[0]))
        detail = "業者名" in header_text and "金額" in header_text
        tables.append(BidSheetTable(tuple(rows), detail=detail))
        if len(tables) > max_tables:
            raise BidSheetModelError("入札調書の表数が処理上限を超えています")

    if not tables or not any(table.detail for table in tables):
        raise BidSheetModelError("業者別の入札明細表を取得できません")
    if _normalise(project_name) not in {
        _normalise(cell.text) for table in tables for row in table.rows for cell in row
    }:
        raise BidSheetModelError("入札調書の件名を帳票モデルで確認できません")

    notes: list[str] = []
    for paragraph in soup.find_all("p"):
        value = paragraph.get_text(" ", strip=True)
        if value and value not in notes:
            notes.append(value)

    return BidSheetDocument(
        title=title,
        project_name=project_name,
        tables=tuple(tables),
        notes=tuple(notes),
        source_sha256=hashlib.sha256(sanitized_html.encode("utf-8")).hexdigest(),
    )


def _build_grid(
    rows: Sequence[Sequence[BidSheetCell]],
) -> tuple[list[list[Optional[BidSheetCell]]], list[tuple]]:
    """HTMLのrowspan/colspanをReportLab用gridとSPANへ変換する。"""

    grid: list[list[Optional[BidSheetCell]]] = []
    spans: list[tuple] = []
    occupied: set[tuple[int, int]] = set()
    maximum_columns = 0
    for row_index, source_row in enumerate(rows):
        row: list[Optional[BidSheetCell]] = []
        column = 0
        for cell in source_row:
            while (row_index, column) in occupied:
                while len(row) <= column:
                    row.append(None)
                column += 1
            while len(row) <= column:
                row.append(None)
            row[column] = cell
            end_column = column + cell.colspan - 1
            end_row = row_index + cell.rowspan - 1
            if end_column != column or end_row != row_index:
                spans.append(("SPAN", (column, row_index), (end_column, end_row)))
            for covered_row in range(row_index, end_row + 1):
                for covered_column in range(column, end_column + 1):
                    if covered_row != row_index or covered_column != column:
                        occupied.add((covered_row, covered_column))
            column = end_column + 1
        maximum_columns = max(maximum_columns, column)
        grid.append(row)
    for row_index in range(len(grid)):
        grid[row_index].extend([None] * (maximum_columns - len(grid[row_index])))
    return grid, spans


def _column_widths(
    grid: Sequence[Sequence[Optional[BidSheetCell]]], width: float
) -> list[float]:
    columns = max((len(row) for row in grid), default=1)
    weights = [4.0] * columns
    for row in grid:
        for index, cell in enumerate(row):
            if cell is None or cell.colspan > 1:
                continue
            length = max((len(line) for line in cell.text.splitlines()), default=0)
            weights[index] = max(weights[index], min(float(length), 40.0))
    total = sum(weights) or 1.0
    return [width * item / total for item in weights]


def _render_reportlab(
    document: BidSheetDocument,
    output_path: Path,
    font_path: Path,
) -> None:
    """隔離ワーカー内でのみ呼ばれるReportLab描画本体。"""

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        LongTable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    font_name = "IppiNotoSansJP"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path), validate=1))

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "IppiTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=16,
        leading=21,
        alignment=TA_CENTER,
        wordWrap="CJK",
        spaceAfter=5 * mm,
    )
    cell_style = ParagraphStyle(
        "IppiCell",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=8.5,
        leading=11,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )
    note_style = ParagraphStyle(
        "IppiNote",
        parent=cell_style,
        fontSize=8,
        leading=10,
        spaceBefore=2 * mm,
    )
    document_template = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=document.title,
        subject=document.project_name,
        creator="ippi-down internal PDF renderer",
        pageCompression=1,
    )
    usable_width = A4[0] - 20 * mm
    story = [Paragraph(html_module.escape(document.title), title_style)]
    for table_model in document.tables:
        source_grid, spans = _build_grid(table_model.rows)
        rendered_grid: list[list[object]] = []
        header_coordinates: list[tuple[int, int]] = []
        for row_index, row in enumerate(source_grid):
            rendered_row: list[object] = []
            for column_index, cell in enumerate(row):
                if cell is None:
                    rendered_row.append("")
                    continue
                rendered_row.append(
                    Paragraph(html_module.escape(cell.text), cell_style)
                )
                if cell.header:
                    header_coordinates.append((column_index, row_index))
            rendered_grid.append(rendered_row)
        repeat_rows = 1 if table_model.detail else 0
        table_class = LongTable if table_model.detail else Table
        table = table_class(
            rendered_grid,
            colWidths=_column_widths(source_grid, usable_width),
            repeatRows=repeat_rows,
            hAlign="LEFT",
            splitByRow=1,
        )
        commands: list[tuple] = [
            ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            *spans,
        ]
        for coordinate in header_coordinates:
            commands.append(
                ("BACKGROUND", coordinate, coordinate, colors.HexColor("#E6E6E6"))
            )
        table.setStyle(TableStyle(commands))
        story.extend((table, Spacer(1, 3 * mm)))
    for note in document.notes:
        story.append(Paragraph(html_module.escape(note), note_style))
    document_template.build(story)


def _worker_entry(
    connection,
    document: BidSheetDocument,
    output_path: str,
    font_path: str,
) -> None:
    try:
        _render_reportlab(document, Path(output_path), Path(font_path))
        connection.send(("ok", ""))
    except BaseException as exc:
        # 案件本文やパスを親へ返さない。
        connection.send(("error", type(exc).__name__))
    finally:
        connection.close()


def validate_generated_pdf(
    output_path: Path,
    document: BidSheetDocument,
) -> tuple[int, int, str]:
    """PDF構造、用紙、帳票の全文字列を再読込して検証する。"""

    from pypdf import PdfReader

    if not output_path.is_file():
        raise ValueError("PDFファイルが生成されませんでした")
    size = output_path.stat().st_size
    if size <= 0:
        raise ValueError("生成されたPDFファイルが空です")
    reader = PdfReader(str(output_path), strict=True)
    if reader.is_encrypted:
        raise ValueError("生成されたPDFが暗号化されています")
    if not 1 <= len(reader.pages) <= 100:
        raise ValueError("生成されたPDFのページ数が不正です")
    extracted_parts: list[str] = []
    for page in reader.pages:
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        if width > height or abs(width - _A4_WIDTH) > 2 or abs(height - _A4_HEIGHT) > 2:
            raise ValueError("生成されたPDFがA4縦ではありません")
        extracted_parts.append(page.extract_text() or "")
    extracted = _normalise("".join(extracted_parts))
    missing = [token for token in document.validation_tokens if token not in extracted]
    if missing:
        raise ValueError(
            f"PDFから帳票内容を確認できません: missing_count={len(missing)}"
        )
    digest = hashlib.sha256()
    with output_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return size, len(reader.pages), digest.hexdigest()


class InternalBidSheetPdfRenderer:
    """ReportLabを隔離プロセスで監視実行する。"""

    name = "ippi-down internal PDF"

    def __init__(
        self,
        *,
        font_path: Path,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        process_factory: Optional[Callable[..., object]] = None,
    ) -> None:
        self.font_path = Path(font_path)
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.poll_interval = max(0.01, float(poll_interval))
        self._clock = clock
        self._sleep = sleeper
        self._process_factory = process_factory

    @property
    def version(self) -> str:
        try:
            import reportlab

            return f"ReportLab {reportlab.Version}"
        except (ImportError, AttributeError):
            return "ReportLab"

    def render(
        self,
        sanitized_html: str,
        output_path: Path,
        *,
        project_name: str,
        cancel_check: CancelCheck = None,
    ) -> InternalPdfResult:
        started = self._clock()
        try:
            document = parse_bid_sheet_document(
                sanitized_html,
                project_name=project_name,
            )
        except (BidSheetModelError, ValueError) as exc:
            return self._failed(started, "MODEL_INVALID", type(exc).__name__)
        if not self.font_path.is_file():
            return self._failed(started, "FONT_MISSING", "FileNotFoundError")

        output_path.unlink(missing_ok=True)
        parent_connection, child_connection = multiprocessing.Pipe(duplex=False)
        process_factory = self._process_factory or multiprocessing.Process
        process = process_factory(
            target=_worker_entry,
            args=(child_connection, document, str(output_path), str(self.font_path)),
            name="ippi-pdf-renderer",
        )
        try:
            process.start()
            child_connection.close()
            deadline = started + self.timeout_seconds
            while process.is_alive():
                if cancel_check is not None and cancel_check():
                    self._stop(process)
                    output_path.unlink(missing_ok=True)
                    return InternalPdfResult(
                        False,
                        cancelled=True,
                        elapsed_seconds=max(0.0, self._clock() - started),
                        issue=DownloadIssue(
                            DownloadIssueCode.CANCELLED,
                            DownloadStage.CONVERT,
                            "内蔵PDF生成をキャンセルしました",
                        ),
                    )
                if self._clock() >= deadline:
                    self._stop(process)
                    output_path.unlink(missing_ok=True)
                    return self._failed(started, "TIMEOUT", "TimeoutError")
                process.join(
                    timeout=min(self.poll_interval, max(0.01, deadline - self._clock()))
                )
            process.join(timeout=0.2)
            status = (
                parent_connection.recv()
                if parent_connection.poll(0.2)
                else ("error", "WorkerExited")
            )
            if process.exitcode != 0 or status[0] != "ok":
                output_path.unlink(missing_ok=True)
                return self._failed(
                    started, "WORKER_FAILED", str(status[1] or process.exitcode)
                )
            try:
                size, pages, sha256 = validate_generated_pdf(output_path, document)
            except Exception as exc:
                output_path.unlink(missing_ok=True)
                return self._failed(started, "CONTENT_VALIDATION", type(exc).__name__)
            return InternalPdfResult(
                True,
                elapsed_seconds=max(0.0, self._clock() - started),
                bytes_written=size,
                sha256=sha256,
                page_count=pages,
            )
        except (OSError, RuntimeError) as exc:
            self._stop(process)
            output_path.unlink(missing_ok=True)
            return self._failed(started, "START_FAILED", type(exc).__name__)
        finally:
            parent_connection.close()
            try:
                child_connection.close()
            except OSError:
                pass

    @staticmethod
    def _stop(process: object) -> None:
        try:
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
        except (AttributeError, OSError):
            pass

    def _failed(
        self, started: float, reason: str, error_type: str
    ) -> InternalPdfResult:
        code = (
            DownloadIssueCode.PDF_CONTENT_VALIDATION_FAILED
            if reason == "CONTENT_VALIDATION"
            else DownloadIssueCode.PDF_INTERNAL_RENDER_FAILED
        )
        message = (
            "生成PDFの内容を検証できませんでした"
            if code == DownloadIssueCode.PDF_CONTENT_VALIDATION_FAILED
            else "内蔵PDF生成に失敗しました"
        )
        return InternalPdfResult(
            False,
            elapsed_seconds=max(0.0, self._clock() - started),
            issue=DownloadIssue(
                code,
                DownloadStage.CONVERT,
                message,
                details={"reason": reason, "error_type": error_type},
            ),
        )


def default_font_path() -> Path:
    """ソース／PyInstallerのどちらでも同梱フォントを解決する。"""

    import sys

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "src" / "resources" / "fonts" / "NotoSansJP-VF.ttf"
