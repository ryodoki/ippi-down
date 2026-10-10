# -*- coding: utf-8 -*-

"""Microsoft Edge HTML→PDF変換の単体テスト。"""

from __future__ import annotations

import hashlib
import io
import multiprocessing
import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest
from bs4 import BeautifulSoup

from src.core.html_to_pdf import (
    HtmlToPdfConverter,
    HtmlToPdfStatus,
    validate_and_sanitize_bid_sheet_html,
)
from src.core.pdf_conversion_audit import PdfConversionAudit
from src.core.windows_process_supervisor import SupervisedProcessResult
from src.models.download_diagnostics import (
    DownloadIssueCode,
    DownloadStage,
    IssueSeverity,
)


SOURCE_URL = (
    "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet"
    "?AnkenKanriNo=021020002025412000000502&BunshoKanriId=40"
)
PROJECT_NAME = "志津地すべり排水トンネル第３期工事"
DOCUMENT_NAME = "入札調書"

VALID_HTML = f"""<!doctype html>
<html>
  <head>
    <title>入札調書</title>
    <link rel="stylesheet" href="https://external.test/site.css">
    <style>@import "https://external.test/a.css"; .x {{ background: url(x); }}</style>
    <meta http-equiv="refresh" content="10; url=https://external.test/">
  </head>
  <body onload="steal()">
    <h1>入札調書</h1>
    <script>fetch("https://external.test/")</script>
    <iframe src="https://external.test/"></iframe>
    <table id="summary">
      <tr><th>件名</th><td>{PROJECT_NAME}</td></tr>
      <tr><th>所属事務所</th><td>東北地方整備局</td></tr>
      <tr><th>入札日時</th><td>2026年7月30日</td></tr>
    </table>
    <table id="details">
      <tr><th>業者名</th><th>入札金額</th></tr>
      <tr><td>テスト建設株式会社</td><td>123,456,000円</td></tr>
    </table>
    <img src="https://external.test/logo.png" onerror="steal()">
    <a href="https://external.test/">外部リンク</a>
  </body>
</html>
"""

PDF_PAYLOAD = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def test_monitored_edge_retries_gpu_crash_with_isolated_profile(tmp_path):
    class RetrySupervisor:
        def __init__(self):
            self.commands = []

        def run(self, command, **_kwargs):
            self.commands.append(tuple(command))
            if len(self.commands) == 1:
                return SupervisedProcessResult(
                    "completed",
                    -1073741790,
                    root_pid=100,
                    peak_process_count=4,
                    stderr_tail="GPU process isn't usable. 0xC0000022",
                )
            output_argument = next(
                value for value in command if value.startswith("--print-to-pdf=")
            )
            Path(output_argument.split("=", 1)[1]).write_bytes(PDF_PAYLOAD)
            return SupervisedProcessResult(
                "completed",
                0,
                root_pid=200,
                peak_process_count=3,
            )

    supervisor = RetrySupervisor()
    output = tmp_path / "result.pdf.part"
    converter = HtmlToPdfConverter(
        edge_path=_edge(tmp_path),
        edge_verifier=lambda _path: True,
        version_runner=_version_runner,
        prefer_internal=False,
        process_supervisor=supervisor,
        audit=PdfConversionAudit(tmp_path / "logs"),
        _isolate_validation=False,
    )

    result = converter.convert(
        VALID_HTML,
        output,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert result.success
    assert result.renderer == "Microsoft Edge"
    assert len(supervisor.commands) == 2
    assert "profile-1" in " ".join(supervisor.commands[0])
    assert "profile-2" in " ".join(supervisor.commands[1])
    assert any(
        issue.code == DownloadIssueCode.EDGE_GPU_PROCESS_CRASH
        and issue.severity == IssueSeverity.WARNING
        for issue in result.issues
    )


def test_unexpected_internal_error_falls_back_to_monitored_edge(tmp_path):
    class BrokenInternalRenderer:
        name = "broken internal"
        version = "test"

        def render(self, *_args, **_kwargs):
            raise RuntimeError("sensitive internal detail")

    class SuccessfulSupervisor:
        def run(self, command, **_kwargs):
            output_argument = next(
                value for value in command if value.startswith("--print-to-pdf=")
            )
            Path(output_argument.split("=", 1)[1]).write_bytes(PDF_PAYLOAD)
            return SupervisedProcessResult("completed", 0, root_pid=300)

    converter = HtmlToPdfConverter(
        edge_path=_edge(tmp_path),
        edge_verifier=lambda _path: True,
        version_runner=_version_runner,
        internal_renderer=BrokenInternalRenderer(),
        prefer_internal=True,
        process_supervisor=SuccessfulSupervisor(),
        audit=PdfConversionAudit(tmp_path / "logs"),
        _isolate_validation=False,
    )

    result = converter.convert(
        VALID_HTML,
        tmp_path / "result.pdf.part",
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert result.success
    assert result.renderer == "Microsoft Edge"
    warning = next(
        issue
        for issue in result.issues
        if issue.code == DownloadIssueCode.PDF_INTERNAL_RENDER_FAILED
    )
    assert warning.severity == IssueSeverity.WARNING
    assert "sensitive internal detail" not in str(warning.details)


def test_stale_converter_temporary_roots_are_recovered_safely(tmp_path):
    stale = tmp_path / ".ippi-edge-p101-c1000-stale"
    active = tmp_path / ".ippi-validation-p202-c1000-active"
    fresh = tmp_path / ".ippi-edge-p303-c9999-fresh"
    unknown = tmp_path / ".ippi-edge-legacy-without-owner"
    for path in (stale, active, fresh, unknown):
        path.mkdir()
        (path / "marker").write_text("temporary", encoding="utf-8")

    removed = HtmlToPdfConverter.recover_stale_temporary_roots(
        tmp_path,
        stale_after_seconds=60,
        now=10_000,
        process_alive=lambda pid: pid == 202,
    )

    assert removed == (stale,)
    assert not stale.exists()
    assert active.exists()
    assert fresh.exists()
    assert unknown.exists()


class FakeProcess:
    def __init__(self, return_code=0, running=False, stderr=None):
        self.return_code = return_code
        self.running = running
        self.stderr = stderr
        self.pid = 12345
        self.terminated = False

    def poll(self):
        return None if self.running and not self.terminated else self.return_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        del timeout
        self.terminated = True
        return self.return_code


class FakePopen:
    def __init__(
        self,
        payload=PDF_PAYLOAD,
        *,
        return_code=0,
        running=False,
        stderr=b"",
        exception=None,
    ):
        self.payload = payload
        self.return_code = return_code
        self.running = running
        self.stderr = stderr
        self.exception = exception
        self.command = []
        self.kwargs = {}
        self.process = None

    def __call__(self, command, **kwargs):
        if self.exception:
            raise self.exception
        self.command = list(command)
        self.kwargs = kwargs
        if self.payload is not None:
            output_argument = next(
                value for value in command if value.startswith("--print-to-pdf=")
            )
            Path(output_argument.split("=", 1)[1]).write_bytes(self.payload)
        stderr_stream = io.BytesIO(self.stderr)
        self.process = FakeProcess(
            self.return_code,
            self.running,
            stderr=stderr_stream,
        )
        return self.process


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def _edge(tmp_path):
    edge_path = tmp_path / "msedge.exe"
    edge_path.write_bytes(b"fake edge")
    return edge_path


def _version_runner(*_args, **_kwargs):
    return SimpleNamespace(
        stdout="Microsoft Edge 130.0.2849.80\n",
        stderr="",
        returncode=0,
    )


def _converter(tmp_path, popen=None, **kwargs):
    kwargs.setdefault("edge_verifier", lambda _path: True)
    return HtmlToPdfConverter(
        edge_path=_edge(tmp_path),
        popen_factory=popen or FakePopen(),
        version_runner=_version_runner,
        _isolate_validation=False,
        **kwargs,
    )


def _convert(converter, source, destination, cancel_check=None):
    return converter.convert(
        source,
        destination,
        cancel_check,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )


def test_bid_sheet_validation_sanitizes_active_and_external_content():
    result = validate_and_sanitize_bid_sheet_html(
        VALID_HTML,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert result.success
    assert "Content-Security-Policy" in result.sanitized_html
    assert "default-src 'none'" in result.sanitized_html
    assert "size: A4 portrait" in result.sanitized_html
    assert "margin: 10mm" in result.sanitized_html
    assert "<script" not in result.sanitized_html
    assert "<iframe" not in result.sanitized_html
    assert "onload=" not in result.sanitized_html
    assert "onerror=" not in result.sanitized_html
    assert "https://external.test" not in result.sanitized_html
    assert result.issues[0].code == DownloadIssueCode.EXTERNAL_RESOURCE_BLOCKED
    assert result.issues[0].severity == IssueSeverity.WARNING


def test_spaced_meta_refresh_is_removed():
    html = VALID_HTML.replace(
        "</head>",
        (
            '<meta http-equiv=" Refresh " '
            'content="0; url=https://external.test/escape"></head>'
        ),
    )

    result = validate_and_sanitize_bid_sheet_html(
        html,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert result.success
    assert "external.test/escape" not in result.sanitized_html


def test_fixed_print_css_is_last_even_when_source_has_body_page_rule():
    hostile_html = VALID_HTML.replace(
        "</body>",
        (
            '<style data-source-style="late">'
            "@page { size: A3 landscape; margin: 0; }"
            "body { background: red !important; }"
            "</style></body>"
        ),
    )

    result = validate_and_sanitize_bid_sheet_html(
        hostile_html,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert result.success
    sanitized = BeautifulSoup(result.sanitized_html, "html.parser")
    styles = sanitized.head.find_all("style", recursive=False)
    assert styles[-1].get("data-ippi-print-style") == "true"
    assert "size: A4 portrait" in styles[-1].get_text()
    assert "margin: 10mm" in styles[-1].get_text()
    assert styles[-2].get("data-source-style") == "late"


def test_saved_id40_site_fixture_matches_current_bid_sheet_structure():
    fixture = (Path(__file__).parent / "fixtures" / "id40_bid_sheet.html").read_bytes()

    result = validate_and_sanitize_bid_sheet_html(
        fixture,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert result.success
    assert "新庄河川事務所" in result.sanitized_html
    assert "三井住友建設株式会社" in result.sanitized_html
    assert "無効" in result.sanitized_html


def test_project_name_must_match_the_value_in_the_subject_field():
    spoofed = VALID_HTML.replace(
        f"<tr><th>件名</th><td>{PROJECT_NAME}</td></tr>",
        (
            "<tr><th>件名</th><td>全く別の道路工事</td></tr>"
            f'<tr><td colspan="2">関連案件: {PROJECT_NAME}</td></tr>'
        ),
    )

    result = validate_and_sanitize_bid_sheet_html(
        spoofed,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.PROJECT_NAME_MISMATCH


def test_project_name_field_accepts_the_sites_numbered_label():
    numbered = VALID_HTML.replace(
        "<th>件名</th>",
        "<th>１．件名</th>",
    )

    result = validate_and_sanitize_bid_sheet_html(
        numbered,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert result.success


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("所属事務所", "東北地方整備局"),
        ("入札日時", "2026年7月30日"),
    ],
)
def test_required_summary_field_must_have_a_value(label, value):
    missing_value = VALID_HTML.replace(
        f"<tr><th>{label}</th><td>{value}</td></tr>",
        f"<tr><th>{label}</th><td></td></tr>",
    )

    result = validate_and_sanitize_bid_sheet_html(
        missing_value,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.HTML_STRUCTURE_INVALID
    assert label in result.primary_issue.details["missing"]


@pytest.mark.parametrize("result_text", ["辞退", "無効", "不参加"])
def test_bid_sheet_accepts_detail_rows_with_a_valid_non_numeric_result(
    result_text,
):
    state_only = VALID_HTML.replace("123,456,000円", result_text)

    result = validate_and_sanitize_bid_sheet_html(
        state_only,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert result.success


@pytest.mark.parametrize(
    ("source_url", "document_name", "project_name", "html", "expected_code"),
    [
        (
            SOURCE_URL.replace("https://e2ppiw01.e-bisc.go.jp", "http://evil.test"),
            DOCUMENT_NAME,
            PROJECT_NAME,
            VALID_HTML,
            DownloadIssueCode.UNEXPECTED_HTML,
        ),
        (
            SOURCE_URL.replace(
                "/CALS/Publish/KokaiBunshoServlet",
                "/not-the-servlet/CALS/Publish/KokaiBunshoServlet",
            ),
            DOCUMENT_NAME,
            PROJECT_NAME,
            VALID_HTML,
            DownloadIssueCode.UNEXPECTED_HTML,
        ),
        (
            SOURCE_URL,
            "公告文書",
            PROJECT_NAME,
            VALID_HTML,
            DownloadIssueCode.UNEXPECTED_HTML,
        ),
        (
            SOURCE_URL,
            DOCUMENT_NAME,
            "別の工事",
            VALID_HTML,
            DownloadIssueCode.PROJECT_NAME_MISMATCH,
        ),
        (
            SOURCE_URL,
            DOCUMENT_NAME,
            PROJECT_NAME,
            VALID_HTML.replace("所属事務所", "発注元"),
            DownloadIssueCode.HTML_STRUCTURE_INVALID,
        ),
        (
            SOURCE_URL,
            DOCUMENT_NAME,
            PROJECT_NAME,
            VALID_HTML.replace(
                "<tr><td>テスト建設株式会社</td><td>123,456,000円</td></tr>",
                "",
            ),
            DownloadIssueCode.HTML_STRUCTURE_INVALID,
        ),
        (
            SOURCE_URL,
            DOCUMENT_NAME,
            PROJECT_NAME,
            VALID_HTML.replace(
                "<h1>入札調書</h1>",
                "<h1>入札調書</h1><p>公開期間外</p>",
            ),
            DownloadIssueCode.HTML_STRUCTURE_INVALID,
        ),
        (
            SOURCE_URL,
            DOCUMENT_NAME,
            PROJECT_NAME,
            VALID_HTML.replace("<h1>入札調書</h1>", "<h1>エラーが発生しました</h1>"),
            DownloadIssueCode.HTML_STRUCTURE_INVALID,
        ),
    ],
)
def test_bid_sheet_validation_rejects_untrusted_or_incomplete_html(
    source_url,
    document_name,
    project_name,
    html,
    expected_code,
):
    result = validate_and_sanitize_bid_sheet_html(
        html,
        source_url=source_url,
        document_name=document_name,
        project_name=project_name,
    )

    assert not result.success
    assert result.primary_issue.code == expected_code


def test_discover_edge_checks_standard_install_location(tmp_path, monkeypatch):
    program_files = tmp_path / "Program Files (x86)"
    edge_path = program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge_path.parent.mkdir(parents=True)
    edge_path.write_bytes(b"edge")
    monkeypatch.setattr(
        HtmlToPdfConverter,
        "_registry_edge_paths",
        staticmethod(lambda: []),
    )

    discovered = HtmlToPdfConverter.discover_edge(
        {"PROGRAMFILES(X86)": str(program_files), "PATH": ""}
    )

    assert discovered == edge_path.resolve()


def test_discover_edge_checks_windows_app_paths(tmp_path, monkeypatch):
    edge_path = _edge(tmp_path)
    monkeypatch.setattr(
        HtmlToPdfConverter,
        "_registry_edge_paths",
        staticmethod(lambda: [edge_path]),
    )

    discovered = HtmlToPdfConverter.discover_edge({"PATH": ""})

    assert discovered == edge_path.resolve()


def test_discover_edge_does_not_execute_an_untrusted_path_candidate(
    tmp_path,
    monkeypatch,
):
    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_bytes(b"not Microsoft Edge")
    monkeypatch.setattr(
        HtmlToPdfConverter,
        "_registry_edge_paths",
        staticmethod(lambda: []),
    )

    discovered = HtmlToPdfConverter.discover_edge({"PATH": str(tmp_path)})

    assert discovered is None


def test_convert_creates_valid_part_with_hash_and_cleans_temporary_data(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        HtmlToPdfConverter,
        "_windows_file_version",
        staticmethod(lambda _path: "130.0.2849.80"),
    )
    source_path = tmp_path / "downloaded.html"
    source_path.write_text(VALID_HTML, encoding="utf-8")
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen()
    converter = _converter(tmp_path, popen)

    result = _convert(converter, source_path, destination)

    assert result.status == HtmlToPdfStatus.SUCCESS
    assert result.success
    assert destination.read_bytes() == PDF_PAYLOAD
    assert source_path.exists()
    assert result.bytes_written == len(PDF_PAYLOAD)
    assert result.sha256 == hashlib.sha256(PDF_PAYLOAD).hexdigest()
    assert result.edge_version == "Microsoft Edge 130.0.2849.80"
    assert "--headless=new" in popen.command
    assert "--disable-quic" in popen.command
    assert "--no-proxy-server" in popen.command
    assert "--host-resolver-rules=MAP * ~NOTFOUND" in popen.command
    assert "--no-pdf-header-footer" in popen.command
    assert "--print-to-pdf-no-header" in popen.command
    assert popen.kwargs["shell"] is False
    assert popen.command[-1].startswith("file:")
    assert not list(tmp_path.glob(".ippi-edge-*"))


def test_convert_does_not_start_edge_when_signature_verification_fails(
    tmp_path,
):
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen()
    converter = _converter(
        tmp_path,
        popen,
        edge_verifier=lambda _path: False,
    )

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.EDGE_START_FAILED
    assert result.primary_issue.details["verification"] == (
        "injected_verifier_rejected"
    )
    assert popen.process is None
    assert not destination.exists()
    assert not list(tmp_path.glob(".ippi-edge-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows署名検証専用")
def test_installed_edge_has_trusted_microsoft_authenticode_signature():
    edge_path = HtmlToPdfConverter.discover_edge()
    if edge_path is None:
        pytest.skip("Microsoft Edgeがインストールされていません")

    verification = HtmlToPdfConverter._verify_edge_authenticode(edge_path)

    assert verification.trusted, verification
    assert verification.publisher == "Microsoft Corporation"


def test_isolated_path_input_is_read_and_sanitized_only_in_child_process(
    tmp_path,
    monkeypatch,
):
    class InspectingPopen(FakePopen):
        sanitized_html = ""

        def __call__(self, command, **kwargs):
            source_uri = command[-1]
            source_path = Path(url2pathname(urlsplit(source_uri).path))
            self.sanitized_html = source_path.read_text(encoding="utf-8")
            return super().__call__(command, **kwargs)

    source_path = tmp_path / "downloaded.html"
    source_path.write_text(VALID_HTML, encoding="utf-8")
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = InspectingPopen()
    converter = HtmlToPdfConverter(
        edge_path=_edge(tmp_path),
        popen_factory=popen,
        version_runner=_version_runner,
        edge_verifier=lambda _path: True,
    )

    def fail_if_parent_reads_payload(*_args, **_kwargs):
        raise AssertionError("隔離経路の親processがHTML本文を読み込みました")

    monkeypatch.setattr(
        converter,
        "_read_source_payload_with_monitor",
        fail_if_parent_reads_payload,
    )

    result = _convert(converter, source_path, destination)

    assert result.success
    assert source_path.exists()
    assert "Content-Security-Policy" in popen.sanitized_html
    assert "<script" not in popen.sanitized_html
    assert "https://external.test" not in popen.sanitized_html
    assert not list(tmp_path.glob(".ippi-edge-*"))
    assert not any(
        child.name == "ippi-html-validation"
        for child in multiprocessing.active_children()
    )


def test_isolated_bytes_input_keeps_public_conversion_compatibility(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    converter = HtmlToPdfConverter(
        edge_path=_edge(tmp_path),
        popen_factory=FakePopen(),
        version_runner=_version_runner,
        edge_verifier=lambda _path: True,
    )

    result = _convert(converter, VALID_HTML.encode("utf-8"), destination)

    assert result.success
    assert destination.read_bytes() == PDF_PAYLOAD
    assert not list(tmp_path.glob(".ippi-edge-*"))


def test_isolated_validation_failure_returns_only_diagnostics_and_cleans(
    tmp_path,
):
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen()
    converter = HtmlToPdfConverter(
        edge_path=_edge(tmp_path),
        popen_factory=popen,
        version_runner=_version_runner,
        edge_verifier=lambda _path: True,
    )
    invalid_html = VALID_HTML.replace(
        "<title>入札調書</title>",
        "<title>エラーページ</title>",
    )

    result = _convert(converter, invalid_html, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.HTML_STRUCTURE_INVALID
    assert result.primary_issue.details["validation"] == "title"
    assert popen.process is None
    assert not destination.exists()
    assert not list(tmp_path.glob(".ippi-edge-*"))
    assert not any(
        child.name == "ippi-html-validation"
        for child in multiprocessing.active_children()
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows版数取得専用")
def test_edge_version_failure_does_not_launch_a_second_edge_process(
    tmp_path,
    monkeypatch,
):
    version_runner = Mock()
    monkeypatch.setattr(
        HtmlToPdfConverter,
        "_windows_file_version",
        staticmethod(lambda _path: ""),
    )
    converter = HtmlToPdfConverter(
        edge_path=_edge(tmp_path),
        version_runner=version_runner,
    )

    version = converter._get_edge_version(_edge(tmp_path))

    assert version == ""
    version_runner.assert_not_called()


def test_convert_requires_context_by_default(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    converter = _converter(tmp_path)

    result = converter.convert(VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.UNEXPECTED_HTML
    assert not destination.exists()


def test_conversion_can_be_cancelled_between_validation_stages(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen()
    checks = 0

    def cancel_check():
        nonlocal checks
        checks += 1
        return checks >= 3

    converter = _converter(tmp_path, popen)
    result = _convert(
        converter,
        VALID_HTML,
        destination,
        cancel_check,
    )

    assert result.cancelled
    assert result.primary_issue.code == DownloadIssueCode.CANCELLED
    assert popen.process is None
    assert not destination.exists()
    assert not list(tmp_path.glob(".ippi-edge-*"))


def test_conversion_deadline_includes_html_validation(
    tmp_path,
    monkeypatch,
):
    from src.core import html_to_pdf as converter_module

    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen()
    clock = FakeClock()
    original_validate = converter_module.validate_and_sanitize_bid_sheet_html

    def slow_validate(*args, **kwargs):
        clock.value += 0.3
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(
        converter_module,
        "validate_and_sanitize_bid_sheet_html",
        slow_validate,
    )
    converter = _converter(
        tmp_path,
        popen,
        timeout_seconds=0.2,
        clock=clock,
        sleeper=clock.sleep,
    )

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.CONVERSION_TIMEOUT
    assert result.primary_issue.stage == DownloadStage.VALIDATE
    assert "入札調書HTMLの検証" in result.primary_issue.message
    assert "Microsoft Edge" not in result.primary_issue.message
    assert popen.process is None
    assert not destination.exists()


def test_blocked_html_validation_observes_live_cancellation(
    tmp_path,
    monkeypatch,
):
    from src.core import html_to_pdf as converter_module

    destination = tmp_path / "bid-sheet.pdf.part"
    source_path = tmp_path / "fetched-bid-sheet.html.part"
    source_path.write_text(VALID_HTML, encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    observed_payload_types = []
    original_validate = converter_module.validate_and_sanitize_bid_sheet_html

    def blocked_validate(source_html, *args, **kwargs):
        observed_payload_types.append(type(source_html))
        entered.set()
        try:
            release.wait(timeout=2)
            return original_validate(source_html, *args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(
        converter_module,
        "validate_and_sanitize_bid_sheet_html",
        blocked_validate,
    )
    converter = _converter(
        tmp_path,
        timeout_seconds=2,
        poll_interval=0.05,
    )
    started = time.monotonic()
    try:
        result = _convert(
            converter,
            source_path,
            destination,
            cancel_check=entered.is_set,
        )
        # 解析スレッドが止まっていても元HTMLのファイルハンドルは
        # 保持されず、HTTP側の後処理を直ちに行える。
        source_path.unlink()
    finally:
        release.set()
        finished.wait(timeout=1)

    assert result.cancelled
    assert time.monotonic() - started < 1
    assert observed_payload_types == [str]
    assert not source_path.exists()
    assert result.primary_issue.code == DownloadIssueCode.CANCELLED
    assert not destination.exists()


def test_blocked_html_validation_observes_hard_deadline(
    tmp_path,
    monkeypatch,
):
    from src.core import html_to_pdf as converter_module

    destination = tmp_path / "bid-sheet.pdf.part"
    release = threading.Event()
    finished = threading.Event()
    original_validate = converter_module.validate_and_sanitize_bid_sheet_html

    def blocked_validate(*args, **kwargs):
        try:
            release.wait(timeout=2)
            return original_validate(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(
        converter_module,
        "validate_and_sanitize_bid_sheet_html",
        blocked_validate,
    )
    converter = _converter(
        tmp_path,
        timeout_seconds=0.2,
        poll_interval=0.05,
    )
    started = time.monotonic()
    try:
        result = _convert(converter, VALID_HTML, destination)
    finally:
        release.set()
        finished.wait(timeout=1)

    assert not result.success
    assert time.monotonic() - started < 1
    assert result.primary_issue.code == DownloadIssueCode.CONVERSION_TIMEOUT
    assert not destination.exists()


def test_isolated_validation_process_is_stopped_on_cancellation(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    converter = HtmlToPdfConverter(
        timeout_seconds=2,
        poll_interval=0.05,
    )

    preparation, result = converter._prepare_in_process_with_monitor(
        VALID_HTML,
        output_path=destination,
        started_at=time.monotonic(),
        cancel_check=lambda: True,
        source_url=SOURCE_URL,
        document_name=DOCUMENT_NAME,
        project_name=PROJECT_NAME,
    )

    assert preparation is None
    assert result.cancelled
    assert result.primary_issue.stage == DownloadStage.VALIDATE
    assert not any(
        child.name == "ippi-html-validation"
        for child in multiprocessing.active_children()
    )
    assert not list(tmp_path.glob(".ippi-validation-*"))


def test_conversion_rejects_oversized_html_before_parsing(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen()
    converter = _converter(
        tmp_path,
        popen,
        max_html_bytes=100,
    )

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.HTML_STRUCTURE_INVALID
    assert result.primary_issue.details["max_bytes"] == 100
    assert popen.process is None
    assert not destination.exists()


def test_html_decoding_failure_is_reported_as_validation_issue(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "bid-sheet.pdf.part"
    converter = _converter(tmp_path)
    monkeypatch.setattr(
        converter,
        "_load_source_html",
        lambda _source: (_ for _ in ()).throw(UnicodeError("encoding unavailable")),
    )

    result = _convert(converter, b"\x81", destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.HTML_PARSE_FAILED
    assert result.primary_issue.stage == DownloadStage.VALIDATE
    assert "文字コード" in result.primary_issue.message
    assert not destination.exists()


def test_convert_reports_missing_edge_and_removes_old_part(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    destination.write_bytes(b"old partial file")
    converter = HtmlToPdfConverter(
        edge_path=tmp_path / "missing-msedge.exe",
        prefer_internal=False,
    )

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.EDGE_NOT_FOUND
    assert not destination.exists()


def test_convert_reports_edge_start_failure(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    converter = _converter(
        tmp_path,
        FakePopen(exception=OSError("cannot start")),
    )

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.EDGE_START_FAILED
    assert not destination.exists()
    assert not list(tmp_path.glob(".ippi-edge-*"))


def test_active_conversion_can_be_cancelled_and_terminates_only_started_tree(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen(running=True)
    terminated = []

    def cancel_check():
        return popen.process is not None

    converter = _converter(
        tmp_path,
        popen,
        tree_terminator=lambda process: (
            terminated.append(process),
            setattr(process, "terminated", True),
        ),
    )
    cleanup_windows = []
    original_safe_unlink = converter._safe_unlink

    def observed_safe_unlink(path, *, deadline=None):
        cleanup_windows.append(deadline - time.monotonic())
        return original_safe_unlink(path, deadline=deadline)

    monkeypatch.setattr(converter, "_safe_unlink", observed_safe_unlink)

    result = _convert(converter, VALID_HTML, destination, cancel_check)

    assert result.cancelled
    assert result.primary_issue.code == DownloadIssueCode.CANCELLED
    assert terminated == [popen.process]
    assert cleanup_windows
    assert 0 <= cleanup_windows[0] <= 0.55
    assert not destination.exists()
    assert not list(tmp_path.glob(".ippi-edge-*"))


def test_conversion_timeout_terminates_process_tree_and_removes_part(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen(running=True)
    clock = FakeClock()
    terminated = []
    converter = _converter(
        tmp_path,
        popen,
        timeout_seconds=0.2,
        poll_interval=0.1,
        clock=clock,
        sleeper=clock.sleep,
        tree_terminator=lambda process: (
            terminated.append(process),
            setattr(process, "terminated", True),
        ),
    )

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.CONVERSION_TIMEOUT
    assert terminated == [popen.process]
    assert result.elapsed_seconds <= converter.timeout_seconds
    assert not destination.exists()


def test_missing_temporary_profile_is_already_clean(tmp_path):
    converter = _converter(tmp_path)

    issue = converter._safe_rmtree(
        tmp_path / "already-removed",
        deadline=time.monotonic() + 0.5,
    )

    assert issue is None


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill専用")
def test_process_termination_uses_absolute_system_taskkill_and_falls_back(
    tmp_path,
    monkeypatch,
):
    process = FakeProcess(running=True)
    fake_path_taskkill = tmp_path / "taskkill.exe"
    fake_path_taskkill.write_bytes(b"untrusted")
    trusted_taskkill = Path("C:/Windows/System32/taskkill.exe")
    commands = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(
        HtmlToPdfConverter,
        "_windows_taskkill_path",
        staticmethod(lambda: trusted_taskkill),
    )

    def failed_taskkill(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(
        "src.core.html_to_pdf.subprocess.run",
        failed_taskkill,
    )

    HtmlToPdfConverter._terminate_process_tree(process)

    assert commands == [
        [
            str(trusted_taskkill),
            "/PID",
            str(process.pid),
            "/T",
            "/F",
        ]
    ]
    assert Path(commands[0][0]).is_absolute()
    assert commands[0][0] != str(fake_path_taskkill)
    assert process.terminated


def test_policy_rejection_is_distinguished_from_normal_nonzero_exit(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen(
        payload=None,
        return_code=1,
        stderr=b"Headless mode disabled by enterprise policy\r\nsecret detail",
    )
    converter = _converter(tmp_path, popen)

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == DownloadIssueCode.EDGE_START_FAILED
    assert result.primary_issue.details["reason"] == "policy_blocked"
    assert "\n" not in result.primary_issue.details["stderr_tail"]
    assert not destination.exists()


def test_edge_stderr_pipe_is_drained_with_a_bounded_tail(tmp_path):
    destination = tmp_path / "bid-sheet.pdf.part"
    popen = FakePopen(
        payload=None,
        return_code=1,
        stderr=(
            b"must-not-be-retained\n"
            + b"x" * (1024 * 1024)
            + b"\nheadless disabled by policy"
        ),
    )
    converter = _converter(tmp_path, popen)

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert popen.kwargs["stderr"] is subprocess.PIPE
    assert popen.process.stderr.closed
    stderr_tail = result.primary_issue.details["stderr_tail"]
    assert len(stderr_tail) <= 500
    assert "must-not-be-retained" not in stderr_tail
    assert stderr_tail.endswith("headless disabled by policy")
    assert not any(
        worker.name == "ippi-edge-stderr" and worker.is_alive()
        for worker in threading.enumerate()
    )


def test_edge_stderr_tail_reads_only_a_bounded_suffix(tmp_path):
    stderr_path = tmp_path / "edge-stderr.log"
    stderr_path.write_bytes(
        b"must-not-be-retained\n" + b"x" * (1024 * 1024) + b"\npolicy blocked marker"
    )

    tail = HtmlToPdfConverter._stderr_tail(stderr_path)

    assert len(tail) <= 500
    assert "\n" not in tail
    assert "must-not-be-retained" not in tail
    assert tail.endswith("policy blocked marker")


def test_pdf_hash_validation_observes_cancellation(
    tmp_path,
    monkeypatch,
):
    from src.core import html_to_pdf as converter_module

    destination = tmp_path / "bid-sheet.pdf.part"
    payload = b"%PDF-1.7\n" + b"x" * (2 * 1024 * 1024) + b"\n%%EOF\n"
    hash_started = threading.Event()
    real_sha256 = hashlib.sha256

    class ObservableDigest:
        def __init__(self):
            self._digest = real_sha256()

        def update(self, data):
            self._digest.update(data)
            hash_started.set()

        def hexdigest(self):
            return self._digest.hexdigest()

    monkeypatch.setattr(
        converter_module.hashlib,
        "sha256",
        ObservableDigest,
    )
    converter = _converter(tmp_path, FakePopen(payload=payload))

    result = _convert(
        converter,
        VALID_HTML,
        destination,
        cancel_check=hash_started.is_set,
    )

    assert result.cancelled
    assert result.primary_issue.code == DownloadIssueCode.CANCELLED
    assert result.primary_issue.stage == DownloadStage.VALIDATE
    assert "生成されたPDFの検証" in result.primary_issue.message
    assert not destination.exists()


@pytest.mark.parametrize(
    ("payload", "expected_code", "validation"),
    [
        (None, DownloadIssueCode.EDGE_OUTPUT_NOT_PRODUCED, None),
        (b"", DownloadIssueCode.OUTPUT_EMPTY, None),
        (b"not a pdf\n%%EOF", DownloadIssueCode.OUTPUT_INVALID_PDF, "signature"),
        (b"%PDF-1.7\nincomplete", DownloadIssueCode.OUTPUT_INVALID_PDF, "eof"),
    ],
)
def test_invalid_edge_output_is_classified_and_removed(
    tmp_path,
    payload,
    expected_code,
    validation,
):
    destination = tmp_path / "bid-sheet.pdf.part"
    converter = _converter(tmp_path, FakePopen(payload=payload))

    result = _convert(converter, VALID_HTML, destination)

    assert not result.success
    assert result.primary_issue.code == expected_code
    if validation:
        assert result.primary_issue.details["validation"] == validation
    assert not destination.exists()
    assert not list(tmp_path.glob(".ippi-edge-*"))
