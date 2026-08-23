# -*- coding: utf-8 -*-

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

    def _set_response_encoding(self, response) -> None:
        """レスポンスのエンコーディングを設定（共通処理）"""
        if response.encoding:
            response.encoding = response.apparent_encoding or 'utf-8'
        else:
            response.encoding = 'utf-8'

    def _parse_response_to_soup(self, response) -> BeautifulSoup:
        """レスポンスからBeautifulSoupを生成（共通処理）"""
        self._set_response_encoding(response)
        try:
            return BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
        except (UnicodeDecodeError, LookupError):
            try:
                return BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
            except UnicodeDecodeError:
                return BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")

    def _set_chubunrui_select_index(self, soup: BeautifulSoup, form_data: Dict[str, str], chubunrui_value: str) -> None:
        """中分類の選択インデックスをform_dataに設定"""
        dropdown = soup.find("select", id="drpLargeKikanInf2")
        if dropdown:
            for idx, opt in enumerate(dropdown.find_all("option")):
                if opt.get("value", "") == chubunrui_value:
                    form_data["txtLgKikanInf2SelIndex_h"] = str(idx)
                    self.logger.debug(f"中分類の選択インデックス: {idx}")
                    break

    def _do_postback(self, url: str, soup: BeautifulSoup, event_target: str, additional_data: Optional[Dict[str, str]] = None) -> BeautifulSoup:
        """POSTバックを実行してBeautifulSoupを返す"""
        form_data = self._get_all_hidden_inputs(soup)
        form_data["__EVENTTARGET"] = event_target
        form_data["__EVENTARGUMENT"] = ""
        if additional_data:
            form_data.update(additional_data)
        response = self.http_client.post(url, data=form_data)
        return self._parse_response_to_soup(response)

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
            return self._parse_response_to_soup(response)
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

    def _get_all_form_inputs(self, soup: BeautifulSoup) -> Dict[str, str]:
        """すべてのフォームフィールド（hidden, select, text, checkbox）の値を取得
        
        ASP.NET WebFormsのページネーションでは、検索条件を維持するために
        すべてのフォームフィールドを送信する必要があります。
        """
        form_data = {}
        
        # 1. Hidden inputs
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                form_data[name] = value
        
        # 2. Select elements (ドロップダウン)
        for select in soup.find_all("select"):
            name = select.get("name", "")
            if name:
                # 選択されているオプションの値を取得
                selected_option = select.find("option", selected=True)
                if selected_option:
                    form_data[name] = selected_option.get("value", "")
                else:
                    # 選択されていない場合は最初のオプションの値
                    first_option = select.find("option")
                    if first_option:
                        form_data[name] = first_option.get("value", "")
        
        # 3. Text inputs
        for text_input in soup.find_all("input", type="text"):
            name = text_input.get("name", "")
            value = text_input.get("value", "")
            if name:
                form_data[name] = value
        
        # 4. Checked checkboxes
        for checkbox in soup.find_all("input", type="checkbox"):
            name = checkbox.get("name", "")
            if name and checkbox.get("checked"):
                form_data[name] = checkbox.get("value", "on")
        
        # 5. Checked radio buttons
        for radio in soup.find_all("input", type="radio"):
            name = radio.get("name", "")
            if name and radio.get("checked"):
                form_data[name] = radio.get("value", "")
        
        self.logger.debug(f"全フォームフィールドを{len(form_data)}個取得しました")
        return form_data

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
            
            # 中分類のエントリを探す
            chubunrui_entry_index = None
            for i, entry in enumerate(entries):
                parts = entry.split(",")
                if len(parts) >= 3:
                    chubunrui_value = parts[2]
                    if chubunrui_value == target_key:
                        chubunrui_entry_index = i
                        break
            
            if chubunrui_entry_index is None:
                self.logger.debug(f"中分類値 '{target_key}' が見つかりませんでした")
                return []
            
            # 中分類のエントリの次のエントリから小分類のデータを探す
            # 小分類の形式: 小分類value,小分類名,親の中分類value
            for i in range(chubunrui_entry_index + 1, len(entries)):
                entry = entries[i]
                parts = entry.split(",")
                if len(parts) >= 3:
                    shoubunrui_value = parts[0]
                    shoubunrui_name = parts[1]
                    parent_chubunrui_value = parts[2]
                    
                    # 親の中分類の値が一致する場合、これは小分類のデータ
                    if parent_chubunrui_value == target_key:
                        options.append((shoubunrui_value, shoubunrui_name))
                        self.logger.debug(f"小分類を発見: '{shoubunrui_name}' -> '{shoubunrui_value}'")
                    else:
                        # 親の値が一致しない場合は、次のエントリに移る
                        break
            
            self.logger.info(f"txtLargeKikanInf_hから中分類値 '{target_key}' の小分類を{len(options)}個抽出しました")
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
            self._set_response_encoding(response)
            response_text = response.text
            
            # ① setListItemSub()をJavaScriptから解析
            self.logger.debug("setListItemSub()の解析を開始")
            if "setListItemSub" in response_text:
                self.logger.debug("レスポンスにsetListItemSubが含まれています")
                options_from_js = self._parse_setListItemSub(response_text, dropdown_name)
                if options_from_js:
                    display_texts = [text for _, text in options_from_js]
                    self.logger.info(f"setListItemSub()から{len(display_texts)}個のオプションを取得しました")
                    return display_texts
                else:
                    self.logger.debug("setListItemSub()からオプションを抽出できませんでした")
            else:
                self.logger.debug("レスポンスにsetListItemSubが含まれていません")
            
            # ② HTMLから<select><option>を解析
            self.logger.debug("HTMLから<select><option>の解析を開始")
            soup = self._parse_response_to_soup(response)
            
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
                        # DEBUG: javascript:__doPostBack(...)形式のリンクを検出
                        if href.startswith("javascript:") and "__doPostBack" in href:
                            # PostBackリンクを解析
                            import re
                            match = re.search(r"__doPostBack\('([^']+)','([^']+)'\)", href)
                            if match:
                                event_target = match.group(1)
                                event_argument = match.group(2)
                                
                                # PostBack情報をmetadataに保持
                                postback_info = {
                                    "postback": True,
                                    "postback_info": {
                                        "event_target": event_target,
                                        "event_argument": event_argument,
                                        "postback_href": href,
                                        "document_name": document_name,
                                    },
                                }
                                
                                # FileInfoを作成（URLはPostBack実行後に解決されるため、仮のURLを設定）
                                # 実際のダウンロード時には、PostBackを実行してファイルURLを取得する
                                file_info = FileInfo(
                                    url=f"postback://{event_target}/{event_argument}",  # 仮のURL（PostBack識別用）
                                    filename=document_name or "postback_file",
                                    file_type=".pdf",  # デフォルト（Content-Dispositionから取得可能な場合に上書き）
                                    page_url=base_url,
                                    metadata={"title": document_name, **postback_info} if document_name else postback_info
                                )
                                files.append(file_info)
                                self.logger.debug(
                                    f"PostBackリンクを検出（FileInfo作成）: 文書名='{document_name}', "
                                    f"event_target='{event_target}', event_argument='{event_argument}' (テーブル: {table_id})"
                                )
                            else:
                                self.logger.warning(
                                    f"PostBackリンクの解析に失敗: 文書名='{document_name}', "
                                    f"href='{href[:100]}...' (テーブル: {table_id})"
                                )
                            continue
                        
                        # 相対URLを絶対URLに変換
                        absolute_url = urljoin(base_url, href)
                        
                        # ファイルタイプをチェック（URLに拡張子が含まれている場合）
                        # または、KokaiBunshoServletのようなファイルダウンロードURLの場合
                        is_file_link = False
                        rejection_reason = None
                        
                        if any(href.lower().endswith(ext) for ext in file_types):
                            is_file_link = True
                            self.logger.debug(
                                f"ファイルリンクを採用: 文書名='{document_name}', "
                                f"理由=拡張子一致 ({href[-10:] if len(href) > 10 else href})"
                            )
                        elif "KokaiBunshoServlet" in href or "Publish" in href or "Download" in href:
                            # ファイルダウンロードURLの可能性が高い
                            is_file_link = True
                            self.logger.debug(
                                f"ファイルリンクを採用: 文書名='{document_name}', "
                                f"理由=servlet/Download/Publish文字列検出"
                            )
                        else:
                            rejection_reason = "拡張子なし/servlet文字列なし"
                            self.logger.debug(
                                f"ファイルリンクを不採用: 文書名='{document_name}', "
                                f"理由={rejection_reason}, href='{href[:80]}...'"
                            )
                        
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
            soup_after_daibunrui = self._parse_response_to_soup(response)
            
            parent_dropdown_name2 = "drpLargeKikanInf2"
            parent_value2 = self._get_dropdown_value_from_text(soup_after_daibunrui, parent_dropdown_name2, chubunrui_value)
            if not parent_value2:
                self.logger.warning(f"中分類のvalueが見つかりませんでした: {chubunrui_value}")
                return []
            
            # 中分類を選択してPOST: 小分類のオプションを取得
            additional_data2 = {
                parent_dropdown_name1: parent_value1,
                parent_dropdown_name2: parent_value2,
                "txtLgKikanInfSelValue_h": f"{chubunrui_value},{parent_value2}"
            }
            self._set_chubunrui_select_index(soup_after_daibunrui, additional_data2, parent_value2)
            
            response2 = self.http_client.post(normalized_url, data={**self._get_all_hidden_inputs(soup_after_daibunrui), "__EVENTTARGET": parent_dropdown_name2, "__EVENTARGUMENT": "", **additional_data2})
            self._set_response_encoding(response2)
            response_text2 = response2.text
            soup_after_chubunrui = self._parse_response_to_soup(response2)
            
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
            soup_after_daibunrui = self._parse_response_to_soup(response)
            
            parent_dropdown_name2 = "drpLargeKikanInf2"
            parent_value2 = self._get_dropdown_value_from_text(soup_after_daibunrui, parent_dropdown_name2, chubunrui_value)
            if not parent_value2:
                self.logger.warning(f"中分類のvalueが見つかりませんでした: {chubunrui_value}")
                return []
            
            # 中分類を選択してPOST: 小分類のvalueを取得
            additional_data2 = {
                parent_dropdown_name1: parent_value1,
                parent_dropdown_name2: parent_value2,
                "txtLgKikanInfSelValue_h": f"{chubunrui_value},{parent_value2}"
            }
            self._set_chubunrui_select_index(soup_after_daibunrui, additional_data2, parent_value2)
            soup_after_chubunrui = self._do_postback(normalized_url, soup_after_daibunrui, parent_dropdown_name2, additional_data2)
            
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
            self._set_response_encoding(response3)
            response_text3 = response3.text
            soup_after_shoubunrui = self._parse_response_to_soup(response3)
            
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
        """検索フォームを送信して検索結果ページを取得（階層的ドロップダウン対応）"""
        try:
            self.logger.info(f"検索フォームを送信中: {search_url}")
            
            normalized_url = self._normalize_search_url(search_url)
            
            # 初期ページを取得
            soup = self.fetch_page(normalized_url)
            if not soup:
                return None
            
            # 階層的ドロップダウンのPOSTバックを順次実行
            daibunrui_value = None
            chubunrui_value = None
            shoubunrui_value = None
            saibunrui_value = None
            
            # 1. 大分類を選択してPOSTバック
            if search_conditions.hachu_daibunrui:
                daibunrui_value = self._get_dropdown_value_from_text(soup, "drpTopKikanInf", search_conditions.hachu_daibunrui)
                if daibunrui_value:
                    self.logger.info(f"大分類を選択: '{search_conditions.hachu_daibunrui}' -> '{daibunrui_value}'")
                    soup = self._do_postback(normalized_url, soup, "drpTopKikanInf", {"drpTopKikanInf": daibunrui_value})
                    self.logger.debug("大分類のPOSTバック完了")
                else:
                    self.logger.warning(f"大分類の値が取得できませんでした: '{search_conditions.hachu_daibunrui}'")
            
            # 2. 中分類を選択してPOSTバック
            if search_conditions.hachu_chubunrui and daibunrui_value:
                chubunrui_value = self._get_dropdown_value_from_text(soup, "drpLargeKikanInf2", search_conditions.hachu_chubunrui)
                if chubunrui_value:
                    self.logger.info(f"中分類を選択: '{search_conditions.hachu_chubunrui}' -> '{chubunrui_value}'")
                    additional_data = {
                        "drpTopKikanInf": daibunrui_value,
                        "drpLargeKikanInf2": chubunrui_value,
                        "drpMiddleKikanInf": "-1",
                        "drpSmallKikanInf": "-1",
                        "txtLgKikanInfSelValue_h": f"{search_conditions.hachu_chubunrui},{chubunrui_value}",
                        "txt_ChangeTopKikan": "true" if daibunrui_value else "false",
                        "txt_ChangeLargeKikan": "true"
                    }
                    self._set_chubunrui_select_index(soup, additional_data, chubunrui_value)
                    soup = self._do_postback(normalized_url, soup, "drpLargeKikanInf2", additional_data)
                    self.logger.debug("中分類のPOSTバック完了")
                else:
                    self.logger.warning(f"中分類の値が取得できませんでした: '{search_conditions.hachu_chubunrui}'")
            
            # 3. 小分類の選択肢を取得（POSTバック後のHTMLから）
            if search_conditions.hachu_shoubunrui and chubunrui_value:
                # まず、POSTバック後のHTMLから小分類の選択肢を取得
                dropdown = soup.find("select", id="drpMiddleKikanInf")
                if dropdown:
                    options = dropdown.find_all("option")
                    self.logger.debug(f"POSTバック後のHTMLから小分類の選択肢を{len(options)}個取得しました")
                    
                    # 小分類の値を取得
                    for opt in options:
                        value = opt.get("value", "")
                        text = opt.get_text(strip=True)
                        if value != "-1" and search_conditions.hachu_shoubunrui in text:
                            shoubunrui_value = value
                            self.logger.info(f"小分類を選択: '{text}' -> '{shoubunrui_value}'")
                            break
                
                # HTMLから取得できなかった場合、txtLargeKikanInf_hから取得を試みる
                if not shoubunrui_value:
                    form_data = self._get_all_hidden_inputs(soup)
                    if "txtLargeKikanInf_h" in form_data:
                        shoubunrui_options = self._parse_txtLargeKikanInf_h(form_data["txtLargeKikanInf_h"], chubunrui_value)
                        self.logger.info(f"txtLargeKikanInf_hから小分類の選択肢を{len(shoubunrui_options)}個取得しました")
                        
                        # 小分類の値を取得
                        for value, text in shoubunrui_options:
                            if search_conditions.hachu_shoubunrui in text:
                                shoubunrui_value = value
                                self.logger.info(f"小分類を選択: '{text}' -> '{shoubunrui_value}'")
                                break
                        
                        if not shoubunrui_value:
                            self.logger.warning(f"小分類の値が取得できませんでした: '{search_conditions.hachu_shoubunrui}'")
                            self.logger.debug(f"利用可能な小分類: {[text for _, text in shoubunrui_options]}")
                    else:
                        self.logger.warning("txtLargeKikanInf_hが見つかりませんでした")
            
            # 4. 小分類を選択してPOSTバック（細分類の選択肢を読み込むため）
            if search_conditions.hachu_shoubunrui and shoubunrui_value:
                self.logger.info(f"小分類を選択してPOSTバック: '{shoubunrui_value}'")
                additional_data = {
                    "drpTopKikanInf": daibunrui_value,
                    "drpLargeKikanInf2": chubunrui_value,
                    "drpMiddleKikanInf": shoubunrui_value,
                    "drpSmallKikanInf": "-1"
                }
                if chubunrui_value:
                    self._set_chubunrui_select_index(soup, additional_data, chubunrui_value)
                soup = self._do_postback(normalized_url, soup, "drpMiddleKikanInf", additional_data)
                self.logger.debug("小分類のPOSTバック完了")
            
            # 5. 細分類を選択（必要な場合）
            if search_conditions.hachu_saibunrui and shoubunrui_value:
                # POSTバック後のHTMLから細分類の選択肢を取得
                dropdown = soup.find("select", id="drpSmallKikanInf")
                if dropdown:
                    options = dropdown.find_all("option")
                    self.logger.debug(f"POSTバック後のHTMLから細分類の選択肢を{len(options)}個取得しました")
                    
                    # 細分類の値を取得
                    for opt in options:
                        value = opt.get("value", "")
                        text = opt.get_text(strip=True)
                        if value != "-1" and search_conditions.hachu_saibunrui in text:
                            saibunrui_value = value
                            self.logger.info(f"細分類を選択: '{text}' -> '{saibunrui_value}'")
                            break
                
                if not saibunrui_value:
                    self.logger.warning(f"細分類の値が取得できませんでした: '{search_conditions.hachu_saibunrui}'")
            
            # 6. 検索フォームのデータを構築
            form_data = self._get_all_hidden_inputs(soup)
            search_form_data = self._build_search_form_data(search_conditions, soup)
            form_data.update(search_form_data)
            
            # 階層的ドロップダウンの値を明示的に設定
            if daibunrui_value:
                form_data["drpTopKikanInf"] = daibunrui_value
            if chubunrui_value:
                form_data["drpLargeKikanInf2"] = chubunrui_value
            if shoubunrui_value:
                form_data["drpMiddleKikanInf"] = shoubunrui_value
                self.logger.info(f"小分類の値を設定: '{shoubunrui_value}'")
            if saibunrui_value:
                form_data["drpSmallKikanInf"] = saibunrui_value
            
            # 中分類の選択インデックスを再設定（検索時に必要）
            if chubunrui_value:
                self._set_chubunrui_select_index(soup, form_data, chubunrui_value)
            
            # POSTリクエストで検索を実行
            response = self.http_client.post(normalized_url, data=form_data)
            soup = self._parse_response_to_soup(response)
            
            # リダイレクト後の最終URLを保存（次ページ取得時に使用）
            self._last_search_result_url = response.url
            self.logger.info(f"検索結果ページを取得しました (URL: {response.url})")
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
        
        # 発注機関（複数選択検索） - このフィールドは複数選択モードで使用
        # 注意: 実際のフィールド名はtxt_MultiSearchFlagと関連するhidden値
        if search_conditions.hachu_multi:
            hachu_multi_value = ",".join(search_conditions.hachu_multi)
            form_data["txt_MultiSearchFlag"] = hachu_multi_value
        
        # 工事名（文字列検索）
        if search_conditions.koji_name:
            # 正しいフィールド名: tbxKojiNm（ブラウザのHTMLから確認）
            form_data["tbxKojiNm"] = search_conditions.koji_name
        
        # 工事場所（リスト検索、正しいフィールド名: drpKojiDistrict, drpKojiPrefecture2, drpKojiCity）
        if search_conditions.place_search_type == "list":
            # ラジオボタンでリスト検索を選択
            form_data["KojiRadioGroup"] = "rbKojiDropList"
            if search_conditions.place_chihou:
                form_data["drpKojiDistrict"] = search_conditions.place_chihou
            if search_conditions.place_todofuken:
                form_data["drpKojiPrefecture2"] = search_conditions.place_todofuken
            if search_conditions.place_shichouson:
                form_data["drpKojiCity"] = search_conditions.place_shichouson
        
        # 工事場所（文字列検索、正しいフィールド名: tbxKojiPlace）
        if search_conditions.place_search_type == "text" and search_conditions.place_text:
            form_data["KojiRadioGroup"] = "rbStrKojiPlace"
            form_data["tbxKojiPlace"] = search_conditions.place_text
        
        # 入札契約方式（チェックボックス形式、正しいフィールド名: chkKojiNyusatsu*）
        contract_type_map = {
            "一般競争入札": "chkKojiNyusatsu1",
            "公募型指名競争入札": "chkKojiNyusatsu2",
            "指名競争入札": "chkKojiNyusatsu3",
            "随意契約": "chkKojiNyusatsu4",
            "その他方式": "chkKojiNyusatsu5",
        }
        for contract_type in search_conditions.contract_types:
            if contract_type in contract_type_map:
                form_data[contract_type_map[contract_type]] = "on"
        
        # 最終更新日（正しいフィールド名: LastUpdate, tbxLastUpdate）
        if search_conditions.update_date_type == "past" and search_conditions.update_date_days:
            form_data["LastUpdate"] = "rbtLastUpdate2"
            form_data["tbxLastUpdate"] = str(search_conditions.update_date_days)
        
        # 公告日（正しいフィールド名: KokokuDateKeika, dateKokokuFromKeika, dateKokokuToKeika）
        if search_conditions.koukoku_date_type == "range":
            form_data["KokokuDateKeika"] = "rbtKokokuDate2Keika"
            if search_conditions.koukoku_date_start:
                form_data["dateKokokuFromKeika"] = search_conditions.koukoku_date_start
            if search_conditions.koukoku_date_end:
                form_data["dateKokokuToKeika"] = search_conditions.koukoku_date_end
        
        # 開札日（正しいフィールド名: KaisatsuDate, dateKaisatsuFrom, dateKaisatsuTo）
        if search_conditions.kaisatsu_date_type == "range":
            form_data["KaisatsuDate"] = "rbtKaisatsuDate2"
            if search_conditions.kaisatsu_date_start:
                form_data["dateKaisatsuFrom"] = search_conditions.kaisatsu_date_start
            if search_conditions.kaisatsu_date_end:
                form_data["dateKaisatsuTo"] = search_conditions.kaisatsu_date_end
        
        # 契約日（正しいフィールド名: KeiyakuDate, dateKeiyakuFrom, dateKeiyakuTo）
        if search_conditions.keiyaku_date_type == "range":
            form_data["KeiyakuDate"] = "rbtKeiyakuDate2"
            if search_conditions.keiyaku_date_start:
                form_data["dateKeiyakuFrom"] = search_conditions.keiyaku_date_start
            if search_conditions.keiyaku_date_end:
                form_data["dateKeiyakuTo"] = search_conditions.keiyaku_date_end
        
        # 工事種別（正しいフィールド名: drpKojiKbn）
        # ラベルまたはコードをコードに変換してPOST値に設定
        if search_conditions.koji_shubetsu:
            from .ppi_dropdowns import label_to_code
            code = label_to_code("koji_shubetsu", search_conditions.koji_shubetsu, self.logger)
            if code:
                form_data["drpKojiKbn"] = code
        
        # 工事の業種（正しいフィールド名: drpKojiGyosyu）
        # ラベルまたはコードをコードに変換してPOST値に設定
        if search_conditions.koji_gyoushu:
            from .ppi_dropdowns import label_to_code
            code = label_to_code("koji_gyoushu", search_conditions.koji_gyoushu, self.logger)
            if code:
                form_data["drpKojiGyosyu"] = code
        
        # 予定価格（正しいフィールド名: tbxYoteiPriceFrom, tbxYoteiPriceTo）
        if search_conditions.yotei_price_min is not None:
            form_data["tbxYoteiPriceFrom"] = str(search_conditions.yotei_price_min)
        if search_conditions.yotei_price_max is not None:
            form_data["tbxYoteiPriceTo"] = str(search_conditions.yotei_price_max)
        
        # 落札価格／契約価格（正しいフィールド名: tbxRakusatsuPriceFrom, tbxRakusatsuPriceTo）
        if search_conditions.rakusatsu_price_min is not None:
            form_data["tbxRakusatsuPriceFrom"] = str(search_conditions.rakusatsu_price_min)
        if search_conditions.rakusatsu_price_max is not None:
            form_data["tbxRakusatsuPriceTo"] = str(search_conditions.rakusatsu_price_max)
        
        # 落札者名／契約者名（正しいフィールド名: tbxRakusatsuNm）
        if search_conditions.rakusatsu_name:
            form_data["tbxRakusatsuNm"] = search_conditions.rakusatsu_name
        
        # 電子入札（正しいフィールド名: chkElectronicNyusatsu）
        if search_conditions.denshi:
            form_data["chkElectronicNyusatsu"] = "on"
        
        # 公開文書（正しいフィールド名: chkKokaiBunsyo）
        if search_conditions.koukai:
            form_data["chkKokaiBunsyo"] = "on"
        
        # 表示件数（正しいフィールド名: drpCount）
        if search_conditions.display_count:
            form_data["drpCount"] = str(search_conditions.display_count)
        
        # 検索ボタンをクリック
        form_data["btnSearch"] = "検索開始"
        
        return form_data

    def extract_file_links_from_search_results(
        self, soup: BeautifulSoup, base_url: str, file_types: List[str], search_conditions: SearchConditions = None
    ) -> List[FileInfo]:
        """検索結果ページからファイルリンクを抽出（全ページを処理、ページネーション対応）
        
        Args:
            soup: 検索結果ページのBeautifulSoupオブジェクト
            base_url: ベースURL
            file_types: ファイルタイプのリスト
            search_conditions: 検索条件（工事名でフィルタリングする場合に使用）
        
        Note:
            処理後、self.last_search_total_koji_count に検索結果の工事件数が設定されます
        """
        all_file_links = []
        current_soup = soup
        page_number = 1
        max_pages = 100  # 無限ループ防止
        total_koji_count = 0  # 全ページの工事件数をカウント
        
        while page_number <= max_pages:
            self.logger.info(f"検索結果ページ {page_number} を処理中...")
            
            # 現在のページの工事件数をカウント（詳細ページアクセス前に）
            page_koji_count = self._count_koji_in_page(current_soup, search_conditions)
            total_koji_count += page_koji_count
            self.logger.info(f"ページ {page_number} の工事件数: {page_koji_count}件 (累計: {total_koji_count}件)")
            
            # 現在のページからファイルリンクを抽出
            page_files = self._extract_file_links_from_single_page(
                current_soup, base_url, file_types, search_conditions
            )
            all_file_links.extend(page_files)
            
            # 次のページが存在するか確認
            next_page_soup = self._get_next_page(current_soup, base_url)
            if next_page_soup is None:
                self.logger.info(f"全{page_number}ページの処理が完了しました")
                break
            
            current_soup = next_page_soup
            page_number += 1
        
        # 工事件数を属性として保存（service.pyから参照可能）
        self.last_search_total_koji_count = total_koji_count

        # 発注機関階層・検索種別を全 FileInfo の metadata に補完（フォルダ構造で使用）
        for f in all_file_links:
            self._ensure_agency_metadata(f, search_conditions, base_url)
        
        self.logger.info(f"検索結果から合計{len(all_file_links)}個のファイルリンクを抽出しました（工事件数: {total_koji_count}件）")
        return all_file_links

    def _infer_search_tab_from_url(self, url: str) -> str:
        """URL の tab パラメータから検索種別を推定。works=工事, services=業務。"""
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
            return tab or "unknown"
        except Exception:
            return "unknown"

    def _ensure_agency_metadata(
        self, file_info: FileInfo, search_conditions: Optional[SearchConditions], base_url: str
    ) -> None:
        """FileInfo.metadata に発注機関階層と search_tab を欠損時は unknown で補完する。"""
        if not file_info.metadata:
            file_info.metadata = {}
        fallback = "unknown"
        if search_conditions:
            sc = search_conditions
            if "daibunrui" not in file_info.metadata or not file_info.metadata.get("daibunrui"):
                file_info.metadata["daibunrui"] = (sc.hachu_daibunrui or "").strip() or fallback
            if "chubunrui" not in file_info.metadata or not file_info.metadata.get("chubunrui"):
                file_info.metadata["chubunrui"] = (sc.hachu_chubunrui or "").strip() or fallback
            if "shoubunrui" not in file_info.metadata or not file_info.metadata.get("shoubunrui"):
                file_info.metadata["shoubunrui"] = (sc.hachu_shoubunrui or "").strip() or fallback
            if "saibunrui" not in file_info.metadata or not file_info.metadata.get("saibunrui"):
                file_info.metadata["saibunrui"] = (sc.hachu_saibunrui or "").strip() or fallback
        else:
            file_info.metadata.setdefault("daibunrui", fallback)
            file_info.metadata.setdefault("chubunrui", fallback)
            file_info.metadata.setdefault("shoubunrui", fallback)
            file_info.metadata.setdefault("saibunrui", fallback)
        if "search_tab" not in file_info.metadata or not file_info.metadata.get("search_tab"):
            file_info.metadata["search_tab"] = self._infer_search_tab_from_url(base_url)
    
    def _count_koji_in_page(self, soup: BeautifulSoup, search_conditions: SearchConditions = None) -> int:
        """現在のページの工事件数をカウント"""
        result_table = soup.find("table", id="dgrSearchList")
        if not result_table:
            return 0
        
        rows = result_table.find_all("tr")[1:]  # ヘッダー行を除く
        count = 0
        
        for row in rows:
            # 工事名のリンクを探す
            detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
            if not detail_link:
                continue
            
            # 工事名を取得
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
            
            # 検索条件で工事名が指定されている場合、フィルタリング
            if search_conditions and search_conditions.koji_name:
                if search_conditions.koji_name not in koji_name:
                    continue
            
            count += 1
        
        return count
    
    def _get_next_page(self, current_soup: BeautifulSoup, base_url: str) -> Optional[BeautifulSoup]:
        """次のページを取得（存在しない場合はNoneを返す）"""
        # 「次ページ」ボタンを探す（inputタイプのsubmit）
        next_button = current_soup.find("input", {"type": "submit", "value": "次ページ"})
        
        # IDで探す（btnNext1, btnNext2）
        if not next_button:
            next_button = current_soup.find("input", {"id": "btnNext1"})
        if not next_button:
            next_button = current_soup.find("input", {"id": "btnNext2"})
        
        # buttonタイプも確認
        if not next_button:
            next_button = current_soup.find("button", string=lambda x: x and "次ページ" in x)
        
        # inputタイプのbutton（id="btnNext"など）も確認
        if not next_button:
            next_button = current_soup.find("input", {"id": lambda x: x and "Next" in str(x)})
        
        if not next_button:
            self.logger.debug("次ページボタンが見つかりません（検索結果に全件表示済みの可能性）")
            return None
        
        # ボタンがdisabledの場合は次のページがない
        if next_button.get("disabled"):
            self.logger.debug("次ページボタンが無効化されています（最終ページです）")
            return None
        
        # ボタンの名前を取得
        button_name = next_button.get("name", "")
        if not button_name:
            self.logger.warning(f"次ページボタンの名前が取得できません: {next_button}")
            return None
        
        self.logger.info(f"次ページに移動中... (ボタン名: {button_name})")
        
        # POSTバックで次のページを取得（全フォームフィールドの値を送信）
        form_data = self._get_all_form_inputs(current_soup)
        self.logger.debug(f"Form inputs: __VIEWSTATE={len(form_data.get('__VIEWSTATE', ''))}, __EVENTVALIDATION={len(form_data.get('__EVENTVALIDATION', ''))}, total_fields={len(form_data)}")
        form_data[button_name] = next_button.get("value", "次ページ")
        
        # フォームのaction属性からPOST先URLを取得（これが最も重要！）
        form = current_soup.find("form")
        if form and form.get("action"):
            form_action = form.get("action")
            # 相対URLを絶対URLに変換
            # 重要: 基準URLは「最後にアクセスしたページのURL」を使用する
            # （元の検索条件ページのURLではない）
            from urllib.parse import urljoin
            current_page_url = getattr(self, '_last_search_result_url', base_url)
            actual_url = urljoin(current_page_url, form_action)
            self.logger.info(f"フォームaction属性から取得したURL: {actual_url} (基準URL: {current_page_url})")
        else:
            # フォームaction属性がない場合は、保存されたURLを使用
            actual_url = getattr(self, '_last_search_result_url', base_url)
            self.logger.debug(f"フォームaction属性なし、保存されたURLを使用: {actual_url}")
        
        try:
            response = self.http_client.post(actual_url, data=form_data)
            self.logger.debug(f"次ページ応答: status={response.status_code}, content_length={len(response.content)}")
            next_soup = self._parse_response_to_soup(response)
            
            # 次ページのURLも更新
            self._last_search_result_url = response.url
            
            if not next_soup:
                self.logger.warning("次ページの解析に失敗しました")
                return None
            
            # 検索結果テーブルが存在するか確認
            result_table = next_soup.find("table", id="dgrSearchList")
            if result_table:
                rows = result_table.find_all("tr")[1:]  # ヘッダー以外
                self.logger.debug(f"次ページで検索結果テーブルを発見: {len(rows)}行")
                return next_soup
            else:
                # ページタイトルを確認
                title = next_soup.find("title")
                title_text = title.get_text() if title else "不明"
                self.logger.warning(f"次ページに検索結果テーブルがありません (ページタイトル: {title_text})")
                return None
        except Exception as e:
            self.logger.error(f"次ページの取得に失敗: {str(e)}", exc_info=True)
            return None
    
    def _extract_file_links_from_single_page(
        self, soup: BeautifulSoup, base_url: str, file_types: List[str], search_conditions: SearchConditions = None
    ) -> List[FileInfo]:
        """単一の検索結果ページからファイルリンクを抽出"""
        file_links = []
        
        # dgrSearchListテーブルを探す
        result_table = soup.find("table", id="dgrSearchList")
        
        if result_table:
            # テーブル内のすべての行を取得（ヘッダー行を除く）
            rows = result_table.find_all("tr")[1:]  # 最初の行はヘッダー
            self.logger.debug(f"検索結果テーブルから{len(rows)}行を発見（ヘッダー行を除く）")
            
            filtered_count = 0
            for row in rows:
                # 工事名のリンクを探す（__doPostBackを呼び出すリンク）
                detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
                if not detail_link:
                    # __doPostBackリンクがない場合はスキップ（ヘッダー行や無効な行の可能性）
                    continue
                
                # 検索結果ページから工事名を抽出（リンクのテキストから）
                koji_name = detail_link.get_text(strip=True)
                if not koji_name:
                    # リンクのテキストが空の場合は、同じ行の他のセルから工事名を探す
                    cells = row.find_all("td")
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        if text and text != "":
                            koji_name = text
                            break
                
                # 工事名が空文字列の場合はスキップ
                if not koji_name:
                    self.logger.debug("工事名が抽出できなかったため、この行をスキップします")
                    continue
                
                # 検索条件で工事名が指定されている場合、フィルタリング
                if search_conditions and search_conditions.koji_name:
                    if search_conditions.koji_name not in koji_name:
                        # 検索条件に一致しない場合はスキップ
                        filtered_count += 1
                        self.logger.debug(f"工事名フィルタリング: '{koji_name}' は '{search_conditions.koji_name}' を含まないためスキップ")
                        continue
                
                # __doPostBack('dgrSearchList','$0') のような形式から詳細ページのURLを構築
                href = detail_link.get("href", "")
                # JavaScriptの__doPostBackを呼び出すリンクなので、POSTリクエストで詳細ページを取得
                # 詳細ページのURLは検索結果ページと同じURLで、__EVENTTARGETと__EVENTARGUMENTを設定
                detail_files = self._extract_files_from_detail_page_via_postback(
                    base_url, href, file_types, soup, koji_name=koji_name
                )
                file_links.extend(detail_files)
            
            if filtered_count > 0:
                self.logger.info(f"工事名フィルタリング: {filtered_count}件の工事を除外しました")
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
        
        self.logger.info(f"このページから{len(file_links)}個のファイルリンクを抽出しました")
        return file_links

    def _extract_files_from_detail_page_via_postback(
        self, base_url: str, postback_href: str, file_types: List[str], current_soup: BeautifulSoup, koji_name: str = None
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
            # 重要: base_urlではなく、最後にアクセスしたページのURLを基準にする
            current_page_url = getattr(self, '_last_search_result_url', base_url)
            
            form = current_soup.find("form")
            if form and form.get("action"):
                # 相対パスを絶対URLに変換（現在のページURLを基準にする）
                post_url = urljoin(current_page_url, form.get("action"))
            else:
                post_url = current_page_url
            
            # 詳細ページのURLとして使用（page_urlに設定するため）
            detail_url = post_url
            
            # 現在のページのhidden inputを取得
            form_data = self._get_all_hidden_inputs(current_soup)
            form_data["__EVENTTARGET"] = event_target
            form_data["__EVENTARGUMENT"] = event_argument
            
            # POSTリクエストで詳細ページを取得
            response = self.http_client.post(post_url, data=form_data)
            detail_soup = self._parse_response_to_soup(response)
            
            if not detail_soup:
                return []
            
            # デバッグ: 詳細ページのHTMLを保存（最初の1件のみ。生成物は artifacts/ に出力）
            if not hasattr(self, '_detail_page_saved'):
                output_file = Path("artifacts/test_detail_page.html")
                output_file.parent.mkdir(parents=True, exist_ok=True)
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
            
            # 工事名をメタデータに追加
            # 1. 検索結果ページから取得した工事名を使用
            # 2. 取得できなかった場合は、詳細ページから抽出
            if koji_name:
                # 検索結果ページから取得した工事名を使用
                for file_info in files:
                    if not file_info.metadata:
                        file_info.metadata = {}
                    file_info.metadata["koji_name"] = koji_name
            else:
                # 詳細ページから工事名を抽出
                metadata = self.extract_metadata(detail_soup)
                if "koji_name" in metadata:
                    for file_info in files:
                        if not file_info.metadata:
                            file_info.metadata = {}
                        file_info.metadata["koji_name"] = metadata["koji_name"]
            
            # DEBUG: 詳細ページからの抽出結果をログ出力
            if files:
                self.logger.info(f"詳細ページから{len(files)}個のファイルリンクを抽出しました")
                for idx, f in enumerate(files, 1):
                    self.logger.debug(
                        f"  ファイル[{idx}]: 文書名='{f.metadata.get('title', 'N/A')}', "
                        f"URL='{f.url[:80]}...', type={f.file_type}"
                    )
            else:
                self.logger.debug("詳細ページからファイルリンクを抽出できませんでした")
            
            # 重要: 詳細ページでファイルが見つかっても、UserEntry_Download.aspxを必ず探索する
            # （入札調書など、UserEntry_Download.aspxにのみ存在するファイルがある可能性があるため）
            # 詳細ページのファイルとUserEntry_Download.aspxのファイルをマージする
            userentry_files = []
            
            # UserEntry_Download.aspxからファイルリンクを取得（詳細ページにファイルがあっても実行）
            # 詳細ページからAnkenkanriNoとHachushaIdを抽出
            ankenkanri_no = None
            hachusha_id = None
            
            # JavaScriptコードからAnkenkanriNoとHachushaIdを抽出（堅牢化）
            # script.stringだけでなく、script.get_text()やsoup.get_text()も使用
            import re
            
            # 方法1: script.stringから抽出（従来の方法）
            script_tags = detail_soup.find_all("script")
            for script in script_tags:
                script_text = script.string
                if script_text and "AnkenkanriNo" in script_text:
                    # var AnkenkanriNo = "021020002022412000000486"; のような形式を抽出
                    match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', script_text)
                    if match:
                        ankenkanri_no = match.group(1)
                        self.logger.debug(f"AnkenkanriNoを抽出（script.string）: {ankenkanri_no}")
                    
                    match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', script_text)
                    if match:
                        hachusha_id = match.group(1)
                        self.logger.debug(f"HachushaIdを抽出（script.string）: {hachusha_id}")
            
            # 方法2: script.get_text()から抽出（script.stringがNoneの場合）
            if not ankenkanri_no or not hachusha_id:
                for script in script_tags:
                    script_text = script.get_text()
                    if script_text and "AnkenkanriNo" in script_text:
                        match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', script_text)
                        if match and not ankenkanri_no:
                            ankenkanri_no = match.group(1)
                            self.logger.debug(f"AnkenkanriNoを抽出（script.get_text()）: {ankenkanri_no}")
                        
                        match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', script_text)
                        if match and not hachusha_id:
                            hachusha_id = match.group(1)
                            self.logger.debug(f"HachushaIdを抽出（script.get_text()）: {hachusha_id}")
            
            # 方法3: soup.get_text()から抽出（scriptタグから取得できない場合）
            if not ankenkanri_no or not hachusha_id:
                page_text = detail_soup.get_text()
                if "AnkenkanriNo" in page_text:
                    match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', page_text)
                    if match and not ankenkanri_no:
                        ankenkanri_no = match.group(1)
                        self.logger.debug(f"AnkenkanriNoを抽出（soup.get_text()）: {ankenkanri_no}")
                    
                    match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', page_text)
                    if match and not hachusha_id:
                        hachusha_id = match.group(1)
                        self.logger.debug(f"HachushaIdを抽出（soup.get_text()）: {hachusha_id}")
            
            # 抽出失敗時のログ出力（INFO/WARNレベル）
            if not ankenkanri_no:
                self.logger.warning(
                    "AnkenkanriNoを抽出できませんでした（UserEntry_Download.aspxをスキップ）。"
                    "詳細ページのHTML構造が変更されている可能性があります。"
                )
            if not hachusha_id:
                self.logger.warning(
                    "HachushaIdを抽出できませんでした（UserEntry_Download.aspxをスキップ）。"
                    "詳細ページのHTML構造が変更されている可能性があります。"
                )
            
            # UserEntry_Download.aspxからファイルリンクを取得
            if ankenkanri_no and hachusha_id:
                download_url = f"https://www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx?data1={ankenkanri_no}&data2={hachusha_id}"
                self.logger.debug(f"UserEntry_Download.aspxにアクセス（詳細ページに{len(files)}件のファイルがある場合でも実行）: {download_url}")
                
                try:
                    download_response = self.http_client.get(download_url)
                    self.logger.debug(
                        f"UserEntry_Download.aspx レスポンス: status={download_response.status_code}, "
                        f"Content-Type={download_response.headers.get('Content-Type', 'N/A')}"
                    )
                    
                    if download_response.status_code == 200:
                        download_soup = self._parse_response_to_soup(download_response)
                        if download_soup:
                            # UserEntry_Download.aspxページからファイルリンクを抽出
                            # dgrKokoku/dgrKeikaテーブル走査ロジックを使用（詳細ページと同じロジック）
                            userentry_files = self._extract_files_from_tables(download_soup, download_url, file_types)
                            if not userentry_files:
                                # フォールバック: 通常のextract_file_linksも試す
                                userentry_files = self.extract_file_links(download_soup, download_url, file_types)
                            
                            if userentry_files:
                                self.logger.info(f"UserEntry_Download.aspxから{len(userentry_files)}個のファイルリンクを抽出しました")
                                for idx, f in enumerate(userentry_files, 1):
                                    self.logger.debug(
                                        f"  UserEntryファイル[{idx}]: 文書名='{f.metadata.get('title', 'N/A')}', "
                                        f"URL='{f.url[:80]}...', type={f.file_type}"
                                    )
                            
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
                            
                            # 工事名を優先的に設定（検索結果ページから取得した工事名があれば使用）
                            if koji_name:
                                metadata["koji_name"] = koji_name
                            
                            for file_info in userentry_files:
                                if file_info.metadata:
                                    file_info.metadata.update(metadata)
                                else:
                                    file_info.metadata = metadata
                    else:
                        self.logger.warning(
                            f"UserEntry_Download.aspx アクセス失敗: status={download_response.status_code}"
                        )
                except Exception as e:
                    self.logger.warning(f"UserEntry_Download.aspxからのファイル抽出エラー: {str(e)}", exc_info=True)
            else:
                # 抽出失敗時は既にWARNINGログを出力しているため、ここでは何もしない
                pass
            
            # 詳細ページのファイルとUserEntry_Download.aspxのファイルをマージ（重複除去）
            # 重複判定: URLが同一、または（文書名 + ファイルタイプ）が同一
            all_files = files.copy()  # 詳細ページのファイル
            existing_urls = {f.url for f in files}
            existing_keys = {(f.metadata.get("title", ""), f.file_type) for f in files}
            
            for uf in userentry_files:
                # URL重複チェック
                if uf.url in existing_urls:
                    self.logger.debug(f"重複ファイルをスキップ（URL同一）: {uf.url[:80]}...")
                    continue
                
                # （文書名 + ファイルタイプ）重複チェック
                uf_key = (uf.metadata.get("title", ""), uf.file_type)
                if uf_key in existing_keys:
                    self.logger.debug(
                        f"重複ファイルをスキップ（文書名+タイプ同一）: "
                        f"文書名='{uf.metadata.get('title', 'N/A')}', type={uf.file_type}"
                    )
                    continue
                
                # 重複なし: 追加
                all_files.append(uf)
                existing_urls.add(uf.url)
                existing_keys.add(uf_key)
                self.logger.debug(f"UserEntryファイルを追加: 文書名='{uf.metadata.get('title', 'N/A')}', URL='{uf.url[:80]}...'")
            
            self.logger.info(
                f"ファイル抽出完了: 詳細ページ={len(files)}件, "
                f"UserEntry_Download.aspx={len(userentry_files)}件, "
                f"マージ後={len(all_files)}件（重複除去済み）"
            )
            
            return all_files
            
            # 詳細ページに直接ファイルリンクがある場合も抽出
            if not files:
                files = self.extract_file_links(detail_soup, base_url, file_types)
                metadata = self.extract_metadata(detail_soup)
                # 工事名を優先的に設定（検索結果ページから取得した工事名があれば使用）
                if koji_name:
                    metadata["koji_name"] = koji_name
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
