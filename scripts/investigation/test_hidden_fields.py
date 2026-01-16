"""hiddenフィールドの取得を確認するスクリプト"""

import sys
import io
from pathlib import Path

# WindowsのコンソールでUTF-8を正しく表示するための設定
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from bs4 import BeautifulSoup
from src.core.scraper import Scraper
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger


def check_hidden_fields(soup: BeautifulSoup, scraper: Scraper):
    """hiddenフィールドを確認"""
    print("\n--- hiddenフィールドの確認 ---")
    
    # すべてのhidden inputを取得
    hidden_inputs = soup.find_all("input", type="hidden")
    print(f"hidden inputの数: {len(hidden_inputs)}")
    
    # 重要なフィールドを確認
    important_fields = [
        "__VIEWSTATE",
        "__EVENTVALIDATION",
        "__VIEWSTATEGENERATOR",
        "txtLargeKikanInf_h",
        "txtLgKikanInf2SelIndex_h",
        "txt_ChangeTopKikan",
        "txt_ChangeLargeKikan",
    ]
    
    print("\n重要なhiddenフィールド:")
    found_fields = {}
    for field in important_fields:
        input_elem = soup.find("input", type="hidden", attrs={"name": field})
        if input_elem:
            value = input_elem.get("value", "")
            # 長い値は最初の100文字だけ表示
            display_value = value[:100] + "..." if len(value) > 100 else value
            print(f"  {field}: '{display_value}'")
            found_fields[field] = value
        else:
            print(f"  {field}: (見つかりません)")
    
    # _get_all_hidden_inputsで取得されるフィールドを確認
    print("\n--- _get_all_hidden_inputsで取得されるフィールド ---")
    form_data = scraper._get_all_hidden_inputs(soup)
    
    print(f"取得されたフィールド数: {len(form_data)}")
    print("\n重要なフィールド:")
    for field in important_fields:
        if field in form_data:
            value = form_data[field]
            display_value = value[:100] + "..." if len(value) > 100 else value
            print(f"  {field}: '{display_value}'")
        else:
            print(f"  {field}: (取得されていません)")
    
    # txtLargeKikanInf_hの内容を解析
    if "txtLargeKikanInf_h" in form_data:
        print("\n--- txtLargeKikanInf_hの内容を解析 ---")
        txt_value = form_data["txtLargeKikanInf_h"]
        print(f"値: '{txt_value[:200]}...'")
        
        # 中分類「国土交通省」(value='21')の小分類を抽出
        options = scraper._parse_txtLargeKikanInf_h(txt_value, "21")
        print(f"\n中分類「国土交通省」の小分類: {len(options)}個")
        for value, text in options[:10]:
            print(f"  '{text}' -> '{value}'")
            if "東北" in text:
                print(f"      ★「東北地方整備局」を発見: 値='{value}'")


def test_hierarchical_postback_with_hidden_fields():
    """hiddenフィールドを含めた階層的POSTバックをテスト"""
    print("="*80)
    print("hiddenフィールドを含めた階層的POSTバックテスト")
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
    
    check_hidden_fields(soup, scraper)
    
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
    check_hidden_fields(soup, scraper)
    
    # 中分類を選択してPOSTバック
    print("\n3. 中分類を選択してPOSTバック...")
    form_data = scraper._get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"
    
    # txt_ChangeLargeKikanを設定
    if "txt_ChangeLargeKikan" in form_data:
        form_data["txt_ChangeLargeKikan"] = "true"
    
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
    check_hidden_fields(soup, scraper)
    
    # 小分類の選択肢を確認
    print("\n4. 小分類の選択肢を確認...")
    select = soup.find("select", id="drpMiddleKikanInf")
    if select:
        options = select.find_all("option")
        print(f"小分類の選択肢数: {len(options)}")
        if len(options) > 1:
            print("\n小分類の選択肢:")
            for i, opt in enumerate(options[:20]):
                value = opt.get("value", "")
                text = opt.get_text(strip=True)
                print(f"  {i+1}. '{text}' -> '{value}'")
                if "東北" in text:
                    print(f"      ★「東北地方整備局」を発見: 値='{value}'")
    
    # txtLargeKikanInf_hから小分類を取得
    print("\n5. txtLargeKikanInf_hから小分類を取得...")
    form_data = scraper._get_all_hidden_inputs(soup)
    if "txtLargeKikanInf_h" in form_data:
        options = scraper._parse_txtLargeKikanInf_h(form_data["txtLargeKikanInf_h"], "21")
        print(f"中分類「国土交通省」の小分類: {len(options)}個")
        for value, text in options:
            print(f"  '{text}' -> '{value}'")
            if "東北" in text:
                print(f"      ★「東北地方整備局」を発見: 値='{value}'")
                
                # この値を使って小分類を選択
                print(f"\n6. 小分類を選択してPOSTバック（値='{value}'）...")
                form_data = scraper._get_all_hidden_inputs(soup)
                form_data["__EVENTTARGET"] = "drpMiddleKikanInf"
                form_data["__EVENTARGUMENT"] = ""
                form_data["drpTopKikanInf"] = "0"
                form_data["drpLargeKikanInf2"] = "21"
                form_data["drpMiddleKikanInf"] = value
                
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
                from src.models.config_model import SearchConditions
                search_conditions = SearchConditions(
                    hachu_daibunrui="国の機関",
                    hachu_chubunrui="国土交通省",
                    hachu_shoubunrui="東北地方整備局",
                )
                
                form_data = scraper._get_all_hidden_inputs(soup)
                search_form_data = scraper._build_search_form_data(search_conditions, soup)
                form_data.update(search_form_data)
                form_data["drpMiddleKikanInf"] = value
                
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
                    if matched_count == len(data_rows) and matched_count > 0:
                        print("  ✅ すべての案件が検索条件に一致しています！")
                    elif matched_count > 0:
                        print(f"  ⚠️ {len(data_rows) - matched_count}件が検索条件と一致しません")
                    else:
                        print("  ❌ 検索条件に一致する案件がありません")
                break


def main():
    """メイン処理"""
    test_hierarchical_postback_with_hidden_fields()
    
    print("\n" + "="*80)
    print("テスト完了")
    print("="*80)


if __name__ == "__main__":
    main()
