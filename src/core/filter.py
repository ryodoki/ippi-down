# -*- coding: utf-8 -*-

"""ダウンロード条件でフィルタリングを行うクラス"""

import re
from typing import Any, List, Optional
from datetime import date, datetime
from ..models.file_info import FileInfo
from ..models.config_model import DownloadConditions
from ..utils.logger import Logger


class Filter:
    """ダウンロード条件でフィルタリングを行うクラス"""

    DATE_METADATA_KEYS = (
        # 公開文書表の行単位の最終更新日を、文書の取得日条件では
        # 最優先にする。案件全体の公告日とは混同しない。
        "document_updated_at",
        "document_updated_at_filename",
        "date",
        "publication_date",
        "published_date",
        "announcement_date",
        "koukoku_date",
        "date_公告日",
        "update_date",
        "last_update",
        "date_更新日",
        "date_最終更新日",
        "kaisatsu_date",
        "date_開札日",
        "keiyaku_date",
        "date_契約日",
        "acquisition_date",
        "download_date",
        "取得日",
    )

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

        # 公開状態や日時などの診断メタデータを追加してもキーワードへ
        # 意図せず一致しないよう、利用者が認識できる項目だけを対象にする。
        metadata = file_info.metadata or {}
        searchable_metadata = (
            metadata.get("document_name", ""),
            metadata.get("koji_name", ""),
            metadata.get("category", ""),
            metadata.get("title", ""),
        )
        search_text = " ".join(
            str(value)
            for value in (
                file_info.filename,
                file_info.url,
                *searchable_metadata,
            )
            if value not in (None, "")
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

        file_date = self._extract_file_date(file_info)
        if file_date is None:
            self.logger.warning(
                f"日付メタデータがないため日付条件から除外します: {file_info.filename}"
            )
            return False

        try:
            start_value = self._parse_date_value(start_date) if start_date else None
            end_value = self._parse_date_value(end_date) if end_date else None

            if start_date and start_value is None:
                raise ValueError(f"開始日を解析できません: {start_date}")
            if end_date and end_value is None:
                raise ValueError(f"終了日を解析できません: {end_date}")

            if start_value and file_date < start_value:
                return False
            if end_value and file_date > end_value:
                return False

            return True
        except Exception as e:
            self.logger.warning(f"日付解析エラー: {str(e)}")
            return False

    def _extract_file_date(self, file_info: FileInfo) -> Optional[date]:
        """既知のメタデータキーから最初に解析できる日付を取得する。"""
        metadata = file_info.metadata or {}
        for key in self.DATE_METADATA_KEYS:
            value = metadata.get(key)
            if value in (None, ""):
                continue
            parsed = self._parse_date_value(value)
            if parsed is not None:
                return parsed
            self.logger.warning(
                f"日付メタデータを解析できません: {key}={value!r}"
            )
        return None

    @staticmethod
    def _parse_date_value(value: Any) -> Optional[date]:
        """日付、日時、一般的な日付文字列を日付へ正規化する。"""
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            return None

        text = value.strip()
        if not text:
            return None

        # dateutilが直接扱えない日本語表記をISO風へ正規化する。
        japanese_date = re.search(
            r"(?P<year>\d{4})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日?",
            text,
        )
        if japanese_date:
            text = (
                f"{japanese_date.group('year')}-"
                f"{int(japanese_date.group('month')):02d}-"
                f"{int(japanese_date.group('day')):02d}"
            )

        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            pass

        numeric_date = re.search(
            r"(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})",
            text,
        )
        if numeric_date:
            try:
                return date(
                    int(numeric_date.group("year")),
                    int(numeric_date.group("month")),
                    int(numeric_date.group("day")),
                )
            except ValueError:
                return None

        if re.fullmatch(r"\d{8}", text):
            try:
                return datetime.strptime(text, "%Y%m%d").date()
            except ValueError:
                return None
        return None
