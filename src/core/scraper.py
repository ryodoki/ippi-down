"""HTML解析・スクレイピングを行うクラス"""

from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple, Optional
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs
from pathlib import Path
import re
from ..models.file_info import FileInfo
from ..models.config_model import SearchConditions
from ..utils.http_client import HTTPClient
from ..utils.logger import Logger


class Scraper:
    """HTML解析・スクレイピングを行うクラス"""

    def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None):
        """初期化"""
        self.http_client = http_client
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
            response = self.http_client.get(normalized_url)
            
            if response.encoding:
                response.encoding = response.apparent_encoding or 'utf-8'
            else:
                response.encoding = 'utf-8'
            
            try:
                soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
            
            return soup
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

    def _parse_setListItemSub(self, response_text: str, dropdown_name: str) -> List[Tuple[str, str]]:
        """setListItemSub()からオプションを抽出（value, textのタプルのリストを返す）"""
        try:
            dropdown_id = dropdown_name.replace("$", "_")
            dropdown_id_part = dropdown_id.split("_")[-1]
            
            self.logger.debug(f"setListItemSub解析開始: dropdown_name={dropdown_name}, dropdown_id={dropdown_id}")
            
            # setListItemSubの呼び出しパターンを検索
            # パターン: setListItemSub('ID', ['value:text', 'value:text', ...]);
            pattern = rf"setListItemSub\s*\(\s*['\"]([^'\"]*{re.escape(dropdown_id_part)}[^'\"]*)['\"]\s*,\s*\[(.*?)\]\s*\)"
            matches = re.findall(pattern, response_text, re.DOTALL)
            
            self.logger.debug(f"setListItemSubパターンマッチ: {len(matches)}件")
            
            for call_id, list_content in matches:
                # IDが一致するか確認
                if dropdown_id in call_id or dropdown_id_part in call_id:
                    self.logger.debug(f"マッチしたsetListItemSub呼び出し: ID={call_id}")
                    
                    # リストアイテムを抽出（'value:text' または "value:text" の形式）
                    items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
                    options = []
                    
                    for item in items:
                        if ":" in item:
                            # "value:text" 形式を分解
                            parts = item.split(":", 1)
                            if len(parts) == 2:
                                value, text = parts
                                options.append((value, text))
                                self.logger.debug(f"  オプション: value={value}, text={text}")
                            else:
                                # コロンが1つしかない場合は値のみ
                                options.append((item, item))
                        else:
                            # コロンがない場合は値とテキストが同じ
                            options.append((item, item))
                    
                    self.logger.info(f"setListItemSubから{len(options)}個のオプションを抽出しました")
                    return options
            
            # 別のパターン: setListItemSub('ID', LIST変数)の形式も試す
            # パターン: setListItemSub('ID', VAR)
            pattern_var = rf"setListItemSub\s*\(\s*['\"]([^'\"]*{re.escape(dropdown_id_part)}[^'\"]*)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
            matches_var = re.findall(pattern_var, response_text)
            
            self.logger.debug(f"setListItemSub変数形式パターンマッチ: {len(matches_var)}件")
            
            for call_id, var_name in matches_var:
                # IDが一致するか確認
                if dropdown_id in call_id or dropdown_id_part in call_id:
                    self.logger.debug(f"マッチしたsetListItemSub呼び出し（変数形式）: ID={call_id}, VAR={var_name}")
                    
                    # 変数定義を探す
                    var_pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\];"
                    var_matches = re.findall(var_pattern, response_text, re.DOTALL)
                    
                    if var_matches:
                        self.logger.debug(f"変数定義が見つかりました: {var_name}")
                        list_content = var_matches[0]
                        
                        # リストアイテムを抽出（'value:text' または "value:text" の形式）
                        items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
                        options = []
                        
                        for item in items:
                            if ":" in item:
                                # "value:text" 形式を分解
                                parts = item.split(":", 1)
                                if len(parts) == 2:
                                    value, text = parts
                                    options.append((value, text))
                                    self.logger.debug(f"  オプション: value={value}, text={text}")
                                else:
                                    options.append((item, item))
                            else:
                                options.append((item, item))
                        
                        if options:
                            self.logger.info(f"setListItemSub（変数形式）から{len(options)}個のオプションを抽出しました")
                            return options
            
            return []
            
        except Exception as e:
            self.logger.error(f"setListItemSub解析エラー: {str(e)}", exc_info=True)
            return []

    def _parse_txtLargeKikanInf_h(self, txtLargeKikanInf_h: str, target_key: str) -> List[Tuple[str, str]]:
        """txtLargeKikanInf_hから指定されたkey（中分類のvalue）に一致するエントリを抽出（Common.jsのgetListItemStrと同じロジック）"""
        try:
            options = []
            # :で分割
            entries = txtLargeKikanInf_h.split(":")
            for entry in entries:
                # ,で分割
                parts = entry.split(",")
                if len(parts) >= 3:
                    # 形式: 大分類value,中分類名,中分類value,小分類名,小分類value,...
                    # または: 大分類value,中分類名,中分類value
                    daibunrui_value = parts[0]
                    chubunrui_name = parts[1]
                    chubunrui_value = parts[2]
                    
                    # 中分類のvalueと一致する場合
                    if chubunrui_value == target_key:
                        # 小分類のデータがある場合（parts[3]以降）
                        if len(parts) >= 5:
                            # 小分類名と小分類valueのペアを抽出
                            for i in range(3, len(parts) - 1, 2):
                                if i + 1 < len(parts):
                                    shoubunrui_name = parts[i]
                                    shoubunrui_value = parts[i + 1]
                                    options.append((shoubunrui_value, shoubunrui_name))
            
            return options
        except Exception as e:
            self.logger.error(f"txtLargeKikanInf_h解析エラー: {str(e)}", exc_info=True)
            return []
    
    def _parse_html_options(self, soup: BeautifulSoup, dropdown_name: str) -> List[Tuple[str, str]]:
        """HTMLから<select><option>を解析（value, textのタプルのリストを返す）"""
        dropdown = self._get_dropdown_select(soup, dropdown_name)
        if dropdown:
            options = []
            for option in dropdown.find_all("option"):
                text = option.get_text().strip()
                value = option.get("value", "")
                if text:  # 空のオプションは除外
                    options.append((value if value else text, text))
            return options
        return []

    def get_dropdown_options(
        self, search_url: str, dropdown_name: str, parent_values: Optional[Dict[str, str]] = None
    ) -> List[str]:
        """階層ドロップダウンのオプションを取得（表示テキストのリストを返す）"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            self.logger.debug(f"ドロップダウンオプション取得開始: {dropdown_name}, URL={normalized_url}")
            
            # 初回GET: すべてのhidden inputを取得
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                self.logger.warning("検索ページの取得に失敗しました")
                return []
            
            form_data = self._get_all_hidden_inputs(initial_soup)
            
            # __EVENTTARGETに対象のドロップダウン名を設定
            form_data["__EVENTTARGET"] = dropdown_name
            form_data["__EVENTARGUMENT"] = ""
            
            # 親ドロップダウンのvalueをform_dataに含める
            if parent_values:
                for key, value in parent_values.items():
                    form_data[key] = value
                    self.logger.debug(f"親ドロップダウンを設定: {key}={value}")
            
            # POSTリクエスト
            self.logger.debug(f"POST送信: form_dataのキー数={len(form_data)}")
            self.logger.debug(f"form_dataのキー: {', '.join(list(form_data.keys())[:20])}")  # 最初の20個
            
            response = self.http_client.post(normalized_url, data=form_data)
            if response.status_code == 405:
                self.logger.error("405 Method Not Allowed エラーが発生しました")
                return []
            
            self.logger.debug(f"POSTレスポンス: status_code={response.status_code}")
            
            # エンコーディング処理
            if response.encoding:
                response.encoding = response.apparent_encoding or 'utf-8'
            else:
                response.encoding = 'utf-8'
            
            response_text = response.text
            
            # ① setListItemSub()をJavaScriptから解析
            self.logger.debug("setListItemSub()の解析を開始")
            if "setListItemSub" in response_text:
                self.logger.debug("レスポンスにsetListItemSubが含まれています")
                options_from_js = self._parse_setListItemSub(response_text, dropdown_name)
                if options_from_js:
                    # (value, text)のタプルからtextのリストを返す
                    display_texts = [text for _, text in options_from_js]
                    self.logger.info(f"setListItemSub()から{len(display_texts)}個のオプションを取得しました")
                    return display_texts
                else:
                    self.logger.debug("setListItemSub()からオプションを抽出できませんでした")
            else:
                self.logger.debug("レスポンスにsetListItemSubが含まれていません")
            
            # ② HTMLから<select><option>を解析（①で取得できなかった場合のみ）
            self.logger.debug("HTMLから<select><option>の解析を開始")
            try:
                soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
            
            options_from_html = self._parse_html_options(soup, dropdown_name)
            if options_from_html:
                display_texts = [text for _, text in options_from_html]
                self.logger.info(f"HTMLから{len(display_texts)}個のオプションを取得しました")
                return display_texts
            
            self.logger.warning(f"ドロップダウンオプションを取得できませんでした: {dropdown_name}")
            return []
            
        except Exception as e:
            self.logger.error(f"ドロップダウンオプション取得エラー: {dropdown_name} - {str(e)}", exc_info=True)
            return []

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

    def _extract_files_from_tables(
        self, soup: BeautifulSoup, base_url: str, file_types: List[str]
    ) -> List[FileInfo]:
        """dgrKokoku/dgrKeikaテーブルからファイルリンクを抽出（再利用可能なメソッド）
        
        Args:
            soup: BeautifulSoupオブジェクト
            base_url: ベースURL（page_urlに設定される）
            file_types: 対象ファイルタイプのリスト
        
        Returns:
            抽出されたFileInfoのリスト
        """
        files = []
        
        # dgrKokokuとdgrKeikaテーブル内のリンクを抽出
        for table_id in ["dgrKokoku", "dgrKeika"]:
            table = soup.find("table", id=table_id)
            if not table:
                self.logger.debug(f"テーブルが見つかりません: {table_id}")
                continue
            
            self.logger.debug(f"テーブルを発見: {table_id}")
            
            # テーブル内のすべての行を取得（ヘッダー行を除く）
            rows = table.find_all("tr")[1:]  # 最初の行はヘッダー
            
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                
                # 文書名称（最初のセル）
                document_name = cells[0].get_text(strip=True)
                
                # 公開状況セル（2番目のセル）内のリンクを探す
                status_cell = cells[1]
                link = status_cell.find("a", href=True)
                
                if link:
                    href = link.get("href")
                    if href:
                        # 相対URLを絶対URLに変換
                        absolute_url = urljoin(base_url, href)
                        
                        # ファイルタイプをチェック（URLに拡張子が含まれている場合）
                        # または、KokaiBunshoServletのようなファイルダウンロードURLの場合
                        is_file_link = False
                        if any(href.lower().endswith(ext) for ext in file_types):
                            is_file_link = True
                        elif "KokaiBunshoServlet" in href or "Publish" in href or "Download" in href:
                            # ファイルダウンロードURLの可能性が高い
                            is_file_link = True
                        
                        if is_file_link:
                            # ファイル名をURLから抽出（拡張子がある場合）
                            filename = absolute_url.split("/")[-1].split("?")[0]
                            if not filename or "." not in filename:
                                # 拡張子がない場合、文書名称から推測
                                filename = document_name
                            
                            # ファイルタイプを抽出
                            # URLに拡張子が含まれている場合はそれを使用
                            file_type = ""
                            url_path = absolute_url.split("?")[0]
                            # URLパスの最後の部分から拡張子を抽出（例: /path/to/file.pdf）
                            path_parts = url_path.split("/")
                            if path_parts:
                                last_part = path_parts[-1]
                                if "." in last_part:
                                    # 拡張子を抽出（例: file.pdf -> .pdf）
                                    ext = "." + last_part.split(".")[-1].lower()
                                    # 有効な拡張子かチェック（短すぎる場合は無視）
                                    if len(ext) <= 6:  # .pdf, .xlsx, .docx など
                                        file_type = ext
                            
                            # 拡張子がない場合、デフォルトで.pdfを設定（KokaiBunshoServletは通常PDFを返す）
                            if not file_type:
                                file_type = ".pdf"
                            
                            file_info = FileInfo(
                                url=absolute_url,
                                filename=filename,
                                file_type=file_type,
                                page_url=base_url,  # ベースURLを設定（Refererヘッダーに使用）
                                metadata={"title": document_name} if document_name else {}
                            )
                            files.append(file_info)
                            self.logger.debug(f"ファイルリンクを抽出: {document_name} -> {absolute_url} (type: {file_type})")
        
        return files

    def get_hachu_daibunrui_options(self, search_url: str) -> List[str]:
        """大分類のオプションを取得"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            
            soup = self.fetch_page(normalized_url)
            if not soup:
                self.logger.warning("検索ページの取得に失敗しました（大分類）")
                return []
            
            dropdown_name = "drpTopKikanInf"
            dropdown = self._get_dropdown_select(soup, dropdown_name)
            
            if dropdown:
                options = []
                for option in dropdown.find_all("option"):
                    text = option.get_text().strip()
                    if text:
                        options.append(text)
                self.logger.info(f"大分類オプション取得成功: {len(options)}件")
                return options
            else:
                self.logger.warning("大分類のドロップダウンが見つかりません")
                return []
            
        except Exception as e:
            self.logger.error(f"大分類オプション取得エラー: {str(e)}", exc_info=True)
            return []

    def get_hachu_chubunrui_options(
        self, search_url: str, daibunrui_value: str
    ) -> List[str]:
        """中分類のオプションを取得（大分類の表示テキストを指定）"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            
            # まず大分類の表示テキストからvalueを取得
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                return []
            
            parent_dropdown_name = "drpTopKikanInf"
            parent_value_actual = self._get_dropdown_value_from_text(initial_soup, parent_dropdown_name, daibunrui_value)
            if not parent_value_actual:
                self.logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
                return []
            
            self.logger.debug(f"大分類のvalueを取得: {daibunrui_value} -> {parent_value_actual}")
            
            parent_values = {
                parent_dropdown_name: parent_value_actual
            }
            
            dropdown_name = "drpLargeKikanInf2"
            return self.get_dropdown_options(normalized_url, dropdown_name, parent_values)
            
        except Exception as e:
            self.logger.error(f"中分類オプション取得エラー: {str(e)}", exc_info=True)
            return []

    def get_hachu_shoubunrui_options(
        self, search_url: str, daibunrui_value: str, chubunrui_value: str
    ) -> List[str]:
        """小分類のオプションを取得（大分類と中分類の表示テキストを指定）"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            
            # 初回GET: 大分類のvalueを取得
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                return []
            
            parent_dropdown_name1 = "drpTopKikanInf"
            parent_value1 = self._get_dropdown_value_from_text(initial_soup, parent_dropdown_name1, daibunrui_value)
            if not parent_value1:
                self.logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
                return []
            
            # 大分類を選択してPOST: 中分類のvalueを取得
            form_data = self._get_all_hidden_inputs(initial_soup)
            form_data["__EVENTTARGET"] = parent_dropdown_name1
            form_data["__EVENTARGUMENT"] = ""
            form_data[parent_dropdown_name1] = parent_value1
            
            response = self.http_client.post(normalized_url, data=form_data)
            if response.encoding:
                response.encoding = response.apparent_encoding or 'utf-8'
            else:
                response.encoding = 'utf-8'
            
            try:
                soup_after_daibunrui = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup_after_daibunrui = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup_after_daibunrui = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
            
            parent_dropdown_name2 = "drpLargeKikanInf2"
            parent_value2 = self._get_dropdown_value_from_text(soup_after_daibunrui, parent_dropdown_name2, chubunrui_value)
            if not parent_value2:
                self.logger.warning(f"中分類のvalueが見つかりませんでした: {chubunrui_value}")
                return []
            
            # 中分類を選択してPOST: 小分類のオプションを取得
            form_data2 = self._get_all_hidden_inputs(soup_after_daibunrui)
            form_data2["__EVENTTARGET"] = parent_dropdown_name2
            form_data2["__EVENTARGUMENT"] = ""
            form_data2[parent_dropdown_name1] = parent_value1
            form_data2[parent_dropdown_name2] = parent_value2
            
            # createListItem2で設定される値を明示的に設定
            # txtLgKikanInfSelValue_h = 中分類のテキスト + "," + 中分類のvalue
            form_data2["txtLgKikanInfSelValue_h"] = f"{chubunrui_value},{parent_value2}"
            
            # txtLgKikanInf2SelIndex_h = 中分類の選択インデックス
            # ドロップダウンから選択インデックスを取得
            dropdown_chubunrui = self._get_dropdown_select(soup_after_daibunrui, parent_dropdown_name2)
            if dropdown_chubunrui:
                options_chubunrui = dropdown_chubunrui.find_all("option")
                for idx, opt in enumerate(options_chubunrui):
                    if opt.get("value", "") == parent_value2:
                        form_data2["txtLgKikanInf2SelIndex_h"] = str(idx)
                        self.logger.debug(f"中分類の選択インデックス: {idx}")
                        break
            
            response2 = self.http_client.post(normalized_url, data=form_data2)
            if response2.encoding:
                response2.encoding = response2.apparent_encoding or 'utf-8'
            else:
                response2.encoding = 'utf-8'
            
            response_text2 = response2.text
            
            try:
                soup_after_chubunrui = BeautifulSoup(response2.content, "lxml", from_encoding=response2.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup_after_chubunrui = BeautifulSoup(response2.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup_after_chubunrui = BeautifulSoup(response2.content.decode('utf-8', errors='ignore'), "lxml")
            
            # 小分類のオプションを取得（中分類選択後のPOSTレスポンスから）
            # ① setListItemSub()をJavaScriptから解析
            if "setListItemSub" in response_text2:
                options_from_js = self._parse_setListItemSub(response_text2, "drpMiddleKikanInf")
                if options_from_js:
                    display_texts = [text for _, text in options_from_js]
                    self.logger.info(f"setListItemSub()から小分類{len(display_texts)}個のオプションを取得しました")
                    return display_texts
            
            # ② HTMLから<select><option>を解析
            dropdown = self._get_dropdown_select(soup_after_chubunrui, "drpMiddleKikanInf")
            
            if dropdown:
                options = []
                all_options = dropdown.find_all("option")
                self.logger.debug(f"小分類のドロップダウンから{len(all_options)}個のoption要素を発見")
                
                for option in all_options:
                    text = option.get_text().strip()
                    value = option.get("value", "")
                    if text and value != "-1":  # ▽小分類を除外
                        options.append(text)
                        self.logger.debug(f"  小分類オプション追加: value={value}, text={text}")
                
                if options:
                    self.logger.info(f"HTMLから小分類{len(options)}個のオプションを取得しました")
                    return options
                else:
                    self.logger.warning(f"小分類のオプションが見つかりませんでした（すべてのoption要素: {len(all_options)}件）")
            else:
                self.logger.warning("小分類のドロップダウンが見つかりませんでした")
                # デバッグ: すべてのselect要素を確認
                all_selects = soup_after_chubunrui.find_all("select")
                self.logger.debug(f"ページ内のselect要素数: {len(all_selects)}")
                for i, sel in enumerate(all_selects[:10]):
                    name = sel.get("name", "なし")
                    id_attr = sel.get("id", "なし")
                    self.logger.debug(f"  select要素{i+1}: name={name}, id={id_attr}")
            
            self.logger.warning("小分類のオプションを取得できませんでした")
            return []
            
        except Exception as e:
            self.logger.error(f"小分類オプション取得エラー: {str(e)}", exc_info=True)
            return []
    
    def get_hachu_saibunrui_options(
        self, search_url: str, daibunrui_value: str, chubunrui_value: str, shoubunrui_value: str
    ) -> List[str]:
        """細分類のオプションを取得（大分類、中分類、小分類の表示テキストを指定）"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            
            # 初回GET: 大分類のvalueを取得
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                return []
            
            parent_dropdown_name1 = "drpTopKikanInf"
            parent_value1 = self._get_dropdown_value_from_text(initial_soup, parent_dropdown_name1, daibunrui_value)
            if not parent_value1:
                self.logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
                return []
            
            # 大分類を選択してPOST: 中分類のvalueを取得
            form_data = self._get_all_hidden_inputs(initial_soup)
            form_data["__EVENTTARGET"] = parent_dropdown_name1
            form_data["__EVENTARGUMENT"] = ""
            form_data[parent_dropdown_name1] = parent_value1
            
            response = self.http_client.post(normalized_url, data=form_data)
            if response.encoding:
                response.encoding = response.apparent_encoding or 'utf-8'
            else:
                response.encoding = 'utf-8'
            
            try:
                soup_after_daibunrui = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup_after_daibunrui = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup_after_daibunrui = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
            
            parent_dropdown_name2 = "drpLargeKikanInf2"
            parent_value2 = self._get_dropdown_value_from_text(soup_after_daibunrui, parent_dropdown_name2, chubunrui_value)
            if not parent_value2:
                self.logger.warning(f"中分類のvalueが見つかりませんでした: {chubunrui_value}")
                return []
            
            # 中分類を選択してPOST: 小分類のvalueを取得
            form_data2 = self._get_all_hidden_inputs(soup_after_daibunrui)
            form_data2["__EVENTTARGET"] = parent_dropdown_name2
            form_data2["__EVENTARGUMENT"] = ""
            form_data2[parent_dropdown_name1] = parent_value1
            form_data2[parent_dropdown_name2] = parent_value2
            
            # createListItem2で設定される値を明示的に設定
            # txtLgKikanInfSelValue_h = 中分類のテキスト + "," + 中分類のvalue
            form_data2["txtLgKikanInfSelValue_h"] = f"{chubunrui_value},{parent_value2}"
            
            # txtLgKikanInf2SelIndex_h = 中分類の選択インデックス
            # ドロップダウンから選択インデックスを取得
            dropdown_chubunrui = self._get_dropdown_select(soup_after_daibunrui, parent_dropdown_name2)
            if dropdown_chubunrui:
                options_chubunrui = dropdown_chubunrui.find_all("option")
                for idx, opt in enumerate(options_chubunrui):
                    if opt.get("value", "") == parent_value2:
                        form_data2["txtLgKikanInf2SelIndex_h"] = str(idx)
                        self.logger.debug(f"中分類の選択インデックス: {idx}")
                        break
            
            response2 = self.http_client.post(normalized_url, data=form_data2)
            if response2.encoding:
                response2.encoding = response2.apparent_encoding or 'utf-8'
            else:
                response2.encoding = 'utf-8'
            
            try:
                soup_after_chubunrui = BeautifulSoup(response2.content, "lxml", from_encoding=response2.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup_after_chubunrui = BeautifulSoup(response2.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup_after_chubunrui = BeautifulSoup(response2.content.decode('utf-8', errors='ignore'), "lxml")
            
            parent_dropdown_name3 = "drpMiddleKikanInf"
            parent_value3 = self._get_dropdown_value_from_text(soup_after_chubunrui, parent_dropdown_name3, shoubunrui_value)
            if not parent_value3:
                self.logger.warning(f"小分類のvalueが見つかりませんでした: {shoubunrui_value}")
                return []
            
            # 小分類を選択してPOST: 細分類のオプションを取得
            form_data3 = self._get_all_hidden_inputs(soup_after_chubunrui)
            form_data3["__EVENTTARGET"] = parent_dropdown_name3
            form_data3["__EVENTARGUMENT"] = ""
            form_data3[parent_dropdown_name1] = parent_value1
            form_data3[parent_dropdown_name2] = parent_value2
            form_data3[parent_dropdown_name3] = parent_value3
            
            response3 = self.http_client.post(normalized_url, data=form_data3)
            if response3.encoding:
                response3.encoding = response3.apparent_encoding or 'utf-8'
            else:
                response3.encoding = 'utf-8'
            
            response_text3 = response3.text
            
            try:
                soup_after_shoubunrui = BeautifulSoup(response3.content, "lxml", from_encoding=response3.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup_after_shoubunrui = BeautifulSoup(response3.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup_after_shoubunrui = BeautifulSoup(response3.content.decode('utf-8', errors='ignore'), "lxml")
            
            # 細分類のオプションを取得（小分類選択後のPOSTレスポンスから）
            # ① setListItemSub()をJavaScriptから解析
            if "setListItemSub" in response_text3:
                options_from_js = self._parse_setListItemSub(response_text3, "drpSmallKikanInf")
                if options_from_js:
                    display_texts = [text for _, text in options_from_js]
                    self.logger.info(f"setListItemSub()から細分類{len(display_texts)}個のオプションを取得しました")
                    return display_texts
            
            # ② HTMLから<select><option>を解析
            dropdown = self._get_dropdown_select(soup_after_shoubunrui, "drpSmallKikanInf")
            
            if dropdown:
                options = []
                all_options = dropdown.find_all("option")
                self.logger.debug(f"細分類のドロップダウンから{len(all_options)}個のoption要素を発見")
                
                for option in all_options:
                    text = option.get_text().strip()
                    value = option.get("value", "")
                    if text and value != "-1":  # ▽細分類を除外
                        options.append(text)
                        self.logger.debug(f"  細分類オプション追加: value={value}, text={text}")
                
                if options:
                    self.logger.info(f"HTMLから細分類{len(options)}個のオプションを取得しました")
                    return options
                else:
                    self.logger.warning(f"細分類のオプションが見つかりませんでした（すべてのoption要素: {len(all_options)}件）")
            else:
                self.logger.warning("細分類のドロップダウンが見つかりませんでした")
            
            self.logger.warning("細分類のオプションを取得できませんでした")
            return []
            
        except Exception as e:
            self.logger.error(f"細分類オプション取得エラー: {str(e)}", exc_info=True)
            return []

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

    def submit_search_form(
        self, search_url: str, search_conditions: SearchConditions
    ) -> Optional[BeautifulSoup]:
        """検索フォームを送信して検索結果ページを取得"""
        try:
            self.logger.info(f"検索フォームを送信中: {search_url}")
            
            normalized_url = self._normalize_search_url(search_url)
            
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                return None
            
            # すべてのhidden inputを取得
            form_data = self._get_all_hidden_inputs(initial_soup)
            
            # 検索フォームのデータを構築
            search_form_data = self._build_search_form_data(search_conditions, initial_soup)
            form_data.update(search_form_data)
            
            # POSTリクエストで検索を実行
            response = self.http_client.post(normalized_url, data=form_data)
            
            # エンコーディング処理
            if response.encoding:
                response.encoding = response.apparent_encoding or 'utf-8'
            else:
                response.encoding = 'utf-8'
            
            try:
                soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
            
            self.logger.info("検索結果ページを取得しました")
            return soup
            
        except Exception as e:
            self.logger.error(f"検索フォーム送信エラー: {str(e)}", exc_info=True)
            return None

    def _build_search_form_data(
        self, search_conditions: SearchConditions, initial_soup: BeautifulSoup
    ) -> Dict[str, Any]:
        """検索フォームのデータを構築"""
        form_data = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
        }
        
        # 発注機関（リスト検索） - 表示テキストからvalueに変換
        if search_conditions.hachu_daibunrui:
            value = self._get_dropdown_value_from_text(initial_soup, "drpTopKikanInf", search_conditions.hachu_daibunrui)
            if value:
                form_data["drpTopKikanInf"] = value
        if search_conditions.hachu_chubunrui:
            value = self._get_dropdown_value_from_text(initial_soup, "drpLargeKikanInf2", search_conditions.hachu_chubunrui)
            if value:
                form_data["drpLargeKikanInf2"] = value
        if search_conditions.hachu_shoubunrui:
            value = self._get_dropdown_value_from_text(initial_soup, "drpMiddleKikanInf", search_conditions.hachu_shoubunrui)
            if value:
                form_data["drpMiddleKikanInf"] = value
        if search_conditions.hachu_saibunrui:
            value = self._get_dropdown_value_from_text(initial_soup, "drpSmallKikanInf", search_conditions.hachu_saibunrui)
            if value:
                form_data["drpSmallKikanInf"] = value
        
        # 発注機関（複数選択検索）
        if search_conditions.hachu_multi:
            hachu_multi_value = ",".join(search_conditions.hachu_multi)
            form_data["ctl00$ContentPlaceHolder1$txtHachuMulti"] = hachu_multi_value
        
        # 工事名（文字列検索）
        if search_conditions.koji_name:
            form_data["ctl00$ContentPlaceHolder1$txtKojiName"] = search_conditions.koji_name
        
        # 工事場所（リスト検索）
        if search_conditions.place_search_type == "list":
            if search_conditions.place_chihou:
                form_data["ctl00$ContentPlaceHolder1$ddlPlaceChihou"] = search_conditions.place_chihou
            if search_conditions.place_todofuken:
                form_data["ctl00$ContentPlaceHolder1$txtPlaceTodofuken"] = search_conditions.place_todofuken
            if search_conditions.place_shichouson:
                form_data["ctl00$ContentPlaceHolder1$txtPlaceShichouson"] = search_conditions.place_shichouson
        
        # 工事場所（文字列検索）
        if search_conditions.place_search_type == "text" and search_conditions.place_text:
            form_data["ctl00$ContentPlaceHolder1$txtPlaceText"] = search_conditions.place_text
        
        # 入札契約方式（チェックボックス形式）
        contract_type_map = {
            "一般競争入札": "ctl00$ContentPlaceHolder1$chkContractType1",
            "公募型指名競争入札": "ctl00$ContentPlaceHolder1$chkContractType2",
            "指名競争入札": "ctl00$ContentPlaceHolder1$chkContractType3",
            "随意契約": "ctl00$ContentPlaceHolder1$chkContractType4",
            "その他方式": "ctl00$ContentPlaceHolder1$chkContractType5",
        }
        for contract_type in search_conditions.contract_types:
            if contract_type in contract_type_map:
                form_data[contract_type_map[contract_type]] = "on"
        
        # 最終更新日
        if search_conditions.update_date_type == "past" and search_conditions.update_date_days:
            form_data["ctl00$ContentPlaceHolder1$rdoUpdateDateType"] = "past"
            form_data["ctl00$ContentPlaceHolder1$txtUpdateDateDays"] = str(search_conditions.update_date_days)
        
        # 公告日
        if search_conditions.koukoku_date_type == "range":
            if search_conditions.koukoku_date_start:
                form_data["ctl00$ContentPlaceHolder1$rdoKoukokuDateType"] = "range"
                form_data["ctl00$ContentPlaceHolder1$txtKoukokuDateStart"] = search_conditions.koukoku_date_start
            if search_conditions.koukoku_date_end:
                form_data["ctl00$ContentPlaceHolder1$txtKoukokuDateEnd"] = search_conditions.koukoku_date_end
        
        # 開札日
        if search_conditions.kaisatsu_date_type == "range":
            if search_conditions.kaisatsu_date_start:
                form_data["ctl00$ContentPlaceHolder1$rdoKaisatsuDateType"] = "range"
                form_data["ctl00$ContentPlaceHolder1$txtKaisatsuDateStart"] = search_conditions.kaisatsu_date_start
            if search_conditions.kaisatsu_date_end:
                form_data["ctl00$ContentPlaceHolder1$txtKaisatsuDateEnd"] = search_conditions.kaisatsu_date_end
        
        # 契約日
        if search_conditions.keiyaku_date_type == "range":
            if search_conditions.keiyaku_date_start:
                form_data["ctl00$ContentPlaceHolder1$rdoKeiyakuDateType"] = "range"
                form_data["ctl00$ContentPlaceHolder1$txtKeiyakuDateStart"] = search_conditions.keiyaku_date_start
            if search_conditions.keiyaku_date_end:
                form_data["ctl00$ContentPlaceHolder1$txtKeiyakuDateEnd"] = search_conditions.keiyaku_date_end
        
        # 工事種別
        if search_conditions.koji_shubetsu:
            form_data["ctl00$ContentPlaceHolder1$ddlKojiShubetsu"] = search_conditions.koji_shubetsu
        
        # 工事の業種
        if search_conditions.koji_gyoushu:
            form_data["ctl00$ContentPlaceHolder1$ddlKojiGyoushu"] = search_conditions.koji_gyoushu
        
        # 予定価格
        if search_conditions.yotei_price_min is not None:
            form_data["ctl00$ContentPlaceHolder1$txtYoteiPriceMin"] = str(search_conditions.yotei_price_min)
        if search_conditions.yotei_price_max is not None:
            form_data["ctl00$ContentPlaceHolder1$txtYoteiPriceMax"] = str(search_conditions.yotei_price_max)
        
        # 落札価格／契約価格
        if search_conditions.rakusatsu_price_min is not None:
            form_data["ctl00$ContentPlaceHolder1$txtRakusatsuPriceMin"] = str(search_conditions.rakusatsu_price_min)
        if search_conditions.rakusatsu_price_max is not None:
            form_data["ctl00$ContentPlaceHolder1$txtRakusatsuPriceMax"] = str(search_conditions.rakusatsu_price_max)
        
        # 落札者名／契約者名
        if search_conditions.rakusatsu_name:
            form_data["ctl00$ContentPlaceHolder1$txtRakusatsuName"] = search_conditions.rakusatsu_name
        
        # 電子入札
        if search_conditions.denshi:
            form_data["ctl00$ContentPlaceHolder1$chkDenshi"] = "on"
        
        # 公開文書
        if search_conditions.koukai:
            form_data["ctl00$ContentPlaceHolder1$chkKoukai"] = "on"
        
        # 表示件数
        if search_conditions.display_count:
            form_data["ctl00$ContentPlaceHolder1$ddlDisplayCount"] = str(search_conditions.display_count)
        
        # 検索ボタンをクリック
        form_data["btnSearch"] = "検索開始"
        
        return form_data

    def extract_file_links_from_search_results(
        self, soup: BeautifulSoup, base_url: str, file_types: List[str]
    ) -> List[FileInfo]:
        """検索結果ページからファイルリンクを抽出（案件詳細ページへのリンクも含む）"""
        file_links = []
        
        # dgrSearchListテーブルを探す
        result_table = soup.find("table", id="dgrSearchList")
        
        if result_table:
            # テーブル内のすべての行を取得（ヘッダー行を除く）
            rows = result_table.find_all("tr")
            self.logger.debug(f"検索結果テーブルから{len(rows)}行を発見")
            
            for row in rows:
                # 工事名のリンクを探す（__doPostBackを呼び出すリンク）
                detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
                if detail_link:
                    # __doPostBack('dgrSearchList','$0') のような形式から詳細ページのURLを構築
                    href = detail_link.get("href", "")
                    # JavaScriptの__doPostBackを呼び出すリンクなので、POSTリクエストで詳細ページを取得
                    # 詳細ページのURLは検索結果ページと同じURLで、__EVENTTARGETと__EVENTARGUMENTを設定
                    detail_files = self._extract_files_from_detail_page_via_postback(
                        base_url, href, file_types, soup
                    )
                    file_links.extend(detail_files)
        else:
            # dgrSearchListが見つからない場合は、従来の方法で検索
            result_rows = soup.find_all("tr", class_=lambda x: x and "result" in x.lower())
            
            if not result_rows:
                # 直接ファイルリンクを抽出
                direct_files = self.extract_file_links(soup, base_url, file_types)
                # page_urlは既にextract_file_linksで設定されている（base_url）
                file_links.extend(direct_files)
            else:
                for row in result_rows:
                    detail_link = row.find("a", href=True)
                    if detail_link:
                        detail_url = urljoin(base_url, detail_link.get("href"))
                        detail_files = self._extract_files_from_detail_page(detail_url, file_types)
                        file_links.extend(detail_files)
        
        # 検索結果ページに直接ファイルリンクがある場合も抽出
        direct_files = self.extract_file_links(soup, base_url, file_types)
        file_links.extend(direct_files)
        
        self.logger.info(f"検索結果から{len(file_links)}個のファイルリンクを抽出しました")
        return file_links

    def _extract_files_from_detail_page_via_postback(
        self, base_url: str, postback_href: str, file_types: List[str], current_soup: BeautifulSoup
    ) -> List[FileInfo]:
        """__doPostBackリンクから詳細ページを取得してファイルを抽出"""
        try:
            # __doPostBack('dgrSearchList','$0') のような形式を解析
            import re
            match = re.search(r"__doPostBack\('([^']+)','([^']+)'\)", postback_href)
            if not match:
                return []
            
            event_target = match.group(1)
            event_argument = match.group(2)
            
            # 現在のページのformのaction属性を取得（検索結果ページのURL）
            form = current_soup.find("form")
            if form and form.get("action"):
                # 相対パスを絶対URLに変換
                post_url = urljoin(base_url, form.get("action"))
            else:
                post_url = base_url
            
            # 詳細ページのURLとして使用（page_urlに設定するため）
            detail_url = post_url
            
            # 現在のページのhidden inputを取得
            form_data = self._get_all_hidden_inputs(current_soup)
            form_data["__EVENTTARGET"] = event_target
            form_data["__EVENTARGUMENT"] = event_argument
            
            # POSTリクエストで詳細ページを取得
            response = self.http_client.post(post_url, data=form_data)
            if response.encoding:
                response.encoding = response.apparent_encoding or 'utf-8'
            else:
                response.encoding = 'utf-8'
            
            try:
                detail_soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    detail_soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    detail_soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
            
            if not detail_soup:
                return []
            
            # デバッグ: 詳細ページのHTMLを保存（最初の1件のみ）
            if not hasattr(self, '_detail_page_saved'):
                output_file = Path("test_detail_page.html")
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(str(detail_soup))
                self.logger.debug(f"詳細ページHTMLを保存: {output_file}")
                self._detail_page_saved = True
            
            # 詳細ページのHTMLから直接ファイルリンクを抽出
            # dgrKokokuとdgrKeikaテーブル内のリンクを抽出（再利用可能なメソッドを使用）
            files = self._extract_files_from_tables(detail_soup, detail_url, file_types)
            
            # フォールバック: テーブルから取得できなかった場合、通常のextract_file_linksも試す
            if not files:
                files = self.extract_file_links(detail_soup, detail_url, file_types)
            
            # ファイルが見つかった場合は、UserEntry_Download.aspxを試さない
            # （UserEntry_Download.aspxにはテーブルが存在しないため、試しても0件になる）
            if files:
                self.logger.info(f"詳細ページから{len(files)}個のファイルリンクを抽出しました（UserEntry_Download.aspxはスキップ）")
                return files
            
            # ファイルが見つからなかった場合のみ、従来の方法（UserEntry_Download.aspx）を試す
            # ただし、実際にはUserEntry_Download.aspxにはテーブルがないため、効果がない可能性が高い
            if not files:
                # 詳細ページからAnkenkanriNoとHachushaIdを抽出
                ankenkanri_no = None
                hachusha_id = None
                
                # JavaScriptコードからAnkenkanriNoとHachushaIdを抽出
                import re
                script_tags = detail_soup.find_all("script")
                for script in script_tags:
                    script_text = script.string
                    if script_text and "AnkenkanriNo" in script_text:
                        # var AnkenkanriNo = "021020002022412000000486"; のような形式を抽出
                        match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', script_text)
                        if match:
                            ankenkanri_no = match.group(1)
                            self.logger.debug(f"AnkenkanriNoを抽出: {ankenkanri_no}")
                        
                        match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', script_text)
                        if match:
                            hachusha_id = match.group(1)
                            self.logger.debug(f"HachushaIdを抽出: {hachusha_id}")
                
                # UserEntry_Download.aspxからファイルリンクを取得
                if ankenkanri_no and hachusha_id:
                    download_url = f"https://www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx?data1={ankenkanri_no}&data2={hachusha_id}"
                    self.logger.debug(f"UserEntry_Download.aspxにアクセス: {download_url}")
                    
                    try:
                        download_response = self.http_client.get(download_url)
                        if download_response.status_code == 200:
                            if download_response.encoding:
                                download_response.encoding = download_response.apparent_encoding or 'utf-8'
                            else:
                                download_response.encoding = 'utf-8'
                            
                            try:
                                download_soup = BeautifulSoup(download_response.content, "lxml", from_encoding=download_response.encoding)
                            except (UnicodeDecodeError, LookupError):
                                try:
                                    download_soup = BeautifulSoup(download_response.content, "lxml", from_encoding='utf-8')
                                except UnicodeDecodeError:
                                    download_soup = BeautifulSoup(download_response.content.decode('utf-8', errors='ignore'), "lxml")
                            
                            if download_soup:
                                # UserEntry_Download.aspxページからファイルリンクを抽出
                                # dgrKokoku/dgrKeikaテーブル走査ロジックを使用（詳細ページと同じロジック）
                                files = self._extract_files_from_tables(download_soup, download_url, file_types)
                                if not files:
                                    # フォールバック: 通常のextract_file_linksも試す
                                    files = self.extract_file_links(download_soup, download_url, file_types)
                                self.logger.info(f"UserEntry_Download.aspxから{len(files)}個のファイルリンクを抽出しました")
                                
                                # 詳細ページの文書情報（dgrKokoku、dgrKeika）を取得してメタデータに追加
                                document_names = []
                                kokoku_table = download_soup.find("table", id="dgrKokoku")
                                if kokoku_table:
                                    rows = kokoku_table.find_all("tr")[1:]  # ヘッダー行をスキップ
                                    for row in rows:
                                        cells = row.find_all("td")
                                        if len(cells) > 0:
                                            doc_name = cells[0].get_text(strip=True)
                                            if doc_name:
                                                document_names.append(doc_name)
                                
                                keika_table = download_soup.find("table", id="dgrKeika")
                                if keika_table:
                                    rows = keika_table.find_all("tr")[1:]  # ヘッダー行をスキップ
                                    for row in rows:
                                        cells = row.find_all("td")
                                        if len(cells) > 0:
                                            doc_name = cells[0].get_text(strip=True)
                                            if doc_name:
                                                document_names.append(doc_name)
                                
                                # メタデータを追加
                                metadata = self.extract_metadata(detail_soup)
                                if document_names:
                                    metadata["document_names"] = document_names
                                
                                for file_info in files:
                                    if file_info.metadata:
                                        file_info.metadata.update(metadata)
                                    else:
                                        file_info.metadata = metadata
                    except Exception as e:
                        self.logger.warning(f"UserEntry_Download.aspxからのファイル抽出エラー: {str(e)}")
            
            # 詳細ページに直接ファイルリンクがある場合も抽出
            if not files:
                files = self.extract_file_links(detail_soup, base_url, file_types)
                metadata = self.extract_metadata(detail_soup)
                for file_info in files:
                    if file_info.metadata:
                        file_info.metadata.update(metadata)
                    else:
                        file_info.metadata = metadata
            
            return files
            
        except Exception as e:
            self.logger.warning(f"詳細ページからのファイル抽出エラー（POST）: {postback_href} - {str(e)}")
            return []

    def _extract_files_from_detail_page(self, detail_url: str, file_types: List[str]) -> List[FileInfo]:
        """案件詳細ページからファイルを抽出"""
        try:
            soup = self.fetch_page(detail_url)
            if not soup:
                return []
            
            files = self.extract_file_links(soup, detail_url, file_types)
            
            metadata = self.extract_metadata(soup)
            for file_info in files:
                if file_info.metadata:
                    file_info.metadata.update(metadata)
                else:
                    file_info.metadata = metadata
            
            return files
            
        except Exception as e:
            self.logger.warning(f"詳細ページからのファイル抽出エラー: {detail_url} - {str(e)}")
            return []
