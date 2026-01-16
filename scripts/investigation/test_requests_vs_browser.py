"""requestsとブラウザのPOSTバックパラメータを比較するスクリプト"""

import sys
import io
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
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger
import json


def parse_post_data(post_data_str):
    """POSTデータ文字列をパース"""
    params = {}
    if post_data_str:
        pairs = post_data_str.split("&")
        for pair in pairs:
            if "=" in pair:
                key, value = pair.split("=", 1)
                key = unquote(key)
                value = unquote(value)
                params[key] = value
    return params


def test_requests_vs_browser():
    """requestsとブラウザのPOSTバックパラメータを比較"""
    print("="*80)
    print("requestsとブラウザのPOSTバックパラメータ比較")
    print("="*80)
    
    logger = Logger()
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    normalized_url = scraper._normalize_search_url(search_url)
    
    # 1. requestsで取得したパラメータ
    print("\n1. requestsで取得したパラメータ:")
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
    form_data_requests = scraper._get_all_hidden_inputs(soup)
    form_data_requests["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data_requests["__EVENTARGUMENT"] = ""
    form_data_requests["drpTopKikanInf"] = "0"
    form_data_requests["drpLargeKikanInf2"] = "21"
    
    # txtLgKikanInf2SelIndex_hを設定
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        options = dropdown.find_all("option")
        for idx, opt in enumerate(options):
            if opt.get("value", "") == "21":
                form_data_requests["txtLgKikanInf2SelIndex_h"] = str(idx)
                break
    
    # txt_ChangeLargeKikanを設定
    if "txt_ChangeLargeKikan" in form_data_requests:
        form_data_requests["txt_ChangeLargeKikan"] = "true"
    
    print(f"   パラメータ数: {len(form_data_requests)}")
    important_keys = [
        "__EVENTTARGET", "__EVENTARGUMENT", "__VIEWSTATE", "__EVENTVALIDATION",
        "drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf",
        "txtLgKikanInf2SelIndex_h", "txtLgKikanInfSelValue_h",
        "txt_ChangeTopKikan", "txt_ChangeLargeKikan",
        "txtLargeKikanInf_h"
    ]
    for key in important_keys:
        if key in form_data_requests:
            value = form_data_requests[key]
            display_value = value[:100] + "..." if len(value) > 100 else value
            print(f"     {key}: '{display_value}'")
    
    # 2. ブラウザで取得したパラメータ
    print("\n2. ブラウザで取得したパラメータ:")
    with open("browser_network_requests.json", "r", encoding="utf-8") as f:
        browser_requests = json.load(f)
    
    browser_post_data = None
    for req in browser_requests:
        if req["method"] == "POST" and "post_data" in req and req["post_data"]:
            browser_post_data = req["post_data"]
            break
    
    if browser_post_data:
        browser_params = parse_post_data(browser_post_data)
        print(f"   パラメータ数: {len(browser_params)}")
        for key in important_keys:
            if key in browser_params:
                value = browser_params[key]
                display_value = value[:100] + "..." if len(value) > 100 else value
                print(f"     {key}: '{display_value}'")
    
    # 3. パラメータの比較
    print("\n3. パラメータの比較:")
    if browser_post_data:
        browser_params = parse_post_data(browser_post_data)
        
        # requestsにないパラメータ
        missing_in_requests = []
        for key in browser_params:
            if key not in form_data_requests:
                missing_in_requests.append(key)
        
        if missing_in_requests:
            print(f"   requestsにないパラメータ: {missing_in_requests}")
        else:
            print("   requestsにないパラメータ: なし")
        
        # 値が異なるパラメータ
        different_values = []
        for key in important_keys:
            if key in browser_params and key in form_data_requests:
                if browser_params[key] != form_data_requests[key]:
                    different_values.append(key)
                    print(f"   値が異なる: {key}")
                    print(f"     ブラウザ: '{browser_params[key][:100]}'")
                    print(f"     requests: '{form_data_requests[key][:100]}'")
        
        if not different_values:
            print("   値が異なるパラメータ: なし")
    
    print("\n" + "="*80)
    print("比較完了")
    print("="*80)


if __name__ == "__main__":
    test_requests_vs_browser()
