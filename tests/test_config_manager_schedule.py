# -*- coding: utf-8 -*-

from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig, ScheduleConfig


class StubLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


def test_schedule_fields_round_trip(tmp_path):
    manager = ConfigManager(str(tmp_path / "config.yaml"), StubLogger())
    config = AppConfig(
        schedule=ScheduleConfig(
            enabled=True,
            interval="weekly",
            time="07:45",
            weekday="wednesday",
            day_of_month=17,
        )
    )

    assert manager.save_config(config) is True
    loaded = manager.load_config()

    assert loaded.schedule.enabled is True
    assert loaded.schedule.interval == "weekly"
    assert loaded.schedule.time == "07:45"
    assert loaded.schedule.weekday == "wednesday"
    assert loaded.schedule.day_of_month == 17


def test_legacy_custom_is_loaded_with_warning(tmp_path):
    logger = StubLogger()
    manager = ConfigManager(str(tmp_path / "config.yaml"), logger)

    config = manager._dict_to_config(
        {
            "schedule": {
                "enabled": True,
                "interval": "custom",
                "cron": "0 9 * * *",
            }
        }
    )

    assert config.schedule.is_supported is False
    assert any(level == "warning" and "custom" in message for level, message in logger.messages)
