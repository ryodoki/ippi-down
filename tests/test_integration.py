# -*- coding: utf-8 -*-

"""統合テスト（既存機能の動作確認）"""

import pytest
import sys
import requests
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.mark.integration
def test_application_service_with_mocks():
    """ApplicationServiceの統合テスト（モック使用）"""
    from src.app.service import ApplicationService
    from src.models.config_model import AppConfig, SearchConditions, DownloadConditions, SavePaths, ScheduleConfig, LoggingConfig
    from src.models.file_info import FileInfo
    from src.models.download_result import DownloadResult
    from src.utils.logger import Logger

    # モックの設定
    with patch('src.app.service.HTTPClient') as mock_http_client, \
         patch('src.app.service.Scraper') as mock_scraper, \
         patch('src.app.service.Filter') as mock_filter, \
         patch('src.app.service.Naming') as mock_naming, \
         patch('src.app.service.Downloader') as mock_downloader:
        
        # モックインスタンス
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

        # 設定
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
        assert run_result.success is True
        assert run_result.result is not None
        assert run_result.result.total == 1


def test_storage_local_integration():
    """LocalStorageの統合テスト"""
    from src.storage.local_storage import LocalStorage
    from src.utils.logger import Logger
    import tempfile
    import os
    from io import BytesIO

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = Logger()
        storage = LocalStorage(tmpdir, logger)

        # ファイル保存
        test_file = os.path.join(tmpdir, "test", "subdir", "file.txt")
        stream = BytesIO(b"test content")
        result = storage.save(stream, test_file)
        assert result is True
        assert os.path.exists(test_file)

        # ファイル読み込み確認
        with open(test_file, "rb") as f:
            content = f.read()
            assert content == b"test content"

        # 存在確認
        assert storage.exists(test_file) is True


def test_exception_handling():
    """例外処理の統合テスト"""
    from src.app.exceptions import NetworkError, RateLimitError, FilesystemError
    from src.utils.http_client import HTTPClient
    from src.utils.logger import Logger
    from unittest.mock import patch, MagicMock

    import pytest
    from src.models.config_model import NetworkConfig, RobotsConfig

    logger = Logger()
    # 許可ホストへのリクエストで接続エラーを起こす（許可外URLだと送信前に弾かれ、
    # 接続エラーの処理を通らないため）
    http_client = HTTPClient(
        logger,
        timeout=1,  # 短いタイムアウトを設定
        network_config=NetworkConfig(
            min_interval_seconds=0.0, robots=RobotsConfig(enabled=False), audit_log=None
        ),
    )

    # NetworkErrorが発生することを確認（モック）
    # session.getを直接パッチして、即座に例外を発生させる
    with patch.object(http_client.session, 'get', side_effect=requests.exceptions.ConnectionError("Connection error")):
        with pytest.raises(NetworkError):
            http_client.get("https://www.i-ppi.jp/invalid-path", max_retries=1)


def test_page_fetcher_integration_removed():
    """PageFetcher/Parser/Extractor は scraper.py に統合済みのため削除（Phase 1）"""
    pass
