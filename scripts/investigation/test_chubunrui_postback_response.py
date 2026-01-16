"""中分類のPOSTバック後のレスポンスを詳細に確認するスクリプト"""

import sys
import io
import re
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


def analyze_response_html(soup: BeautifulSoup, output_file: str):
    """レスポンスのHTMLを解析"""
    print("\n" + "="*80)
    print("レスポンスHTMLの解析")
    print("="*80)
    
    # HTMLをファイルに保存
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(soup.prettify())
    print(f"HTMLを保存しました: {output_file}")
    
    # 小分類のselect要素を確認
    print("\n--- 小分類のselect要素 (drpMiddleKikanInf) ---")
    select = soup.find("select", id="drpMiddleKikanInf")
    if select:
        options = select.find_all("option")
        print(f"選択肢数: {len(options)}")
        print("\n選択肢の詳細:")
        for i, opt in enumerate(options):
            value = opt.get("value", "")
            text = opt.get_text(strip=True)
            selected = opt.get("selected")
            print(f"  {i+1}. value='{value}', text='{text}', selected={selected}")
            if "東北" in text:
                print(f"      ★「東北地方整備局」を発見！")
    else:
        print("  select要素が見つかりません")
    
    # 中分類のselect要素を確認
    print("\n--- 中分類のselect要素 (drpLargeKikanInf2) ---")
    select = soup.find("select", id="drpLargeKikanInf2")
    if select:
        options = select.find_all("option")
        print(f"選択肢数: {len(options)}")
        selected_option = select.find("option", selected=True)
        if selected_option:
            print(f"選択されている値: '{selected_option.get('value')}', テキスト: '{selected_option.get_text(strip=True)}'")
    
    # hiddenフィールドを確認
    print("\n--- hiddenフィールドの確認 ---")
    important_fields = [
        "__VIEWSTATE",
        "__EVENTVALIDATION",
        "__VIEWSTATEGENERATOR",
        "txtLargeKikanInf_h",
        "txtLgKikanInf2SelIndex_h",
        "txt_ChangeTopKikan",
        "txt_ChangeLargeKikan",
    ]
    
    for field in important_fields:
        input_elem = soup.find("input", type="hidden", attrs={"name": field})
        if input_elem:
            value = input_elem.get("value", "")
            display_value = value[:100] + "..." if len(value) > 100 else value
            print(f"  {field}: '{display_value}'")
        else:
            print(f"  {field}: (見つかりません)")


def analyze_response_javascript(response_text: str):
    """レスポンスのJavaScriptコードを解析"""
    print("\n" + "="*80)
    print("レスポンスJavaScriptの解析")
    print("="*80)
    
    # setListItemSubの呼び出しを探す
    print("\n--- setListItemSub()の呼び出し ---")
    pattern = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*\[(.*?)\]\s*\)"
    matches = re.findall(pattern, response_text, re.DOTALL)
    
    if matches:
        print(f"setListItemSub()の呼び出し数: {len(matches)}")
        for i, (dropdown_id, list_content) in enumerate(matches):
            print(f"\n呼び出し {i+1}:")
            print(f"  ドロップダウンID: '{dropdown_id}'")
            
            # リストアイテムを抽出
            items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
            print(f"  アイテム数: {len(items)}")
            
            if "drpMiddleKikanInf" in dropdown_id or "MiddleKikanInf" in dropdown_id:
                print(f"  ★ 小分類のドロップダウンを発見！")
                print(f"  アイテム:")
                for j, item in enumerate(items[:20]):
                    if ":" in item:
                        value, text = item.split(":", 1)
                        print(f"    {j+1}. value='{value}', text='{text}'")
                        if "東北" in text:
                            print(f"        ★「東北地方整備局」を発見！")
                    else:
                        print(f"    {j+1}. '{item}'")
                
                if len(items) > 20:
                    print(f"    ... (他 {len(items) - 20}個)")
    else:
        print("setListItemSub()の呼び出しが見つかりません")
    
    # その他のJavaScript関数呼び出しを探す
    print("\n--- その他のJavaScript関数呼び出し（小分類関連） ---")
    patterns = [
        r"setListItem\s*\(\s*['\"]([^'\"]*MiddleKikanInf[^'\"]*)['\"]",
        r"addOption\s*\(\s*['\"]([^'\"]*MiddleKikanInf[^'\"]*)['\"]",
        r"drpMiddleKikanInf.*options",
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, response_text, re.IGNORECASE)
        if matches:
            print(f"パターン '{pattern}' に一致: {len(matches)}件")
            for match in matches[:5]:
                print(f"  '{match[:100]}'")
    
    # 小分類の選択肢が含まれる可能性のある変数を探す
    print("\n--- 小分類の選択肢が含まれる可能性のある変数 ---")
    var_patterns = [
        r"var\s+(\w*MiddleKikanInf\w*)\s*=\s*\[(.*?)\];",
        r"(\w*MiddleKikanInf\w*)\s*=\s*\[(.*?)\];",
    ]
    
    for pattern in var_patterns:
        matches = re.findall(pattern, response_text, re.DOTALL | re.IGNORECASE)
        if matches:
            print(f"パターン '{pattern}' に一致: {len(matches)}件")
            for var_name, var_content in matches[:3]:
                print(f"  変数名: '{var_name}'")
                items = re.findall(r"['\"]([^'\"]+)['\"]", var_content)
                print(f"  アイテム数: {len(items)}")
                if items:
                    print(f"  最初の5個: {items[:5]}")


def analyze_response_text(response_text: str):
    """レスポンスのテキスト全体を解析"""
    print("\n" + "="*80)
    print("レスポンステキストの解析")
    print("="*80)
    
    # 「東北」を含む行を探す
    print("\n--- 「東北」を含む行 ---")
    lines = response_text.split("\n")
    tohoku_lines = [line for line in lines if "東北" in line]
    
    if tohoku_lines:
        print(f"「東北」を含む行数: {len(tohoku_lines)}")
        for i, line in enumerate(tohoku_lines[:10]):
            # 前後のコンテキストを含めて表示
            line_num = lines.index(line)
            context_start = max(0, line_num - 2)
            context_end = min(len(lines), line_num + 3)
            print(f"\n行 {line_num} (前後2行):")
            for j in range(context_start, context_end):
                marker = ">>> " if j == line_num else "    "
                print(f"{marker}{j+1}: {lines[j][:200]}")
    else:
        print("「東北」を含む行が見つかりません")
    
    # 小分類の値（'02'など）を含む行を探す
    print("\n--- 小分類の値（'02'など）を含む行 ---")
    value_lines = [line for line in lines if re.search(r"['\"]0[0-9]['\"]", line) and ("MiddleKikanInf" in line or "小分類" in line)]
    
    if value_lines:
        print(f"小分類の値を含む行数: {len(value_lines)}")
        for i, line in enumerate(value_lines[:10]):
            line_num = lines.index(line)
            print(f"\n行 {line_num}:")
            print(f"  {line[:300]}")


def test_chubunrui_postback_response():
    """中分類のPOSTバック後のレスポンスをテスト"""
    print("="*80)
    print("中分類のPOSTバック後のレスポンス確認スクリプト")
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
    
    # txt_ChangeLargeKikanを設定
    if "txt_ChangeLargeKikan" in form_data:
        form_data["txt_ChangeLargeKikan"] = "true"
    
    print("\n送信するパラメータ（主要なもの）:")
    for key in ["__EVENTTARGET", "__EVENTARGUMENT", "drpTopKikanInf", "drpLargeKikanInf2", "txt_ChangeLargeKikan"]:
        if key in form_data:
            print(f"  {key}: '{form_data[key]}'")
    
    response = scraper.http_client.post(normalized_url, data=form_data)
    
    # レスポンスのエンコーディング処理
    if response.encoding:
        response.encoding = response.apparent_encoding or 'utf-8'
    else:
        response.encoding = 'utf-8'
    
    # レスポンステキストを取得
    try:
        response_text = response.content.decode(response.encoding, errors='ignore')
    except:
        response_text = response.text
    
    # HTMLをパース
    try:
        soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
    except (UnicodeDecodeError, LookupError):
        try:
            soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
        except UnicodeDecodeError:
            soup = BeautifulSoup(response_text, "lxml")
    
    print("中分類のPOSTバック完了")
    
    # レスポンスを詳細に解析
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # HTMLを解析
    html_file = f"chubunrui_postback_response_{timestamp}.html"
    analyze_response_html(soup, html_file)
    
    # JavaScriptを解析
    analyze_response_javascript(response_text)
    
    # テキスト全体を解析
    analyze_response_text(response_text)
    
    # レスポンステキスト全体をファイルに保存
    text_file = f"chubunrui_postback_response_{timestamp}.txt"
    with open(text_file, "w", encoding="utf-8") as f:
        f.write(response_text)
    print(f"\nレスポンステキスト全体を保存しました: {text_file}")
    
    print("\n" + "="*80)
    print("解析完了")
    print("="*80)


def main():
    """メイン処理"""
    test_chubunrui_postback_response()


if __name__ == "__main__":
    main()
