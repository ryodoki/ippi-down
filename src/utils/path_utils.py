# -*- coding: utf-8 -*-

"""パス解決ユーティリティ

exe配布時と開発時の両方で正しいパスを解決するためのユーティリティ。
"""

import ctypes
import os
import sys
from pathlib import Path
from typing import Union


_DRIVE_REMOVABLE = 2
_DRIVE_FIXED = 3
_DRIVE_REMOTE = 4
_ALLOWED_LOCAL_DRIVE_TYPES = {_DRIVE_REMOVABLE, _DRIVE_FIXED}


def get_base_path() -> Path:
    """アプリケーションのベースパスを取得
    
    PyInstallerでビルドされたexeの場合: exeが存在するディレクトリ
    開発時（python実行）の場合: プロジェクトルート（src/utils/path_utils.pyの親の親の親）
    
    Returns:
        Path: ベースパス
    """
    if getattr(sys, 'frozen', False):
        # PyInstallerでビルドされたexe
        # sys.executableはexeファイルのフルパス
        return Path(sys.executable).parent
    else:
        # 開発時
        # このファイルは src/utils/path_utils.py なので、3階層上がプロジェクトルート
        return Path(__file__).parent.parent.parent


def get_config_path(config_filename: str = "config.yaml") -> Path:
    """設定ファイルのパスを取得
    
    Args:
        config_filename: 設定ファイル名（デフォルト: config.yaml）
    
    Returns:
        Path: 設定ファイルのフルパス
    """
    return get_base_path() / "config" / config_filename


def get_logs_path(log_filename: str = "app.log") -> Path:
    """ログファイルのパスを取得
    
    Args:
        log_filename: ログファイル名（デフォルト: app.log）
    
    Returns:
        Path: ログファイルのフルパス
    """
    return get_base_path() / "logs" / log_filename


def get_downloads_path() -> Path:
    """ダウンロードフォルダのパスを取得
    
    Returns:
        Path: ダウンロードフォルダのフルパス
    """
    return get_base_path() / "downloads"


def resolve_app_path(path: Union[str, Path]) -> Path:
    """相対パスを現在の作業フォルダーではなくアプリ配置場所基準で解決する。"""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = get_base_path() / candidate
    return candidate.resolve(strict=False)


def _looks_like_unc_or_device_path(path: Union[str, Path]) -> bool:
    """UNCとWindowsデバイス名前空間を、I/Oを行わず字句だけで判定する。"""

    text = os.fspath(path).strip().replace("/", "\\")
    return text.startswith("\\\\")


def _get_windows_drive_type(path: Path) -> int | None:
    """解決済みパスのWindowsドライブ種別を返す（非WindowsではNone）。"""

    if os.name != "nt":
        return None
    root = path.anchor
    if not root:
        return None
    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    get_drive_type.argtypes = [ctypes.c_wchar_p]
    get_drive_type.restype = ctypes.c_uint
    return int(get_drive_type(root))


def resolve_verified_local_path(path: Union[str, Path]) -> Path:
    """アプリ基準で解決し、ネットワーク保存先でないことを確認する。

    UNCを先に拒否するため、検証そのものがネットワーク共有へアクセスしない。
    Windowsでは、解決後のドライブが固定またはリムーバブルの場合だけ許可する。
    """

    raw = os.fspath(path).strip()
    if not raw:
        raise ValueError("パスが指定されていません")
    if _looks_like_unc_or_device_path(raw):
        raise ValueError("UNCまたはデバイスパスは使用できません")
    unresolved = Path(raw).expanduser()
    if not unresolved.is_absolute():
        unresolved = get_base_path() / unresolved
    unresolved_drive_type = _get_windows_drive_type(unresolved)
    if unresolved_drive_type == _DRIVE_REMOTE:
        raise ValueError("ネットワークドライブは使用できません")
    try:
        resolved = resolve_app_path(raw)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"パスを安全に解決できません: {exc}") from exc
    if _looks_like_unc_or_device_path(resolved):
        raise ValueError("解決後のパスがネットワーク共有を参照しています")

    drive_type = _get_windows_drive_type(resolved)
    if drive_type is None:
        return resolved
    if drive_type == _DRIVE_REMOTE:
        raise ValueError("ネットワークドライブは使用できません")
    if drive_type not in _ALLOWED_LOCAL_DRIVE_TYPES:
        raise ValueError("固定ドライブまたはリムーバブルドライブを指定してください")
    return resolved


def get_resource_path(relative_path: str) -> Path:
    """リソースファイルのパスを取得
    
    PyInstallerでバンドルされたリソースファイル、または開発時のリソースファイルのパスを取得。
    
    Args:
        relative_path: ベースパスからの相対パス
    
    Returns:
        Path: リソースファイルのフルパス
    """
    if getattr(sys, 'frozen', False):
        # PyInstallerでビルドされた場合
        # _MEIPASSはPyInstallerが一時展開するディレクトリ
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    else:
        # 開発時
        base = get_base_path()
    
    return base / relative_path


def ensure_directory(path: Path) -> None:
    """ディレクトリが存在することを保証する
    
    Args:
        path: 保証したいディレクトリのパス（ファイルパスの場合は親ディレクトリ）
    """
    if path.suffix:
        # ファイルパスの場合は親ディレクトリを作成
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        # ディレクトリパスの場合
        path.mkdir(parents=True, exist_ok=True)
