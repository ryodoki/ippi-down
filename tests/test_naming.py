# -*- coding: utf-8 -*-

"""Naming クラスのテスト"""

import pytest
from pathlib import Path
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.naming import Naming  # pyright: ignore[reportMissingImports]
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
        """テンプレートに欠けているキーがあっても例外にならない"""
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
        
        # 例外が発生しないことを確認
        filename = naming.generate_filename(file_info, index=1)
        assert filename.endswith(".pdf")

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
