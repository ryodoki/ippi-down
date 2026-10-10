# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
import threading
import uuid

import pytest

import src.utils.scheduled_notifier as scheduled_notifier
from src.utils.scheduled_notifier import (
    MAX_BODY_LENGTH,
    MAX_NOTIFICATION_SECONDS,
    MAX_TITLE_LENGTH,
    NOTIFICATION_FAILED,
    NOTIFICATION_SUBMITTED,
    NOTIFICATION_SUPPRESSED,
    NOTIFICATION_UNAVAILABLE,
    NotificationApiUnavailable,
    NotificationDeliveryStatus,
    ScheduleNotificationPolicy,
    ScheduledRunNotifier,
)


@dataclass
class Record:
    result: str = "success"
    new_count: int = 0
    saved_count: int = 0
    existing_count: int = 0
    failed_count: int = 0
    reason_code: str = "SUCCESS"
    exit_code: int = 0
    display_name: str = "東北トンネル"
    run_id: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = uuid.uuid4().hex


class RecordingApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    def show(self, title: str, body: str, timeout_seconds: float) -> None:
        self.calls.append((title, body, timeout_seconds))


@pytest.mark.parametrize(
    ("policy", "record", "expected"),
    [
        (ScheduleNotificationPolicy.OFF, Record(new_count=2), False),
        (ScheduleNotificationPolicy.IMPORTANT_ONLY, Record(), False),
        (
            ScheduleNotificationPolicy.IMPORTANT_ONLY,
            Record(result="no_match", reason_code="NO_MATCH"),
            False,
        ),
        (ScheduleNotificationPolicy.IMPORTANT_ONLY, Record(new_count=1), True),
        (
            ScheduleNotificationPolicy.IMPORTANT_ONLY,
            Record(result="partial", failed_count=1, exit_code=2),
            True,
        ),
        (ScheduleNotificationPolicy.FAILURES_ONLY, Record(new_count=2), False),
        (
            ScheduleNotificationPolicy.FAILURES_ONLY,
            Record(result="queue_timeout", exit_code=75),
            True,
        ),
        (ScheduleNotificationPolicy.ALL_RESULTS, Record(), True),
    ],
)
def test_policy_selects_only_final_results_requested(
    policy: ScheduleNotificationPolicy,
    record: Record,
    expected: bool,
) -> None:
    api = RecordingApi()
    result = ScheduledRunNotifier(api, platform_name="nt").notify(record, policy)

    assert result.submitted is expected
    assert len(api.calls) == int(expected)
    if expected:
        assert result.reason_code == NOTIFICATION_SUBMITTED
    else:
        assert result.reason_code == NOTIFICATION_SUPPRESSED


def test_control_failure_is_abnormal_even_without_failed_files() -> None:
    api = RecordingApi()
    record = Record(result="config_invalid", reason_code="CONFIG_INVALID", exit_code=3)

    result = ScheduledRunNotifier(api, platform_name="nt").notify(
        record, ScheduleNotificationPolicy.FAILURES_ONLY
    )

    assert result.status is NotificationDeliveryStatus.SUBMITTED
    assert "設定不正" in api.calls[0][1]
    assert "CONFIG_INVALID" in api.calls[0][1]


def test_message_is_bounded_and_does_not_expose_url_or_path() -> None:
    api = RecordingApi()
    record = Record(
        result="failed",
        failed_count=1,
        exit_code=2,
        display_name="C:\\Users\\person\\secret https://example.test/query",
        reason_code="https://example.test/private",
    )

    result = ScheduledRunNotifier(api, platform_name="nt").notify(
        record, ScheduleNotificationPolicy.ALL_RESULTS
    )

    assert result.submitted
    title, body, _timeout = api.calls[0]
    assert len(title) <= MAX_TITLE_LENGTH
    assert len(body) <= MAX_BODY_LENGTH
    assert "定期実行設定" in title
    combined = title + body
    assert "C:\\" not in combined
    assert "https://" not in combined
    assert "example.test" not in combined


def test_message_truncates_long_safe_schedule_name() -> None:
    notifier = ScheduledRunNotifier(RecordingApi(), platform_name="nt")
    title, body = notifier.build_message(Record(display_name="工" * 200))

    assert len(title) == MAX_TITLE_LENGTH
    assert title.endswith("…")
    assert len(body) <= MAX_BODY_LENGTH


def test_same_run_id_is_suppressed_across_instances() -> None:
    api = RecordingApi()
    run_id = uuid.uuid4().hex
    record = Record(new_count=1, run_id=run_id)

    first = ScheduledRunNotifier(api, platform_name="nt").notify(
        record, ScheduleNotificationPolicy.IMPORTANT_ONLY
    )
    second = ScheduledRunNotifier(api, platform_name="nt").notify(
        record, ScheduleNotificationPolicy.ALL_RESULTS
    )

    assert first.submitted
    assert second.status is NotificationDeliveryStatus.SUPPRESSED
    assert second.reason_code == NOTIFICATION_SUPPRESSED
    assert len(api.calls) == 1


def test_duplicate_claim_is_thread_safe() -> None:
    api = RecordingApi()
    record = Record(new_count=1)
    results = []

    def invoke() -> None:
        results.append(
            ScheduledRunNotifier(api, platform_name="nt").notify(
                record, ScheduleNotificationPolicy.ALL_RESULTS
            )
        )

    threads = [threading.Thread(target=invoke) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(result.submitted for result in results) == 1
    assert len(api.calls) == 1


def test_non_windows_is_unavailable_without_calling_injected_api() -> None:
    api = RecordingApi()

    result = ScheduledRunNotifier(api, platform_name="posix").notify(
        Record(new_count=1), ScheduleNotificationPolicy.IMPORTANT_ONLY
    )

    assert result.status is NotificationDeliveryStatus.UNAVAILABLE
    assert result.reason_code == NOTIFICATION_UNAVAILABLE
    assert not api.calls


class UnavailableApi:
    def show(self, title: str, body: str, timeout_seconds: float) -> None:
        del title, body, timeout_seconds
        raise NotificationApiUnavailable("Explorer is unavailable")


class FailedApi:
    def show(self, title: str, body: str, timeout_seconds: float) -> None:
        del title, body, timeout_seconds
        raise OSError("C:\\private\\must-not-be-returned")


@pytest.mark.parametrize(
    ("api", "status", "reason_code"),
    [
        (
            UnavailableApi(),
            NotificationDeliveryStatus.UNAVAILABLE,
            NOTIFICATION_UNAVAILABLE,
        ),
        (FailedApi(), NotificationDeliveryStatus.FAILED, NOTIFICATION_FAILED),
    ],
)
def test_backend_errors_do_not_escape_or_expose_details(
    api, status: NotificationDeliveryStatus, reason_code: str
) -> None:
    result = ScheduledRunNotifier(api, platform_name="nt").notify(
        Record(new_count=1), ScheduleNotificationPolicy.IMPORTANT_ONLY
    )

    assert result.status is status
    assert result.reason_code == reason_code
    assert result.elapsed_seconds >= 0
    assert not hasattr(result, "error")


def test_timeout_is_clamped_to_ten_seconds() -> None:
    api = RecordingApi()

    result = ScheduledRunNotifier(
        api, platform_name="nt", timeout_seconds=999
    ).notify(Record(), ScheduleNotificationPolicy.ALL_RESULTS)

    assert result.submitted
    assert api.calls[0][2] == MAX_NOTIFICATION_SECONDS


def test_invalid_policy_fails_safely_without_api_call() -> None:
    api = RecordingApi()

    result = ScheduledRunNotifier(api, platform_name="nt").notify(
        Record(new_count=1), "invalid"
    )

    assert result.status is NotificationDeliveryStatus.FAILED
    assert result.reason_code == NOTIFICATION_FAILED
    assert not api.calls


def test_policy_values_are_stable_lower_snake_case() -> None:
    assert [policy.value for policy in ScheduleNotificationPolicy] == [
        "off",
        "important_only",
        "all_results",
        "failures_only",
    ]


def test_test_notification_bypasses_policy_and_deduplication() -> None:
    api = RecordingApi()
    notifier = ScheduledRunNotifier(api, platform_name="nt")

    first = notifier.test_notification()
    second = notifier.test_notification()

    assert first.submitted
    assert second.submitted
    assert len(api.calls) == 2
    assert api.calls[0][0] == "ippi-down テスト通知"


def test_test_notification_sanitizes_custom_url_and_path() -> None:
    api = RecordingApi()
    notifier = ScheduledRunNotifier(api, platform_name="nt")

    result = notifier.test_notification(
        "C:\\Users\\private", "https://example.test/secret"
    )

    assert result.submitted
    title, body, _timeout = api.calls[0]
    assert title == "ippi-down テスト通知"
    assert body == "定期実行の完了通知を表示できます。"


def test_mocked_high_volume_notifications_do_not_create_threads() -> None:
    api = RecordingApi()
    before = threading.active_count()
    notifier = ScheduledRunNotifier(api, platform_name="nt", timeout_seconds=0)

    for index in range(1000):
        notifier.notify(
            Record(run_id=f"bulk-{uuid.uuid4().hex}-{index}"),
            ScheduleNotificationPolicy.ALL_RESULTS,
        )

    assert len(api.calls) == 1000
    assert threading.active_count() == before


class FakeUser32:
    def __init__(self, *, fail_icon: bool = False) -> None:
        self.fail_icon = fail_icon
        self.destroyed: list[int] = []

    def CreateWindowExW(self, *_args):
        return 123

    def LoadIconW(self, *_args):
        if self.fail_icon:
            raise OSError("icon failure")
        return 456

    def DestroyWindow(self, hwnd):
        self.destroyed.append(hwnd)
        return True

    def PeekMessageW(self, *_args):
        return False

    def TranslateMessage(self, *_args):
        return True

    def DispatchMessageW(self, *_args):
        return 0


class FakeShell32:
    def __init__(self) -> None:
        self.operations: list[int] = []

    def Shell_NotifyIconW(self, operation, _data):
        self.operations.append(operation)
        return True


def _install_fake_windows_libraries(monkeypatch, user32, shell32) -> None:
    def loader(name, **_kwargs):
        return user32 if name == "user32" else shell32

    monkeypatch.setattr(scheduled_notifier.ctypes, "WinDLL", loader)
    monkeypatch.setattr(
        scheduled_notifier._WindowsShellNotificationApi,
        "_configure_api",
        lambda *_args: None,
    )


def test_native_backend_deletes_icon_and_destroys_window(monkeypatch) -> None:
    user32 = FakeUser32()
    shell32 = FakeShell32()
    _install_fake_windows_libraries(monkeypatch, user32, shell32)

    scheduled_notifier._WindowsShellNotificationApi().show("title", "body", 0)

    assert shell32.operations == [
        scheduled_notifier._WindowsShellNotificationApi._NIM_ADD,
        scheduled_notifier._WindowsShellNotificationApi._NIM_DELETE,
    ]
    assert user32.destroyed == [123]


def test_native_backend_destroys_window_when_preparation_fails(monkeypatch) -> None:
    user32 = FakeUser32(fail_icon=True)
    shell32 = FakeShell32()
    _install_fake_windows_libraries(monkeypatch, user32, shell32)

    with pytest.raises(OSError, match="icon failure"):
        scheduled_notifier._WindowsShellNotificationApi().show(
            "title", "body", 0
        )

    assert shell32.operations == []
    assert user32.destroyed == [123]
