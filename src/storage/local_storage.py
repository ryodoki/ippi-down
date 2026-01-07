"""ローカルファイルシステムへの保存を行うクラス"""

from pathlib import Path
from typing import Optional
from ..utils.logger import Logger
from ..utils.file_utils import FileUtils


class LocalStorage:
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

