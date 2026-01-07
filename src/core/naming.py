"""ファイル名を生成するクラス"""

from typing import Dict, Any
from datetime import datetime
from ..models.file_info import FileInfo
from ..utils.file_utils import FileUtils
from ..utils.logger import Logger


class Naming:
    """ファイル名を生成するクラス"""

    def __init__(self, naming_rule: str, logger: Logger = None):
        """初期化"""
        self.naming_rule = naming_rule
        self.logger = logger or Logger()
        self.file_utils = FileUtils()

    def generate_filename(
        self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
    ) -> str:
        """ファイル名を生成"""
        # メタデータをマージ
        context = {
            "filename": file_info.filename,
            "file_type": file_info.get_file_extension().replace(".", ""),
            "category": metadata.get("category", "") if metadata else "",
            "title": metadata.get("title", "") if metadata else "",
            "date": datetime.now().strftime("%Y%m%d"),
            "index": str(index),
        }

        # メタデータから追加情報を取得
        if file_info.metadata:
            context.update(file_info.metadata)

        # 命名規則に従ってファイル名を生成
        filename = self.naming_rule.format(**context)

        # 無効な文字を削除
        filename = self.file_utils.sanitize_filename(filename)

        # 拡張子を追加（元のファイルの拡張子）
        extension = file_info.get_file_extension()
        if extension and not filename.endswith(extension):
            filename += extension

        return filename

    def sanitize_filename(self, filename: str) -> str:
        """ファイル名から無効な文字を削除"""
        return self.file_utils.sanitize_filename(filename)

    def ensure_unique(self, file_path: str) -> str:
        """ファイルパスが既に存在する場合、一意なパスを生成"""
        return self.file_utils.ensure_unique(file_path)

