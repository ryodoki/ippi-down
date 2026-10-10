# -*- coding: utf-8 -*-

"""ApplicationServiceの動作確認テスト"""

import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_application_service_initialization():
    """ApplicationServiceの初期化確認"""
    from src.app.service import ApplicationService
    from src.utils.logger import Logger
    from src.models.config_model import LoggingConfig

    config = LoggingConfig(
        level="INFO",
        file="logs/test.log",
        max_bytes=10485760,
        backup_count=5
    )
    logger = Logger(config)
    
    service = ApplicationService(logger)
    assert service is not None
    assert service.logger is logger


def test_run_result():
    """RunResultの動作確認"""
    from src.app.run_result import RunResult
    from src.models.download_result import DownloadResult

    # 成功ケース
    result = DownloadResult(total=10, success=8, failed=1, skipped=1)
    run_result = RunResult(
        success=True,
        result=result,
        message="ダウンロード完了"
    )
    
    assert run_result.success is True
    assert run_result.result is not None
    assert run_result.result.total == 10
    assert run_result.message == "ダウンロード完了"
    assert run_result.error is None

    # 失敗ケース
    run_result_fail = RunResult(
        success=False,
        error="エラーが発生しました",
        message="ダウンロードに失敗しました"
    )
    
    assert run_result_fail.success is False
    assert run_result_fail.error == "エラーが発生しました"
    assert run_result_fail.result is None


@patch('src.app.service.HTTPClient')
@patch('src.app.service.Scraper')
@patch('src.app.service.Filter')
@patch('src.app.service.Naming')
@patch('src.app.service.Downloader')
def test_application_service_run_without_files(mock_downloader, mock_naming, mock_filter, mock_scraper, mock_http_client):
    """ApplicationService.run() - ページ取得自体が失敗した場合"""
    from src.app.headless import is_transient_failure
    from src.app.service import ApplicationService
    from src.core.scraper import RequestFailureDiagnostic
    from src.models.config_model import AppConfig, SearchConditions, DownloadConditions, SavePaths, ScheduleConfig, LoggingConfig
    from src.models.download_diagnostics import DownloadIssueCode
    from src.utils.logger import Logger

    # モックの設定
    mock_scraper_instance = MagicMock()
    mock_scraper_instance.fetch_page.return_value = None
    mock_scraper_instance.last_request_failure = RequestFailureDiagnostic(
        DownloadIssueCode.NETWORK_TIMEOUT.value,
        "接続がタイムアウトしました",
        retryable=True,
    )
    mock_scraper.return_value = mock_scraper_instance

    mock_filter_instance = MagicMock()
    mock_filter_instance.filter_files.return_value = []
    mock_filter.return_value = mock_filter_instance

    # 設定の作成
    config = AppConfig(
        target_urls=["https://example.com"],
        download_conditions=DownloadConditions(),
        search_conditions=SearchConditions(),
        save_paths=SavePaths(local="./test_downloads"),
        schedule=ScheduleConfig(),
        logging=LoggingConfig(),
    )

    logger = Logger()
    service = ApplicationService(logger)

    # 実行
    run_result = service.run(config)

    # 検証
    assert run_result.success is False
    assert run_result.outcome.value == "FAILED"
    assert "取得または解析に失敗" in run_result.message
    assert "[NETWORK_TIMEOUT]" in run_result.error
    assert is_transient_failure(run_result)


@patch('src.app.service.HTTPClient')
@patch('src.app.service.Scraper')
@patch('src.app.service.Filter')
@patch('src.app.service.Naming')
@patch('src.app.service.Downloader')
def test_search_page_rate_limit_is_propagated_to_headless_retry(
    mock_downloader,
    mock_naming,
    mock_filter,
    mock_scraper,
    mock_http_client,
    tmp_path,
):
    from src.app.headless import is_transient_failure
    from src.app.service import ApplicationService
    from src.core.scraper import RequestFailureDiagnostic
    from src.models.config_model import AppConfig, SavePaths, SearchConditions
    from src.models.download_diagnostics import DownloadIssueCode
    from src.utils.logger import Logger

    scraper = MagicMock()
    scraper.submit_search_form.return_value = None
    scraper.last_request_failure = RequestFailureDiagnostic(
        DownloadIssueCode.RATE_LIMIT.value,
        "レート制限に達しました",
        retryable=True,
    )
    mock_scraper.return_value = scraper
    config = AppConfig(
        target_urls=["https://example.invalid/search"],
        search_conditions=SearchConditions(koji_name="橋梁"),
        save_paths=SavePaths(local=str(tmp_path)),
    )

    run_result = ApplicationService(Logger()).run(config)

    assert run_result.outcome.value == "FAILED"
    assert "[RATE_LIMIT]" in run_result.error
    assert is_transient_failure(run_result)


@patch('src.app.service.HTTPClient')
@patch('src.app.service.Scraper')
@patch('src.app.service.Filter')
@patch('src.app.service.Naming')
@patch('src.app.service.Downloader')
def test_application_service_distinguishes_real_no_match(
    mock_downloader,
    mock_naming,
    mock_filter,
    mock_scraper,
    mock_http_client,
):
    """ページ取得成功後の0件だけをNO_MATCHとして扱う。"""
    from src.app.run_result import RunOutcome
    from src.app.service import ApplicationService
    from src.models.config_model import AppConfig, SavePaths
    from src.utils.logger import Logger

    scraper = MagicMock()
    scraper.fetch_page.return_value = MagicMock()
    scraper.extract_file_links.return_value = []
    mock_scraper.return_value = scraper
    config = AppConfig(
        target_urls=["https://example.com"],
        save_paths=SavePaths(local="./test_downloads"),
    )

    run_result = ApplicationService(Logger()).run(config)

    assert run_result.outcome == RunOutcome.NO_MATCH
    assert "見つかりませんでした" in run_result.message


@patch('src.app.service.HTTPClient')
@patch('src.app.service.Scraper')
@patch('src.app.service.Filter')
@patch('src.app.service.Naming')
@patch('src.app.service.Downloader')
def test_official_no_match_fixture_does_not_start_downloader(
    mock_downloader,
    mock_naming,
    mock_filter,
    mock_scraper,
    mock_http_client,
    tmp_path,
):
    """公式0件メッセージは正常終了しDownloaderへ進まない。"""
    from bs4 import BeautifulSoup

    from src.app.run_result import RunOutcome
    from src.app.service import ApplicationService
    from src.core.scraper import Scraper as RealScraper
    from src.models.config_model import AppConfig, SavePaths, SearchConditions
    from src.utils.logger import Logger

    del mock_naming, mock_filter, mock_http_client
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "search_no_match_official.html"
    )
    no_match_soup = BeautifulSoup(
        fixture.read_text(encoding="utf-8"), "html.parser"
    )
    scraper = RealScraper(Mock(), Mock())
    scraper.submit_search_form = Mock(return_value=no_match_soup)
    mock_scraper.return_value = scraper
    config = AppConfig(
        target_urls=["https://www.i-ppi.jp/search"],
        search_conditions=SearchConditions(koji_name="該当しない工事"),
        save_paths=SavePaths(local=str(tmp_path)),
    )

    run_result = ApplicationService(Logger()).run(config)

    assert run_result.outcome == RunOutcome.NO_MATCH
    mock_downloader.return_value.download_files.assert_not_called()


@patch('src.app.service.HTTPClient')
@patch('src.app.service.Scraper')
@patch('src.app.service.Filter')
@patch('src.app.service.Naming')
@patch('src.app.service.Downloader')
def test_application_service_marks_source_url_failure_as_partial(
    mock_downloader,
    mock_naming,
    mock_filter,
    mock_scraper,
    mock_http_client,
):
    """複数URLの一部取得失敗を成功へ丸めない。"""
    from src.app.run_result import RunOutcome
    from src.app.service import ApplicationService
    from src.models.config_model import AppConfig, SavePaths
    from src.models.download_result import DownloadResult
    from src.models.file_info import FileInfo
    from src.utils.logger import Logger

    file_info = FileInfo(
        "https://example.com/file.pdf",
        "file.pdf",
        ".pdf",
    )
    scraper = MagicMock()
    scraper.fetch_page.side_effect = [None, MagicMock()]
    scraper.extract_file_links.return_value = [file_info]
    mock_scraper.return_value = scraper
    filter_instance = MagicMock()
    filter_instance.filter_files.return_value = [file_info]
    mock_filter.return_value = filter_instance
    downloader = MagicMock()
    downloader.download_files.return_value = DownloadResult(
        total=1, success=1
    )
    mock_downloader.return_value = downloader
    config = AppConfig(
        target_urls=["https://failed.example", "https://ok.example"],
        save_paths=SavePaths(local="./test_downloads"),
    )

    run_result = ApplicationService(Logger()).run(config)

    assert run_result.success
    assert run_result.outcome == RunOutcome.PARTIAL
    assert "検索ページ取得失敗=1/2 URL" in run_result.message


@patch('src.app.service.HTTPClient')
@patch('src.app.service.Scraper')
@patch('src.app.service.Filter')
@patch('src.app.service.Naming')
@patch('src.app.service.Downloader')
def test_application_service_run_with_progress_callback(mock_downloader, mock_naming, mock_filter, mock_scraper, mock_http_client):
    """ApplicationService.run() - 進捗コールバックの動作確認"""
    from src.app.service import ApplicationService
    from src.models.config_model import AppConfig, SearchConditions, DownloadConditions, SavePaths, ScheduleConfig, LoggingConfig
    from src.models.file_info import FileInfo
    from src.models.download_result import DownloadResult
    from src.utils.logger import Logger
    from src.app.events import ProgressEvent, EventType

    # モックの設定
    mock_scraper_instance = MagicMock()
    mock_soup = MagicMock()
    mock_scraper_instance.fetch_page.return_value = mock_soup
    mock_scraper_instance.extract_file_links.return_value = [
        FileInfo(url="https://example.com/file1.pdf", filename="file1.pdf", file_type=".pdf")
    ]
    mock_scraper.return_value = mock_scraper_instance

    mock_filter_instance = MagicMock()
    mock_filter_instance.filter_files.return_value = [
        FileInfo(url="https://example.com/file1.pdf", filename="file1.pdf", file_type=".pdf")
    ]
    mock_filter.return_value = mock_filter_instance

    mock_downloader_instance = MagicMock()
    mock_downloader_instance.download_files.return_value = DownloadResult(
        total=1, success=1, failed=0, skipped=0
    )
    mock_downloader.return_value = mock_downloader_instance

    # 設定の作成（検索条件なし）
    config = AppConfig(
        target_urls=["https://example.com"],
        download_conditions=DownloadConditions(),
        search_conditions=SearchConditions(),
        save_paths=SavePaths(local="./test_downloads"),
        schedule=ScheduleConfig(),
        logging=LoggingConfig(),
    )

    logger = Logger()
    service = ApplicationService(logger)

    # 進捗コールバックの記録
    progress_events = []

    def progress_callback(event: ProgressEvent):
        progress_events.append(event)

    # 実行
    run_result = service.run(config, progress_callback=progress_callback)

    # 検証
    assert len(progress_events) > 0
    assert any(e.type == EventType.START for e in progress_events)
    assert run_result.success is True
    assert any(e.type == EventType.COMPLETE for e in progress_events)


def test_has_search_conditions():
    """検索条件のチェック機能の確認"""
    from src.app.service import ApplicationService
    from src.models.config_model import SearchConditions
    from src.utils.logger import Logger

    logger = Logger()
    service = ApplicationService(logger)

    # 検索条件なし（デフォルト値のみ）
    sc_empty = SearchConditions(
        hachu_daibunrui="",
        hachu_chubunrui="",
        hachu_shoubunrui="",
        hachu_saibunrui="",
        koji_name="",
        place_chihou="",
        place_todofuken="",
        place_shichouson="",
        place_text="",
        contract_types=[],  # 空のリスト
        update_date_type="none",
        koukoku_date_type="none",
        kaisatsu_date_type="none",
        keiyaku_date_type="none",
        koji_shubetsu="",
        koji_gyoushu="",
        rakusatsu_name="",
        denshi=False,
        koukai=False
    )
    assert service._has_search_conditions(sc_empty) is False

    # 検索条件あり（工事名）
    sc_with_koji_name = SearchConditions(koji_name="トンネル")
    assert service._has_search_conditions(sc_with_koji_name) is True

    # 検索条件あり（大分類）
    sc_with_daibunrui = SearchConditions(hachu_daibunrui="国の機関")
    assert service._has_search_conditions(sc_with_daibunrui) is True


def test_application_service_cleanup():
    """ApplicationServiceのクリーンアップ確認"""
    from src.app.service import ApplicationService
    from src.utils.logger import Logger
    from src.utils.http_client import HTTPClient

    logger = Logger()
    service = ApplicationService(logger)
    
    # HTTPClientを設定
    http_client = Mock(spec=HTTPClient)
    service._http_client = http_client
    
    # クリーンアップ実行
    service._cleanup()
    
    http_client.close.assert_called_once_with()


@patch('src.app.service.HTTPClient')
@patch('src.app.service.Scraper')
@patch('src.app.service.Filter')
@patch('src.app.service.Naming')
@patch('src.app.service.Downloader')
def test_detail_failure_with_downloaded_file_is_partial(
    mock_downloader,
    mock_naming,
    mock_filter,
    mock_scraper,
    mock_http_client,
    tmp_path,
):
    """詳細ページの一部失敗をSUCCESSへ丸めない。"""
    from src.app.events import EventType
    from src.app.run_result import RunOutcome
    from src.app.service import ApplicationService
    from src.models.config_model import AppConfig, SavePaths, SearchConditions
    from src.models.download_result import DownloadResult
    from src.models.file_info import FileInfo
    from src.utils.logger import Logger

    file_info = FileInfo(
        "https://example.invalid/file.pdf",
        "file.pdf",
        ".pdf",
    )
    scraper = MagicMock()
    scraper.submit_search_form.return_value = MagicMock()
    scraper.extract_file_links_from_search_results.return_value = [file_info]
    scraper.last_search_diagnostics = SimpleNamespace(
        errors=["詳細ページ1件の取得に失敗"]
    )
    mock_scraper.return_value = scraper
    filter_instance = MagicMock()
    filter_instance.filter_files.return_value = [file_info]
    mock_filter.return_value = filter_instance
    downloader = MagicMock()
    downloader.download_files.return_value = DownloadResult(
        total=1, success=1
    )
    mock_downloader.return_value = downloader
    config = AppConfig(
        target_urls=["https://example.invalid/search"],
        search_conditions=SearchConditions(koji_name="テスト"),
        save_paths=SavePaths(local=str(tmp_path)),
    )
    events = []

    run_result = ApplicationService(Logger()).run(
        config, progress_callback=events.append
    )

    assert run_result.outcome == RunOutcome.PARTIAL
    assert run_result.success is True
    assert "検索結果内処理失敗=1件" in run_result.message
    terminal = events[-1]
    assert terminal.type == EventType.COMPLETE
    assert terminal.metadata["outcome"] == "PARTIAL"
    assert terminal.metadata["type"] == "warning"


@patch('src.app.service.HTTPClient')
@patch('src.app.service.Scraper')
@patch('src.app.service.Filter')
@patch('src.app.service.Naming')
@patch('src.app.service.Downloader')
def test_all_detail_failures_are_failed_not_no_match(
    mock_downloader,
    mock_naming,
    mock_filter,
    mock_scraper,
    mock_http_client,
    tmp_path,
):
    """検索ページが成功しても詳細が全滅した場合はFAILEDとする。"""
    from src.app.events import EventType
    from src.app.run_result import RunOutcome
    from src.app.service import ApplicationService
    from src.models.config_model import AppConfig, SavePaths, SearchConditions
    from src.utils.logger import Logger

    scraper = MagicMock()
    scraper.submit_search_form.return_value = MagicMock()
    scraper.extract_file_links_from_search_results.return_value = []
    scraper.last_search_diagnostics = SimpleNamespace(
        errors=["詳細ページを取得できません"]
    )
    mock_scraper.return_value = scraper
    config = AppConfig(
        target_urls=["https://example.invalid/search"],
        search_conditions=SearchConditions(koji_name="テスト"),
        save_paths=SavePaths(local=str(tmp_path)),
    )
    events = []

    run_result = ApplicationService(Logger()).run(
        config, progress_callback=events.append
    )

    assert run_result.outcome == RunOutcome.FAILED
    assert run_result.success is False
    assert "検索ページの取得または解析に失敗" in run_result.message
    assert events[-1].type == EventType.FAIL
    assert events[-1].metadata["outcome"] == "FAILED"
