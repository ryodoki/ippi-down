# -*- coding: utf-8 -*-

"""ファイル名を生成するクラス"""

import hashlib
from pathlib import Path
from typing import Dict, Any, List, Mapping, Optional, Set
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from ..models.file_info import FileInfo
from ..models.config_model import SearchConditions
from ..utils.file_utils import FileUtils
from ..utils.logger import Logger
from ..utils.naming_template import (
    ALLOWED_NAMING_PLACEHOLDERS,
    format_document_updated_at,
    get_unknown_placeholders,
    validate_naming_rule,
)


class Naming:
    """ファイル名を生成するクラス"""

    ALLOWED_PLACEHOLDERS = ALLOWED_NAMING_PLACEHOLDERS
    AGENCY_LEVELS = (
        "daibunrui",
        "chubunrui",
        "shoubunrui",
        "saibunrui",
    )
    DOCUMENT_SECTION_FOLDERS = {
        "入札公告等": "01_入札公告等",
        "入札経過・その他": "02_入札経過・その他",
        "入札の経過": "02_入札経過・その他",
    }

    def __init__(self, naming_rule: str, logger: Logger = None, search_conditions: Optional[SearchConditions] = None):
        """初期化
        
        Args:
            naming_rule: 命名規則（テンプレート文字列）
            logger: ロガー
            search_conditions: 検索条件（SearchConditionsオブジェクト）
        """
        self.validate_rule(naming_rule)
        self.naming_rule = naming_rule
        self.logger = logger or Logger()
        self.file_utils = FileUtils()
        self.search_conditions = search_conditions

    def generate_filename(
        self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
    ) -> str:
        """設定されたテンプレートからファイル名を生成する。"""
        context = self._build_context_from_search_conditions(file_info, metadata, index)
        try:
            filename = self.naming_rule.format_map(context)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"命名規則をファイル名へ適用できません: {exc}") from exc

        # フルパス確定時に安定ハッシュ付きで短縮するため、ここでは末尾を失わない。
        filename = self.file_utils.sanitize_filename(
            filename, max_length=max(200, len(filename))
        )

        # テンプレートに拡張子が含まれない場合も、元ファイルの種類を維持する。
        extension = file_info.get_file_extension()
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        if extension and not filename.lower().endswith(extension.lower()):
            filename += extension

        self.logger.debug(f"生成されたファイル名: '{filename}'")
        return filename

    @classmethod
    def get_unknown_placeholders(cls, naming_rule: str) -> Set[str]:
        """命名規則に含まれる未対応のプレースホルダーを返す。"""
        return get_unknown_placeholders(naming_rule)

    @classmethod
    def validate_rule(cls, naming_rule: str) -> None:
        """命名規則の構文とプレースホルダーを検証する。"""
        validate_naming_rule(naming_rule)

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
            "index": index,
        }
        
        # 検索条件から分類情報を取得
        if self.search_conditions:
            sc = self.search_conditions
            context["daibunrui"] = sc.hachu_daibunrui or ""
            context["chubunrui"] = sc.hachu_chubunrui or ""
            context["shoubunrui"] = sc.hachu_shoubunrui or ""
            context["saibunrui"] = sc.hachu_saibunrui or ""
            context["project_name"] = sc.effective_project_name
            context["koji_name"] = sc.effective_project_name
        else:
            context["daibunrui"] = ""
            context["chubunrui"] = ""
            context["shoubunrui"] = ""
            context["saibunrui"] = ""
            context["koji_name"] = ""
            context["project_name"] = ""
        
        # メタデータから追加情報を取得
        if metadata:
            context.update(metadata)
        if file_info.metadata:
            context.update(file_info.metadata)

        # 文書行固有の値をページ共通タイトルや実行日時から独立させる。
        # HPの日時はJSTの安定した表記へ正規化し、欠落時も現在時刻では
        # 代用しない。
        document_name = str(
            context.get("document_name")
            or Path(file_info.filename).stem
            or "文書"
        ).strip()
        document_id = self._document_id(file_info, context)
        document_updated_at = format_document_updated_at(
            context.get("document_updated_at")
        )
        if not document_updated_at:
            document_updated_at = f"更新日時不明_{document_id}"
        context.update(
            {
                "document_name": document_name,
                "document_id": document_id,
                "document_updated_at": document_updated_at,
                "document_status": str(
                    context.get("document_status")
                    or context.get("publication_status")
                    or ""
                ),
                "document_expires_at": str(
                    context.get("document_expires_at")
                    or context.get("listing_end_at")
                    or ""
                ),
                "document_section": str(
                    context.get("document_section") or ""
                ),
            }
        )
        
        return context

    @staticmethod
    def _document_id(file_info: FileInfo, context: Dict[str, Any]) -> str:
        """文書IDをメタデータ、URL、最後に安定ハッシュから得る。"""
        for key in ("document_id", "bunsho_kanri_id", "BunshoKanriId"):
            value = str(context.get(key) or "").strip()
            if value:
                return value
        try:
            query = parse_qs(urlparse(file_info.url).query)
            for key, values in query.items():
                if key.lower() == "bunshokanriid" and values:
                    value = str(values[0]).strip()
                    if value:
                        return value
        except (TypeError, ValueError):
            pass
        digest = hashlib.sha256(file_info.url.encode("utf-8")).hexdigest()[:8]
        return f"url_{digest}"

    def add_document_id_suffix(
        self,
        filename: str,
        file_info: FileInfo,
    ) -> str:
        """同名・同更新日時が衝突した場合だけ文書IDを付ける。"""
        path = Path(filename)
        document_id = self._document_id(
            file_info,
            file_info.metadata or {},
        )
        candidate = f"{path.stem}_{document_id}{path.suffix}"
        return self.file_utils.sanitize_filename(
            candidate,
            max_length=max(200, len(candidate)),
        )

    @staticmethod
    def _resolution_status(resolution: object) -> str:
        """新旧形式の分類解決結果から状態だけを取り出す。"""
        if isinstance(resolution, Mapping):
            return str(resolution.get("status") or "").strip().lower()
        return str(resolution or "").strip().lower()

    @classmethod
    def _normalize_agency_path(cls, value: object) -> Dict[str, Any]:
        """agency_pathを安全な表示ラベル・コードの組へ正規化する。"""
        if not isinstance(value, Mapping):
            return {}
        raw_segments = value.get("segments")
        if not isinstance(raw_segments, list):
            return {}

        by_level: Dict[str, Dict[str, str]] = {}
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, Mapping):
                continue
            level = str(raw_segment.get("level") or "").strip().lower()
            label = str(raw_segment.get("label") or "").strip()
            if level not in cls.AGENCY_LEVELS or not label or level in by_level:
                continue
            by_level[level] = {
                "level": level,
                "label": label,
                "code": str(raw_segment.get("code") or "").strip(),
            }

        segments: List[Dict[str, str]] = []
        previous_label = ""
        for level in cls.AGENCY_LEVELS:
            segment = by_level.get(level)
            if segment is None:
                continue
            normalized_label = segment["label"].casefold()
            if normalized_label == previous_label:
                continue
            segments.append(segment)
            previous_label = normalized_label
        if not segments:
            return {}

        resolution = value.get("resolution", "")
        if isinstance(resolution, Mapping):
            normalized_resolution: object = {
                "status": str(resolution.get("status") or "").strip(),
                "method": str(resolution.get("method") or "").strip(),
                "reason": str(resolution.get("reason") or "").strip(),
                "reason_code": str(
                    resolution.get("reason_code") or ""
                ).strip(),
            }
        else:
            # 初期v3仕様の文字列形式も読み取れるよう、そのまま保持する。
            normalized_resolution = str(resolution or "").strip()
        try:
            version = int(value.get("version", 1))
        except (TypeError, ValueError):
            version = 1
        return {
            "version": version,
            "segments": segments,
            "resolution": normalized_resolution,
        }

    def generate_agency_path(self, file_info: FileInfo) -> Dict[str, Any]:
        """案件メタデータ、検索条件、取得済み表示名の順に機関階層を得る。"""
        metadata = file_info.metadata or {}
        agency_path = self._normalize_agency_path(metadata.get("agency_path"))
        if agency_path:
            return agency_path

        segments: List[Dict[str, str]] = []
        if self.search_conditions:
            for level in self.AGENCY_LEVELS:
                label = str(
                    getattr(self.search_conditions, f"hachu_{level}", "") or ""
                ).strip()
                if not label:
                    continue
                if segments and segments[-1]["label"].casefold() == label.casefold():
                    continue
                code = str(
                    getattr(
                        self.search_conditions,
                        f"hachu_{level}_code",
                        "",
                    )
                    or ""
                ).strip()
                segments.append({"level": level, "label": label, "code": code})
        if segments:
            return {
                "version": 2,
                "segments": segments,
                "resolution": {
                    "status": "selected",
                    "method": "search_conditions",
                    "reason": "",
                    "reason_code": "AGENCY_SELECTED",
                },
            }

        # 分類マスターと照合できない案件でも取得自体は止めず、取得できた
        # 発注機関・担当部事務所の表示名を未解決配下へ隔離する。
        fallback_labels: List[str] = []
        for key in ("hachu_kikan", "office_name"):
            label = str(metadata.get(key) or "").strip()
            if not label:
                continue
            if fallback_labels and fallback_labels[-1].casefold() == label.casefold():
                continue
            fallback_labels.append(label)
        fallback_levels = ("daibunrui", "saibunrui")
        fallback_segments = [
            {"level": fallback_levels[min(index, 1)], "label": label, "code": ""}
            for index, label in enumerate(fallback_labels)
        ]
        return {
            "version": 2,
            "segments": fallback_segments,
            "resolution": {
                "status": "unresolved",
                "method": "metadata_fallback" if fallback_segments else "none",
                "reason": "発注機関階層を特定できませんでした",
                "reason_code": "AGENCY_SELECTION_MISSING",
            },
        }

    @classmethod
    def generate_agency_folder_parts(
        cls,
        agency_path: object,
        office_name: str = "",
    ) -> List[str]:
        """分類結果から実際に保存へ使う発注機関階層を返す。

        未解決時は推測した細分類を作らず、未解決マーカー、取得済みの
        部分階層、詳細ページに表示された担当事務所名の順で保持する。
        """
        normalized_path = cls._normalize_agency_path(agency_path)
        resolution_status = cls._resolution_status(
            normalized_path.get("resolution")
        )
        agency_labels = [
            str(segment.get("label") or "").strip()
            for segment in normalized_path.get("segments", [])
            if isinstance(segment, Mapping)
            and str(segment.get("label") or "").strip()
        ]
        if resolution_status == "unresolved":
            normalized_office = str(office_name or "").strip()
            if normalized_office and all(
                label.casefold() != normalized_office.casefold()
                for label in agency_labels
            ):
                agency_labels.append(normalized_office)

        parts: List[str] = []
        if resolution_status == "unresolved" or not agency_labels:
            parts.append("99_分類未解決")
        parts.extend(agency_labels)

        safe_parts: List[str] = []
        for part in parts:
            safe = FileUtils.sanitize_path_component(part)
            if safe_parts and safe_parts[-1].casefold() == safe.casefold():
                continue
            safe_parts.append(safe)
        return safe_parts

    @classmethod
    def _document_section_folder(cls, file_info: FileInfo) -> str:
        metadata = file_info.metadata or {}
        section = str(
            metadata.get("document_section")
            or metadata.get("section")
            or ""
        ).strip()
        if section in cls.DOCUMENT_SECTION_FOLDERS:
            return cls.DOCUMENT_SECTION_FOLDERS[section]
        if "入札公告" in section:
            return "01_入札公告等"
        if "入札経過" in section or "入札の経過" in section:
            return "02_入札経過・その他"
        return "99_区分不明"

    def generate_folder_parts(self, file_info: FileInfo) -> List[str]:
        """発注機関階層、工事名、文書区分の安全なパス要素を返す。"""
        agency_path = self.generate_agency_path(file_info)
        metadata = file_info.metadata or {}
        parts = self.generate_agency_folder_parts(
            agency_path,
            office_name=str(metadata.get("office_name") or ""),
        )

        unknown_name = (
            "業務名不明"
            if metadata.get("search_target") == "gyomu_keika"
            else "工事名不明"
        )
        project_name = str(
            metadata.get("project_name")
            or metadata.get("koji_name")
            or unknown_name
        ).strip()
        parts.append(project_name or unknown_name)
        parts.append(self._document_section_folder(file_info))

        safe_parts: List[str] = []
        for part in parts:
            safe = self.file_utils.sanitize_path_component(part)
            if safe_parts and safe_parts[-1].casefold() == safe.casefold():
                continue
            safe_parts.append(safe)
        self.logger.debug(f"フォルダ階層生成 - パーツ: {safe_parts}")
        return safe_parts

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
        
        # 案件名はFileInfoのmetadataから取得（検索条件ではない）。
        # koji_name は旧履歴・旧テンプレート向けの互換別名として残す。
        koji_name = None
        if file_info.metadata:
            koji_name = (
                file_info.metadata.get("project_name")
                or file_info.metadata.get("koji_name")
            )
        
        if koji_name:
            parts.append(koji_name)
        
        self.logger.debug(f"フォルダ名生成 - パーツ: {parts}")
        
        if not parts:
            self.logger.warning("フォルダ名のパーツが空のため、デフォルトフォルダ名 'その他' を使用します")
            return "その他"
        
        folder_name = "_".join(parts)
        
        # 無効な文字を削除（Windowsのファイル名として使用可能にする）
        folder_name = self.file_utils.sanitize_filename(
            folder_name, max_length=max(200, len(folder_name))
        )
        
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
        return self.file_utils.ensure_unique(file_path, max_path_length=240)
