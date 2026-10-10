# -*- coding: utf-8 -*-

"""通知機能を提供するクラス（Windows専用）"""

from typing import Optional
from ..utils.logger import Logger


class Notifier:
    """通知機能を提供するクラス（Windows専用）"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()

    def notify(self, title: str, message: str, duration: int = 5):
        """通知を表示"""
        try:
            self._notify_windows(title, message, duration)
        except Exception as e:
            self.logger.error(f"通知エラー: {str(e)}")

    def _notify_windows(self, title: str, message: str, duration: int):
        """Windows通知"""
        try:
            from win10toast import ToastNotifier

            toaster = ToastNotifier()
            toaster.show_toast(
                title,
                message,
                duration=duration,
                threaded=True,
            )
            self.logger.info(f"通知を表示: {title} - {message}")
        except ImportError:
            # win10toastがインストールされていない場合、代替手段を使用
            self.logger.warning("win10toastがインストールされていません。代替通知を使用します。")
            self._notify_windows_fallback(title, message)
        except Exception as e:
            self.logger.error(f"Windows通知エラー: {str(e)}")
            self._notify_windows_fallback(title, message)

    def _notify_windows_fallback(self, title: str, message: str):
        """通知ライブラリがない場合はログへ記録する。

        通知はダウンロードやスケジューラーのワーカースレッドから呼ばれる。
        Tkをここで生成するとメインスレッド制約に違反するため、GUI表示は
        EventHandler側に任せ、このフォールバックではTkを一切操作しない。
        """
        self.logger.info(f"通知（ログ代替）: {title} - {message}")
