# -*- coding: utf-8 -*-
"""
2 つのスナップショットディレクトリの構造化データを比較し、差分を重要度付きで返す。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

# 重要度
HIGH = "HIGH"
MED = "MED"
LOW = "LOW"


def _load_snapshot_dir(path: Path) -> Dict[str, Dict[str, Any]]:
    """manifest.json を読んで URL → スナップショット内容 の dict を返す"""
    manifest_file = path / "manifest.json"
    if not manifest_file.exists():
        return {}
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    by_url: Dict[str, Dict[str, Any]] = {}
    for fname in manifest.get("files", []):
        fpath = path / fname
        if not fpath.exists():
            continue
        data = json.loads(fpath.read_text(encoding="utf-8"))
        url = data.get("url", "")
        if url:
            by_url[url] = data
    return by_url


def _compare_inputs(old_list: List[Dict], new_list: List[Dict]) -> List[Tuple[str, str, Any, Any]]:
    """inputs の差分を (importance, message, old_val, new_val) のリストで返す"""
    changes: List[Tuple[str, str, Any, Any]] = []
    old_by_key = {(e.get("name"), e.get("id")): e for e in (old_list or []) if e.get("name") or e.get("id")}
    new_by_key = {(e.get("name"), e.get("id")): e for e in (new_list or []) if e.get("name") or e.get("id")}
    all_keys = set(old_by_key) | set(new_by_key)
    for key in all_keys:
        old_e = old_by_key.get(key)
        new_e = new_by_key.get(key)
        if not old_e:
            changes.append((MED, f"input 追加: name={key[0]}, id={key[1]}", None, new_e))
            continue
        if not new_e:
            changes.append((HIGH, f"input 削除: name={key[0]}, id={key[1]}", old_e, None))
            continue
        if old_e.get("type") != new_e.get("type"):
            changes.append((MED, f"input type 変更: name={key[0]}", old_e.get("type"), new_e.get("type")))
        if old_e.get("name") != new_e.get("name") or old_e.get("id") != new_e.get("id"):
            changes.append((HIGH, f"input name/id 変更: {key}", (old_e.get("name"), old_e.get("id")), (new_e.get("name"), new_e.get("id"))))
    return changes


def _compare_selects(old_list: List[Dict], new_list: List[Dict]) -> List[Tuple[str, str, Any, Any]]:
    """selects の差分（name/id 変更、options の value 体系変更）"""
    changes: List[Tuple[str, str, Any, Any]] = []
    old_by_key = {(e.get("name"), e.get("id")): e for e in (old_list or []) if e.get("name") or e.get("id")}
    new_by_key = {(e.get("name"), e.get("id")): e for e in (new_list or []) if e.get("name") or e.get("id")}
    all_keys = set(old_by_key) | set(new_by_key)
    for key in all_keys:
        old_e = old_by_key.get(key)
        new_e = new_by_key.get(key)
        if not old_e:
            changes.append((MED, f"select 追加: name={key[0]}, id={key[1]}", None, new_e))
            continue
        if not new_e:
            changes.append((HIGH, f"select 削除: name={key[0]}, id={key[1]}", old_e, None))
            continue
        if old_e.get("name") != new_e.get("name") or old_e.get("id") != new_e.get("id"):
            changes.append((HIGH, f"select name/id 変更: {key}", (old_e.get("name"), old_e.get("id")), (new_e.get("name"), new_e.get("id"))))
        old_opts = {(o.get("value"), o.get("text")) for o in old_e.get("options", [])}
        new_opts = {(o.get("value"), o.get("text")) for o in new_e.get("options", [])}
        if old_opts != new_opts:
            added = new_opts - old_opts
            removed = old_opts - new_opts
            if removed or added:
                changes.append((HIGH, f"select options 変更: name={key[0]} (value/text 体系)", {"removed": len(removed), "added": len(added)}, None))
    return changes


def _compare_forms(old_list: List[Dict], new_list: List[Dict]) -> List[Tuple[str, str, Any, Any]]:
    changes: List[Tuple[str, str, Any, Any]] = []
    if (old_list or []) != (new_list or []):
        changes.append((HIGH, "form action/method 変更", old_list, new_list))
    return changes


def _compare_dom_keys(old_keys: List[str], new_keys: List[str]) -> List[Tuple[str, str, Any, Any]]:
    """重要な DOM id の消失を HIGH で報告"""
    changes: List[Tuple[str, str, Any, Any]] = []
    old_set = set(old_keys or [])
    new_set = set(new_keys or [])
    missing = old_set - new_set
    for id_ in missing:
        if id_ in ("dgrSearchList", "drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", "drpSmallKikanInf"):
            changes.append((HIGH, f"重要 DOM id 消失: {id_}", id_, None))
        else:
            changes.append((MED, f"DOM id 消失: {id_}", id_, None))
    for id_ in new_set - old_set:
        changes.append((LOW, f"DOM id 追加: {id_}", None, id_))
    return changes


def diff_snapshots(old_dir: Path, new_dir: Path) -> List[Dict[str, Any]]:
    """
    2 つのスナップショットディレクトリを比較する。
    返り値: [ { "url": str, "importance": str, "message": str, "detail": ... }, ... ]
    """
    old_by_url = _load_snapshot_dir(old_dir)
    new_by_url = _load_snapshot_dir(new_dir)
    all_urls = set(old_by_url) | set(new_by_url)
    results: List[Dict[str, Any]] = []
    for url in sorted(all_urls):
        old_data = old_by_url.get(url)
        new_data = new_by_url.get(url)
        if not old_data:
            results.append({"url": url, "importance": MED, "message": "新規 URL のスナップショット", "detail": None})
            continue
        if not new_data:
            results.append({"url": url, "importance": HIGH, "message": "スナップショットから削除された URL", "detail": None})
            continue
        for imp, msg, old_val, new_val in _compare_forms(old_data.get("forms", []), new_data.get("forms", [])):
            results.append({"url": url, "importance": imp, "message": msg, "detail": {"old": old_val, "new": new_val}})
        for imp, msg, old_val, new_val in _compare_inputs(old_data.get("inputs", []), new_data.get("inputs", [])):
            results.append({"url": url, "importance": imp, "message": msg, "detail": {"old": old_val, "new": new_val}})
        for imp, msg, old_val, new_val in _compare_selects(old_data.get("selects", []), new_data.get("selects", [])):
            results.append({"url": url, "importance": imp, "message": msg, "detail": {"old": old_val, "new": new_val}})
        for imp, msg, old_val, new_val in _compare_dom_keys(old_data.get("dom_keys", []), new_data.get("dom_keys", [])):
            results.append({"url": url, "importance": imp, "message": msg, "detail": {"old": old_val, "new": new_val}})
    return results
