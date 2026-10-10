# -*- coding: utf-8 -*-

"""設定値間の検証に関する回帰テスト。"""

import pytest

from src.config.config_validator import ConfigValidator
from src.models.config_model import AppConfig, IPPI_OFFICIAL_SEARCH_URL
from src.utils import path_utils


class StubLogger:
    def warning(self, message):
        pass


@pytest.mark.parametrize(
    ("normal_folder", "scheduled_folder"),
    [
        ("Foo", "foo"),
        ("A B", "A_B"),
        ("CON", "_CON"),
    ],
)
def test_save_folder_names_must_differ_after_windows_normalization(
    normal_folder,
    scheduled_folder,
):
    config = AppConfig()
    config.save_paths.normal_folder = normal_folder
    config.save_paths.scheduled_folder = scheduled_folder

    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is False
    assert "通常ダウンロードと定期実行のフォルダー名は分けてください" in errors


def test_distinct_save_folder_names_are_accepted():
    config = AppConfig()
    config.save_paths.normal_folder = "01_通常ダウンロード"
    config.save_paths.scheduled_folder = "02_定期実行"

    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is True
    assert errors == []


def test_mutated_schedule_notification_policy_is_rejected():
    config = AppConfig()
    config.schedule.notification_policy = "unexpected"

    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is False
    assert "スケジュールの完了通知方針が不正です" in errors


def test_target_url_is_limited_to_canonical_official_search_page():
    config = AppConfig(target_urls=[IPPI_OFFICIAL_SEARCH_URL])

    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is True
    assert errors == []

    config.target_urls = ["https://www.i-ppi.jp/other"]
    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is False
    assert any("公式検索URL" in error for error in errors)


@pytest.mark.parametrize(
    "attribute",
    ["save", "log"],
)
def test_unc_paths_are_rejected_without_resolving_them(attribute, monkeypatch):
    config = AppConfig()
    if attribute == "save":
        config.save_paths.local = r"\\server\share\downloads"
    else:
        config.logging.file = r"\\server\share\logs\app.log"
    unc_resolve_called = False
    original_resolve = path_utils.resolve_app_path

    def track_resolve(candidate):
        nonlocal unc_resolve_called
        if path_utils._looks_like_unc_or_device_path(candidate):
            unc_resolve_called = True
            raise AssertionError("UNCを解決してはいけません")
        return original_resolve(candidate)

    monkeypatch.setattr(path_utils, "resolve_app_path", track_resolve)

    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is False
    assert unc_resolve_called is False
    assert any("UNC" in error for error in errors)


def test_remote_drive_is_rejected_before_path_resolution(monkeypatch):
    resolve_called = False

    def track_resolve(_path):
        nonlocal resolve_called
        resolve_called = True
        raise AssertionError("リモートドライブを解決してはいけません")

    monkeypatch.setattr(path_utils, "_get_windows_drive_type", lambda _path: 4)
    monkeypatch.setattr(path_utils, "resolve_app_path", track_resolve)

    with pytest.raises(ValueError, match="ネットワークドライブ"):
        path_utils.resolve_verified_local_path("./downloads")

    assert resolve_called is False


@pytest.mark.parametrize("drive_type", [2, 3])
def test_fixed_and_removable_drives_are_allowed(monkeypatch, drive_type):
    monkeypatch.setattr(
        path_utils,
        "_get_windows_drive_type",
        lambda _path: drive_type,
    )

    resolved = path_utils.resolve_verified_local_path("./downloads")

    assert resolved.is_absolute()
