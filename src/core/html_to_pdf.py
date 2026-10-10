# -*- coding: utf-8 -*-

"""入札調書HTMLをMicrosoft Edgeで安全にPDFへ変換する。"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, UnicodeDammit

from ..models.download_diagnostics import (
    DiagnosticValue,
    DownloadIssue,
    DownloadIssueCode,
    DownloadStage,
    IssueSeverity,
)
from .parser.document_classifier import (
    is_html_bid_sheet_candidate,
    is_known_publish_servlet,
)
from .bid_sheet_pdf import (
    InternalBidSheetPdfRenderer,
    default_font_path,
)
from .pdf_conversion_audit import (
    PdfConversionAudit,
    PdfConversionContext,
    new_conversion_id,
)
from .windows_process_supervisor import WindowsJobProcessSupervisor


HtmlSource = Union[str, bytes, Path]
HtmlPayload = Union[str, bytes]
CancelCheck = Optional[Callable[[], bool]]


class HtmlToPdfStatus(str, Enum):
    """HTMLからPDFへの変換結果。"""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class HtmlPreparationResult:
    """入札調書HTMLの検証・無害化結果。"""

    success: bool
    sanitized_html: str = ""
    issues: Tuple[DownloadIssue, ...] = ()

    @property
    def primary_issue(self) -> Optional[DownloadIssue]:
        return _primary_issue(self.issues)

    @property
    def error(self) -> str:
        issue = self.primary_issue
        return issue.message if issue else ""


@dataclass(frozen=True)
class _IsolatedPreparationMetadata:
    """隔離processから返す、HTML本文を含まない検証結果。"""

    success: bool
    issues: Tuple[DownloadIssue, ...] = ()
    sanitized_bytes: int = 0


@dataclass(frozen=True)
class _EdgeVerificationResult:
    """Edge実行ファイルのオフライン署名検証結果。"""

    trusted: bool
    publisher: str = ""
    reason: str = ""
    status_code: int = 0


class _BoundedByteTail:
    """subprocess出力の末尾だけを固定長で保持する。"""

    def __init__(self, max_bytes: int = 4096):
        self._max_bytes = max(1, int(max_bytes))
        self._value = bytearray()
        self._lock = threading.Lock()

    def append(self, value: object) -> None:
        if isinstance(value, str):
            payload = value.encode("utf-8", errors="replace")
        elif isinstance(value, (bytes, bytearray, memoryview)):
            payload = bytes(value)
        else:
            return
        if not payload:
            return
        with self._lock:
            self._value.extend(payload)
            overflow = len(self._value) - self._max_bytes
            if overflow > 0:
                del self._value[:overflow]

    def text(self, max_chars: int = 500) -> str:
        with self._lock:
            payload = bytes(self._value)
        text = payload.decode("utf-8", errors="replace")
        return re.sub(r"[\r\n\t]+", " ", text).strip()[-max_chars:]


@dataclass(frozen=True)
class HtmlToPdfResult:
    """内蔵生成またはMicrosoft Edgeによる変換結果。"""

    status: HtmlToPdfStatus
    output_path: str
    edge_path: str = ""
    edge_version: str = ""
    elapsed_seconds: float = 0.0
    exit_code: Optional[int] = None
    bytes_written: int = 0
    sha256: str = ""
    issues: Tuple[DownloadIssue, ...] = ()
    conversion_id: str = ""
    renderer: str = ""
    renderer_version: str = ""
    recovery_artifact: str = ""

    @property
    def success(self) -> bool:
        return self.status == HtmlToPdfStatus.SUCCESS

    @property
    def cancelled(self) -> bool:
        return self.status == HtmlToPdfStatus.CANCELLED

    @property
    def primary_issue(self) -> Optional[DownloadIssue]:
        return _primary_issue(self.issues)

    @property
    def error(self) -> str:
        issue = self.primary_issue
        return issue.message if issue else ""

    def __bool__(self) -> bool:
        return self.success


def _primary_issue(
    issues: Sequence[DownloadIssue],
) -> Optional[DownloadIssue]:
    return next(
        (issue for issue in issues if issue.severity == IssueSeverity.ERROR),
        issues[0] if issues else None,
    )


def _issue(
    code: DownloadIssueCode,
    stage: DownloadStage,
    message: str,
    *,
    severity: IssueSeverity = IssueSeverity.ERROR,
    details: Optional[Mapping[str, DiagnosticValue]] = None,
) -> DownloadIssue:
    return DownloadIssue(
        code=code,
        stage=stage,
        message=message,
        severity=severity,
        details=dict(details or {}),
    )


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", "", normalized)


def _temporary_root_metadata(name: str) -> Optional[tuple[int, float]]:
    """このconverterが作成した一時rootのPIDと作成UNIX時刻を得る。"""

    match = re.match(
        r"^\.ippi-(?:edge|validation)-p(\d+)-c(\d+)-.+$",
        name,
    )
    if match is None:
        return None
    try:
        return int(match.group(1)), float(match.group(2))
    except ValueError:
        return None


def _is_process_alive_for_cleanup(pid: int) -> bool:
    """PID照会ができない場合は使用中として扱う安全側の判定。"""

    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


_BLOCKED_PAGE_MARKERS = (
    "公開期間外",
    "現在公開されていません",
    "公開されていません",
    "文書が存在しません",
    "該当する情報はありません",
    "システムエラー",
    "エラーが発生しました",
)
_REQUIRED_VALUE_FIELDS = ("所属事務所", "入札日時")
_BID_RESULT_MARKERS = (
    "辞退",
    "無効",
    "不参加",
    "失格",
    "棄権",
    "未入札",
    "入札書不着",
    "予定価格超過",
)
_DEFAULT_MAX_HTML_BYTES = 10 * 1024 * 1024
_TEMPORARY_ROOT_STALE_SECONDS = 24 * 60 * 60
_EDGE_TEMPORARY_ROOT_PREFIX = ".ippi-edge-"
_VALIDATION_TEMPORARY_ROOT_PREFIX = ".ippi-validation-"
_REMOVED_TAGS = ("script", "iframe", "object", "embed")
_RESOURCE_ATTRIBUTES = (
    "src",
    "srcset",
    "href",
    "action",
    "formaction",
    "poster",
    "data",
    "background",
)
_CSS_IMPORT_RE = re.compile(
    r"@import\s+(?:url\([^)]*\)|[\"'][^\"']*[\"'])\s*[^;]*;?",
    flags=re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"url\s*\([^)]*\)", flags=re.IGNORECASE)

_PRINT_STYLE = """
@page {
  size: A4 portrait;
  margin: 10mm;
}
html, body {
  background: #fff !important;
  color: #000 !important;
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
}
body {
  font-family: "Yu Gothic", "Meiryo", sans-serif;
}
""".strip()

_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "style-src 'unsafe-inline'; "
    "img-src data:; "
    "font-src data:; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "object-src 'none'; "
    "base-uri 'none'"
)


def validate_and_sanitize_bid_sheet_html(
    html: str,
    *,
    source_url: str,
    document_name: str,
    project_name: str,
) -> HtmlPreparationResult:
    """既知の入札調書だけを検証し、外部通信不能なHTMLへ無害化する。"""

    context_issue = _validate_conversion_context(
        source_url=source_url,
        document_name=document_name,
        project_name=project_name,
    )
    if context_issue:
        return HtmlPreparationResult(False, issues=(context_issue,))

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.HTML_PARSE_FAILED,
                    DownloadStage.CLASSIFY,
                    "入札調書HTMLを解析できませんでした",
                    details={"error_type": type(exc).__name__},
                ),
            ),
        )

    if soup.html is None:
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.HTML_STRUCTURE_INVALID,
                    DownloadStage.VALIDATE,
                    "HTML文書のルート要素がありません",
                    details={"validation": "html_root"},
                ),
            ),
        )

    page_text = soup.get_text(" ", strip=True)
    normalized_page = _normalize_text(page_text)
    blocked_marker = next(
        (
            marker
            for marker in _BLOCKED_PAGE_MARKERS
            if _normalize_text(marker) in normalized_page
        ),
        "",
    )
    if blocked_marker:
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.HTML_STRUCTURE_INVALID,
                    DownloadStage.VALIDATE,
                    "公開対象の入札調書ではなく、エラーページが返されました",
                    details={
                        "validation": "error_page",
                        "marker": blocked_marker,
                    },
                ),
            ),
        )

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    heading = soup.find("h1")
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    if "入札調書" not in _normalize_text(title):
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.HTML_STRUCTURE_INVALID,
                    DownloadStage.VALIDATE,
                    "HTMLのタイトルが入札調書と一致しません",
                    details={"validation": "title"},
                ),
            ),
        )
    if "入札調書" not in _normalize_text(heading_text):
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.HTML_STRUCTURE_INVALID,
                    DownloadStage.VALIDATE,
                    "HTMLの見出しが入札調書と一致しません",
                    details={"validation": "heading"},
                ),
            ),
        )

    normalized_project = _normalize_text(project_name)
    project_field = _extract_table_field(soup, "件名")
    if not project_field:
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.HTML_STRUCTURE_INVALID,
                    DownloadStage.VALIDATE,
                    "入札調書の件名欄が空です",
                    details={"validation": "project_name_field"},
                ),
            ),
        )
    if not normalized_project or _normalize_text(project_field) != normalized_project:
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.PROJECT_NAME_MISMATCH,
                    DownloadStage.VALIDATE,
                    "HTML内の案件名が検索結果の工事名と一致しません",
                    details={"validation": "project_name"},
                ),
            ),
        )

    missing_fields = [
        label
        for label in _REQUIRED_VALUE_FIELDS
        if not _extract_table_field(soup, label)
    ]
    if missing_fields:
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.HTML_STRUCTURE_INVALID,
                    DownloadStage.VALIDATE,
                    "入札調書の必須項目が不足しています",
                    details={
                        "validation": "required_fields",
                        "missing": ",".join(missing_fields),
                    },
                ),
            ),
        )

    if not _has_bid_detail_row(soup):
        return HtmlPreparationResult(
            False,
            issues=(
                _issue(
                    DownloadIssueCode.HTML_STRUCTURE_INVALID,
                    DownloadStage.VALIDATE,
                    "入札調書に業者別の金額明細がありません",
                    details={"validation": "detail_rows"},
                ),
            ),
        )

    sanitized_html, blocked_count = _sanitize_html(soup)
    issues: Tuple[DownloadIssue, ...] = ()
    if blocked_count:
        issues = (
            _issue(
                DownloadIssueCode.EXTERNAL_RESOURCE_BLOCKED,
                DownloadStage.CLASSIFY,
                "HTML内の外部リソースと実行可能要素を除去しました",
                severity=IssueSeverity.WARNING,
                details={"removed_items": blocked_count},
            ),
        )
    return HtmlPreparationResult(True, sanitized_html, issues)


def _extract_table_field(soup: BeautifulSoup, label: str) -> str:
    """表の見出しセルと同じ行にある最初の値を返す。"""

    def normalize_label(value: str) -> str:
        normalized = _normalize_text(value).rstrip(":：")
        return re.sub(
            r"^(?:\(\d+\)|\d+)[.、:：]?",
            "",
            normalized,
        )

    normalized_label = normalize_label(label)
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for index, cell in enumerate(cells):
            cell_label = normalize_label(cell.get_text(" ", strip=True))
            if cell_label != normalized_label:
                continue
            for value_cell in cells[index + 1 :]:
                value = value_cell.get_text(" ", strip=True)
                if _normalize_text(value):
                    return value
            return ""
    return ""


def _validate_conversion_context(
    *,
    source_url: str,
    document_name: str,
    project_name: str,
) -> Optional[DownloadIssue]:
    try:
        parsed = urlsplit(source_url)
    except ValueError:
        parsed = None

    query = parse_qs(parsed.query) if parsed else {}
    if (
        parsed is None
        or not is_known_publish_servlet(source_url)
        or "AnkenKanriNo" not in query
        or "BunshoKanriId" not in query
    ):
        return _issue(
            DownloadIssueCode.UNEXPECTED_HTML,
            DownloadStage.CLASSIFY,
            "HTMLからPDFへの変換を許可していない配信元です",
            details={"validation": "source_url"},
        )
    if not is_html_bid_sheet_candidate(source_url, document_name):
        return _issue(
            DownloadIssueCode.UNEXPECTED_HTML,
            DownloadStage.CLASSIFY,
            "入札調書以外のHTMLはPDFへ変換しません",
            details={"validation": "document_name"},
        )
    if not _normalize_text(project_name):
        return _issue(
            DownloadIssueCode.PROJECT_NAME_MISMATCH,
            DownloadStage.VALIDATE,
            "照合に必要な工事名が指定されていません",
            details={"validation": "project_name"},
        )
    return None


def _has_bid_detail_row(soup: BeautifulSoup) -> bool:
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header_index = -1
        for index, row in enumerate(rows):
            cells = [
                _normalize_text(cell.get_text(" ", strip=True))
                for cell in row.find_all(["th", "td"])
            ]
            joined = "".join(cells)
            if "業者名" in joined and "金額" in joined:
                header_index = index
                break
        if header_index < 0:
            continue

        for row in rows[header_index + 1 :]:
            cells = [
                _normalize_text(cell.get_text(" ", strip=True))
                for cell in row.find_all(["th", "td"])
            ]
            non_empty = [cell for cell in cells if cell]
            if len(non_empty) < 2 or "業者名" in "".join(non_empty):
                continue
            result_present = any(
                re.search(r"\d", cell)
                or any(marker in cell for marker in _BID_RESULT_MARKERS)
                for cell in non_empty[1:]
            )
            vendor_present = any(
                not re.fullmatch(r"[\d,，.．円￥¥()（）\-ー]+", cell)
                and not any(marker == cell for marker in _BID_RESULT_MARKERS)
                for cell in non_empty[:-1]
            )
            if vendor_present and result_present:
                return True
    return False


def _sanitize_css(css: str) -> tuple[str, int]:
    sanitized, imports = _CSS_IMPORT_RE.subn("", css)
    sanitized, urls = _CSS_URL_RE.subn("none", sanitized)
    return sanitized, imports + urls


def _sanitize_html(soup: BeautifulSoup) -> tuple[str, int]:
    removed = 0

    for tag_name in _REMOVED_TAGS:
        for tag in list(soup.find_all(tag_name)):
            tag.decompose()
            removed += 1

    for tag in list(soup.find_all(["link", "base"])):
        tag.decompose()
        removed += 1

    for tag in soup.find_all("meta"):
        if str(tag.get("http-equiv", "")).strip().casefold() == "refresh":
            tag.decompose()
            removed += 1

    for style in soup.find_all("style"):
        css = style.string if style.string is not None else style.get_text()
        sanitized_css, css_removed = _sanitize_css(css)
        style.clear()
        style.append(sanitized_css)
        removed += css_removed

    for tag in soup.find_all(True):
        for attribute in list(tag.attrs):
            lower = attribute.lower()
            if lower.startswith("on"):
                del tag.attrs[attribute]
                removed += 1
                continue
            if lower == "style":
                raw_style = str(tag.attrs[attribute])
                clean_style, css_removed = _sanitize_css(raw_style)
                tag.attrs[attribute] = clean_style
                removed += css_removed
                continue
            if lower not in _RESOURCE_ATTRIBUTES:
                continue
            raw_value = tag.attrs.get(attribute, "")
            value = (
                " ".join(raw_value) if isinstance(raw_value, list) else str(raw_value)
            ).strip()
            if (
                lower == "href"
                and value.startswith("#")
                or lower == "src"
                and value.lower().startswith("data:")
            ):
                continue
            del tag.attrs[attribute]
            removed += 1

    if soup.head is None:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    else:
        head = soup.head

    for existing in list(head.find_all("meta")):
        if (
            str(existing.get("http-equiv", "")).strip().casefold()
            == "content-security-policy"
        ):
            existing.decompose()

    charset = soup.new_tag("meta")
    charset["charset"] = "utf-8"
    csp = soup.new_tag("meta")
    csp["http-equiv"] = "Content-Security-Policy"
    csp["content"] = _CONTENT_SECURITY_POLICY
    print_style = soup.new_tag("style")
    print_style["data-ippi-print-style"] = "true"
    print_style.string = _PRINT_STYLE

    # body内を含む元のstyleをすべて固定印刷CSSより前へ集約する。
    # これにより、元HTML側の後置@page規則がA4縦・10mm指定を
    # カスケードで上書きすることを防ぐ。
    for existing_style in list(soup.find_all("style")):
        if existing_style.parent is not head:
            head.append(existing_style.extract())
    head.append(print_style)
    head.insert(0, csp)
    head.insert(0, charset)

    return "<!DOCTYPE html>\n" + str(soup), removed


def _decode_html_payload(source_html: HtmlPayload) -> str:
    if isinstance(source_html, bytes):
        converted = UnicodeDammit(
            source_html,
            is_html=True,
        ).unicode_markup
        if converted is None:
            raise UnicodeError("HTMLの文字コードを判定できません")
        return converted
    return source_html


def _validation_process_entry(
    connection,
    source_path: str,
    source_is_utf8_text: bool,
    sanitized_output_path: str,
    max_html_bytes: int,
    source_url: str,
    document_name: str,
    project_name: str,
) -> None:
    """Pathを子で読み、無害化済みHTMLを直接一時Pathへ書く。"""

    try:
        payload = bytearray()
        with Path(source_path).open("rb") as source_stream:
            while True:
                chunk = source_stream.read(64 * 1024)
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > max_html_bytes:
                    prepared = HtmlPreparationResult(
                        False,
                        issues=(
                            _issue(
                                DownloadIssueCode.HTML_STRUCTURE_INVALID,
                                DownloadStage.VALIDATE,
                                "入札調書HTMLが変換可能なサイズ上限を超えています",
                                details={
                                    "source_bytes": len(payload),
                                    "max_bytes": max_html_bytes,
                                },
                            ),
                        ),
                    )
                    connection.send(
                        (
                            "result",
                            _IsolatedPreparationMetadata(
                                False,
                                prepared.issues,
                            ),
                        )
                    )
                    return
        raw_payload = bytes(payload)
        if source_is_utf8_text:
            decoded_html = raw_payload.decode("utf-8")
        else:
            decoded_html = _decode_html_payload(raw_payload)
        prepared = validate_and_sanitize_bid_sheet_html(
            decoded_html,
            source_url=source_url,
            document_name=document_name,
            project_name=project_name,
        )
        sanitized_bytes = 0
        if prepared.success:
            sanitized_path = Path(sanitized_output_path)
            sanitized_path.write_text(
                prepared.sanitized_html,
                encoding="utf-8",
                newline="\n",
            )
            sanitized_bytes = sanitized_path.stat().st_size
        connection.send(
            (
                "result",
                _IsolatedPreparationMetadata(
                    prepared.success,
                    prepared.issues,
                    sanitized_bytes,
                ),
            )
        )
    except BaseException as exc:
        # HTML本文や例外本文を親process・ログへ渡さない。
        connection.send(("error", type(exc).__name__))
    finally:
        connection.close()


class HtmlToPdfConverter:
    """内蔵生成を優先し、必要時だけEdgeを監視下で実行する。"""

    def __init__(
        self,
        logger=None,
        *,
        edge_path: Optional[Union[str, Path]] = None,
        timeout_seconds: float = 60.0,
        poll_interval: float = 0.1,
        max_html_bytes: int = _DEFAULT_MAX_HTML_BYTES,
        popen_factory: Callable = subprocess.Popen,
        version_runner: Callable = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        tree_terminator: Optional[Callable[[object], None]] = None,
        edge_verifier: Optional[Callable[[Path], object]] = None,
        _isolate_validation: bool = True,
        internal_renderer: Optional[InternalBidSheetPdfRenderer] = None,
        prefer_internal: Optional[bool] = None,
        audit: Optional[PdfConversionAudit] = None,
        process_supervisor: Optional[WindowsJobProcessSupervisor] = None,
        max_edge_attempts: int = 2,
    ):
        self.logger = logger
        self._configured_edge_path = (
            Path(edge_path).expanduser() if edge_path is not None else None
        )
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.poll_interval = max(0.01, float(poll_interval))
        self.max_html_bytes = max(1, int(max_html_bytes))
        self._popen = popen_factory
        self._version_runner = version_runner
        self._clock = clock
        self._sleep = sleeper
        self._custom_tree_terminator = tree_terminator
        self._edge_verifier = edge_verifier or self._verify_edge_authenticode
        self._isolate_validation = bool(_isolate_validation)
        # Fake Popenを注入する既存Edge単体テストは、そのままEdge経路だけを
        # 検証できるようにする。本番の標準Popenでは内蔵生成を優先する。
        self._prefer_internal = (
            popen_factory is subprocess.Popen
            if prefer_internal is None
            else bool(prefer_internal)
        )
        self._internal_renderer = internal_renderer or InternalBidSheetPdfRenderer(
            font_path=default_font_path(),
            timeout_seconds=min(30.0, self.timeout_seconds),
        )
        self._audit = audit or PdfConversionAudit()
        self._process_supervisor = process_supervisor
        if self._process_supervisor is None and popen_factory is subprocess.Popen:
            self._process_supervisor = WindowsJobProcessSupervisor(
                poll_interval=self.poll_interval,
            )
        # Fake Popenを使う単体テストは従来どおり1回だけ実行する。本番では
        # Job Objectで各試行の全子process終了を確認できる場合に限り再試行する。
        self._max_edge_attempts = (
            max(1, min(int(max_edge_attempts), 2))
            if self._process_supervisor is not None
            else 1
        )

    @staticmethod
    def recover_stale_temporary_roots(
        parent: Union[str, Path],
        *,
        stale_after_seconds: float = _TEMPORARY_ROOT_STALE_SECONDS,
        now: Optional[float] = None,
        process_alive: Callable[[int], bool] = _is_process_alive_for_cleanup,
    ) -> tuple[Path, ...]:
        """未使用で期限切れのconverter専用一時rootだけを回収する。

        一時root名の所有PID・作成時刻を確認できないもの、現在実行中の
        プロセスに属するもの、シンボリックリンクには一切触れない。
        """

        root = Path(parent).expanduser().resolve(strict=False)
        if not root.is_dir():
            return ()
        current = float(now) if now is not None else time.time()
        removed: list[Path] = []
        try:
            candidates = tuple(
                list(root.glob(f"{_EDGE_TEMPORARY_ROOT_PREFIX}*"))
                + list(root.glob(f"{_VALIDATION_TEMPORARY_ROOT_PREFIX}*"))
            )
        except OSError:
            return ()
        for path in candidates:
            metadata = _temporary_root_metadata(path.name)
            if metadata is None or not path.is_dir() or path.is_symlink():
                continue
            owner_pid, created_at = metadata
            if current - created_at < max(0.0, float(stale_after_seconds)):
                continue
            try:
                if process_alive(owner_pid):
                    continue
            except OSError:
                continue
            try:
                shutil.rmtree(path)
            except OSError:
                continue
            removed.append(path)
        return tuple(removed)

    @classmethod
    def discover_edge(
        cls,
        environ: Optional[Mapping[str, str]] = None,
    ) -> Optional[Path]:
        """標準インストール場所とWindows App PathsからEdgeを探す。"""

        environment = dict(os.environ if environ is None else environ)
        candidates = []
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "PROGRAMW6432"):
            root = environment.get(variable)
            if root:
                candidates.append(
                    Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                )
        local_app_data = environment.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(
                Path(local_app_data)
                / "Microsoft"
                / "Edge"
                / "Application"
                / "msedge.exe"
            )

        candidates.extend(cls._registry_edge_paths())

        seen = set()
        for candidate in candidates:
            try:
                normalized = candidate.expanduser().resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            key = os.path.normcase(str(normalized))
            if key in seen:
                continue
            seen.add(key)
            if normalized.is_file():
                return normalized
        return None

    @staticmethod
    def _registry_edge_paths() -> list[Path]:
        if os.name != "nt":
            return []
        try:
            import winreg
        except ImportError:
            return []

        paths: list[Path] = []
        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\App Paths\msedge.exe"
        )
        access_modes = [winreg.KEY_READ]
        for flag_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
            flag = getattr(winreg, flag_name, 0)
            if flag:
                access_modes.append(winreg.KEY_READ | flag)

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for access in access_modes:
                try:
                    with winreg.OpenKey(hive, key_path, 0, access) as key:
                        value, _ = winreg.QueryValueEx(key, None)
                    if value:
                        paths.append(Path(str(value).strip().strip('"')))
                except OSError:
                    continue
        return paths

    def find_edge(self) -> Optional[Path]:
        """明示指定またはシステムからEdge実行ファイルを解決する。"""

        if self._configured_edge_path is not None:
            candidate = self._configured_edge_path.resolve(strict=False)
            return candidate if candidate.is_file() else None
        return self.discover_edge()

    def convert(
        self,
        source_html: HtmlSource,
        output_part: Union[str, Path],
        cancel_check: CancelCheck = None,
        *,
        source_url: str = "",
        document_name: str = "",
        project_name: str = "",
        run_id: str = "",
        document_id: str = "",
        conversion_id: str = "",
    ) -> HtmlToPdfResult:
        """HTMLを検証・無害化し、検証済みPDFの一時ファイルを生成する。

        ``source_html`` がPathの場合も入力ファイルは削除しない。
        ``output_part`` は成功時だけ残し、失敗・キャンセル時は削除する。
        """

        started_at = self._clock()
        output_path = Path(output_part).expanduser().resolve(strict=False)
        temporary_root: Optional[Path] = None
        result: Optional[HtmlToPdfResult] = None
        preparation_issues: Tuple[DownloadIssue, ...] = ()
        preparation: Optional[HtmlPreparationResult] = None
        source_payload: Optional[HtmlPayload] = None
        sanitized_source_path: Optional[Path] = None
        audit_context = PdfConversionContext(
            run_id=run_id,
            conversion_id=(conversion_id or new_conversion_id()),
            project_name=project_name,
            document_name=document_name,
            document_id=document_id,
        )
        internal_attempted = False
        sanitized_for_recovery = ""
        try:
            self._audit.purge_expired()
            self._audit.record(
                audit_context,
                "conversion_started",
                source_bytes=self._source_size_bytes(source_html),
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self.recover_stale_temporary_roots(output_path.parent)
            self._remove_output_part(output_path)

            result = self._guard_conversion(
                output_path,
                started_at,
                cancel_check,
                stage=DownloadStage.VALIDATE,
                activity="入札調書HTMLの検証",
            )
            if result is None:
                source_size = self._source_size_bytes(source_html)
                if source_size > self.max_html_bytes:
                    result = self._failed_result(
                        output_path,
                        started_at,
                        issues=(
                            _issue(
                                DownloadIssueCode.HTML_STRUCTURE_INVALID,
                                DownloadStage.VALIDATE,
                                "入札調書HTMLが変換可能なサイズ上限を超えています",
                                details={
                                    "source_bytes": source_size,
                                    "max_bytes": self.max_html_bytes,
                                },
                            ),
                        ),
                    )
            if result is None:
                temporary_root = Path(
                    tempfile.mkdtemp(
                        prefix=(
                            f"{_EDGE_TEMPORARY_ROOT_PREFIX}p{os.getpid()}-"
                            f"c{int(time.time())}-"
                        ),
                        dir=str(output_path.parent),
                    )
                )
                sanitized_source_path = temporary_root / "bid-sheet.html"
                if self._isolate_validation:
                    preparation, result = self._prepare_with_monitor(
                        source_html,
                        output_path=output_path,
                        started_at=started_at,
                        cancel_check=cancel_check,
                        source_url=source_url,
                        document_name=document_name,
                        project_name=project_name,
                        sanitized_output_path=sanitized_source_path,
                    )
                else:
                    source_payload, result = self._read_source_payload_with_monitor(
                        source_html,
                        output_path=output_path,
                        started_at=started_at,
                        cancel_check=cancel_check,
                    )
                    if result is None:
                        if source_payload is None:
                            raise RuntimeError("HTML入力を取得できませんでした")
                        preparation, result = self._prepare_with_monitor(
                            source_payload,
                            output_path=output_path,
                            started_at=started_at,
                            cancel_check=cancel_check,
                            source_url=source_url,
                            document_name=document_name,
                            project_name=project_name,
                        )
            if result is None:
                if preparation is None:
                    raise RuntimeError("HTML検証結果を取得できませんでした")
                preparation_issues = preparation.issues
                result = self._guard_conversion(
                    output_path,
                    started_at,
                    cancel_check,
                    stage=DownloadStage.VALIDATE,
                    activity="入札調書HTMLの検証",
                    base_issues=preparation_issues,
                )

            if result is None:
                if not preparation.success:
                    result = self._failed_result(
                        output_path,
                        started_at,
                        issues=preparation.issues,
                    )
            if (
                result is None
                and temporary_root is not None
                and sanitized_source_path is not None
            ):
                if not self._isolate_validation:
                    sanitized_source_path.write_text(
                        preparation.sanitized_html,
                        encoding="utf-8",
                        newline="\n",
                    )
                elif not sanitized_source_path.is_file():
                    raise OSError("無害化済みHTMLが生成されませんでした")
                sanitized_for_recovery = sanitized_source_path.read_text(
                    encoding="utf-8"
                )

            if result is None and self._prefer_internal:
                internal_attempted = True
                self._audit.record(
                    audit_context,
                    "renderer_attempt_started",
                    renderer=self._internal_renderer.name,
                    renderer_version=self._internal_renderer.version,
                    attempt=1,
                )
                try:
                    internal = self._internal_renderer.render(
                        sanitized_for_recovery,
                        output_path,
                        project_name=project_name,
                        cancel_check=cancel_check,
                    )
                except Exception as exc:
                    internal = None
                    issue = _issue(
                        DownloadIssueCode.PDF_INTERNAL_RENDER_FAILED,
                        DownloadStage.CONVERT,
                        "内蔵PDF生成で予期しないエラーが発生しました",
                        details={"error_type": type(exc).__name__},
                    )
                    preparation_issues += (
                        replace(issue, severity=IssueSeverity.WARNING),
                    )
                    self._audit.record(
                        audit_context,
                        "renderer_attempt_finished",
                        renderer=self._internal_renderer.name,
                        renderer_version=self._internal_renderer.version,
                        attempt=1,
                        status="FAILED",
                        reason_code=issue.code.value,
                        reason=issue.message,
                    )
                if internal is None:
                    pass
                elif internal.cancelled:
                    self._audit.record(
                        audit_context,
                        "renderer_attempt_finished",
                        renderer=self._internal_renderer.name,
                        renderer_version=self._internal_renderer.version,
                        attempt=1,
                        status="CANCELLED",
                        reason_code=(
                            internal.issue.code.value if internal.issue else "CANCELLED"
                        ),
                        reason=(internal.issue.message if internal.issue else ""),
                        elapsed_seconds=round(internal.elapsed_seconds, 3),
                    )
                    result = HtmlToPdfResult(
                        status=HtmlToPdfStatus.CANCELLED,
                        output_path=str(output_path),
                        elapsed_seconds=max(0.0, self._clock() - started_at),
                        issues=preparation_issues
                        + ((internal.issue,) if internal.issue else ()),
                        conversion_id=audit_context.conversion_id,
                        renderer=self._internal_renderer.name,
                        renderer_version=self._internal_renderer.version,
                    )
                elif internal.success:
                    self._audit.record(
                        audit_context,
                        "renderer_attempt_finished",
                        renderer=self._internal_renderer.name,
                        renderer_version=self._internal_renderer.version,
                        attempt=1,
                        status="SUCCESS",
                        elapsed_seconds=round(internal.elapsed_seconds, 3),
                        page_count=internal.page_count,
                        bytes=internal.bytes_written,
                        sha256=internal.sha256,
                    )
                    result = HtmlToPdfResult(
                        status=HtmlToPdfStatus.SUCCESS,
                        output_path=str(output_path),
                        elapsed_seconds=max(0.0, self._clock() - started_at),
                        bytes_written=internal.bytes_written,
                        sha256=internal.sha256,
                        issues=preparation_issues,
                        conversion_id=audit_context.conversion_id,
                        renderer=self._internal_renderer.name,
                        renderer_version=self._internal_renderer.version,
                    )
                else:
                    issue = internal.issue or _issue(
                        DownloadIssueCode.PDF_INTERNAL_RENDER_FAILED,
                        DownloadStage.CONVERT,
                        "内蔵PDF生成に失敗しました",
                    )
                    warning = replace(issue, severity=IssueSeverity.WARNING)
                    preparation_issues += (warning,)
                    self._audit.record(
                        audit_context,
                        "renderer_attempt_finished",
                        renderer=self._internal_renderer.name,
                        renderer_version=self._internal_renderer.version,
                        attempt=1,
                        status="FAILED",
                        reason_code=issue.code.value,
                        reason=issue.message,
                        elapsed_seconds=round(internal.elapsed_seconds, 3),
                    )
            if result is None:
                edge_path = self.find_edge()
                result = self._guard_conversion(
                    output_path,
                    started_at,
                    cancel_check,
                    edge_path=edge_path,
                    base_issues=preparation_issues,
                )
                if result is None and edge_path is None:
                    result = self._failed_result(
                        output_path,
                        started_at,
                        issues=preparation_issues
                        + (
                            _issue(
                                DownloadIssueCode.EDGE_NOT_FOUND,
                                DownloadStage.CONVERT,
                                "Microsoft Edgeが見つかりません",
                            ),
                        ),
                    )

            if result is None:
                if temporary_root is None or sanitized_source_path is None:
                    raise RuntimeError("変換用一時領域を取得できませんでした")
                edge_verification = self._normalise_edge_verification(
                    self._edge_verifier(edge_path)
                )
                if not edge_verification.trusted:
                    details: dict[str, DiagnosticValue] = {
                        "verification": (
                            edge_verification.reason or "signature_not_trusted"
                        ),
                    }
                    if edge_verification.status_code:
                        details["status_code"] = edge_verification.status_code
                    result = self._failed_result(
                        output_path,
                        started_at,
                        edge_path=edge_path,
                        issues=preparation_issues
                        + (
                            _issue(
                                DownloadIssueCode.EDGE_START_FAILED,
                                DownloadStage.CONVERT,
                                "Microsoft署名を確認できないEdgeは起動しません",
                                details=details,
                            ),
                        ),
                    )

            if result is None:
                if temporary_root is None or sanitized_source_path is None:
                    raise RuntimeError("変換用一時領域を取得できませんでした")
                if not self._isolate_validation:
                    sanitized_source_path.write_text(
                        preparation.sanitized_html,
                        encoding="utf-8",
                        newline="\n",
                    )
                elif not sanitized_source_path.is_file():
                    raise OSError("無害化済みHTMLが生成されませんでした")
                for edge_attempt in range(1, self._max_edge_attempts + 1):
                    result = self._guard_conversion(
                        output_path,
                        started_at,
                        cancel_check,
                        edge_path=edge_path,
                        base_issues=preparation_issues,
                    )
                    if result is not None:
                        break
                    self._remove_output_part(output_path)
                    result = self._run_edge(
                        edge_path=edge_path,
                        source_path=sanitized_source_path,
                        output_path=output_path,
                        temporary_root=temporary_root,
                        cancel_check=cancel_check,
                        started_at=started_at,
                        preparation_issues=preparation_issues,
                        audit_context=audit_context,
                        attempt=edge_attempt,
                    )
                    edge_issue = result.primary_issue
                    self._audit.record(
                        audit_context,
                        "renderer_attempt_finished",
                        renderer="Microsoft Edge",
                        renderer_version=result.edge_version,
                        attempt=edge_attempt,
                        status=result.status.value,
                        reason_code=(edge_issue.code.value if edge_issue else ""),
                        reason=(edge_issue.message if edge_issue else ""),
                        elapsed_seconds=round(result.elapsed_seconds, 3),
                        bytes=result.bytes_written,
                        sha256=result.sha256,
                    )
                    if (
                        result.success
                        or result.cancelled
                        or edge_attempt >= self._max_edge_attempts
                        or not self._edge_retry_allowed(result)
                    ):
                        break
                    if edge_issue is not None:
                        preparation_issues += (
                            replace(edge_issue, severity=IssueSeverity.WARNING),
                        )
                    result = None
        except UnicodeError as exc:
            result = self._failed_result(
                output_path,
                started_at,
                issues=(
                    _issue(
                        DownloadIssueCode.HTML_PARSE_FAILED,
                        DownloadStage.VALIDATE,
                        "入札調書HTMLの文字コードを判定できませんでした",
                        details={"error_type": type(exc).__name__},
                    ),
                ),
            )
        except OSError as exc:
            result = self._failed_result(
                output_path,
                started_at,
                issues=(
                    _issue(
                        DownloadIssueCode.SAVE_FAILED,
                        DownloadStage.CONVERT,
                        "HTMLからPDFへの変換用ファイルを準備できませんでした",
                        details={"error_type": type(exc).__name__},
                    ),
                ),
            )
        except Exception as exc:
            result = self._failed_result(
                output_path,
                started_at,
                issues=(
                    _issue(
                        DownloadIssueCode.UNKNOWN,
                        DownloadStage.CONVERT,
                        "HTMLからPDFへの変換中に予期しないエラーが発生しました",
                        details={"error_type": type(exc).__name__},
                    ),
                ),
            )

        if result is None:
            result = self._failed_result(
                output_path,
                started_at,
                issues=(
                    _issue(
                        DownloadIssueCode.UNKNOWN,
                        DownloadStage.CONVERT,
                        "HTMLからPDFへの変換結果を取得できませんでした",
                    ),
                ),
            )

        recovery_artifact = ""
        if (
            result is not None
            and not result.success
            and not result.cancelled
            and sanitized_for_recovery
        ):
            primary = result.primary_issue
            artifact = self._audit.store_failure(
                audit_context,
                sanitized_for_recovery,
                {
                    "reason_code": primary.code.value if primary else "UNKNOWN",
                    "reason": primary.message if primary else result.error,
                    "internal_attempted": internal_attempted,
                    "renderer": result.renderer or "Microsoft Edge",
                },
                stderr_tail=str(
                    (primary.details if primary else {}).get("stderr_tail", "")
                ),
            )
            if artifact is not None:
                recovery_artifact = str(artifact)
                result = replace(
                    result,
                    recovery_artifact=recovery_artifact,
                    issues=result.issues
                    + (
                        _issue(
                            DownloadIssueCode.PDF_RECOVERY_ARTIFACT_STORED,
                            DownloadStage.CLEANUP,
                            "再変換用の無害化済みHTMLを30日間保持します",
                            severity=IssueSeverity.WARNING,
                            details={"conversion_id": audit_context.conversion_id},
                        ),
                    ),
                )

        cleanup_issues = []
        cleanup_deadline = min(
            started_at + self.timeout_seconds,
            self._clock() + min(0.5, self.timeout_seconds),
        )
        if not result.success:
            cleanup_issue = self._safe_unlink(
                output_path,
                deadline=cleanup_deadline,
            )
            if cleanup_issue:
                cleanup_issues.append(cleanup_issue)
        if temporary_root is not None:
            cleanup_issue = self._safe_rmtree(
                temporary_root,
                deadline=cleanup_deadline,
            )
            if cleanup_issue:
                cleanup_issues.append(cleanup_issue)

        if cleanup_issues:
            result = replace(
                result,
                issues=result.issues + tuple(cleanup_issues),
                elapsed_seconds=max(0.0, self._clock() - started_at),
            )
        if not result.success:
            correlated_issues = []
            for item in result.issues:
                if item.severity != IssueSeverity.ERROR:
                    correlated_issues.append(item)
                    continue
                details = dict(item.details)
                details.setdefault("conversion_id", audit_context.conversion_id)
                correlated_issues.append(replace(item, details=details))
            result = replace(result, issues=tuple(correlated_issues))
        primary = result.primary_issue
        self._audit.record(
            audit_context,
            "conversion_finished",
            status=result.status.value,
            renderer=result.renderer or ("Microsoft Edge" if result.edge_path else ""),
            renderer_version=result.renderer_version or result.edge_version,
            elapsed_seconds=round(result.elapsed_seconds, 3),
            bytes=result.bytes_written,
            sha256=result.sha256,
            reason_code=primary.code.value if primary else "",
            reason=primary.message if primary else "",
            recovery_artifact=bool(recovery_artifact),
        )
        if not result.conversion_id:
            result = replace(result, conversion_id=audit_context.conversion_id)
        return result

    @staticmethod
    def _load_source_html(source_html: HtmlSource) -> str:
        if isinstance(source_html, Path):
            return _decode_html_payload(source_html.read_bytes())
        return _decode_html_payload(source_html)

    def _source_size_bytes(self, source_html: HtmlSource) -> int:
        if isinstance(source_html, Path):
            return source_html.stat().st_size
        if isinstance(source_html, bytes):
            return len(source_html)
        # UTF-8では文字数よりバイト数が小さくならないため、
        # 巨大文字列を不必要にencodeする前に早期判定できる。
        if len(source_html) > self.max_html_bytes:
            return len(source_html)
        return len(source_html.encode("utf-8"))

    def _read_source_payload_with_monitor(
        self,
        source_html: HtmlSource,
        *,
        output_path: Path,
        started_at: float,
        cancel_check: CancelCheck,
    ) -> tuple[Optional[HtmlPayload], Optional[HtmlToPdfResult]]:
        """入力Pathを閉じてから、解析スレッドへ副作用のない値を渡す。

        Path入力は小さなチャンクで読み、各チャンクの前後にキャンセルと
        変換期限を確認する。これにより、解析スレッドを待たずに呼び出し元が
        戻った場合も、HTTP側が元の一時HTMLを安全に削除できる。
        """

        guard_result = self._guard_conversion(
            output_path,
            started_at,
            cancel_check,
            stage=DownloadStage.VALIDATE,
            activity="入札調書HTMLの読込",
        )
        if guard_result is not None:
            return None, guard_result
        if not isinstance(source_html, Path):
            return source_html, None

        payload = bytearray()
        with source_html.open("rb") as source_stream:
            while True:
                guard_result = self._guard_conversion(
                    output_path,
                    started_at,
                    cancel_check,
                    stage=DownloadStage.VALIDATE,
                    activity="入札調書HTMLの読込",
                )
                if guard_result is not None:
                    return None, guard_result
                chunk = source_stream.read(64 * 1024)
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > self.max_html_bytes:
                    return (
                        None,
                        self._failed_result(
                            output_path,
                            started_at,
                            issues=(
                                _issue(
                                    DownloadIssueCode.HTML_STRUCTURE_INVALID,
                                    DownloadStage.VALIDATE,
                                    "入札調書HTMLが変換可能なサイズ上限を超えています",
                                    details={
                                        "source_bytes": len(payload),
                                        "max_bytes": self.max_html_bytes,
                                    },
                                ),
                            ),
                        ),
                    )

        guard_result = self._guard_conversion(
            output_path,
            started_at,
            cancel_check,
            stage=DownloadStage.VALIDATE,
            activity="入札調書HTMLの読込",
        )
        if guard_result is not None:
            return None, guard_result
        return bytes(payload), None

    def _prepare_with_monitor(
        self,
        source_html: HtmlSource,
        *,
        output_path: Path,
        started_at: float,
        cancel_check: CancelCheck,
        source_url: str,
        document_name: str,
        project_name: str,
        sanitized_output_path: Optional[Path] = None,
    ) -> tuple[
        Optional[HtmlPreparationResult],
        Optional[HtmlToPdfResult],
    ]:
        """隔離processのHTML解析を100ms間隔で監視する。

        本番経路ではキャンセル・期限超過時に解析processを強制終了する。
        単体テストでは決定的な論理時計を使うため、明示時だけ同じ監視を
        副作用のないdaemonスレッドへ適用する。
        """
        if self._isolate_validation:
            return self._prepare_in_process_with_monitor(
                source_html,
                output_path=output_path,
                started_at=started_at,
                cancel_check=cancel_check,
                source_url=source_url,
                document_name=document_name,
                project_name=project_name,
                sanitized_output_path=sanitized_output_path,
            )
        return self._prepare_in_thread_with_monitor(
            source_html,
            output_path=output_path,
            started_at=started_at,
            cancel_check=cancel_check,
            source_url=source_url,
            document_name=document_name,
            project_name=project_name,
        )

    def _prepare_in_thread_with_monitor(
        self,
        source_html: HtmlSource,
        *,
        output_path: Path,
        started_at: float,
        cancel_check: CancelCheck,
        source_url: str,
        document_name: str,
        project_name: str,
    ) -> tuple[
        Optional[HtmlPreparationResult],
        Optional[HtmlToPdfResult],
    ]:
        results: queue.Queue[
            tuple[Optional[HtmlPreparationResult], Optional[Exception]]
        ] = queue.Queue(maxsize=1)

        def prepare() -> None:
            try:
                raw_html = self._load_source_html(source_html)
                prepared = validate_and_sanitize_bid_sheet_html(
                    raw_html,
                    source_url=source_url,
                    document_name=document_name,
                    project_name=project_name,
                )
                results.put_nowait((prepared, None))
            except Exception as exc:
                results.put_nowait((None, exc))

        worker = threading.Thread(
            target=prepare,
            name="ippi-html-validation",
            daemon=True,
        )
        worker.start()

        while True:
            guard_result = self._guard_conversion(
                output_path,
                started_at,
                cancel_check,
                stage=DownloadStage.VALIDATE,
                activity="入札調書HTMLの検証",
            )
            if guard_result is not None:
                return None, guard_result
            try:
                preparation, error = results.get_nowait()
            except queue.Empty:
                remaining = self.timeout_seconds - (self._clock() - started_at)
                self._sleep(min(self.poll_interval, max(0.0, remaining)))
                # テスト用の論理時計でもworkerへ実行権を渡す。
                time.sleep(0)
                continue
            if error is not None:
                raise error
            if preparation is None:
                raise RuntimeError("HTML検証結果を取得できませんでした")
            guard_result = self._guard_conversion(
                output_path,
                started_at,
                cancel_check,
                stage=DownloadStage.VALIDATE,
                activity="入札調書HTMLの検証",
                base_issues=preparation.issues,
            )
            if guard_result is not None:
                return None, guard_result
            return preparation, None

    def _prepare_in_process_with_monitor(
        self,
        source_html: HtmlSource,
        *,
        output_path: Path,
        started_at: float,
        cancel_check: CancelCheck,
        source_url: str,
        document_name: str,
        project_name: str,
        sanitized_output_path: Optional[Path] = None,
    ) -> tuple[
        Optional[HtmlPreparationResult],
        Optional[HtmlToPdfResult],
    ]:
        owned_temporary_root: Optional[Path] = None
        if sanitized_output_path is None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            owned_temporary_root = Path(
                tempfile.mkdtemp(
                    prefix=(
                        f"{_VALIDATION_TEMPORARY_ROOT_PREFIX}p{os.getpid()}-"
                        f"c{int(time.time())}-"
                    ),
                    dir=str(output_path.parent),
                )
            )
            sanitized_output_path = owned_temporary_root / "bid-sheet.html"

        try:
            source_is_utf8_text = isinstance(source_html, str)
            if isinstance(source_html, Path):
                isolated_source_path = source_html.expanduser().resolve(strict=False)
                source_is_utf8_text = False
            else:
                isolated_source_path = (
                    sanitized_output_path.parent / "source-input.html"
                )
                if isinstance(source_html, bytes):
                    isolated_source_path.write_bytes(source_html)
                else:
                    isolated_source_path.write_text(
                        source_html,
                        encoding="utf-8",
                        newline="\n",
                    )

            context = multiprocessing.get_context("spawn")
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_validation_process_entry,
                args=(
                    sender,
                    str(isolated_source_path),
                    source_is_utf8_text,
                    str(sanitized_output_path),
                    self.max_html_bytes,
                    source_url,
                    document_name,
                    project_name,
                ),
                name="ippi-html-validation",
                daemon=True,
            )
        except BaseException:
            if owned_temporary_root is not None:
                shutil.rmtree(owned_temporary_root, ignore_errors=True)
            raise
        started = False
        try:
            process.start()
            started = True
            sender.close()
            while True:
                guard_result = self._guard_conversion(
                    output_path,
                    started_at,
                    cancel_check,
                    stage=DownloadStage.VALIDATE,
                    activity="入札調書HTMLの検証",
                )
                if guard_result is not None:
                    self._stop_validation_process(process)
                    return None, guard_result
                remaining = self.timeout_seconds - (self._clock() - started_at)
                termination_grace = min(
                    0.2,
                    max(0.1, self.timeout_seconds / 2),
                )
                if remaining <= termination_grace:
                    self._stop_validation_process(process)
                    return (
                        None,
                        self._timeout_result(
                            output_path,
                            started_at,
                            stage=DownloadStage.VALIDATE,
                            activity="入札調書HTMLの検証",
                        ),
                    )

                if receiver.poll():
                    try:
                        message = receiver.recv()
                    except EOFError as exc:
                        raise RuntimeError(
                            "HTML検証processから結果を取得できませんでした"
                        ) from exc
                    process.join(timeout=0)
                    if not isinstance(message, tuple) or len(message) != 2:
                        raise RuntimeError("HTML検証processの応答が不正です")
                    kind, payload = message
                    if kind == "error":
                        if payload == "UnicodeError":
                            raise UnicodeError("HTMLの文字コードを判定できません")
                        if payload in {
                            "OSError",
                            "FileNotFoundError",
                            "PermissionError",
                        }:
                            raise OSError(
                                "HTML検証processでファイルを処理できませんでした"
                            )
                        raise RuntimeError("HTML検証processでエラーが発生しました")
                    if kind != "result" or not isinstance(
                        payload,
                        _IsolatedPreparationMetadata,
                    ):
                        raise RuntimeError("HTML検証processの結果が不正です")
                    if process.is_alive():
                        self._stop_validation_process(process)
                    else:
                        process.join(timeout=0)
                    guard_result = self._guard_conversion(
                        output_path,
                        started_at,
                        cancel_check,
                        stage=DownloadStage.VALIDATE,
                        activity="入札調書HTMLの検証",
                        base_issues=payload.issues,
                    )
                    if guard_result is not None:
                        return None, guard_result
                    if payload.success:
                        try:
                            generated_size = sanitized_output_path.stat().st_size
                        except OSError as exc:
                            raise OSError(
                                "無害化済みHTMLを確認できませんでした"
                            ) from exc
                        if (
                            generated_size <= 0
                            or generated_size != payload.sanitized_bytes
                        ):
                            raise OSError("無害化済みHTMLのサイズが一致しません")
                    return (
                        HtmlPreparationResult(
                            payload.success,
                            issues=payload.issues,
                        ),
                        None,
                    )

                if not process.is_alive():
                    raise RuntimeError("HTML検証processが結果を返さず終了しました")
                self._sleep(min(self.poll_interval, max(0.0, remaining)))
        finally:
            try:
                sender.close()
            except (OSError, ValueError):
                pass
            receiver.close()
            if started and process.is_alive():
                self._stop_validation_process(process)
            if started and not process.is_alive():
                try:
                    process.join(timeout=0)
                    process.close()
                except (OSError, ValueError):
                    pass
            if owned_temporary_root is not None:
                shutil.rmtree(owned_temporary_root, ignore_errors=True)

    @staticmethod
    def _stop_validation_process(process) -> None:
        """副作用のないHTML解析processを期限内に停止する。"""

        if not process.is_alive():
            process.join(timeout=0)
            return
        process.terminate()
        process.join(timeout=0.05)
        if process.is_alive():
            kill = getattr(process, "kill", None)
            if callable(kill):
                kill()
            process.join(timeout=0.05)

    def _run_edge(
        self,
        *,
        edge_path: Path,
        source_path: Path,
        output_path: Path,
        temporary_root: Path,
        cancel_check: CancelCheck,
        started_at: float,
        preparation_issues: Tuple[DownloadIssue, ...],
        audit_context: Optional[PdfConversionContext] = None,
        attempt: int = 1,
    ) -> HtmlToPdfResult:
        profile_path = temporary_root / f"profile-{max(1, int(attempt))}"
        profile_path.mkdir()
        remaining_seconds = max(
            0.01,
            self.timeout_seconds - (self._clock() - started_at),
        )
        edge_version = self._get_edge_version(
            edge_path,
            timeout_seconds=min(5.0, remaining_seconds),
        )
        guard_result = self._guard_conversion(
            output_path,
            started_at,
            cancel_check,
            edge_path=edge_path,
            edge_version=edge_version,
            base_issues=preparation_issues,
        )
        if guard_result is not None:
            return guard_result
        command = self._edge_command(
            edge_path=edge_path,
            source_path=source_path,
            output_path=output_path,
            profile_path=profile_path,
        )
        process = None
        stderr_capture = _BoundedByteTail()
        stderr_worker: Optional[threading.Thread] = None
        supervised = None

        if audit_context is not None:
            self._audit.record(
                audit_context,
                "renderer_attempt_started",
                renderer="Microsoft Edge",
                renderer_version=edge_version,
                attempt=attempt,
            )

        if self._process_supervisor is not None:

            def on_process_event(event: str, values: dict[str, object]) -> None:
                if audit_context is not None:
                    self._audit.record(
                        audit_context, event, renderer="Microsoft Edge", **values
                    )

            supervised = self._process_supervisor.run(
                command,
                cwd=temporary_root,
                timeout_seconds=remaining_seconds,
                cancel_check=cancel_check,
                event_callback=on_process_event,
            )
            state = supervised.state
            exit_code = supervised.exit_code
            stderr_tail = supervised.stderr_tail
            if state == "supervision_unavailable":
                return self._failed_result(
                    output_path,
                    started_at,
                    edge_path=edge_path,
                    edge_version=edge_version,
                    issues=preparation_issues
                    + (
                        _issue(
                            DownloadIssueCode.EDGE_SUPERVISION_UNAVAILABLE,
                            DownloadStage.CONVERT,
                            "Edgeのプロセスツリーを安全に監視できないため起動しませんでした",
                            details={"reason": supervised.supervision_error},
                        ),
                    ),
                    conversion_id=(
                        audit_context.conversion_id if audit_context else ""
                    ),
                    renderer="Microsoft Edge",
                    renderer_version=edge_version,
                )
        else:
            state = ""
            exit_code = None
            stderr_tail = ""

        if supervised is None:
            try:
                process = self._popen(
                    command,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    cwd=str(temporary_root),
                    **self._hidden_process_options(),
                )
                stderr_stream = getattr(process, "stderr", None)
                if stderr_stream is not None:
                    stderr_worker = threading.Thread(
                        target=self._drain_stderr_stream,
                        args=(stderr_stream, stderr_capture),
                        name="ippi-edge-stderr",
                        daemon=True,
                    )
                    stderr_worker.start()
                state = self._wait_for_process(process, cancel_check, started_at)
            except OSError as exc:
                return self._failed_result(
                    output_path,
                    started_at,
                    edge_path=edge_path,
                    edge_version=edge_version,
                    issues=preparation_issues
                    + (
                        _issue(
                            DownloadIssueCode.EDGE_START_FAILED,
                            DownloadStage.CONVERT,
                            "Microsoft Edgeを起動できませんでした",
                            details={"error_type": type(exc).__name__},
                        ),
                    ),
                    conversion_id=(
                        audit_context.conversion_id if audit_context else ""
                    ),
                    renderer="Microsoft Edge",
                    renderer_version=edge_version,
                )
            finally:
                if process is not None:
                    self._finish_stderr_capture(process, stderr_worker)

            exit_code = process.poll() if process is not None else None
            stderr_tail = stderr_capture.text()
        if state == "cancelled":
            return HtmlToPdfResult(
                status=HtmlToPdfStatus.CANCELLED,
                output_path=str(output_path),
                edge_path=str(edge_path),
                edge_version=edge_version,
                elapsed_seconds=max(0.0, self._clock() - started_at),
                exit_code=exit_code,
                issues=preparation_issues
                + (
                    _issue(
                        DownloadIssueCode.CANCELLED,
                        DownloadStage.CONVERT,
                        "HTMLからPDFへの変換をキャンセルしました",
                    ),
                ),
                conversion_id=(audit_context.conversion_id if audit_context else ""),
                renderer="Microsoft Edge",
                renderer_version=edge_version,
            )
        if state == "start_failed":
            return self._failed_result(
                output_path,
                started_at,
                edge_path=edge_path,
                edge_version=edge_version,
                exit_code=exit_code,
                issues=preparation_issues
                + (
                    _issue(
                        DownloadIssueCode.EDGE_START_FAILED,
                        DownloadStage.CONVERT,
                        "Microsoft Edgeの監視付き起動に失敗しました",
                        details={
                            "reason": (
                                supervised.supervision_error
                                if supervised is not None
                                else "process_start_failed"
                            ),
                            "stderr_tail": stderr_tail,
                        },
                    ),
                ),
                conversion_id=(audit_context.conversion_id if audit_context else ""),
                renderer="Microsoft Edge",
                renderer_version=edge_version,
            )
        if state == "timeout":
            return self._failed_result(
                output_path,
                started_at,
                edge_path=edge_path,
                edge_version=edge_version,
                exit_code=exit_code,
                issues=preparation_issues
                + (
                    _issue(
                        DownloadIssueCode.CONVERSION_TIMEOUT,
                        DownloadStage.CONVERT,
                        "Microsoft EdgeによるPDF変換が"
                        f"{self.timeout_seconds:g}秒以内に完了しませんでした",
                        details={
                            "timeout_seconds": self.timeout_seconds,
                            "stderr_tail": stderr_tail,
                        },
                    ),
                ),
                conversion_id=(audit_context.conversion_id if audit_context else ""),
                renderer="Microsoft Edge",
                renderer_version=edge_version,
            )
        if exit_code != 0:
            policy_blocked = self._looks_like_policy_error(stderr_tail)
            gpu_crash = self._looks_like_gpu_crash(stderr_tail)
            return self._failed_result(
                output_path,
                started_at,
                edge_path=edge_path,
                edge_version=edge_version,
                exit_code=exit_code,
                issues=preparation_issues
                + (
                    _issue(
                        (
                            DownloadIssueCode.EDGE_START_FAILED
                            if policy_blocked
                            else (
                                DownloadIssueCode.EDGE_GPU_PROCESS_CRASH
                                if gpu_crash
                                else DownloadIssueCode.EDGE_PROCESS_CRASH
                            )
                        ),
                        DownloadStage.CONVERT,
                        (
                            "組織のポリシーによりMicrosoft Edgeの"
                            "ヘッドレス実行が拒否されました"
                            if policy_blocked
                            else (
                                "Microsoft EdgeのGPUプロセスが異常終了しました"
                                if gpu_crash
                                else "Microsoft Edgeのプロセスが異常終了しました"
                            )
                        ),
                        details={
                            "exit_code": exit_code or 0,
                            "reason": (
                                "policy_blocked" if policy_blocked else "nonzero_exit"
                            ),
                            "stderr_tail": stderr_tail,
                            "exit_code_hex": f"0x{((exit_code or 0) & 0xFFFFFFFF):08X}",
                            "root_pid": supervised.root_pid
                            if supervised
                            else getattr(process, "pid", 0),
                            "peak_process_count": supervised.peak_process_count
                            if supervised
                            else 1,
                        },
                    ),
                ),
                conversion_id=(audit_context.conversion_id if audit_context else ""),
                renderer="Microsoft Edge",
                renderer_version=edge_version,
            )

        guard_result = self._guard_conversion(
            output_path,
            started_at,
            cancel_check,
            edge_path=edge_path,
            edge_version=edge_version,
            stage=DownloadStage.VALIDATE,
            activity="生成されたPDFの検証",
            base_issues=preparation_issues,
        )
        if guard_result is not None:
            return guard_result
        pdf_issue, size, sha256, guard_result = self._validate_pdf(
            output_path,
            started_at=started_at,
            cancel_check=cancel_check,
            edge_path=edge_path,
            edge_version=edge_version,
            base_issues=preparation_issues,
        )
        if guard_result is not None:
            return guard_result
        if pdf_issue:
            if pdf_issue.code == DownloadIssueCode.OUTPUT_MISSING:
                code = (
                    DownloadIssueCode.EDGE_GPU_PROCESS_CRASH
                    if self._looks_like_gpu_crash(stderr_tail)
                    else DownloadIssueCode.EDGE_OUTPUT_NOT_PRODUCED
                )
                message = (
                    "Microsoft EdgeのGPUプロセスが異常終了し、PDFを生成しませんでした"
                    if code == DownloadIssueCode.EDGE_GPU_PROCESS_CRASH
                    else "Microsoft Edgeの全プロセス終了後もPDFが生成されませんでした"
                )
                pdf_issue = _issue(
                    code,
                    DownloadStage.VALIDATE,
                    message,
                    details={
                        "exit_code": exit_code or 0,
                        "exit_code_hex": f"0x{((exit_code or 0) & 0xFFFFFFFF):08X}",
                        "stderr_tail": stderr_tail,
                        "root_pid": supervised.root_pid
                        if supervised
                        else getattr(process, "pid", 0),
                        "peak_process_count": supervised.peak_process_count
                        if supervised
                        else 1,
                    },
                )
            return self._failed_result(
                output_path,
                started_at,
                edge_path=edge_path,
                edge_version=edge_version,
                exit_code=exit_code,
                issues=preparation_issues + (pdf_issue,),
                conversion_id=(audit_context.conversion_id if audit_context else ""),
                renderer="Microsoft Edge",
                renderer_version=edge_version,
            )

        return HtmlToPdfResult(
            status=HtmlToPdfStatus.SUCCESS,
            output_path=str(output_path),
            edge_path=str(edge_path),
            edge_version=edge_version,
            elapsed_seconds=max(0.0, self._clock() - started_at),
            exit_code=exit_code,
            bytes_written=size,
            sha256=sha256,
            issues=preparation_issues,
            conversion_id=(audit_context.conversion_id if audit_context else ""),
            renderer="Microsoft Edge",
            renderer_version=edge_version,
        )

    @staticmethod
    def _edge_retry_allowed(result: HtmlToPdfResult) -> bool:
        """独立profileで再試行する価値がある一時障害だけを選ぶ。"""

        issue = result.primary_issue
        return issue is not None and issue.code in {
            DownloadIssueCode.EDGE_PROCESS_CRASH,
            DownloadIssueCode.EDGE_GPU_PROCESS_CRASH,
            DownloadIssueCode.EDGE_OUTPUT_NOT_PRODUCED,
            DownloadIssueCode.CONVERSION_TIMEOUT,
            DownloadIssueCode.OUTPUT_EMPTY,
            DownloadIssueCode.OUTPUT_INVALID_PDF,
            DownloadIssueCode.PDF_CONTENT_VALIDATION_FAILED,
        }

    @staticmethod
    def _looks_like_gpu_crash(stderr_tail: str) -> bool:
        value = str(stderr_tail or "").casefold()
        return any(
            marker in value
            for marker in (
                "gpu process isn't usable",
                "gpu process exited unexpectedly",
                "gpu-process",
                "dawngraphitecache",
                "gpupersistentcache",
                "0xc0000022",
                "-1073741790",
            )
        )

    @staticmethod
    def _drain_stderr_stream(stream, capture: _BoundedByteTail) -> None:
        """PIPEを継続的に読み、Edgeをバッファ満杯で停止させない。"""

        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                capture.append(chunk)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    @staticmethod
    def _finish_stderr_capture(
        process,
        worker: Optional[threading.Thread],
    ) -> None:
        """Edgeのhandleとstderr readerを期限付きで回収する。"""

        try:
            process.wait(timeout=0.2)
        except (AttributeError, OSError, subprocess.SubprocessError):
            pass

        stderr_stream = getattr(process, "stderr", None)
        if worker is not None:
            worker.join(timeout=0.25)
            if worker.is_alive() and stderr_stream is not None:
                try:
                    stderr_stream.close()
                except (OSError, ValueError):
                    pass
                worker.join(timeout=0.1)
        elif stderr_stream is not None:
            try:
                stderr_stream.close()
            except (OSError, ValueError):
                pass

    def _wait_for_process(
        self,
        process,
        cancel_check: CancelCheck,
        started_at: float,
    ) -> str:
        deadline = started_at + self.timeout_seconds
        cleanup_reserve = min(
            0.5,
            max(0.02, self.timeout_seconds / 4),
        )
        termination_grace = min(
            1.0,
            max(cleanup_reserve + 0.05, self.timeout_seconds / 2),
        )
        while process.poll() is None:
            remaining = deadline - self._clock()
            if self._is_cancelled(cancel_check):
                self._terminate_started_tree(
                    process,
                    max_wait_seconds=min(
                        0.5,
                        max(0.01, remaining - cleanup_reserve),
                    ),
                )
                return "cancelled"
            if remaining <= termination_grace:
                self._terminate_started_tree(
                    process,
                    max_wait_seconds=min(
                        0.5,
                        max(0.01, remaining - cleanup_reserve),
                    ),
                )
                return "timeout"
            self._sleep(min(self.poll_interval, remaining))
        return "completed"

    def _terminate_started_tree(
        self,
        process,
        *,
        max_wait_seconds: float,
    ) -> None:
        if self._custom_tree_terminator is not None:
            self._custom_tree_terminator(process)
            return
        self._terminate_process_tree(
            process,
            timeout_seconds=max_wait_seconds,
        )

    @staticmethod
    def _edge_command(
        *,
        edge_path: Path,
        source_path: Path,
        output_path: Path,
        profile_path: Path,
    ) -> list[str]:
        return [
            str(edge_path),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-quic",
            "--disable-sync",
            "--no-proxy-server",
            "--host-resolver-rules=MAP * ~NOTFOUND",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-pings",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            f"--user-data-dir={profile_path}",
            f"--print-to-pdf={output_path}",
            source_path.as_uri(),
        ]

    @staticmethod
    def _normalise_edge_verification(value: object) -> _EdgeVerificationResult:
        """単純なfake verifierとの後方互換を保って結果を構造化する。"""

        if isinstance(value, _EdgeVerificationResult):
            return value
        return _EdgeVerificationResult(
            trusted=bool(value),
            reason="injected_verifier_rejected" if not value else "",
        )

    @staticmethod
    def _verify_edge_authenticode(edge_path: Path) -> _EdgeVerificationResult:
        """WinVerifyTrustでMicrosoft署名を外部通信なしに検証する。

        Authenticode標準ポリシーへ証明書・署名時刻の判定を委ねる。
        ``WTD_LIFETIME_SIGNING_FLAG``を指定しないため、署名証明書の現在の
        有効期限だけで拒否せず、有効なRFC 3161/Authenticodeタイムスタンプを
        Windowsの通常規則どおり評価する。失効情報の取得は無効化し、URL取得は
        キャッシュだけに限定するため、この検証自体は通信を発生させない。
        """

        candidate = Path(edge_path).expanduser().resolve(strict=False)
        if candidate.name.casefold() != "msedge.exe":
            return _EdgeVerificationResult(
                False,
                reason="unexpected_executable_name",
            )
        if not candidate.is_file():
            return _EdgeVerificationResult(False, reason="file_not_found")
        if os.name != "nt":
            # Windows以外は正式対象外。既存のテスト用fakeを実行可能なままにする。
            return _EdgeVerificationResult(True, reason="non_windows_test")

        try:
            import ctypes
            from ctypes import wintypes

            class Guid(ctypes.Structure):
                _fields_ = [
                    ("data1", wintypes.DWORD),
                    ("data2", wintypes.WORD),
                    ("data3", wintypes.WORD),
                    ("data4", ctypes.c_ubyte * 8),
                ]

            class WintrustFileInfo(ctypes.Structure):
                _fields_ = [
                    ("cb_struct", wintypes.DWORD),
                    ("file_path", wintypes.LPCWSTR),
                    ("file_handle", wintypes.HANDLE),
                    ("known_subject", ctypes.POINTER(Guid)),
                ]

            class WintrustData(ctypes.Structure):
                _fields_ = [
                    ("cb_struct", wintypes.DWORD),
                    ("policy_callback_data", ctypes.c_void_p),
                    ("sip_client_data", ctypes.c_void_p),
                    ("ui_choice", wintypes.DWORD),
                    ("revocation_checks", wintypes.DWORD),
                    ("union_choice", wintypes.DWORD),
                    ("file_info", ctypes.POINTER(WintrustFileInfo)),
                    ("state_action", wintypes.DWORD),
                    ("state_data", wintypes.HANDLE),
                    ("url_reference", wintypes.LPWSTR),
                    ("provider_flags", wintypes.DWORD),
                    ("ui_context", wintypes.DWORD),
                    ("signature_settings", ctypes.c_void_p),
                ]

            class CryptProviderCert(ctypes.Structure):
                _fields_ = [
                    ("cb_struct", wintypes.DWORD),
                    ("cert_context", ctypes.c_void_p),
                    ("commercial", wintypes.BOOL),
                    ("trusted_root", wintypes.BOOL),
                    ("self_signed", wintypes.BOOL),
                    ("test_cert", wintypes.BOOL),
                    ("revoked_reason", wintypes.DWORD),
                    ("confidence", wintypes.DWORD),
                    ("error", wintypes.DWORD),
                    ("trust_list_context", ctypes.c_void_p),
                    ("trust_list_signer_cert", wintypes.BOOL),
                    ("ctl_context", ctypes.c_void_p),
                    ("ctl_error", wintypes.DWORD),
                    ("is_cyclic", wintypes.BOOL),
                    ("chain_element", ctypes.c_void_p),
                ]

            class CryptProviderSigner(ctypes.Structure):
                _fields_ = [
                    ("cb_struct", wintypes.DWORD),
                    ("verify_as_of", wintypes.FILETIME),
                    ("cert_chain_count", wintypes.DWORD),
                    (
                        "cert_chain",
                        ctypes.POINTER(CryptProviderCert),
                    ),
                    ("signer_type", wintypes.DWORD),
                    ("signer", ctypes.c_void_p),
                    ("error", wintypes.DWORD),
                    ("counter_signer_count", wintypes.DWORD),
                    ("counter_signers", ctypes.c_void_p),
                    ("chain_context", ctypes.c_void_p),
                ]

            action = Guid(
                0x00AAC56B,
                0xCD44,
                0x11D0,
                (ctypes.c_ubyte * 8)(
                    0x8C,
                    0xC2,
                    0x00,
                    0xC0,
                    0x4F,
                    0xC2,
                    0x95,
                    0xEE,
                ),
            )
            file_info = WintrustFileInfo(
                ctypes.sizeof(WintrustFileInfo),
                str(candidate),
                None,
                None,
            )
            trust_data = WintrustData()
            trust_data.cb_struct = ctypes.sizeof(WintrustData)
            trust_data.ui_choice = 2  # WTD_UI_NONE
            trust_data.revocation_checks = 0  # WTD_REVOKE_NONE
            trust_data.union_choice = 1  # WTD_CHOICE_FILE
            trust_data.file_info = ctypes.pointer(file_info)
            trust_data.state_action = 1  # WTD_STATEACTION_VERIFY
            # WTD_REVOCATION_CHECK_NONE | WTD_CACHE_ONLY_URL_RETRIEVAL
            trust_data.provider_flags = 0x10 | 0x1000

            wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
            verify = wintrust.WinVerifyTrust
            verify.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(Guid),
                ctypes.POINTER(WintrustData),
            ]
            verify.restype = wintypes.LONG
            provider_data = wintrust.WTHelperProvDataFromStateData
            provider_data.argtypes = [wintypes.HANDLE]
            provider_data.restype = ctypes.c_void_p
            provider_signer = wintrust.WTHelperGetProvSignerFromChain
            provider_signer.argtypes = [
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            provider_signer.restype = ctypes.POINTER(CryptProviderSigner)

            status = int(verify(None, ctypes.byref(action), ctypes.byref(trust_data)))
            if status != 0:
                return _EdgeVerificationResult(
                    False,
                    reason="winverifytrust_rejected",
                    status_code=status,
                )

            publisher = ""
            state_provider = provider_data(trust_data.state_data)
            signer = (
                provider_signer(state_provider, 0, False, 0) if state_provider else None
            )
            if (
                signer
                and signer.contents.cert_chain_count
                and signer.contents.cert_chain
            ):
                cert_context = signer.contents.cert_chain[0].cert_context
                crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
                get_name = crypt32.CertGetNameStringW
                get_name.argtypes = [
                    ctypes.c_void_p,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    ctypes.c_void_p,
                    wintypes.LPWSTR,
                    wintypes.DWORD,
                ]
                get_name.restype = wintypes.DWORD
                organization_oid = ctypes.c_char_p(b"2.5.4.10")
                organization_parameter = ctypes.cast(
                    organization_oid,
                    ctypes.c_void_p,
                )
                length = get_name(
                    cert_context,
                    3,  # CERT_NAME_ATTR_TYPE
                    0,
                    organization_parameter,
                    None,
                    0,
                )
                if length:
                    name_buffer = ctypes.create_unicode_buffer(length)
                    if get_name(
                        cert_context,
                        3,
                        0,
                        organization_parameter,
                        name_buffer,
                        length,
                    ):
                        publisher = name_buffer.value.strip()

            if publisher.casefold() != "microsoft corporation":
                return _EdgeVerificationResult(
                    False,
                    publisher=publisher,
                    reason="publisher_not_microsoft",
                )
            return _EdgeVerificationResult(True, publisher=publisher)
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            return _EdgeVerificationResult(
                False,
                reason=f"verification_error_{type(exc).__name__}",
            )
        finally:
            trust_data_value = locals().get("trust_data")
            verify_value = locals().get("verify")
            action_value = locals().get("action")
            if (
                trust_data_value is not None
                and verify_value is not None
                and action_value is not None
                and trust_data_value.state_data
            ):
                try:
                    trust_data_value.state_action = 2  # STATEACTION_CLOSE
                    verify_value(
                        None,
                        ctypes.byref(action_value),
                        ctypes.byref(trust_data_value),
                    )
                except (AttributeError, OSError, TypeError, ValueError):
                    pass

    def _get_edge_version(
        self,
        edge_path: Path,
        *,
        timeout_seconds: float = 5.0,
    ) -> str:
        file_version = self._windows_file_version(edge_path)
        if file_version:
            return f"Microsoft Edge {file_version}"
        # 正式対象のWindowsでは、version resourceを読めないexeを
        # ``--version`` で追加起動しない。通常ブラウザーへの接続や
        # 意図しない外部通信を避け、版数は空欄のまま扱う。
        if os.name == "nt":
            return ""
        try:
            completed = self._version_runner(
                [str(edge_path), "--version"],
                shell=False,
                capture_output=True,
                text=True,
                timeout=max(0.01, min(5.0, timeout_seconds)),
                **self._hidden_process_options(),
            )
            output = " ".join(
                part.strip()
                for part in (
                    getattr(completed, "stdout", ""),
                    getattr(completed, "stderr", ""),
                )
                if part and part.strip()
            )
            return re.sub(r"\s+", " ", output)[:200]
        except (OSError, subprocess.SubprocessError):
            return ""

    @staticmethod
    def _windows_file_version(edge_path: Path) -> str:
        """既存ブラウザーセッションを起動せずexeの製品版数を取得する。"""
        if os.name != "nt":
            return ""
        try:
            import ctypes
            from ctypes import wintypes

            class FixedFileInfo(ctypes.Structure):
                _fields_ = [
                    ("signature", wintypes.DWORD),
                    ("struct_version", wintypes.DWORD),
                    ("file_version_ms", wintypes.DWORD),
                    ("file_version_ls", wintypes.DWORD),
                    ("product_version_ms", wintypes.DWORD),
                    ("product_version_ls", wintypes.DWORD),
                    ("file_flags_mask", wintypes.DWORD),
                    ("file_flags", wintypes.DWORD),
                    ("file_os", wintypes.DWORD),
                    ("file_type", wintypes.DWORD),
                    ("file_subtype", wintypes.DWORD),
                    ("file_date_ms", wintypes.DWORD),
                    ("file_date_ls", wintypes.DWORD),
                ]

            version_api = ctypes.WinDLL("version", use_last_error=True)
            get_size = version_api.GetFileVersionInfoSizeW
            get_size.argtypes = [
                wintypes.LPCWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            get_size.restype = wintypes.DWORD
            get_info = version_api.GetFileVersionInfoW
            get_info.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
            ]
            get_info.restype = wintypes.BOOL
            query_value = version_api.VerQueryValueW
            query_value.argtypes = [
                ctypes.c_void_p,
                wintypes.LPCWSTR,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(wintypes.UINT),
            ]
            query_value.restype = wintypes.BOOL

            unused_handle = wintypes.DWORD()
            size = get_size(
                str(edge_path),
                ctypes.byref(unused_handle),
            )
            if not size:
                return ""
            buffer = ctypes.create_string_buffer(size)
            if not get_info(
                str(edge_path),
                0,
                size,
                ctypes.cast(buffer, ctypes.c_void_p),
            ):
                return ""
            value_pointer = ctypes.c_void_p()
            value_length = wintypes.UINT()
            if not query_value(
                ctypes.cast(buffer, ctypes.c_void_p),
                "\\",
                ctypes.byref(value_pointer),
                ctypes.byref(value_length),
            ):
                return ""
            if value_length.value < ctypes.sizeof(FixedFileInfo):
                return ""
            info = ctypes.cast(
                value_pointer,
                ctypes.POINTER(FixedFileInfo),
            ).contents
            if info.signature != 0xFEEF04BD:
                return ""
            return ".".join(
                str(value)
                for value in (
                    info.file_version_ms >> 16,
                    info.file_version_ms & 0xFFFF,
                    info.file_version_ls >> 16,
                    info.file_version_ls & 0xFFFF,
                )
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return ""

    @staticmethod
    def _hidden_process_options() -> dict:
        if os.name != "nt":
            return {}
        options = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
        if startupinfo_factory is not None:
            startupinfo = startupinfo_factory()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startupinfo.wShowWindow = 0
            options["startupinfo"] = startupinfo
        return options

    @staticmethod
    def _terminate_process_tree(
        process,
        *,
        timeout_seconds: float = 0.5,
    ) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            taskkill_path = HtmlToPdfConverter._windows_taskkill_path()
            try:
                if taskkill_path is not None:
                    completed = subprocess.run(
                        [
                            str(taskkill_path),
                            "/PID",
                            str(process.pid),
                            "/T",
                            "/F",
                        ],
                        shell=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=max(0.01, timeout_seconds),
                        creationflags=getattr(
                            subprocess,
                            "CREATE_NO_WINDOW",
                            0,
                        ),
                        check=False,
                    )
                    if completed.returncode == 0 or process.poll() is not None:
                        return
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            process.terminate()
            if process.poll() is None:
                process.kill()
        except OSError:
            try:
                process.kill()
            except OSError:
                pass

    @staticmethod
    def _windows_taskkill_path() -> Optional[Path]:
        """WindowsのSystem32にあるtaskkillだけを解決する。"""

        if os.name != "nt":
            return None
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetSystemDirectoryW(
                buffer,
                len(buffer),
            )
            if not 0 < length < len(buffer):
                return None
            candidate = Path(buffer.value) / "taskkill.exe"
            if candidate.is_file():
                return candidate.resolve(strict=False)
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        return None

    def _validate_pdf(
        self,
        output_path: Path,
        *,
        started_at: float,
        cancel_check: CancelCheck,
        edge_path: Path,
        edge_version: str,
        base_issues: Tuple[DownloadIssue, ...],
    ) -> tuple[
        Optional[DownloadIssue],
        int,
        str,
        Optional[HtmlToPdfResult],
    ]:
        guard_result = self._guard_conversion(
            output_path,
            started_at,
            cancel_check,
            edge_path=edge_path,
            edge_version=edge_version,
            stage=DownloadStage.VALIDATE,
            activity="生成されたPDFの検証",
            base_issues=base_issues,
        )
        if guard_result is not None:
            return None, 0, "", guard_result
        if not output_path.is_file():
            return (
                _issue(
                    DownloadIssueCode.OUTPUT_MISSING,
                    DownloadStage.VALIDATE,
                    "Microsoft EdgeがPDFファイルを生成しませんでした",
                ),
                0,
                "",
                None,
            )
        try:
            size = output_path.stat().st_size
            if size <= 0:
                return (
                    _issue(
                        DownloadIssueCode.OUTPUT_EMPTY,
                        DownloadStage.VALIDATE,
                        "生成されたPDFファイルが空です",
                    ),
                    0,
                    "",
                    None,
                )
            with output_path.open("rb") as stream:
                signature = stream.read(5)
                stream.seek(max(0, size - 2048))
                tail = stream.read()
            guard_result = self._guard_conversion(
                output_path,
                started_at,
                cancel_check,
                edge_path=edge_path,
                edge_version=edge_version,
                stage=DownloadStage.VALIDATE,
                activity="生成されたPDFの検証",
                base_issues=base_issues,
            )
            if guard_result is not None:
                return None, 0, "", guard_result
            if signature != b"%PDF-":
                return (
                    _issue(
                        DownloadIssueCode.OUTPUT_INVALID_PDF,
                        DownloadStage.VALIDATE,
                        "生成ファイルのPDF署名が不正です",
                        details={"validation": "signature"},
                    ),
                    0,
                    "",
                    None,
                )
            if not tail.rstrip().endswith(b"%%EOF"):
                return (
                    _issue(
                        DownloadIssueCode.OUTPUT_INVALID_PDF,
                        DownloadStage.VALIDATE,
                        "生成されたPDFが完全ではありません",
                        details={"validation": "eof"},
                    ),
                    0,
                    "",
                    None,
                )
            digest = hashlib.sha256()
            with output_path.open("rb") as stream:
                while True:
                    guard_result = self._guard_conversion(
                        output_path,
                        started_at,
                        cancel_check,
                        edge_path=edge_path,
                        edge_version=edge_version,
                        stage=DownloadStage.VALIDATE,
                        activity="生成されたPDFの検証",
                        base_issues=base_issues,
                    )
                    if guard_result is not None:
                        return None, 0, "", guard_result
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            guard_result = self._guard_conversion(
                output_path,
                started_at,
                cancel_check,
                edge_path=edge_path,
                edge_version=edge_version,
                stage=DownloadStage.VALIDATE,
                activity="生成されたPDFの検証",
                base_issues=base_issues,
            )
            if guard_result is not None:
                return None, 0, "", guard_result
            return None, size, digest.hexdigest(), None
        except OSError as exc:
            return (
                _issue(
                    DownloadIssueCode.SAVE_FAILED,
                    DownloadStage.VALIDATE,
                    "生成されたPDFを検証できませんでした",
                    details={"error_type": type(exc).__name__},
                ),
                0,
                "",
                None,
            )

    @staticmethod
    def _looks_like_policy_error(stderr_tail: str) -> bool:
        lowered = stderr_tail.lower()
        return any(
            marker in lowered
            for marker in (
                "policy",
                "policies",
                "administrator",
                "not allowed",
                "disabled by",
                "blocked by",
            )
        )

    @staticmethod
    def _stderr_tail(path: Path) -> str:
        try:
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - 4096))
                text = stream.read(4096).decode(
                    "utf-8",
                    errors="replace",
                )
        except OSError:
            return ""
        return re.sub(r"[\r\n\t]+", " ", text).strip()[-500:]

    @staticmethod
    def _is_cancelled(cancel_check: CancelCheck) -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception:
            return False

    def _guard_conversion(
        self,
        output_path: Path,
        started_at: float,
        cancel_check: CancelCheck,
        *,
        edge_path: Optional[Path] = None,
        edge_version: str = "",
        stage: DownloadStage = DownloadStage.CONVERT,
        activity: str = "Microsoft EdgeによるPDF変換",
        base_issues: Tuple[DownloadIssue, ...] = (),
    ) -> Optional[HtmlToPdfResult]:
        """変換全体にキャンセルと共通期限を適用する。"""
        if self._is_cancelled(cancel_check):
            return self._cancelled_result(
                output_path,
                started_at,
                edge_path=edge_path,
                edge_version=edge_version,
                stage=stage,
                activity=activity,
                base_issues=base_issues,
            )
        if self._clock() - started_at >= self.timeout_seconds:
            return self._timeout_result(
                output_path,
                started_at,
                edge_path=edge_path,
                edge_version=edge_version,
                stage=stage,
                activity=activity,
                base_issues=base_issues,
            )
        return None

    def _timeout_result(
        self,
        output_path: Path,
        started_at: float,
        *,
        edge_path: Optional[Path] = None,
        edge_version: str = "",
        stage: DownloadStage,
        activity: str,
        base_issues: Tuple[DownloadIssue, ...] = (),
    ) -> HtmlToPdfResult:
        return self._failed_result(
            output_path,
            started_at,
            edge_path=edge_path,
            edge_version=edge_version,
            issues=base_issues
            + (
                _issue(
                    DownloadIssueCode.CONVERSION_TIMEOUT,
                    stage,
                    f"{activity}が{self.timeout_seconds:g}秒以内に完了しませんでした",
                    details={
                        "timeout_seconds": self.timeout_seconds,
                    },
                ),
            ),
        )

    @staticmethod
    def _remove_output_part(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise OSError("既存のPDF一時ファイルを削除できません") from exc

    def _safe_unlink(
        self,
        path: Path,
        *,
        deadline: Optional[float] = None,
    ) -> Optional[DownloadIssue]:
        """Edgeのハンドル解放を待ちつつ一時PDFを削除する。"""
        last_error: Optional[OSError] = None
        cleanup_deadline = (
            deadline
            if deadline is not None
            else self._clock() + min(5.0, self.timeout_seconds)
        )
        while True:
            try:
                path.unlink(missing_ok=True)
                return None
            except OSError as exc:
                last_error = exc
            remaining = cleanup_deadline - self._clock()
            if remaining <= 0:
                break
            self._sleep(min(self.poll_interval, remaining))
        return _issue(
            DownloadIssueCode.TEMP_CLEANUP_FAILED,
            DownloadStage.CLEANUP,
            "PDF一時ファイルを削除できませんでした",
            severity=IssueSeverity.WARNING,
            details={
                "error_type": (type(last_error).__name__ if last_error else "OSError")
            },
        )

    def _safe_rmtree(
        self,
        path: Path,
        *,
        deadline: Optional[float] = None,
    ) -> Optional[DownloadIssue]:
        """Edge子プロセスの終了を待ちつつ専用一時領域を削除する。"""
        last_error: Optional[OSError] = None
        cleanup_deadline = (
            deadline
            if deadline is not None
            else self._clock() + min(5.0, self.timeout_seconds)
        )
        while True:
            try:
                shutil.rmtree(path)
                return None
            except FileNotFoundError:
                return None
            except OSError as exc:
                last_error = exc
            remaining = cleanup_deadline - self._clock()
            if remaining <= 0:
                break
            self._sleep(min(self.poll_interval, remaining))
        return _issue(
            DownloadIssueCode.TEMP_CLEANUP_FAILED,
            DownloadStage.CLEANUP,
            "Microsoft Edgeの一時ファイルを削除できませんでした",
            severity=IssueSeverity.WARNING,
            details={
                "error_type": (type(last_error).__name__ if last_error else "OSError")
            },
        )

    def _failed_result(
        self,
        output_path: Path,
        started_at: float,
        *,
        edge_path: Optional[Path] = None,
        edge_version: str = "",
        exit_code: Optional[int] = None,
        issues: Tuple[DownloadIssue, ...],
        conversion_id: str = "",
        renderer: str = "",
        renderer_version: str = "",
    ) -> HtmlToPdfResult:
        return HtmlToPdfResult(
            status=HtmlToPdfStatus.FAILED,
            output_path=str(output_path),
            edge_path=str(edge_path) if edge_path else "",
            edge_version=edge_version,
            elapsed_seconds=max(0.0, self._clock() - started_at),
            exit_code=exit_code,
            issues=issues,
            conversion_id=conversion_id,
            renderer=renderer,
            renderer_version=renderer_version,
        )

    def _cancelled_result(
        self,
        output_path: Path,
        started_at: float,
        *,
        edge_path: Optional[Path] = None,
        edge_version: str = "",
        stage: DownloadStage = DownloadStage.CONVERT,
        activity: str = "HTMLからPDFへの変換",
        base_issues: Tuple[DownloadIssue, ...] = (),
    ) -> HtmlToPdfResult:
        return HtmlToPdfResult(
            status=HtmlToPdfStatus.CANCELLED,
            output_path=str(output_path),
            edge_path=str(edge_path) if edge_path else "",
            edge_version=edge_version,
            elapsed_seconds=max(0.0, self._clock() - started_at),
            issues=base_issues
            + (
                _issue(
                    DownloadIssueCode.CANCELLED,
                    stage,
                    f"{activity}をキャンセルしました",
                ),
            ),
        )
