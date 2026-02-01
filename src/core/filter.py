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
        """日付範囲が条件に一致するかチェック
        
        日付範囲が指定されていない場合は True を返す。
        日付が取得できない場合は False を返す（フィルタ不一致）。
        """
        if not self.conditions.date_range:
            return True  # 日付範囲が指定されていない場合はすべて一致

        date_range = self.conditions.date_range
        start_date = date_range.get("start")
        end_date = date_range.get("end")

        if not start_date and not end_date:
            return True

        # メタデータから日付を取得
        file_date = None
        if file_info.metadata:
            # 優先順位: koukoku_date > kaisatsu_date > keiyaku_date > update_date
            for date_key in ["koukoku_date", "kaisatsu_date", "keiyaku_date", "update_date", "date"]:
                if date_key in file_info.metadata:
                    file_date = file_info.metadata[date_key]
                    break
        
        if not file_date:
            # 日付が取得できない場合はフィルタ不一致（False）を返す
            self.logger.debug(f"日付が取得できませんでした（フィルタ不一致）: {file_info.filename}")
            return False

        try:
            # 日付文字列を datetime に変換
            if isinstance(file_date, str):
                file_datetime = date_parser.parse(file_date)
            elif isinstance(file_date, datetime):
                file_datetime = file_date
            else:
                self.logger.warning(f"日付の形式が不正です: {file_date} (type: {type(file_date)})")
                return False

            # 開始日チェック
            if start_date:
                start_datetime = date_parser.parse(start_date) if isinstance(start_date, str) else start_date
                if file_datetime < start_datetime:
                    self.logger.debug(
                        f"日付範囲外（開始日より前）: {file_info.filename}, "
                        f"ファイル日付={file_datetime.strftime('%Y-%m-%d')}, 開始日={start_datetime.strftime('%Y-%m-%d')}"
                    )
                    return False

            # 終了日チェック
            if end_date:
                end_datetime = date_parser.parse(end_date) if isinstance(end_date, str) else end_date
                if file_datetime > end_datetime:
                    self.logger.debug(
                        f"日付範囲外（終了日より後）: {file_info.filename}, "
                        f"ファイル日付={file_datetime.strftime('%Y-%m-%d')}, 終了日={end_datetime.strftime('%Y-%m-%d')}"
                    )
                    return False

            return True
        except Exception as e:
            self.logger.warning(f"日付解析エラー: {str(e)}, file_info={file_info.filename}")
            # エラーの場合はフィルタ不一致（False）を返す
            return False

