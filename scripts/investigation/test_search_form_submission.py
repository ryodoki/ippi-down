"""検索フォームの送信処理を確認するスクリプト"""

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


def analyze_dropdown_options(soup: BeautifulSoup, select_id: str, label: str):
    """ドロップダウンの選択肢を解析"""
    print(f"\n--- {label} ({select_id}) の選択肢 ---")
    
    select = soup.find("select", id=select_id)
    if not select:
        print(f"  エラー: {select_id} が見つかりません")
        return None
    
    options = select.find_all("option")
    print(f"  選択肢数: {len(options)}")
    
    option_map = {}
    for option in options:
        value = option.get("value", "")
        text = option.get_text(strip=True)
        option_map[text] = value
        if len(options) <= 20:  # 20個以下ならすべて表示
            print(f"    '{text}' -> '{value}'")
        elif len(option_map) <= 10:  # 最初の10個だけ表示
            print(f"    '{text}' -> '{value}'")
    
    if len(options) > 10:
        print(f"    ... (他 {len(options) - 10}個)")
    
    return option_map


def verify_search_form_data(scraper: Scraper, search_url: str, search_conditions: SearchConditions):
    """検索フォームの送信データを確認"""
    print("\n" + "="*80)
    print("検索フォームの送信データ確認")
    print("="*80)
    
    # 初期ページを取得
    initial_soup = scraper.fetch_page(search_url)
    if not initial_soup:
        print("エラー: 初期ページの取得に失敗しました")
        return
    
    # ドロップダウンの選択肢を確認
    daibunrui_map = analyze_dropdown_options(initial_soup, "drpTopKikanInf", "大分類")
    chubunrui_map = analyze_dropdown_options(initial_soup, "drpLargeKikanInf2", "中分類")
    shoubunrui_map = analyze_dropdown_options(initial_soup, "drpMiddleKikanInf", "小分類")
    saibunrui_map = analyze_dropdown_options(initial_soup, "drpSmallKikanInf", "細分類")
    
    # 検索条件から値を取得
    print("\n--- 検索条件から値を取得 ---")
    print(f"検索条件:")
    print(f"  大分類: '{search_conditions.hachu_daibunrui}'")
    print(f"  中分類: '{search_conditions.hachu_chubunrui}'")
    print(f"  小分類: '{search_conditions.hachu_shoubunrui}'")
    print(f"  細分類: '{search_conditions.hachu_saibunrui}'")
    
    # 実際に取得される値を確認
    if search_conditions.hachu_daibunrui:
        value = scraper._get_dropdown_value_from_text(initial_soup, "drpTopKikanInf", search_conditions.hachu_daibunrui)
        print(f"\n大分類の値取得:")
        print(f"  検索テキスト: '{search_conditions.hachu_daibunrui}'")
        print(f"  取得された値: '{value}'")
        if value and daibunrui_map:
            # 逆引きして確認
            for text, val in daibunrui_map.items():
                if val == value:
                    print(f"  対応するテキスト: '{text}'")
                    if text != search_conditions.hachu_daibunrui:
                        print(f"  ⚠️ 警告: テキストが一致しません！")
                    break
    
    if search_conditions.hachu_chubunrui:
        value = scraper._get_dropdown_value_from_text(initial_soup, "drpLargeKikanInf2", search_conditions.hachu_chubunrui)
        print(f"\n中分類の値取得:")
        print(f"  検索テキスト: '{search_conditions.hachu_chubunrui}'")
        print(f"  取得された値: '{value}'")
        if value and chubunrui_map:
            for text, val in chubunrui_map.items():
                if val == value:
                    print(f"  対応するテキスト: '{text}'")
                    if text != search_conditions.hachu_chubunrui:
                        print(f"  ⚠️ 警告: テキストが一致しません！")
                    break
    
    if search_conditions.hachu_shoubunrui:
        value = scraper._get_dropdown_value_from_text(initial_soup, "drpMiddleKikanInf", search_conditions.hachu_shoubunrui)
        print(f"\n小分類の値取得:")
        print(f"  検索テキスト: '{search_conditions.hachu_shoubunrui}'")
        print(f"  取得された値: '{value}'")
        if value and shoubunrui_map:
            for text, val in shoubunrui_map.items():
                if val == value:
                    print(f"  対応するテキスト: '{text}'")
                    if text != search_conditions.hachu_shoubunrui:
                        print(f"  ⚠️ 警告: テキストが一致しません！")
                    break
        elif not value:
            print(f"  ⚠️ エラー: 値が取得できませんでした")
            print(f"  利用可能な選択肢:")
            for text, val in list(shoubunrui_map.items())[:10]:
                print(f"    '{text}'")
    
    # フォームデータを構築
    print("\n--- 送信されるフォームデータ ---")
    form_data = scraper._build_search_form_data(search_conditions, initial_soup)
    
    # 発注機関関連のフィールドを表示
    print("\n発注機関関連のフィールド:")
    for key in ["drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", "drpSmallKikanInf"]:
        if key in form_data:
            print(f"  {key}: '{form_data[key]}'")
        else:
            print(f"  {key}: (設定されていません)")
    
    # フォームデータ全体をJSONファイルに保存
    json_file = "search_form_data.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(form_data, f, ensure_ascii=False, indent=2)
    print(f"\nフォームデータを保存しました: {json_file}")


def main():
    """メイン処理"""
    print("="*80)
    print("検索フォームの送信処理確認スクリプト")
    print("="*80)
    
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
    
    # 検索フォームの送信データを確認
    verify_search_form_data(scraper, search_url, search_conditions)
    
    print("\n" + "="*80)
    print("完了")
    print("="*80)


if __name__ == "__main__":
    main()
