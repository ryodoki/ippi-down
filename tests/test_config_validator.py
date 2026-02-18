# -*- coding: utf-8 -*-

"""ConfigValidator のテスト（命名規則検証を含む）"""

import pytest
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.config_validator import ConfigValidator
from src.models.config_model import AppConfig, SavePaths, SearchConditions


class TestConfigValidatorNamingRule:
    """命名規則テンプレートの検証"""

    def test_valid_naming_rule_passes(self):
        """使用可能な変数のみのテンプレートはエラーにならない"""
        v = ConfigValidator()
        errors = v.validate_naming_rule("{category}_{title}_{date}_{index}")
        assert errors == []

    def test_unknown_key_returns_error(self):
        """未知の変数があるとエラーメッセージと使用可能一覧が返る"""
        v = ConfigValidator()
        errors = v.validate_naming_rule("{category}_{typo_key}_{index}")
        assert len(errors) == 1
        assert "typo_key" in errors[0]
        assert "使用可能" in errors[0] or "category" in errors[0]

    def test_validate_config_includes_naming_error(self):
        """validate_config で naming_rule に未知キーがあるとエラーに含まれる"""
        v = ConfigValidator()
        config = AppConfig(
            target_urls=["https://example.com/"],
            save_paths=SavePaths(local="./out"),
            naming_rule="{unknown_var}_{index}",
        )
        is_valid, errors = v.validate_config(config)
        assert is_valid is False
        assert any("unknown_var" in e or "未知" in e for e in errors)

