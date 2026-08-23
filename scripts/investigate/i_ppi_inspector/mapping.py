# -*- coding: utf-8 -*-
"""
Scraper/Parser 依存項目のマッピング（フィールド名・DOM id → 実装箇所）

diff で検出した変更項目と突合し、impact サブコマンドで修正ポイントを提示するために使用する。
"""

from typing import Dict, List, Tuple

# 項目識別子（name または id） → (ファイルパス, 説明)
FIELD_TO_SRC: Dict[str, List[Tuple[str, str]]] = {
    # 検索フォーム・ドロップダウン（工事 tab=4 で使用）
    "drpTopKikanInf": [
        ("src/core/scraper.py", "大分類ドロップダウン value 取得・POSTBACK 送信"),
    ],
    "drpLargeKikanInf2": [
        ("src/core/scraper.py", "中分類ドロップダウン value 取得・POSTBACK 送信"),
    ],
    "drpMiddleKikanInf": [
        ("src/core/scraper.py", "小分類ドロップダウン value 取得・POSTBACK 送信"),
    ],
    "drpSmallKikanInf": [
        ("src/core/scraper.py", "細分類ドロップダウン value 取得・POSTBACK 送信"),
    ],
    "__EVENTTARGET": [
        ("src/core/scraper.py", "_do_postback / フォーム送信"),
        ("src/core/parser/aspnet_form_parser.py", "build_postback_data"),
    ],
    "__EVENTARGUMENT": [
        ("src/core/scraper.py", "POSTBACK 送信"),
        ("src/core/parser/aspnet_form_parser.py", "build_postback_data"),
    ],
    # 検索結果テーブル
    "dgrSearchList": [
        ("src/core/scraper.py", "検索結果テーブル行取得・ページネーション・詳細リンク抽出"),
        ("src/core/parser/search_result_parser.py", "検索結果パース"),
    ],
    # 詳細ページ PostBack
    "dgrKokoku": [
        ("src/core/scraper.py", "公告テーブル・ファイルリンク抽出"),
    ],
    "dgrKeika": [
        ("src/core/scraper.py", "経過テーブル・ファイルリンク抽出"),
    ],
    # フォーム共通
    "form": [
        ("src/core/scraper.py", "form action 取得・POST 先 URL"),
    ],
}


def get_impact_locations(field_name_or_id: str) -> List[Tuple[str, str]]:
    """フィールド名または id に対応する実装箇所を返す"""
    return FIELD_TO_SRC.get(field_name_or_id, [])


def get_all_mapped_keys() -> List[str]:
    """マッピングされている全キーを返す"""
    return list(FIELD_TO_SRC.keys())
