# -*- coding: utf-8 -*-

"""ファイル操作ユーティリティ"""

import os
import re
import hashlib
from pathlib import Path
from typing import Iterable, List


class FileUtils:
    """ファイル操作ユーティリティ"""

    WINDOWS_RESERVED_NAMES = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }

    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 200) -> str:
        """ファイル名から無効な文字を削除し、長さを制限
        
        Args:
            filename: ファイル名
            max_length: 最大長（拡張子を除く、デフォルト200文字）
                        Windowsのパス長制限（260文字）を考慮
        """
        # Windowsで無効な文字を削除
        invalid_chars = r'[\x00-\x1f<>:"/\\|?*]'
        filename = re.sub(invalid_chars, "_", filename)

        # 先頭・末尾の空白とドットを削除
        filename = filename.strip(" .")

        # 連続する空白やアンダースコアを1つに
        filename = re.sub(r"[_\s]+", "_", filename)

        # 空の場合はデフォルト名を返す
        if not filename:
            filename = "untitled"

        # Windowsパス長制限を考慮（拡張子を除いてmax_length文字以内）
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            ext = '.' + ext
        else:
            name = filename
            ext = ''

        # Windows予約デバイス名は拡張子があってもファイルとして作成できない。
        if name.upper() in FileUtils.WINDOWS_RESERVED_NAMES:
            name = f"_{name}"
            filename = name + ext
        
        # ファイル名を切り詰め
        if len(name) > max_length:
            name = name[:max_length]
            filename = name + ext
        elif len(filename) > max_length + len(ext):
            # 拡張子を含めた全体が長すぎる場合
            max_name_length = max_length - len(ext)
            if max_name_length > 0:
                name = name[:max_name_length]
                filename = name + ext
            else:
                # 拡張子が長すぎる場合はファイル名を短縮
                filename = filename[:max_length]

        return filename

    @staticmethod
    def sanitize_path_component(
        value: object,
        max_length: int = 200,
        default: str = "untitled",
    ) -> str:
        """1つのフォルダ名をWindowsで安全な要素へ変換する。

        区切り文字、予約デバイス名、末尾の空白・ピリオドを無害化し、
        長い要素は単純切り捨てではなく安定ハッシュ付きで短縮する。
        """
        component = re.sub(
            r'[\x00-\x1f<>:"/\\|?*]',
            "_",
            str(value or ""),
        )
        component = component.strip(" .")
        component = re.sub(r"[_\s]+", "_", component)
        if not component:
            component = default

        # Windowsでは拡張子の有無にかかわらず、先頭名が予約デバイス名
        # なら作成できない。
        device_name = component.split(".", 1)[0]
        if device_name.upper() in FileUtils.WINDOWS_RESERVED_NAMES:
            component = f"_{component}"

        if len(component) > max_length:
            component = FileUtils._truncate_component(
                component,
                max_length,
            )
        return component

    @staticmethod
    def ensure_unique(file_path: str, max_path_length: int = 260) -> str:
        """ファイルパスが既に存在する場合、一意なパスを生成
        
        Args:
            file_path: ファイルパス
            max_path_length: 最大パス長（Windowsの制限を考慮、デフォルト260文字）
        """
        path = Path(FileUtils._truncate_path(file_path, max_path_length))
        if not path.exists():
            return str(path)

        # ファイル名に連番を追加
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1

        while True:
            new_name = f"{stem}_{counter}{suffix}"
            new_path = Path(
                FileUtils._truncate_path(
                    str(parent / new_name), max_path_length
                )
            )
            
            if not new_path.exists():
                return str(new_path)
            counter += 1
            
            # 無限ループを防ぐ（1000回まで）
            if counter > 1000:
                raise ValueError(f"一意なファイル名を生成できませんでした: {file_path}")

    @staticmethod
    def _truncate_path(file_path: str, max_length: int) -> str:
        """拡張子と安定ハッシュを保持してファイル名を短縮する。
        
        Args:
            file_path: ファイルパス
            max_length: 最大長
        """
        if len(file_path) <= max_length:
            return file_path
        
        path = Path(file_path)
        parent = str(path.parent)
        available_length = max_length - len(parent) - 1  # -1はパス区切り文字
        if available_length < 14:
            raise ValueError(
                "保存先パスが長すぎます。より短い保存先を指定してください: "
                f"{parent}"
            )
        filename = FileUtils._truncate_component(
            path.name, available_length, preserve_suffix=True
        )
        result = str(Path(parent) / filename)
        if len(result) > max_length:
            raise ValueError(f"パスを{max_length}文字以内に短縮できません: {file_path}")
        return result

    @staticmethod
    def _truncate_component(
        value: str, max_length: int, preserve_suffix: bool = False
    ) -> str:
        """末尾に安定ハッシュを付けて1つのパス要素を短縮する。"""
        if len(value) <= max_length:
            return value
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
        suffix = Path(value).suffix if preserve_suffix else ""
        marker = f"_{digest}"
        prefix_length = max_length - len(marker) - len(suffix)
        if prefix_length < 1:
            raise ValueError(f"パス要素を短縮できません: {value}")
        stem = value[:-len(suffix)] if suffix else value
        return f"{stem[:prefix_length]}{marker}{suffix}"

    @staticmethod
    def build_safe_download_path(
        base_dir: Path,
        folder_name: str,
        filename: str,
        max_path_length: int = 240,
    ) -> Path:
        """生成フォルダとファイル名を含むフルパスを安全な長さに収める。"""
        return FileUtils.build_safe_download_path_parts(
            base_dir,
            [folder_name],
            filename,
            max_path_length=max_path_length,
        )

    @staticmethod
    def _assert_contained(base_dir: Path, candidate: Path) -> Path:
        """候補パスが保存ルート配下であることを確認する。"""
        resolved_base = base_dir.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
        try:
            resolved_candidate.relative_to(resolved_base)
        except ValueError as exc:
            raise ValueError(
                f"保存先ルート外のパスは使用できません: {candidate}"
            ) from exc
        return resolved_candidate

    @staticmethod
    def _fit_component_budgets(
        lengths: List[int],
        minimums: List[int],
        available: int,
    ) -> List[int]:
        """複数要素の長さを偏りなく、決定的に予算内へ収める。"""
        if sum(minimums) > available:
            raise ValueError("保存先パスが長すぎます。より短い保存先を指定してください")

        budgets = list(lengths)
        excess = sum(budgets) - available
        while excess > 0:
            reducible = [
                index
                for index, budget in enumerate(budgets)
                if budget > minimums[index]
            ]
            if not reducible:
                raise ValueError(
                    "保存先パスが長すぎます。より短い保存先を指定してください"
                )
            largest = max(budgets[index] for index in reducible)
            same_largest = [
                index for index in reducible if budgets[index] == largest
            ]
            lower_values = [
                budgets[index]
                for index in reducible
                if budgets[index] < largest
            ]
            next_level = max(lower_values) if lower_values else 0
            reduction_per_item = max(
                1,
                min(
                    largest - max(next_level, 0),
                    (excess + len(same_largest) - 1)
                    // len(same_largest),
                ),
            )
            for index in same_largest:
                if excess <= 0:
                    break
                reduction = min(
                    reduction_per_item,
                    budgets[index] - minimums[index],
                    excess,
                )
                budgets[index] -= reduction
                excess -= reduction
        return budgets

    @staticmethod
    def build_safe_download_path_parts(
        base_dir: Path,
        folder_parts: Iterable[object],
        filename: str,
        max_path_length: int = 240,
        return_lexical: bool = False,
    ) -> Path:
        """複数階層のフォルダとファイル名から安全な保存先を作る。

        ``return_lexical`` はsymlink/reparse pointを別途検査する保守処理用。
        containmentは常に解決後pathで確認し、既定の戻り値は従来どおり
        解決済みpathとする。
        """
        resolved_base = Path(base_dir).resolve(strict=False)
        lexical_base = Path(os.path.abspath(os.fspath(base_dir)))
        output_base = lexical_base if return_lexical else resolved_base
        raw_parts = list(folder_parts)
        safe_parts = [
            FileUtils.sanitize_path_component(
                part,
                max_length=max(200, len(str(part or ""))),
            )
            for part in raw_parts
            if str(part or "").strip()
        ]
        if not safe_parts:
            safe_parts = ["その他"]
        safe_filename = FileUtils.sanitize_filename(
            filename,
            max_length=max(200, len(str(filename or ""))),
        )

        proposed = output_base.joinpath(*safe_parts, safe_filename)
        resolved_proposed = FileUtils._assert_contained(
            resolved_base,
            proposed,
        )
        if len(str(proposed)) <= max_path_length:
            return proposed if return_lexical else resolved_proposed

        # ``base\\dir\\file`` の区切り文字分を先に差し引く。
        component_count = len(safe_parts) + 1
        available = max_path_length - len(str(output_base)) - component_count
        suffix = Path(safe_filename).suffix
        values = safe_parts + [safe_filename]
        minimums = [
            min(len(value), 10) for value in safe_parts
        ] + [min(len(safe_filename), max(14, len(suffix) + 10))]
        try:
            budgets = FileUtils._fit_component_budgets(
                [len(value) for value in values],
                minimums,
                available,
            )
        except ValueError as exc:
            raise ValueError(
                "保存先パスが長すぎます。より短い保存先を指定してください: "
                f"{resolved_base}"
            ) from exc

        fitted_parts = [
            FileUtils._truncate_component(value, budget)
            for value, budget in zip(safe_parts, budgets[:-1])
        ]
        fitted_filename = FileUtils._truncate_component(
            safe_filename,
            budgets[-1],
            preserve_suffix=True,
        )
        result = output_base.joinpath(*fitted_parts, fitted_filename)
        resolved_result = FileUtils._assert_contained(resolved_base, result)
        if len(str(result)) > max_path_length:
            raise ValueError(
                f"パスを{max_path_length}文字以内に短縮できません: {proposed}"
            )
        return result if return_lexical else resolved_result

    @staticmethod
    def build_safe_directory_path(
        base_dir: Path,
        folder_parts: Iterable[object],
    ) -> Path:
        """保存ルート配下の複数階層ディレクトリを安全に構築する。"""
        base = Path(base_dir)
        safe_parts = [
            FileUtils.sanitize_path_component(part)
            for part in folder_parts
            if str(part or "").strip()
        ]
        if not safe_parts:
            raise ValueError("保存フォルダが指定されていません")
        candidate = base.joinpath(*safe_parts)
        # 相対ルートはアプリ基準で後から解決されるため、ここでは絶対化した
        # containment確認後に元の相対性を保って返す。
        FileUtils._assert_contained(base, candidate)
        return candidate

    @staticmethod
    def create_directory_structure(path: str) -> bool:
        """ディレクトリ構造を作成"""
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False

    @staticmethod
    def get_file_size(file_path: str) -> int:
        """ファイルサイズを取得（バイト）"""
        try:
            return os.path.getsize(file_path)
        except OSError:
            return 0

    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """ファイルサイズを人間が読みやすい形式に変換"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"
