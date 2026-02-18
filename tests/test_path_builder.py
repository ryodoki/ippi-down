# -*- coding: utf-8 -*-

"""path_builder（発注機関フォルダ階層）のユニットテスト（回帰防止）"""

import pytest
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.path_builder import (
    build_save_dir,
    sanitize_and_trim,
    _partition_date,
    PLACEHOLDER,
)
from src.models.file_info import FileInfo
from src.models.config_model import AppConfig, SavePaths


def _config(enable_agency=True, **save_paths_kw):
    sp = SavePaths(
        local="./downloads",
        use_subfolders=True,
        enable_agency_root_folders=enable_agency,
        **save_paths_kw,
    )
    return AppConfig(save_paths=sp)


class TestSanitizeAndTrim:
    """sanitize_and_trim のテスト"""

    def test_none_returns_unknown(self):
        assert sanitize_and_trim(None) == PLACEHOLDER

    def test_empty_string_returns_unknown(self):
        assert sanitize_and_trim("") == PLACEHOLDER
        assert sanitize_and_trim("   ") == PLACEHOLDER

    def test_valid_name_unchanged(self):
        assert sanitize_and_trim("国の機関") == "国の機関"
        assert sanitize_and_trim("工事_入札公告等") == "工事_入札公告等"

    def test_invalid_chars_replaced(self):
        # Windows 禁則文字は FileUtils.sanitize_filename で _ に置換される
        result = sanitize_and_trim("test<>:*/\\|?*name")
        assert "unknown" not in result or result == PLACEHOLDER
        assert "<" not in result and ">" not in result
        assert ":" not in result and "*" not in result
        assert "\\" not in result and "|" not in result and "?" not in result


class TestPartitionDate:
    """_partition_date のテスト（モジュール内で使用）"""

    def test_yyyy(self):
        assert _partition_date("2025-02-15", "yyyy") == "2025"
        assert _partition_date("2024/12/01", "yyyy") == "2024"

    def test_yyyy_mm(self):
        assert _partition_date("2025-02-15", "yyyy_mm") == "2025_02"
        assert _partition_date("2024-01-01", "yyyy_mm") == "2024_01"

    def test_yyyy_mm_dd(self):
        assert _partition_date("2025-02-15", "yyyy_mm_dd") == "2025_02_15"
        assert _partition_date("2024-12-31", "yyyy_mm_dd") == "2024_12_31"

    def test_empty_uses_today(self):
        out = _partition_date(None, "yyyy")
        assert out.isdigit() and len(out) == 4
        out_mm = _partition_date("", "yyyy_mm")
        assert "_" in out_mm and len(out_mm) == 7


class TestBuildSaveDir:
    """build_save_dir のテスト（発注機関フォルダ ON/OFF・欠損・日付・現行互換）"""

    def test_agency_off_returns_base_dir(self, tmp_path):
        """enable_agency_root_folders=False のとき base_dir がそのまま返ること（現行互換）"""
        config = _config(enable_agency=False)
        file_info = FileInfo(
            url="https://example.com/a.pdf",
            filename="a.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国の機関",
                "chubunrui": "国交省",
                "search_tab": "works",
            },
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        assert result == tmp_path
        assert not (tmp_path / "発注機関").exists()

    def test_agency_on_creates_full_hierarchy(self, tmp_path):
        """enable_agency_root_folders=True のとき期待する階層が作成されること"""
        config = _config(
            enable_agency=True,
            agency_root_label="発注機関",
            agency_folder_levels=["daibunrui", "chubunrui", "shoubunrui", "saibunrui"],
            include_search_tab_folder=True,
            date_partition="none",
        )
        file_info = FileInfo(
            url="https://example.com/doc.pdf",
            filename="doc.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国の機関",
                "chubunrui": "国交省",
                "shoubunrui": "東北",
                "saibunrui": "トンネル",
                "search_tab": "works",
            },
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        expected = (
            tmp_path
            / "発注機関"
            / "国の機関"
            / "国交省"
            / "東北"
            / "トンネル"
            / "工事_入札公告等"
        )
        assert result == expected
        assert result.exists()
        assert expected.exists()

    def test_missing_metadata_uses_unknown(self, tmp_path):
        """欠損値があるとき unknown にフォールバックすること"""
        config = _config(enable_agency=True, date_partition="none")
        file_info = FileInfo(
            url="https://example.com/a.pdf",
            filename="a.pdf",
            file_type=".pdf",
            metadata={"daibunrui": "国の機関"},  # chubunrui, shoubunrui, saibunrui, search_tab なし
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        assert (tmp_path / "発注機関" / "国の機関" / PLACEHOLDER / PLACEHOLDER / PLACEHOLDER).exists()
        assert result.exists()

    def test_empty_metadata_all_unknown(self, tmp_path):
        """metadata が空のときも全て unknown で保存に失敗しない"""
        config = _config(enable_agency=True, date_partition="none")
        file_info = FileInfo(
            url="https://example.com/b.pdf",
            filename="b.pdf",
            file_type=".pdf",
            metadata={},
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        for part in ["発注機関", PLACEHOLDER]:
            assert (tmp_path / part).exists() or part in str(result)
        assert result.exists()

    def test_sanitize_removes_invalid_chars(self, tmp_path):
        """フォルダ名に禁則文字が含まれると sanitize で除去されること"""
        config = _config(enable_agency=True, date_partition="none")
        file_info = FileInfo(
            url="https://example.com/c.pdf",
            filename="c.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国<>機関",
                "chubunrui": "国交省",
                "shoubunrui": "東北",
                "saibunrui": "トンネル",
                "search_tab": "works",
            },
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        assert result.exists()
        assert "<" not in str(result) and ">" not in str(result)

    def test_date_partition_yyyy(self, tmp_path):
        """date_partition=yyyy のとき年フォルダができること"""
        config = _config(
            enable_agency=True,
            date_partition="yyyy",
        )
        file_info = FileInfo(
            url="https://example.com/d.pdf",
            filename="d.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国の機関",
                "chubunrui": "国交省",
                "shoubunrui": "東北",
                "saibunrui": "トンネル",
                "search_tab": "works",
                "date": "2025-02-15",
            },
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        assert result.name == "2025"
        assert result.exists()

    def test_date_partition_yyyy_mm(self, tmp_path):
        """date_partition=yyyy_mm のとき年_月フォルダができること"""
        config = _config(
            enable_agency=True,
            date_partition="yyyy_mm",
        )
        file_info = FileInfo(
            url="https://example.com/e.pdf",
            filename="e.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国の機関",
                "chubunrui": "国交省",
                "shoubunrui": "東北",
                "saibunrui": "トンネル",
                "search_tab": "services",
                "date": "2025-03-01",
            },
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        assert result.exists()
        assert "2025_03" in str(result)

    def test_date_partition_yyyy_mm_dd(self, tmp_path):
        """date_partition=yyyy_mm_dd のとき年_月_日フォルダができること"""
        config = _config(
            enable_agency=True,
            date_partition="yyyy_mm_dd",
        )
        file_info = FileInfo(
            url="https://example.com/f.pdf",
            filename="f.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国の機関",
                "chubunrui": "国交省",
                "shoubunrui": "東北",
                "saibunrui": "トンネル",
                "search_tab": "works",
                "date": "2025-12-31",
            },
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        assert result.exists()
        assert "2025_12_31" in str(result)

    def test_services_tab_label(self, tmp_path):
        """search_tab=services のとき業務_入札公告等フォルダになること"""
        config = _config(enable_agency=True, date_partition="none")
        file_info = FileInfo(
            url="https://example.com/g.pdf",
            filename="g.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国の機関",
                "chubunrui": "国交省",
                "shoubunrui": "東北",
                "saibunrui": "トンネル",
                "search_tab": "services",
            },
        )
        result = build_save_dir(tmp_path, file_info, config, logger=None)
        assert "業務_入札公告等" in str(result)
        assert result.exists()
