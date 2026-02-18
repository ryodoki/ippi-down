# -*- coding: utf-8 -*-
"""
i-ppi 調査用統合ツール（旧 debug/*.py および scripts/debug_extract_files.py の統合）

サブコマンド:
  search      - 検索フォーム送信→結果1ページ目の概要
  paginate    - 全ページを辿って件数/工事件数を集計
  verify      - 検索条件に対する結果妥当性（機関名一致/工事名ヒット等）
  html        - hidden/input/select 一覧、dgrSearchList 等の存在確認
  scraper     - src.core.scraper 経由で同じ確認（GUI 同経路の再現）
  extract-files - 詳細ページ URL から添付ファイル抽出（JSON 出力）

共通引数: --base-url, --daibunrui, --chubunrui, --shoubunrui, --saibunrui, --koji-name,
         --timeout, --output-json, --debug-log

実行例:
  python scripts/investigate/investigate_i_ppi.py search
  python scripts/investigate/investigate_i_ppi.py paginate --output-json
  python scripts/investigate/investigate_i_ppi.py html --base-url "https://www.i-ppi.jp/.../Search.aspx?tab=4"
  python scripts/investigate/investigate_i_ppi.py extract-files --url "https://www.i-ppi.jp/.../Detail.aspx?..." --out result.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# プロジェクトルートをパスに追加（scripts/investigate/ に配置時の想定）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# UTF-8 出力（Windows）
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# デフォルト検索条件（サンプル: 国の機関→国交省→東北→トンネル）
DEFAULT_DAIBUNRUI = "国の機関"
DEFAULT_CHUBUNRUI = "国土交通省"
DEFAULT_SHOUBUNRUI = "東北地方整備局"
DEFAULT_SAIBUNRUI = ""
DEFAULT_KOJI_NAME = "トンネル"
DEFAULT_BASE_URL = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"


def _ensure_src() -> None:
    """src を import 可能にする（遅延 import 用）"""
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))


def _create_scraper_and_conditions(
    base_url: str,
    daibunrui: str,
    chubunrui: str,
    shoubunrui: str,
    saibunrui: str,
    koji_name: str,
    timeout: int,
    debug_log: bool,
) -> tuple:
    _ensure_src()
    from src.core.scraper import Scraper
    from src.models.config_model import SearchConditions
    from src.utils.logger import Logger, LoggingConfig
    from src.utils.http_client import HTTPClient

    log_config = LoggingConfig(level="DEBUG" if debug_log else "INFO")
    logger = Logger(log_config)
    http_client = HTTPClient(logger, timeout=timeout)
    scraper = Scraper(http_client, logger)
    conditions = SearchConditions(
        hachu_daibunrui=daibunrui or "",
        hachu_chubunrui=chubunrui or "",
        hachu_shoubunrui=shoubunrui or "",
        hachu_saibunrui=saibunrui or "",
        koji_name=koji_name or "",
    )
    return scraper, conditions, logger, http_client


def _collect_result(out: Dict[str, Any], key: str, value: Any) -> None:
    """出力用辞書に格納（--output-json 用）"""
    if key not in out:
        out[key] = []
    if isinstance(out[key], list):
        out[key].append(value)
    else:
        out[key] = value


def cmd_search(
    base_url: str,
    daibunrui: str,
    chubunrui: str,
    shoubunrui: str,
    saibunrui: str,
    koji_name: str,
    timeout: int,
    debug_log: bool,
    output_json: bool,
) -> int:
    """検索フォーム送信→結果1ページ目の概要"""
    scraper, conditions, logger, http_client = _create_scraper_and_conditions(
        base_url, daibunrui, chubunrui, shoubunrui, saibunrui, koji_name, timeout, debug_log
    )
    result: Dict[str, Any] = {"command": "search", "total_rows": 0, "rows_preview": []}
    try:
        soup = scraper.submit_search_form(base_url, conditions)
        if not soup:
            print("検索フォームの送信に失敗しました")
            result["error"] = "submit_search_form returned None"
            if output_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        tbl = soup.find("table", id="dgrSearchList")
        if not tbl:
            print("検索結果テーブル(dgrSearchList)が見つかりません")
            result["error"] = "dgrSearchList not found"
            if output_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        rows = tbl.find_all("tr")[1:]
        result["total_rows"] = len(rows)
        print(f"検索結果 1 ページ目: {len(rows)} 件")
        for i, row in enumerate(rows[:10]):
            cells = row.find_all("td")
            link = row.find("a")
            if link and len(cells) >= 2:
                koji = link.get_text(strip=True)
                kikan = cells[1].get_text(strip=True)
                line = f"  {i+1}. {koji[:50]}... / {kikan}"
                print(line)
                result["rows_preview"].append({"koji_name": koji[:80], "hachu_kikan": kikan})
        if len(rows) > 10:
            print(f"  ... 他 {len(rows) - 10} 件")
        if output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        http_client.close()


def cmd_paginate(
    base_url: str,
    daibunrui: str,
    chubunrui: str,
    shoubunrui: str,
    saibunrui: str,
    koji_name: str,
    timeout: int,
    debug_log: bool,
    output_json: bool,
) -> int:
    """全ページを辿って件数/工事件数を集計"""
    scraper, conditions, logger, http_client = _create_scraper_and_conditions(
        base_url, daibunrui, chubunrui, shoubunrui, saibunrui, koji_name, timeout, debug_log
    )
    result: Dict[str, Any] = {"command": "paginate", "pages": [], "total_pages": 0, "total_koji": 0}
    try:
        soup = scraper.submit_search_form(base_url, conditions)
        if not soup:
            print("検索フォームの送信に失敗しました")
            result["error"] = "submit_search_form returned None"
            if output_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        base_url_actual = getattr(scraper, "_last_search_result_url", base_url)
        page_num = 1
        total_koji = 0
        while True:
            tbl = soup.find("table", id="dgrSearchList")
            if tbl:
                rows = tbl.find_all("tr")[1:]
                count = len(rows)
                total_koji += count
                result["pages"].append({"page": page_num, "rows": count})
                print(f"ページ {page_num}: {count} 件 (累計: {total_koji})")
            next_soup = scraper._get_next_page(soup, base_url_actual)
            if next_soup is None:
                break
            soup = next_soup
            base_url_actual = getattr(scraper, "_last_search_result_url", base_url_actual)
            page_num += 1
        result["total_pages"] = page_num
        result["total_koji"] = total_koji
        print(f"全 {page_num} ページ、合計 {total_koji} 件")
        if output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        http_client.close()


def cmd_verify(
    base_url: str,
    daibunrui: str,
    chubunrui: str,
    shoubunrui: str,
    saibunrui: str,
    koji_name: str,
    timeout: int,
    debug_log: bool,
    output_json: bool,
) -> int:
    """検索条件に対する結果妥当性（機関名一致/工事名ヒット等）"""
    scraper, conditions, logger, http_client = _create_scraper_and_conditions(
        base_url, daibunrui, chubunrui, shoubunrui, saibunrui, koji_name, timeout, debug_log
    )
    result: Dict[str, Any] = {"command": "verify", "matched": 0, "total": 0, "other_kikan": []}
    try:
        soup = scraper.submit_search_form(base_url, conditions)
        if not soup:
            print("検索フォームの送信に失敗しました")
            result["error"] = "submit_search_form returned None"
            if output_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        tbl = soup.find("table", id="dgrSearchList")
        if not tbl:
            print("検索結果テーブルが見つかりません")
            result["error"] = "dgrSearchList not found"
            if output_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        rows = tbl.find_all("tr")[1:]
        result["total"] = len(rows)
        expect_kikan = shoubunrui or chubunrui or ""
        other_set = set()
        matched = 0
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                kikan = cells[1].get_text(strip=True)
                if expect_kikan and expect_kikan in kikan:
                    matched += 1
                else:
                    other_set.add(kikan)
        result["matched"] = matched
        result["other_kikan"] = list(other_set)[:20]
        print(f"結果: {len(rows)} 件中、発注機関一致 {matched} 件")
        if other_set:
            print(f"その他の発注機関（最大5件）: {list(other_set)[:5]}")
        if output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        http_client.close()


def cmd_html(
    base_url: str,
    timeout: int,
    debug_log: bool,
    output_json: bool,
    save_html: Optional[str],
) -> int:
    """hidden/input/select 一覧、dgrSearchList 等の存在確認"""
    _ensure_src()
    from src.utils.http_client import HTTPClient
    from src.utils.logger import Logger, LoggingConfig

    log_config = LoggingConfig(level="DEBUG" if debug_log else "INFO")
    logger = Logger(log_config)
    http_client = HTTPClient(logger, timeout=timeout)
    result: Dict[str, Any] = {"command": "html", "hidden": [], "select": [], "text": [], "dgrSearchList": False}
    try:
        response = http_client.get(base_url)
        response.encoding = response.apparent_encoding or "utf-8"
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")
        if save_html:
            Path(save_html).write_text(response.text, encoding="utf-8")
            print(f"HTML を保存: {save_html}")
        form = soup.find("form")
        if form:
            result["form_action"] = form.get("action")
            result["form_method"] = form.get("method")
        for inp in soup.find_all("input", type="hidden"):
            name = inp.get("name")
            if name:
                result["hidden"].append({"name": name, "value_len": len(inp.get("value", ""))})
        for sel in soup.find_all("select"):
            name = sel.get("name") or sel.get("id")
            if name:
                opts = sel.find_all("option")
                result["select"].append({"name": name, "options_count": len(opts)})
        for inp in soup.find_all("input", type="text"):
            name = inp.get("name")
            if name:
                result["text"].append(name)
        tbl = soup.find("table", id="dgrSearchList")
        result["dgrSearchList"] = tbl is not None
        print(f"hidden: {len(result['hidden'])} 個, select: {len(result['select'])} 個, text: {len(result['text'])} 個")
        print(f"dgrSearchList 存在: {result['dgrSearchList']}")
        if output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        http_client.close()


def cmd_scraper(
    base_url: str,
    daibunrui: str,
    chubunrui: str,
    shoubunrui: str,
    saibunrui: str,
    koji_name: str,
    timeout: int,
    debug_log: bool,
    output_json: bool,
) -> int:
    """src.core.scraper 経由で検索（GUI 同経路の再現）"""
    return cmd_search(
        base_url, daibunrui, chubunrui, shoubunrui, saibunrui, koji_name, timeout, debug_log, output_json
    )


def cmd_extract_files(
    url: str,
    out_path: str,
    file_types: List[str],
    debug_log: bool,
    output_json: bool,
) -> int:
    """詳細ページ URL から添付ファイル抽出（JSON 出力）"""
    _ensure_src()
    from src.core.scraper import Scraper
    from src.utils.http_client import HTTPClient
    from src.utils.logger import Logger, LoggingConfig

    log_config = LoggingConfig(level="DEBUG" if debug_log else "INFO")
    logger = Logger(log_config)
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    result: Dict[str, Any] = {"url": url, "file_types": file_types, "files_count": 0, "files": []}
    try:
        if url.startswith("javascript:") and "__doPostBack" in url:
            result["postback_detected"] = True
            result["error"] = "PostBack リンクは --url に詳細ページ URL を指定してください"
            print(result["error"])
            if output_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1
        files = scraper._extract_files_from_detail_page(url, file_types)
        result["files_count"] = len(files)
        for i, fi in enumerate(files, 1):
            result["files"].append({
                "index": i,
                "url": fi.url,
                "filename": fi.filename,
                "file_type": fi.file_type,
                "metadata": fi.metadata or {},
            })
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"抽出: {len(files)} 件 → {out_path}")
        if output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        http_client.close()


def main() -> int:
    # 共通引数（全サブコマンドで利用）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"検索画面 URL (default: ...Search.aspx?tab=4)")
    common.add_argument("--daibunrui", default=DEFAULT_DAIBUNRUI, help=f"大分類 (default: {DEFAULT_DAIBUNRUI})")
    common.add_argument("--chubunrui", default=DEFAULT_CHUBUNRUI, help=f"中分類 (default: {DEFAULT_CHUBUNRUI})")
    common.add_argument("--shoubunrui", default=DEFAULT_SHOUBUNRUI, help=f"小分類 (default: {DEFAULT_SHOUBUNRUI})")
    common.add_argument("--saibunrui", default=DEFAULT_SAIBUNRUI, help="細分類")
    common.add_argument("--koji-name", default=DEFAULT_KOJI_NAME, help=f"工事名 (default: {DEFAULT_KOJI_NAME})")
    common.add_argument("--timeout", type=int, default=30, help="HTTP タイムアウト秒")
    common.add_argument("--output-json", action="store_true", help="結果を JSON で標準出力にも出す")
    common.add_argument("--debug-log", action="store_true", help="DEBUG ログを有効化")

    parser = argparse.ArgumentParser(
        description="i-ppi 調査用統合ツール（検索・ページネーション・HTML 構造・ファイル抽出）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", parents=[common], help="検索フォーム送信→結果1ページ目の概要")
    p_search.set_defaults(func=lambda ns: cmd_search(
        ns.base_url, ns.daibunrui, ns.chubunrui, ns.shoubunrui, ns.saibunrui, ns.koji_name,
        ns.timeout, ns.debug_log, ns.output_json
    ))

    # paginate
    p_paginate = sub.add_parser("paginate", parents=[common], help="全ページを辿って件数/工事件数を集計")
    p_paginate.set_defaults(func=lambda ns: cmd_paginate(
        ns.base_url, ns.daibunrui, ns.chubunrui, ns.shoubunrui, ns.saibunrui, ns.koji_name,
        ns.timeout, ns.debug_log, ns.output_json
    ))

    # verify
    p_verify = sub.add_parser("verify", parents=[common], help="検索条件に対する結果妥当性（機関名一致等）")
    p_verify.set_defaults(func=lambda ns: cmd_verify(
        ns.base_url, ns.daibunrui, ns.chubunrui, ns.shoubunrui, ns.saibunrui, ns.koji_name,
        ns.timeout, ns.debug_log, ns.output_json
    ))

    # html
    p_html = sub.add_parser("html", parents=[common], help="hidden/select/text 一覧・dgrSearchList 存在確認")
    p_html.add_argument("--save-html", type=str, default=None, help="HTML を保存するファイルパス")
    p_html.set_defaults(func=lambda ns: cmd_html(
        ns.base_url, ns.timeout, ns.debug_log, ns.output_json, getattr(ns, "save_html", None)
    ))

    # scraper
    p_scraper = sub.add_parser("scraper", parents=[common], help="Scraper 経由で検索（GUI 同経路）")
    p_scraper.set_defaults(func=lambda ns: cmd_scraper(
        ns.base_url, ns.daibunrui, ns.chubunrui, ns.shoubunrui, ns.saibunrui, ns.koji_name,
        ns.timeout, ns.debug_log, ns.output_json
    ))

    # extract-files
    p_ext = sub.add_parser("extract-files", parents=[common], help="詳細ページ URL から添付ファイル抽出")
    p_ext.add_argument("--url", required=True, help="詳細ページ URL")
    p_ext.add_argument("--out", required=True, help="出力 JSON ファイルパス")
    p_ext.add_argument("--file-types", nargs="+", default=[".pdf", ".xlsx", ".docx"], help="対象拡張子")
    p_ext.set_defaults(
        func=lambda ns: cmd_extract_files(ns.url, ns.out, ns.file_types, ns.debug_log, ns.output_json)
    )

    # サイト変更監視（i_ppi_inspector: 同梱 scripts/investigate から import）
    _investigate_dir = Path(__file__).resolve().parent
    if str(_investigate_dir) not in sys.path:
        sys.path.insert(0, str(_investigate_dir))
    try:
        from i_ppi_inspector.cli import (
            add_parser_snapshot,
            add_parser_probe,
            add_parser_diff,
            add_parser_impact,
            run_inspector,
        )
        add_parser_snapshot(sub)
        add_parser_probe(sub)
        add_parser_diff(sub)
        add_parser_impact(sub)
        for cmd in ("snapshot", "probe", "diff", "impact"):
            if cmd in sub.choices:
                sub.choices[cmd].set_defaults(func=run_inspector)
    except ImportError:
        pass  # i_ppi_inspector が無い環境では従来コマンドのみ

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
