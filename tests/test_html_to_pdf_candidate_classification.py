# -*- coding: utf-8 -*-

"""入札調書HTML→PDF候補分類の回帰テスト。"""

from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup

from src.core.extractor.metadata_extractor import MetadataExtractor
from src.core.parser.detail_page_parser import DetailPageParser
from src.core.parser.document_classifier import (
    classify_document_candidate,
    is_html_bid_sheet_candidate,
)
from src.core.parser.models import FileCandidate
from src.core.scraper import Scraper
from src.models.file_info import FileInfo


PUBLISH_URL = (
    "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/"
    "KokaiBunshoServlet?AnkenKanriNo=1&BunshoKanriId=40"
)


def _fixture_soup() -> BeautifulSoup:
    fixture = Path(__file__).parent / "fixtures" / "test_detail_page.html"
    return BeautifulSoup(fixture.read_text(encoding="utf-8"), "lxml")


def test_model_flags_are_backward_compatible_and_propagated():
    file_info = FileInfo("https://example.test/a.pdf", "a.pdf", ".pdf")
    candidate = FileCandidate(
        PUBLISH_URL,
        "入札調書.pdf",
        ".pdf",
        allow_html_to_pdf=True,
    )

    converted = MetadataExtractor(Mock()).to_file_info(candidate)

    assert file_info.allow_html_to_pdf is False
    assert converted.allow_html_to_pdf is True


def test_bid_sheet_conversion_requires_trusted_https_servlet_and_pdf():
    eligible = classify_document_candidate(
        PUBLISH_URL, "入札調書（総合評価落札方式）", [".pdf"]
    )

    assert eligible.file_type == ".pdf"
    assert eligible.allow_html_to_pdf is True
    assert classify_document_candidate(
        PUBLISH_URL, "入札調書.pdf", [".pdf"]
    ).allow_html_to_pdf
    assert not is_html_bid_sheet_candidate(
        PUBLISH_URL.replace("https://", "http://"), "入札調書"
    )
    assert not is_html_bid_sheet_candidate(
        PUBLISH_URL.replace("e-bisc.go.jp", "example.test"), "入札調書"
    )
    assert not is_html_bid_sheet_candidate(PUBLISH_URL, "入札公告")
    assert (
        classify_document_candidate(
            PUBLISH_URL, "入札調書", [".xlsx"]
        ).file_type
        == ""
    )


def test_direct_pdf_candidate_remains_direct():
    result = classify_document_candidate(
        "https://files.example.test/report.pdf",
        "入札調書",
        [".pdf"],
    )

    assert result.file_type == ".pdf"
    assert result.allow_html_to_pdf is False


def test_modular_parser_marks_only_bid_sheets_for_conversion():
    candidates = DetailPageParser(Mock()).extract_file_candidates(
        _fixture_soup(),
        "https://www.i-ppi.jp/detail",
        [".pdf"],
        "テスト工事",
    )

    by_name = {candidate.document_name: candidate for candidate in candidates}
    assert by_name["入札公告"].allow_html_to_pdf is False
    assert by_name["入札調書"].allow_html_to_pdf is True
    assert (
        by_name["入札調書（総合評価落札方式）"].allow_html_to_pdf
        is True
    )
    assert all(candidate.file_type == ".pdf" for candidate in candidates)


def test_legacy_parser_keeps_document_name_and_conversion_flag():
    files = Scraper(Mock(), Mock())._extract_files_from_tables(
        _fixture_soup(),
        "https://www.i-ppi.jp/detail",
        [".pdf"],
    )

    by_name = {
        file_info.metadata["document_name"]: file_info
        for file_info in files
    }
    bid_sheet = by_name["入札調書"]
    assert bid_sheet.metadata["title"] == "入札調書"
    assert bid_sheet.allow_html_to_pdf is True
    assert bid_sheet.filename == "入札調書.pdf"
    assert by_name["入札公告"].allow_html_to_pdf is False
