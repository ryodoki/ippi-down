# -*- coding: utf-8 -*-
"""ASP.NET WebForms のフォーム操作（hidden input 収集、POSTBACK データ構築）"""

from __future__ import annotations
from typing import Dict, Optional, TYPE_CHECKING

from bs4 import BeautifulSoup

from .html import parse_response_to_soup

if TYPE_CHECKING:
    from ...utils.http_client import HTTPClient
    from ...utils.logger import Logger


def get_all_hidden_inputs(soup: BeautifulSoup, logger: "Logger") -> Dict[str, str]:
    """すべての hidden input を取得"""
    hidden_inputs: Dict[str, str] = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            hidden_inputs[name] = value

    logger.debug(f"hidden inputを{len(hidden_inputs)}個取得しました")
    if hidden_inputs:
        keys_list = list(hidden_inputs.keys())[:10]
        logger.debug(f"取得したhidden inputの名前（最初の10個）: {', '.join(keys_list)}")

    if "__VIEWSTATE" in hidden_inputs:
        logger.debug(f"__VIEWSTATE: 取得済み (長さ: {len(hidden_inputs['__VIEWSTATE'])})")
    else:
        logger.warning("__VIEWSTATEが見つかりませんでした")
        viewstate_keys = [k for k in hidden_inputs if "VIEWSTATE" in k.upper()]
        if viewstate_keys:
            logger.debug(f"VIEWSTATE関連のキーが見つかりました: {viewstate_keys}")

    if "__EVENTVALIDATION" in hidden_inputs:
        logger.debug(f"__EVENTVALIDATION: 取得済み (長さ: {len(hidden_inputs['__EVENTVALIDATION'])})")
    else:
        logger.warning("__EVENTVALIDATIONが見つかりませんでした")
        ev_keys = [k for k in hidden_inputs if "EVENTVALIDATION" in k.upper()]
        if ev_keys:
            logger.debug(f"EVENTVALIDATION関連のキーが見つかりました: {ev_keys}")

    if "__VIEWSTATEGENERATOR" in hidden_inputs:
        logger.debug("__VIEWSTATEGENERATOR: 取得済み")

    return hidden_inputs


def get_all_form_inputs(soup: BeautifulSoup, logger: "Logger") -> Dict[str, str]:
    """すべてのフォームフィールド（hidden, select, text, checkbox, radio）の値を取得

    ASP.NET WebForms のページネーションでは、検索条件を維持するために
    すべてのフォームフィールドを送信する必要がある。
    """
    form_data: Dict[str, str] = {}

    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            form_data[name] = value

    for select in soup.find_all("select"):
        name = select.get("name", "")
        if name:
            selected_option = select.find("option", selected=True)
            if selected_option:
                form_data[name] = selected_option.get("value", "")
            else:
                first_option = select.find("option")
                if first_option:
                    form_data[name] = first_option.get("value", "")

    for text_input in soup.find_all("input", type="text"):
        name = text_input.get("name", "")
        value = text_input.get("value", "")
        if name:
            form_data[name] = value

    for checkbox in soup.find_all("input", type="checkbox"):
        name = checkbox.get("name", "")
        if name and checkbox.get("checked"):
            form_data[name] = checkbox.get("value", "on")

    for radio in soup.find_all("input", type="radio"):
        name = radio.get("name", "")
        if name and radio.get("checked"):
            form_data[name] = radio.get("value", "")

    logger.debug(f"全フォームフィールドを{len(form_data)}個取得しました")
    return form_data


def do_postback(
    http_client: "HTTPClient",
    url: str,
    soup: BeautifulSoup,
    event_target: str,
    logger: "Logger",
    additional_data: Optional[Dict[str, str]] = None,
) -> BeautifulSoup:
    """POSTBACK を実行して BeautifulSoup を返す"""
    form_data = get_all_hidden_inputs(soup, logger)
    form_data["__EVENTTARGET"] = event_target
    form_data["__EVENTARGUMENT"] = ""
    if additional_data:
        form_data.update(additional_data)
    response = http_client.post(url, data=form_data)
    return parse_response_to_soup(response)


def set_chubunrui_select_index(
    soup: BeautifulSoup,
    form_data: Dict[str, str],
    chubunrui_value: str,
    logger: "Logger",
) -> None:
    """中分類の選択インデックスを form_data に設定"""
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        for idx, opt in enumerate(dropdown.find_all("option")):
            if opt.get("value", "") == chubunrui_value:
                form_data["txtLgKikanInf2SelIndex_h"] = str(idx)
                logger.debug(f"中分類の選択インデックス: {idx}")
                break
