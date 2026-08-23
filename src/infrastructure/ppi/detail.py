# -*- coding: utf-8 -*-
"""詳細ページの解析・ファイルリンク抽出"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .html import parse_response_to_soup
from .forms import get_all_hidden_inputs
from ...models.file_info import FileInfo

if TYPE_CHECKING:
    from ...utils.http_client import HTTPClient
    from ...utils.logger import Logger


def extract_link_metadata(link_tag) -> Dict[str, Any]:
    """リンクタグからメタデータを抽出"""
    metadata: Dict[str, Any] = {}
    link_text = link_tag.get_text().strip()
    if link_text:
        metadata["link_text"] = link_text
    parent = link_tag.parent
    if parent:
        parent_text = parent.get_text().strip()
        if parent_text:
            metadata["parent_text"] = parent_text
    return metadata


def extract_file_links(
    soup: BeautifulSoup, base_url: str, file_types: List[str], logger: "Logger"
) -> List[FileInfo]:
    """ページからファイルリンクを抽出"""
    file_links: List[FileInfo] = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if not href:
            continue
        absolute_url = urljoin(base_url, href)
        path = urlparse(absolute_url).path.lower()
        matched_type = None
        for ft in file_types:
            if path.endswith(ft.lower()):
                matched_type = ft
                break
        if matched_type:
            filename = path.split("/")[-1] or "untitled" + matched_type
            metadata = extract_link_metadata(link)
            file_links.append(
                FileInfo(url=absolute_url, filename=filename, file_type=matched_type, page_url=base_url, metadata=metadata)
            )
            logger.debug(f"ファイルリンクを発見: {absolute_url}")
    logger.info(f"{len(file_links)}個のファイルリンクを抽出しました")
    return file_links


def extract_metadata(soup: BeautifulSoup) -> Dict[str, Any]:
    """ページからメタデータを抽出（発注機関、工事名、日付、価格等）"""
    metadata: Dict[str, Any] = {}

    title_tag = soup.find("title")
    if title_tag:
        metadata["title"] = title_tag.get_text().strip()

    _extract_table_field(soup, metadata, "hachu_kikan", ["発注機関", "発注者", "発注元"])
    _extract_table_field(soup, metadata, "koji_name", ["工事名", "工事名称", "案件名"])

    date_labels = ["公告日", "開札日", "契約日", "更新日", "最終更新日"]
    for label in date_labels:
        date_elem = soup.find("td", string=re.compile(label))
        if date_elem:
            next_td = date_elem.find_next_sibling("td")
            if next_td:
                date_text = next_td.get_text().strip()
                if date_text:
                    if "date" not in metadata:
                        metadata["date"] = date_text
                    metadata[f"date_{label}"] = date_text

    if "date" not in metadata:
        _extract_date_from_text(soup, metadata)

    _extract_table_field(soup, metadata, "category", ["カテゴリ", "分類", "種別"])
    _extract_price(soup, metadata, "yotei_price", ["予定価格", "予定金額"])
    _extract_price(soup, metadata, "rakusatsu_price", ["落札価格", "契約価格", "落札金額"])

    return metadata


def extract_files_from_tables(
    soup: BeautifulSoup, base_url: str, file_types: List[str], logger: "Logger"
) -> List[FileInfo]:
    """dgrKokoku / dgrKeika テーブルからファイルリンクを抽出"""
    files: List[FileInfo] = []
    for table_id in ("dgrKokoku", "dgrKeika"):
        table = soup.find("table", id=table_id)
        if not table:
            logger.debug(f"テーブルが見つかりません: {table_id}")
            continue
        logger.debug(f"テーブルを発見: {table_id}")
        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            document_name = cells[0].get_text(strip=True)
            link = cells[1].find("a", href=True)
            if not link:
                continue
            href = link.get("href")
            if not href:
                continue
            fi = _process_table_link(href, document_name, base_url, file_types, table_id, logger)
            if fi:
                files.append(fi)
    return files


def count_unavailable_documents(soup: BeautifulSoup, logger: "Logger") -> int:
    """公開文書テーブルで文書名はあるがリンク(href)が無い行を数える

    ppi.jp の入札の経過ページなどでは、公開期限切れの文書が
    「公開終了」表示となり <a> に href が付かない。これらは
    ダウンロード不能だが「添付が存在しない」とは区別したいため件数を数える。
    """
    count = 0
    for table_id in ("dgrKokoku", "dgrKeika"):
        table = soup.find("table", id=table_id)
        if not table:
            continue
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            document_name = cells[0].get_text(strip=True)
            if not document_name:
                continue
            if cells[1].find("a", href=True):
                continue
            count += 1
            logger.debug(f"公開終了/リンクなしの文書を検出: '{document_name}' ({table_id})")
    return count


def extract_files_from_detail_via_postback(
    http_client: "HTTPClient",
    base_url: str,
    postback_href: str,
    file_types: List[str],
    current_soup: BeautifulSoup,
    logger: "Logger",
    last_search_result_url: str,
    koji_name: Optional[str] = None,
    detail_page_saved_flag: bool = False,
) -> tuple[List[FileInfo], bool, int]:
    """__doPostBack リンクから詳細ページを取得してファイルを抽出

    Returns:
        (抽出ファイルリスト, detail_page_saved_flag の更新値, 公開終了等で取得不能だった文書数)
    """
    try:
        match = re.search(r"__doPostBack\('([^']+)','([^']+)'\)", postback_href)
        if not match:
            return [], detail_page_saved_flag, 0

        event_target = match.group(1)
        event_argument = match.group(2)

        form = current_soup.find("form")
        if form and form.get("action"):
            post_url = urljoin(last_search_result_url, form.get("action"))
        else:
            post_url = last_search_result_url
        detail_url = post_url

        form_data = get_all_hidden_inputs(current_soup, logger)
        form_data["__EVENTTARGET"] = event_target
        form_data["__EVENTARGUMENT"] = event_argument

        response = http_client.post(post_url, data=form_data)
        detail_soup = parse_response_to_soup(response)
        if not detail_soup:
            return [], detail_page_saved_flag, 0

        if not detail_page_saved_flag:
            output_file = Path("artifacts/test_detail_page.html")
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(str(detail_soup))
            logger.debug(f"詳細ページHTMLを保存: {output_file}")
            detail_page_saved_flag = True

        files = extract_files_from_tables(detail_soup, detail_url, file_types, logger)
        if not files:
            files = extract_file_links(detail_soup, detail_url, file_types, logger)

        if koji_name:
            for fi in files:
                if not fi.metadata:
                    fi.metadata = {}
                fi.metadata["koji_name"] = koji_name
        else:
            meta = extract_metadata(detail_soup)
            if "koji_name" in meta:
                for fi in files:
                    if not fi.metadata:
                        fi.metadata = {}
                    fi.metadata["koji_name"] = meta["koji_name"]

        if files:
            logger.info(f"詳細ページから{len(files)}個のファイルリンクを抽出しました")
            for idx, f in enumerate(files, 1):
                logger.debug(f"  ファイル[{idx}]: 文書名='{f.metadata.get('title', 'N/A')}', URL='{f.url[:80]}...', type={f.file_type}")
        else:
            logger.debug("詳細ページからファイルリンクを抽出できませんでした")

        userentry_files = _fetch_userentry_files(
            http_client, detail_soup, detail_url, file_types, logger, koji_name
        )

        all_files = _merge_files(files, userentry_files, logger)

        unavailable_count = 0
        if not all_files:
            unavailable_count = count_unavailable_documents(detail_soup, logger)
            if unavailable_count:
                logger.info(
                    f"公開終了等で取得不能な文書が{unavailable_count}件ありました"
                    f"（工事名: {koji_name or 'N/A'}）"
                )
        return all_files, detail_page_saved_flag, unavailable_count

    except Exception as e:
        logger.warning(f"詳細ページからのファイル抽出エラー（POST）: {postback_href} - {str(e)}")
        return [], detail_page_saved_flag, 0


def extract_files_from_detail_page(
    http_client: "HTTPClient",
    detail_url: str,
    file_types: List[str],
    logger: "Logger",
) -> List[FileInfo]:
    """案件詳細ページ（GET）からファイルを抽出"""
    try:
        logger.info(f"ページを取得中: {detail_url}")
        response = http_client.get(detail_url)
        soup = parse_response_to_soup(response)
        if not soup:
            return []
        files = extract_file_links(soup, detail_url, file_types, logger)
        meta = extract_metadata(soup)
        for fi in files:
            if fi.metadata:
                fi.metadata.update(meta)
            else:
                fi.metadata = meta
        return files
    except Exception as e:
        logger.warning(f"詳細ページからのファイル抽出エラー: {detail_url} - {str(e)}")
        return []


# ─── 内部ヘルパー ─────────────────────────────────────


def _extract_table_field(soup: BeautifulSoup, metadata: dict, key: str, labels: List[str]) -> None:
    for label in labels:
        elem = soup.find("td", string=re.compile(label))
        if elem:
            next_td = elem.find_next_sibling("td")
            if next_td:
                text = next_td.get_text().strip()
                if text:
                    metadata[key] = text
                    return


def _extract_date_from_text(soup: BeautifulSoup, metadata: dict) -> None:
    patterns = [
        r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})[日]?",
        r"(\d{4})-(\d{2})-(\d{2})",
        r"(\d{4})\.(\d{2})\.(\d{2})",
    ]
    page_text = soup.get_text()
    for pattern in patterns:
        m = re.search(pattern, page_text)
        if m:
            y, mo, d = m.groups()
            metadata["date"] = f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
            return


def _extract_price(soup: BeautifulSoup, metadata: dict, key: str, labels: List[str]) -> None:
    for label in labels:
        elem = soup.find("td", string=re.compile(label))
        if elem:
            next_td = elem.find_next_sibling("td")
            if next_td:
                text = next_td.get_text().strip()
                m = re.search(r"[\d,]+", text.replace(",", ""))
                if m:
                    metadata[key] = int(m.group().replace(",", ""))
                    return


def _process_table_link(
    href: str, document_name: str, base_url: str, file_types: List[str], table_id: str, logger: "Logger"
) -> Optional[FileInfo]:
    if href.startswith("javascript:") and "__doPostBack" in href:
        match = re.search(r"__doPostBack\('([^']+)','([^']+)'\)", href)
        if match:
            et, ea = match.group(1), match.group(2)
            postback_info = {
                "postback": True,
                "postback_info": {"event_target": et, "event_argument": ea, "postback_href": href, "document_name": document_name},
            }
            fi = FileInfo(
                url=f"postback://{et}/{ea}",
                filename=document_name or "postback_file",
                file_type=".pdf",
                page_url=base_url,
                metadata={"title": document_name, **postback_info} if document_name else postback_info,
            )
            logger.debug(f"PostBackリンクを検出: 文書名='{document_name}', event_target='{et}', event_argument='{ea}' ({table_id})")
            return fi
        else:
            logger.warning(f"PostBackリンクの解析に失敗: 文書名='{document_name}', href='{href[:100]}...' ({table_id})")
            return None

    absolute_url = urljoin(base_url, href)
    is_file_link = False

    if any(href.lower().endswith(ext) for ext in file_types):
        is_file_link = True
        logger.debug(f"ファイルリンクを採用: 文書名='{document_name}', 理由=拡張子一致")
    elif "KokaiBunshoServlet" in href or "Publish" in href or "Download" in href:
        is_file_link = True
        logger.debug(f"ファイルリンクを採用: 文書名='{document_name}', 理由=servlet/Download/Publish")
    else:
        logger.debug(f"ファイルリンクを不採用: 文書名='{document_name}', href='{href[:80]}...'")

    if not is_file_link:
        return None

    filename = absolute_url.split("/")[-1].split("?")[0]
    if not filename or "." not in filename:
        filename = document_name

    file_type = ""
    url_path = absolute_url.split("?")[0]
    parts = url_path.split("/")
    if parts:
        last = parts[-1]
        if "." in last:
            ext = "." + last.split(".")[-1].lower()
            if len(ext) <= 6:
                file_type = ext
    if not file_type:
        file_type = ".pdf"

    return FileInfo(
        url=absolute_url,
        filename=filename,
        file_type=file_type,
        page_url=base_url,
        metadata={"title": document_name} if document_name else {},
    )


def _extract_ankenkanri_no(detail_soup: BeautifulSoup, logger: "Logger") -> tuple[Optional[str], Optional[str]]:
    """JavaScript 変数 AnkenkanriNo, HachushaId を抽出"""
    ankenkanri_no: Optional[str] = None
    hachusha_id: Optional[str] = None

    for get_text_fn in (
        lambda s: s.string,
        lambda s: s.get_text(),
    ):
        for script in detail_soup.find_all("script"):
            text = get_text_fn(script)
            if text and "AnkenkanriNo" in text:
                m = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', text)
                if m and not ankenkanri_no:
                    ankenkanri_no = m.group(1)
                    logger.debug(f"AnkenkanriNoを抽出: {ankenkanri_no}")
                m = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', text)
                if m and not hachusha_id:
                    hachusha_id = m.group(1)
                    logger.debug(f"HachushaIdを抽出: {hachusha_id}")
        if ankenkanri_no and hachusha_id:
            break

    if not ankenkanri_no or not hachusha_id:
        page_text = detail_soup.get_text()
        if "AnkenkanriNo" in page_text:
            m = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', page_text)
            if m and not ankenkanri_no:
                ankenkanri_no = m.group(1)
            m = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', page_text)
            if m and not hachusha_id:
                hachusha_id = m.group(1)

    if not ankenkanri_no:
        logger.warning("AnkenkanriNoを抽出できませんでした")
    if not hachusha_id:
        logger.warning("HachushaIdを抽出できませんでした")

    return ankenkanri_no, hachusha_id


def _fetch_userentry_files(
    http_client: "HTTPClient",
    detail_soup: BeautifulSoup,
    detail_url: str,
    file_types: List[str],
    logger: "Logger",
    koji_name: Optional[str] = None,
) -> List[FileInfo]:
    """UserEntry_Download.aspx からファイルリンクを取得"""
    ankenkanri_no, hachusha_id = _extract_ankenkanri_no(detail_soup, logger)
    if not ankenkanri_no or not hachusha_id:
        return []

    download_url = f"https://www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx?data1={ankenkanri_no}&data2={hachusha_id}"
    logger.debug(f"UserEntry_Download.aspxにアクセス: {download_url}")

    try:
        resp = http_client.get(download_url)
        logger.debug(f"UserEntry_Download.aspx レスポンス: status={resp.status_code}, Content-Type={resp.headers.get('Content-Type', 'N/A')}")
        if resp.status_code != 200:
            logger.warning(f"UserEntry_Download.aspx アクセス失敗: status={resp.status_code}")
            return []
        dl_soup = parse_response_to_soup(resp)
        if not dl_soup:
            return []

        userentry_files = extract_files_from_tables(dl_soup, download_url, file_types, logger)
        if not userentry_files:
            userentry_files = extract_file_links(dl_soup, download_url, file_types, logger)

        if userentry_files:
            logger.info(f"UserEntry_Download.aspxから{len(userentry_files)}個のファイルリンクを抽出しました")
            meta = extract_metadata(detail_soup)
            doc_names = _get_document_names(dl_soup)
            if doc_names:
                meta["document_names"] = doc_names
            if koji_name:
                meta["koji_name"] = koji_name
            for fi in userentry_files:
                if fi.metadata:
                    fi.metadata.update(meta)
                else:
                    fi.metadata = meta

        return userentry_files
    except Exception as e:
        logger.warning(f"UserEntry_Download.aspxからのファイル抽出エラー: {str(e)}", exc_info=True)
        return []


def _get_document_names(soup: BeautifulSoup) -> List[str]:
    names: List[str] = []
    for tid in ("dgrKokoku", "dgrKeika"):
        table = soup.find("table", id=tid)
        if table:
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if cells:
                    name = cells[0].get_text(strip=True)
                    if name:
                        names.append(name)
    return names


def _merge_files(
    detail_files: List[FileInfo], userentry_files: List[FileInfo], logger: "Logger"
) -> List[FileInfo]:
    """重複を除去してマージ"""
    all_files = list(detail_files)
    existing_urls = {f.url for f in detail_files}
    existing_keys = {(f.metadata.get("title", ""), f.file_type) for f in detail_files}

    for uf in userentry_files:
        if uf.url in existing_urls:
            logger.debug(f"重複ファイルをスキップ（URL同一）: {uf.url[:80]}...")
            continue
        uf_key = (uf.metadata.get("title", ""), uf.file_type)
        if uf_key in existing_keys:
            logger.debug(f"重複ファイルをスキップ（文書名+タイプ同一）: '{uf.metadata.get('title', 'N/A')}'")
            continue
        all_files.append(uf)
        existing_urls.add(uf.url)
        existing_keys.add(uf_key)
        logger.debug(f"UserEntryファイルを追加: 文書名='{uf.metadata.get('title', 'N/A')}'")

    logger.info(
        f"ファイル抽出完了: 詳細ページ={len(detail_files)}件, "
        f"UserEntry_Download.aspx={len(userentry_files)}件, "
        f"マージ後={len(all_files)}件（重複除去済み）"
    )
    return all_files
