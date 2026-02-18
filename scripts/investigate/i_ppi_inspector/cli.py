# -*- coding: utf-8 -*-
"""
サイト変更監視・調査の CLI（snapshot / probe / diff / impact）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

# プロジェクトルートをパスに追加（scripts/investigate/i_ppi_inspector/ に配置時の想定）
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from .snapshot import take_snapshot, save_snapshot_dir
from .diff import diff_snapshots
from .report import write_report, render_markdown
from .mapping import get_impact_locations, get_all_mapped_keys


# スナップショット保存先（scripts/snapshots/ で .gitignore 済み）
DEFAULT_SNAPSHOTS_DIR = _SCRIPT_DIR.parent.parent / "snapshots"
BASE_SEARCH = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"


def cmd_snapshot(
    urls: List[str],
    out_dir: Path,
    timeout: int,
) -> int:
    """指定 URL の構造化スナップショットを保存する"""
    import requests
    sess = requests.Session()
    sess.headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    snapshots = []
    for url in urls:
        try:
            data = take_snapshot(url, timeout=timeout, session=sess)
            snapshots.append(data)
            print(f"OK: {url[:70]}...")
        except Exception as e:
            print(f"ERR: {url[:70]}... - {e}", file=sys.stderr)
    if not snapshots:
        return 1
    saved = save_snapshot_dir(snapshots, out_dir)
    print(f"保存先: {saved}")
    return 0


def cmd_probe(
    tabs: List[int],
    base_url: str,
    timeout: int,
    no_postback: bool,
    out_path: Optional[Path],
) -> int:
    """工事(tab=3)・業務(tab=6) 等のドロップダウンと POSTBACK を検証する"""
    from .probe import run_probe
    out_dir = Path(out_path) if out_path else DEFAULT_SNAPSHOTS_DIR / "probe"
    results = run_probe(tabs, base_url=base_url, timeout=timeout, do_postback=not no_postback, output_dir=out_dir)
    for r in results:
        print(f"tab={r['tab']}: status={r['status_code']}, __EVENTTARGET={r.get('has_eventtarget')}, postback={r.get('postback_done')}")
    if out_path:
        print(f"保存先: {out_dir / 'probe_result.json'}")
    return 0


def cmd_diff(
    old_dir: Path,
    new_dir: Path,
    output: Optional[Path],
    format: str,
) -> int:
    """2 つのスナップショットを比較して差分レポートを出力する"""
    results = diff_snapshots(old_dir, new_dir)
    if not results:
        print("差分はありません")
        return 0
    print(render_markdown(results))
    if output:
        write_report(results, output, format=format)
        print(f"レポート保存: {output}")
    return 0


def cmd_impact(
    diff_report_path: Path,
    output: Optional[Path],
) -> int:
    """差分レポート（JSON）と mapping を突合し、影響する src 箇所を列挙する"""
    if not diff_report_path.exists():
        print(f"ファイルが見つかりません: {diff_report_path}", file=sys.stderr)
        return 1
    data = json.loads(diff_report_path.read_text(encoding="utf-8"))
    impacts = []
    for item in data:
        msg = item.get("message", "")
        importance = item.get("importance", "LOW")
        # メッセージからフィールド名らしきものを抽出（簡易: "input 削除: name=xxx" 等）
        locs = []
        for key in get_all_mapped_keys():
            if key in msg or key.lower() in msg.lower():
                for path, desc in get_impact_locations(key):
                    locs.append((path, desc))
        if locs:
            impacts.append({"importance": importance, "message": msg, "locations": locs})
    if not impacts:
        print("マッピングにヒットした影響箇所はありません")
        return 0
    for imp in impacts:
        print(f"\n[{imp['importance']}] {imp['message']}")
        for path, desc in imp["locations"]:
            print(f"  - {path}: {desc}")
    if output:
        out_data = [{"importance": i["importance"], "message": i["message"], "locations": i["locations"]} for i in impacts]
        output.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n保存: {output}")
    return 0


def add_parser_snapshot(sub: Any) -> None:
    p = sub.add_parser("snapshot", help="指定 URL の構造化スナップショットを保存")
    p.add_argument("urls", nargs="+", help="取得する URL（複数可）")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_SNAPSHOTS_DIR, help="スナップショット保存先ディレクトリ")
    p.add_argument("--timeout", type=int, default=30, help="HTTP タイムアウト秒")
    p.set_defaults(inspector_cmd="snapshot")


def add_parser_probe(sub: Any) -> None:
    p = sub.add_parser("probe", help="tab=3/6 等のドロップダウン・POSTBACK を検証")
    p.add_argument("--tabs", type=int, nargs="+", default=[3, 4, 6], help="検証する tab 番号")
    p.add_argument("--base-url", default=BASE_SEARCH, help="検索画面ベース URL")
    p.add_argument("--timeout", type=int, default=30, help="HTTP タイムアウト秒")
    p.add_argument("--no-postback", action="store_true", help="POSTBACK を実行しない")
    p.add_argument("--out", type=Path, default=None, help="結果 JSON の保存先ディレクトリ")
    p.set_defaults(inspector_cmd="probe")


def add_parser_diff(sub: Any) -> None:
    p = sub.add_parser("diff", help="2 つのスナップショットを比較して差分レポート生成")
    p.add_argument("old_dir", type=Path, help="比較元スナップショットディレクトリ（YYYYMMDD_HHMMSS）")
    p.add_argument("new_dir", type=Path, help="比較先スナップショットディレクトリ")
    p.add_argument("--output", "-o", type=Path, default=None, help="レポート出力パス")
    p.add_argument("--format", choices=("markdown", "json"), default="markdown", help="出力形式")
    p.set_defaults(inspector_cmd="diff")


def add_parser_impact(sub: Any) -> None:
    p = sub.add_parser("impact", help="差分レポートから影響する src 実装箇所を列挙")
    p.add_argument("diff_report", type=Path, help="diff で出力した JSON レポートのパス")
    p.add_argument("--output", "-o", type=Path, default=None, help="影響一覧の出力パス（JSON）")
    p.set_defaults(inspector_cmd="impact")


def run_inspector(args: argparse.Namespace) -> int:
    """inspector サブコマンドのエントリ"""
    cmd = getattr(args, "inspector_cmd", None)
    if cmd == "snapshot":
        return cmd_snapshot(args.urls, args.out_dir, args.timeout)
    if cmd == "probe":
        return cmd_probe(args.tabs, args.base_url, args.timeout, args.no_postback, args.out)
    if cmd == "diff":
        return cmd_diff(args.old_dir, args.new_dir, args.output, args.format)
    if cmd == "impact":
        return cmd_impact(args.diff_report, args.output)
    return 0


