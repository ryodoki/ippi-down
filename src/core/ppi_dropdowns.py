# -*- coding: utf-8 -*-

"""ppi.jpのドロップダウン選択肢（工事種別・業種）のコードとラベルのマッピング"""

from typing import List, Tuple, Dict, Optional
from ..utils.logger import Logger


# 工事種別のオプション（コード, ラベル）
# 注: 実際のHTMLから抽出した値。順序は重要（コードが連番の場合がある）
KOJI_SHUBETSU_OPTIONS: List[Tuple[str, str]] = [
    ("", ""),  # 未選択
    ("01", "一般土木工事"),
    ("02", "アスファルト舗装工事"),
    ("03", "鋼橋上部工事"),
    ("04", "造園工事"),
    ("05", "建築工事"),
    ("06", "木造建築工事"),
    ("07", "電気設備工事"),
    ("08", "暖冷房衛生設備工事"),
    ("09", "セメント・コンクリート舗装工事"),
    ("10", "プレストレスト・コンクリート工事"),
    ("11", "法面処理工事"),
    ("12", "塗装工事"),
    ("13", "維持修繕工事"),
    ("14", "浚渫工事"),
    ("15", "グラウト工事"),
    ("16", "杭打工事"),
    ("17", "さく井工事"),
    ("18", "プレハブ建築工事"),
    ("19", "機械設備工事"),
    ("20", "通信設備工事"),
    ("21", "受変電設備工事"),
    ("22", "港湾土木工事"),
    ("23", "農林土木工事"),
    ("24", "農林建築工事"),
    ("25", "橋梁補修工事"),
    ("99", "その他"),
]

# 工事の業種のオプション（コード, ラベル）
# 注: 実際のHTMLから抽出した値。順序は重要（コードが連番の場合がある）
KOJI_GYOUSHU_OPTIONS: List[Tuple[str, str]] = [
    ("", ""),  # 未選択
    ("01", "土木一式工事"),
    ("02", "建築一式工事"),
    ("03", "大工工事"),
    ("04", "左官工事"),
    ("05", "とび・土工・コンクリート工事"),
    ("06", "石工事"),
    ("07", "屋根工事"),
    ("08", "電気工事"),
    ("09", "管工事"),
    ("10", "タイル・れんが・ブロック工事"),
    ("11", "鋼構造物工事"),
    ("12", "鉄筋工事"),
    ("13", "舗装工事"),
    ("14", "浚渫工事"),
    ("15", "板金工事"),
    ("16", "ガラス工事"),
    ("17", "塗装工事"),
    ("18", "防水工事"),
    ("19", "内装仕上工事"),
    ("20", "機械器具設置工事"),
    ("21", "熱絶縁工事"),
    ("22", "電気通信工事"),
    ("23", "造園工事"),
    ("24", "さく井工事"),
    ("25", "建具工事"),
    ("26", "水道施設工事"),
    ("27", "消防施設工事"),
    ("28", "清掃施設工事"),
    ("29", "解体工事"),
    ("99", "その他"),
]


def _get_options(kind: str) -> List[Tuple[str, str]]:
    """種類に応じたオプションリストを取得"""
    if kind == "koji_shubetsu":
        return KOJI_SHUBETSU_OPTIONS
    elif kind == "koji_gyoushu":
        return KOJI_GYOUSHU_OPTIONS
    else:
        raise ValueError(f"未知の種類: {kind}")


def _build_label_to_code_map(kind: str) -> Dict[str, str]:
    """ラベル→コードのマッピングを構築"""
    options = _get_options(kind)
    return {label: code for code, label in options if label}


def _build_code_to_label_map(kind: str) -> Dict[str, str]:
    """コード→ラベルのマッピングを構築"""
    options = _get_options(kind)
    return {code: label for code, label in options if code}


def label_to_code(kind: str, label_or_code: str, logger: Optional[Logger] = None) -> str:
    """ラベルまたはコードをコードに変換
    
    Args:
        kind: "koji_shubetsu" または "koji_gyoushu"
        label_or_code: ラベル（例: "一般土木工事"）またはコード（例: "01"）
        logger: ロガー（変換ログ出力用）
    
    Returns:
        コード（例: "01"）。未知の入力の場合は空文字列（未指定）
    """
    if not label_or_code:
        return ""
    
    # 既にコードっぽい（数字のみ）ならそのまま返す
    if label_or_code.isdigit() or (len(label_or_code) == 2 and label_or_code.isdigit()):
        # コードが有効か確認
        code_to_label = _build_code_to_label_map(kind)
        if label_or_code in code_to_label:
            return label_or_code
        else:
            if logger:
                logger.warning(f"{kind}: 無効なコード '{label_or_code}' を検出、未指定として扱います")
            return ""
    
    # ラベルからコードを検索
    label_to_code_map = _build_label_to_code_map(kind)
    code = label_to_code_map.get(label_or_code)
    
    if code:
        if logger and label_or_code != code:
            logger.info(f"{kind}: '{label_or_code}' -> '{code}' に変換しました")
        return code
    else:
        if logger:
            logger.warning(f"{kind}: 未知のラベル '{label_or_code}' を検出、未指定として扱います")
        return ""


def code_to_label(kind: str, code_or_label: str, logger: Optional[Logger] = None) -> str:
    """コードまたはラベルをラベルに変換
    
    Args:
        kind: "koji_shubetsu" または "koji_gyoushu"
        code_or_label: コード（例: "01"）またはラベル（例: "一般土木工事"）
        logger: ロガー（変換ログ出力用）
    
    Returns:
        ラベル（例: "一般土木工事"）。未知の入力の場合は空文字列（未指定）
    """
    if not code_or_label:
        return ""
    
    # 既にコードっぽい（数字のみ）ならコード→ラベル変換
    if code_or_label.isdigit() or (len(code_or_label) == 2 and code_or_label.isdigit()):
        code_to_label_map = _build_code_to_label_map(kind)
        label = code_to_label_map.get(code_or_label)
        if label:
            return label
        else:
            if logger:
                logger.warning(f"{kind}: 無効なコード '{code_or_label}' を検出、未指定として扱います")
            return ""
    
    # ラベルとして有効か確認
    label_to_code_map = _build_label_to_code_map(kind)
    if code_or_label in label_to_code_map:
        return code_or_label
    else:
        if logger:
            logger.warning(f"{kind}: 未知のラベル '{code_or_label}' を検出、未指定として扱います")
        return ""


def get_labels(kind: str) -> List[str]:
    """指定された種類のラベルリストを取得（GUIのCombobox用）
    
    Args:
        kind: "koji_shubetsu" または "koji_gyoushu"
    
    Returns:
        ラベルリスト（空文字列を含む）
    """
    options = _get_options(kind)
    return [label for code, label in options]
