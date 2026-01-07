"""通知機能を提供するクラス"""

import platform
from typing import Optional
from ..utils.logger import Logger


class Notifier:
    """通知機能を提供するクラス"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()
        self.system = platform.system()

    def notify(self, title: str, message: str, duration: int = 5):
        """通知を表示"""
        try:
            if self.system == "Windows":
                self._notify_windows(title, message, duration)
            elif self.system == "Darwin":  # macOS
                self._notify_macos(title, message)
            elif self.system == "Linux":
                self._notify_linux(title, message)
            else:
                self.logger.warning(f"未対応のOS: {self.system}")
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
        """Windows通知のフォールバック（メッセージボックス）"""
        try:
            import tkinter.messagebox as messagebox
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()  # メインウィンドウを非表示
            messagebox.showinfo(title, message)
            root.destroy()
        except Exception as e:
            self.logger.error(f"フォールバック通知エラー: {str(e)}")

    def _notify_macos(self, title: str, message: str):
        """macOS通知"""
        try:
            import subprocess

            script = f'''
            display notification "{message}" with title "{title}"
            '''
            subprocess.run(["osascript", "-e", script], check=True)
        except Exception as e:
            self.logger.error(f"macOS通知エラー: {str(e)}")

    def _notify_linux(self, title: str, message: str):
        """Linux通知"""
        try:
            import subprocess

            subprocess.run(
                ["notify-send", title, message],
                check=True,
            )
        except Exception as e:
            self.logger.error(f"Linux通知エラー: {str(e)}")

