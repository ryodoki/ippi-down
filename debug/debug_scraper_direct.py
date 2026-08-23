# -*- coding: utf-8 -*-
"""
スクレイパーを直接使用して検索をテスト
GUIと同じパスを通って検索を実行
"""

import sys
import io
from pathlib import Path

# UTF-8出力を強制
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# パス設定
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient
from src.utils.logger import Logger
from src.core.scraper import Scraper
from src.models.config_model import SearchConditions

def main():
    print("="*70)
    print("スクレイパー直接テスト")
    print("="*70)
    
    # ロガーとHTTPクライアントを作成
    logger = Logger()
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    # 検索条件を設定
    search_conditions = SearchConditions(
        hachu_daibunrui="国の機関",
        hachu_chubunrui="国土交通省",
        hachu_shoubunrui="東北地方整備局",
        hachu_saibunrui="",
        koji_name="トンネル"
    )
    
    print(f"\n検索条件:")
    print(f"  大分類: {search_conditions.hachu_daibunrui}")
    print(f"  中分類: {search_conditions.hachu_chubunrui}")
    print(f"  小分類: {search_conditions.hachu_shoubunrui}")
    print(f"  工事名: {search_conditions.koji_name}")
    
    # 検索URL
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print(f"\n検索URL: {search_url}")
    
    # 検索を実行
    print("\n[1] 検索フォームを送信中...")
    soup = scraper.submit_search_form(search_url, search_conditions)
    
    if not soup:
        print("  検索フォームの送信に失敗しました")
        return
    
    print("  検索フォームの送信に成功しました")
    
    # 検索結果を確認
    result_table = soup.find("table", id="dgrSearchList")
    if result_table:
        rows = result_table.find_all("tr")[1:]  # ヘッダー除く
        print(f"\n[2] 検索結果: {len(rows)}件 (最初のページ)")
        
        # 最初の10件を表示
        print("\n  === 最初の10件 ===")
        for i, row in enumerate(rows[:10]):
            cells = row.find_all("td")
            link = row.find("a")
            if link and len(cells) >= 2:
                koji_name = link.get_text(strip=True)
                hachu_kikan = cells[1].get_text(strip=True)
                print(f"    {i+1}. {koji_name[:40]}... / {hachu_kikan}")
        
        # 東北地方整備局のものを数える
        tohoku_count = 0
        other_kikan = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                hachu_kikan = cells[1].get_text(strip=True)
                if "東北地方整備局" in hachu_kikan:
                    tohoku_count += 1
                else:
                    if hachu_kikan not in other_kikan:
                        other_kikan.append(hachu_kikan)
        
        print(f"\n  東北地方整備局の件数: {tohoku_count}/{len(rows)}件")
        if other_kikan:
            print(f"  その他の発注機関: {other_kikan[:5]}")
    else:
        print("\n[2] 検索結果テーブルが見つかりません")
        title = soup.find("title")
        if title:
            print(f"  ページタイトル: {title.get_text()}")
    
    # ファイルリンクを抽出
    print("\n[3] ファイルリンクを抽出中...")
    file_types = [".pdf", ".xlsx", ".xls", ".doc", ".docx"]
    
    # 最初のページのみ（デバッグ用）
    file_links = scraper._extract_file_links_from_single_page(
        soup, search_url, file_types, search_conditions
    )
    
    print(f"  抽出されたファイルリンク: {len(file_links)}件")
    
    # ファイルリンクの詳細を表示
    if file_links:
        print("\n  === 最初の5件 ===")
        for i, file_info in enumerate(file_links[:5]):
            koji_name = file_info.metadata.get("koji_name", "N/A") if file_info.metadata else "N/A"
            print(f"    {i+1}. {koji_name[:40]}... -> {file_info.filename}")
    
    http_client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
