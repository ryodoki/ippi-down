# -*- coding: utf-8 -*-
"""
工事(tab=3)・業務(tab=6) 等の階層ドロップダウンを実際に操作して更新を確認する。
POST バックに必要なパラメータ（__EVENTTARGET 等）の存在確認を行う。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

from .snapshot import take_snapshot, fetch_page, extract_structure

BASE_SEARCH = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"


def _normalize_tab(url: str, tab: int) -> str:
    """URL に tab パラメータを付与（既存の query は維持）"""
    parsed = urlparse(url)
    if not parsed.path:
        parsed = urlparse(BASE_SEARCH)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["tab"] = [str(tab)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _get_hidden_inputs(soup: BeautifulSoup) -> Dict[str, str]:
    out = {}
    for inp in soup.find_all("input", type="hidden"):
        name = inp.get("name")
        if name:
            out[name] = inp.get("value", "")
    return out


def _get_select_options(soup: BeautifulSoup, select_id: str) -> List[Dict[str, str]]:
    sel = soup.find("select", id=select_id) or soup.find("select", {"name": select_id})
    if not sel:
        return []
    return [{"value": o.get("value", ""), "text": (o.get_text() or "").strip()} for o in sel.find_all("option")]


def probe_tab(
    tab: int,
    base_url: str,
    timeout: int = 30,
    do_postback: bool = True,
    postback_dropdown: str = "drpTopKikanInf",
    postback_value: Optional[str] = None,
) -> Dict[str, Any]:
    """
    指定 tab の検索ページを取得し、必要なら 1 回 POSTBACK して中分類などの変化を記録する。
    返り値: { "tab": int, "url": str, "status_code": int, "has_eventtarget": bool, "selects_before": {...}, "selects_after": {...} }
    """
    url = _normalize_tab(base_url, tab)
    sess = requests.Session()
    sess.headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    sess.headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    resp = sess.get(url, timeout=timeout)
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    hidden = _get_hidden_inputs(soup)
    has_eventtarget = "__EVENTTARGET" in hidden or any(k.startswith("__EVENT") for k in hidden)
    result: Dict[str, Any] = {
        "tab": tab,
        "url": url,
        "status_code": resp.status_code,
        "has_eventtarget": "__EVENTTARGET" in hidden,
        "has_viewstate": "__VIEWSTATE" in hidden,
        "selects_before": {},
        "selects_after": None,
        "postback_done": False,
    }
    for sid in ("drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", "drpSmallKikanInf"):
        opts = _get_select_options(soup, sid)
        if opts:
            result["selects_before"][sid] = {"count": len(opts), "options": opts[:20]}
    if not do_postback or resp.status_code != 200:
        return result
    # 1 回 POSTBACK（大分類を選択して中分類の options が変わるか確認）
    form = soup.find("form")
    action = form.get("action") if form else ""
    post_url = urljoin(url, action) if action else url
    form_data = dict(hidden)
    form_data["__EVENTTARGET"] = postback_dropdown
    form_data["__EVENTARGUMENT"] = ""
    if postback_value is None:
        first_opt = _get_select_options(soup, postback_dropdown)
        postback_value = first_opt[1]["value"] if len(first_opt) > 1 else (first_opt[0]["value"] if first_opt else "")
    form_data[postback_dropdown] = postback_value
    resp2 = sess.post(post_url, data=form_data, timeout=timeout)
    resp2.encoding = resp2.apparent_encoding or "utf-8"
    soup2 = BeautifulSoup(resp2.text, "html.parser")
    result["selects_after"] = {}
    for sid in ("drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", "drpSmallKikanInf"):
        opts = _get_select_options(soup2, sid)
        if opts:
            result["selects_after"][sid] = {"count": len(opts), "options": opts[:20]}
    result["postback_done"] = True
    return result


def run_probe(
    tabs: List[int],
    base_url: str = BASE_SEARCH,
    timeout: int = 30,
    do_postback: bool = True,
    output_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """複数 tab を probe し、結果を返す。output_dir があれば JSON で保存する。"""
    import sys
    from pathlib import Path as _Path

    _root = _Path(__file__).resolve().parents[3]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from src.utils.ssl_config import configure_ssl
    configure_ssl()

    results = []
    for tab in tabs:
        r = probe_tab(tab, base_url, timeout=timeout, do_postback=do_postback)
        results.append(r)
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "probe_result.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return results
