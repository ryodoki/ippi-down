"""階層的ドロップダウンのPOSTバック処理をテストするスクリプト"""

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
import json
from datetime import datetime


def test_postback_for_dropdown(scraper: Scraper, soup: BeautifulSoup, select_id: str, target_text: str, base_url: str):
    """ドロップダウンのPOSTバックをテスト"""
    print(f"\n--- {select_id} のPOSTバックテスト ---")
    print(f"目標テキスト: '{target_text}'")
    
    # 現在の選択肢を確認
    select = soup.find("select", id=select_id)
    if not select:
        print(f"  エラー: {select_id} が見つかりません")
        return None, soup
    
    options_before = select.find_all("option")
    print(f"  POSTバック前の選択肢数: {len(options_before)}")
    if len(options_before) <= 10:
        for opt in options_before:
            print(f"    '{opt.get_text(strip=True)}' -> '{opt.get('value', '')}'")
    
    # 値を取得してみる
    value = scraper._get_dropdown_value_from_text(soup, select_id, target_text)
    if value:
        print(f"  POSTバック前の値取得: '{value}' (成功)")
        return value, soup
    
    print(f"  POSTバック前の値取得: 失敗 (値が取得できませんでした)")
    
    # POSTバックを実行
    print(f"  POSTバックを実行中...")
    
    # すべてのhidden inputを取得
    form_data = scraper._get_all_hidden_inputs(soup)
    
    # 親のドロップダウンの値を設定（階層的な場合）
    # 大分類が選択されている場合は、その値を含める
    if select_id == "drpLargeKikanInf2":
        # 中分類のPOSTバック時は、大分類の値を設定
        daibunrui_select = soup.find("select", id="drpTopKikanInf")
        if daibunrui_select:
            selected_option = daibunrui_select.find("option", selected=True)
            if not selected_option:
                # 選択されていない場合は、最初の非デフォルトオプションを探す
                for opt in daibunrui_select.find_all("option"):
                    if opt.get("value") and opt.get("value") != "-1":
                        selected_option = opt
                        break
            if selected_option and selected_option.get("value"):
                form_data["drpTopKikanInf"] = selected_option.get("value")
                print(f"    大分類の値を設定: {form_data['drpTopKikanInf']}")
    
    elif select_id == "drpMiddleKikanInf":
        # 小分類のPOSTバック時は、大分類と中分類の値を設定
        # 注意: この関数内では、すでにPOSTバック後のsoupが渡されているため、
        # 親の値は別途設定する必要がある
        pass  # この関数では設定しない（呼び出し側で設定）
    
    # POSTバックのイベントを設定
    form_data["__EVENTTARGET"] = select_id
    form_data["__EVENTARGUMENT"] = ""
    
    # POSTリクエストを送信
    response = scraper.http_client.post(base_url, data=form_data)
    
    # エンコーディング処理
    if response.encoding:
        response.encoding = response.apparent_encoding or 'utf-8'
    else:
        response.encoding = 'utf-8'
    
    try:
        new_soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
    except (UnicodeDecodeError, LookupError):
        try:
            new_soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
        except UnicodeDecodeError:
            new_soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
    
    # POSTバック後の選択肢を確認
    new_select = new_soup.find("select", id=select_id)
    if new_select:
        options_after = new_select.find_all("option")
        print(f"  POSTバック後の選択肢数: {len(options_after)}")
        if len(options_after) <= 20:
            for opt in options_after:
                print(f"    '{opt.get_text(strip=True)}' -> '{opt.get('value', '')}'")
        else:
            for opt in options_after[:10]:
                print(f"    '{opt.get_text(strip=True)}' -> '{opt.get('value', '')}'")
            print(f"    ... (他 {len(options_after) - 10}個)")
    
    # POSTバック後に値を取得
    value = scraper._get_dropdown_value_from_text(new_soup, select_id, target_text)
    if value:
        print(f"  POSTバック後の値取得: '{value}' (成功)")
        return value, new_soup
    else:
        print(f"  POSTバック後の値取得: 失敗")
        return None, new_soup


def test_hierarchical_dropdown_flow(scraper: Scraper, search_url: str, search_conditions: SearchConditions):
    """階層的ドロップダウンのフローをテスト"""
    print("="*80)
    print("階層的ドロップダウンのPOSTバック処理テスト")
    print("="*80)
    
    normalized_url = scraper._normalize_search_url(search_url)
    
    # 初期ページを取得
    print("\n1. 初期ページを取得中...")
    soup = scraper.fetch_page(normalized_url)
    if not soup:
        print("エラー: 初期ページの取得に失敗しました")
        return None
    
    print("初期ページを取得しました")
    
    # 大分類を選択
    daibunrui_value = None
    if search_conditions.hachu_daibunrui:
        print(f"\n2. 大分類を選択: '{search_conditions.hachu_daibunrui}'")
        # 大分類の値を取得（POSTバックは不要）
        daibunrui_value = scraper._get_dropdown_value_from_text(soup, "drpTopKikanInf", search_conditions.hachu_daibunrui)
        if daibunrui_value:
            print(f"  大分類の値: '{daibunrui_value}'")
            # 大分類を選択してPOSTバックを実行
            form_data = scraper._get_all_hidden_inputs(soup)
            form_data["__EVENTTARGET"] = "drpTopKikanInf"
            form_data["__EVENTARGUMENT"] = ""
            form_data["drpTopKikanInf"] = daibunrui_value
            
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
            print("  大分類のPOSTバック完了")
        else:
            print("  警告: 大分類の値が取得できませんでした")
    
    # 中分類を選択
    chubunrui_value = None
    if search_conditions.hachu_chubunrui and daibunrui_value:
        print(f"\n3. 中分類を選択: '{search_conditions.hachu_chubunrui}'")
        # 中分類の値を取得
        chubunrui_value = scraper._get_dropdown_value_from_text(soup, "drpLargeKikanInf2", search_conditions.hachu_chubunrui)
        if chubunrui_value:
            print(f"  中分類の値: '{chubunrui_value}'")
            # 中分類を選択してPOSTバックを実行
            form_data = scraper._get_all_hidden_inputs(soup)
            form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
            form_data["__EVENTARGUMENT"] = ""
            form_data["drpTopKikanInf"] = daibunrui_value
            form_data["drpLargeKikanInf2"] = chubunrui_value
            
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
            print("  中分類のPOSTバック完了")
        else:
            print("  警告: 中分類の値が取得できませんでした")
    
    # 小分類を選択
    shoubunrui_value = None
    if search_conditions.hachu_shoubunrui and chubunrui_value:
        print(f"\n4. 小分類を選択: '{search_conditions.hachu_shoubunrui}'")
        # 小分類の値を取得
        shoubunrui_value = scraper._get_dropdown_value_from_text(soup, "drpMiddleKikanInf", search_conditions.hachu_shoubunrui)
        if shoubunrui_value:
            print(f"  小分類の値: '{shoubunrui_value}'")
        else:
            # 値が取得できない場合は、POSTバックを実行
            print("  小分類の値が取得できないため、POSTバックを実行...")
            form_data = scraper._get_all_hidden_inputs(soup)
            form_data["__EVENTTARGET"] = "drpMiddleKikanInf"
            form_data["__EVENTARGUMENT"] = ""
            form_data["drpTopKikanInf"] = daibunrui_value
            form_data["drpLargeKikanInf2"] = chubunrui_value
            
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
            
            # POSTバック後の選択肢を確認
            select = soup.find("select", id="drpMiddleKikanInf")
            if select:
                options = select.find_all("option")
                print(f"  POSTバック後の小分類の選択肢数: {len(options)}")
                if len(options) <= 20:
                    for opt in options:
                        print(f"    '{opt.get_text(strip=True)}' -> '{opt.get('value', '')}'")
                else:
                    for opt in options[:10]:
                        print(f"    '{opt.get_text(strip=True)}' -> '{opt.get('value', '')}'")
                    print(f"    ... (他 {len(options) - 10}個)")
            
            # POSTバック後に再度値を取得
            shoubunrui_value = scraper._get_dropdown_value_from_text(soup, "drpMiddleKikanInf", search_conditions.hachu_shoubunrui)
            if shoubunrui_value:
                print(f"  POSTバック後の小分類の値: '{shoubunrui_value}'")
            else:
                print("  警告: 小分類の値が取得できませんでした")
                # 選択肢の中に「東北」を含むものを探す
                if select:
                    for opt in select.find_all("option"):
                        text = opt.get_text(strip=True)
                        if "東北" in text:
                            print(f"  '東北'を含む選択肢を発見: '{text}' -> '{opt.get('value', '')}'")
    
    # 細分類を選択
    saibunrui_value = None
    if search_conditions.hachu_saibunrui and shoubunrui_value:
        print(f"\n5. 細分類を選択: '{search_conditions.hachu_saibunrui}'")
        saibunrui_value, soup = test_postback_for_dropdown(
            scraper, soup, "drpSmallKikanInf", search_conditions.hachu_saibunrui, normalized_url
        )
        if not saibunrui_value:
            print("  警告: 細分類の値が取得できませんでした")
    
    # 結果をまとめる
    print("\n" + "="*80)
    print("テスト結果")
    print("="*80)
    print(f"大分類 '{search_conditions.hachu_daibunrui}': {daibunrui_value if daibunrui_value else '失敗'}")
    print(f"中分類 '{search_conditions.hachu_chubunrui}': {chubunrui_value if chubunrui_value else '失敗'}")
    print(f"小分類 '{search_conditions.hachu_shoubunrui}': {shoubunrui_value if shoubunrui_value else '失敗'}")
    print(f"細分類 '{search_conditions.hachu_saibunrui}': {saibunrui_value if saibunrui_value else '失敗'}")
    
    # 検索フォームのデータを構築
    print("\n--- 検索フォームのデータ ---")
    form_data = scraper._get_all_hidden_inputs(soup)
    search_form_data = scraper._build_search_form_data(search_conditions, soup)
    form_data.update(search_form_data)
    
    print("発注機関関連のフィールド:")
    for key in ["drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", "drpSmallKikanInf"]:
        if key in form_data:
            print(f"  {key}: '{form_data[key]}'")
        else:
            print(f"  {key}: (設定されていません)")
    
    # 検索を実行して結果を確認
    print("\n--- 検索を実行 ---")
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
    
    # 検索結果テーブルを確認
    result_table = result_soup.find("table", id="dgrSearchList")
    if result_table:
        rows = result_table.find_all("tr")
        print(f"検索結果の行数: {len(rows)}")
        
        # 最初の5件を表示
        data_rows = rows[1:6] if len(rows) > 1 else []
        print("\n検索結果（最初の5件）:")
        for i, row in enumerate(data_rows):
            cells = row.find_all("td")
            if len(cells) >= 3:
                no = cells[0].get_text(strip=True)
                kikan = cells[1].get_text(strip=True)
                koji_name = cells[2].get_text(strip=True)
                print(f"  {i+1}. No={no}, 発注機関={kikan[:30]}, 工事名={koji_name[:30]}")
                
                # 検索条件と照合
                if search_conditions.hachu_shoubunrui:
                    if search_conditions.hachu_shoubunrui not in kikan:
                        print(f"      ⚠️ 警告: 検索条件 '{search_conditions.hachu_shoubunrui}' と一致しません")
    
    # HTMLを保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_file = f"search_results_after_postback_{timestamp}.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(result_soup.prettify())
    print(f"\n検索結果のHTMLを保存しました: {html_file}")
    
    return result_soup


def main():
    """メイン処理"""
    # ロガーを初期化
    logger = Logger()
    
    # HTTPクライアントを初期化
    http_client = HTTPClient(logger)
    
    # Scraperを初期化
    scraper = Scraper(http_client, logger)
    
    # 検索条件を設定
    search_conditions = SearchConditions(
        hachu_daibunrui="国の機関",
        hachu_chubunrui="国土交通省",
        hachu_shoubunrui="東北地方整備局",
        hachu_saibunrui="",
        koji_name="",
        place_todofuken="",
    )
    
    # 検索URL
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print(f"検索条件:")
    print(f"  大分類: {search_conditions.hachu_daibunrui}")
    print(f"  中分類: {search_conditions.hachu_chubunrui}")
    print(f"  小分類: {search_conditions.hachu_shoubunrui}")
    print(f"  細分類: {search_conditions.hachu_saibunrui}")
    print(f"\n検索URL: {search_url}")
    
    # 階層的ドロップダウンのフローをテスト
    result_soup = test_hierarchical_dropdown_flow(scraper, search_url, search_conditions)
    
    print("\n" + "="*80)
    print("テスト完了")
    print("="*80)


if __name__ == "__main__":
    main()
