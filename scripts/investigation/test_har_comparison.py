"""HARファイルと実際のPOSTバック処理を比較するスクリプト"""

import sys
import io
import json
from pathlib import Path
from urllib.parse import unquote

# WindowsのコンソールでUTF-8を正しく表示するための設定
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from bs4 import BeautifulSoup
from src.core.scraper import Scraper
from src.models.config_model import SearchConditions
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger


def parse_har_post_data(post_data_text: str) -> dict:
    """HARファイルのPOSTデータをパース"""
    params = {}
    for pair in post_data_text.split('&'):
        if '=' in pair:
            key, value = pair.split('=', 1)
            key = unquote(key)
            value = unquote(value)
            params[key] = value
    return params


def compare_postback_parameters():
    """HARファイルと実際のPOSTバック処理のパラメータを比較"""
    print("="*80)
    print("HARファイルと実際のPOSTバック処理の比較")
    print("="*80)
    
    # HARファイルを読み込む
    har_file = Path("trace_out/network.har")
    if not har_file.exists():
        print(f"エラー: HARファイルが見つかりません: {har_file}")
        return
    
    with open(har_file, "r", encoding="utf-8") as f:
        har_data = json.load(f)
    
    # 中分類のPOSTバックを探す
    print("\n--- 中分類のPOSTバック (drpLargeKikanInf2) ---")
    chubunrui_postback = None
    for entry in har_data.get("log", {}).get("entries", []):
        request = entry.get("request", {})
        post_data = request.get("postData", {})
        if post_data and "__EVENTTARGET=drpLargeKikanInf2" in post_data.get("text", ""):
            chubunrui_postback = post_data.get("text", "")
            print("HARファイルから中分類のPOSTバックを発見")
            break
    
    if chubunrui_postback:
        har_params = parse_har_post_data(chubunrui_postback)
        print("\nHARファイルのパラメータ（主要なもの）:")
        for key in ["__EVENTTARGET", "__EVENTARGUMENT", "drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", "drpSmallKikanInf"]:
            if key in har_params:
                print(f"  {key}: '{har_params[key]}'")
        
        # その他の重要なパラメータ
        important_keys = [k for k in har_params.keys() if k.startswith("txt") or k.startswith("__")]
        print(f"\nその他の重要なパラメータ数: {len(important_keys)}")
        for key in sorted(important_keys)[:10]:
            value = har_params[key][:100] if len(har_params[key]) > 100 else har_params[key]
            print(f"  {key}: '{value}'")
    
    # 小分類のPOSTバックを探す
    print("\n--- 小分類のPOSTバック (drpMiddleKikanInf) ---")
    shoubunrui_postback = None
    for entry in har_data.get("log", {}).get("entries", []):
        request = entry.get("request", {})
        post_data = request.get("postData", {})
        if post_data and "__EVENTTARGET=drpMiddleKikanInf" in post_data.get("text", ""):
            shoubunrui_postback = post_data.get("text", "")
            print("HARファイルから小分類のPOSTバックを発見")
            break
    
    if shoubunrui_postback:
        har_params = parse_har_post_data(shoubunrui_postback)
        print("\nHARファイルのパラメータ（主要なもの）:")
        for key in ["__EVENTTARGET", "__EVENTARGUMENT", "drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", "drpSmallKikanInf"]:
            if key in har_params:
                print(f"  {key}: '{har_params[key]}'")
        
        # 小分類の値が設定されているか確認
        if "drpMiddleKikanInf" in har_params:
            print(f"\n重要: 小分類の値が設定されています: '{har_params['drpMiddleKikanInf']}'")
            print("これは、中分類のPOSTバック後に小分類の選択肢が読み込まれ、")
            print("その中から「東北地方整備局」を選択したことを示しています。")
    
    # 実際のPOSTバック処理を実行して比較
    print("\n" + "="*80)
    print("実際のPOSTバック処理を実行")
    print("="*80)
    
    logger = Logger()
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    normalized_url = scraper._normalize_search_url(search_url)
    
    # 初期ページを取得
    print("\n1. 初期ページを取得...")
    soup = scraper.fetch_page(normalized_url)
    if not soup:
        print("エラー: 初期ページの取得に失敗")
        return
    
    # 大分類を選択してPOSTバック
    print("\n2. 大分類を選択してPOSTバック...")
    form_data = scraper._get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpTopKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    
    response = scraper.http_client.post(normalized_url, data=form_data)
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
    
    print("大分類のPOSTバック完了")
    
    # 中分類を選択してPOSTバック
    print("\n3. 中分類を選択してPOSTバック...")
    form_data = scraper._get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"
    
    print("\n実際のPOSTバックパラメータ（主要なもの）:")
    for key in ["__EVENTTARGET", "__EVENTARGUMENT", "drpTopKikanInf", "drpLargeKikanInf2"]:
        if key in form_data:
            print(f"  {key}: '{form_data[key]}'")
    
    response = scraper.http_client.post(normalized_url, data=form_data)
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
    
    print("中分類のPOSTバック完了")
    
    # 小分類の選択肢を確認
    print("\n4. 小分類の選択肢を確認...")
    select = soup.find("select", id="drpMiddleKikanInf")
    if select:
        options = select.find_all("option")
        print(f"小分類の選択肢数: {len(options)}")
        print("\n小分類の選択肢（最初の20個）:")
        for i, opt in enumerate(options[:20]):
            value = opt.get("value", "")
            text = opt.get_text(strip=True)
            print(f"  {i+1}. '{text}' -> '{value}'")
            if "東北" in text:
                print(f"      ★「東北地方整備局」を発見: 値='{value}'")
        
        if len(options) > 20:
            print(f"  ... (他 {len(options) - 20}個)")
    
    # 小分類の値を取得
    print("\n5. 小分類の値を取得...")
    shoubunrui_value = scraper._get_dropdown_value_from_text(soup, "drpMiddleKikanInf", "東北地方整備局")
    if shoubunrui_value:
        print(f"小分類の値: '{shoubunrui_value}'")
        
        # 小分類を選択してPOSTバック
        print("\n6. 小分類を選択してPOSTバック...")
        form_data = scraper._get_all_hidden_inputs(soup)
        form_data["__EVENTTARGET"] = "drpMiddleKikanInf"
        form_data["__EVENTARGUMENT"] = ""
        form_data["drpTopKikanInf"] = "0"
        form_data["drpLargeKikanInf2"] = "21"
        form_data["drpMiddleKikanInf"] = shoubunrui_value
        
        print("\n実際のPOSTバックパラメータ（主要なもの）:")
        for key in ["__EVENTTARGET", "__EVENTARGUMENT", "drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf"]:
            if key in form_data:
                print(f"  {key}: '{form_data[key]}'")
        
        # HARファイルと比較
        if shoubunrui_postback:
            har_params = parse_har_post_data(shoubunrui_postback)
            print("\n--- HARファイルとの比較 ---")
            print("HARファイル:")
            print(f"  drpMiddleKikanInf: '{har_params.get('drpMiddleKikanInf', 'なし')}'")
            print("実際の実装:")
            print(f"  drpMiddleKikanInf: '{form_data.get('drpMiddleKikanInf', 'なし')}'")
            
            if har_params.get('drpMiddleKikanInf') == form_data.get('drpMiddleKikanInf'):
                print("  ✅ 値が一致しています")
            else:
                print("  ⚠️ 値が一致しません")
        
        response = scraper.http_client.post(normalized_url, data=form_data)
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
        
        print("小分類のPOSTバック完了")
        
        # 検索を実行
        print("\n7. 検索を実行...")
        search_conditions = SearchConditions(
            hachu_daibunrui="国の機関",
            hachu_chubunrui="国土交通省",
            hachu_shoubunrui="東北地方整備局",
        )
        
        form_data = scraper._get_all_hidden_inputs(soup)
        search_form_data = scraper._build_search_form_data(search_conditions, soup)
        form_data.update(search_form_data)
        
        # 小分類の値を明示的に設定
        form_data["drpMiddleKikanInf"] = shoubunrui_value
        
        response = scraper.http_client.post(normalized_url, data=form_data)
        if response.encoding:
            response.encoding = response.apparent_encoding or 'utf-8'
        else:
            response.encoding = 'utf-8'
        
        try:
            result_soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
        except (UnicodeDecodeError, LookupError):
            try:
                result_soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
            except UnicodeDecodeError:
                result_soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
        
        # 検索結果を確認
        result_table = result_soup.find("table", id="dgrSearchList")
        if result_table:
            rows = result_table.find_all("tr")
            print(f"検索結果の行数: {len(rows)}")
            
            # 最初の5件を表示
            data_rows = rows[1:6] if len(rows) > 1 else []
            print("\n検索結果（最初の5件）:")
            matched_count = 0
            for i, row in enumerate(data_rows):
                cells = row.find_all("td")
                if len(cells) >= 3:
                    no = cells[0].get_text(strip=True)
                    kikan = cells[1].get_text(strip=True)
                    koji_name = cells[2].get_text(strip=True)
                    is_matched = "東北地方整備局" in kikan
                    if is_matched:
                        matched_count += 1
                    print(f"  {i+1}. No={no}, 発注機関={kikan[:40]}, 工事名={koji_name[:30]}")
                    if not is_matched:
                        print(f"      ⚠️ 警告: 検索条件 '東北地方整備局' と一致しません")
            
            print(f"\n一致した案件数: {matched_count}/{len(data_rows)}")
    else:
        print("エラー: 小分類の値が取得できませんでした")


def main():
    """メイン処理"""
    compare_postback_parameters()
    
    print("\n" + "="*80)
    print("比較完了")
    print("="*80)


if __name__ == "__main__":
    main()
