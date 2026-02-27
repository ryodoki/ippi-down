# -*- coding: utf-8 -*-

"""ConfigModelのテスト"""

import pytest
from pathlib import Path
import sys

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.config_model import (
    AppConfig,
    ScheduleConfig,
    LoggingConfig,
    DownloadConditions,
    SearchConditions,
)


class TestScheduleConfig:
    """ScheduleConfigのテストクラス"""

    def test_schedule_config_default(self):
        """デフォルト設定のテスト"""
        config = ScheduleConfig()
        assert config.enabled is False
        assert config.interval == "daily"
        assert config.time == "09:00"

    def test_schedule_config_custom_without_cron(self):
        """custom intervalでcronが指定されていない場合のエラーテスト"""
        with pytest.raises(ValueError, match="cron形式を指定してください"):
            ScheduleConfig(enabled=True, interval="custom", cron=None)

    def test_schedule_config_custom_with_cron(self):
        """custom intervalでcronが指定されている場合のテスト"""
        config = ScheduleConfig(enabled=True, interval="custom", cron="0 9 * * *")
        assert config.interval == "custom"
        assert config.cron == "0 9 * * *"

    def test_schedule_config_daily_without_time(self):
        """daily intervalでtimeが指定されていない場合のエラーテスト"""
        with pytest.raises(ValueError, match="timeを指定してください"):
            ScheduleConfig(enabled=True, interval="daily", time="")

    def test_schedule_config_invalid_time_format(self):
        """無効なtime形式のテスト"""
        with pytest.raises(ValueError, match="HH:MM形式で指定してください"):
            ScheduleConfig(enabled=True, interval="daily", time="25:00")

    def test_schedule_config_valid_time_format(self):
        """有効なtime形式のテスト"""
        config = ScheduleConfig(enabled=True, interval="daily", time="09:00")
        assert config.time == "09:00"


class TestAppConfig:
    """AppConfigのテストクラス"""

    def test_app_config_default(self):
        """デフォルト設定のテスト"""
        config = AppConfig()
        assert len(config.target_urls) > 0
        assert config.download_conditions is not None
        assert config.search_conditions is not None
        assert config.save_paths is not None
        assert config.schedule is not None
        assert config.logging is not None


class TestSearchConditions:
    """SearchConditions のデフォルト（起動時に検索条件が勝手に入らない）"""

    def test_contract_types_default_empty(self):
        """contract_types のデフォルトは空リスト（全選択にしない）"""
        sc = SearchConditions()
        assert sc.contract_types == []

    def test_is_effectively_empty_default(self):
        """デフォルト状態は空と判定される"""
        sc = SearchConditions()
        assert sc.is_effectively_empty() is True

    def test_is_effectively_empty_with_daibunrui(self):
        """大分類が設定されていれば空でない"""
        sc = SearchConditions(hachu_daibunrui="国の機関")
        assert sc.is_effectively_empty() is False

    def test_is_effectively_empty_with_koji_name(self):
        """工事名が設定されていれば空でない"""
        sc = SearchConditions(koji_name="テスト工事")
        assert sc.is_effectively_empty() is False

    def test_is_effectively_empty_with_full_contract_types(self):
        """入札方式5つ全選択はデフォルト扱い（空と判定）"""
        sc = SearchConditions(contract_types=[
            "一般競争入札", "公募型指名競争入札", "指名競争入札", "随意契約", "その他方式"
        ])
        assert sc.is_effectively_empty() is True

    def test_is_effectively_empty_with_partial_contract_types(self):
        """入札方式が一部選択なら空でない"""
        sc = SearchConditions(contract_types=["一般競争入札"])
        assert sc.is_effectively_empty() is False

    def test_is_effectively_empty_with_price(self):
        """予定価格が設定されていれば空でない"""
        sc = SearchConditions(yotei_price_min=1000000)
        assert sc.is_effectively_empty() is False

