# -*- coding: utf-8 -*-
"""
サイト構造のスナップショット取得・正規化・保存

機密情報（hidden の値・cookie）は原則保存しない。name/id/type 等の構造のみ保存する。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


# 値を持たせない hidden 名（存在のみ記録）
SENSITIVE_NAMES = {"__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__EVENTTARGET", "__EVENTARGUMENT"}


def _normalize_url(url: str) -> str:
    """比較用に URL を正規化（クエリの順序等は変えずに）"""
    return url.strip().rstrip("/")


def _url_to_safe_filename(url: str, max_len: int = 80) -> str:
    """URL を安全なファイル名に変換"""
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    parsed = urlparse(url)
    path = (parsed.netloc or "") + (parsed.path or "")
    path = re.sub(r"[^\w\-.]", "_", path)[:max_len]
    return f"{path}_{h}.json"


def fetch_page(url: str, timeout: int = 30, session: Optional[requests.Session] = None) -> requests.Response:
    """1 ページ取得（Session は呼び出し側で管理してもよい）"""
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    sess.headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    return sess.get(url, timeout=timeout)


def extract_structure(html: str, url: str, skip_hidden_values: bool = True) -> Dict[str, Any]:
    """
    HTML から構造のみ抽出（値は原則保存しない）。
    返す構造:
      - url, status_code, content_type, encoding（呼び出し側で設定）
      - forms: [{ action, method }]
      - inputs: [{ name, id, type, value_saved: bool }]  ※hidden は name のみ or value 長のみ
      - selects: [{ name, id, options: [{ value, text }] }]
      - key_elements: [{ tag, id, name, onclick }]  ※主要ボタン・リンク
      - dom_keys: [id の一覧]  ※dgrSearchList 等の存在確認用
    """
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, Any] = {
        "forms": [],
        "inputs": [],
        "selects": [],
        "key_elements": [],
        "dom_keys": [],
    }
    # forms
    for form in soup.find_all("form"):
        out["forms"].append({
            "action": form.get("action"),
            "method": (form.get("method") or "get").lower(),
        })
    # inputs（hidden は名前と「値があるか」程度のみ）
    seen_inputs: set = set()
    for inp in soup.find_all("input"):
        name = inp.get("name")
        id_attr = inp.get("id")
        typ = (inp.get("type") or "text").lower()
        key = (name or "", id_attr or "")
        if key in seen_inputs:
            continue
        seen_inputs.add(key)
        if not name and not id_attr:
            continue
        entry: Dict[str, Any] = {"name": name, "id": id_attr, "type": typ}
        if typ == "hidden":
            if skip_hidden_values or (name and name in SENSITIVE_NAMES):
                entry["value_saved"] = False
                if name:
                    entry["value_len"] = len(inp.get("value") or "")
            else:
                entry["value_saved"] = True
                entry["value"] = inp.get("value", "")
        out["inputs"].append(entry)
    # selects
    for sel in soup.find_all("select"):
        name = sel.get("name")
        id_attr = sel.get("id")
        options: List[Dict[str, str]] = []
        for opt in sel.find_all("option"):
            options.append({
                "value": opt.get("value", ""),
                "text": (opt.get_text() or "").strip()[:200],
            })
        out["selects"].append({"name": name, "id": id_attr, "options_count": len(options), "options": options})
    # 主要要素（submit/button/a のうち id/name/onclick があるもの）
    for tag in soup.find_all(["input", "button", "a"], type=lambda x: x in ("submit", "button", None)):
        if tag.name == "input" and (tag.get("type") or "").lower() not in ("submit", "button", "image"):
            continue
        id_attr = tag.get("id")
        name = tag.get("name")
        onclick = tag.get("onclick")
        if id_attr or name or onclick:
            out["key_elements"].append({
                "tag": tag.name,
                "id": id_attr,
                "name": name,
                "value": tag.get("value"),
                "onclick": (onclick[:200] if onclick else None),
            })
    # DOM キー（主要 id の存在確認用）
    for tag in soup.find_all(id=True):
        out["dom_keys"].append(tag.get("id"))
    out["dom_keys"] = sorted(set(out["dom_keys"]))
    return out


def take_snapshot(
    url: str,
    timeout: int = 30,
    session: Optional[requests.Session] = None,
    skip_hidden_values: bool = True,
) -> Dict[str, Any]:
    """1 URL のスナップショットを取得して構造化 dict を返す"""
    resp = fetch_page(url, timeout=timeout, session=session)
    resp.encoding = resp.apparent_encoding or "utf-8"
    structure = extract_structure(resp.text, url, skip_hidden_values=skip_hidden_values)
    structure["url"] = _normalize_url(url)
    structure["status_code"] = resp.status_code
    structure["content_type"] = resp.headers.get("Content-Type", "")
    structure["encoding"] = resp.encoding
    return structure


def save_snapshot_dir(
    snapshots: List[Dict[str, Any]],
    base_dir: Path,
    timestamp: Optional[datetime] = None,
) -> Path:
    """
    複数 URL のスナップショットを 1 つのタイムスタンプ付きディレクトリに保存する。
    base_dir は scripts/snapshots を想定。
    """
    ts = timestamp or datetime.now()
    dir_name = ts.strftime("%Y%m%d_%H%M%S")
    out_dir = base_dir / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"timestamp": ts.isoformat(), "urls": [], "files": []}
    for data in snapshots:
        url = data.get("url", "")
        fname = _url_to_safe_filename(url)
        manifest["urls"].append(url)
        manifest["files"].append(fname)
        (out_dir / fname).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_dir
