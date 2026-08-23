<<<<<<< HEAD
﻿"""ファイル名を生成するクラス"""
=======
# -*- coding: utf-8 -*-

"""ファイル名を生成するクラス"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

from typing import Dict, Any, Optional
from datetime import datetime
from ..models.file_info import FileInfo
from ..models.config_model import SearchConditions
from ..utils.file_utils import FileUtils
from ..utils.logger import Logger

# テンプレートの欠損キー・空値用の安全な既定値（FR-009/FR-010）
DEFAULT_PLACEHOLDER = "unknown"

# 命名テンプレートで使用可能な変数（README・設定画面と一致させる）
NAMING_TEMPLATE_VARIABLES = (
    "category",
    "title",
    "date",
    "index",
    "filename",
    "file_type",
    "ext",
    "koji_name",
    "daibunrui",
    "chubunrui",
    "shoubunrui",
    "saibunrui",
)


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
        """ファイル名を生成
        
        naming_rule が設定されている場合はテンプレート文字列を使用し、
        設定されていない場合は従来の固定ロジックを使用する。
        """
        # コンテキストを構築
        context = self._build_context_from_search_conditions(file_info, metadata, index)
        
        # naming_rule が設定されている場合はテンプレート文字列を使用
        if self.naming_rule and self.naming_rule.strip():
            try:
                # テンプレート文字列を展開
                filename = self.naming_rule.format_map(context)
                self.logger.debug(f"テンプレート文字列を使用: '{self.naming_rule}' -> '{filename}'")
            except KeyError as e:
                # 欠けているキーがある場合は警告を出して安全な既定値を使用（FR-009）
                missing_key = str(e).strip("'")
                self.logger.warning(f"テンプレートに欠けているキー: {missing_key}。既定値 '{DEFAULT_PLACEHOLDER}' を使用します。")
                safe_context = {**context, missing_key: DEFAULT_PLACEHOLDER}
                filename = self.naming_rule.format_map(safe_context)
            except Exception as e:
                # その他のエラー（フォーマットエラー等）の場合は従来ロジックにフォールバック
                self.logger.warning(f"テンプレート文字列の展開に失敗: {str(e)}。従来のロジックを使用します。")
                filename = self._generate_filename_legacy(file_info, metadata, index)
        else:
            # naming_rule が設定されていない場合は従来の固定ロジックを使用
            filename = self._generate_filename_legacy(file_info, metadata, index)
        
        # 無効な文字を削除
        filename = self.file_utils.sanitize_filename(filename)
        
        # 拡張子を追加（テンプレに {ext} を含む場合は既に付与されているので重複付与しない）
        extension = file_info.get_file_extension()
        if extension and not filename.endswith(extension):
            filename += extension

        self.logger.debug(f"生成されたファイル名: '{filename}'")
        return filename

    def _generate_filename_legacy(
        self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
    ) -> str:
        """従来の固定ロジックでファイル名を生成: 大分類_中分類_小分類_細分類_工事名_ファイル名"""
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
        
        self.logger.debug(f"ファイル名生成（従来ロジック） - パーツ: {parts}")
        
        # 結合
        filename = "_".join(parts)
        return filename

    def _build_context_from_search_conditions(
        self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
    ) -> Dict[str, Any]:
        """検索条件からコンテキストを構築（テンプレート文字列用）"""
        # メタデータをマージ
        merged_metadata = {}
        if metadata:
            merged_metadata.update(metadata)
        if file_info.metadata:
            merged_metadata.update(file_info.metadata)
        
        # 元のファイル名（拡張子を除く）
        original_filename = file_info.filename
        if "." in original_filename:
            original_filename = original_filename.rsplit(".", 1)[0]
        
        ext_raw = file_info.get_file_extension() or ""
        ext_no_dot = ext_raw.replace(".", "") if ext_raw else ""
        # file_type: ドットなし（例: "pdf"）, ext: ドット付き（例: ".pdf"）
        context = {
            "filename": original_filename or DEFAULT_PLACEHOLDER,
            "file_type": ext_no_dot or DEFAULT_PLACEHOLDER,
            "ext": ext_raw if ext_raw else "." + DEFAULT_PLACEHOLDER,
            "category": merged_metadata.get("category") or DEFAULT_PLACEHOLDER,
            "title": merged_metadata.get("title") or DEFAULT_PLACEHOLDER,
            "date": datetime.now().strftime("%Y%m%d"),
            "index": str(index),
            "koji_name": merged_metadata.get("koji_name") or DEFAULT_PLACEHOLDER,
        }
        
        # 検索条件から分類情報を取得
        if self.search_conditions:
            sc = self.search_conditions
            context["daibunrui"] = sc.hachu_daibunrui or DEFAULT_PLACEHOLDER
            context["chubunrui"] = sc.hachu_chubunrui or DEFAULT_PLACEHOLDER
            context["shoubunrui"] = sc.hachu_shoubunrui or DEFAULT_PLACEHOLDER
            context["saibunrui"] = sc.hachu_saibunrui or DEFAULT_PLACEHOLDER
            context["koji_name"] = context.get("koji_name") or merged_metadata.get("koji_name") or (sc.koji_name or DEFAULT_PLACEHOLDER)
        else:
            context["daibunrui"] = DEFAULT_PLACEHOLDER
            context["chubunrui"] = DEFAULT_PLACEHOLDER
            context["shoubunrui"] = DEFAULT_PLACEHOLDER
            context["saibunrui"] = DEFAULT_PLACEHOLDER
            # koji_name は初期 context で設定済み
        
        # メタデータから追加情報を取得（既存のキーを上書きしない）
        for key, value in merged_metadata.items():
            if key not in context:
                context[key] = str(value) if value is not None else DEFAULT_PLACEHOLDER
        
        # すべての値を文字列に変換し、空文字は既定値に（FR-009）
        safe_context = {}
        for key, value in context.items():
            if value is None or value == "":
                safe_context[key] = DEFAULT_PLACEHOLDER
            elif isinstance(value, (int, float)):
                safe_context[key] = str(value)
            elif isinstance(value, datetime):
                safe_context[key] = value.strftime("%Y%m%d")
            else:
                safe_context[key] = str(value)
        
        return safe_context

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

