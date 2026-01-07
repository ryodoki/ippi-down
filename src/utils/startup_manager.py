"""PC起動時の自動実行を管理するクラス"""

import os
import sys
import platform
from pathlib import Path
from typing import Optional
from ..utils.logger import Logger


class StartupManager:
    """PC起動時の自動実行を管理するクラス"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()
        self.system = platform.system()

    def register_startup(self, app_path: str, app_name: str = "ppi-file-downloader") -> bool:
        """PC起動時に自動実行するように登録"""
        try:
            if self.system == "Windows":
                return self._register_windows(app_path, app_name)
            elif self.system == "Darwin":  # macOS
                return self._register_macos(app_path, app_name)
            elif self.system == "Linux":
                return self._register_linux(app_path, app_name)
            else:
                self.logger.warning(f"未対応のOS: {self.system}")
                return False
        except Exception as e:
            self.logger.error(f"スタートアップ登録エラー: {str(e)}")
            return False

    def unregister_startup(self, app_name: str = "ppi-file-downloader") -> bool:
        """PC起動時の自動実行を解除"""
        try:
            if self.system == "Windows":
                return self._unregister_windows(app_name)
            elif self.system == "Darwin":  # macOS
                return self._unregister_macos(app_name)
            elif self.system == "Linux":
                return self._unregister_linux(app_name)
            else:
                return False
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

    def _register_macos(self, app_path: str, app_name: str) -> bool:
        """macOSでスタートアップに登録"""
        try:
            # LaunchAgentsにplistファイルを作成
            launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
            launch_agents_dir.mkdir(parents=True, exist_ok=True)

            plist_path = launch_agents_dir / f"com.{app_name}.plist"
            plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.{app_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{app_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""

            with open(plist_path, "w") as f:
                f.write(plist_content)

            self.logger.info(f"macOSスタートアップに登録しました: {plist_path}")
            return True

        except Exception as e:
            self.logger.error(f"macOSスタートアップ登録エラー: {str(e)}")
            return False

    def _unregister_macos(self, app_name: str) -> bool:
        """macOSでスタートアップを解除"""
        try:
            plist_path = Path.home() / "Library" / "LaunchAgents" / f"com.{app_name}.plist"
            if plist_path.exists():
                plist_path.unlink()
                self.logger.info("macOSスタートアップを解除しました")
                return True
            return False
        except Exception as e:
            self.logger.error(f"macOSスタートアップ解除エラー: {str(e)}")
            return False

    def _register_linux(self, app_path: str, app_name: str) -> bool:
        """Linuxでスタートアップに登録"""
        try:
            # .config/autostartに.desktopファイルを作成
            autostart_dir = Path.home() / ".config" / "autostart"
            autostart_dir.mkdir(parents=True, exist_ok=True)

            desktop_path = autostart_dir / f"{app_name}.desktop"
            desktop_content = f"""[Desktop Entry]
Type=Application
Name={app_name}
Exec={sys.executable} {app_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""

            with open(desktop_path, "w") as f:
                f.write(desktop_content)
            os.chmod(desktop_path, 0o755)

            self.logger.info(f"Linuxスタートアップに登録しました: {desktop_path}")
            return True

        except Exception as e:
            self.logger.error(f"Linuxスタートアップ登録エラー: {str(e)}")
            return False

    def _unregister_linux(self, app_name: str) -> bool:
        """Linuxでスタートアップを解除"""
        try:
            desktop_path = Path.home() / ".config" / "autostart" / f"{app_name}.desktop"
            if desktop_path.exists():
                desktop_path.unlink()
                self.logger.info("Linuxスタートアップを解除しました")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Linuxスタートアップ解除エラー: {str(e)}")
            return False

