# -*- coding: utf-8 -*-

"""定期実行の最終結果を、常駐プロセスなしでWindowsへ通知する。"""

from __future__ import annotations

from collections import deque
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
import os
import re
import threading
import time
from typing import Any, Callable, Optional, Protocol

from ..models.config_model import ScheduleNotificationPolicy


MAX_NOTIFICATION_SECONDS = 10.0
MAX_TITLE_LENGTH = 48
MAX_BODY_LENGTH = 200

NOTIFICATION_SUBMITTED = "NOTIFICATION_SUBMITTED"
NOTIFICATION_SUPPRESSED = "NOTIFICATION_SUPPRESSED"
NOTIFICATION_UNAVAILABLE = "NOTIFICATION_UNAVAILABLE"
NOTIFICATION_FAILED = "NOTIFICATION_FAILED"


class NotificationDeliveryStatus(str, Enum):
    """通知処理の診断状態。"""

    SUBMITTED = "submitted"
    SUPPRESSED = "suppressed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class NotificationDeliveryResult:
    """通知結果。

    OS側の集中モードなどにより実際に画面へ描画されたかは判定できないため、
    ``submitted``はShellへの受付成功だけを表す。
    """

    status: NotificationDeliveryStatus
    reason_code: str
    elapsed_seconds: float = 0.0

    @property
    def submitted(self) -> bool:
        return self.status is NotificationDeliveryStatus.SUBMITTED


class NotificationApiUnavailable(RuntimeError):
    """対話デスクトップまたはWindows通知領域を利用できない。"""


class NotificationApi(Protocol):
    """テストでWindows APIを置換するための最小インターフェース。"""

    def show(self, title: str, body: str, timeout_seconds: float) -> None: ...


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _Guid),
        ("hBalloonIcon", wintypes.HICON),
    ]


class _WindowsShellNotificationApi:
    """``Shell_NotifyIconW``を使う短命なWindows通知バックエンド。"""

    _NIM_ADD = 0x00000000
    _NIM_DELETE = 0x00000002
    _NIF_MESSAGE = 0x00000001
    _NIF_ICON = 0x00000002
    _NIF_TIP = 0x00000004
    _NIF_INFO = 0x00000010
    _NIIF_INFO = 0x00000001
    _WM_APP = 0x8000
    _IDI_INFORMATION = 32516
    _PM_REMOVE = 0x0001

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._monotonic = monotonic
        self._sleep = sleep

    def show(self, title: str, body: str, timeout_seconds: float) -> None:
        if os.name != "nt":
            raise NotificationApiUnavailable("Windows以外では通知できません")

        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise NotificationApiUnavailable(
                "Windows通知APIを読み込めません"
            ) from exc

        self._configure_api(user32, shell32)
        hwnd = user32.CreateWindowExW(
            0,
            "STATIC",
            "ippi-down scheduled notification",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            None,
            None,
        )
        if not hwnd:
            raise NotificationApiUnavailable("通知用ウィンドウを作成できません")

        notification: Optional[_NotifyIconData] = None
        added = False
        try:
            notification = _NotifyIconData()
            notification.cbSize = ctypes.sizeof(_NotifyIconData)
            notification.hWnd = hwnd
            notification.uID = 1
            notification.uFlags = (
                self._NIF_MESSAGE
                | self._NIF_ICON
                | self._NIF_TIP
                | self._NIF_INFO
            )
            notification.uCallbackMessage = self._WM_APP + 1
            notification.hIcon = user32.LoadIconW(
                None,
                ctypes.cast(
                    ctypes.c_void_p(self._IDI_INFORMATION), wintypes.LPCWSTR
                ),
            )
            notification.szTip = "ippi-down"
            notification.szInfo = body
            notification.szInfoTitle = title
            notification.dwInfoFlags = self._NIIF_INFO
            notification.uTimeoutOrVersion = int(timeout_seconds * 1000)
            if not shell32.Shell_NotifyIconW(
                self._NIM_ADD, ctypes.byref(notification)
            ):
                raise NotificationApiUnavailable(
                    "Windows通知領域を利用できません"
                )
            added = True
            self._pump_messages(user32, timeout_seconds)
        finally:
            if added and notification is not None:
                shell32.Shell_NotifyIconW(
                    self._NIM_DELETE, ctypes.byref(notification)
                )
            user32.DestroyWindow(hwnd)

    @staticmethod
    def _configure_api(user32: Any, shell32: Any) -> None:
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadIconW.restype = wintypes.HICON
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = wintypes.LRESULT
        shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(_NotifyIconData),
        ]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    def _pump_messages(self, user32: Any, timeout_seconds: float) -> None:
        deadline = self._monotonic() + timeout_seconds
        message = wintypes.MSG()
        while self._monotonic() < deadline:
            while user32.PeekMessageW(
                ctypes.byref(message), None, 0, 0, self._PM_REMOVE
            ):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            remaining = deadline - self._monotonic()
            if remaining > 0:
                self._sleep(min(0.05, remaining))


_SENSITIVE_LOCATION = re.compile(
    r"(?:https?://|file://|[A-Za-z]:[\\/]|\\\\)", re.IGNORECASE
)
_SAFE_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_BENIGN_RESULTS = {"success", "no_match"}
_RESULT_LABELS = {
    "success": "成功",
    "no_match": "該当なし",
    "partial": "一部失敗",
    "partial_failure": "一部失敗",
    "failed": "失敗",
    "run_failed": "失敗",
    "cancelled": "キャンセル",
    "config_invalid": "設定不正",
    "queue_timeout": "キュー待機超過",
    "run_timeout": "実行時間超過",
    "timeout": "実行時間超過",
}

_seen_lock = threading.Lock()
_seen_run_ids: set[str] = set()
_seen_run_order: deque[str] = deque()
_MAX_SEEN_RUN_IDS = 2048


class ScheduledRunNotifier:
    """定期実行レコードから安全な通知文を作り、最終結果を1回だけ通知する。"""

    def __init__(
        self,
        api: Optional[NotificationApi] = None,
        *,
        platform_name: Optional[str] = None,
        timeout_seconds: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._platform_name = platform_name or os.name
        self._api = api
        self._timeout_seconds = min(
            MAX_NOTIFICATION_SECONDS, max(0.0, float(timeout_seconds))
        )
        self._monotonic = monotonic

    def notify(
        self,
        record: Any,
        policy: ScheduleNotificationPolicy | str,
    ) -> NotificationDeliveryResult:
        """最終実行レコードを通知する。

        ``record``は``ExecutionRecord``または``ScheduledRunRecord``相当の
        属性を持つオブジェクトでよく、このモジュールからscheduler層へは依存しない。
        """

        started = self._monotonic()
        try:
            normalized_policy = ScheduleNotificationPolicy(policy)
        except (TypeError, ValueError):
            return self._result(
                NotificationDeliveryStatus.FAILED,
                NOTIFICATION_FAILED,
                started,
            )

        abnormal = self._is_abnormal(record)
        new_count = self._count(record, "new_count", "saved_count")
        should_notify = self._should_notify(
            normalized_policy,
            abnormal=abnormal,
            new_count=new_count,
        )
        if not should_notify:
            return self._result(
                NotificationDeliveryStatus.SUPPRESSED,
                NOTIFICATION_SUPPRESSED,
                started,
            )

        run_id = self._safe_text(getattr(record, "run_id", ""), 128)
        if run_id and not self._claim_run_id(run_id):
            return self._result(
                NotificationDeliveryStatus.SUPPRESSED,
                NOTIFICATION_SUPPRESSED,
                started,
            )

        if self._platform_name != "nt":
            return self._result(
                NotificationDeliveryStatus.UNAVAILABLE,
                NOTIFICATION_UNAVAILABLE,
                started,
            )

        api = self._api or _WindowsShellNotificationApi()
        title, body = self._build_message(record, abnormal=abnormal)
        try:
            api.show(title, body, self._timeout_seconds)
        except NotificationApiUnavailable:
            return self._result(
                NotificationDeliveryStatus.UNAVAILABLE,
                NOTIFICATION_UNAVAILABLE,
                started,
            )
        except Exception:
            return self._result(
                NotificationDeliveryStatus.FAILED,
                NOTIFICATION_FAILED,
                started,
            )
        return self._result(
            NotificationDeliveryStatus.SUBMITTED,
            NOTIFICATION_SUBMITTED,
            started,
        )

    def test_notification(
        self,
        title: str = "ippi-down テスト通知",
        message: str = "定期実行の完了通知を表示できます。",
    ) -> NotificationDeliveryResult:
        """設定画面から、ポリシーやrun_idに関係なく通知経路を確認する。"""

        started = self._monotonic()
        if self._platform_name != "nt":
            return self._result(
                NotificationDeliveryStatus.UNAVAILABLE,
                NOTIFICATION_UNAVAILABLE,
                started,
            )
        safe_title = self._safe_test_text(
            title,
            fallback="ippi-down テスト通知",
            limit=MAX_TITLE_LENGTH,
        )
        safe_message = self._safe_test_text(
            message,
            fallback="定期実行の完了通知を表示できます。",
            limit=MAX_BODY_LENGTH,
        )
        api = self._api or _WindowsShellNotificationApi()
        try:
            api.show(safe_title, safe_message, self._timeout_seconds)
        except NotificationApiUnavailable:
            return self._result(
                NotificationDeliveryStatus.UNAVAILABLE,
                NOTIFICATION_UNAVAILABLE,
                started,
            )
        except Exception:
            return self._result(
                NotificationDeliveryStatus.FAILED,
                NOTIFICATION_FAILED,
                started,
            )
        return self._result(
            NotificationDeliveryStatus.SUBMITTED,
            NOTIFICATION_SUBMITTED,
            started,
        )

    def build_message(self, record: Any) -> tuple[str, str]:
        """GUIのプレビューや単体試験向けに、通知文だけを構築する。"""

        return self._build_message(record, abnormal=self._is_abnormal(record))

    def _result(
        self,
        status: NotificationDeliveryStatus,
        reason_code: str,
        started: float,
    ) -> NotificationDeliveryResult:
        return NotificationDeliveryResult(
            status=status,
            reason_code=reason_code,
            elapsed_seconds=max(0.0, self._monotonic() - started),
        )

    @staticmethod
    def _should_notify(
        policy: ScheduleNotificationPolicy,
        *,
        abnormal: bool,
        new_count: int,
    ) -> bool:
        if policy is ScheduleNotificationPolicy.OFF:
            return False
        if policy is ScheduleNotificationPolicy.ALL_RESULTS:
            return True
        if policy is ScheduleNotificationPolicy.FAILURES_ONLY:
            return abnormal
        return abnormal or new_count > 0

    @classmethod
    def _is_abnormal(cls, record: Any) -> bool:
        result = cls._safe_text(getattr(record, "result", ""), 64).lower()
        failed_count = cls._count(record, "failed_count")
        try:
            exit_code = int(getattr(record, "exit_code", 0) or 0)
        except (TypeError, ValueError):
            exit_code = 1
        return failed_count > 0 or exit_code != 0 or result not in _BENIGN_RESULTS

    @classmethod
    def _build_message(cls, record: Any, *, abnormal: bool) -> tuple[str, str]:
        display_name = cls._safe_display_name(
            getattr(record, "display_name", "")
        )
        title = cls._truncate(f"ippi-down 定期実行: {display_name}", MAX_TITLE_LENGTH)

        result = cls._safe_text(getattr(record, "result", ""), 64).lower()
        result_label = _RESULT_LABELS.get(
            result, "失敗" if abnormal else "完了"
        )
        new_count = cls._count(record, "new_count", "saved_count")
        existing_count = cls._count(record, "existing_count")
        failed_count = cls._count(record, "failed_count")
        body = (
            f"結果: {result_label} / 新規 {new_count}・"
            f"保存済み {existing_count}・失敗 {failed_count}"
        )
        reason_code = cls._safe_reason_code(
            getattr(record, "reason_code", "")
        )
        if reason_code and abnormal:
            body += f" / 理由: {reason_code}"
        return title, cls._truncate(body, MAX_BODY_LENGTH)

    @staticmethod
    def _safe_display_name(value: Any) -> str:
        text = ScheduledRunNotifier._safe_text(value, 80)
        if not text or _SENSITIVE_LOCATION.search(text):
            return "定期実行設定"
        return text

    @staticmethod
    def _safe_test_text(value: Any, *, fallback: str, limit: int) -> str:
        text = ScheduledRunNotifier._safe_text(value, limit)
        if not text or _SENSITIVE_LOCATION.search(text):
            return fallback
        return ScheduledRunNotifier._truncate(text, limit)

    @staticmethod
    def _safe_reason_code(value: Any) -> str:
        text = ScheduledRunNotifier._safe_text(value, 64).upper()
        return text if _SAFE_REASON_CODE.fullmatch(text) else ""

    @staticmethod
    def _safe_text(value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split())
        return text[:limit]

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        if limit <= 1:
            return value[:limit]
        return value[: limit - 1] + "…"

    @staticmethod
    def _count(record: Any, primary: str, fallback: str = "") -> int:
        value = getattr(record, primary, None)
        if value is None and fallback:
            value = getattr(record, fallback, 0)
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _claim_run_id(run_id: str) -> bool:
        with _seen_lock:
            if run_id in _seen_run_ids:
                return False
            _seen_run_ids.add(run_id)
            _seen_run_order.append(run_id)
            while len(_seen_run_order) > _MAX_SEEN_RUN_IDS:
                expired = _seen_run_order.popleft()
                _seen_run_ids.discard(expired)
            return True


__all__ = [
    "MAX_BODY_LENGTH",
    "MAX_NOTIFICATION_SECONDS",
    "MAX_TITLE_LENGTH",
    "NOTIFICATION_FAILED",
    "NOTIFICATION_SUBMITTED",
    "NOTIFICATION_SUPPRESSED",
    "NOTIFICATION_UNAVAILABLE",
    "NotificationApi",
    "NotificationApiUnavailable",
    "NotificationDeliveryResult",
    "NotificationDeliveryStatus",
    "ScheduleNotificationPolicy",
    "ScheduledRunNotifier",
]
