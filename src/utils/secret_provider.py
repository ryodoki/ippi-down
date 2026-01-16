"""Secret Provider（機密情報管理）"""

from abc import ABC, abstractmethod
from typing import Optional
import os


class SecretProvider(ABC):
    """Secret Provider interface"""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """機密情報を取得"""
        pass

    @abstractmethod
    def set(self, key: str, value: str) -> bool:
        """機密情報を設定（実装可能な場合）"""
        pass


class EnvSecretProvider(SecretProvider):
    """環境変数ベースのSecret Provider"""

    def __init__(self, prefix: str = "PPI_"):
        """初期化"""
        self.prefix = prefix

    def get(self, key: str) -> Optional[str]:
        """環境変数から機密情報を取得"""
        env_key = f"{self.prefix}{key.upper()}"
        return os.getenv(env_key)

    def set(self, key: str, value: str) -> bool:
        """環境変数に機密情報を設定"""
        env_key = f"{self.prefix}{key.upper()}"
        os.environ[env_key] = value
        return True


class ConfigSecretProvider(SecretProvider):
    """設定ファイルベースのSecret Provider（非推奨、後方互換性のため）"""

    def __init__(self, secrets: dict):
        """初期化"""
        self.secrets = secrets

    def get(self, key: str) -> Optional[str]:
        """設定から機密情報を取得"""
        return self.secrets.get(key)

    def set(self, key: str, value: str) -> bool:
        """設定に機密情報を設定"""
        self.secrets[key] = value
        return True
