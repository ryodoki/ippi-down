# -*- coding: utf-8 -*-

from __future__ import annotations

import yaml
import pytest

from src.config.config_manager import ConfigManager
from src.models.config_model import (
    AppConfig,
    ScheduleConfig,
    ScheduleNotificationPolicy,
)
from src.scheduler.models import (
    ScheduleRegistrationStatus,
    ScheduleServiceError,
    ScheduleState,
)
from src.scheduler.profile import (
    PREVIOUS_PROFILE_SCHEMA_VERSION,
    PROFILE_METADATA_KEY,
    PROFILE_SCHEMA_VERSION,
    ScheduleProfileStore,
    calculate_profile_fingerprint,
)


def test_schedule_notification_policy_defaults_to_off_and_validates() -> None:
    assert ScheduleConfig().notification_policy == "off"
    assert (
        ScheduleConfig(
            notification_policy=ScheduleNotificationPolicy.IMPORTANT_ONLY
        ).notification_policy
        == "important_only"
    )

    with pytest.raises(ValueError, match="notification_policy"):
        ScheduleConfig(notification_policy="UNKNOWN")


def test_retry_waiting_schedule_state_is_backward_compatible() -> None:
    assert ScheduleState.RETRY_WAITING.display_name == "再試行待機中"
    assert ScheduleRegistrationStatus().retry_waiting is False


def test_config_manager_round_trip_preserves_notification_policy() -> None:
    manager = ConfigManager()
    config = AppConfig(
        schedule=ScheduleConfig(notification_policy="FAILURES_ONLY")
    )

    document = manager._config_to_dict(config)
    restored = manager._dict_to_config(document)

    assert document["schedule"]["notification_policy"] == "failures_only"
    assert restored.schedule.notification_policy == "failures_only"

    document["schedule"].pop("notification_policy")
    assert manager._dict_to_config(document).schedule.notification_policy == "off"


def test_profile_v3_seals_notification_policy(tmp_path) -> None:
    store = ScheduleProfileStore(tmp_path / "profiles")
    config = AppConfig(
        schedule=ScheduleConfig(notification_policy="IMPORTANT_ONLY")
    )
    profile = store.create(
        config,
        snapshot_id="notification-v3",
        schedule_id="schedule-a",
    )
    document = yaml.safe_load(profile.path.read_text(encoding="utf-8"))

    assert document[PROFILE_METADATA_KEY]["schema_version"] == PROFILE_SCHEMA_VERSION
    assert document["schedule"]["notification_policy"] == "important_only"

    document["schedule"]["notification_policy"] = "ALL_RESULTS"
    profile.path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ScheduleServiceError) as raised:
        store.read(profile.path)
    assert raised.value.reason_code == "PROFILE_FINGERPRINT_MISMATCH"


def test_profile_v2_uses_legacy_fingerprint_and_forces_notification_off(
    tmp_path,
) -> None:
    store = ScheduleProfileStore(tmp_path / "profiles")
    profile = store.create(
        AppConfig(schedule=ScheduleConfig(notification_policy="IMPORTANT_ONLY")),
        snapshot_id="notification-v2",
        schedule_id="schedule-a",
    )
    document = yaml.safe_load(profile.path.read_text(encoding="utf-8"))
    metadata = document[PROFILE_METADATA_KEY]
    metadata["schema_version"] = PREVIOUS_PROFILE_SCHEMA_VERSION
    metadata["fingerprint"] = calculate_profile_fingerprint(
        document,
        schema_version=PREVIOUS_PROFILE_SCHEMA_VERSION,
    )
    # v2では通知方針が未封印だった。管理情報の新しい封印も外し、
    # 実在する旧snapshotと同じ形にする。
    metadata.pop("integrity_fingerprint", None)
    profile.path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    restored = store.read(profile.path)

    assert restored["schedule"]["notification_policy"] == "off"
    assert store.matches_config(
        "notification-v2",
        AppConfig(schedule=ScheduleConfig(notification_policy="ALL_RESULTS")),
    )


def test_notification_policy_changes_current_profile_fingerprint() -> None:
    disabled = AppConfig(schedule=ScheduleConfig(notification_policy="OFF"))
    important = AppConfig(
        schedule=ScheduleConfig(notification_policy="IMPORTANT_ONLY")
    )

    assert calculate_profile_fingerprint(disabled) != calculate_profile_fingerprint(
        important
    )
    assert calculate_profile_fingerprint(
        disabled,
        schema_version=PREVIOUS_PROFILE_SCHEMA_VERSION,
    ) == calculate_profile_fingerprint(
        important,
        schema_version=PREVIOUS_PROFILE_SCHEMA_VERSION,
    )
