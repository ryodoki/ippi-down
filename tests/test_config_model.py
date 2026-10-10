# -*- coding: utf-8 -*-

"""ConfigModelのテスト"""

import pytest

from src.models.config_model import (
    AppConfig,
    ScheduleConfig,
)


class TestScheduleConfig:
    """ScheduleConfigのテストクラス"""

    def test_schedule_config_default(self):
        """デフォルト設定のテスト"""
        config = ScheduleConfig()
        assert config.enabled is False
        assert config.interval == "daily"
        assert config.time == "09:00"

    def test_schedule_config_custom_is_legacy_unsupported(self):
        """旧custom設定は読込可能だが実行対象外であること"""
        config = ScheduleConfig(enabled=True, interval="custom", cron=None)
        assert config.is_supported is False

    def test_schedule_config_custom_with_cron(self):
        """cronは旧設定との互換性のため保持されること"""
        config = ScheduleConfig(enabled=True, interval="custom", cron="0 9 * * *")
        assert config.interval == "custom"
        assert config.cron == "0 9 * * *"
        assert config.is_supported is False

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

    def test_schedule_config_weekday(self):
        config = ScheduleConfig(
            enabled=True, interval="weekly", time="09:00", weekday="friday"
        )
        assert config.weekday == "friday"

    def test_schedule_config_invalid_weekday(self):
        with pytest.raises(ValueError, match="weekday"):
            ScheduleConfig(
                enabled=True, interval="weekly", time="09:00", weekday="holiday"
            )

    @pytest.mark.parametrize("day", [0, 29])
    def test_schedule_config_invalid_day_of_month(self, day):
        with pytest.raises(ValueError, match="day_of_month"):
            ScheduleConfig(
                enabled=True, interval="monthly", time="09:00", day_of_month=day
            )


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
