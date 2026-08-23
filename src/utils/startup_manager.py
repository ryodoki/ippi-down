<<<<<<< HEAD
﻿"""PC起動時の自動実行を管理するクラス（Windows専用）"""
=======
# -*- coding: utf-8 -*-

"""PC起動時の自動実行を管理するクラス（Windows専用）"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

import os
import sys
from pathlib import Path
from typing import Optional
from ..utils.logger import Logger


class StartupManager:
    """PC起動時の自動実行を管理するクラス（Windows専用）"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()

    def register_startup(self, app_path: str, app_name: str = "ppi-file-downloader") -> bool:
        """PC起動時に自動実行するように登録"""
        try:
            return self._register_windows(app_path, app_name)
        except Exception as e:
            self.logger.error(f"スタートアップ登録エラー: {str(e)}")
            return False

    def unregister_startup(self, app_name: str = "ppi-file-downloader") -> bool:
        """PC起動時の自動実行を解除"""
        try:
            return self._unregister_windows(app_name)
        except Exception as e:
            self.logger.error(f"スタートアップ解除エラー: {str(e)}")
            return False

    def _register_windows(self, app_path: str, app_name: str) -> bool:
        """Windowsでスタートアップに登録"""
        try:
            import win32com.client

            # スタートアップフォルダのパスを取得
            startup_folder = os.path.join(
                os.environ["APPDATA"],
                "Microsoft",
                "Windows",
                "Start Menu",
                "Programs",
                "Startup",
            )

            # ショートカットを作成
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut_path = os.path.join(startup_folder, f"{app_name}.lnk")
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = sys.executable
            shortcut.Arguments = f'"{app_path}"'
            shortcut.WorkingDirectory = str(Path(app_path).parent)
            shortcut.save()

            self.logger.info(f"Windowsスタートアップに登録しました: {shortcut_path}")
            return True

        except ImportError:
            # pywin32がインストールされていない場合、代替手段を使用
            self.logger.warning("pywin32がインストールされていません。代替方法を使用します。")
            return self._register_windows_fallback(app_path, app_name)
        except Exception as e:
            self.logger.error(f"Windowsスタートアップ登録エラー: {str(e)}")
            return False

    def _register_windows_fallback(self, app_path: str, app_name: str) -> bool:
        """Windowsスタートアップ登録のフォールバック（レジストリ使用）"""
        try:
            import winreg

            # レジストリキーを開く
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )

            # 値を設定
            command = f'"{sys.executable}" "{app_path}"'
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
            winreg.CloseKey(key)

            self.logger.info(f"Windowsレジストリにスタートアップを登録しました")
            return True

        except Exception as e:
            self.logger.error(f"Windowsレジストリストートアップ登録エラー: {str(e)}")
            return False

    def _unregister_windows(self, app_name: str) -> bool:
        """Windowsでスタートアップを解除"""
        try:
            # ショートカットを削除
            startup_folder = os.path.join(
                os.environ["APPDATA"],
                "Microsoft",
                "Windows",
                "Start Menu",
                "Programs",
                "Startup",
            )
            shortcut_path = os.path.join(startup_folder, f"{app_name}.lnk")
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)

            # レジストリからも削除
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_SET_VALUE,
                )
                winreg.DeleteValue(key, app_name)
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass  # レジストリに存在しない場合は無視

            self.logger.info("Windowsスタートアップを解除しました")
            return True

        except Exception as e:
            self.logger.error(f"Windowsスタートアップ解除エラー: {str(e)}")
            return False
