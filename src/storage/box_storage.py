"""Box Storage実装"""

from typing import Optional, BinaryIO
from ..utils.logger import Logger
from ..app.exceptions import BoxApiError
from .base import Storage
from .box_client import BoxClient


class BoxStorage(Storage):
    """Box Storage実装"""

    def __init__(
        self,
        box_client: BoxClient,
        base_folder_id: str,
        logger: Optional[Logger] = None
    ):
        """初期化"""
        self.box_client = box_client
        self.base_folder_id = base_folder_id
        self.logger = logger or box_client.logger

    def exists(self, key: str) -> bool:
        """ファイルが存在するかチェック（Storageインターフェース）"""
        # keyはfilenameとして扱う
        return self.box_client.file_exists(self.base_folder_id, key)

    def save(
        self,
        stream: BinaryIO,
        key: str,
        metadata: Optional[dict] = None
    ) -> bool:
        """ファイルを保存（Storageインターフェース）"""
        try:
            # 一時ファイルに保存してからBoxにアップロード
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(key)[1]) as tmp_file:
                tmp_file.write(stream.read())
                tmp_path = tmp_file.name

            try:
                # Boxにアップロード
                success = self.box_client.upload_file(tmp_path, self.base_folder_id)
                return success
            finally:
                # 一時ファイルを削除
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except Exception as e:
            self.logger.error(f"Box保存エラー: {key} - {str(e)}")
            raise BoxApiError(f"Box保存エラー: {key} - {str(e)}")

    def ensure_path(self, key: str) -> None:
        """パス（ディレクトリ）を確保（Storageインターフェース）"""
        # Boxではフォルダを作成
        folder_id = self.box_client.create_folder(key, self.base_folder_id)
        if not folder_id:
            raise BoxApiError(f"Boxフォルダ作成エラー: {key}")
