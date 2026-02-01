# -*- coding: utf-8 -*-

"""ダウンロード履歴を管理するクラス（FR-008）"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from ..utils.logger import Logger


class DownloadHistory:
    """ダウンロード履歴を管理するクラス"""

    def __init__(self, history_file: str = "logs/download_history.jsonl", logger: Optional[Logger] = None):
        """初期化
        
        Args:
            history_file: 履歴ファイルのパス（JSONL形式）
            logger: ロガーインスタンス
        """
        self.history_file = Path(history_file)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logger or Logger()

    def add_record(
        self,
        url: str,
        filename: str,
        file_path: str,
        file_size: int,
        file_hash: Optional[str] = None,
        status: str = "completed",
        error_message: Optional[str] = None,
    ):
        """ダウンロード履歴を追加
        
        Args:
            url: ダウンロードURL
            filename: ファイル名
            file_path: 保存先パス
            file_size: ファイルサイズ（バイト）
            file_hash: ファイルハッシュ（MD5、オプション）
            status: ステータス（completed, failed, skipped）
            error_message: エラーメッセージ（失敗時）
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "url": url,
            "filename": filename,
            "file_path": str(file_path),
            "file_size": file_size,
            "file_hash": file_hash,
            "status": status,
            "error_message": error_message,
        }
        
        try:
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            self.logger.warning(f"ダウンロード履歴の記録に失敗: {str(e)}")

    def find_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """URLで履歴を検索（最新の1件）
        
        Args:
            url: ダウンロードURL
        
        Returns:
            履歴レコード（見つからない場合はNone）
        """
        if not self.history_file.exists():
            return None
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in reversed(list(f)):
                    if not line.strip():
                        continue
                    record = json.loads(line.strip())
                    if record.get("url") == url and record.get("status") == "completed":
                        return record
        except Exception as e:
            self.logger.warning(f"ダウンロード履歴の読み込みに失敗: {str(e)}")
        
        return None

    def find_by_filename_and_size(self, filename: str, file_size: int) -> Optional[Dict[str, Any]]:
        """ファイル名+サイズで履歴を検索（最新の1件）
        
        Args:
            filename: ファイル名
            file_size: ファイルサイズ（バイト）
        
        Returns:
            履歴レコード（見つからない場合はNone）
        """
        if not self.history_file.exists():
            return None
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in reversed(list(f)):
                    if not line.strip():
                        continue
                    record = json.loads(line.strip())
                    if (record.get("filename") == filename and 
                        record.get("file_size") == file_size and
                        record.get("status") == "completed"):
                        return record
        except Exception as e:
            self.logger.warning(f"ダウンロード履歴の読み込みに失敗: {str(e)}")
        
        return None

    def calculate_file_hash(self, file_path: str) -> Optional[str]:
        """ファイルのMD5ハッシュ値を計算
        
        Args:
            file_path: ファイルパス
        
        Returns:
            MD5ハッシュ値（16進数文字列）、計算失敗時はNone
        """
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.logger.warning(f"ファイルハッシュの計算に失敗: {file_path} - {str(e)}")
            return None
