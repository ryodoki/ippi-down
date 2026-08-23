# -*- coding: utf-8 -*-
"""
Scraperクラスを直接呼び出して工事件数を確認するスクリプト
"""

import sys
from pathlib import Path
import io

# UTF-8出力を強制
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.core.scraper import Scraper
from src.models.config_model import SearchConditions
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger

def main():
    logger = Logger()
    
    print("="*70)
    print("Scraperクラス直接テスト - 工事件数の確認")
    print("="*70)
    
    http_client = HTTPClient(logger=logger)
    scraper = Scraper(http_client, logger=logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    file_types = [".pdf", ".xlsx", ".docx", ".xls", ".doc"]
    
    # 検索条件: 国の機関 → 国土交通省 → 東北地方整備局 + トンネル
    search_conditions = SearchConditions(
        hachu_daibunrui="国の機関",
        hachu_chubunrui="国土交通省",
        hachu_shoubunrui="東北地方整備局",
        koji_name="トンネル"
    )
    
    print("\n検索条件:")
    print(f"  大分類: {search_conditions.hachu_daibunrui}")
    print(f"  中分類: {search_conditions.hachu_chubunrui}")
    print(f"  小分類: {search_conditions.hachu_shoubunrui}")
    print(f"  工事名: {search_conditions.koji_name}")
    
    # Step 1: 検索フォームを送信
    print("\n[1] 検索フォームを送信中...")
    soup = scraper.submit_search_form(search_url, search_conditions)
    
    if not soup:
        print("検索フォームの送信に失敗しました")
        return
    
    print("  検索フォームの送信に成功しました")
    
    # Step 2: _last_search_result_urlを確認
    last_url = getattr(scraper, '_last_search_result_url', None)
    print(f"\n[2] 最後の検索結果URL: {last_url}")
    
    # Step 3: 最初のページの工事件数を確認
    result_table = soup.find("table", id="dgrSearchList")
    if result_table:
        rows = result_table.find_all("tr")[1:]
        print(f"\n[3] 最初のページの工事件数: {len(rows)}件")
        
        # 最初の3件の工事名を表示
        print("\n  最初の3件:")
        for i, row in enumerate(rows[:3]):
            link = row.find("a")
            if link:
                print(f"    {i+1}. {link.get_text(strip=True)[:50]}...")
    else:
        print("\n[3] 検索結果テーブルが見つかりません")
        title = soup.find("title")
        print(f"  ページタイトル: {title.get_text() if title else '不明'}")
    
    # Step 4: ファイルリンクを抽出（全ページ）
    print("\n[4] 全ページからファイルリンクを抽出中...")
    file_links = scraper.extract_file_links_from_search_results(
        soup, search_url, file_types, search_conditions
    )
    
    print(f"\n[結果]")
    print(f"  抽出ファイル数: {len(file_links)}件")
    
    # 工事名のユニーク数をカウント
    koji_names = set()
    files_with_koji = 0
    files_without_koji = 0
    
    for f in file_links:
        if f.metadata and f.metadata.get("koji_name"):
            koji_names.add(f.metadata["koji_name"])
            files_with_koji += 1
        else:
            files_without_koji += 1
    
    print(f"  ユニーク工事件数: {len(koji_names)}件")
    print(f"  工事名あり: {files_with_koji}件")
    print(f"  工事名なし: {files_without_koji}件")
    
    # 最初の10件の工事名を表示
    print(f"\n  工事名リスト（最初の10件）:")
    for i, name in enumerate(list(koji_names)[:10]):
        print(f"    {i+1}. {name[:50]}...")
    
    # 「トンネル」を含まない工事名をチェック
    non_tunnel = [n for n in koji_names if "トンネル" not in n]
    print(f"\n  「トンネル」を含まない工事: {len(non_tunnel)}件")
    if non_tunnel:
        for name in non_tunnel[:5]:
            print(f"    - {name[:50]}...")
    
    print("\n完了")

if __name__ == "__main__":
    main()
