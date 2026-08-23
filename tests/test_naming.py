# -*- coding: utf-8 -*-

"""Naming クラスのテスト"""

import pytest
from pathlib import Path
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.naming import Naming, DEFAULT_PLACEHOLDER  # pyright: ignore[reportMissingImports]
from src.models.file_info import FileInfo  # pyright: ignore[reportMissingImports]
from src.models.config_model import SearchConditions  # pyright: ignore[reportMissingImports]
from src.utils.logger import Logger, LoggingConfig  # pyright: ignore[reportMissingImports]


class TestNaming:
    """Naming クラスのテスト"""

    def test_generate_filename_with_template(self):
        """テンプレート文字列を使用したファイル名生成"""
        logger = Logger(LoggingConfig(level="WARNING"))
        naming = Naming(
            naming_rule="{category}_{title}_{date}_{index}",
            logger=logger,
            search_conditions=None
        )
        
        file_info = FileInfo(
            url="https://example.com/file.pdf",
            filename="test.pdf",
            file_type=".pdf",
            metadata={"category": "公告", "title": "入札調書"}
        )
        
        filename = naming.generate_filename(file_info, index=1)
        
        # 拡張子が付いていることを確認
        assert filename.endswith(".pdf")
        # テンプレートの要素が含まれていることを確認
        assert "公告" in filename or "入札調書" in filename

    def test_generate_filename_with_missing_key(self):
        """テンプレートに欠けているキーがあっても例外にならず、既定値 unknown が使われる（FR-009）"""
        logger = Logger(LoggingConfig(level="WARNING"))
        naming = Naming(
            naming_rule="{category}_{title}_{date}_{index}_{missing_key}",
            logger=logger,
            search_conditions=None
        )
        
        file_info = FileInfo(
            url="https://example.com/file.pdf",
            filename="test.pdf",
            file_type=".pdf",
            metadata={"category": "公告", "title": "入札調書"}
        )
        
        filename = naming.generate_filename(file_info, index=1)
        assert filename.endswith(".pdf")
        # 欠損キーは安全な既定値になる
        assert DEFAULT_PLACEHOLDER in filename

    def test_generate_filename_without_template(self):
        """テンプレートが設定されていない場合は従来ロジックを使用"""
        logger = Logger(LoggingConfig(level="WARNING"))
        naming = Naming(
            naming_rule="",  # 空文字
            logger=logger,
            search_conditions=None
        )
        
        file_info = FileInfo(
            url="https://example.com/file.pdf",
            filename="test.pdf",
            file_type=".pdf",
            metadata={"category": "公告", "title": "入札調書"}
        )
        
        filename = naming.generate_filename(file_info, index=1)
        assert filename.endswith(".pdf")
        # 従来ロジックではファイル名が含まれる
        assert "test" in filename.lower()

    def test_generate_filename_with_search_conditions(self):
        """検索条件を使用したファイル名生成"""
        logger = Logger(LoggingConfig(level="WARNING"))
        search_conditions = SearchConditions(
            hachu_daibunrui="建設工事",
            hachu_chubunrui="土木工事",
            koji_name="テスト工事"
        )
        naming = Naming(
            naming_rule="{daibunrui}_{chubunrui}_{koji_name}_{filename}",
            logger=logger,
            search_conditions=search_conditions
        )
        
        file_info = FileInfo(
            url="https://example.com/file.pdf",
            filename="test.pdf",
            file_type=".pdf"
        )
        
        filename = naming.generate_filename(file_info, index=1)
        assert filename.endswith(".pdf")
        # 検索条件の要素が含まれていることを確認
        assert "建設工事" in filename or "土木工事" in filename or "テスト工事" in filename

    def test_generate_filename_sanitize(self):
        """無効な文字が削除されることを確認"""
        logger = Logger(LoggingConfig(level="WARNING"))
        naming = Naming(
            naming_rule="{title}",
            logger=logger,
            search_conditions=None
        )
        
        file_info = FileInfo(
            url="https://example.com/file.pdf",
            filename="test.pdf",
            file_type=".pdf",
            metadata={"title": "テスト<>:\"/\\|?*ファイル"}
        )
        
        filename = naming.generate_filename(file_info, index=1)
        # Windowsの無効な文字が含まれていないことを確認
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in invalid_chars:
            assert char not in filename

    def test_generate_filename_ext_placeholder(self):
        """プレースホルダ {ext} はドット付き（.pdf）。{filename}{ext} で doc.xlsx になる（FR-010）"""
        logger = Logger(LoggingConfig(level="WARNING"))
        naming = Naming(
            naming_rule="{filename}{ext}",
            logger=logger,
            search_conditions=None
        )
        file_info = FileInfo(
            url="https://example.com/doc.xlsx",
            filename="doc.xlsx",
            file_type=".xlsx",
            metadata={},
        )
        filename = naming.generate_filename(file_info, index=0)
        assert filename.endswith(".xlsx")
        assert "doc" in filename

    def test_generate_filename_index_ext_produces_0_pdf(self):
        """naming_rule={index}{ext} のとき 0.pdf になる（ext はドット付き）"""
        logger = Logger(LoggingConfig(level="WARNING"))
        naming = Naming(
            naming_rule="{index}{ext}",
            logger=logger,
            search_conditions=None
        )
        file_info = FileInfo(
            url="https://example.com/a.pdf",
            filename="a.pdf",
            file_type=".pdf",
            metadata={},
        )
        filename = naming.generate_filename(file_info, index=0)
        assert filename == "0.pdf"

    def test_generate_filename_empty_metadata_uses_unknown(self):
        """メタデータが空の場合、category/title/koji_name 等が unknown になること（FR-009）"""
        logger = Logger(LoggingConfig(level="WARNING"))
        naming = Naming(
            naming_rule="{category}_{title}_{koji_name}_{index}",
            logger=logger,
            search_conditions=None
        )
        file_info = FileInfo(
            url="https://example.com/a.pdf",
            filename="a.pdf",
            file_type=".pdf",
            metadata={},
        )
        filename = naming.generate_filename(file_info, index=0)
        assert filename.endswith(".pdf")
        # 空のメタデータは unknown に置換される
        assert DEFAULT_PLACEHOLDER in filename
