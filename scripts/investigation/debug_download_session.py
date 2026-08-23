# -*- coding: utf-8 -*-
"""
ダウンロード時のセッション状態を調査するスクリプト
GUIと同じ流れで処理して、ダウンロードが成功するか確認
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
import requests

def main():
    logger = Logger()
    
    print("="*70)
    print("ダウンロードセッション調査")
    print("="*70)
    
    http_client = HTTPClient(logger=logger)
    scraper = Scraper(http_client, logger=logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    file_types = [".pdf", ".xlsx", ".docx", ".xls", ".doc"]
    
    # 検索条件
    search_conditions = SearchConditions(
        hachu_daibunrui="国の機関",
        hachu_chubunrui="国土交通省",
        hachu_shoubunrui="東北地方整備局",
        koji_name="トンネル"
    )
    
    print("\n[1] 検索フォームを送信中...")
    soup = scraper.submit_search_form(search_url, search_conditions)
    
    if not soup:
        print("検索フォームの送信に失敗しました")
        return
    
    print("  検索完了")
    
    # ファイルリンクを抽出
    print("\n[2] ファイルリンクを抽出中...")
    file_links = scraper.extract_file_links_from_search_results(
        soup, search_url, file_types, search_conditions
    )
    
    print(f"  抽出ファイル数: {len(file_links)}件")
    
    if not file_links:
        print("ファイルリンクが見つかりませんでした")
        return
    
    # 最初のファイルをダウンロードしてテスト
    print("\n[3] セッション状態の確認")
    session = http_client.get_session()
    
    print(f"  クッキー数: {len(session.cookies)}")
    for cookie in session.cookies:
        print(f"    - {cookie.name}: {cookie.domain} (path: {cookie.path})")
    
    # 最初のファイルをダウンロードしてみる
    test_file = file_links[0]
    print(f"\n[4] テストダウンロード")
    print(f"  URL: {test_file.url[:80]}...")
    print(f"  page_url: {test_file.page_url[:80] if test_file.page_url else 'なし'}...")
    print(f"  工事名: {test_file.metadata.get('koji_name', '不明')[:40]}...")
    
    # URLのドメインを確認
    from urllib.parse import urlparse
    parsed = urlparse(test_file.url)
    print(f"  ダウンロードドメイン: {parsed.netloc}")
    
    # ダウンロードを試行
    print(f"\n[5] ダウンロード試行（GUIと同じ方法）")
    
    # HTTPClientのdownload_fileを使用
    save_path = "test_download_session.pdf"
    referer = test_file.page_url if test_file.page_url else None
    
    print(f"  Referer: {referer[:80] if referer else 'なし'}...")
    
    success = http_client.download_file(
        test_file.url,
        save_path,
        progress_callback=None,
        max_retries=1,
        referer=referer
    )
    
    if success:
        print(f"  結果: 成功！")
        # ファイルの内容を確認
        with open(save_path, "rb") as f:
            first_bytes = f.read(100)
        if first_bytes.startswith(b'%PDF'):
            print(f"  内容: PDF (正常)")
        elif b'<html' in first_bytes.lower():
            print(f"  内容: HTML (失敗)")
        else:
            print(f"  内容: 不明 ({first_bytes[:20]})")
    else:
        print(f"  結果: 失敗")
    
    # 直接セッションでダウンロードを試行
    print(f"\n[6] 直接セッションでダウンロード試行")
    
    download_headers = {
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    if referer:
        download_headers["Referer"] = referer
    
    response = session.get(test_file.url, headers=download_headers, stream=True, timeout=30)
    
    print(f"  ステータス: {response.status_code}")
    print(f"  Content-Type: {response.headers.get('Content-Type', '不明')}")
    print(f"  Content-Length: {response.headers.get('Content-Length', '不明')}")
    
    # 最初の100バイトを確認
    first_bytes = response.content[:100]
    if first_bytes.startswith(b'%PDF'):
        print(f"  内容: PDF (正常)")
    elif b'<html' in first_bytes.lower() or b'<!doctype' in first_bytes.lower():
        print(f"  内容: HTML (失敗)")
        # HTMLの内容を表示
        try:
            html_content = response.content[:500].decode('utf-8', errors='replace')
            print(f"\n  HTMLプレビュー:")
            print(f"  {html_content[:300]}...")
        except:
            pass
    else:
        print(f"  内容: 不明 ({first_bytes[:30]})")
    
    # 別の新しいセッションでダウンロード試行
    print(f"\n[7] 新しいセッションで詳細ページ→ダウンロード")
    
    new_session = requests.Session()
    new_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    
    # 詳細ページにアクセス（page_url）
    if test_file.page_url:
        print(f"  詳細ページにアクセス: {test_file.page_url[:60]}...")
        detail_response = new_session.get(test_file.page_url, timeout=30)
        print(f"  詳細ページステータス: {detail_response.status_code}")
        
        # ダウンロード
        print(f"  ファイルダウンロード...")
        download_headers["Referer"] = test_file.page_url
        dl_response = new_session.get(test_file.url, headers=download_headers, stream=True, timeout=30)
        
        print(f"  ステータス: {dl_response.status_code}")
        print(f"  Content-Type: {dl_response.headers.get('Content-Type', '不明')}")
        
        first_bytes = dl_response.content[:100]
        if first_bytes.startswith(b'%PDF'):
            print(f"  内容: PDF (正常)")
        elif b'<html' in first_bytes.lower():
            print(f"  内容: HTML (失敗)")
        else:
            print(f"  内容: 不明")
    
    http_client.close()
    new_session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
