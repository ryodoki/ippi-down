# -*- coding: utf-8 -*-
"""
差分レポートの出力（Markdown / JSON）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def render_markdown(diff_results: List[Dict[str, Any]], title: str = "i-ppi サイト構造 差分レポート") -> str:
    """差分結果を Markdown 文字列で返す"""
    lines = [f"# {title}", ""]
    by_imp: Dict[str, List[Dict]] = {}
    for r in diff_results:
        imp = r.get("importance", "LOW")
        by_imp.setdefault(imp, []).append(r)
    for imp in ("HIGH", "MED", "LOW"):
        items = by_imp.get(imp, [])
        if not items:
            continue
        lines.append(f"## {imp} ({len(items)} 件)")
        lines.append("")
        for r in items:
            url = r.get("url", "")
            msg = r.get("message", "")
            lines.append(f"- **{msg}**")
            if url:
                lines.append(f"  - URL: `{url[:80]}...`" if len(url) > 80 else f"  - URL: `{url}`")
            detail = r.get("detail")
            if detail:
                lines.append(f"  - detail: `{detail}`")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def write_report(
    diff_results: List[Dict[str, Any]],
    output_path: Path,
    format: str = "markdown",
    title: str = "i-ppi サイト構造 差分レポート",
) -> None:
    """レポートをファイルに書き出す（format: markdown | json）"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        output_path.write_text(json.dumps(diff_results, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_markdown(diff_results, title=title), encoding="utf-8")
