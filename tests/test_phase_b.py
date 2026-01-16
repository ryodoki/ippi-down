"""Phase B リファクタリング動作確認テスト"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from io import BytesIO

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_custom_exceptions():
    """カスタム例外の動作確認"""
    from src.app.exceptions import (
        PpiDownloaderError,
        NetworkError,
        RateLimitError,
        FilesystemError,
        BoxApiError,
        ConfigError,
        ScrapingError,
        ValidationError
    )
    
    # ベース例外
    base_error = PpiDownloaderError("ベースエラー")
    assert isinstance(base_error, Exception)
    
    # NetworkError
    network_error = NetworkError("ネットワークエラー")
    assert isinstance(network_error, PpiDownloaderError)
    
    # RateLimitError
    rate_limit_error = RateLimitError("レート制限", retry_after=60)
    assert isinstance(rate_limit_error, PpiDownloaderError)
    assert rate_limit_error.retry_after == 60
    
    # FilesystemError
    fs_error = FilesystemError("ファイルシステムエラー")
    assert isinstance(fs_error, PpiDownloaderError)
    
    # BoxApiError
    box_error = BoxApiError("Box APIエラー")
    assert isinstance(box_error, PpiDownloaderError)
    
    # ConfigError
    config_error = ConfigError("設定エラー")
    assert isinstance(config_error, PpiDownloaderError)
    
    # ScrapingError
    scraping_error = ScrapingError("スクレイピングエラー")
    assert isinstance(scraping_error, PpiDownloaderError)
    
    # ValidationError
    validation_error = ValidationError("検証エラー")
    assert isinstance(validation_error, PpiDownloaderError)


def test_storage_interface():
    """Storageインターフェースの動作確認"""
    from src.storage.base import Storage
    from src.storage.local_storage import LocalStorage
    from src.utils.logger import Logger
    import tempfile
    import os
    
    # LocalStorageがStorageを実装しているか確認
    assert issubclass(LocalStorage, Storage)
    
    # 一時ディレクトリでテスト
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = Logger()
        storage = LocalStorage(tmpdir, logger)
        
        # exists
        assert storage.exists("nonexistent.txt") is False
        
        # ensure_path
        test_path = os.path.join(tmpdir, "test", "subdir")
        storage.ensure_path(test_path)
        assert os.path.exists(test_path)
        
        # save
        test_file = os.path.join(tmpdir, "test.txt")
        stream = BytesIO(b"test content")
        result = storage.save(stream, test_file)
        assert result is True
        assert os.path.exists(test_file)
        
        # exists (after save)
        assert storage.exists(test_file) is True


def test_page_fetcher():
    """PageFetcherの動作確認"""
    from src.core.fetcher.page_fetcher import PageFetcher
    from src.utils.http_client import HTTPClient
    from src.utils.logger import Logger
    
    logger = Logger()
    http_client = HTTPClient(logger)
    fetcher = PageFetcher(http_client, logger)
    
    # URL正規化のテスト
    url = "https://example.com/search"
    normalized = fetcher._normalize_search_url(url)
    assert "tab=4" in normalized
    
    # 既にtabパラメータがある場合
    url_with_tab = "https://example.com/search?tab=3"
    normalized2 = fetcher._normalize_search_url(url_with_tab)
    assert "tab=4" in normalized2


def test_aspnet_form_parser():
    """AspNetFormParserの動作確認"""
    from src.core.parser.aspnet_form_parser import AspNetFormParser
    from bs4 import BeautifulSoup
    from src.utils.logger import Logger
    
    logger = Logger()
    parser = AspNetFormParser(logger)
    
    # HTMLサンプル
    html = """
    <html>
    <body>
        <form>
            <input type="hidden" name="__VIEWSTATE" value="test_viewstate" />
            <input type="hidden" name="__EVENTVALIDATION" value="test_validation" />
            <input type="hidden" name="other_field" value="other_value" />
        </form>
    </body>
    </html>
    """
    
    soup = BeautifulSoup(html, "lxml")
    
    # hidden input取得
    hidden_inputs = parser.get_all_hidden_inputs(soup)
    assert "__VIEWSTATE" in hidden_inputs
    assert "__EVENTVALIDATION" in hidden_inputs
    assert hidden_inputs["__VIEWSTATE"] == "test_viewstate"
    
    # POSTバックデータ構築
    post_data = parser.build_postback_data(soup, "btnSearch", "arg1")
    assert post_data["__EVENTTARGET"] == "btnSearch"
    assert post_data["__EVENTARGUMENT"] == "arg1"
    assert "__VIEWSTATE" in post_data


def test_search_result_parser():
    """SearchResultParserの動作確認"""
    from src.core.parser.search_result_parser import SearchResultParser
    from bs4 import BeautifulSoup
    from src.utils.logger import Logger
    
    logger = Logger()
    parser = SearchResultParser(logger)
    
    # HTMLサンプル（検索結果テーブル）
    html = """
    <html>
    <body>
        <table id="dgrSearchList">
            <tr><th>工事名</th><th>詳細</th></tr>
            <tr>
                <td>テスト工事1</td>
                <td><a href="/detail/1">詳細</a></td>
            </tr>
            <tr>
                <td>テスト工事2</td>
                <td><a href="/detail/2">詳細</a></td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    soup = BeautifulSoup(html, "lxml")
    
    # 案件エントリ抽出
    entries = parser.extract_project_entries(soup, "https://example.com")
    assert len(entries) == 2
    assert entries[0].koji_name == "詳細"  # リンクテキスト
    assert "/detail/1" in entries[0].detail_url


def test_detail_page_parser():
    """DetailPageParserの動作確認"""
    from src.core.parser.detail_page_parser import DetailPageParser
    from bs4 import BeautifulSoup
    from src.utils.logger import Logger
    
    logger = Logger()
    parser = DetailPageParser(logger)
    
    # HTMLサンプル（詳細ページ）
    html = """
    <html>
    <body>
        <div>入札公告等</div>
        <table>
            <tr>
                <td>文書1</td>
                <td><a href="/file1.pdf">公開中</a></td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    soup = BeautifulSoup(html, "lxml")
    
    # ファイル候補抽出
    candidates = parser.extract_file_candidates(
        soup, "https://example.com", [".pdf"], "テスト工事"
    )
    assert len(candidates) == 1
    assert candidates[0].file_type == ".pdf"
    assert "file1.pdf" in candidates[0].url


def test_metadata_extractor():
    """MetadataExtractorの動作確認"""
    from src.core.extractor.metadata_extractor import MetadataExtractor
    from src.core.parser.models import FileCandidate, ProjectEntry
    from src.utils.logger import Logger
    
    logger = Logger()
    extractor = MetadataExtractor(logger)
    
    # FileCandidate作成
    candidate = FileCandidate(
        url="https://example.com/file.pdf",
        filename="file.pdf",
        file_type=".pdf",
        document_name="文書名",
        metadata={"test": "value"}
    )
    
    # ProjectEntry作成
    project_entry = ProjectEntry(
        detail_url="https://example.com/detail",
        koji_name="テスト工事",
        metadata={"koji_name": "テスト工事"}
    )
    
    # FileInfoに変換
    file_info = extractor.to_file_info(candidate, project_entry, "https://example.com/page")
    
    assert file_info.url == "https://example.com/file.pdf"
    assert file_info.filename == "file.pdf"
    assert file_info.file_type == ".pdf"
    assert file_info.metadata["koji_name"] == "テスト工事"
    assert file_info.metadata["document_name"] == "文書名"


def test_box_storage():
    """BoxStorageの動作確認"""
    from src.storage.box_storage import BoxStorage
    from src.storage.box_client import BoxClient
    from src.utils.logger import Logger
    from unittest.mock import MagicMock
    
    logger = Logger()
    
    # BoxClientのモック
    box_client = MagicMock(spec=BoxClient)
    box_client.logger = logger
    box_client.file_exists.return_value = False
    box_client.upload_file.return_value = True
    box_client.create_folder.return_value = "folder_id_123"
    
    # BoxStorage作成
    storage = BoxStorage(box_client, "base_folder_id", logger)
    
    # exists
    assert storage.exists("test.pdf") is False
    
    # save
    stream = BytesIO(b"test content")
    result = storage.save(stream, "test.pdf")
    assert result is True
    box_client.upload_file.assert_called_once()
    
    # ensure_path
    storage.ensure_path("new_folder")
    box_client.create_folder.assert_called_once_with("new_folder", "base_folder_id")
