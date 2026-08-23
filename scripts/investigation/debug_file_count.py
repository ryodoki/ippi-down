# -*- coding: utf-8 -*-
"""
ファイル数の重複問題を調査するスクリプト
"""

import sys
from pathlib import Path
import io
from collections import Counter

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
    print("ファイル数の重複問題を調査")
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
    
    # 検索フォームを送信
    print("\n[1] 検索フォームを送信中...")
    soup = scraper.submit_search_form(search_url, search_conditions)
    
    if not soup:
        print("検索フォームの送信に失敗しました")
        return
    
    # ファイルリンクを抽出
    print("\n[2] ファイルリンクを抽出中...")
    file_links = scraper.extract_file_links_from_search_results(
        soup, search_url, file_types, search_conditions
    )
    
    print(f"\n[結果]")
    print(f"  抽出ファイル数: {len(file_links)}件")
    
    # URLの重複をチェック
    urls = [f.url for f in file_links]
    url_counts = Counter(urls)
    
    duplicates = {url: count for url, count in url_counts.items() if count > 1}
    
    print(f"  ユニークURL数: {len(url_counts)}件")
    print(f"  重複URL数: {len(duplicates)}件")
    
    if duplicates:
        print(f"\n[重複URLの例（最初の5件）]")
        for i, (url, count) in enumerate(list(duplicates.items())[:5]):
            print(f"  {i+1}. {url[:80]}... ({count}回)")
    
    # ファイル名+工事名の重複をチェック
    file_keys = [(f.filename, f.metadata.get("koji_name", "不明")) for f in file_links]
    file_key_counts = Counter(file_keys)
    
    file_duplicates = {key: count for key, count in file_key_counts.items() if count > 1}
    
    print(f"\n[ファイル名+工事名の重複]")
    print(f"  重複数: {len(file_duplicates)}件")
    
    if file_duplicates:
        print(f"\n[重複ファイルの例（最初の5件）]")
        for i, ((filename, koji), count) in enumerate(list(file_duplicates.items())[:5]):
            print(f"  {i+1}. {filename} / {koji[:30]}... ({count}回)")
    
    http_client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
