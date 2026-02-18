# -*- coding: utf-8 -*-

"""path_utils のテスト（保存先絶対パス解決）"""

import pytest
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.path_utils import get_base_path, resolve_save_path


class TestResolveSavePath:
    """相対パスがベースパス基準で絶対パスに解決されること"""

    def test_relative_path_resolved_against_base(self):
        """相対パス ./downloads が get_base_path() 基準で解決される"""
        resolved = resolve_save_path("./downloads")
        base = get_base_path()
        assert resolved.is_absolute()
        assert resolved == (base / "downloads").resolve()

    def test_absolute_path_unchanged(self):
        """絶対パスはそのまま返る"""
        abs_path = Path(__file__).resolve().parent
        resolved = resolve_save_path(str(abs_path))
        assert resolved == abs_path
