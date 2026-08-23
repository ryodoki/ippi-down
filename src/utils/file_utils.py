<<<<<<< HEAD
﻿"""ファイル操作ユーティリティ"""
=======
# -*- coding: utf-8 -*-

"""ファイル操作ユーティリティ"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

import os
import re
from pathlib import Path
from typing import Optional


class FileUtils:
    """ファイル操作ユーティリティ"""

    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 200) -> str:
        """ファイル名から無効な文字を削除し、長さを制限
        
        Args:
            filename: ファイル名
            max_length: 最大長（拡張子を除く、デフォルト200文字）
                        Windowsのパス長制限（260文字）を考慮
        """
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

        # Windowsパス長制限を考慮（拡張子を除いてmax_length文字以内）
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            ext = '.' + ext
        else:
            name = filename
            ext = ''
        
        # ファイル名を切り詰め
        if len(name) > max_length:
            name = name[:max_length]
            filename = name + ext
        elif len(filename) > max_length + len(ext):
            # 拡張子を含めた全体が長すぎる場合
            max_name_length = max_length - len(ext)
            if max_name_length > 0:
                name = name[:max_name_length]
                filename = name + ext
            else:
                # 拡張子が長すぎる場合はファイル名を短縮
                filename = filename[:max_length]

        return filename

    @staticmethod
    def ensure_unique(file_path: str, max_path_length: int = 260) -> str:
        """ファイルパスが既に存在する場合、一意なパスを生成
        
        Args:
            file_path: ファイルパス
            max_path_length: 最大パス長（Windowsの制限を考慮、デフォルト260文字）
        """
        path = Path(file_path)
        if not path.exists():
            # パス長をチェック
            path_str = str(path)
            if len(path_str) <= max_path_length:
                return path_str
            # パスが長すぎる場合は短縮
            return FileUtils._truncate_path(path_str, max_path_length)

        # ファイル名に連番を追加
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1

        while True:
            new_name = f"{stem}_{counter}{suffix}"
            new_path = parent / new_name
            new_path_str = str(new_path)
            
            # パス長をチェック
            if len(new_path_str) > max_path_length:
                # パスが長すぎる場合は短縮
                new_path_str = FileUtils._truncate_path(new_path_str, max_path_length)
                new_path = Path(new_path_str)
            
            if not new_path.exists():
                return str(new_path)
            counter += 1
            
            # 無限ループを防ぐ（1000回まで）
            if counter > 1000:
                raise ValueError(f"一意なファイル名を生成できませんでした: {file_path}")

    @staticmethod
    def _truncate_path(file_path: str, max_length: int) -> str:
        """パスを最大長以内に切り詰める
        
        Args:
            file_path: ファイルパス
            max_length: 最大長
        """
        if len(file_path) <= max_length:
            return file_path
        
        path = Path(file_path)
        # 親ディレクトリとファイル名を分離
        parent = str(path.parent)
        filename = path.name
        
        # 親ディレクトリの長さを考慮してファイル名を短縮
        available_length = max_length - len(parent) - 1  # -1はパス区切り文字
        if available_length < 10:  # 最低限のファイル名長を確保
            # 親ディレクトリも短縮が必要
            parent_parts = Path(parent).parts
            # 最後のディレクトリ名を短縮
            if len(parent_parts) > 1:
                last_dir = parent_parts[-1]
                if len(last_dir) > 20:
                    last_dir = last_dir[:20]
                parent = str(Path(*parent_parts[:-1]) / last_dir)
                available_length = max_length - len(parent) - 1
        
        if available_length < 10:
            available_length = 10
        
        # ファイル名を短縮
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            ext = '.' + ext
            max_name_length = available_length - len(ext)
            if max_name_length > 0:
                name = name[:max_name_length]
                filename = name + ext
            else:
                filename = filename[:available_length]
        else:
            filename = filename[:available_length]
        
        return str(Path(parent) / filename)

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

