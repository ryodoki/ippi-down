# -*- coding: utf-8 -*-

"""詳細ページの公開文書一覧解析テスト。"""

from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup

from src.core.parser.detail_page_parser import DetailPageParser
from src.core.parser.models import DocumentPublicationStatus


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def test_saved_fixture_extracts_all_document_row_fields():
    fixture = Path(__file__).parent / "fixtures" / "test_detail_page.html"
    parser = DetailPageParser(Mock())

    result = parser.extract_detail_result(
        _soup(fixture.read_text(encoding="utf-8")),
        "https://www.i-ppi.jp/detail",
        [".pdf"],
        koji_name="摩当山トンネル換気設備製作据付工事",
    )

    assert len(result.document_rows) == 3
    assert len(result.candidates) == 3
    announcement = result.document_rows[0]
    assert announcement.document_name == "入札公告"
    assert announcement.status is DocumentPublicationStatus.PUBLIC
    assert announcement.document_updated_at == "2025-10-03T07:00:00+09:00"
    assert announcement.listing_end_at == "2027-03-31T23:00:00+09:00"
    assert announcement.section == "入札公告等"
    assert announcement.document_id == "20"
    assert announcement.href and "BunshoKanriId=20" in announcement.href

    candidate = result.candidates[0]
    assert candidate.document_info is announcement
    assert candidate.metadata["title"] == "入札公告"
    assert candidate.metadata["document_title"] == "入札公告"
    assert candidate.metadata["document_updated_at_filename"] == (
        "20251003_0700"
    )
    assert candidate.metadata["document_expires_at"] == (
        "2027-03-31T23:00:00+09:00"
    )
    assert candidate.metadata["publication_status"] == "PUBLIC"


def test_keeps_non_downloadable_rows_and_public_link_missing():
    soup = _soup(
        """
        <table id="dgrKokoku">
          <tr><td>文書名称</td><td>公開状況</td>
              <td>最終更新日</td><td>掲載終了日</td></tr>
          <tr><td>公開リンク欠落</td><td>公開中</td><td></td><td></td></tr>
          <tr><td>古い公告</td><td>公開終了</td><td></td><td></td></tr>
          <tr><td>予告資料</td><td>公開予定</td><td></td><td></td></tr>
          <tr><td>非公開資料</td><td>非公開</td><td></td><td></td></tr>
          <tr><td>判定不能</td><td>確認中</td><td></td><td></td></tr>
        </table>
        """
    )

    result = DetailPageParser(Mock()).extract_detail_result(
        soup,
        "https://example.invalid/detail",
        [".pdf"],
    )

    assert [row.status for row in result.document_rows] == [
        DocumentPublicationStatus.PUBLIC,
        DocumentPublicationStatus.EXPIRED,
        DocumentPublicationStatus.SCHEDULED,
        DocumentPublicationStatus.NON_PUBLIC,
        DocumentPublicationStatus.UNKNOWN,
    ]
    assert result.document_rows[0].href is None
    assert result.candidates == []


def test_header_names_drive_reordered_column_mapping():
    soup = _soup(
        """
        <table id="dgrKeika">
          <tr><th>公開状況</th><th>掲載終了日</th>
              <th>文書名称</th><th>最終更新日</th></tr>
          <tr><td><a href="/report.pdf?BunshoKanriId=41">公開中</a></td>
              <td>2027/03/31 23:00</td><td>入札調書</td>
              <td>2026/02/04 14:22</td></tr>
        </table>
        """
    )

    result = DetailPageParser(Mock()).extract_detail_result(
        soup,
        "https://example.invalid/detail",
        [".pdf"],
    )

    row = result.document_rows[0]
    assert row.document_name == "入札調書"
    assert row.document_updated_at == "2026-02-04T14:22:00+09:00"
    assert row.listing_end_at == "2027-03-31T23:00:00+09:00"
    assert row.document_id == "41"
    assert result.candidates[0].filename == "入札調書.pdf"


def test_legacy_list_api_and_table_without_headers_remain_supported():
    soup = _soup(
        """
        <div>入札公告等</div>
        <table>
          <tr><td>文書1</td><td><a href="/file1.pdf">公開中</a></td></tr>
        </table>
        """
    )

    candidates = DetailPageParser(Mock()).extract_file_candidates(
        soup,
        "https://example.invalid/detail",
        [".pdf"],
        "テスト工事",
    )

    assert len(candidates) == 1
    assert candidates[0].url == "https://example.invalid/file1.pdf"
    assert candidates[0].metadata["document_name"] == "文書1"


def test_unparseable_datetime_preserves_source_text_without_guessing():
    soup = _soup(
        """
        <table id="dgrKokoku">
          <tr><td>文書名称</td><td>公開状況</td>
              <td>最終更新日</td><td>掲載終了日</td></tr>
          <tr><td>入札公告</td><td><a href="/file.pdf">公開中</a></td>
              <td>日時不明</td><td>-</td></tr>
        </table>
        """
    )

    row = DetailPageParser(Mock()).extract_document_rows(
        soup, "https://example.invalid/detail"
    )[0]

    assert row.document_updated_at == ""
    assert row.document_updated_at_text == "日時不明"
    assert row.listing_end_at == ""
    assert row.listing_end_at_text == "-"
