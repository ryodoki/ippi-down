# -*- coding: utf-8 -*-

"""ローカルファイルシステムへの保存を行うクラス"""

from pathlib import Path
from typing import Optional, BinaryIO
from ..utils.logger import Logger
from ..utils.file_utils import FileUtils
from ..app.exceptions import FilesystemError
from .base import Storage


class LocalStorage(Storage):
    """ローカルファイルシステムへの保存を行うクラス"""

    def __init__(self, base_path: str, logger: Optional[Logger] = None):
        """初期化"""
        self.base_path = Path(base_path)
        self.logger = logger or Logger()
        self.file_utils = FileUtils()

        # ベースディレクトリを作成
        self.create_directory_structure(str(self.base_path))

    def save_file(self, file_data: bytes, file_path: str) -> bool:
        """ファイルを保存"""
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "wb") as f:
                f.write(file_data)

            self.logger.info(f"ファイルを保存しました: {file_path}")
            return True

        except Exception as e:
            self.logger.error(f"ファイル保存エラー: {file_path} - {str(e)}")
            return False

    def create_directory_structure(self, path: str) -> bool:
        """ディレクトリ構造を作成"""
        return self.file_utils.create_directory_structure(path)

    def get_save_path(self, relative_path: str) -> Path:
        """保存パスを取得"""
        return self.base_path / relative_path

    def file_exists(self, file_path: str) -> bool:
        """ファイルが存在するかチェック"""
        return Path(file_path).exists()

    # Storageインターフェースの実装
    def exists(self, key: str) -> bool:
        """ファイルが存在するかチェック（Storageインターフェース）"""
        return self.file_exists(key)

    def save(
        self,
        stream: BinaryIO,
        key: str,
        metadata: Optional[dict] = None
    ) -> bool:
        """ファイルを保存（Storageインターフェース）"""
        try:
            path = Path(key)
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "wb") as f:
                f.write(stream.read())

            self.logger.info(f"ファイルを保存しました: {key}")
            return True
        except (IOError, OSError) as e:
            self.logger.error(f"ファイル保存エラー: {key} - {str(e)}")
            raise FilesystemError(f"ファイル保存エラー: {key} - {str(e)}")
        except Exception as e:
            self.logger.error(f"ファイル保存エラー: {key} - {str(e)}")
            raise FilesystemError(f"ファイル保存エラー: {key} - {str(e)}")

    def ensure_path(self, key: str) -> None:
        """パス（ディレクトリ）を確保（Storageインターフェース）"""
        try:
            path = Path(key)
            if path.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
            else:
                path.mkdir(parents=True, exist_ok=True)
        except (IOError, OSError) as e:
            self.logger.error(f"ディレクトリ作成エラー: {key} - {str(e)}")
            raise FilesystemError(f"ディレクトリ作成エラー: {key} - {str(e)}")
