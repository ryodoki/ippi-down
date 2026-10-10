# -*- coding: utf-8 -*-

"""通常実行と定期実行の保存ルートを解決する。"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Final, Mapping, Union

from ..models.search_target import SearchTarget
from ..utils.file_utils import FileUtils


class RunKind(str, Enum):
    """ダウンロードの実行種別。"""

    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"


TARGET_STORAGE_FOLDERS: Final[Mapping[SearchTarget, str]] = MappingProxyType(
    {
        SearchTarget.KOJI_KEIKA: "工事の検索（入札の経過）",
        SearchTarget.GYOMU_KEIKA: "業務の検索（入札の経過）",
    }
)


def target_storage_folder(search_target: SearchTarget | str) -> str:
    """検索対象に対応する、変更されないv4最上位フォルダー名を返す。"""

    target = SearchTarget.coerce(search_target)
    return TARGET_STORAGE_FOLDERS[target]


def _coerce_run_kind(value: Union[RunKind, str]) -> RunKind:
    if isinstance(value, RunKind):
        return value
    try:
        return RunKind(str(value).strip().upper())
    except ValueError as exc:
        raise ValueError(f"未対応の実行種別です: {value}") from exc


def _required_folder(save_paths: object, attribute: str) -> str:
    value = str(getattr(save_paths, attribute, "") or "").strip()
    if not value:
        raise ValueError(f"保存フォルダ設定 {attribute} が指定されていません")
    return value


def resolve_run_root(
    save_paths: object,
    run_kind: Union[RunKind, str],
    search_target: SearchTarget | str,
) -> Path:
    """設定されたデータルートから実行種別ごとの保存ルートを返す。

    ``layout_version`` がない旧設定はv2として扱い、従来どおり
    ``local`` 自体を返す。v3では通常実行と定期実行を分離し、v4では
    さらに検索対象をデータルート直下で分離する。
    戻り値は絶対化しないため、既存のアプリ基準相対パス解決と併用できる。
    """

    local = str(getattr(save_paths, "local", "") or "").strip()
    if not local:
        raise ValueError("保存先 save_paths.local が指定されていません")

    try:
        layout_version = int(getattr(save_paths, "layout_version", 2))
    except (TypeError, ValueError) as exc:
        raise ValueError("layout_versionは整数で指定してください") from exc

    base = Path(local)
    if layout_version < 3:
        return base

    kind = _coerce_run_kind(run_kind)
    folder_parts = []
    if layout_version >= 4:
        folder_parts.append(target_storage_folder(search_target))
    if kind is RunKind.MANUAL:
        folder_parts.extend([
            _required_folder(save_paths, "normal_folder"),
        ])
    else:
        folder_parts.extend([
            _required_folder(save_paths, "scheduled_folder"),
            _required_folder(save_paths, "schedule_storage_folder"),
        ])

    return FileUtils.build_safe_directory_path(base, folder_parts)
