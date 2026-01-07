"""ファイル操作ユーティリティ"""

import os
import re
from pathlib import Path
from typing import Optional


class FileUtils:
    """ファイル操作ユーティリティ"""

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """ファイル名から無効な文字を削除"""
        # Windowsで無効な文字を削除
        invalid_chars = r'[<>:"/\\|?*]'
        filename = re.sub(invalid_chars, "_", filename)

        # 先頭・末尾の空白とドットを削除
        filename = filename.strip(" .")

        # 連続する空白やアンダースコアを1つに
        filename = re.sub(r"[_\s]+", "_", filename)

        # 空の場合はデフォルト名を返す
        if not filename:
            filename = "untitled"

        return filename

    @staticmethod
    def ensure_unique(file_path: str) -> str:
        """ファイルパスが既に存在する場合、一意なパスを生成"""
        path = Path(file_path)
        if not path.exists():
            return file_path

        # ファイル名に連番を追加
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1

        while True:
            new_name = f"{stem}_{counter}{suffix}"
            new_path = parent / new_name
            if not new_path.exists():
                return str(new_path)
            counter += 1

    @staticmethod
    def create_directory_structure(path: str) -> bool:
        """ディレクトリ構造を作成"""
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            return False

    @staticmethod
    def get_file_size(file_path: str) -> int:
        """ファイルサイズを取得（バイト）"""
        try:
            return os.path.getsize(file_path)
        except OSError:
            return 0

    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """ファイルサイズを人間が読みやすい形式に変換"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

