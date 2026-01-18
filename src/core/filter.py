# -*- coding: utf-8 -*-

"""ダウンロード条件でフィルタリングを行うクラス"""

from typing import List
from datetime import datetime
from dateutil import parser as date_parser
from ..models.file_info import FileInfo
from ..models.config_model import DownloadConditions
from ..utils.logger import Logger


class Filter:
    """ダウンロード条件でフィルタリングを行うクラス"""

    def __init__(self, conditions: DownloadConditions, logger: Logger = None):
        """初期化"""
        self.conditions = conditions
        self.logger = logger or Logger()

    def filter_files(self, file_list: List[FileInfo]) -> List[FileInfo]:
        """ファイルリストを条件でフィルタリング"""
        filtered = []

        for file_info in file_list:
            if self._matches_all_conditions(file_info):
                filtered.append(file_info)

        self.logger.info(f"フィルタリング結果: {len(filtered)}/{len(file_list)}件")
        return filtered

    def _matches_all_conditions(self, file_info: FileInfo) -> bool:
        """すべての条件に一致するかチェック"""
        # ファイルタイプのチェック
        if not self.match_file_type(file_info):
            return False

        # キーワードのチェック
        if not self.match_keywords(file_info):
            return False

        # 日付範囲のチェック
        if not self.match_date_range(file_info):
            return False

        return True

    def match_file_type(self, file_info: FileInfo) -> bool:
        """ファイルタイプが条件に一致するかチェック"""
        if not self.conditions.file_types:
            return True  # ファイルタイプが指定されていない場合はすべて一致

        file_ext = file_info.get_file_extension()
        return file_ext.lower() in [ft.lower() for ft in self.conditions.file_types]

    def match_keywords(self, file_info: FileInfo) -> bool:
        """キーワードが条件に一致するかチェック"""
        if not self.conditions.keywords:
            return True  # キーワードが指定されていない場合はすべて一致

        # ファイル名、URL、メタデータから検索
        search_text = (
            file_info.filename
            + " "
            + file_info.url
            + " "
            + str(file_info.metadata or {})
        ).lower()

        for keyword in self.conditions.keywords:
            if keyword.lower() in search_text:
                return True

        return False

    def match_date_range(self, file_info: FileInfo) -> bool:
        """日付範囲が条件に一致するかチェック"""
        if not self.conditions.date_range:
            return True  # 日付範囲が指定されていない場合はすべて一致

        date_range = self.conditions.date_range
        start_date = date_range.get("start")
        end_date = date_range.get("end")

        if not start_date and not end_date:
            return True

        # メタデータから日付を取得（実装は必要に応じて拡張）
        file_date = None
        if file_info.metadata:
            # メタデータから日付を抽出する処理（実装が必要）
            pass

        if not file_date:
            return True  # 日付が取得できない場合は一致とみなす

        try:
            file_datetime = date_parser.parse(file_date) if isinstance(file_date, str) else file_date

            if start_date:
                start_datetime = date_parser.parse(start_date) if isinstance(start_date, str) else start_date
                if file_datetime < start_datetime:
                    return False

            if end_date:
                end_datetime = date_parser.parse(end_date) if isinstance(end_date, str) else end_date
                if file_datetime > end_datetime:
                    return False

            return True
        except Exception as e:
            self.logger.warning(f"日付解析エラー: {str(e)}")
            return True  # エラーの場合は一致とみなす

