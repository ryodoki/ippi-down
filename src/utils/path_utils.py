# -*- coding: utf-8 -*-

"""パス解決ユーティリティ

exe配布時と開発時の両方で正しいパスを解決するためのユーティリティ。
"""

import sys
from pathlib import Path


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
