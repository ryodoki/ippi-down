# -*- coding: utf-8 -*-

"""ファイル名を生成するクラス"""

from typing import Dict, Any, Optional
from datetime import datetime
from ..models.file_info import FileInfo
from ..models.config_model import SearchConditions
from ..utils.file_utils import FileUtils
from ..utils.logger import Logger


class Naming:
    """ファイル名を生成するクラス"""

    def __init__(self, naming_rule: str, logger: Logger = None, search_conditions: Optional[SearchConditions] = None):
        """初期化
        
        Args:
            naming_rule: 命名規則（テンプレート文字列）
            logger: ロガー
            search_conditions: 検索条件（SearchConditionsオブジェクト）
        """
        self.naming_rule = naming_rule
        self.logger = logger or Logger()
        self.file_utils = FileUtils()
        self.search_conditions = search_conditions

    def generate_filename(
        self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
    ) -> str:
        """ファイル名を生成: 大分類_中分類_小分類_細分類_工事名_ファイル名"""
        # 検索条件から分類情報を取得してファイル名を構築
        parts = []
        
        if self.search_conditions:
            sc = self.search_conditions
            if sc.hachu_daibunrui:
                parts.append(sc.hachu_daibunrui)
            if sc.hachu_chubunrui:
                parts.append(sc.hachu_chubunrui)
            if sc.hachu_shoubunrui:
                parts.append(sc.hachu_shoubunrui)
            if sc.hachu_saibunrui:
                parts.append(sc.hachu_saibunrui)
        else:
            self.logger.debug("検索条件が設定されていないため、分類情報なしでファイル名を生成します")
        
        # 工事名はFileInfoのmetadataから取得（検索条件ではない）
        koji_name = None
        if file_info.metadata and "koji_name" in file_info.metadata:
            koji_name = file_info.metadata["koji_name"]
        elif metadata and "koji_name" in metadata:
            koji_name = metadata["koji_name"]
        
        if koji_name:
            parts.append(koji_name)
        
        # 元のファイル名を追加（拡張子を除く）
        original_filename = file_info.filename
        if "." in original_filename:
            original_filename = original_filename.rsplit(".", 1)[0]
        parts.append(original_filename)
        
        self.logger.debug(f"ファイル名生成 - パーツ: {parts}")
        
        # 結合
        filename = "_".join(parts)
        
        # 無効な文字を削除
        filename = self.file_utils.sanitize_filename(filename)
        
        # 拡張子を追加（元のファイルの拡張子）
        extension = file_info.get_file_extension()
        if extension and not filename.endswith(extension):
            filename += extension

        self.logger.debug(f"生成されたファイル名: '{filename}'")
        return filename

    def _build_context_from_search_conditions(
        self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
    ) -> Dict[str, Any]:
        """検索条件からコンテキストを構築"""
        context = {
            "filename": file_info.filename,
            "file_type": file_info.get_file_extension().replace(".", ""),
            "category": metadata.get("category", "") if metadata else "",
            "title": metadata.get("title", "") if metadata else "",
            "date": datetime.now().strftime("%Y%m%d"),
            "index": str(index),
        }
        
        # 検索条件から分類情報を取得
        if self.search_conditions:
            sc = self.search_conditions
            context["daibunrui"] = sc.hachu_daibunrui or ""
            context["chubunrui"] = sc.hachu_chubunrui or ""
            context["shoubunrui"] = sc.hachu_shoubunrui or ""
            context["saibunrui"] = sc.hachu_saibunrui or ""
            context["koji_name"] = sc.koji_name or ""
        else:
            context["daibunrui"] = ""
            context["chubunrui"] = ""
            context["shoubunrui"] = ""
            context["saibunrui"] = ""
            context["koji_name"] = ""
        
        # メタデータから追加情報を取得
        if metadata:
            context.update(metadata)
        if file_info.metadata:
            context.update(file_info.metadata)
        
        return context

    def generate_folder_name(self, file_info: FileInfo) -> str:
        """フォルダ名を生成: 大分類_中分類_小分類_細分類_工事名
        
        Args:
            file_info: ファイル情報（工事名をmetadataから取得）
        """
        parts = []
        
        # 検索条件から分類情報を取得
        if self.search_conditions:
            sc = self.search_conditions
            if sc.hachu_daibunrui:
                parts.append(sc.hachu_daibunrui)
            if sc.hachu_chubunrui:
                parts.append(sc.hachu_chubunrui)
            if sc.hachu_shoubunrui:
                parts.append(sc.hachu_shoubunrui)
            if sc.hachu_saibunrui:
                parts.append(sc.hachu_saibunrui)
        else:
            self.logger.debug("検索条件が設定されていないため、分類情報なしでフォルダ名を生成します")
        
        # 工事名はFileInfoのmetadataから取得（検索条件ではない）
        koji_name = None
        if file_info.metadata and "koji_name" in file_info.metadata:
            koji_name = file_info.metadata["koji_name"]
        
        if koji_name:
            parts.append(koji_name)
        
        self.logger.debug(f"フォルダ名生成 - パーツ: {parts}")
        
        if not parts:
            self.logger.warning("フォルダ名のパーツが空のため、デフォルトフォルダ名 'その他' を使用します")
            return "その他"
        
        folder_name = "_".join(parts)
        
        # 無効な文字を削除（Windowsのファイル名として使用可能にする）
        folder_name = self.file_utils.sanitize_filename(folder_name)
        
        # 空の場合はデフォルト名を使用
        if not folder_name:
            self.logger.warning("フォルダ名が空のため、デフォルトフォルダ名 'その他' を使用します")
            folder_name = "その他"
        
        self.logger.debug(f"生成されたフォルダ名: '{folder_name}'")
        return folder_name

    def sanitize_filename(self, filename: str) -> str:
        """ファイル名から無効な文字を削除"""
        return self.file_utils.sanitize_filename(filename)

    def ensure_unique(self, file_path: str) -> str:
        """ファイルパスが既に存在する場合、一意なパスを生成"""
        return self.file_utils.ensure_unique(file_path)

