"""FileUtilsのテスト"""

import pytest
from pathlib import Path
import sys
import os

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.file_utils import FileUtils


class TestFileUtils:
    """FileUtilsのテストクラス"""

    def test_sanitize_filename_basic(self):
        """基本的なファイル名のサニタイズテスト"""
        filename = "test file.pdf"
        result = FileUtils.sanitize_filename(filename)
        assert result == "test_file.pdf"
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result

    def test_sanitize_filename_invalid_chars(self):
        """無効な文字の削除テスト"""
        filename = "test<>:\"/\\|?*file.pdf"
        result = FileUtils.sanitize_filename(filename)
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "/" not in result
        assert "\\" not in result

    def test_sanitize_filename_max_length(self):
        """最大長の制限テスト"""
        long_filename = "a" * 300 + ".pdf"
        result = FileUtils.sanitize_filename(long_filename, max_length=200)
        assert len(result) <= 200 + len(".pdf")  # 拡張子を含む

    def test_sanitize_filename_empty(self):
        """空のファイル名のテスト"""
        result = FileUtils.sanitize_filename("")
        assert result == "untitled"

    def test_ensure_unique_new_file(self, tmp_path):
        """新しいファイルの一意性確保テスト"""
        file_path = str(tmp_path / "test.txt")
        result = FileUtils.ensure_unique(file_path)
        assert result == file_path

    def test_ensure_unique_existing_file(self, tmp_path):
        """既存ファイルの一意性確保テスト"""
        file_path = tmp_path / "test.txt"
        file_path.write_text("test")
        
        result = FileUtils.ensure_unique(str(file_path))
        assert result != str(file_path)
        assert "_1" in result or result.endswith("_1.txt")

    def test_format_file_size(self):
        """ファイルサイズのフォーマットテスト"""
        assert "B" in FileUtils.format_file_size(100)
        assert "KB" in FileUtils.format_file_size(1024)
        assert "MB" in FileUtils.format_file_size(1024 * 1024)
        assert "GB" in FileUtils.format_file_size(1024 * 1024 * 1024)

