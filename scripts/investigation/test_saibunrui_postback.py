"""小分類のPOSTバック後のレスポンスで細分類の選択肢を確認するスクリプト"""

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
from datetime import datetime


def test_saibunrui_postback():
    """小分類のPOSTバック後のレスポンスで細分類の選択肢を確認"""
    print("="*80)
    print("小分類のPOSTバック後のレスポンスで細分類の選択肢を確認")
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
    form_data["drpMiddleKikanInf"] = "-1"
    form_data["drpSmallKikanInf"] = "-1"
    
    # txtLgKikanInf2SelIndex_hを設定
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        options = dropdown.find_all("option")
        for idx, opt in enumerate(options):
            if opt.get("value", "") == "21":
                form_data["txtLgKikanInf2SelIndex_h"] = str(idx)
                break
    
    # txtLgKikanInfSelValue_hを設定
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
    
    print("中分類のPOSTバック完了")
    
    # 小分類を選択してPOSTバック
    print("\n4. 小分類を選択してPOSTバック...")
    form_data = scraper._get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpMiddleKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"
    form_data["drpMiddleKikanInf"] = "02"
    form_data["drpSmallKikanInf"] = "-1"
    
    # txtLgKikanInf2SelIndex_hを再設定
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
    
    print("小分類のPOSTバック完了")
    
    # 細分類のselect要素を確認
    print("\n5. 細分類のselect要素を確認...")
    dropdown = soup.find("select", id="drpSmallKikanInf")
    if dropdown:
        options = dropdown.find_all("option")
        print(f"細分類の選択肢数: {len(options)}")
        print("\n細分類の選択肢:")
        for i, opt in enumerate(options[:20]):  # 最初の20個を表示
            value = opt.get("value", "")
            text = opt.get_text(strip=True)
            print(f"  {i+1}. value='{value}', text='{text}'")
    else:
        print("細分類のselect要素が見つかりません")
        # すべてのselect要素を確認
        all_selects = soup.find_all("select")
        print(f"\nすべてのselect要素: {len(all_selects)}個")
        for select in all_selects:
            select_id = select.get("id", "")
            select_name = select.get("name", "")
            if "Small" in select_id or "Small" in select_name or "細" in select.get_text():
                print(f"  関連するselect: id='{select_id}', name='{select_name}'")
    
    # HTMLを保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_file = f"saibunrui_postback_response_{timestamp}.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(soup.prettify())
    print(f"\nHTMLを保存しました: {html_file}")
    
    print("\n" + "="*80)
    print("確認完了")
    print("="*80)


if __name__ == "__main__":
    test_saibunrui_postback()
