"""Storage抽象化インターフェース"""

from abc import ABC, abstractmethod
from typing import Optional, BinaryIO
from ..models.file_info import FileInfo


class Storage(ABC):
    """Storage抽象化インターフェース"""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """ファイルが存在するかチェック
        
        Args:
            key: ファイルのキー（パスまたはID）
        
        Returns:
            存在する場合はTrue
        """
        pass

    @abstractmethod
    def save(
        self,
        stream: BinaryIO,
        key: str,
        metadata: Optional[dict] = None
    ) -> bool:
        """ファイルを保存
        
        Args:
            stream: ファイルストリーム
            key: ファイルのキー（パスまたはID）
            metadata: メタデータ（オプション）
        
        Returns:
            保存成功時True
        """
        pass

    @abstractmethod
    def ensure_path(self, key: str) -> None:
        """パス（ディレクトリ）を確保
        
        Args:
            key: パスのキー
        """
        pass
