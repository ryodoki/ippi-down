# -*- coding: utf-8 -*-

"""FileUtilsのテスト"""

import pytest
from pathlib import Path

from src.utils.file_utils import FileUtils
from src.utils import path_utils


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

    @pytest.mark.parametrize(
        "value",
        ["CON", "con.pdf", "AUX", "LPT1.txt", "COM9"],
    )
    def test_sanitize_filename_windows_reserved_names(self, value):
        """Windows予約デバイス名を通常ファイル名へ無害化する。"""
        result = FileUtils.sanitize_filename(value)
        assert result.startswith("_")

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

    def test_long_paths_keep_extension_and_use_stable_hash(self, tmp_path):
        first = FileUtils.build_safe_download_path(
            tmp_path,
            "案件" * 180,
            "資料" * 180 + ".pdf",
        )
        second = FileUtils.build_safe_download_path(
            tmp_path,
            "案件" * 180,
            "資料" * 179 + "別.pdf",
        )

        assert len(str(first)) <= 240
        assert first.suffix == ".pdf"
        assert second.suffix == ".pdf"
        assert first != second

    def test_truncated_target_is_rechecked_for_collision(self, tmp_path):
        original = tmp_path / (("a" * 300) + ".pdf")
        first = Path(FileUtils.ensure_unique(str(original), max_path_length=120))
        first.write_bytes(b"existing")

        second = Path(FileUtils.ensure_unique(str(original), max_path_length=120))

        assert second != first
        assert not second.exists()

    def test_too_long_base_path_fails_with_actionable_error(self):
        base = Path("C:/") / ("x" * 230)

        with pytest.raises(ValueError, match="より短い保存先"):
            FileUtils.build_safe_download_path(
                base,
                "folder",
                "document.pdf",
                max_path_length=240,
            )

    def test_relative_base_is_resolved_before_path_budget(
        self, tmp_path, monkeypatch
    ):
        """相対パスの絶対配置を含めて長さを判定する。"""
        monkeypatch.chdir(tmp_path)

        result = FileUtils.build_safe_download_path(
            Path("relative-downloads"),
            "分類" * 80,
            ("文書" * 80) + ".pdf",
        )

        assert result.is_absolute()
        assert len(str(result)) <= 240

    def test_format_file_size(self):
        """ファイルサイズのフォーマットテスト"""
        assert "B" in FileUtils.format_file_size(100)
        assert "KB" in FileUtils.format_file_size(1024)
        assert "MB" in FileUtils.format_file_size(1024 * 1024)
        assert "GB" in FileUtils.format_file_size(1024 * 1024 * 1024)


def test_relative_runtime_path_uses_application_base_not_cwd(
    tmp_path, monkeypatch
):
    app_base = tmp_path / "application"
    unrelated_cwd = tmp_path / "parent"
    app_base.mkdir()
    unrelated_cwd.mkdir()
    monkeypatch.setattr(path_utils, "get_base_path", lambda: app_base)
    monkeypatch.chdir(unrelated_cwd)

    resolved = path_utils.resolve_app_path("./downloads")

    assert resolved == (app_base / "downloads").resolve()
