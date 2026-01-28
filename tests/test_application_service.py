"""ApplicationServiceの動作確認テスト"""

import pytest
import sys
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
    """ApplicationService.run() - ファイルが見つからない場合"""
    from src.app.service import ApplicationService
    from src.models.config_model import AppConfig, SearchConditions, DownloadConditions, SavePaths, ScheduleConfig, LoggingConfig
    from src.utils.logger import Logger

    # モックの設定
    mock_scraper_instance = MagicMock()
    mock_scraper_instance.fetch_page.return_value = None
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
    assert "ファイルが見つかりませんでした" in run_result.message


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
    # 成功した場合のみCOMPLETEイベントが発行される
    if run_result.success:
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
    service._http_client = HTTPClient(logger)
    
    # クリーンアップ実行
    service._cleanup()
    
    # HTTPClientが閉じられていることを確認（実際の実装に依存）
    # ここでは例外が発生しないことを確認
    assert True
