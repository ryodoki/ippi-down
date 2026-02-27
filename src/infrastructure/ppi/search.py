# -*- coding: utf-8 -*-
"""検索フォーム送信・結果ページからの案件抽出"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

from .html import normalize_search_url, parse_response_to_soup
from .forms import get_all_hidden_inputs, get_all_form_inputs, do_postback, set_chubunrui_select_index
from .dropdowns import get_dropdown_value_from_text
from .detail import (
    extract_file_links,
    extract_files_from_detail_via_postback,
    extract_files_from_detail_page,
)
from ...models.file_info import FileInfo
from ...models.config_model import SearchConditions

if TYPE_CHECKING:
    from ...utils.http_client import HTTPClient
    from ...utils.logger import Logger


def infer_search_tab_from_url(url: str) -> str:
    """URL の tab パラメータまたはパスから検索種別を推定"""
    if not url:
        return "unknown"
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        tab = (qs.get("tab") or [None])[0]
        if tab == "4":
            return "works"
        if tab == "6":
            return "services"
        path = (parsed.path or "").lower()
        if "searchworks" in path:
            return "works"
        return tab if tab else "unknown"
    except Exception:
        return "unknown"


def ensure_agency_metadata(
    file_info: FileInfo, search_conditions: Optional[SearchConditions], base_url: str
) -> None:
    """FileInfo.metadata に発注機関階層と search_tab を補完"""
    if not file_info.metadata:
        file_info.metadata = {}
    fallback = "unknown"
    if search_conditions:
        sc = search_conditions
        for key, attr in (
            ("daibunrui", "hachu_daibunrui"),
            ("chubunrui", "hachu_chubunrui"),
            ("shoubunrui", "hachu_shoubunrui"),
            ("saibunrui", "hachu_saibunrui"),
        ):
            if key not in file_info.metadata or not file_info.metadata.get(key):
                file_info.metadata[key] = (getattr(sc, attr, "") or "").strip() or fallback
    else:
        for key in ("daibunrui", "chubunrui", "shoubunrui", "saibunrui"):
            file_info.metadata.setdefault(key, fallback)
    if "search_tab" not in file_info.metadata or not file_info.metadata.get("search_tab"):
        file_info.metadata["search_tab"] = infer_search_tab_from_url(base_url)


def fetch_page(
    http_client: "HTTPClient", url: str, logger: "Logger"
) -> Optional[BeautifulSoup]:
    """ページを取得して BeautifulSoup を返す"""
    try:
        normalized_url = normalize_search_url(url)
        logger.info(f"ページを取得中: {normalized_url}")
        response = http_client.get(normalized_url)
        return parse_response_to_soup(response)
    except Exception as e:
        logger.error(f"ページ取得エラー: {url} - {str(e)}", exc_info=True)
        return None


def submit_search_form(
    http_client: "HTTPClient",
    search_url: str,
    search_conditions: SearchConditions,
    logger: "Logger",
) -> tuple[Optional[BeautifulSoup], str]:
    """検索フォームを送信して検索結果ページを取得

    Returns:
        (結果 soup, 最終 URL)
    """
    try:
        logger.info(f"検索フォームを送信中: {search_url}")
        normalized_url = normalize_search_url(search_url)

        soup = fetch_page(http_client, normalized_url, logger)
        if not soup:
            return None, normalized_url

        daibunrui_value = chubunrui_value = shoubunrui_value = saibunrui_value = None

        # 1. 大分類
        if search_conditions.hachu_daibunrui:
            daibunrui_value = get_dropdown_value_from_text(soup, "drpTopKikanInf", search_conditions.hachu_daibunrui, logger)
            if daibunrui_value:
                logger.info(f"大分類を選択: '{search_conditions.hachu_daibunrui}' -> '{daibunrui_value}'")
                soup = do_postback(http_client, normalized_url, soup, "drpTopKikanInf", logger, {"drpTopKikanInf": daibunrui_value})
            else:
                logger.warning(f"大分類の値が取得できませんでした: '{search_conditions.hachu_daibunrui}'")

        # 2. 中分類
        if search_conditions.hachu_chubunrui and daibunrui_value:
            chubunrui_value = get_dropdown_value_from_text(soup, "drpLargeKikanInf2", search_conditions.hachu_chubunrui, logger)
            if chubunrui_value:
                logger.info(f"中分類を選択: '{search_conditions.hachu_chubunrui}' -> '{chubunrui_value}'")
                additional = {
                    "drpTopKikanInf": daibunrui_value,
                    "drpLargeKikanInf2": chubunrui_value,
                    "drpMiddleKikanInf": "-1",
                    "drpSmallKikanInf": "-1",
                    "txtLgKikanInfSelValue_h": f"{search_conditions.hachu_chubunrui},{chubunrui_value}",
                    "txt_ChangeTopKikan": "true" if daibunrui_value else "false",
                    "txt_ChangeLargeKikan": "true",
                }
                set_chubunrui_select_index(soup, additional, chubunrui_value, logger)
                soup = do_postback(http_client, normalized_url, soup, "drpLargeKikanInf2", logger, additional)
            else:
                logger.warning(f"中分類の値が取得できませんでした: '{search_conditions.hachu_chubunrui}'")

        # 3. 小分類
        if search_conditions.hachu_shoubunrui and chubunrui_value:
            shoubunrui_value = _resolve_shoubunrui(soup, search_conditions.hachu_shoubunrui, chubunrui_value, logger)

        # 4. 小分類 POSTBACK
        if search_conditions.hachu_shoubunrui and shoubunrui_value:
            logger.info(f"小分類を選択してPOSTバック: '{shoubunrui_value}'")
            additional = {
                "drpTopKikanInf": daibunrui_value,
                "drpLargeKikanInf2": chubunrui_value,
                "drpMiddleKikanInf": shoubunrui_value,
                "drpSmallKikanInf": "-1",
            }
            if chubunrui_value:
                set_chubunrui_select_index(soup, additional, chubunrui_value, logger)
            soup = do_postback(http_client, normalized_url, soup, "drpMiddleKikanInf", logger, additional)

        # 5. 細分類
        if search_conditions.hachu_saibunrui and shoubunrui_value:
            dropdown = soup.find("select", id="drpSmallKikanInf")
            if dropdown:
                for opt in dropdown.find_all("option"):
                    value = opt.get("value", "")
                    text = opt.get_text(strip=True)
                    if value != "-1" and search_conditions.hachu_saibunrui in text:
                        saibunrui_value = value
                        logger.info(f"細分類を選択: '{text}' -> '{saibunrui_value}'")
                        break
            if not saibunrui_value:
                logger.warning(f"細分類の値が取得できませんでした: '{search_conditions.hachu_saibunrui}'")

        # 5b. 工事場所（リスト）
        if (
            search_conditions.place_search_type == "list"
            and search_conditions.place_chihou
            and (search_conditions.place_todofuken or search_conditions.place_shichouson)
        ):
            dv = get_dropdown_value_from_text(soup, "drpKojiDistrict", search_conditions.place_chihou, logger)
            if dv:
                logger.debug(f"工事場所・地区のPOSTバック: '{search_conditions.place_chihou}' -> '{dv}'")
                soup = do_postback(http_client, normalized_url, soup, "drpKojiDistrict", logger, {"drpKojiDistrict": dv})

        # 6. 検索実行
        form_data = get_all_hidden_inputs(soup, logger)
        search_form_data = build_search_form_data(search_conditions, soup, logger)
        form_data.update(search_form_data)

        if daibunrui_value:
            form_data["drpTopKikanInf"] = daibunrui_value
        if chubunrui_value:
            form_data["drpLargeKikanInf2"] = chubunrui_value
        if shoubunrui_value:
            form_data["drpMiddleKikanInf"] = shoubunrui_value
            logger.info(f"小分類の値を設定: '{shoubunrui_value}'")
        if saibunrui_value:
            form_data["drpSmallKikanInf"] = saibunrui_value
        if chubunrui_value:
            set_chubunrui_select_index(soup, form_data, chubunrui_value, logger)

        response = http_client.post(normalized_url, data=form_data)
        result_soup = parse_response_to_soup(response)
        result_url = response.url
        logger.info(f"検索結果ページを取得しました (URL: {result_url})")
        return result_soup, result_url

    except Exception as e:
        logger.error(f"検索フォーム送信エラー: {str(e)}", exc_info=True)
        return None, search_url


def build_search_form_data(
    search_conditions: SearchConditions,
    initial_soup: BeautifulSoup,
    logger: "Logger",
) -> Dict[str, Any]:
    """検索フォームの POST データを構築"""
    form_data: Dict[str, Any] = {"__EVENTTARGET": "", "__EVENTARGUMENT": ""}

    if search_conditions.hachu_daibunrui:
        v = get_dropdown_value_from_text(initial_soup, "drpTopKikanInf", search_conditions.hachu_daibunrui, logger)
        if v:
            form_data["drpTopKikanInf"] = v
    if search_conditions.hachu_chubunrui:
        v = get_dropdown_value_from_text(initial_soup, "drpLargeKikanInf2", search_conditions.hachu_chubunrui, logger)
        if v:
            form_data["drpLargeKikanInf2"] = v
    if search_conditions.hachu_shoubunrui:
        v = get_dropdown_value_from_text(initial_soup, "drpMiddleKikanInf", search_conditions.hachu_shoubunrui, logger)
        if v:
            form_data["drpMiddleKikanInf"] = v
    if search_conditions.hachu_saibunrui:
        v = get_dropdown_value_from_text(initial_soup, "drpSmallKikanInf", search_conditions.hachu_saibunrui, logger)
        if v:
            form_data["drpSmallKikanInf"] = v

    if search_conditions.hachu_multi:
        form_data["txt_MultiSearchFlag"] = ",".join(search_conditions.hachu_multi)

    if search_conditions.koji_name:
        form_data["tbxKojiNm"] = search_conditions.koji_name

    if search_conditions.place_search_type == "list":
        form_data["KojiRadioGroup"] = "rbKojiDropList"
        for attr, drp in (
            ("place_chihou", "drpKojiDistrict"),
            ("place_todofuken", "drpKojiPrefecture2"),
            ("place_shichouson", "drpKojiCity"),
        ):
            val = getattr(search_conditions, attr, None)
            if val:
                v = get_dropdown_value_from_text(initial_soup, drp, val, logger)
                form_data[drp] = v if v else val

    logger.debug(
        f"place_search_type={getattr(search_conditions, 'place_search_type', None)}, "
        f"place_text={getattr(search_conditions, 'place_text', None)}"
    )
    if search_conditions.place_search_type == "text" and search_conditions.place_text:
        form_data["KojiRadioGroup"] = "rbStrKojiPlace"
        form_data["tbxKojiPlace"] = search_conditions.place_text
        logger.debug(f"POSTに tbxKojiPlace を送信: {form_data.get('tbxKojiPlace')}")

    contract_type_map = {
        "一般競争入札": "chkKojiNyusatsu1",
        "公募型指名競争入札": "chkKojiNyusatsu2",
        "指名競争入札": "chkKojiNyusatsu3",
        "随意契約": "chkKojiNyusatsu4",
        "その他方式": "chkKojiNyusatsu5",
    }
    for ct in search_conditions.contract_types:
        if ct in contract_type_map:
            form_data[contract_type_map[ct]] = "on"

    if search_conditions.update_date_type == "past" and search_conditions.update_date_days:
        form_data["LastUpdate"] = "rbtLastUpdate2"
        form_data["tbxLastUpdate"] = str(search_conditions.update_date_days)

    if search_conditions.koukoku_date_type == "range":
        form_data["KokokuDateKeika"] = "rbtKokokuDate2Keika"
        if search_conditions.koukoku_date_start:
            form_data["dateKokokuFromKeika"] = search_conditions.koukoku_date_start
        if search_conditions.koukoku_date_end:
            form_data["dateKokokuToKeika"] = search_conditions.koukoku_date_end

    if search_conditions.kaisatsu_date_type == "range":
        form_data["KaisatsuDate"] = "rbtKaisatsuDate2"
        if search_conditions.kaisatsu_date_start:
            form_data["dateKaisatsuFrom"] = search_conditions.kaisatsu_date_start
        if search_conditions.kaisatsu_date_end:
            form_data["dateKaisatsuTo"] = search_conditions.kaisatsu_date_end

    if search_conditions.keiyaku_date_type == "range":
        form_data["KeiyakuDate"] = "rbtKeiyakuDate2"
        if search_conditions.keiyaku_date_start:
            form_data["dateKeiyakuFrom"] = search_conditions.keiyaku_date_start
        if search_conditions.keiyaku_date_end:
            form_data["dateKeiyakuTo"] = search_conditions.keiyaku_date_end

    if search_conditions.koji_shubetsu:
        from ...core.ppi_dropdowns import label_to_code
        code = label_to_code("koji_shubetsu", search_conditions.koji_shubetsu, logger)
        if code:
            form_data["drpKojiKbn"] = code

    if search_conditions.koji_gyoushu:
        from ...core.ppi_dropdowns import label_to_code
        code = label_to_code("koji_gyoushu", search_conditions.koji_gyoushu, logger)
        if code:
            form_data["drpKojiGyosyu"] = code

    if search_conditions.yotei_price_min is not None:
        form_data["tbxYoteiPriceFrom"] = str(search_conditions.yotei_price_min)
    if search_conditions.yotei_price_max is not None:
        form_data["tbxYoteiPriceTo"] = str(search_conditions.yotei_price_max)

    if search_conditions.rakusatsu_price_min is not None:
        form_data["tbxRakusatsuPriceFrom"] = str(search_conditions.rakusatsu_price_min)
    if search_conditions.rakusatsu_price_max is not None:
        form_data["tbxRakusatsuPriceTo"] = str(search_conditions.rakusatsu_price_max)

    if search_conditions.rakusatsu_name:
        form_data["tbxRakusatsuNm"] = search_conditions.rakusatsu_name

    if search_conditions.denshi:
        form_data["chkElectronicNyusatsu"] = "on"
    if search_conditions.koukai:
        form_data["chkKokaiBunsyo"] = "on"
    if search_conditions.display_count:
        form_data["drpCount"] = str(search_conditions.display_count)

    form_data["btnSearch"] = "検索開始"
    return form_data


def extract_file_links_from_search_results(
    http_client: "HTTPClient",
    soup: BeautifulSoup,
    base_url: str,
    file_types: List[str],
    logger: "Logger",
    search_conditions: Optional[SearchConditions] = None,
    last_search_result_url: str = "",
) -> tuple[List[FileInfo], int, str]:
    """検索結果の全ページからファイルリンクを抽出（ページネーション対応）

    Returns:
        (全ファイルリスト, 工事件数, 最終URL)
    """
    all_file_links: List[FileInfo] = []
    current_soup = soup
    page_number = 1
    max_pages = 100
    total_koji_count = 0
    current_url = last_search_result_url or base_url
    detail_saved = False

    while page_number <= max_pages:
        logger.info(f"検索結果ページ {page_number} を処理中...")

        page_koji_count = _count_koji_in_page(current_soup, search_conditions)
        total_koji_count += page_koji_count
        logger.info(f"ページ {page_number} の工事件数: {page_koji_count}件 (累計: {total_koji_count}件)")

        page_files, detail_saved = _extract_file_links_from_single_page(
            http_client, current_soup, base_url, file_types, logger,
            search_conditions, current_url, detail_saved,
        )
        all_file_links.extend(page_files)

        next_soup, next_url = _get_next_page(http_client, current_soup, base_url, current_url, logger)
        if next_soup is None:
            logger.info(f"全{page_number}ページの処理が完了しました")
            break

        current_soup = next_soup
        current_url = next_url
        page_number += 1

    for f in all_file_links:
        ensure_agency_metadata(f, search_conditions, base_url)

    logger.info(f"検索結果から合計{len(all_file_links)}個のファイルリンクを抽出しました（工事件数: {total_koji_count}件）")
    return all_file_links, total_koji_count, current_url


# ─── 内部ヘルパー ─────────────────────────────────────


def _resolve_shoubunrui(
    soup: BeautifulSoup, target_text: str, chubunrui_value: str, logger: "Logger"
) -> Optional[str]:
    """小分類の value を解決（HTML ドロップダウン→hidden フィールドの順）"""
    dropdown = soup.find("select", id="drpMiddleKikanInf")
    if dropdown:
        for opt in dropdown.find_all("option"):
            value = opt.get("value", "")
            text = opt.get_text(strip=True)
            if value != "-1" and target_text in text:
                logger.info(f"小分類を選択: '{text}' -> '{value}'")
                return value

    form_data = get_all_hidden_inputs(soup, logger)
    if "txtLargeKikanInf_h" in form_data:
        from .dropdowns import parse_txtLargeKikanInf_h
        options = parse_txtLargeKikanInf_h(form_data["txtLargeKikanInf_h"], chubunrui_value, logger)
        logger.info(f"txtLargeKikanInf_hから小分類の選択肢を{len(options)}個取得しました")
        for value, text in options:
            if target_text in text:
                logger.info(f"小分類を選択: '{text}' -> '{value}'")
                return value
        logger.warning(f"小分類の値が取得できませんでした: '{target_text}'")
        logger.debug(f"利用可能な小分類: {[t for _, t in options]}")
    else:
        logger.warning("txtLargeKikanInf_hが見つかりませんでした")

    return None


def _count_koji_in_page(soup: BeautifulSoup, search_conditions: Optional[SearchConditions] = None) -> int:
    result_table = soup.find("table", id="dgrSearchList")
    if not result_table:
        return 0
    rows = result_table.find_all("tr")[1:]
    count = 0
    for row in rows:
        detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
        if not detail_link:
            continue
        koji_name = detail_link.get_text(strip=True)
        if not koji_name:
            cells = row.find_all("td")
            for cell in cells:
                text = cell.get_text(strip=True)
                if text:
                    koji_name = text
                    break
        if not koji_name:
            continue
        if search_conditions and search_conditions.koji_name:
            if search_conditions.koji_name not in koji_name:
                continue
        count += 1
    return count


def _get_next_page(
    http_client: "HTTPClient",
    current_soup: BeautifulSoup,
    base_url: str,
    last_search_result_url: str,
    logger: "Logger",
) -> tuple[Optional[BeautifulSoup], str]:
    """次のページを取得。(soup, url) を返す。"""
    next_button = (
        current_soup.find("input", {"type": "submit", "value": "次ページ"})
        or current_soup.find("input", {"id": "btnNext1"})
        or current_soup.find("input", {"id": "btnNext2"})
        or current_soup.find("button", string=lambda x: x and "次ページ" in x)
        or current_soup.find("input", {"id": lambda x: x and "Next" in str(x)})
    )
    if not next_button:
        logger.debug("次ページボタンが見つかりません")
        return None, last_search_result_url
    if next_button.get("disabled"):
        logger.debug("次ページボタンが無効化されています（最終ページ）")
        return None, last_search_result_url

    button_name = next_button.get("name", "")
    if not button_name:
        logger.warning(f"次ページボタンの名前が取得できません: {next_button}")
        return None, last_search_result_url

    logger.info(f"次ページに移動中... (ボタン名: {button_name})")

    form_data = get_all_form_inputs(current_soup, logger)
    logger.debug(
        f"Form inputs: __VIEWSTATE={len(form_data.get('__VIEWSTATE', ''))}, "
        f"__EVENTVALIDATION={len(form_data.get('__EVENTVALIDATION', ''))}, total_fields={len(form_data)}"
    )
    form_data[button_name] = next_button.get("value", "次ページ")

    form = current_soup.find("form")
    if form and form.get("action"):
        actual_url = urljoin(last_search_result_url, form.get("action"))
        logger.info(f"フォームaction属性から取得したURL: {actual_url}")
    else:
        actual_url = last_search_result_url
        logger.debug(f"フォームaction属性なし、保存されたURLを使用: {actual_url}")

    try:
        response = http_client.post(actual_url, data=form_data)
        logger.debug(f"次ページ応答: status={response.status_code}, content_length={len(response.content)}")
        next_soup = parse_response_to_soup(response)
        new_url = response.url

        if not next_soup:
            logger.warning("次ページの解析に失敗しました")
            return None, last_search_result_url

        result_table = next_soup.find("table", id="dgrSearchList")
        if result_table:
            rows = result_table.find_all("tr")[1:]
            logger.debug(f"次ページで検索結果テーブルを発見: {len(rows)}行")
            return next_soup, new_url
        else:
            title = next_soup.find("title")
            title_text = title.get_text() if title else "不明"
            logger.warning(f"次ページに検索結果テーブルがありません (ページタイトル: {title_text})")
            return None, last_search_result_url
    except Exception as e:
        logger.error(f"次ページの取得に失敗: {str(e)}", exc_info=True)
        return None, last_search_result_url


def _extract_file_links_from_single_page(
    http_client: "HTTPClient",
    soup: BeautifulSoup,
    base_url: str,
    file_types: List[str],
    logger: "Logger",
    search_conditions: Optional[SearchConditions],
    last_search_result_url: str,
    detail_saved: bool,
) -> tuple[List[FileInfo], bool]:
    """単一の検索結果ページからファイルリンクを抽出"""
    file_links: List[FileInfo] = []
    result_table = soup.find("table", id="dgrSearchList")

    if result_table:
        rows = result_table.find_all("tr")[1:]
        logger.debug(f"検索結果テーブルから{len(rows)}行を発見（ヘッダー行を除く）")
        filtered_count = 0
        for row in rows:
            detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
            if not detail_link:
                continue
            koji_name = detail_link.get_text(strip=True)
            if not koji_name:
                cells = row.find_all("td")
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if text:
                        koji_name = text
                        break
            if not koji_name:
                logger.debug("工事名が抽出できなかったため、この行をスキップします")
                continue
            if search_conditions and search_conditions.koji_name:
                if search_conditions.koji_name not in koji_name:
                    filtered_count += 1
                    logger.debug(f"工事名フィルタリング: '{koji_name}' は '{search_conditions.koji_name}' を含まないためスキップ")
                    continue

            href = detail_link.get("href", "")
            detail_files, detail_saved = extract_files_from_detail_via_postback(
                http_client, base_url, href, file_types, soup, logger,
                last_search_result_url, koji_name=koji_name,
                detail_page_saved_flag=detail_saved,
            )
            file_links.extend(detail_files)

        if filtered_count > 0:
            logger.info(f"工事名フィルタリング: {filtered_count}件の工事を除外しました")
    else:
        result_rows = soup.find_all("tr", class_=lambda x: x and "result" in x.lower())
        if not result_rows:
            direct_files = extract_file_links(soup, base_url, file_types, logger)
            file_links.extend(direct_files)
        else:
            for row in result_rows:
                dl = row.find("a", href=True)
                if dl:
                    detail_url = urljoin(base_url, dl.get("href"))
                    detail_files = extract_files_from_detail_page(http_client, detail_url, file_types, logger)
                    file_links.extend(detail_files)

    direct_files = extract_file_links(soup, base_url, file_types, logger)
    file_links.extend(direct_files)

    logger.info(f"このページから{len(file_links)}個のファイルリンクを抽出しました")
    return file_links, detail_saved
