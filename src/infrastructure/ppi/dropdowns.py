# -*- coding: utf-8 -*-
"""発注機関/工事場所の階層ドロップダウン取得"""

from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from bs4 import BeautifulSoup

from .html import normalize_search_url, set_response_encoding, parse_response_to_soup
from .forms import get_all_hidden_inputs, set_chubunrui_select_index

if TYPE_CHECKING:
    from ...utils.http_client import HTTPClient
    from ...utils.logger import Logger


def get_dropdown_select(soup: BeautifulSoup, dropdown_name: str, logger: "Logger"):
    """ドロップダウン要素を取得（name→id→パターンの順でフォールバック）"""
    dropdown = soup.find("select", {"name": dropdown_name})
    if not dropdown:
        dropdown_id = dropdown_name.replace("$", "_")
        dropdown = soup.find("select", {"id": dropdown_id})
    if not dropdown:
        _FALLBACK = {
            "TopKikanInf": ["TopKikanInf", "HachuDaibunrui"],
            "HachuDaibunrui": ["TopKikanInf", "HachuDaibunrui"],
            "LargeKikanInf": ["LargeKikanInf", "HachuChubunrui"],
            "HachuChubunrui": ["LargeKikanInf", "HachuChubunrui"],
            "MiddleKikanInf": ["MiddleKikanInf", "HachuShoubunrui"],
            "HachuShoubunrui": ["MiddleKikanInf", "HachuShoubunrui"],
            "SmallKikanInf": ["SmallKikanInf", "HachuSaibunrui"],
            "HachuSaibunrui": ["SmallKikanInf", "HachuSaibunrui"],
        }
        for key, patterns in _FALLBACK.items():
            if key in dropdown_name:
                for p in patterns:
                    dropdown = soup.find("select", {"id": lambda x: x and p in str(x)})
                    if dropdown:
                        break
                    dropdown = soup.find("select", {"name": lambda x: x and p in str(x)})
                    if dropdown:
                        break
                break

    if not dropdown:
        all_selects = soup.find_all("select")
        logger.debug(f"ドロップダウンが見つかりません: {dropdown_name}")
        logger.debug(f"ページ内のselect要素数: {len(all_selects)}")
        if all_selects:
            select_names = [s.get("name", "なし") for s in all_selects[:5]]
            logger.debug(f"最初の5個のselect要素のname: {select_names}")

    return dropdown


def get_dropdown_value_from_text(
    soup: BeautifulSoup, dropdown_name: str, display_text: str, logger: "Logger"
) -> Optional[str]:
    """ドロップダウンから表示テキストに対応する value を取得"""
    dropdown = get_dropdown_select(soup, dropdown_name, logger)
    if dropdown:
        for option in dropdown.find_all("option"):
            if option.get_text().strip() == display_text:
                value = option.get("value", "")
                return value if value else None
    return None


def parse_setListItemSub(
    response_text: str, dropdown_name: str, logger: "Logger"
) -> List[Tuple[str, str]]:
    """setListItemSub() から (value, text) のリストを抽出"""
    try:
        dropdown_id = dropdown_name.replace("$", "_")
        dropdown_id_part = dropdown_id.split("_")[-1]

        logger.debug(f"setListItemSub解析開始: dropdown_name={dropdown_name}, dropdown_id={dropdown_id}")

        pattern = rf"setListItemSub\s*\(\s*['\"]([^'\"]*{re.escape(dropdown_id_part)}[^'\"]*)['\"]\s*,\s*\[(.*?)\]\s*\)"
        matches = re.findall(pattern, response_text, re.DOTALL)
        logger.debug(f"setListItemSubパターンマッチ: {len(matches)}件")

        for call_id, list_content in matches:
            if dropdown_id in call_id or dropdown_id_part in call_id:
                logger.debug(f"マッチしたsetListItemSub呼び出し: ID={call_id}")
                items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
                options = _parse_colon_items(items, logger)
                if options:
                    logger.info(f"setListItemSubから{len(options)}個のオプションを抽出しました")
                    return options

        pattern_var = rf"setListItemSub\s*\(\s*['\"]([^'\"]*{re.escape(dropdown_id_part)}[^'\"]*)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
        matches_var = re.findall(pattern_var, response_text)
        logger.debug(f"setListItemSub変数形式パターンマッチ: {len(matches_var)}件")

        for call_id, var_name in matches_var:
            if dropdown_id in call_id or dropdown_id_part in call_id:
                logger.debug(f"マッチしたsetListItemSub呼び出し（変数形式）: ID={call_id}, VAR={var_name}")
                var_pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\];"
                var_matches = re.findall(var_pattern, response_text, re.DOTALL)
                if var_matches:
                    logger.debug(f"変数定義が見つかりました: {var_name}")
                    items = re.findall(r"['\"]([^'\"]+)['\"]", var_matches[0])
                    options = _parse_colon_items(items, logger)
                    if options:
                        logger.info(f"setListItemSub（変数形式）から{len(options)}個のオプションを抽出しました")
                        return options

        return []

    except Exception as e:
        logger.error(f"setListItemSub解析エラー: {str(e)}", exc_info=True)
        return []


def _parse_colon_items(items: List[str], logger: "Logger") -> List[Tuple[str, str]]:
    """'value:text' 形式のリストを (value, text) に変換"""
    options: List[Tuple[str, str]] = []
    for item in items:
        if ":" in item:
            parts = item.split(":", 1)
            if len(parts) == 2:
                options.append((parts[0], parts[1]))
                logger.debug(f"  オプション: value={parts[0]}, text={parts[1]}")
            else:
                options.append((item, item))
        else:
            options.append((item, item))
    return options


def parse_txtLargeKikanInf_h(
    txt: str, target_key: str, logger: "Logger"
) -> List[Tuple[str, str]]:
    """txtLargeKikanInf_h からエントリを抽出（Common.js の getListItemStr と同じロジック）"""
    try:
        entries = txt.split(":")
        chubunrui_entry_index = None
        for i, entry in enumerate(entries):
            parts = entry.split(",")
            if len(parts) >= 3 and parts[2] == target_key:
                chubunrui_entry_index = i
                break

        if chubunrui_entry_index is None:
            logger.debug(f"中分類値 '{target_key}' が見つかりませんでした")
            return []

        options: List[Tuple[str, str]] = []
        for i in range(chubunrui_entry_index + 1, len(entries)):
            parts = entries[i].split(",")
            if len(parts) >= 3:
                if parts[2] == target_key:
                    options.append((parts[0], parts[1]))
                    logger.debug(f"小分類を発見: '{parts[1]}' -> '{parts[0]}'")
                else:
                    break

        logger.info(f"txtLargeKikanInf_hから中分類値 '{target_key}' の小分類を{len(options)}個抽出しました")
        return options
    except Exception as e:
        logger.error(f"txtLargeKikanInf_h解析エラー: {str(e)}", exc_info=True)
        return []


def parse_html_options(
    soup: BeautifulSoup, dropdown_name: str, logger: "Logger"
) -> List[Tuple[str, str]]:
    """HTML の <select><option> から (value, text) のリストを抽出"""
    dropdown = get_dropdown_select(soup, dropdown_name, logger)
    if dropdown:
        options: List[Tuple[str, str]] = []
        for option in dropdown.find_all("option"):
            text = option.get_text().strip()
            value = option.get("value", "")
            if text:
                options.append((value if value else text, text))
        return options
    return []


# ────────────────────────────────────────────────────────
# 公開 API: GUI/サービスから呼ばれるドロップダウン取得関数
# ────────────────────────────────────────────────────────


def fetch_dropdown_options(
    http_client: "HTTPClient",
    search_url: str,
    dropdown_name: str,
    logger: "Logger",
    parent_values: Optional[Dict[str, str]] = None,
) -> List[str]:
    """階層ドロップダウンのオプションを取得（表示テキストのリスト）"""
    try:
        normalized_url = normalize_search_url(search_url)
        logger.debug(f"ドロップダウンオプション取得開始: {dropdown_name}, URL={normalized_url}")

        initial_soup = _fetch_page(http_client, normalized_url, logger)
        if not initial_soup:
            logger.warning("検索ページの取得に失敗しました")
            return []

        form_data = get_all_hidden_inputs(initial_soup, logger)
        form_data["__EVENTTARGET"] = dropdown_name
        form_data["__EVENTARGUMENT"] = ""

        if parent_values:
            for key, value in parent_values.items():
                form_data[key] = value
                logger.debug(f"親ドロップダウンを設定: {key}={value}")

        logger.debug(f"POST送信: form_dataのキー数={len(form_data)}")
        logger.debug(f"form_dataのキー: {', '.join(list(form_data.keys())[:20])}")

        response = http_client.post(normalized_url, data=form_data)
        if response.status_code == 405:
            logger.error("405 Method Not Allowed エラーが発生しました")
            return []

        logger.debug(f"POSTレスポンス: status_code={response.status_code}")
        set_response_encoding(response)
        response_text = response.text

        if "setListItemSub" in response_text:
            logger.debug("レスポンスにsetListItemSubが含まれています")
            options_from_js = parse_setListItemSub(response_text, dropdown_name, logger)
            if options_from_js:
                display_texts = [text for _, text in options_from_js]
                logger.info(f"setListItemSub()から{len(display_texts)}個のオプションを取得しました")
                return display_texts
            else:
                logger.debug("setListItemSub()からオプションを抽出できませんでした")
        else:
            logger.debug("レスポンスにsetListItemSubが含まれていません")

        soup = parse_response_to_soup(response)
        options_from_html = parse_html_options(soup, dropdown_name, logger)
        if options_from_html:
            display_texts = [text for _, text in options_from_html]
            logger.info(f"HTMLから{len(display_texts)}個のオプションを取得しました")
            return display_texts

        logger.warning(f"ドロップダウンオプションを取得できませんでした: {dropdown_name}")
        return []

    except Exception as e:
        logger.error(f"ドロップダウンオプション取得エラー: {dropdown_name} - {str(e)}", exc_info=True)
        return []


def fetch_hachu_daibunrui(
    http_client: "HTTPClient", search_url: str, logger: "Logger"
) -> List[str]:
    """大分類のオプションを取得"""
    try:
        normalized_url = normalize_search_url(search_url)
        soup = _fetch_page(http_client, normalized_url, logger)
        if not soup:
            logger.warning("検索ページの取得に失敗しました（大分類）")
            return []
        dropdown = get_dropdown_select(soup, "drpTopKikanInf", logger)
        if dropdown:
            options = [opt.get_text().strip() for opt in dropdown.find_all("option") if opt.get_text().strip()]
            logger.info(f"大分類オプション取得成功: {len(options)}件")
            return options
        else:
            logger.warning("大分類のドロップダウンが見つかりません")
            return []
    except Exception as e:
        logger.error(f"大分類オプション取得エラー: {str(e)}", exc_info=True)
        return []


def fetch_hachu_chubunrui(
    http_client: "HTTPClient", search_url: str, daibunrui_value: str, logger: "Logger"
) -> List[str]:
    """中分類のオプションを取得（大分類の表示テキストを指定）"""
    try:
        normalized_url = normalize_search_url(search_url)
        initial_soup = _fetch_page(http_client, normalized_url, logger)
        if not initial_soup:
            return []
        parent_value = get_dropdown_value_from_text(initial_soup, "drpTopKikanInf", daibunrui_value, logger)
        if not parent_value:
            logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
            return []
        logger.debug(f"大分類のvalueを取得: {daibunrui_value} -> {parent_value}")
        return fetch_dropdown_options(http_client, normalized_url, "drpLargeKikanInf2", logger, {"drpTopKikanInf": parent_value})
    except Exception as e:
        logger.error(f"中分類オプション取得エラー: {str(e)}", exc_info=True)
        return []


def fetch_hachu_shoubunrui(
    http_client: "HTTPClient",
    search_url: str,
    daibunrui_value: str,
    chubunrui_value: str,
    logger: "Logger",
) -> List[str]:
    """小分類のオプションを取得"""
    try:
        normalized_url = normalize_search_url(search_url)
        initial_soup = _fetch_page(http_client, normalized_url, logger)
        if not initial_soup:
            return []

        pv1 = get_dropdown_value_from_text(initial_soup, "drpTopKikanInf", daibunrui_value, logger)
        if not pv1:
            logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
            return []

        form_data = get_all_hidden_inputs(initial_soup, logger)
        form_data.update({"__EVENTTARGET": "drpTopKikanInf", "__EVENTARGUMENT": "", "drpTopKikanInf": pv1})
        resp1 = http_client.post(normalized_url, data=form_data)
        soup2 = parse_response_to_soup(resp1)

        pv2 = get_dropdown_value_from_text(soup2, "drpLargeKikanInf2", chubunrui_value, logger)
        if not pv2:
            logger.warning(f"中分類のvalueが見つかりませんでした: {chubunrui_value}")
            return []

        additional = {
            "drpTopKikanInf": pv1,
            "drpLargeKikanInf2": pv2,
            "txtLgKikanInfSelValue_h": f"{chubunrui_value},{pv2}",
        }
        set_chubunrui_select_index(soup2, additional, pv2, logger)

        fd2 = get_all_hidden_inputs(soup2, logger)
        fd2.update({"__EVENTTARGET": "drpLargeKikanInf2", "__EVENTARGUMENT": "", **additional})
        resp2 = http_client.post(normalized_url, data=fd2)
        set_response_encoding(resp2)
        response_text2 = resp2.text
        soup3 = parse_response_to_soup(resp2)

        if "setListItemSub" in response_text2:
            opts = parse_setListItemSub(response_text2, "drpMiddleKikanInf", logger)
            if opts:
                texts = [t for _, t in opts]
                logger.info(f"setListItemSub()から小分類{len(texts)}個のオプションを取得しました")
                return texts

        dropdown = get_dropdown_select(soup3, "drpMiddleKikanInf", logger)
        if dropdown:
            options = []
            for opt in dropdown.find_all("option"):
                text = opt.get_text().strip()
                value = opt.get("value", "")
                if text and value != "-1":
                    options.append(text)
            if options:
                logger.info(f"HTMLから小分類{len(options)}個のオプションを取得しました")
                return options

        logger.warning("小分類のオプションを取得できませんでした")
        return []

    except Exception as e:
        logger.error(f"小分類オプション取得エラー: {str(e)}", exc_info=True)
        return []


def fetch_hachu_saibunrui(
    http_client: "HTTPClient",
    search_url: str,
    daibunrui_value: str,
    chubunrui_value: str,
    shoubunrui_value: str,
    logger: "Logger",
) -> List[str]:
    """細分類のオプションを取得"""
    try:
        normalized_url = normalize_search_url(search_url)
        initial_soup = _fetch_page(http_client, normalized_url, logger)
        if not initial_soup:
            return []

        pv1 = get_dropdown_value_from_text(initial_soup, "drpTopKikanInf", daibunrui_value, logger)
        if not pv1:
            logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
            return []

        from .forms import do_postback
        soup2 = do_postback(http_client, normalized_url, initial_soup, "drpTopKikanInf", logger, {"drpTopKikanInf": pv1})

        pv2 = get_dropdown_value_from_text(soup2, "drpLargeKikanInf2", chubunrui_value, logger)
        if not pv2:
            logger.warning(f"中分類のvalueが見つかりませんでした: {chubunrui_value}")
            return []

        additional2 = {
            "drpTopKikanInf": pv1,
            "drpLargeKikanInf2": pv2,
            "txtLgKikanInfSelValue_h": f"{chubunrui_value},{pv2}",
        }
        set_chubunrui_select_index(soup2, additional2, pv2, logger)
        soup3 = do_postback(http_client, normalized_url, soup2, "drpLargeKikanInf2", logger, additional2)

        pv3 = get_dropdown_value_from_text(soup3, "drpMiddleKikanInf", shoubunrui_value, logger)
        if not pv3:
            logger.warning(f"小分類のvalueが見つかりませんでした: {shoubunrui_value}")
            return []

        fd3 = get_all_hidden_inputs(soup3, logger)
        fd3.update({
            "__EVENTTARGET": "drpMiddleKikanInf",
            "__EVENTARGUMENT": "",
            "drpTopKikanInf": pv1,
            "drpLargeKikanInf2": pv2,
            "drpMiddleKikanInf": pv3,
        })
        resp3 = http_client.post(normalized_url, data=fd3)
        set_response_encoding(resp3)
        response_text3 = resp3.text
        soup4 = parse_response_to_soup(resp3)

        if "setListItemSub" in response_text3:
            opts = parse_setListItemSub(response_text3, "drpSmallKikanInf", logger)
            if opts:
                texts = [t for _, t in opts]
                logger.info(f"setListItemSub()から細分類{len(texts)}個のオプションを取得しました")
                return texts

        dropdown = get_dropdown_select(soup4, "drpSmallKikanInf", logger)
        if dropdown:
            options = []
            for opt in dropdown.find_all("option"):
                text = opt.get_text().strip()
                value = opt.get("value", "")
                if text and value != "-1":
                    options.append(text)
            if options:
                logger.info(f"HTMLから細分類{len(options)}個のオプションを取得しました")
                return options

        logger.warning("細分類のオプションを取得できませんでした")
        return []

    except Exception as e:
        logger.error(f"細分類オプション取得エラー: {str(e)}", exc_info=True)
        return []


def fetch_koji_prefecture(
    http_client: "HTTPClient",
    search_url: str,
    district_text: str,
    logger: "Logger",
) -> List[str]:
    """工事場所・都道府県のオプションを取得"""
    try:
        normalized_url = normalize_search_url(search_url)
        initial_soup = _fetch_page(http_client, normalized_url, logger)
        if not initial_soup:
            logger.warning("検索ページの取得に失敗しました（都道府県オプション）")
            return []
        district_value = get_dropdown_value_from_text(initial_soup, "drpKojiDistrict", district_text, logger)
        if not district_value:
            logger.warning(f"地方のvalueが見つかりませんでした: {district_text}")
            return []
        form_data = get_all_hidden_inputs(initial_soup, logger)
        form_data.update({
            "__EVENTTARGET": "drpKojiDistrict",
            "__EVENTARGUMENT": "",
            "KojiRadioGroup": "rbKojiDropList",
            "drpKojiDistrict": district_value,
        })
        response = http_client.post(normalized_url, data=form_data)
        set_response_encoding(response)
        response_text = response.text
        soup = parse_response_to_soup(response)
        if "setListItemSub" in response_text:
            opts = parse_setListItemSub(response_text, "drpKojiPrefecture2", logger)
            if opts:
                return [text for _, text in opts]
        html_opts = parse_html_options(soup, "drpKojiPrefecture2", logger)
        if html_opts:
            return [text for _, text in html_opts]
        return []
    except Exception as e:
        logger.error(f"都道府県オプション取得エラー: {str(e)}", exc_info=True)
        return []


def fetch_koji_city(
    http_client: "HTTPClient",
    search_url: str,
    district_text: str,
    prefecture_text: str,
    logger: "Logger",
) -> List[str]:
    """工事場所・市町村のオプションを取得"""
    try:
        normalized_url = normalize_search_url(search_url)
        initial_soup = _fetch_page(http_client, normalized_url, logger)
        if not initial_soup:
            return []
        district_value = get_dropdown_value_from_text(initial_soup, "drpKojiDistrict", district_text, logger)
        if not district_value:
            logger.warning(f"地方のvalueが見つかりませんでした: {district_text}")
            return []
        form_data = get_all_hidden_inputs(initial_soup, logger)
        form_data.update({
            "__EVENTTARGET": "drpKojiDistrict",
            "__EVENTARGUMENT": "",
            "KojiRadioGroup": "rbKojiDropList",
            "drpKojiDistrict": district_value,
        })
        resp1 = http_client.post(normalized_url, data=form_data)
        set_response_encoding(resp1)
        soup2 = parse_response_to_soup(resp1)

        pref_value = get_dropdown_value_from_text(soup2, "drpKojiPrefecture2", prefecture_text, logger)
        if not pref_value:
            logger.warning(f"都道府県のvalueが見つかりませんでした: {prefecture_text}")
            return []

        fd2 = get_all_hidden_inputs(soup2, logger)
        fd2.update({
            "__EVENTTARGET": "drpKojiPrefecture2",
            "__EVENTARGUMENT": "",
            "KojiRadioGroup": "rbKojiDropList",
            "drpKojiDistrict": district_value,
            "drpKojiPrefecture2": pref_value,
        })
        resp2 = http_client.post(normalized_url, data=fd2)
        set_response_encoding(resp2)
        response_text2 = resp2.text
        soup3 = parse_response_to_soup(resp2)

        if "setListItemSub" in response_text2:
            opts = parse_setListItemSub(response_text2, "drpKojiCity", logger)
            if opts:
                return [text for _, text in opts]
        html_opts = parse_html_options(soup3, "drpKojiCity", logger)
        if html_opts:
            return [text for _, text in html_opts]
        return []
    except Exception as e:
        logger.error(f"市町村オプション取得エラー: {str(e)}", exc_info=True)
        return []


# ─── ヘルパー ─────────────────────────────────────────


def _fetch_page(
    http_client: "HTTPClient", url: str, logger: "Logger"
) -> Optional[BeautifulSoup]:
    """ページを取得して BeautifulSoup を返す（GET）"""
    try:
        logger.info(f"ページを取得中: {url}")
        response = http_client.get(url)
        return parse_response_to_soup(response)
    except Exception as e:
        logger.error(f"ページ取得エラー: {url} - {str(e)}", exc_info=True)
        return None
