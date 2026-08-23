<<<<<<< HEAD
﻿"""通知機能を提供するクラス（Windows専用）"""
=======
# -*- coding: utf-8 -*-

"""通知機能を提供するクラス（Windows専用）"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

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
        """Windows通知のフォールバック（メッセージボックス）
        
        注意: このメソッドはimport時に呼ばれないように、notify()メソッド内でのみ呼ばれる
        """
        try:
            import tkinter.messagebox as messagebox
            import tkinter as tk

            # GUIが既に起動している場合は、そのrootを使用
            # 起動していない場合は新規作成（ただし、これは通常の実行時のみ）
            try:
                # 既存のTkインスタンスを探す（存在する場合）
                root = tk._default_root
                if root is None:
                    root = tk.Tk()
                    root.withdraw()  # メインウィンドウを非表示
                    messagebox.showinfo(title, message)
                    root.destroy()
                else:
                    # 既存のrootがある場合は、そのrootでメッセージボックスを表示
                    messagebox.showinfo(title, message)
            except Exception:
                # フォールバック: 新規作成
                root = tk.Tk()
                root.withdraw()
                messagebox.showinfo(title, message)
                root.destroy()
        except Exception as e:
            self.logger.error(f"フォールバック通知エラー: {str(e)}")

