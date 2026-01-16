"""方針1の実装をテストするスクリプト"""

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


def test_implementation_fix1():
    """方針1の実装をテスト"""
    print("="*80)
    print("方針1の実装テスト")
    print("="*80)
    
    logger = Logger()
    http_client = HTTPClient(logger)
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
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print(f"\n検索条件:")
    print(f"  大分類: {search_conditions.hachu_daibunrui}")
    print(f"  中分類: {search_conditions.hachu_chubunrui}")
    print(f"  小分類: {search_conditions.hachu_shoubunrui}")
    print(f"  細分類: {search_conditions.hachu_saibunrui}")
    print(f"\n検索URL: {search_url}")
    
    # 検索フォームを送信
    print("\n検索フォームを送信中...")
    result_soup = scraper.submit_search_form(search_url, search_conditions)
    
    if not result_soup:
        print("エラー: 検索結果ページの取得に失敗しました")
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
    
    # HTMLを保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_file = f"search_results_after_fix1_{timestamp}.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(result_soup.prettify())
    print(f"\n検索結果のHTMLを保存しました: {html_file}")
    
    print("\n" + "="*80)
    print("テスト完了")
    print("="*80)


if __name__ == "__main__":
    test_implementation_fix1()
