# -*- coding: utf-8 -*-

"""ファイルダウンロードのオーケストレーション。"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import parse_qs, urlparse

from ..models.download_diagnostics import (
    DownloadIssue,
    DownloadIssueCode,
    DownloadMode,
    DownloadStage,
    IssueSeverity,
    RedownloadPolicy,
)
from ..models.download_result import DownloadResult
from ..models.download_task import DownloadTask
from ..models.file_info import FileInfo
from ..utils.file_utils import FileUtils
from ..utils.http_client import (
    DownloadFileResult,
    DownloadStatus,
    HTTPClient,
)
from ..utils.logger import Logger
from ..utils.naming_template import (
    document_datetime_iso,
    parse_document_datetime,
)
from .html_to_pdf import HtmlToPdfConverter


@dataclass(frozen=True)
class HistoryMatch:
    """検証を通過した保存済みファイルと履歴メタデータ。"""

    path: Path
    size: int
    sha256: str
    processing_mode: DownloadMode
    validation_kind: str
    expected_format: str
    final_url: str = ""
    completed_at: str = ""
    reuse_kind: str = "EXACT_PATH"
    alias_from_path: str = ""
    document_name: str = ""
    document_updated_at: str = ""


@dataclass(frozen=True)
class _HistoryLookup:
    """履歴キーの最新状態と、再利用可能なファイル。"""

    has_record: bool = False
    actual_path: Optional[Path] = None
    match: Optional[HistoryMatch] = None
    invalid_reason: str = ""
    alias_record_required: bool = False


@dataclass(frozen=True)
class _PlannedDownload:
    """履歴を一度だけ走査するために先に確定した保存計画。"""

    file_info: FileInfo
    proposed_path: Optional[Path] = None
    collision_path: Optional[Path] = None
    expected_format: str = ""
    error: Optional[Exception] = None


class _DownloadHistory:
    """URL・希望保存先・期待形式をキーにしたJSON Lines履歴。"""

    FILE_NAME = ".ippi-download-history.jsonl"
    SCHEMA_VERSION = 2

    def __init__(
        self,
        base_dir: Path,
        logger: Logger,
        layout_version: int = 2,
    ):
        self.base_dir = base_dir.resolve()
        self.path = self.base_dir / self.FILE_NAME
        self.logger = logger
        self.layout_version = int(layout_version)
        self._lock = threading.Lock()
        # JSONL全体を常駐させず、今回照合するキーの最新レコードだけを
        # 保持する。ダウンロード前にprepare_lookups()でまとめて構築すれば
        # 履歴サイズではなく今回の対象件数に比例したメモリで済む。
        self._exact_records: Dict[Tuple[str, str, str], Dict[str, object]] = {}
        self._url_format_records: Dict[Tuple[str, str], Dict[str, object]] = {}
        self._prepared_exact_keys: set[Tuple[str, str, str]] = set()
        self._prepared_url_format_keys: set[Tuple[str, str]] = set()

    def _stored_path(self, file_path: Path) -> str:
        resolved = file_path.resolve()
        try:
            return resolved.relative_to(self.base_dir).as_posix()
        except ValueError:
            return str(resolved)

    def stored_path(self, file_path: Path) -> str:
        """保存ルート基準の安全な履歴パスを返す公開補助API。"""

        return self._stored_path(file_path)

    def _lookup_path(self, file_path: Path) -> str:
        """履歴索引用に保存先を正規化する（履歴書込とは独立）。"""
        resolved = file_path.resolve()
        try:
            return resolved.relative_to(self.base_dir).as_posix()
        except ValueError:
            return str(resolved)

    def _actual_path(self, stored_path: str) -> Path:
        candidate = Path(stored_path)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.base_dir / candidate).resolve()
        )
        # 履歴ファイルが改変されても保存ルート外のファイルを読み取らない。
        resolved.relative_to(self.base_dir)
        return resolved

    def actual_path(self, stored_path: str) -> Path:
        """履歴値を保存ルート内の絶対パスへ安全に解決する。"""

        return self._actual_path(stored_path)

    @staticmethod
    def _sha256(file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def sha256(file_path: Path) -> str:
        """大きなファイルを全量保持せずSHA-256を計算する。"""

        return _DownloadHistory._sha256(file_path)

    @staticmethod
    def normalize_expected_format(
        expected_format: str,
        target_path: Path,
    ) -> str:
        """履歴キー用の期待形式を先頭ドット付き小文字へ正規化する。"""
        value = (expected_format or target_path.suffix).strip().lower()
        if value and not value.startswith("."):
            value = "." + value
        return value

    @staticmethod
    def validation_kind(expected_format: str) -> str:
        """期待拡張子から実体検証方式を決定する。"""
        return {
            ".pdf": "PDF",
            ".docx": "OOXML_DOCX",
            ".xlsx": "OOXML_XLSX",
            ".pptx": "OOXML_PPTX",
            ".zip": "ZIP",
            ".doc": "OLE_COMPOUND",
            ".xls": "OLE_COMPOUND",
            ".ppt": "OLE_COMPOUND",
            ".rtf": "RTF",
        }.get(expected_format, "BINARY")

    def _record_target(self, record: Dict[str, object]) -> str:
        stored = str(record.get("target_path") or record["path"])
        return self._stored_path(self._actual_path(stored))

    def _record_expected_format(
        self,
        record: Dict[str, object],
    ) -> str:
        stored = str(record.get("target_path") or record["path"])
        return self.normalize_expected_format(
            str(record.get("expected_format") or ""),
            self._actual_path(stored),
        )

    def _exact_key(
        self,
        url: str,
        target_path: Path,
        expected_format: str,
    ) -> Tuple[str, str, str]:
        return (
            url,
            self._lookup_path(target_path),
            self.normalize_expected_format(expected_format, target_path),
        )

    def _scan_relevant_records(
        self,
        exact_keys: set[Tuple[str, str, str]],
        url_format_keys: set[Tuple[str, str]],
    ) -> None:
        """指定キーだけについてJSONLをストリーム走査する。"""
        if not self.path.exists() or not (exact_keys or url_format_keys):
            return
        relevant_urls = {key[0] for key in exact_keys} | {
            key[0] for key in url_format_keys
        }
        invalid_lines = 0
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        invalid_lines += 1
                        continue
                    if not isinstance(record, dict):
                        continue
                    url = str(record.get("url") or "")
                    if url not in relevant_urls:
                        continue
                    try:
                        record_layout = int(record.get("layout_version", 2))
                        if (
                            self.layout_version >= 3
                            and record_layout != self.layout_version
                        ):
                            continue
                        record_format = self._record_expected_format(record)
                        url_format_key = (url, record_format)
                        if url_format_key in url_format_keys:
                            self._url_format_records[url_format_key] = record
                        exact_key = (
                            url,
                            self._record_target(record),
                            record_format,
                        )
                        if exact_key in exact_keys:
                            self._exact_records[exact_key] = record
                    except (KeyError, TypeError, ValueError, OSError):
                        continue
        except OSError as exc:
            self.logger.warning(f"ダウンロード履歴を読めません: {exc}")
            return
        if invalid_lines:
            self.logger.warning(
                f"不正なダウンロード履歴行を無視します: {self.path} ({invalid_lines}行)"
            )

    def prepare_lookups(
        self,
        exact_lookups: Sequence[Tuple[str, Path, str]],
        url_format_lookups: Sequence[Tuple[str, str]] = (),
    ) -> None:
        """今回必要な履歴キーだけを一度の走査で索引化する。"""
        requested_exact = {
            self._exact_key(url, target_path, expected_format)
            for url, target_path, expected_format in exact_lookups
        }
        requested_url_format = {
            (
                url,
                self.normalize_expected_format(
                    expected_format,
                    Path("file" + expected_format),
                ),
            )
            for url, expected_format in url_format_lookups
        }
        new_exact = requested_exact - self._prepared_exact_keys
        new_url_format = requested_url_format - self._prepared_url_format_keys
        if not new_exact and not new_url_format:
            return
        self._scan_relevant_records(new_exact, new_url_format)
        self._prepared_exact_keys.update(new_exact)
        self._prepared_url_format_keys.update(new_url_format)

    def _latest_record(
        self,
        url: str,
        target_path: Path,
        expected_format: str,
    ) -> Optional[Dict[str, object]]:
        key = self._exact_key(url, target_path, expected_format)
        if key not in self._prepared_exact_keys:
            self.prepare_lookups(((url, target_path, expected_format),))
        return self._exact_records.get(key)

    def _latest_record_for_url_format(
        self,
        url: str,
        expected_format: str,
    ) -> Optional[Dict[str, object]]:
        """保存名を問わず、同じURL・期待形式の最新状態を返す。"""
        normalized_format = self.normalize_expected_format(
            expected_format,
            Path("file" + expected_format),
        )
        key = (url, normalized_format)
        if key not in self._prepared_url_format_keys:
            self.prepare_lookups((), (key,))
        return self._url_format_records.get(key)

    @staticmethod
    def _is_fresh_enough(
        record: Dict[str, object],
        document_updated_at: object,
        *,
        require_revision: bool,
    ) -> bool:
        """取得完了日時がHPの文書更新日時以降かを判定する。"""
        source_updated_at = parse_document_datetime(document_updated_at)
        if source_updated_at is None:
            return not require_revision
        completed_at = parse_document_datetime(record.get("completed_at"))
        return completed_at is not None and completed_at >= source_updated_at

    def _reuse_kind_from_record(
        self,
        record: Dict[str, object],
        target_path: Path,
        actual_path: Path,
    ) -> str:
        value = str(record.get("reuse_kind") or "").upper()
        if value in {"EXACT_PATH", "LEGACY_PATH_ALIAS"}:
            return value
        if self._stored_path(actual_path) == self._stored_path(target_path):
            return "EXACT_PATH"
        return "LEGACY_PATH_ALIAS"

    @staticmethod
    def _mode_from_record(record: Dict[str, object]) -> DownloadMode:
        try:
            return DownloadMode(
                str(record.get("processing_mode") or DownloadMode.DIRECT.value)
            )
        except ValueError:
            return DownloadMode.DIRECT

    def _validate_file(
        self,
        path: Path,
        *,
        expected_size: int,
        expected_sha256: str,
        expected_format: str,
    ) -> Tuple[bool, str]:
        """履歴値と現在の実体形式を照合する。"""
        try:
            if not path.is_file():
                return False, "保存済みファイルが存在しません"
            actual_size = path.stat().st_size
            if actual_size <= 0:
                return False, "保存済みファイルが空です"
            if actual_size != expected_size:
                return (
                    False,
                    "保存済みファイルのサイズが履歴と一致しません",
                )
            if self._sha256(path) != expected_sha256:
                return (
                    False,
                    "保存済みファイルのSHA-256が履歴と一致しません",
                )

            with path.open("rb") as stream:
                prefix = stream.read(8192)
                if expected_format == ".pdf":
                    if not prefix.startswith(b"%PDF-"):
                        return False, "保存済みPDFの署名が不正です"
                    stream.seek(max(0, actual_size - 8192))
                    if not stream.read().rstrip().endswith(b"%%EOF"):
                        return False, "保存済みPDFの終端が不正です"
                elif not HTTPClient._matches_expected_signature(
                    prefix,
                    Path("file" + expected_format),
                ):
                    return False, "保存済みファイルの署名が不正です"
                elif expected_format not in {
                    ".docx",
                    ".xlsx",
                    ".pptx",
                } and HTTPClient._looks_like_error_payload(prefix):
                    return False, "保存済みファイルがHTML等のエラー応答です"

            if expected_format in {".docx", ".xlsx", ".pptx"}:
                ooxml_error = HTTPClient._validate_ooxml_container(
                    path,
                    Path("file" + expected_format),
                )
                if ooxml_error:
                    return False, ooxml_error
            return True, ""
        except OSError as exc:
            return False, f"保存済みファイルを検証できません: {exc}"

    def validate_file(
        self,
        path: Path,
        *,
        expected_size: int,
        expected_sha256: str,
        expected_format: str,
    ) -> Tuple[bool, str]:
        """履歴値に対してサイズ・hash・実形式を再検証する。"""

        normalized_format = self.normalize_expected_format(
            expected_format,
            path,
        )
        return self._validate_file(
            path,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            expected_format=normalized_format,
        )

    def lookup(
        self,
        url: str,
        target_path: Path,
        expected_format: str = "",
        document_updated_at: object = "",
        allow_legacy_alias: bool = True,
        exact_checked: bool = False,
    ) -> _HistoryLookup:
        """同一キー、続いて条件を満たす旧名称履歴を評価する。"""
        normalized_format = self.normalize_expected_format(
            expected_format,
            target_path,
        )
        record = (
            None
            if exact_checked
            else self._latest_record(
                url,
                target_path,
                normalized_format,
            )
        )
        if record is None:
            if not allow_legacy_alias:
                return _HistoryLookup()
            if parse_document_datetime(document_updated_at) is None:
                return _HistoryLookup()
            record = self._latest_record_for_url_format(
                url,
                normalized_format,
            )
            if record is None:
                return _HistoryLookup()
            # 旧名称ファイルは、HPの更新日時を取得でき、かつ実取得が
            # その日時以降である場合に限って新しい希望名へ関連付ける。
            if not self._is_fresh_enough(
                record,
                document_updated_at,
                require_revision=True,
            ):
                return _HistoryLookup()
            is_legacy_alias = True
        else:
            is_legacy_alias = False

        actual_path: Optional[Path] = None
        try:
            actual_path = self._actual_path(str(record["path"]))
        except (KeyError, TypeError, ValueError, OSError):
            reason = "履歴の実保存先が不正です"
            self._log_invalid(url, target_path, reason)
            return _HistoryLookup(
                not is_legacy_alias,
                invalid_reason=reason,
            )

        # v1にはstatusがないため、従来の成功履歴として厳格に再検証する。
        status = str(record.get("status") or "SUCCESS").upper()
        if status != "SUCCESS":
            return _HistoryLookup(
                not is_legacy_alias,
                actual_path=actual_path if not is_legacy_alias else None,
            )

        if not self._is_fresh_enough(
            record,
            document_updated_at,
            require_revision=is_legacy_alias,
        ):
            return _HistoryLookup(
                not is_legacy_alias,
                actual_path=actual_path if not is_legacy_alias else None,
            )

        try:
            expected_size = int(record["size"])
            expected_sha256 = str(record["sha256"])
        except (KeyError, TypeError, ValueError):
            reason = "履歴のサイズまたはSHA-256が不正です"
            self._log_invalid(url, target_path, reason)
            return _HistoryLookup(
                not is_legacy_alias,
                actual_path=actual_path,
                invalid_reason=reason,
            )

        valid, reason = self._validate_file(
            actual_path,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            expected_format=normalized_format,
        )
        if not valid:
            self._log_invalid(url, target_path, reason)
            return _HistoryLookup(
                not is_legacy_alias,
                actual_path=actual_path,
                invalid_reason=reason,
            )

        reuse_kind = (
            "LEGACY_PATH_ALIAS"
            if is_legacy_alias
            else self._reuse_kind_from_record(
                record,
                target_path,
                actual_path,
            )
        )

        return _HistoryLookup(
            has_record=True,
            actual_path=actual_path,
            match=HistoryMatch(
                path=actual_path,
                size=expected_size,
                sha256=expected_sha256,
                processing_mode=self._mode_from_record(record),
                validation_kind=str(
                    record.get("validation_kind")
                    or self.validation_kind(normalized_format)
                ),
                expected_format=normalized_format,
                final_url=str(record.get("final_url") or url),
                completed_at=str(record.get("completed_at") or ""),
                reuse_kind=reuse_kind,
                alias_from_path=str(
                    record.get("alias_from_path")
                    or (
                        self._stored_path(actual_path)
                        if reuse_kind == "LEGACY_PATH_ALIAS"
                        else ""
                    )
                ),
                document_name=str(record.get("document_name") or ""),
                document_updated_at=(
                    document_datetime_iso(document_updated_at)
                    or str(record.get("document_updated_at") or "")
                ),
            ),
            alias_record_required=is_legacy_alias,
        )

    def _log_invalid(
        self,
        url: str,
        target_path: Path,
        reason: str,
    ) -> None:
        payload = {
            "reason_code": DownloadIssueCode.HISTORY_INVALID.value,
            "reason": reason,
            "url": url,
            "target_path": str(target_path),
        }
        self.logger.warning(
            "download.history.invalid "
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )

    def find_valid(
        self,
        url: str,
        preferred_path: Path,
        expected_format: str = "",
    ) -> Optional[HistoryMatch]:
        """履歴と実ファイルが完全一致する最新の成功結果を返す。"""
        return self.lookup(url, preferred_path, expected_format).match

    def append_record(
        self,
        record: Mapping[str, object],
        *,
        durable: bool = False,
    ) -> None:
        """検証済みレコードをJSONLへ追記する。

        再分類などファイル移動と組み合わせる処理は ``durable=True`` を
        指定し、journalを完了する前にOSへflushする。
        """

        if not isinstance(record, Mapping):
            raise TypeError("履歴レコードはMappingで指定してください")
        normalized_record = dict(record)
        line = json.dumps(
            normalized_record,
            ensure_ascii=False,
            sort_keys=True,
        )
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")
                stream.flush()
                if durable:
                    os.fsync(stream.fileno())
            # 今回準備済みのキーなら、追記結果を直ちに最新状態へ反映する。
            try:
                url = str(normalized_record.get("url") or "")
                expected_format = self._record_expected_format(normalized_record)
                exact_key = (
                    url,
                    self._record_target(normalized_record),
                    expected_format,
                )
                if exact_key in self._prepared_exact_keys:
                    self._exact_records[exact_key] = normalized_record
                url_format_key = (url, expected_format)
                if url_format_key in self._prepared_url_format_keys:
                    self._url_format_records[url_format_key] = normalized_record
            except (KeyError, TypeError, ValueError, OSError):
                pass

    def _write_record(self, record: Dict[str, object]) -> None:
        """旧内部呼び出しを公開追記APIへ委譲する。"""

        self.append_record(record)

    def _layout_record_fields(
        self,
        history_metadata: Optional[Mapping[str, object]],
    ) -> Dict[str, object]:
        """保存構成と安全に抽出済みの案件情報を履歴項目へ変換する。"""
        fields: Dict[str, object] = {
            "layout_version": self.layout_version,
        }
        if not history_metadata:
            return fields
        agency_path = history_metadata.get("agency_path")
        if isinstance(agency_path, Mapping):
            fields["agency_path"] = dict(agency_path)
        for key in (
            "run_kind",
            "schedule_id",
            "storage_key",
            "office_name",
            "agency_id",
            "project_name",
            "search_target",
        ):
            value = str(history_metadata.get(key) or "").strip()
            if value:
                fields[key] = value
        return fields

    def append_success(
        self,
        url: str,
        target_path: Path,
        actual_path: Path,
        size: int,
        sha256: str,
        processing_mode: DownloadMode = DownloadMode.DIRECT,
        final_url: str = "",
        expected_format: str = "",
        *,
        completed_at: str = "",
        reuse_kind: str = "EXACT_PATH",
        alias_from_path: str = "",
        document_name: str = "",
        document_updated_at: object = "",
        document_id: str = "",
        history_metadata: Optional[Mapping[str, object]] = None,
    ) -> None:
        """確定済みファイルをv2成功履歴へ追記する。"""
        try:
            normalized_format = self.normalize_expected_format(
                expected_format,
                target_path,
            )
            record: Dict[str, object] = {
                "schema_version": self.SCHEMA_VERSION,
                "url": url,
                "target_path": self._stored_path(target_path),
                "path": self._stored_path(actual_path),
                "expected_format": normalized_format,
                "status": "SUCCESS",
                "processing_mode": processing_mode.value,
                "validation_kind": self.validation_kind(normalized_format),
                "reason_code": "",
                "final_url": final_url or url,
                "size": size,
                "sha256": sha256,
                "completed_at": completed_at or datetime.now(timezone.utc).isoformat(),
                "reuse_kind": reuse_kind,
                "alias_from_path": alias_from_path,
                "document_name": document_name,
                "document_updated_at": document_datetime_iso(document_updated_at),
                "document_id": document_id,
            }
            record.update(self._layout_record_fields(history_metadata))
            self._write_record(record)
        except Exception as exc:
            # ファイル本体は正常に確定済みなので、履歴失敗で処理全体を
            # 失敗にしない。
            self.logger.warning(f"ダウンロード履歴を保存できません: {exc}")

    def append(
        self,
        url: str,
        file_path: Path,
        size: int,
        sha256: str,
        *,
        target_path: Optional[Path] = None,
        processing_mode: DownloadMode = DownloadMode.DIRECT,
        final_url: str = "",
        expected_format: str = "",
    ) -> None:
        """旧呼び出し互換の成功履歴追記API。"""
        self.append_success(
            url,
            target_path or file_path,
            file_path,
            size,
            sha256,
            processing_mode,
            final_url,
            expected_format,
        )

    def append_terminal(
        self,
        url: str,
        target_path: Path,
        actual_path: Path,
        status: str,
        expected_format: str,
        processing_mode: DownloadMode,
        reason_code: str,
        final_url: str = "",
        *,
        document_name: str = "",
        document_updated_at: object = "",
        document_id: str = "",
        history_metadata: Optional[Mapping[str, object]] = None,
    ) -> None:
        """失敗・キャンセルを記録し、古い成功履歴を遮断する。"""
        terminal_status = status.upper()
        if terminal_status not in {"FAILED", "CANCELLED"}:
            raise ValueError("履歴の終端状態はFAILED/CANCELLEDのみです")
        try:
            normalized_format = self.normalize_expected_format(
                expected_format,
                target_path,
            )
            record: Dict[str, object] = {
                "schema_version": self.SCHEMA_VERSION,
                "url": url,
                "target_path": self._stored_path(target_path),
                "path": self._stored_path(actual_path),
                "expected_format": normalized_format,
                "status": terminal_status,
                "processing_mode": processing_mode.value,
                "validation_kind": self.validation_kind(normalized_format),
                "reason_code": reason_code,
                "final_url": final_url or url,
                "size": 0,
                "sha256": "",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "reuse_kind": "",
                "alias_from_path": "",
                "document_name": document_name,
                "document_updated_at": document_datetime_iso(document_updated_at),
                "document_id": document_id,
            }
            record.update(self._layout_record_fields(history_metadata))
            self._write_record(record)
        except Exception as exc:
            self.logger.warning(f"ダウンロード履歴を保存できません: {exc}")


# 再分類・保守処理でも、通常ダウンロードと同じ履歴キー・形式検証を
# 使用できるようにする。旧private名は既存テストと内部互換のため維持する。
DownloadHistory = _DownloadHistory


class Downloader:
    """複数ファイルを安全にダウンロードする。"""

    def __init__(
        self,
        http_client: HTTPClient,
        logger: Optional[Logger] = None,
        html_to_pdf_converter: Optional[HtmlToPdfConverter] = None,
    ):
        self.http_client = http_client
        self.logger = logger or Logger()
        self.file_utils = FileUtils()
        self.html_to_pdf_converter = html_to_pdf_converter or HtmlToPdfConverter(
            self.logger
        )
        self._history: Optional[_DownloadHistory] = None
        self.last_download_result: Optional[DownloadFileResult] = None

    @staticmethod
    def _sha256(file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _document_history_fields(
        file_info: FileInfo,
    ) -> Tuple[str, object, str]:
        """履歴へ保存する文書固有メタデータを得る。"""
        metadata = file_info.metadata or {}
        document_name = str(metadata.get("document_name") or file_info.filename)
        document_updated_at = metadata.get("document_updated_at") or ""
        document_id = str(
            metadata.get("document_id")
            or metadata.get("bunsho_kanri_id")
            or metadata.get("BunshoKanriId")
            or ""
        ).strip()
        if not document_id:
            try:
                for key, values in parse_qs(urlparse(file_info.url).query).items():
                    if key.lower() == "bunshokanriid" and values:
                        document_id = str(values[0]).strip()
                        break
            except (TypeError, ValueError):
                pass
        return document_name, document_updated_at, document_id

    @staticmethod
    def _normalize_history_agency_path(value: object) -> Dict[str, object]:
        """履歴へ書けるプリミティブ型だけでagency_pathを複製する。"""
        if not isinstance(value, Mapping):
            return {}
        raw_segments = value.get("segments")
        if not isinstance(raw_segments, list):
            return {}
        segments: List[Dict[str, str]] = []
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, Mapping):
                continue
            level = str(raw_segment.get("level") or "").strip()
            label = str(raw_segment.get("label") or "").strip()
            if not level or not label:
                continue
            segments.append(
                {
                    "level": level,
                    "label": label,
                    "code": str(raw_segment.get("code") or "").strip(),
                }
            )

        resolution = value.get("resolution", "")
        if isinstance(resolution, Mapping):
            normalized_resolution: object = {
                "status": str(resolution.get("status") or "").strip(),
                "method": str(resolution.get("method") or "").strip(),
                "reason": str(resolution.get("reason") or "").strip(),
                "reason_code": str(resolution.get("reason_code") or "").strip(),
            }
        else:
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

    def _history_layout_metadata(
        self,
        file_info: FileInfo,
        naming: object,
        layout_version: int,
    ) -> Dict[str, object]:
        """layout v3履歴へ保存する分類・実行補助情報を抽出する。"""
        metadata = file_info.metadata or {}
        result: Dict[str, object] = {}
        project_name = str(
            metadata.get("project_name") or metadata.get("koji_name") or ""
        ).strip()
        search_target = str(metadata.get("search_target") or "").strip()
        if project_name:
            result["project_name"] = project_name
        if search_target:
            result["search_target"] = search_target
        if layout_version < 3:
            return result
        agency_value: object = metadata.get("agency_path")
        agency_getter = getattr(naming, "generate_agency_path", None)
        if callable(agency_getter):
            try:
                agency_value = agency_getter(file_info)
            except Exception as exc:
                self.logger.warning(f"履歴用の発注機関階層を取得できません: {exc}")

        agency_path = self._normalize_history_agency_path(agency_value)
        if agency_path:
            result["agency_path"] = agency_path
        for source_key, target_key in (
            ("run_kind", "run_kind"),
            ("schedule_id", "schedule_id"),
            ("storage_key", "storage_key"),
            ("schedule_storage_key", "storage_key"),
            ("office_name", "office_name"),
            ("agency_id", "agency_id"),
            ("project_name", "project_name"),
            ("search_target", "search_target"),
        ):
            value = str(metadata.get(source_key) or "").strip()
            if value and target_key not in result:
                result[target_key] = value
        return result

    def _build_download_path(
        self,
        save_dir_path: Path,
        folder: Union[str, Sequence[str]],
        filename: str,
    ) -> Path:
        """旧単一フォルダとv3複数階層の双方から保存先を作る。"""
        if isinstance(folder, str):
            return self.file_utils.build_safe_download_path(
                save_dir_path,
                folder,
                filename,
            )
        return self.file_utils.build_safe_download_path_parts(
            save_dir_path,
            folder,
            filename,
        )

    @staticmethod
    def _requires_legacy_path_redownload(
        history_match: HistoryMatch,
        proposed_path: Path,
        save_dir_path: Path,
        layout_version: int,
    ) -> bool:
        """旧未解決階層から確定階層へ変わった文書は再取得する。

        旧ファイルは移動・削除せず、正しい現在レイアウトへ新しく保存する。
        単なる命名規則変更によるエイリアス再利用は従来どおり維持する。
        """
        if layout_version < 3 or history_match.reuse_kind != "LEGACY_PATH_ALIAS":
            return False
        try:
            root = save_dir_path.resolve()
            old_relative = history_match.path.resolve().relative_to(root)
            new_relative = proposed_path.resolve().relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return False
        if not old_relative.parts or not new_relative.parts:
            return False
        unresolved = "99_分類未解決".casefold()
        return (
            old_relative.parts[0].casefold() == unresolved
            and new_relative.parts[0].casefold() != unresolved
        )

    def _collision_path(
        self,
        save_dir_path: Path,
        folder: Union[str, Sequence[str]],
        filename: str,
        file_info: FileInfo,
        naming,
    ) -> Path:
        """衝突時は連番でなく安定した文書IDをファイル名へ付ける。"""
        add_suffix = getattr(naming, "add_document_id_suffix", None)
        if callable(add_suffix):
            collision_name = add_suffix(filename, file_info)
        else:
            path = Path(filename)
            digest = hashlib.sha256(file_info.url.encode("utf-8")).hexdigest()[:8]
            collision_name = f"{path.stem}_{digest}{path.suffix}"
        return self._build_download_path(
            save_dir_path,
            folder,
            collision_name,
        )

    def download_file(
        self,
        file_info: FileInfo,
        save_path: str,
        progress_callback: Optional[Callable] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_retries: int = 3,
    ) -> DownloadFileResult:
        """単一ファイルをダウンロードし、詳細結果を返す。

        戻り値は真偽値評価に対応するため、従来の呼び出しも維持される。
        """
        save_path_obj = Path(save_path)
        try:
            save_path_obj.parent.mkdir(parents=True, exist_ok=True)
            referer = file_info.page_url or None
            metadata = file_info.metadata or {}
            http_options = {}
            if file_info.allow_html_to_pdf:
                http_options = {
                    "allow_html_to_pdf": True,
                    "html_to_pdf_converter": self.html_to_pdf_converter,
                    "document_name": str(
                        metadata.get("document_name") or file_info.filename
                    ),
                    "project_name": str(
                        metadata.get("project_name") or metadata.get("koji_name") or ""
                    ),
                    "run_id": str(metadata.get("run_id") or ""),
                    "document_id": str(
                        metadata.get("document_id")
                        or metadata.get("bunsho_kanri_id")
                        or metadata.get("BunshoKanriId")
                        or ""
                    ),
                }
            raw_result = self.http_client.download_file(
                file_info.url,
                save_path,
                progress_callback,
                max_retries=max_retries,
                referer=referer,
                cancel_check=cancel_check,
                **http_options,
            )

            # 旧HTTPClientモック（boolを返す）との互換処理。
            if isinstance(raw_result, DownloadFileResult):
                result = raw_result
            elif raw_result:
                size = save_path_obj.stat().st_size if save_path_obj.exists() else 0
                sha256 = self._sha256(save_path_obj) if size else ""
                result = DownloadFileResult(
                    DownloadStatus.SUCCESS,
                    file_info.url,
                    save_path,
                    bytes_written=size,
                    sha256=sha256,
                    attempts=1,
                )
            else:
                result = DownloadFileResult(
                    DownloadStatus.FAILED,
                    file_info.url,
                    save_path,
                    attempts=1,
                    error="ダウンロードに失敗しました",
                    issues=(
                        DownloadIssue(
                            DownloadIssueCode.UNKNOWN,
                            DownloadStage.FETCH,
                            "ダウンロードに失敗しました",
                        ),
                    ),
                )
        except Exception as exc:
            message = f"ダウンロード処理で予期しないエラーが発生しました: {exc}"
            result = DownloadFileResult(
                DownloadStatus.FAILED,
                file_info.url,
                save_path,
                error=message,
                processing_mode=(
                    DownloadMode.HTML_TO_PDF
                    if file_info.allow_html_to_pdf
                    else DownloadMode.DIRECT
                ),
                issues=(
                    DownloadIssue(
                        DownloadIssueCode.UNKNOWN,
                        DownloadStage.FETCH,
                        message,
                    ),
                ),
            )

        self.last_download_result = result
        self._log_file_result(file_info, result)
        return result

    def _log_file_result(
        self,
        file_info: FileInfo,
        result: DownloadFileResult,
    ) -> None:
        """機密情報を含めず、ファイル単位の最終結果を一行で記録する。"""
        metadata = file_info.metadata or {}
        issue = result.primary_issue
        payload = {
            "status": result.status.value,
            "project_name": str(
                metadata.get("project_name") or metadata.get("koji_name") or ""
            ),
            "document_name": str(metadata.get("document_name") or file_info.filename),
            "stage": issue.stage.value if issue else "COMMIT",
            "reason_code": issue.code.value if issue else "",
            "reason": issue.message if issue else "",
            "issue_details": dict(issue.details) if issue else {},
            "url": result.final_url or result.url,
            "save_path": result.save_path,
            "http_status": result.http_status,
            "content_type": result.content_type,
            "content_length": result.content_length,
            "attempts": result.attempts,
            "mode": result.processing_mode.value,
            "processor": result.processor,
            "bytes": result.bytes_written,
            "sha256": result.sha256,
        }
        message = "download.file.final " + json.dumps(
            payload, ensure_ascii=False, sort_keys=True
        )
        if result.success or result.cancelled:
            self.logger.info(message)
        else:
            self.logger.error(message)

    def _log_non_transfer_task(
        self,
        task: DownloadTask,
        *,
        stage: DownloadStage,
        reason_code: str,
        reason: str,
        history_match: Optional[HistoryMatch] = None,
    ) -> None:
        """HTTP取得を行わなかった終端タスクを同じスキーマで一行記録する。"""
        metadata = task.file_info.metadata or {}
        issue = next(
            (item for item in task.issues if item.severity == IssueSeverity.ERROR),
            task.issues[0] if task.issues else None,
        )
        payload = {
            "status": task.status.upper(),
            "project_name": str(
                metadata.get("project_name") or metadata.get("koji_name") or ""
            ),
            "document_name": str(
                metadata.get("document_name") or task.file_info.filename
            ),
            "stage": issue.stage.value if issue else stage.value,
            "reason_code": issue.code.value if issue else reason_code,
            "reason": issue.message if issue else reason,
            "issue_details": dict(issue.details) if issue else {},
            "url": task.file_info.url,
            "save_path": task.local_path,
            "http_status": None,
            "content_type": None,
            "content_length": None,
            "attempts": 0,
            "mode": task.processing_mode.value,
            "processor": "",
            "bytes": (
                history_match.size if history_match is not None else task.bytes_written
            ),
            "sha256": (
                history_match.sha256 if history_match is not None else task.sha256
            ),
        }
        if task.reuse_kind:
            payload["reuse_kind"] = task.reuse_kind
        if history_match is not None:
            payload.update(
                {
                    "validation_kind": history_match.validation_kind,
                    "http_request_performed": False,
                    "alias_from_path": history_match.alias_from_path,
                    "document_updated_at": (history_match.document_updated_at),
                }
            )
        message = "download.file.final " + json.dumps(
            payload, ensure_ascii=False, sort_keys=True
        )
        if task.status == "failed":
            self.logger.error(message)
        else:
            self.logger.info(message)

    @staticmethod
    def _callback_allows_continue(
        progress_callback: Optional[Callable[[int, int, str], Optional[bool]]],
        current: int,
        total: int,
        filename: str,
    ) -> bool:
        if progress_callback is None:
            return True
        try:
            return progress_callback(current, total, filename) is not False
        except Exception:
            # 表示コールバックの障害でダウンロードを止めない。
            return True

    def _add_cancelled_tasks(
        self,
        result: DownloadResult,
        file_list: List[FileInfo],
        start_index: int,
        task_result_callback: Optional[Callable[[int, int, DownloadTask], None]] = None,
    ) -> None:
        total = len(file_list)
        for index, file_info in enumerate(
            file_list[start_index:],
            start=start_index,
        ):
            task = DownloadTask(file_info=file_info, local_path="")
            issue = DownloadIssue(
                DownloadIssueCode.CANCELLED,
                DownloadStage.FETCH,
                "ダウンロード開始前にキャンセルされました",
            )
            task.mark_cancelled(issue.message, (issue,))
            result.add_task(task)
            self._log_non_transfer_task(
                task,
                stage=DownloadStage.FETCH,
                reason_code=issue.code.value,
                reason=issue.message,
            )
            self._notify_task_result(
                task_result_callback,
                index + 1,
                total,
                task,
            )
        if result.tasks:
            result.update_status(result.tasks[-1])

    def _notify_task_result(
        self,
        callback: Optional[Callable[[int, int, DownloadTask], None]],
        current: int,
        total: int,
        task: DownloadTask,
    ) -> None:
        """結果通知の障害でダウンロード本体を失敗させない。"""
        if callback is None:
            return
        try:
            callback(current, total, task)
        except Exception as exc:
            self.logger.warning(f"タスク結果コールバックを実行できません: {exc}")

    def _plan_downloads(
        self,
        file_list: Sequence[FileInfo],
        save_dir_path: Path,
        naming: object,
        layout_version: int,
    ) -> List[_PlannedDownload]:
        """命名結果と履歴照合キーをHTTP開始前に確定する。"""
        if self._history is None:
            raise RuntimeError("ダウンロード履歴が初期化されていません")
        planned: List[_PlannedDownload] = []
        claimed_targets: Dict[str, str] = {}
        exact_lookups: List[Tuple[str, Path, str]] = []
        url_format_lookups: List[Tuple[str, str]] = []

        for index, file_info in enumerate(file_list):
            try:
                _, document_updated_at, _ = self._document_history_fields(file_info)
                folder_parts_getter = getattr(
                    naming,
                    "generate_folder_parts",
                    None,
                )
                if layout_version >= 3 and callable(folder_parts_getter):
                    generated_parts = folder_parts_getter(file_info)
                    if isinstance(generated_parts, str):
                        file_folder: Union[str, Sequence[str]] = [generated_parts]
                    else:
                        file_folder = list(generated_parts or [])
                    if not file_folder:
                        file_folder = [naming.generate_folder_name(file_info)]
                else:
                    file_folder = naming.generate_folder_name(file_info)
                filename = naming.generate_filename(
                    file_info,
                    file_info.metadata,
                    index,
                )
                proposed_path = self._build_download_path(
                    save_dir_path,
                    file_folder,
                    filename,
                )

                # 同一実行内の同名異URLは、従来と同じ安定文書ID名へ送る。
                target_key = str(proposed_path.resolve()).casefold()
                if (
                    target_key in claimed_targets
                    and claimed_targets[target_key] != file_info.url
                ):
                    proposed_path = self._collision_path(
                        save_dir_path,
                        file_folder,
                        filename,
                        file_info,
                        naming,
                    )
                    target_key = str(proposed_path.resolve()).casefold()
                claimed_targets[target_key] = file_info.url

                collision_path = self._collision_path(
                    save_dir_path,
                    file_folder,
                    filename,
                    file_info,
                    naming,
                )
                expected_format = self._history.normalize_expected_format(
                    file_info.get_file_extension(),
                    proposed_path,
                )
                planned.append(
                    _PlannedDownload(
                        file_info=file_info,
                        proposed_path=proposed_path,
                        collision_path=collision_path,
                        expected_format=expected_format,
                    )
                )
                exact_lookups.append((file_info.url, proposed_path, expected_format))
                if collision_path != proposed_path:
                    exact_lookups.append(
                        (file_info.url, collision_path, expected_format)
                    )
                if parse_document_datetime(document_updated_at) is not None:
                    url_format_lookups.append((file_info.url, expected_format))
            except Exception as exc:
                # 命名エラーは従来どおりそのファイルだけを失敗にし、
                # キャンセル判定と通知順も本処理ループ側で維持する。
                planned.append(
                    _PlannedDownload(
                        file_info=file_info,
                        error=exc,
                    )
                )

        self._history.prepare_lookups(
            exact_lookups,
            url_format_lookups,
        )
        return planned

    def download_files(
        self,
        file_list: List[FileInfo],
        save_dir: str,
        naming,
        progress_callback: Optional[Callable[[int, int, str], Optional[bool]]] = None,
        folder_name: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        task_result_callback: Optional[Callable[[int, int, DownloadTask], None]] = None,
        redownload_policy: RedownloadPolicy = (RedownloadPolicy.REUSE_VERIFIED),
        layout_version: int = 2,
    ) -> DownloadResult:
        """複数ファイルをダウンロードする。"""
        del folder_name  # 既存API互換。フォルダ名はNamingが決定する。
        redownload_policy = RedownloadPolicy(redownload_policy)
        layout_version = int(layout_version)
        result = DownloadResult(total=len(file_list))
        save_dir_path = Path(save_dir)
        save_dir_path.mkdir(parents=True, exist_ok=True)
        self._history = _DownloadHistory(
            save_dir_path,
            self.logger,
            layout_version=layout_version,
        )
        planned_downloads = self._plan_downloads(
            file_list,
            save_dir_path,
            naming,
            layout_version,
        )

        for index, plan in enumerate(planned_downloads):
            file_info = plan.file_info
            if (
                cancel_check is not None and cancel_check()
            ) or not self._callback_allows_continue(
                progress_callback,
                index,
                len(file_list),
                file_info.filename,
            ):
                self.logger.info("ダウンロードがキャンセルされました")
                self._add_cancelled_tasks(
                    result,
                    file_list,
                    index,
                    task_result_callback,
                )
                break

            try:
                if plan.error is not None:
                    raise plan.error
                (
                    document_name,
                    document_updated_at,
                    document_id,
                ) = self._document_history_fields(file_info)
                proposed_path = plan.proposed_path
                collision_path = plan.collision_path
                if proposed_path is None or collision_path is None:
                    raise RuntimeError("保存計画に保存先がありません")
                history_metadata = self._history_layout_metadata(
                    file_info,
                    naming,
                    layout_version,
                )
                expected_format = plan.expected_format

                # 物理ファイルがある場合はまず同一希望名の履歴だけを確認する。
                # 履歴のない別文書を旧名称エイリアスで上書きしない。
                history_lookup = self._history.lookup(
                    file_info.url,
                    proposed_path,
                    expected_format,
                    document_updated_at,
                    allow_legacy_alias=False,
                )
                if (
                    not history_lookup.has_record
                    and history_lookup.match is None
                    and not history_lookup.invalid_reason
                    and proposed_path.exists()
                ):
                    proposed_path = collision_path
                    history_lookup = self._history.lookup(
                        file_info.url,
                        proposed_path,
                        expected_format,
                        document_updated_at,
                        allow_legacy_alias=False,
                    )
                if (
                    not history_lookup.has_record
                    and history_lookup.match is None
                    and not history_lookup.invalid_reason
                    and parse_document_datetime(document_updated_at) is not None
                ):
                    history_lookup = self._history.lookup(
                        file_info.url,
                        proposed_path,
                        expected_format,
                        document_updated_at,
                        allow_legacy_alias=True,
                        exact_checked=True,
                    )
                history_match = history_lookup.match
                history_issue: Optional[DownloadIssue] = None
                legacy_path_redownload = bool(
                    history_match is not None
                    and self._requires_legacy_path_redownload(
                        history_match,
                        proposed_path,
                        save_dir_path,
                        layout_version,
                    )
                )
                if legacy_path_redownload and history_match is not None:
                    history_issue = DownloadIssue(
                        DownloadIssueCode.LEGACY_PATH_REDOWNLOAD,
                        DownloadStage.VALIDATE,
                        (
                            "旧分類場所の保存済みファイルを保持し、"
                            "分類済みの保存先へ再取得します"
                        ),
                        IssueSeverity.WARNING,
                        {
                            "existing_file_preserved": True,
                            "previous_path": str(history_match.path),
                            "target_path": str(proposed_path),
                        },
                    )
                    self.logger.warning(
                        "download.history.legacy_path_redownload "
                        + json.dumps(
                            {
                                "reason_code": (
                                    DownloadIssueCode.LEGACY_PATH_REDOWNLOAD.value
                                ),
                                "reason": history_issue.message,
                                "url": file_info.url,
                                "previous_path": str(history_match.path),
                                "target_path": str(proposed_path),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                if history_lookup.invalid_reason:
                    history_issue = DownloadIssue(
                        DownloadIssueCode.HISTORY_INVALID,
                        DownloadStage.VALIDATE,
                        history_lookup.invalid_reason,
                        IssueSeverity.WARNING,
                        {
                            "existing_file_preserved": bool(
                                history_lookup.actual_path
                                and history_lookup.actual_path.is_file()
                            ),
                            "redownload_policy": redownload_policy.value,
                        },
                    )

                if (
                    history_match is not None
                    and not legacy_path_redownload
                    and redownload_policy == RedownloadPolicy.REUSE_VERIFIED
                ):
                    if history_lookup.alias_record_required:
                        self._history.append_success(
                            file_info.url,
                            proposed_path,
                            history_match.path,
                            history_match.size,
                            history_match.sha256,
                            history_match.processing_mode,
                            history_match.final_url,
                            expected_format,
                            completed_at=history_match.completed_at,
                            reuse_kind="LEGACY_PATH_ALIAS",
                            alias_from_path=self._history._stored_path(
                                history_match.path
                            ),
                            document_name=document_name,
                            document_updated_at=document_updated_at,
                            document_id=document_id,
                            history_metadata=history_metadata,
                        )
                    self.logger.info(
                        (
                            "保存済み確認（旧名称を再利用）: "
                            if history_match.reuse_kind == "LEGACY_PATH_ALIAS"
                            else "保存済み確認（履歴一致）: "
                        )
                        + str(history_match.path)
                    )
                    task = DownloadTask(
                        file_info=file_info,
                        local_path=str(history_match.path),
                        status="skipped",
                        processing_mode=history_match.processing_mode,
                        bytes_written=history_match.size,
                        sha256=history_match.sha256,
                        validation_kind=history_match.validation_kind,
                        reuse_kind=history_match.reuse_kind,
                    )
                    result.add_task(task)
                    result.update_status(task)
                    self._log_non_transfer_task(
                        task,
                        stage=DownloadStage.COMMIT,
                        reason_code="HISTORY_MATCH",
                        reason=(
                            "旧名称の履歴と保存済みファイルを検証し、"
                            "新しい予定名へ関連付けて再利用しました"
                            if history_match.reuse_kind == "LEGACY_PATH_ALIAS"
                            else "履歴と保存済みファイルを検証し、"
                            "既存ファイルを再利用しました"
                        ),
                        history_match=history_match,
                    )
                    self._notify_task_result(
                        task_result_callback,
                        index + 1,
                        len(file_list),
                        task,
                    )
                    continue

                if legacy_path_redownload and proposed_path.exists():
                    # 分類済み予定先に履歴で確認できないファイルがある場合は
                    # 上書きせず、安定文書ID名または一意名へ保存する。
                    save_path = naming.ensure_unique(str(collision_path))
                elif (
                    history_lookup.has_record
                    and history_lookup.actual_path is not None
                    and not (
                        history_match is not None
                        and history_match.reuse_kind == "LEGACY_PATH_ALIAS"
                    )
                ):
                    # 同一キーの再取得は同じ正式名へ原子的に確定する。
                    # HTTPClientは失敗・キャンセル時に.partだけを削除する。
                    save_path = str(history_lookup.actual_path)
                elif history_lookup.has_record:
                    save_path = str(proposed_path)
                else:
                    # 履歴のない既存ファイルは上書きせず、一意名へ退避する。
                    save_path = naming.ensure_unique(str(proposed_path))

                save_path_obj = Path(save_path)
                existing_sha256 = ""
                if save_path_obj.is_file():
                    try:
                        existing_sha256 = self._sha256(save_path_obj)
                    except OSError:
                        existing_sha256 = ""

                def progress_wrapper(downloaded: int, total: int) -> Optional[bool]:
                    # バイト進捗は現行UIで表示していない。8KBごとにGUIイベントを
                    # 発行するとキューを圧迫するため、ここでは独立したキャンセル
                    # フラグだけを確認する。
                    del downloaded, total
                    return not (cancel_check is not None and cancel_check())

                task = DownloadTask(file_info=file_info, local_path=save_path)
                task.mark_downloading()
                download_result = self.download_file(
                    file_info,
                    save_path,
                    progress_wrapper,
                    cancel_check=cancel_check,
                    max_retries=3,
                )

                if download_result.success:
                    task_issues = list(download_result.issues)
                    if history_issue is not None:
                        task_issues.append(history_issue)
                    task.mark_completed(
                        task_issues,
                        download_result.processing_mode,
                    )
                    completed_path = Path(save_path)
                    task.bytes_written = download_result.bytes_written
                    task.sha256 = download_result.sha256
                    task.validation_kind = self._history.validation_kind(
                        expected_format
                    )
                    self._history.append_success(
                        file_info.url,
                        proposed_path,
                        completed_path,
                        download_result.bytes_written,
                        download_result.sha256,
                        download_result.processing_mode,
                        download_result.final_url,
                        expected_format,
                        document_name=document_name,
                        document_updated_at=document_updated_at,
                        document_id=document_id,
                        history_metadata=history_metadata,
                    )
                else:
                    task_issues = list(download_result.issues)
                    if history_issue is not None:
                        task_issues.append(history_issue)
                    if not any(
                        item.severity == IssueSeverity.ERROR for item in task_issues
                    ):
                        fallback_code = (
                            DownloadIssueCode.CANCELLED
                            if download_result.cancelled
                            else DownloadIssueCode.UNKNOWN
                        )
                        task_issues.insert(
                            0,
                            DownloadIssue(
                                fallback_code,
                                DownloadStage.FETCH,
                                download_result.error
                                or (
                                    "キャンセルされました"
                                    if download_result.cancelled
                                    else "ダウンロードに失敗しました"
                                ),
                            ),
                        )

                    existing_file_preserved = False
                    if existing_sha256 and save_path_obj.is_file():
                        try:
                            existing_file_preserved = (
                                self._sha256(save_path_obj) == existing_sha256
                            )
                        except OSError:
                            existing_file_preserved = False

                    error_index = next(
                        (
                            issue_index
                            for issue_index, item in enumerate(task_issues)
                            if item.severity == IssueSeverity.ERROR
                        ),
                        None,
                    )
                    if error_index is not None and history_lookup.has_record:
                        original_issue = task_issues[error_index]
                        details = dict(original_issue.details)
                        details.update(
                            {
                                "existing_file_preserved": (existing_file_preserved),
                                "redownload_policy": (redownload_policy.value),
                            }
                        )
                        task_issues[error_index] = replace(
                            original_issue,
                            details=details,
                        )

                    primary_issue = next(
                        (
                            item
                            for item in task_issues
                            if item.severity == IssueSeverity.ERROR
                        ),
                        task_issues[0] if task_issues else None,
                    )
                    terminal_status = (
                        "CANCELLED" if download_result.cancelled else "FAILED"
                    )
                    self._history.append_terminal(
                        file_info.url,
                        proposed_path,
                        save_path_obj,
                        terminal_status,
                        expected_format,
                        download_result.processing_mode,
                        (
                            primary_issue.code.value
                            if primary_issue
                            else DownloadIssueCode.UNKNOWN.value
                        ),
                        download_result.final_url,
                        document_name=document_name,
                        document_updated_at=document_updated_at,
                        document_id=document_id,
                        history_metadata=history_metadata,
                    )

                if download_result.cancelled:
                    task.mark_cancelled(
                        download_result.error,
                        task_issues,
                        download_result.processing_mode,
                    )
                elif not download_result.success:
                    task.mark_failed(
                        download_result.error or "ダウンロードに失敗しました",
                        task_issues,
                        download_result.processing_mode,
                    )
                task.retry_count = max(0, download_result.attempts - 1)

                result.add_task(task)
                result.update_status(task)
                self._notify_task_result(
                    task_result_callback,
                    index + 1,
                    len(file_list),
                    task,
                )

                if download_result.cancelled:
                    self._add_cancelled_tasks(
                        result,
                        file_list,
                        index + 1,
                        task_result_callback,
                    )
                    break

            except Exception as exc:
                message = f"ファイル処理で予期しないエラーが発生しました: {exc}"
                issue = DownloadIssue(
                    DownloadIssueCode.UNKNOWN,
                    DownloadStage.FETCH,
                    message,
                )
                task = DownloadTask(
                    file_info=file_info,
                    local_path="",
                    status="failed",
                    error_message=message,
                    issues=[issue],
                    processing_mode=(
                        DownloadMode.HTML_TO_PDF
                        if file_info.allow_html_to_pdf
                        else DownloadMode.DIRECT
                    ),
                )
                result.add_task(task)
                result.update_status(task)
                fallback_result = DownloadFileResult(
                    DownloadStatus.FAILED,
                    file_info.url,
                    "",
                    error=message,
                    processing_mode=task.processing_mode,
                    issues=(issue,),
                )
                self._log_file_result(file_info, fallback_result)
                self._notify_task_result(
                    task_result_callback,
                    index + 1,
                    len(file_list),
                    task,
                )

        # 通常経路では必ず一致する。不測の中断でも結果の嘘を防ぐ。
        if len(result.tasks) < result.total:
            missing = file_list[len(result.tasks) :]
            for file_info in missing:
                task = DownloadTask(
                    file_info=file_info,
                    local_path="",
                    status="failed",
                    error_message="処理されませんでした",
                    issues=[
                        DownloadIssue(
                            DownloadIssueCode.UNKNOWN,
                            DownloadStage.FETCH,
                            "処理されませんでした",
                        )
                    ],
                )
                result.add_task(task)
                self._log_non_transfer_task(
                    task,
                    stage=DownloadStage.FETCH,
                    reason_code=DownloadIssueCode.UNKNOWN.value,
                    reason="処理されませんでした",
                )
                self._notify_task_result(
                    task_result_callback,
                    len(result.tasks),
                    len(file_list),
                    task,
                )
            result.update_status(result.tasks[-1])

        issue_summary = ", ".join(
            f"{code.value}={count}"
            for code, count in sorted(
                result.issue_counts.items(),
                key=lambda item: item[0].value,
            )
        )
        failed_reason_counts = Counter()
        for task in result.failed_tasks:
            primary_issue = next(
                (item for item in task.issues if item.severity == IssueSeverity.ERROR),
                task.issues[0] if task.issues else None,
            )
            if primary_issue:
                failed_reason_counts[primary_issue.code.value] += 1
        failure_summary = ", ".join(
            f"{code}={count}" for code, count in sorted(failed_reason_counts.items())
        )
        self.logger.info(
            f"ダウンロード完了: 新規保存={result.success}, "
            f"保存済み確認={result.reused}, 失敗={result.failed}, "
            f"旧名称再利用={result.legacy_reused}, "
            f"キャンセル={result.cancelled}, "
            f"HTML→PDF変換={result.converted}, "
            f"失敗理由別={failure_summary or 'なし'}, "
            f"診断内訳={issue_summary or 'なし'}"
        )
        return result

    def retry_download(
        self, file_info: FileInfo, save_path: str, max_retries: int = 3
    ) -> bool:
        """互換API。HTTP層で初回を含む最大3回だけ試行する。"""
        max_attempts = max(1, min(max_retries, 3))
        self.logger.info(f"ダウンロード試行（最大{max_attempts}回）: {save_path}")
        return bool(
            self.download_file(
                file_info,
                save_path,
                max_retries=max_retries,
            )
        )

    def check_duplicate(
        self,
        file_path: str,
        file_info: Optional[FileInfo] = None,
    ) -> bool:
        """履歴が利用可能ならURL・サイズ・SHA-256一致を確認する。

        ``file_info`` がない旧呼び出しでは、HTML/空ファイルを除いた
        存在確認のみを行う。新しい本番経路では必ず履歴を使用する。
        """
        path = Path(file_path)
        if file_info is not None and self._history is not None:
            return self._history.find_valid(file_info.url, path) is not None
        if not path.is_file() or path.stat().st_size == 0:
            return False
        try:
            with path.open("rb") as stream:
                return not HTTPClient._looks_like_html(stream.read(100))
        except OSError:
            return False
