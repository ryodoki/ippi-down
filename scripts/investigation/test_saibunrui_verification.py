"""細分類の検証を行うスクリプト"""

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
from src.models.config_model import SearchConditions
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger
from datetime import datetime


def test_saibunrui_verification():
    """細分類の検証"""
    print("="*80)
    print("細分類の検証")
    print("="*80)
    
    logger = Logger()
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    # まず、細分類の選択肢を取得するために、小分類まで選択した状態を確認
    print("\n1. 小分類まで選択した状態で細分類の選択肢を確認...")
    
    search_conditions_test = SearchConditions(
        hachu_daibunrui="国の機関",
        hachu_chubunrui="国土交通省",
        hachu_shoubunrui="東北地方整備局",
        hachu_saibunrui="",
        koji_name="",
        place_todofuken="",
    )
    
    # 検索フォームを送信（小分類まで、検索は実行しない）
    # submit_search_formは検索を実行してしまうので、直接POSTバックを実行
    normalized_url = scraper._normalize_search_url(search_url)
    soup = scraper.fetch_page(normalized_url)
    if not soup:
        print("エラー: 初期ページの取得に失敗")
        return
    
    # 大分類を選択してPOSTバック
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
    
    # 中分類を選択してPOSTバック
    form_data = scraper._get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"
    form_data["drpMiddleKikanInf"] = "-1"
    form_data["drpSmallKikanInf"] = "-1"
    
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        options = dropdown.find_all("option")
        for idx, opt in enumerate(options):
            if opt.get("value", "") == "21":
                form_data["txtLgKikanInf2SelIndex_h"] = str(idx)
                break
    
    form_data["txtLgKikanInfSelValue_h"] = "国土交通省,21"
    form_data["txt_ChangeTopKikan"] = "true"
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
    
    # 小分類を選択してPOSTバック
    form_data = scraper._get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpMiddleKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"
    form_data["drpMiddleKikanInf"] = "02"
    form_data["drpSmallKikanInf"] = "-1"
    
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        options = dropdown.find_all("option")
        for idx, opt in enumerate(options):
            if opt.get("value", "") == "21":
                form_data["txtLgKikanInf2SelIndex_h"] = str(idx)
                break
    
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
    
    # 細分類のselect要素を確認
    dropdown_saibunrui = soup.find("select", id="drpSmallKikanInf")
    if dropdown_saibunrui:
        options = dropdown_saibunrui.find_all("option")
        print(f"細分類の選択肢数: {len(options)}")
        print("\n細分類の選択肢（最初の20個）:")
        for i, opt in enumerate(options[:20]):
            value = opt.get("value", "")
            text = opt.get_text(strip=True)
            print(f"  {i+1}. value='{value}', text='{text}'")
        if len(options) > 20:
            print(f"  ... (他 {len(options) - 20}個)")
    else:
        print("細分類のselect要素が見つかりません")
    
    # 細分類を含む検索条件でテスト
    print("\n2. 細分類を含む検索条件でテスト...")
    
    # 細分類の選択肢から1つを選択（例: 最初の有効な選択肢）
    if dropdown_saibunrui:
        options = dropdown_saibunrui.find_all("option")
        saibunrui_text = None
        for opt in options:
            value = opt.get("value", "")
            text = opt.get_text(strip=True)
            if value != "-1" and text:
                saibunrui_text = text
                print(f"選択する細分類: '{saibunrui_text}'")
                break
        
        if saibunrui_text:
            search_conditions = SearchConditions(
                hachu_daibunrui="国の機関",
                hachu_chubunrui="国土交通省",
                hachu_shoubunrui="東北地方整備局",
                hachu_saibunrui=saibunrui_text,
                koji_name="",
                place_todofuken="",
            )
            
            print(f"\n検索条件:")
            print(f"  大分類: {search_conditions.hachu_daibunrui}")
            print(f"  中分類: {search_conditions.hachu_chubunrui}")
            print(f"  小分類: {search_conditions.hachu_shoubunrui}")
            print(f"  細分類: {search_conditions.hachu_saibunrui}")
            
            # 検索フォームを送信
            print("\n検索フォームを送信中...")
            result_soup = scraper.submit_search_form(search_url, search_conditions)
            
            if not result_soup:
                print("エラー: 検索結果ページの取得に失敗")
                return
            
            print("検索結果ページを取得しました")
            
            # 検索結果テーブルを確認
            result_table = result_soup.find("table", id="dgrSearchList")
            if result_table:
                rows = result_table.find_all("tr")
                print(f"\n検索結果の行数: {len(rows)}")
                
                # 最初の10件を表示
                data_rows = rows[1:11] if len(rows) > 1 else []
                print("\n検索結果（最初の10件）:")
                matched_count = 0
                unmatched_count = 0
                
                for i, row in enumerate(data_rows):
                    cells = row.find_all("td")
                    if len(cells) >= 3:
                        no = cells[0].get_text(strip=True)
                        kikan = cells[1].get_text(strip=True)
                        koji_name = cells[2].get_text(strip=True)
                        
                        # 検索条件と照合
                        is_matched = True
                        reasons = []
                        
                        if search_conditions.hachu_shoubunrui:
                            if search_conditions.hachu_shoubunrui not in kikan:
                                is_matched = False
                                reasons.append(f"小分類 '{search_conditions.hachu_shoubunrui}' が含まれない")
                        
                        if search_conditions.hachu_saibunrui:
                            if search_conditions.hachu_saibunrui not in kikan:
                                is_matched = False
                                reasons.append(f"細分類 '{search_conditions.hachu_saibunrui}' が含まれない")
                        
                        if is_matched:
                            matched_count += 1
                            marker = "✅"
                        else:
                            unmatched_count += 1
                            marker = "❌"
                        
                        print(f"  {marker} {i+1}. No={no}, 発注機関={kikan[:50]}, 工事名={koji_name[:40]}")
                        if not is_matched:
                            print(f"     理由: {', '.join(reasons)}")
                
                print(f"\n照合結果:")
                print(f"  一致: {matched_count}件")
                print(f"  不一致: {unmatched_count}件")
                print(f"  合計: {len(data_rows)}件")
                
                if matched_count == len(data_rows) and matched_count > 0:
                    print("  ✅ すべての案件が検索条件に一致しています！")
                elif matched_count > 0:
                    print(f"  ⚠️ {unmatched_count}件が検索条件と一致しません")
                else:
                    print("  ❌ 検索条件に一致する案件がありません")
            else:
                print("検索結果テーブルが見つかりません")
        else:
            print("有効な細分類の選択肢が見つかりません")
    else:
        print("細分類のselect要素が見つからないため、細分類を含むテストをスキップします")
    
    # HTMLを保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_file = f"search_results_saibunrui_{timestamp}.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(result_soup.prettify())
    print(f"\n検索結果のHTMLを保存しました: {html_file}")
    
    print("\n" + "="*80)
    print("検証完了")
    print("="*80)


if __name__ == "__main__":
    test_saibunrui_verification()
