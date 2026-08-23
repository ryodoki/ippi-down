<<<<<<< HEAD
﻿"""Phase B リファクタリング動作確認テスト"""
=======
# -*- coding: utf-8 -*-

"""Phase B リファクタリング動作確認テスト"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

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


def test_page_fetcher_removed():
    """PageFetcher/Parser/Extractor は scraper.py に統合済みのため削除（Phase 1）"""
    pass
