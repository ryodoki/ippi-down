"""txtLargeKikanInf_hの解析を詳細に確認するスクリプト"""

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


def test_parse_txtLargeKikanInf_h_detailed():
    """txtLargeKikanInf_hの解析を詳細に確認"""
    print("="*80)
    print("txtLargeKikanInf_hの解析詳細確認")
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
    
    # txtLgKikanInf2SelIndex_hを設定
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        options = dropdown.find_all("option")
        for idx, opt in enumerate(options):
            if opt.get("value", "") == "21":
                form_data["txtLgKikanInf2SelIndex_h"] = str(idx)
                break
    
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
    
    # txtLargeKikanInf_hを取得
    form_data = scraper._get_all_hidden_inputs(soup)
    if "txtLargeKikanInf_h" not in form_data:
        print("エラー: txtLargeKikanInf_hが見つかりません")
        return
    
    txtLargeKikanInf_h = form_data["txtLargeKikanInf_h"]
    print(f"\n4. txtLargeKikanInf_hの内容:")
    print(f"  長さ: {len(txtLargeKikanInf_h)}文字")
    print(f"  内容: {txtLargeKikanInf_h[:500]}...")
    
    # エントリを分割して表示
    print("\n5. エントリの詳細:")
    entries = txtLargeKikanInf_h.split(":")
    print(f"  エントリ数: {len(entries)}")
    
    for i, entry in enumerate(entries):
        parts = entry.split(",")
        if len(parts) >= 3:
            daibunrui_value = parts[0]
            chubunrui_name = parts[1]
            chubunrui_value = parts[2]
            
            print(f"\n  エントリ {i+1}:")
            print(f"    大分類value: '{daibunrui_value}'")
            print(f"    中分類名: '{chubunrui_name}'")
            print(f"    中分類value: '{chubunrui_value}'")
            
            # 小分類のデータがあるか確認
            if len(parts) > 3:
                print(f"    小分類データ:")
                for j in range(3, len(parts) - 1, 2):
                    if j + 1 < len(parts):
                        shoubunrui_name = parts[j]
                        shoubunrui_value = parts[j + 1]
                        print(f"      '{shoubunrui_name}' -> '{shoubunrui_value}'")
                        if "東北" in shoubunrui_name:
                            print(f"        ★「東北地方整備局」を発見！")
    
    # _parse_txtLargeKikanInf_hメソッドを呼び出し
    print("\n6. _parse_txtLargeKikanInf_hメソッドの結果:")
    options = scraper._parse_txtLargeKikanInf_h(txtLargeKikanInf_h, "21")
    print(f"  取得した選択肢数: {len(options)}")
    
    for value, text in options:
        print(f"    '{text}' -> '{value}'")
        if "東北" in text:
            print(f"      ★「東北地方整備局」を発見！")
    
    # 「東北」を含むエントリを探す
    print("\n7. 「東北」を含むエントリ:")
    tohoku_found = False
    for i, entry in enumerate(entries):
        if "東北" in entry:
            tohoku_found = True
            print(f"  エントリ {i+1}: {entry}")
    
    if not tohoku_found:
        print("  「東北」を含むエントリが見つかりません")
    
    print("\n" + "="*80)
    print("解析完了")
    print("="*80)


if __name__ == "__main__":
    test_parse_txtLargeKikanInf_h_detailed()
