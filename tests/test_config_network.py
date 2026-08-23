# -*- coding: utf-8 -*-

"""NetworkConfig の読み込み・既定値・検証のテスト"""

import sys
from pathlib import Path

import pytest
import yaml

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.app.exceptions import ConfigError
from src.config.config_manager import ConfigManager
from src.config.config_validator import ConfigValidator
from src.models.config_model import AppConfig, LoggingConfig, NetworkConfig
from src.utils.logger import Logger

ALLOWED_URL = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"


@pytest.fixture
def logger():
    return Logger(LoggingConfig(level="INFO"))


def write_config(tmp_path: Path, body: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(body, allow_unicode=True), encoding="utf-8")
    return path


def test_defaults_allow_only_the_target_site():
    network = NetworkConfig()
    assert network.allowed_hosts == ["www.i-ppi.jp"]
    assert network.allowed_schemes == ["https"]
    assert network.block_private_ips is True
    assert network.min_interval_seconds == 1.0
    assert network.max_concurrency == 1
    assert network.max_requests_per_run == 500
    assert network.robots.enabled is True
    assert network.robots.on_error == "block"
    assert "ippi-down" in network.user_agent_suffix


def test_network_section_is_loaded(tmp_path, logger):
    path = write_config(
        tmp_path,
        {
            "target_urls": [ALLOWED_URL],
            "network": {
                "allowed_hosts": ["www.i-ppi.jp"],
                "min_interval_seconds": 2.5,
                "max_requests_per_run": 10,
                "allowed_hours": "08:00-22:00",
                "robots": {"enabled": False, "on_error": "allow"},
                "audit_log": "./logs/net.log",
            },
        },
    )
    config = ConfigManager(config_path=str(path), logger=logger).load_config()

    assert config.network.min_interval_seconds == 2.5
    assert config.network.max_requests_per_run == 10
    assert config.network.allowed_hours == "08:00-22:00"
    assert config.network.robots.enabled is False
    assert config.network.robots.on_error == "allow"
    assert config.network.audit_log == "./logs/net.log"


def test_missing_network_section_falls_back_to_defaults(tmp_path, logger):
    path = write_config(tmp_path, {"target_urls": [ALLOWED_URL]})
    config = ConfigManager(config_path=str(path), logger=logger).load_config()
    assert config.network.allowed_hosts == ["www.i-ppi.jp"]
    assert config.network.robots.enabled is True


def test_target_url_outside_the_allowlist_stops_startup(tmp_path, logger):
    path = write_config(
        tmp_path,
        {
            "target_urls": ["https://example.com/list"],
            "network": {"allowed_hosts": ["www.i-ppi.jp"]},
        },
    )
    with pytest.raises(ConfigError) as excinfo:
        ConfigManager(config_path=str(path), logger=logger).load_config()
    assert "allowed_hosts" in str(excinfo.value)


def test_plain_http_target_url_stops_startup(tmp_path, logger):
    path = write_config(
        tmp_path,
        {
            "target_urls": ["http://www.i-ppi.jp/list"],
            "network": {"allowed_hosts": ["www.i-ppi.jp"], "allowed_schemes": ["https"]},
        },
    )
    with pytest.raises(ConfigError):
        ConfigManager(config_path=str(path), logger=logger).load_config()


def test_validator_reports_invalid_network_values(logger):
    validator = ConfigValidator(logger)
    config = AppConfig(
        target_urls=[ALLOWED_URL],
        network=NetworkConfig(
            allowed_hosts=[],
            min_interval_seconds=-1,
            max_concurrency=0,
            max_requests_per_run=0,
            allowed_hours="いつでも",
        ),
    )
    config.network.robots.on_error = "ignore"
    errors = validator.validate_network(config)

    joined = " / ".join(errors)
    assert "allowed_hosts" in joined
    assert "min_interval_seconds" in joined
    assert "max_concurrency" in joined
    assert "max_requests_per_run" in joined
    assert "allowed_hours" in joined
    assert "robots.on_error" in joined


def test_wildcard_host_is_accepted(logger):
    validator = ConfigValidator(logger)
    config = AppConfig(
        target_urls=[ALLOWED_URL],
        network=NetworkConfig(allowed_hosts=["*.i-ppi.jp"]),
    )
    assert validator.validate_network(config) == []


def test_network_settings_survive_a_save_and_load_round_trip(tmp_path, logger):
    manager = ConfigManager(config_path=str(tmp_path / "config.yaml"), logger=logger)
    config = AppConfig(
        target_urls=[ALLOWED_URL],
        network=NetworkConfig(min_interval_seconds=3.0, max_requests_per_run=42),
    )
    assert manager.save_config(config) is True

    reloaded = manager.load_config()
    assert reloaded.network.min_interval_seconds == 3.0
    assert reloaded.network.max_requests_per_run == 42


def test_example_config_matches_the_policy(logger):
    example = yaml.safe_load(
        (project_root / "config" / "config.example.yaml").read_text(encoding="utf-8")
    )
    assert example["network"]["allowed_hosts"] == ["www.i-ppi.jp"]
    assert example["network"]["allowed_schemes"] == ["https"]
    assert example["network"]["robots"]["enabled"] is True

    validator = ConfigValidator(logger)
    config = ConfigManager(logger=logger)._dict_to_config(example)
    assert validator.validate_network(config) == []
