"""ブラウザでのダウンロード動作を分析するスクリプト

実際のブラウザでのダウンロード動作をシミュレートし、
必要なヘッダー、Cookie、リダイレクトの流れを確認します。
"""

import sys
from pathlib import Path
import json
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import re


def analyze_browser_download():
    """ブラウザでのダウンロード動作を分析"""
    print("=" * 80)
    print("ブラウザでのダウンロード動作分析")
    print("=" * 80)
    print("\nこのスクリプトは以下を確認します：")
    print("  1. 実際のURLとリダイレクトの流れ")
    print("  2. 必要なヘッダー（Referer, Cookie等）")
    print("  3. セッション管理")
    print("  4. ダウンロードURLの生成方法")
    print()
    
    logger = Logger(LoggingConfig(level="INFO"))
    http_client = HTTPClient(logger, timeout=30, download_timeout=300)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    
    try:
        # ステップ1: 検索を実行してファイルリンクを取得
        print("\n[ステップ1] 検索を実行してファイルリンクを取得")
        print("-" * 80)
        
        search_conditions = SearchConditions(hachu_daibunrui="国の機関")
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        
        if not result_soup:
            print("[ERROR] 検索に失敗しました")
            return False
        
        files = scraper.extract_file_links_from_search_results(
            result_soup, search_url, [".pdf"]
        )
        
        if not files or len(files) == 0:
            print("[ERROR] ファイルが見つかりませんでした")
            return False
        
        test_file = files[0]
        print(f"\n[INFO] テストファイルを選択: {test_file.filename}")
        print(f"  URL: {test_file.url}")
        print(f"  Page URL: {test_file.page_url}")
        print(f"  Metadata: {test_file.metadata}")
        
        # ステップ2: URLの詳細分析
        print("\n[ステップ2] URLの詳細分析")
        print("-" * 80)
        
        parsed_url = urlparse(test_file.url)
        print(f"  スキーム: {parsed_url.scheme}")
        print(f"  ホスト: {parsed_url.netloc}")
        print(f"  パス: {parsed_url.path}")
        print(f"  クエリ: {parsed_url.query}")
        print(f"  フラグメント: {parsed_url.fragment}")
        
        # クエリパラメータを解析
        if parsed_url.query:
            from urllib.parse import parse_qs
            params = parse_qs(parsed_url.query)
            print(f"\n  クエリパラメータ:")
            for key, values in params.items():
                print(f"    {key}: {values[0] if values else ''}")
        
        # ステップ3: セッション情報の確認
        print("\n[ステップ3] セッション情報の確認")
        print("-" * 80)
        
        print(f"  Cookies数: {len(http_client.session.cookies)}")
        for cookie in http_client.session.cookies:
            print(f"    {cookie.name}:")
            print(f"      domain: {cookie.domain}")
            print(f"      path: {cookie.path}")
            print(f"      secure: {cookie.secure}")
            print(f"      expires: {cookie.expires}")
            print(f"      value: {cookie.value[:50]}...")
        
        # ステップ4: 実際のダウンロードURLへのアクセスを試行（詳細ログ付き）
        print("\n[ステップ4] ダウンロードURLへのアクセス試行（詳細ログ）")
        print("-" * 80)
        
        download_headers = {
            "User-Agent": http_client.session.headers.get("User-Agent"),
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        # Refererを追加
        if test_file.page_url:
            download_headers["Referer"] = test_file.page_url
            print(f"  Referer: {test_file.page_url}")
        
        print(f"\n  送信するヘッダー:")
        for key, value in download_headers.items():
            print(f"    {key}: {value}")
        
        print(f"\n  リクエストURL: {test_file.url}")
        
        # HEADリクエストで接続テスト
        print(f"\n  [試行1] HEADリクエスト（接続確認）")
        try:
            head_response = http_client.session.head(
                test_file.url,
                headers=download_headers,
                timeout=(10, 30),
                allow_redirects=True
            )
            print(f"    Status Code: {head_response.status_code}")
            print(f"    Final URL: {head_response.url}")
            print(f"    Redirects: {len(head_response.history)}")
            if head_response.history:
                for i, resp in enumerate(head_response.history, 1):
                    print(f"      {i}. {resp.status_code} -> {resp.url[:100]}...")
            print(f"    Headers:")
            for key, value in head_response.headers.items():
                if key.lower() in ['content-type', 'content-length', 'location', 'server', 'set-cookie']:
                    print(f"      {key}: {value}")
        except Exception as e:
            print(f"    [ERROR] HEADリクエスト失敗: {type(e).__name__}: {str(e)}")
        
        # GETリクエストで実際のダウンロードを試行
        print(f"\n  [試行2] GETリクエスト（stream=True, 最初の1KBのみ）")
        try:
            get_response = http_client.session.get(
                test_file.url,
                headers=download_headers,
                stream=True,
                timeout=(10, 60),
                allow_redirects=True
            )
            print(f"    Status Code: {get_response.status_code}")
            print(f"    Final URL: {get_response.url}")
            print(f"    Redirects: {len(get_response.history)}")
            if get_response.history:
                for i, resp in enumerate(get_response.history, 1):
                    print(f"      {i}. {resp.status_code} -> {resp.url[:100]}...")
            
            print(f"\n    Response Headers:")
            for key, value in get_response.headers.items():
                print(f"      {key}: {value}")
            
            # 最初の1KBを読み取ってContent-Typeを確認
            if get_response.status_code == 200:
                chunk = next(get_response.iter_content(chunk_size=1024), None)
                if chunk:
                    content_type = get_response.headers.get('Content-Type', '')
                    print(f"\n    Content-Type: {content_type}")
                    print(f"    最初の1KB読み取り: 成功 ({len(chunk)} bytes)")
                    
                    # PDFのマジックナンバーを確認
                    if chunk.startswith(b'%PDF'):
                        print(f"    [SUCCESS] PDFファイルとして認識されました")
                    else:
                        print(f"    [WARN] PDFのマジックナンバーが見つかりませんでした")
                        print(f"    最初の16バイト: {chunk[:16]}")
                
                get_response.close()
        except requests.exceptions.Timeout as e:
            print(f"    [ERROR] タイムアウト: {type(e).__name__}")
            print(f"      詳細: {str(e)}")
        except requests.exceptions.ConnectionError as e:
            print(f"    [ERROR] 接続エラー: {type(e).__name__}")
            print(f"      詳細: {str(e)}")
        except Exception as e:
            print(f"    [ERROR] 予期しないエラー: {type(e).__name__}: {str(e)}")
        
        # ステップ5: ページURLから直接アクセスを試行
        print("\n[ステップ5] ページURLから直接アクセスを試行")
        print("-" * 80)
        
        if test_file.page_url:
            print(f"  Page URL: {test_file.page_url}")
            try:
                page_response = http_client.get(test_file.page_url)
                page_soup = BeautifulSoup(page_response.content, 'html.parser')
                
                # ページ内のダウンロードリンクを再確認
                print(f"  Status Code: {page_response.status_code}")
                
                # JavaScript変数を探す
                scripts = page_soup.find_all('script')
                for script in scripts:
                    if script.string and ('AnkenkanriNo' in script.string or 'KokaiBunshoServlet' in script.string):
                        print(f"\n  JavaScriptコードを発見:")
                        script_text = script.string[:500]  # 最初の500文字
                        print(f"    {script_text}...")
                        
                        # AnkenkanriNoとBunshoKanriIdを抽出
                        anken_match = re.search(r'AnkenkanriNo\s*=\s*["\']([^"\']+)["\']', script.string)
                        bunsho_match = re.search(r'BunshoKanriId\s*=\s*["\']([^"\']+)["\']', script.string)
                        
                        if anken_match:
                            print(f"    AnkenkanriNo: {anken_match.group(1)}")
                        if bunsho_match:
                            print(f"    BunshoKanriId: {bunsho_match.group(1)}")
            except Exception as e:
                print(f"  [ERROR] ページURL取得失敗: {type(e).__name__}: {str(e)}")
        
        # ステップ6: 分析結果を保存
        print("\n[ステップ6] 分析結果を保存")
        print("-" * 80)
        
        analysis_result = {
            "timestamp": datetime.now().isoformat(),
            "test_file": {
                "filename": test_file.filename,
                "url": test_file.url,
                "page_url": test_file.page_url,
                "metadata": test_file.metadata
            },
            "parsed_url": {
                "scheme": parsed_url.scheme,
                "netloc": parsed_url.netloc,
                "path": parsed_url.path,
                "query": parsed_url.query
            },
            "cookies": [
                {
                    "name": cookie.name,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "secure": cookie.secure
                }
                for cookie in http_client.session.cookies
            ],
            "headers": download_headers
        }
        
        output_file = project_root / "docs" / "dev" / "browser_download_analysis.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)
        
        print(f"  分析結果を保存: {output_file}")
        
        # ステップ7: 推奨事項を提示
        print("\n[ステップ7] 推奨事項")
        print("-" * 80)
        print("以下の点を確認してください：")
        print("  1. ブラウザの開発者ツール（F12）でネットワークタブを開く")
        print("  2. 実際にブラウザでファイルをダウンロード")
        print("  3. ネットワークタブで以下の情報を確認：")
        print("     - リクエストURL（最終的なURL、リダイレクト後）")
        print("     - リクエストヘッダー（すべて）")
        print("     - レスポンスヘッダー（すべて）")
        print("     - Cookie（すべて）")
        print("     - リダイレクトの流れ")
        print("  4. このスクリプトの結果と比較")
        print("\n  分析結果ファイル: docs/dev/browser_download_analysis.json")
        
        return True
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()


if __name__ == "__main__":
    success = analyze_browser_download()
    sys.exit(0 if success else 1)
