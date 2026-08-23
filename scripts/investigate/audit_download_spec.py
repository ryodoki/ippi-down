# -*- coding: utf-8 -*-
"""
ダウンロード仕様の要件突合監査ツール。

docs/requirements.md の FR-005/008/009/012/013 と実装・設定・ログを比較し、
乖離レポートを JSON / Markdown で出力する。

実行例:
  python scripts/investigate/audit_download_spec.py
  python scripts/investigate/audit_download_spec.py --config config/config.yaml --out docs/investigation
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.config_manager import ConfigManager
from src.core.path_builder import build_save_dir
from src.core.naming import Naming, NAMING_TEMPLATE_VARIABLES
from src.models.config_model import AppConfig, SavePaths
from src.models.file_info import FileInfo
from src.utils.logger import Logger


# 要件ドキュメント上の期待（docs/requirements.md / README より）
SPEC_EXPECTATIONS = {
    "naming_rule_example": "{category}_{title}_{date}_{index}",
    "agency_folders_readme_default": False,
    "agency_folders_code_default": False,
    "folder_should_include_koji_name_when_subfolders": True,
    "filename_should_reflect_metadata": True,
    "save_path_visible_to_user_on_complete": True,
}


def _load_config(config_path: Optional[str]) -> AppConfig:
    mgr = ConfigManager(config_path or str(_PROJECT_ROOT / "config" / "config.yaml"), Logger())
    return mgr.load_config()


def _parse_recent_download_log(log_path: Path, max_lines: int = 500) -> Dict[str, Any]:
    if not log_path.exists():
        return {"error": f"log not found: {log_path}"}

    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()[-max_lines:]

    save_paths: List[str] = []
    skips: List[Dict[str, str]] = []
    completes: List[str] = []
    summary: Optional[str] = None

    for line in lines:
        if "保存先:" in line and "発注機関フォルダ" not in line:
            m = re.search(r"保存先:\s*(.+)$", line)
            if m:
                save_paths.append(m.group(1).strip())
        if "スキップ（重複:" in line:
            m = re.search(r"スキップ（重複:\s*(\w+)）:\s*(.+)$", line)
            if m:
                skips.append({"reason": m.group(1), "path": m.group(2).strip()})
        if "ダウンロード完了:" in line and "成功=" in line:
            summary = line.split(" - ", 1)[-1].strip()
        if "ファイルダウンロード完了:" in line:
            m = re.search(r"ファイルダウンロード完了:\s*(.+)$", line)
            if m:
                completes.append(m.group(1).strip())

    skip_reasons = Counter(s["reason"] for s in skips)
    unique_dirs = sorted({str(Path(p).parent) for p in save_paths})

    return {
        "summary_line": summary,
        "save_path_samples": save_paths[:5],
        "save_path_count": len(save_paths),
        "unique_parent_dirs": unique_dirs[:10],
        "unique_parent_dir_count": len(unique_dirs),
        "completed_files": len(completes),
        "skip_count": len(skips),
        "skip_reasons": dict(skip_reasons),
        "filename_samples": [Path(p).name for p in save_paths[:8]],
    }


def _analyze_history(history_path: Path, limit: int = 200) -> Dict[str, Any]:
    if not history_path.exists():
        return {"error": f"history not found: {history_path}"}

    records: List[dict] = []
    for line in history_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    recent = records[-limit:]
    path_patterns = Counter()
    naming_styles = Counter()
    for r in recent:
        fp = r.get("file_path", "")
        parent = str(Path(fp).parent.name) if fp else ""
        if parent:
            path_patterns[parent] += 1
        fname = Path(fp).name if fp else ""
        if re.match(r"^\d+\.pdf$", fname):
            naming_styles["index_only"] += 1
        elif re.match(r"^_.*_\d{8}_\d+\.pdf$", fname):
            naming_styles["legacy_title_date_index"] += 1
        elif "_" in fname:
            naming_styles["descriptive"] += 1
        else:
            naming_styles["other"] += 1

    return {
        "total_records": len(records),
        "recent_analyzed": len(recent),
        "naming_style_counts": dict(naming_styles),
        "sample_paths": [r.get("file_path") for r in recent[-5:]],
        "top_parent_folder_names": path_patterns.most_common(8),
    }


def _simulate_paths(config: AppConfig) -> Dict[str, Any]:
    """代表メタデータで保存パスをシミュレート"""
    sample_files = [
        FileInfo(
            url="https://example.com/a.pdf",
            filename="入札公告.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国の機関",
                "chubunrui": "国土交通省",
                "shoubunrui": "東北地方整備局",
                "saibunrui": "",
                "search_tab": "works",
                "koji_name": "桂巣トンネル外照明設備工事",
                "title": "入札公告",
                "category": "入札公告",
                "date": "2026-02-01",
            },
        ),
        FileInfo(
            url="https://example.com/b.pdf",
            filename="設計書.pdf",
            file_type=".pdf",
            metadata={
                "daibunrui": "国の機関",
                "chubunrui": "国土交通省",
                "shoubunrui": "東北地方整備局",
                "saibunrui": "",
                "search_tab": "works",
                "koji_name": "猪ノ鼻トンネル外照明設備工事",
                "title": "設計書",
                "category": "設計書",
            },
        ),
    ]

    naming = Naming(config.naming_rule, Logger(), config.search_conditions)
    base = Path(config.save_paths.local)
    results = []

    for idx, fi in enumerate(sample_files):
        entry: Dict[str, Any] = {"index": idx, "koji_name": fi.metadata.get("koji_name")}
        if config.save_paths.enable_agency_root_folders:
            save_dir = build_save_dir(base, fi, config, logger=None)
            entry["agency_mode_dir"] = str(save_dir)
            entry["use_subfolders_bypassed"] = True
        elif config.save_paths.use_subfolders:
            save_dir = base / naming.generate_folder_name(fi)
            entry["subfolder_mode_dir"] = str(save_dir)
        else:
            save_dir = base
            entry["flat_dir"] = str(save_dir)

        fname = naming.generate_filename(fi, fi.metadata, idx)
        entry["filename"] = fname
        entry["full_path"] = str(save_dir / fname)
        results.append(entry)

    same_dir = len({r.get("agency_mode_dir") or r.get("subfolder_mode_dir") or r.get("flat_dir") for r in results}) == 1
    return {"simulations": results, "multiple_koji_same_dir_when_agency_on": same_dir}


def _collect_gaps(config: AppConfig, log_info: dict, history_info: dict, sim: dict, config_path: str) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    sp = config.save_paths
    service_src = (_PROJECT_ROOT / "src" / "app" / "service.py").read_text(encoding="utf-8")
    naming = Naming(config.naming_rule, Logger(), config.search_conditions)
    sample_meta = {
        "date": "1999-01-15",
        "category": "入札公告",
        "title": "テスト公告",
    }
    sample_fi = FileInfo(
        url="https://example.com/x.pdf",
        filename="x.pdf",
        file_type=".pdf",
        metadata=sample_meta,
    )
    sample_fname = naming.generate_filename(sample_fi, sample_meta, 0)

    # P0: ユーザー体験に直結
    if sp.enable_agency_root_folders and sim.get("multiple_koji_same_dir_when_agency_on"):
        gaps.append({
            "id": "GAP-001",
            "priority": "P0",
            "fr": "FR-013",
            "title": "発注機関フォルダON時に工事件ごとのサブフォルダが消える",
            "expected": "メタデータ（工事名等）に基づき分類保存（README: トンネル/工事名フォルダ）",
            "actual": "全工事のファイルが同一フォルダ（…/工事_入札公告等/）にフラット配置",
            "evidence": "downloader.py: build_save_dir_fn 使用時 use_subfolders/generate_folder_name をスキップ",
        })

    if config.naming_rule.strip() in ("{index}", "{index}{ext}"):
        gaps.append({
            "id": "GAP-002",
            "priority": "P0",
            "fr": "FR-009",
            "title": "命名規則が連番のみで文書種別・工事名が失われる",
            "expected": "テンプレ例: {category}_{title}_{date}_{index} で識別可能なファイル名",
            "actual": f"naming_rule='{config.naming_rule}' → 0.pdf, 1.pdf 等",
            "evidence": f"config.naming_rule, history naming styles: {history_info.get('naming_style_counts')}",
        })

    if SavePaths().enable_agency_root_folders != SPEC_EXPECTATIONS["agency_folders_readme_default"]:
        gaps.append({
            "id": "GAP-003",
            "priority": "P1",
            "fr": "FR-012/FR-SET",
            "title": "発注機関フォルダのデフォルトが README とコードで不一致",
            "expected": "README: デフォルト OFF",
            "actual": f"SavePaths.enable_agency_root_folders コードデフォルト={SavePaths().enable_agency_root_folders}, 現設定={sp.enable_agency_root_folders}",
            "evidence": "config_model.py vs README.md",
        })

    if log_info.get("unique_parent_dir_count", 0) <= 1 and log_info.get("save_path_count", 0) > 3:
        gaps.append({
            "id": "GAP-004",
            "priority": "P0",
            "fr": "FR-012",
            "title": "保存先がユーザー想定と乖離（深い階層・単一フォルダ）",
            "expected": "指定フォルダ直下または分かりやすいサブフォルダ",
            "actual": f"親ディレクトリ数={log_info.get('unique_parent_dir_count')}, 例={log_info.get('unique_parent_dirs', [])[:1]}",
            "evidence": "logs/app.log 保存先行",
        })

    skip_total = log_info.get("skip_count", 0)
    complete_total = log_info.get("completed_files", 0)
    if skip_total > complete_total and skip_total > 0:
        gaps.append({
            "id": "GAP-005",
            "priority": "P1",
            "fr": "FR-008",
            "title": "重複スキップが多く、新規取得件数が少ない",
            "expected": "初回は全件保存、再実行時のみスキップ",
            "actual": f"スキップ={skip_total}, 新規完了={complete_total}, 理由={log_info.get('skip_reasons')}",
            "evidence": "index ベース命名 + URL 履歴により同一パスに既存ファイル",
        })

    # naming date uses metadata when available
    if "19990115" not in sample_fname:
        gaps.append({
            "id": "GAP-006",
            "priority": "P2",
            "fr": "FR-009",
            "title": "命名の {date} が HTML メタデータではなく実行日",
            "expected": "公告日等のメタデータ日付を優先",
            "actual": f"metadata date=1999-01-15 だが生成ファイル名={sample_fname}",
            "evidence": "src/core/naming.py _resolve_date_for_naming",
        })

    yaml_text = Path(config_path).read_text(encoding="utf-8")
    if "enable_agency_root_folders" not in yaml_text:
        gaps.append({
            "id": "GAP-007",
            "priority": "P1",
            "fr": "FR-019",
            "title": "config.yaml に save_paths 拡張項目が未記載",
            "expected": "有効な設定が YAML に明示され GUI と一致",
            "actual": "enable_agency_root_folders 等が未記載のためコードデフォルトが暗黙適用",
            "evidence": config_path,
        })

    if "summarize_skips" not in service_src or "スキップ内訳" not in service_src:
        gaps.append({
            "id": "GAP-008",
            "priority": "P2",
            "fr": "FR-005",
            "title": "完了サマリーが保存先・スキップ内訳を十分に示さない",
            "expected": "成功件数と実保存ファイル数の一致、保存先フォルダの明示",
            "actual": f"サマリー例: {log_info.get('summary_line')}",
            "evidence": "service.py 完了メッセージ",
        })

    gap_report = _PROJECT_ROOT / "docs" / "requirement_gap_report.md"
    if gap_report.exists():
        report_text = gap_report.read_text(encoding="utf-8")
        if "発注機関フォルダ" in report_text and "デフォルト OFF" not in report_text:
            gaps.append({
                "id": "GAP-009",
                "priority": "P2",
                "fr": "—",
                "title": "要件トレーサビリティ文書が実態と乖離",
                "expected": "requirement_gap_report.md が現状を反映",
                "actual": "FR-013/FR-009 の記載が発注機関モード・命名改善前の前提のまま",
                "evidence": "docs/requirement_gap_report.md",
            })

    return gaps


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# ダウンロード仕様 乖離調査レポート",
        "",
        f"生成日時: {report['generated_at']}",
        f"設定: `{report['config_path']}`",
        "",
        "## 現行設定サマリー",
        "",
        f"| 項目 | 値 |",
        f"|------|-----|",
    ]
    cs = report["config_summary"]
    for k, v in cs.items():
        lines.append(f"| {k} | `{v}` |")

    lines.extend(["", "## ログ・履歴からの観測", ""])
    lines.append(f"- 直近ログ: {json.dumps(report['log_analysis'], ensure_ascii=False, indent=2)}")
    lines.append(f"- 履歴: {json.dumps(report['history_analysis'], ensure_ascii=False, indent=2)}")

    lines.extend(["", "## パスシミュレーション", ""])
    for s in report["path_simulation"]["simulations"]:
        lines.append(f"- **{s.get('koji_name')}** → `{s.get('full_path')}`")

    lines.extend(["", "## 乖離一覧", ""])
    for g in report["gaps"]:
        lines.extend([
            f"### {g['id']} [{g['priority']}] {g['title']} ({g['fr']})",
            f"- **期待**: {g['expected']}",
            f"- **実態**: {g['actual']}",
            f"- **根拠**: {g['evidence']}",
            "",
        ])

    lines.extend(["", "## 改善方針（実装前）", ""])
    for step in report["improvement_plan"]:
        lines.append(f"{step}")

    return "\n".join(lines)


def run_audit(config_path: Optional[str], out_dir: Path) -> Dict[str, Any]:
    cfg_path = config_path or str(_PROJECT_ROOT / "config" / "config.yaml")
    config = _load_config(cfg_path)
    log_path = _PROJECT_ROOT / "logs" / "app.log"
    history_path = _PROJECT_ROOT / "logs" / "download_history.jsonl"

    log_info = _parse_recent_download_log(log_path)
    history_info = _analyze_history(history_path)
    sim = _simulate_paths(config)

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "config_path": cfg_path,
        "config_summary": {
            "save_paths.local": config.save_paths.local,
            "enable_agency_root_folders": config.save_paths.enable_agency_root_folders,
            "use_subfolders": config.save_paths.use_subfolders,
            "run_subfolder_mode": config.save_paths.run_subfolder_mode,
            "naming_rule": config.naming_rule,
            "date_partition": config.save_paths.date_partition,
        },
        "spec_expectations": SPEC_EXPECTATIONS,
        "naming_template_variables": list(NAMING_TEMPLATE_VARIABLES),
        "log_analysis": log_info,
        "history_analysis": history_info,
        "path_simulation": sim,
        "gaps": _collect_gaps(config, log_info, history_info, sim, cfg_path),
        "improvement_plan": [
            "1. **保存戦略の統一**: 発注機関フォルダ ON 時も `koji_name`（工事名）サブフォルダを維持する。`path_builder` に `koji_name` 階層を追加し、`use_subfolders` と排他にしない。",
            "2. **命名規則のデフォルト修正**: `naming_rule` デフォルトを `{category}_{title}_{date}_{index}{ext}` に戻し、設定画面にプレビューを表示（FR-SET-010）。",
            "3. **設定の明示化**: `config.example.yaml` / GUI 保存時に `enable_agency_root_folders` を必ず書き出し、README のデフォルト記述とコードデフォルトを一致させる（OFF 推奨）。",
            "4. **完了 UX**: 完了メッセージに保存先ルート＋新規保存ファイル一覧（最大5件）を表示。スキップ理由別件数を GUI ログに出力。",
            "5. **重複判定の見直し**: 同一フォルダ内の index 衝突を避けるため、パスに `koji_name` または `AnkenKanriNo` を含める。URL スキップ時は『既存ファイルのパス』をログに出す。",
            "6. **メタデータ日付**: `{date}` は公告日等の HTML メタデータを優先し、無い場合のみ実行日。",
            "7. **ドキュメント更新**: requirement_gap_report / TRACEABILITY を再監査し、本レポートを正とする。",
            "8. **回帰テスト**: 発注機関 ON/OFF × naming_rule 組み合わせの統合テストを追加。",
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"download_spec_audit_{ts}.json"
    md_path = out_dir / f"download_spec_audit_{ts}.md"
    latest_md = out_dir / "DOWNLOAD_SPEC_GAP_REPORT.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_content = _render_markdown(report)
    md_path.write_text(md_content, encoding="utf-8")
    latest_md.write_text(md_content, encoding="utf-8")

    report["output"] = {"json": str(json_path), "markdown": str(md_path), "latest": str(latest_md)}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="ダウンロード仕様の要件突合監査")
    parser.add_argument("--config", default=None, help="設定ファイルパス")
    parser.add_argument("--out", default=str(_PROJECT_ROOT / "docs" / "investigation"), help="出力ディレクトリ")
    args = parser.parse_args()

    report = run_audit(args.config, Path(args.out))
    print(f"監査完了: {len(report['gaps'])} 件の乖離")
    print(f"レポート: {report['output']['latest']}")
    for g in report["gaps"]:
        print(f"  [{g['priority']}] {g['id']}: {g['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
