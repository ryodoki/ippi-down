"""Playwrightを使用したHTML解析・スクレイピングクラス"""

from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs
from pathlib import Path
import re
from ..models.file_info import FileInfo
from ..models.config_model import SearchConditions
from ..utils.playwright_client import PlaywrightClient
from ..utils.logger import Logger


class ScraperPlaywright:
    """Playwrightを使用したHTML解析・スクレイピングクラス"""

    def __init__(self, playwright_client: PlaywrightClient, logger: Optional[Logger] = None):
        """初期化"""
        self.playwright_client = playwright_client
        self.logger = logger or Logger()

    def _normalize_search_url(self, search_url: str) -> str:
        """検索URLを正規化（tab=4パラメータを追加）"""
        parsed = urlparse(search_url)
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        # tab=4パラメータを追加（必須）
        query_params['tab'] = ['4']
        new_query = '&'.join(
            f"{k}={v[0]}" if len(v) == 1 else '&'.join(f"{k}={val}" for val in v)
            for k, v in query_params.items()
        )
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        return normalized

    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """ページを取得してBeautifulSoupオブジェクトを返す"""
        try:
            normalized_url = self._normalize_search_url(url)
            self.logger.info(f"ページを取得中: {normalized_url}")
            
            # Playwrightでページを取得
            soup = self.playwright_client.get_page_soup(normalized_url, wait_until="networkidle")
            
            if soup:
                return soup
            else:
                self.logger.error(f"ページ取得失敗: {normalized_url}")
                return None
        except Exception as e:
            self.logger.error(f"ページ取得エラー: {url} - {str(e)}", exc_info=True)
            return None

    def _get_all_hidden_inputs(self, soup: BeautifulSoup) -> Dict[str, str]:
        """すべてのhidden inputを取得"""
        hidden_inputs = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                hidden_inputs[name] = value
        
        self.logger.debug(f"hidden inputを{len(hidden_inputs)}個取得しました")
        # 取得したhidden inputの名前をログに出力（最初の10個）
        if hidden_inputs:
            keys_list = list(hidden_inputs.keys())[:10]
            self.logger.debug(f"取得したhidden inputの名前（最初の10個）: {', '.join(keys_list)}")
        
        # 重要なhidden inputの存在を確認
        if "__VIEWSTATE" in hidden_inputs:
            self.logger.debug(f"__VIEWSTATE: 取得済み (長さ: {len(hidden_inputs['__VIEWSTATE'])})")
        else:
            self.logger.warning("__VIEWSTATEが見つかりませんでした")
            # __VIEWSTATEで始まるキーを探す
            viewstate_keys = [k for k in hidden_inputs.keys() if "__VIEWSTATE" in k.upper() or "VIEWSTATE" in k.upper()]
            if viewstate_keys:
                self.logger.debug(f"VIEWSTATE関連のキーが見つかりました: {viewstate_keys}")
        
        if "__EVENTVALIDATION" in hidden_inputs:
            self.logger.debug(f"__EVENTVALIDATION: 取得済み (長さ: {len(hidden_inputs['__EVENTVALIDATION'])})")
        else:
            self.logger.warning("__EVENTVALIDATIONが見つかりませんでした")
            # __EVENTVALIDATIONで始まるキーを探す
            eventvalidation_keys = [k for k in hidden_inputs.keys() if "__EVENTVALIDATION" in k.upper() or "EVENTVALIDATION" in k.upper()]
            if eventvalidation_keys:
                self.logger.debug(f"EVENTVALIDATION関連のキーが見つかりました: {eventvalidation_keys}")
        
        if "__VIEWSTATEGENERATOR" in hidden_inputs:
            self.logger.debug(f"__VIEWSTATEGENERATOR: 取得済み")
        
        return hidden_inputs

    def _get_dropdown_select(self, soup: BeautifulSoup, dropdown_name: str):
        """ドロップダウン要素を取得"""
        dropdown = soup.find("select", {"name": dropdown_name})
        if not dropdown:
            dropdown_id = dropdown_name.replace("$", "_")
            dropdown = soup.find("select", {"id": dropdown_id})
        if not dropdown:
            if "TopKikanInf" in dropdown_name or "HachuDaibunrui" in dropdown_name:
                dropdown = soup.find("select", {"id": lambda x: x and ("TopKikanInf" in str(x) or "HachuDaibunrui" in str(x))})
                if not dropdown:
                    dropdown = soup.find("select", {"name": lambda x: x and ("TopKikanInf" in str(x) or "HachuDaibunrui" in str(x))})
            elif "LargeKikanInf" in dropdown_name or "HachuChubunrui" in dropdown_name:
                dropdown = soup.find("select", {"id": lambda x: x and ("LargeKikanInf" in str(x) or "HachuChubunrui" in str(x))})
                if not dropdown:
                    dropdown = soup.find("select", {"name": lambda x: x and ("LargeKikanInf" in str(x) or "HachuChubunrui" in str(x))})
            elif "MiddleKikanInf" in dropdown_name or "HachuShoubunrui" in dropdown_name:
                dropdown = soup.find("select", {"id": lambda x: x and ("MiddleKikanInf" in str(x) or "HachuShoubunrui" in str(x))})
                if not dropdown:
                    dropdown = soup.find("select", {"name": lambda x: x and ("MiddleKikanInf" in str(x) or "HachuShoubunrui" in str(x))})
            elif "SmallKikanInf" in dropdown_name or "HachuSaibunrui" in dropdown_name:
                dropdown = soup.find("select", {"id": lambda x: x and ("SmallKikanInf" in str(x) or "HachuSaibunrui" in str(x))})
                if not dropdown:
                    dropdown = soup.find("select", {"name": lambda x: x and ("SmallKikanInf" in str(x) or "HachuSaibunrui" in str(x))})
        
        if not dropdown:
            # デバッグ: すべてのselect要素を確認
            all_selects = soup.find_all("select")
            self.logger.debug(f"ドロップダウンが見つかりません: {dropdown_name}")
            self.logger.debug(f"ページ内のselect要素数: {len(all_selects)}")
            if all_selects:
                select_names = [s.get("name", "なし") for s in all_selects[:5]]
                self.logger.debug(f"最初の5個のselect要素のname: {select_names}")
        
        return dropdown

    def _get_dropdown_value_from_text(self, soup: BeautifulSoup, dropdown_name: str, display_text: str) -> Optional[str]:
        """ドロップダウンから表示テキストに対応するvalueを取得"""
        dropdown = self._get_dropdown_select(soup, dropdown_name)
        if dropdown:
            for option in dropdown.find_all("option"):
                if option.get_text().strip() == display_text:
                    value = option.get("value", "")
                    return value if value else None
            return None

    def extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """ページからメタデータを抽出
        
        抽出する情報:
        - title: ページタイトル
        - hachu_kikan: 発注機関
        - koji_name: 工事名
        - date: 日付（公告日、開札日、契約日など）
        - category: カテゴリ
        """
        metadata = {}

        # タイトル
        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text().strip()

        # テーブルから情報を抽出（ppi.jpのページ構造に応じて）
        # 発注機関の抽出
        hachu_labels = ["発注機関", "発注者", "発注元"]
        for label in hachu_labels:
            hachu_elem = soup.find("td", string=re.compile(label))
            if hachu_elem:
                next_td = hachu_elem.find_next_sibling("td")
                if next_td:
                    hachu_text = next_td.get_text().strip()
                    if hachu_text:
                        metadata["hachu_kikan"] = hachu_text
                        break

        # 工事名の抽出
        koji_labels = ["工事名", "工事名称", "案件名"]
        for label in koji_labels:
            koji_elem = soup.find("td", string=re.compile(label))
            if koji_elem:
                next_td = koji_elem.find_next_sibling("td")
                if next_td:
                    koji_text = next_td.get_text().strip()
                    if koji_text:
                        metadata["koji_name"] = koji_text
                        break

        # 日付の抽出（公告日、開札日、契約日など）
        date_labels = ["公告日", "開札日", "契約日", "更新日", "最終更新日"]
        for label in date_labels:
            date_elem = soup.find("td", string=re.compile(label))
            if date_elem:
                next_td = date_elem.find_next_sibling("td")
                if next_td:
                    date_text = next_td.get_text().strip()
                    if date_text:
                        # 最初に見つかった日付を優先的に使用
                        if "date" not in metadata:
                            metadata["date"] = date_text
                        # ラベル付きで保存
                        metadata[f"date_{label}"] = date_text

        # 日付パターンでテキスト全体から日付を抽出（上記で見つからなかった場合）
        if "date" not in metadata:
            date_patterns = [
                r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})[日]?",
                r"(\d{4})-(\d{2})-(\d{2})",
                r"(\d{4})\.(\d{2})\.(\d{2})",
            ]
            page_text = soup.get_text()
            for pattern in date_patterns:
                date_match = re.search(pattern, page_text)
                if date_match:
                    # 日付を正規化（YYYY-MM-DD形式）
                    year, month, day = date_match.groups()
                    metadata["date"] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    break

        # カテゴリの抽出（ページ構造に応じて調整）
        category_elem = soup.find("td", string=re.compile("カテゴリ|分類|種別"))
        if category_elem:
            next_td = category_elem.find_next_sibling("td")
            if next_td:
                category_text = next_td.get_text().strip()
                if category_text:
                    metadata["category"] = category_text

        # 予定価格の抽出
        price_elem = soup.find("td", string=re.compile("予定価格|予定金額"))
        if price_elem:
            next_td = price_elem.find_next_sibling("td")
            if next_td:
                price_text = next_td.get_text().strip()
                # 数値を抽出
                price_match = re.search(r"[\d,]+", price_text.replace(",", ""))
                if price_match:
                    metadata["yotei_price"] = int(price_match.group().replace(",", ""))

        # 落札価格の抽出
        rakusatsu_elem = soup.find("td", string=re.compile("落札価格|契約価格|落札金額"))
        if rakusatsu_elem:
            next_td = rakusatsu_elem.find_next_sibling("td")
            if next_td:
                rakusatsu_text = next_td.get_text().strip()
                # 数値を抽出
                rakusatsu_match = re.search(r"[\d,]+", rakusatsu_text.replace(",", ""))
                if rakusatsu_match:
                    metadata["rakusatsu_price"] = int(rakusatsu_match.group().replace(",", ""))

        return metadata

    def extract_file_links(
        self, soup: BeautifulSoup, base_url: str, file_types: List[str]
    ) -> List[FileInfo]:
        """ページからファイルリンクを抽出"""
        file_links = []
        base_parsed = urlparse(base_url)

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if not href:
                continue

            absolute_url = urljoin(base_url, href)

            parsed_url = urlparse(absolute_url)
            path = parsed_url.path.lower()

            matched_type = None
            for file_type in file_types:
                if path.endswith(file_type.lower()):
                    matched_type = file_type
                    break

            if matched_type:
                filename = path.split("/")[-1] or "untitled" + matched_type
                metadata = self._extract_link_metadata(link)

                file_info = FileInfo(
                    url=absolute_url,
                    filename=filename,
                    file_type=matched_type,
                    page_url=base_url,
                    metadata=metadata,
                )

                file_links.append(file_info)
                self.logger.debug(f"ファイルリンクを発見: {absolute_url}")

        self.logger.info(f"{len(file_links)}個のファイルリンクを抽出しました")
        return file_links

    def _extract_link_metadata(self, link_tag) -> Dict[str, Any]:
        """リンクタグからメタデータを抽出"""
        metadata = {}

        link_text = link_tag.get_text().strip()
        if link_text:
            metadata["link_text"] = link_text

        parent = link_tag.parent
        if parent:
            parent_text = parent.get_text().strip()
            if parent_text:
                metadata["parent_text"] = parent_text

        return metadata
