# -*- coding: utf-8 -*-

"""保存先フォルダ階層を組み立てる責務（発注機関ルートフォルダ対応）"""

from pathlib import Path
from datetime import datetime
from typing import Optional

from ..models.file_info import FileInfo
from ..models.config_model import AppConfig
from ..utils.file_utils import FileUtils


# フォルダ名の最大長（Windows パス長を考慮）
FOLDER_NAME_MAX_LENGTH = 80
PLACEHOLDER = "unknown"


def sanitize_and_trim(name: Optional[str], max_length: int = FOLDER_NAME_MAX_LENGTH) -> str:
    """フォルダ名を安全な文字列にし、長さ制限をかける。空/None は unknown。"""
    if name is None or not str(name).strip():
        return PLACEHOLDER
    s = FileUtils.sanitize_filename(str(name).strip(), max_length=max_length)
    return s if s else PLACEHOLDER


def _partition_date(date_value: Optional[str], mode: str) -> str:
    """日付値からフォルダ名用のパーティション文字列を生成。"""
    today = datetime.now()
    if not date_value or not str(date_value).strip():
        y, m, d = today.year, today.month, today.day
    else:
        try:
            # YYYY-MM-DD または YYYY/MM/DD 等を想定
            s = str(date_value).strip()
            for sep in ["-", "/", "."]:
                if sep in s:
                    parts = s.split(sep)
                    if len(parts) >= 3:
                        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                        break
                    if len(parts) >= 1:
                        y = int(parts[0])
                        m = today.month if len(parts) < 2 else int(parts[1])
                        d = today.day if len(parts) < 3 else int(parts[2])
                        break
            else:
                y, m, d = today.year, today.month, today.day
        except (ValueError, IndexError):
            y, m, d = today.year, today.month, today.day
    if mode == "yyyy":
        return str(y)
    if mode == "yyyy_mm":
        return f"{y}_{m:02d}"
    if mode == "yyyy_mm_dd":
        return f"{y}_{m:02d}_{d:02d}"
    return str(y)


def build_save_dir(
    base_dir: Path,
    file_info: FileInfo,
    config: AppConfig,
    logger=None,
) -> Path:
    """発注機関階層・工事/業務・日付パーティションを反映した保存ディレクトリを組み立てる。

    - enable_agency_root_folders が False のときは base_dir をそのまま返す（呼び出し側で use_subfolders/folder_name を適用）。
    - True のときは base_dir / 発注機関 / 大分類 / 中分類 / 小分類 / 細分類 / 工事 or 業務 / (日付) を生成し mkdir して返す。
    """
    save_paths = config.save_paths
    if not getattr(save_paths, "enable_agency_root_folders", True):
        return base_dir

    base = base_dir
    meta = file_info.metadata or {}
    levels = getattr(save_paths, "agency_folder_levels", None) or [
        "daibunrui", "chubunrui", "shoubunrui", "saibunrui"
    ]
    root_label = getattr(save_paths, "agency_root_label", None) or "発注機関"
    base = base / sanitize_and_trim(root_label)

    for level in levels:
        value = meta.get(level) or PLACEHOLDER
        base = base / sanitize_and_trim(str(value))

    if getattr(save_paths, "include_search_tab_folder", True):
        tab = meta.get("search_tab") or PLACEHOLDER
        labels = getattr(save_paths, "search_tab_labels", None) or {
            "works": "工事_入札公告等",
            "services": "業務_入札公告等",
        }
        folder_name = labels.get(tab, tab if tab != PLACEHOLDER else "unknown")
        base = base / sanitize_and_trim(folder_name)

    date_partition = getattr(save_paths, "date_partition", "none") or "none"
    if date_partition != "none":
        date_val = meta.get("date")
        part = _partition_date(date_val, date_partition)
        base = base / sanitize_and_trim(part)

    base.mkdir(parents=True, exist_ok=True)
    if logger:
        logger.info(
            f"発注機関フォルダ: base_dir={base_dir}, 生成先={base}, "
            f"metadata(daibunrui/chubunrui/search_tab)={meta.get('daibunrui')}/{meta.get('chubunrui')}/{meta.get('search_tab')}"
        )
    return base
