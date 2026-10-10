# -*- coding: utf-8 -*-

"""設定ファイルの往復保存と旧設定移行の回帰テスト。"""

import yaml
import pytest

from src.app.exceptions import ConfigError
from src.config.config_manager import ConfigManager
from src.models.config_model import (
    AppConfig,
    DownloadConditions,
    LoggingConfig,
    SavePaths,
    ScheduleConfig,
    SearchConditions,
    IPPI_OFFICIAL_SEARCH_URL,
)


class StubLogger:
    def __init__(self):
        self.warnings = []

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        self.warnings.append(message)

    def error(self, message, exc_info=False):
        pass


def test_config_round_trip_preserves_supported_fields(tmp_path):
    path = tmp_path / "config.yaml"
    manager = ConfigManager(str(path), StubLogger())
    config = AppConfig(
        target_urls=[IPPI_OFFICIAL_SEARCH_URL],
        download_conditions=DownloadConditions(
            file_types=[".pdf", ".xlsx"],
            keywords=["道路", "橋梁"],
            date_range={"start": "2026-07-01", "end": "2026-07-30"},
        ),
        search_conditions=SearchConditions(
            hachu_daibunrui="国の機関",
            hachu_chubunrui="国土交通省",
            hachu_shoubunrui="地方整備局",
            hachu_saibunrui="関東地方整備局",
            koji_name="トンネル",
            place_search_type="text",
            place_text="東京都",
            koukoku_date_type="range",
            koukoku_date_start="2026-01-01",
            koukoku_date_end="2026-12-31",
            koji_shubetsu="一般土木工事",
            koji_gyoushu="土木一式工事",
            display_count=50,
        ),
        save_paths=SavePaths(local=str(tmp_path / "downloads")),
        naming_rule="{daibunrui}_{koji_name}_{title}_{index}",
        schedule=ScheduleConfig(
            enabled=True,
            interval="weekly",
            time="10:30",
            weekday="friday",
            day_of_month=28,
        ),
        logging=LoggingConfig(file=str(tmp_path / "app.log")),
    )

    assert manager.save_config(config) is True

    loaded = manager.load_config()

    assert loaded == config
    assert loaded.save_paths.layout_version == 4
    assert loaded.save_paths.normal_folder == "01_通常ダウンロード"
    assert loaded.save_paths.scheduled_folder == "02_定期実行"


def test_config_without_layout_version_keeps_legacy_v2_save_root(tmp_path):
    path = tmp_path / "legacy-layout.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "target_urls": [IPPI_OFFICIAL_SEARCH_URL],
                "download_conditions": {"file_types": [".pdf"]},
                "save_paths": {"local": str(tmp_path / "legacy-downloads")},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    loaded = ConfigManager(str(path), StubLogger()).load_config()

    assert loaded.save_paths.layout_version == 2
    assert loaded.save_paths.local == str(tmp_path / "legacy-downloads")
    assert loaded.save_paths.schedule_storage_key == ""
    assert loaded.save_paths.schedule_storage_folder == ""


def test_legacy_custom_schedule_is_loaded_disabled(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "target_urls": [IPPI_OFFICIAL_SEARCH_URL],
                "download_conditions": {"file_types": [".pdf"]},
                "save_paths": {"local": str(tmp_path / "downloads")},
                "schedule": {
                    "enabled": True,
                    "interval": "custom",
                    "cron": "0 9 * * *",
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    logger = StubLogger()
    manager = ConfigManager(str(path), logger)

    loaded = manager.load_config()

    assert loaded.schedule.interval == "custom"
    assert loaded.schedule.enabled is False
    assert any("custom" in warning for warning in logger.warnings)


def test_legacy_box_settings_are_warned_and_not_used(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "target_urls": [IPPI_OFFICIAL_SEARCH_URL],
                "download_conditions": {"file_types": [".pdf"]},
                "save_paths": {
                    "local": str(tmp_path / "downloads"),
                    "box": {"enabled": True, "folder_id": "legacy"},
                },
                "box": {"access_token": "legacy-secret"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    logger = StubLogger()
    manager = ConfigManager(str(path), logger)

    loaded = manager.load_config()

    assert loaded.save_paths.local == str(tmp_path / "downloads")
    assert any("Box" in warning for warning in logger.warnings)


def test_only_legacy_default_naming_rule_is_migrated(tmp_path):
    legacy_path = tmp_path / "legacy.yaml"
    legacy_path.write_text(
        yaml.safe_dump(
            {
                "target_urls": [IPPI_OFFICIAL_SEARCH_URL],
                "naming_rule": "{category}_{title}_{date}_{index}",
                "save_paths": {"local": str(tmp_path / "downloads")},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    logger = StubLogger()

    migrated = ConfigManager(str(legacy_path), logger).load_config()

    assert migrated.naming_rule == "{document_name}_{document_updated_at}"
    assert any("命名規則" in warning for warning in logger.warnings)

    custom_path = tmp_path / "custom.yaml"
    custom_path.write_text(
        yaml.safe_dump(
            {
                "target_urls": [IPPI_OFFICIAL_SEARCH_URL],
                "naming_rule": "{koji_name}_{filename}",
                "save_paths": {"local": str(tmp_path / "downloads")},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    custom = ConfigManager(str(custom_path), StubLogger()).load_config()

    assert custom.naming_rule == "{koji_name}_{filename}"


def test_missing_config_uses_defaults(tmp_path):
    manager = ConfigManager(str(tmp_path / "missing.yaml"), StubLogger())

    loaded = manager.load_config()

    assert loaded.target_urls == [IPPI_OFFICIAL_SEARCH_URL]


def test_existing_invalid_config_is_not_replaced_with_defaults(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "invalid.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "target_urls": ["https://example.test/search"],
                "save_paths": {"local": str(tmp_path / "downloads")},
            }
        ),
        encoding="utf-8",
    )
    manager = ConfigManager(str(path), StubLogger())
    monkeypatch.setattr(
        manager,
        "get_default_config",
        lambda: pytest.fail("既存の不正設定を既定値へ置換してはいけません"),
    )

    with pytest.raises(ConfigError, match="公式検索URL"):
        manager.load_config()
