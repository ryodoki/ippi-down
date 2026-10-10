# -*- coding: utf-8 -*-

"""検索フォーム値と詳細ページ正規化の回帰テスト。"""

from unittest.mock import MagicMock, Mock
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.app.events import EventType, ProgressEvent
from src.app.exceptions import NetworkError, RateLimitError
from src.core.parser.detail_page_parser import DetailPageParser
from src.core.parser.search_result_parser import SearchResultParser
from src.core.scraper import Scraper
from src.gui.event_handler import EventHandler
from src.gui.main_window import MainWindow
from src.models.config_model import SearchConditions
from src.models.download_diagnostics import DownloadIssueCode
from src.models.download_result import RunOutcome
from src.utils.notifier import Notifier


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            NetworkError("GETリクエスト失敗: HTTP 503"),
            DownloadIssueCode.HTTP_5XX,
        ),
        (
            RateLimitError("レート制限に達しました"),
            DownloadIssueCode.RATE_LIMIT,
        ),
    ],
)
def test_search_form_preserves_initial_request_failure_reason(
    error,
    expected_code,
):
    http_client = Mock()
    http_client.get.side_effect = error
    scraper = Scraper(http_client, Mock())

    soup = scraper.submit_search_form(
        "https://example.invalid/search",
        SearchConditions(koji_name="橋梁"),
    )

    assert soup is None
    assert scraper.last_request_failure is not None
    assert scraper.last_request_failure.reason_code == expected_code.value
    assert scraper.last_request_failure.retryable is True


def test_search_form_uses_site_option_values():
    logger = Mock()
    scraper = Scraper(Mock(), logger)
    soup = _soup(
        """
        <select name="drpKojiDistrict">
          <option value="-1">▽地方</option><option value="3">関東</option>
        </select>
        <select name="drpKojiPrefecture2">
          <option value="13">東京都</option>
        </select>
        <select name="drpKojiCity">
          <option value="13101">千代田区</option>
        </select>
        <select name="drpKojiKbn">
          <option value="01">一般土木工事</option>
        </select>
        <select name="drpKojiGyosyu">
          <option value="08">電気工事</option>
        </select>
        """
    )
    conditions = SearchConditions(
        place_search_type="list",
        place_chihou="関東",
        place_todofuken="東京都",
        place_shichouson="千代田区",
        koji_shubetsu="一般土木工事",
        koji_gyoushu="電気工事",
    )

    data = scraper._build_search_form_data(conditions, soup)

    assert data["KojiRadioGroup"] == "0"
    assert data["drpKojiDistrict"] == "3"
    assert data["drpKojiPrefecture2"] == "13"
    assert data["drpKojiCity"] == "13101"
    assert data["drpKojiKbn"] == "01"
    assert data["drpKojiGyosyu"] == "08"
    info_messages = [call.args[0] for call in logger.info.call_args_list]
    assert (
        "検索送信条件を解決しました: 工事種別 "
        "(表示名='一般土木工事', コード='01')"
    ) in info_messages
    assert (
        "検索送信条件を解決しました: 工事の業種 "
        "(表示名='電気工事', コード='08')"
    ) in info_messages


def test_search_form_rejects_unresolvable_display_name():
    scraper = Scraper(Mock(), Mock())
    soup = _soup(
        """
        <select name="drpKojiKbn">
          <option value="-1">▽工事種別</option>
          <option value="01">一般土木工事</option>
        </select>
        """
    )

    with pytest.raises(ValueError, match="変換できません"):
        scraper._build_search_form_data(
            SearchConditions(koji_shubetsu="サイトにない工事種別"),
            soup,
        )


def test_search_submission_stops_when_saved_agency_no_longer_exists():
    http_client = Mock()
    logger = Mock()
    scraper = Scraper(http_client, logger)
    scraper.fetch_page = Mock(
        return_value=_soup(
            """
            <select name="drpTopKikanInf">
              <option value="0">国の機関</option>
            </select>
            """
        )
    )

    result = scraper.submit_search_form(
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/"
        "Search.aspx?tab=4",
        SearchConditions(hachu_daibunrui="廃止された機関"),
    )

    assert result is None
    http_client.post.assert_not_called()
    assert "変換できません" in logger.error.call_args.args[0]


def test_search_result_parser_extracts_fields_used_for_validation():
    soup = _soup(
        """
        <table id="dgrSearchList">
          <tr>
            <th>発注機関</th><th>工事名</th>
            <th>入札契約方式</th><th>工事種別</th><th>公告日</th>
          </tr>
          <tr>
            <td>国土交通省 東北地方整備局</td>
            <td><a href="javascript:__doPostBack('dgrSearchList','$0')">
              ○○トンネル工事
            </a></td>
            <td>一般競争入札</td><td>一般土木工事</td><td>2026/07/30</td>
          </tr>
        </table>
        """
    )

    entries = SearchResultParser(Mock()).extract_project_entries(
        soup, "https://example.invalid/search", page_no=1
    )

    assert len(entries) == 1
    assert entries[0].koji_name == "○○トンネル工事"
    assert entries[0].metadata["hachu_kikan"] == (
        "国土交通省 東北地方整備局"
    )
    assert entries[0].metadata["koji_shubetsu"] == "一般土木工事"
    assert entries[0].event_target == "dgrSearchList"
    assert entries[0].event_argument == "$0"


def test_search_result_parser_splits_combined_type_and_industry_column():
    soup = _soup(
        """
        <table id="dgrSearchList">
          <tr><th>工事名</th><th>工事種別／工事の業種</th></tr>
          <tr>
            <td><a href="javascript:__doPostBack('dgrSearchList','$0')">
              舗装更新工事
            </a></td>
            <td>
              <span>アスファルト舗装工事</span><br>
              <span>土木一式工事</span>
            </td>
          </tr>
        </table>
        """
    )

    entries = SearchResultParser(Mock()).extract_project_entries(
        soup, "https://example.invalid/search", page_no=1
    )

    assert len(entries) == 1
    assert entries[0].metadata["koji_shubetsu"] == (
        "アスファルト舗装工事"
    )
    assert entries[0].metadata["koji_gyoushu"] == "土木一式工事"


def test_search_result_validation_rejects_observable_industry_mismatch():
    scraper = Scraper(Mock(), Mock())
    scraper._extract_files_from_detail_page_via_postback = Mock(
        return_value=[]
    )
    soup = _soup(
        """
        <table id="dgrSearchList">
          <tr><th>工事名</th><th>工事の業種</th></tr>
          <tr>
            <td><a href="javascript:__doPostBack('dgrSearchList','$0')">
              舗装更新工事
            </a></td>
            <td>電気工事</td>
          </tr>
        </table>
        """
    )

    files = scraper.extract_file_links_from_search_results(
        soup,
        "https://example.invalid/search",
        [".pdf"],
        SearchConditions(koji_gyoushu="土木一式工事"),
    )

    assert files == []
    assert scraper.last_search_diagnostics.validation_failed == 1
    assert "工事業種" in scraper.last_search_diagnostics.errors[0]
    scraper._extract_files_from_detail_page_via_postback.assert_not_called()


def test_search_result_does_not_claim_unobservable_industry_was_checked():
    logger = Mock()
    scraper = Scraper(Mock(), logger)
    scraper._extract_files_from_detail_page_via_postback = Mock(
        return_value=[]
    )
    scraper._get_next_page = Mock(return_value=None)
    soup = _soup(
        """
        <table id="dgrSearchList">
          <tr><th>工事名</th><th>工事種別</th></tr>
          <tr>
            <td><a href="javascript:__doPostBack('dgrSearchList','$0')">
              舗装更新工事
            </a></td>
            <td>アスファルト舗装工事</td>
          </tr>
        </table>
        """
    )

    scraper.extract_file_links_from_search_results(
        soup,
        "https://example.invalid/search",
        [".pdf"],
        SearchConditions(
            koji_shubetsu="アスファルト舗装工事",
            koji_gyoushu="土木一式工事",
        ),
    )

    assert scraper.last_search_diagnostics.validation_failed == 0
    assert any(
        "工事業種の照合は未実施" in call.args[0]
        for call in logger.info.call_args_list
    )


def test_official_no_match_fixture_is_a_valid_empty_search_response():
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "search_no_match_official.html"
    )
    logger = Mock()
    scraper = Scraper(Mock(), logger)

    files = scraper.extract_file_links_from_search_results(
        _soup(fixture.read_text(encoding="utf-8")),
        "https://www.i-ppi.jp/search",
        [".pdf"],
        SearchConditions(koji_name="該当しない工事"),
    )

    assert files == []
    assert scraper.last_search_total_koji_count == 0
    assert scraper.last_search_diagnostics.failure_count == 0
    assert scraper.last_search_summary.complete is True
    logger.warning.assert_not_called()


def test_search_result_validation_rejects_response_without_selected_agency():
    scraper = Scraper(Mock(), Mock())
    conditions = SearchConditions(
        hachu_daibunrui="国の機関",
        hachu_chubunrui="国土交通省",
        hachu_shoubunrui="東北地方整備局",
        koji_shubetsu="一般土木工事",
        koji_name="トンネル",
    )
    soup = _soup(
        """
        <table id="dgrSearchList">
          <tr><th>発注機関</th><th>工事名</th><th>工事種別</th></tr>
          <tr>
            <td>国土交通省 関東地方整備局</td>
            <td><a href="javascript:__doPostBack('dgrSearchList','$0')">
              ○○トンネル工事
            </a></td>
            <td>一般土木工事</td>
          </tr>
        </table>
        """
    )

    files = scraper.extract_file_links_from_search_results(
        soup,
        "https://example.invalid/search",
        [".pdf"],
        conditions,
    )

    assert files == []
    assert scraper.last_search_total_koji_count == 0
    assert scraper.last_search_diagnostics.validation_failed == 1
    assert "発注機関" in scraper.last_search_diagnostics.errors[0]


def test_search_progress_is_reported_and_cancel_stops_current_page():
    scraper = Scraper(Mock(), Mock())
    soup = _soup(
        """
        <table id="dgrSearchList">
          <tr><th>発注機関</th><th>工事名</th><th>工事種別</th></tr>
          <tr>
            <td>東北地方整備局</td>
            <td><a href="javascript:__doPostBack('dgrSearchList','$0')">
              Aトンネル工事
            </a></td>
            <td>一般土木工事</td>
          </tr>
          <tr>
            <td>東北地方整備局</td>
            <td><a href="javascript:__doPostBack('dgrSearchList','$1')">
              Bトンネル工事
            </a></td>
            <td>一般土木工事</td>
          </tr>
        </table>
        """
    )
    progress = []
    cancelled = False

    def record_progress(event):
        nonlocal cancelled
        progress.append(event)
        if event.phase == "detail" and event.projects_scanned == 1:
            cancelled = True

    scraper._extract_files_from_detail_page_via_postback = Mock(
        return_value=[]
    )

    scraper.extract_file_links_from_search_results(
        soup,
        "https://example.invalid/search",
        [".pdf"],
        SearchConditions(
            hachu_shoubunrui="東北地方整備局",
            koji_shubetsu="一般土木工事",
            koji_name="トンネル",
        ),
        cancel_check=lambda: cancelled,
        progress_callback=record_progress,
    )

    assert [event.phase for event in progress] == ["page", "detail"]
    assert progress[-1].projects_scanned == 1
    assert (
        scraper._extract_files_from_detail_page_via_postback.call_count == 1
    )


def test_placeholder_options_are_excluded_from_gui_values():
    scraper = Scraper(Mock(), Mock())
    soup = _soup(
        """
        <select name="drpTopKikanInf">
          <option value="-1">▽大分類</option>
          <option value="">選択してください</option>
          <option value="1">国の機関</option>
        </select>
        """
    )

    assert scraper._parse_html_options(
        soup, "drpTopKikanInf"
    ) == [("1", "国の機関")]


def test_text_place_search_uses_radio_value_one():
    scraper = Scraper(Mock(), Mock())
    conditions = SearchConditions(
        place_search_type="text",
        place_text="千代田区",
    )

    data = scraper._build_search_form_data(conditions, _soup("<html></html>"))

    assert data["KojiRadioGroup"] == "1"
    assert data["tbxKojiPlace"] == "千代田区"
    assert "drpKojiDistrict" not in data


def test_prefecture_options_are_read_from_site_hidden_mapping():
    scraper = Scraper(Mock(), Mock())
    soup = _soup(
        """
        <input name="txtKojiPrefectureInf_h" type="hidden"
          value="3,東京都,13:3,神奈川県,14:6,大阪府,27" />
        """
    )

    assert scraper._get_place_prefecture_pairs(soup, "3") == [
        ("13", "東京都"),
        ("14", "神奈川県"),
    ]


def test_prefecture_postback_uses_site_codes():
    scraper = Scraper(Mock(), Mock())
    initial = _soup(
        """
        <select name="drpKojiDistrict"><option value="3">関東</option></select>
        <input name="txtKojiPrefectureInf_h" type="hidden"
          value="3,東京都,13:3,神奈川県,14" />
        """
    )
    updated = _soup(
        '<select name="drpKojiCity"><option value="13101">千代田区</option></select>'
    )
    scraper._do_postback = Mock(return_value=updated)

    result_soup, district, prefecture = scraper._post_place_prefecture(
        "https://example.invalid/Search.aspx",
        initial,
        "関東",
        "東京都",
    )

    assert result_soup is updated
    assert district == "3"
    assert prefecture == "13"
    additional = scraper._do_postback.call_args.args[3]
    assert additional["KojiRadioGroup"] == "0"
    assert additional["drpKojiDistrict"] == "3"
    assert additional["drpKojiPrefecture2"] == "13"
    assert additional["txtKojiPrefecture2SelIndex_h"] == "1"


def test_hachu_child_options_post_back_changed_parent():
    initial = _soup(
        """
        <input type="hidden" name="__VIEWSTATE" value="x" />
        <select name="drpTopKikanInf">
          <option value="1">国の機関</option>
        </select>
        """
    )
    response = Mock()
    response.status_code = 200
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.text = (
        '<select name="drpLargeKikanInf2">'
        '<option value="10">国土交通省</option></select>'
    )
    response.content = response.text.encode("utf-8")
    http_client = Mock()
    http_client.post.return_value = response
    scraper = Scraper(http_client, Mock())
    scraper.fetch_page = Mock(return_value=initial)

    options = scraper.get_hachu_chubunrui_options(
        "https://example.invalid/Search.aspx",
        "国の機関",
    )

    assert options == ["国土交通省"]
    post_data = http_client.post.call_args.kwargs["data"]
    assert post_data["__EVENTTARGET"] == "drpTopKikanInf"
    assert post_data["drpTopKikanInf"] == "1"


def test_event_handler_runs_queued_ui_call_on_poll():
    root = Mock()
    callback = Mock()
    handler = EventHandler(root, Mock())

    handler.call_soon(callback, "message", level="info")
    handler._poll_events()

    callback.assert_called_once_with("message", level="info")
    root.after.assert_called_once()


def test_event_handler_limits_work_per_poll():
    root = Mock()
    callback = Mock()
    handler = EventHandler(root, Mock())
    for index in range(101):
        handler.call_soon(callback, index)

    handler._poll_events()

    assert callback.call_count == 100
    assert handler.event_queue.qsize() == 1
    root.after.assert_called_once()


@pytest.mark.parametrize(
    ("event_type", "raw_outcome", "expected"),
    [
        (EventType.COMPLETE, "SUCCESS", RunOutcome.SUCCESS),
        (EventType.COMPLETE, "PARTIAL", RunOutcome.PARTIAL),
        (EventType.FAIL, "FAILED", RunOutcome.FAILED),
        (EventType.COMPLETE, "CANCELLED", RunOutcome.CANCELLED),
        (EventType.COMPLETE, "NO_MATCH", RunOutcome.NO_MATCH),
    ],
)
def test_event_handler_preserves_terminal_outcome(
    event_type, raw_outcome, expected
):
    window = Mock()
    handler = EventHandler(Mock(), window)
    event = ProgressEvent(
        type=event_type,
        message="終了",
        current=1,
        total=2,
        metadata={"outcome": raw_outcome, "type": "warning"},
    )

    handler._handle_event(event)

    window.set_run_outcome.assert_called_once_with(expected, 1, 2)


def test_event_handler_routes_search_progress_to_search_display():
    window = Mock()
    handler = EventHandler(Mock(), window)
    metadata = {
        "phase": "search",
        "search_phase": "detail",
        "page": 1,
        "row": 3,
        "rows_on_page": 13,
        "projects_scanned": 3,
        "files_discovered": 8,
    }

    handler._handle_event(
        ProgressEvent(
            type=EventType.PROGRESS,
            message="検索中",
            metadata=metadata,
        )
    )

    window.update_search_progress.assert_called_once_with(metadata)
    window.update_progress.assert_not_called()


def test_stale_place_response_is_not_applied():
    window = MainWindow.__new__(MainWindow)
    window.place_chihou_var = Mock()
    window.place_chihou_var.get.return_value = "近畿"
    window.place_todofuken_var = Mock()
    window.place_todofuken_combobox = MagicMock()
    window._finish_option_load = Mock()

    window._update_place_todofuken_options("関東", ["東京都"])

    window.place_todofuken_combobox.__setitem__.assert_not_called()
    window.place_todofuken_var.set.assert_not_called()
    window._finish_option_load.assert_called_once()


def test_dynamic_search_validation_rejects_stale_agency_selection():
    window = MainWindow.__new__(MainWindow)

    def variable(value):
        result = Mock()
        result.get.return_value = value
        return result

    def combo(values):
        result = Mock()
        result.cget.return_value = values
        return result

    window.hachu_daibunrui_var = variable("国の機関")
    window.hachu_daibunrui_combo = combo(("", "国の機関"))
    window.hachu_chubunrui_var = variable("国土交通省")
    window.hachu_chubunrui_combo = combo(("", "国土交通省"))
    window.hachu_shoubunrui_var = variable("東北地方整備局")
    window.hachu_shoubunrui_combo = combo(("", "関東地方整備局"))
    window.hachu_saibunrui_var = variable("")
    window.hachu_saibunrui_combo = combo(())
    window.koji_shubetsu_var = variable("一般土木工事")
    window.koji_shubetsu_combobox = combo(("", "一般土木工事"))
    window.koji_gyoushu_var = variable("")
    window.koji_gyoushu_combobox = combo(())
    window.place_search_type_var = variable("list")
    window.place_chihou_var = variable("")
    window.place_chihou_combobox = combo(())
    window.place_todofuken_var = variable("")
    window.place_todofuken_combobox = combo(())
    window.place_shichouson_var = variable("")
    window.place_shichouson_combobox = combo(())
    window._agency_invalid_fields = {"hachu_shoubunrui"}
    window._dynamic_invalid_fields = set()

    error = window._validate_dynamic_search_selections()

    assert "東北地方整備局" in error
    assert "選択し直してください" in error


def test_notification_fallback_never_creates_tk():
    logger = Mock()
    Notifier(logger)._notify_windows_fallback("ippi-down", "完了")

    logger.info.assert_called_once_with("通知（ログ代替）: ippi-down - 完了")


class _Response:
    encoding = "utf-8"
    apparent_encoding = "utf-8"
    status_code = 200
    url = "https://example.invalid/detail"

    def __init__(self, html: str):
        self.content = html.encode("utf-8")


def test_detail_page_adds_full_metadata_without_debug_file(tmp_path, monkeypatch):
    detail_html = """
    <html><head><title>案件詳細</title></head><body>
      <table><tr><td>発注機関</td><td>テスト発注機関</td></tr>
      <tr><td>公告日</td><td>2026-07-30</td></tr></table>
      <div>入札公告等</div>
      <table id="dgrKokoku">
        <tr><th>文書</th><th>状態</th></tr>
        <tr><td>入札説明書</td><td><a href="/docs/info.pdf">公開中</a></td></tr>
      </table>
    </body></html>
    """
    http_client = Mock()
    http_client.post.return_value = _Response(detail_html)
    scraper = Scraper(http_client, Mock())
    current_soup = _soup(
        '<form action="/detail"><input type="hidden" name="__VIEWSTATE" value="x"></form>'
    )
    monkeypatch.chdir(tmp_path)

    files = scraper._extract_files_from_detail_page_via_postback(
        "https://example.invalid/search",
        "javascript:__doPostBack('dgrSearchList','$0')",
        [".pdf"],
        current_soup,
        koji_name="テスト工事",
    )

    assert len(files) == 1
    assert files[0].metadata["koji_name"] == "テスト工事"
    assert files[0].metadata["hachu_kikan"] == "テスト発注機関"
    assert files[0].metadata["date"] == "2026-07-30"
    assert not (tmp_path / "test_detail_page.html").exists()


def test_detail_page_failure_is_recorded_for_service():
    http_client = Mock()
    http_client.post.side_effect = RuntimeError("detail unavailable")
    scraper = Scraper(http_client, Mock())
    current_soup = _soup(
        '<form action="/detail">'
        '<input type="hidden" name="__VIEWSTATE" value="x">'
        "</form>"
    )

    files = scraper._extract_files_from_detail_page_via_postback(
        "https://example.invalid/search",
        "javascript:__doPostBack('dgrSearchList','$0')",
        [".pdf"],
        current_soup,
        koji_name="テスト工事",
    )

    assert files == []
    assert scraper.last_search_diagnostics.detail_attempted == 1
    assert scraper.last_search_diagnostics.detail_failed == 1
    assert "detail unavailable" in scraper.last_search_diagnostics.errors[0]


def test_next_page_failure_is_not_treated_as_last_page():
    http_client = Mock()
    http_client.post.side_effect = RuntimeError("next page unavailable")
    scraper = Scraper(http_client, Mock())
    scraper._last_search_result_url = "https://example.invalid/search"
    current_soup = _soup(
        """
        <form action="/search">
          <input type="hidden" name="__VIEWSTATE" value="x">
          <input type="submit" name="next" value="次ページ">
        </form>
        """
    )

    next_page = scraper._get_next_page(
        current_soup, "https://example.invalid/search"
    )

    assert next_page is None
    assert scraper.last_search_diagnostics.pagination_failed == 1
    assert "next page unavailable" in scraper.last_search_diagnostics.errors[0]


def test_saved_detail_fixture_extracts_extensionless_download_links():
    fixture = Path(__file__).parent / "fixtures" / "test_detail_page.html"
    soup = _soup(fixture.read_text(encoding="utf-8"))
    scraper = Scraper(Mock(), Mock())

    files = scraper._extract_files_from_tables(
        soup,
        "https://www.i-ppi.jp/detail",
        [".pdf", ".xlsx", ".docx"],
    )
    metadata = scraper.extract_metadata(soup)

    assert files
    assert all(file_info.url.startswith("https://") for file_info in files)
    assert all(file_info.file_type == ".pdf" for file_info in files)
    assert metadata["hachu_kikan"]
    assert metadata["koji_name"]
    assert metadata["date"]


def test_saved_detail_fixture_uses_modular_detail_parser():
    fixture = Path(__file__).parent / "fixtures" / "test_detail_page.html"
    soup = _soup(fixture.read_text(encoding="utf-8"))

    candidates = DetailPageParser(Mock()).extract_file_candidates(
        soup,
        "https://www.i-ppi.jp/detail",
        [".pdf", ".xlsx", ".docx"],
        koji_name="fixture工事",
    )

    assert candidates
    assert all(candidate.url.startswith("https://") for candidate in candidates)
    assert all(candidate.file_type == ".pdf" for candidate in candidates)
    assert all(candidate.metadata["koji_name"] == "fixture工事" for candidate in candidates)


def test_extensionless_download_uses_explicit_document_type():
    soup = _soup(
        """
        <table id="dgrKokoku">
          <tr><th>文書</th><th>状態</th></tr>
          <tr>
            <td>数量表.xlsx</td>
            <td><a href="/Download?id=1">公開中</a></td>
          </tr>
          <tr>
            <td>説明資料（Word）</td>
            <td><a href="/Download?id=2">公開中</a></td>
          </tr>
        </table>
        """
    )
    scraper = Scraper(Mock(), Mock())

    files = scraper._extract_files_from_tables(
        soup,
        "https://example.invalid/detail",
        [".pdf", ".xlsx", ".docx"],
    )

    assert [file_info.file_type for file_info in files] == [
        ".xlsx",
        ".docx",
    ]


def test_extensionless_non_pdf_is_not_misclassified_when_filtered_out():
    assert Scraper._infer_download_file_type(
        "https://example.invalid/Download?id=1",
        "数量表.xlsx",
        [".pdf"],
    ) == ""
