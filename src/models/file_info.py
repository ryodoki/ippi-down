"""ファイル情報を保持するデータモデル"""

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class FileInfo:
    """ファイル情報を保持するデータモデル"""

    url: str  # ファイルURL
    filename: str  # 元のファイル名
    file_type: str  # ファイルタイプ（拡張子）
    size: int = 0  # ファイルサイズ（バイト）
    metadata: Optional[Dict[str, Any]] = None  # メタデータ（タイトル、カテゴリ、日付等）
    page_url: str = ""  # 元のページURL

    def __post_init__(self):
        """初期化後の処理"""
        if self.metadata is None:
            self.metadata = {}

    def get_file_extension(self) -> str:
        """ファイル拡張子を取得"""
        if self.file_type:
            return self.file_type
        # ファイル名から拡張子を抽出
        if "." in self.filename:
            return "." + self.filename.split(".")[-1].lower()
        return ""

    def is_valid(self) -> bool:
        """ファイル情報が有効かどうかをチェック"""
        return bool(self.url and self.filename)

