# -*- coding: utf-8 -*-
"""
スクレイパーで全ページを取得
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
    print("スクレイパー全ページ取得テスト")
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
    
    # 全ページからファイルリンクを抽出
    print("\n[2] 全ページからファイルリンクを抽出中...")
    file_types = [".pdf", ".xlsx", ".xls", ".doc", ".docx"]
    
    all_files = scraper.extract_file_links_from_search_results(
        soup, search_url, file_types, search_conditions
    )
    
    print(f"\n[3] 抽出結果:")
    print(f"  総ファイルリンク数: {len(all_files)}件")
    
    # 工事ごとにグループ化
    koji_names = set()
    for file_info in all_files:
        if file_info.metadata and "koji_name" in file_info.metadata:
            koji_names.add(file_info.metadata["koji_name"])
    
    print(f"  ユニークな工事名数: {len(koji_names)}件")
    
    # 最初の10件の工事名を表示
    print("\n  === 工事名（最初の10件）===")
    for i, name in enumerate(list(koji_names)[:10]):
        print(f"    {i+1}. {name[:60]}...")
    
    http_client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
