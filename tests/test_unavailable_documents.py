# -*- coding: utf-8 -*-

"""公開終了文書の検出・0件メッセージのテスト（原因調査の回帰防止）"""

import sys
from pathlib import Path

from bs4 import BeautifulSoup

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infrastructure.ppi.detail import count_unavailable_documents
from src.app.extract_result import ExtractResult
from src.app.service import ApplicationService
from src.utils.logger import Logger, LoggingConfig


def _logger():
    return Logger(LoggingConfig(level="WARNING"))


class TestCountUnavailableDocuments:
    def test_counts_rows_without_href(self):
        """公開終了（href無し）の文書行を数える"""
        html = """
        <table id="dgrKeika">
          <tr class="dgrtitle"><td>文書名称</td><td>公開状況</td></tr>
          <tr><td>工事設計書</td><td><a target="_blank">公開終了</a></td></tr>
          <tr><td>随意契約結果及び契約の内容</td><td><a target="_blank">公開終了</a></td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert count_unavailable_documents(soup, _logger()) == 2

    def test_does_not_count_rows_with_href(self):
        """ダウンロード可能（href有り）な行は数えない"""
        html = """
        <table id="dgrKokoku">
          <tr class="dgrtitle"><td>文書名称</td><td>公開状況</td></tr>
          <tr><td>入札公告</td><td><a href="/files/a.pdf">公開中</a></td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert count_unavailable_documents(soup, _logger()) == 0

    def test_no_table_returns_zero(self):
        soup = BeautifulSoup("<html><body>なし</body></html>", "html.parser")
        assert count_unavailable_documents(soup, _logger()) == 0


class TestNoFilesMessage:
    def _service(self):
        return ApplicationService(_logger())

    def test_connection_failure_message(self):
        er = ExtractResult(search_failed_urls=["https://example.com"])
        msg = self._service()._build_no_files_message(er)
        assert "接続" in msg or "検索の実行に失敗" in msg

    def test_fetch_failure_message(self):
        er = ExtractResult(fetch_failed_urls=["https://example.com"])
        msg = self._service()._build_no_files_message(er)
        assert "取得に失敗" in msg

    def test_hit_but_all_expired_message(self):
        """案件ヒット＋全文書公開終了のとき、件数と理由が伝わること"""
        er = ExtractResult(total_koji_count=1, unavailable_document_count=2)
        msg = self._service()._build_no_files_message(er)
        assert "1件" in msg
        assert "公開終了" in msg

    def test_hit_but_no_attachments_message(self):
        er = ExtractResult(total_koji_count=3, unavailable_document_count=0)
        msg = self._service()._build_no_files_message(er)
        assert "3件" in msg
        assert "添付" in msg

    def test_no_match_message(self):
        er = ExtractResult(total_koji_count=0)
        msg = self._service()._build_no_files_message(er)
        assert "一致する案件が見つかりません" in msg
