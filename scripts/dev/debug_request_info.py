"""開発者モードで必要な情報を抽出・確認するスクリプト

実際のブラウザのリクエストと比較して、不足している情報を特定します。
"""

import sys
from pathlib import Path
import json
from urllib.parse import urlparse, urljoin

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig  # type: ignore
from src.core.scraper import Scraper  # type: ignore
import requests
from bs4 import BeautifulSoup


def analyze_browser_request():
    """ブラウザのリクエスト情報を分析"""
    print("=" * 80)
    print("開発者モード: リクエスト情報の分析")
    print("=" * 80)
    
    logger = Logger(LoggingConfig(level="DEBUG"))
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    
    try:
        # ステップ1: 初回GETリクエストの情報を取得
        print("\n[ステップ1] 初回GETリクエストの情報")
        print("-" * 80)
        
        response = http_client.get(search_url)
        
        # リクエスト情報
        print("\n[送信] リクエスト情報:")
        print(f"  URL: {response.request.url}")
        print(f"  Method: {response.request.method}")
        print(f"  Headers:")
        for key, value in response.request.headers.items():
            print(f"    {key}: {value}")
        
        # レスポンス情報
        print("\n[受信] レスポンス情報:")
        print(f"  Status Code: {response.status_code}")
        print(f"  Headers:")
        for key, value in response.headers.items():
            if key.lower() in ['set-cookie', 'cookie']:
                print(f"    {key}: {value[:100]}...")
            else:
                print(f"    {key}: {value}")
        
        # Cookie情報
        print("\n[Cookie] Cookie情報:")
        cookies = http_client.session.cookies
        if cookies:
            for cookie in cookies:
                print(f"  {cookie.name}: {cookie.value[:50]}... (domain: {cookie.domain}, path: {cookie.path})")
        else:
            print("  Cookieなし")
        
        # ステップ2: HTMLから必要な情報を抽出
        print("\n[ステップ2] HTMLから必要な情報を抽出")
        print("-" * 80)
        
        soup = BeautifulSoup(response.content, "lxml")
        
        # Hidden inputの確認
        hidden_inputs = scraper._get_all_hidden_inputs(soup)
        print(f"\n[Hidden Inputs] Hidden Inputs ({len(hidden_inputs)}個):")
        important_keys = ["__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR", "__EVENTTARGET", "__EVENTARGUMENT"]
        for key in important_keys:
            if key in hidden_inputs:
                value = hidden_inputs[key]
                print(f"  [OK] {key}: 長さ={len(value)}")
            else:
                # 部分一致で探す
                found = [k for k in hidden_inputs.keys() if key.upper() in k.upper()]
                if found:
                    print(f"  [WARN] {key}: 見つかりません（類似: {found}）")
                else:
                    print(f"  [NG] {key}: 見つかりません")
        
        # フォーム情報
        forms = soup.find_all("form")
        print(f"\n[Form] フォーム情報 ({len(forms)}個):")
        for i, form in enumerate(forms, 1):
            print(f"  フォーム {i}:")
            print(f"    action: {form.get('action', 'なし')}")
            print(f"    method: {form.get('method', 'GET')}")
            print(f"    enctype: {form.get('enctype', 'なし')}")
        
        # ステップ3: ファイルダウンロードURLの分析
        print("\n[ステップ3] ファイルダウンロードURLの分析")
        print("-" * 80)
        
        # 検索条件を設定して検索
        from src.models.config_model import SearchConditions
        search_conditions = SearchConditions(
            hachu_daibunrui="国の機関"
        )
        
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        if result_soup:
            files = scraper.extract_file_links_from_search_results(
                result_soup, search_url, [".pdf"]
            )
            
            if files:
                test_file = files[0]
                print(f"\n[File] テストファイル:")
                print(f"  URL: {test_file.url}")
                print(f"  Filename: {test_file.filename}")
                
                # URLの解析
                parsed_url = urlparse(test_file.url)
                print(f"\n[URL] URL解析:")
                print(f"  Scheme: {parsed_url.scheme}")
                print(f"  Netloc: {parsed_url.netloc}")
                print(f"  Path: {parsed_url.path}")
                print(f"  Query: {parsed_url.query}")
                
                # ステップ4: ダウンロードリクエストの準備
                print("\n[ステップ4] ダウンロードリクエストの準備")
                print("-" * 80)
                
                # 現在のセッション情報
                print("\n[Session] 現在のセッション情報:")
                print(f"  Cookies数: {len(http_client.session.cookies)}")
                print(f"  Headers:")
                for key, value in http_client.session.headers.items():
                    print(f"    {key}: {value}")
                
                # 必要なヘッダーの確認
                print("\n[Headers] 推奨される追加ヘッダー:")
                recommended_headers = {
                    "Referer": search_url,
                    "Accept": "application/pdf,application/octet-stream,*/*",
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1"
                }
                
                current_headers = dict(http_client.session.headers)
                for key, value in recommended_headers.items():
                    if key not in current_headers:
                        print(f"  [NG] {key}: {value} (不足)")
                    else:
                        print(f"  [OK] {key}: {current_headers[key]}")
                
                # ステップ5: 実際のダウンロードリクエストを試行（ヘッダー付き）
                print("\n[ステップ5] 改善されたヘッダーでダウンロードを試行")
                print("-" * 80)
                
                # ヘッダーを追加
                download_headers = {
                    "Referer": search_url,
                    "Accept": "application/pdf,application/octet-stream,*/*",
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                }
                
                print(f"\n[Request] 改善されたリクエスト:")
                print(f"  URL: {test_file.url}")
                print(f"  Headers:")
                for key, value in download_headers.items():
                    print(f"    {key}: {value}")
                
                # 実際のリクエストを試行（HEADリクエストで確認）
                try:
                    head_response = http_client.session.head(
                        test_file.url,
                        headers=download_headers,
                        timeout=30,
                        allow_redirects=True
                    )
                    print(f"\n[Response] HEADリクエスト結果:")
                    print(f"  Status Code: {head_response.status_code}")
                    print(f"  Headers:")
                    for key, value in head_response.headers.items():
                        if key.lower() in ['content-type', 'content-length', 'location']:
                            print(f"    {key}: {value}")
                    
                    if head_response.status_code == 200:
                        print("\n[SUCCESS] HEADリクエスト成功！ダウンロード可能です")
                    elif head_response.status_code in [301, 302, 303, 307, 308]:
                        print(f"\n[REDIRECT] リダイレクト: {head_response.headers.get('Location', 'なし')}")
                    else:
                        print(f"\n[ERROR] エラー: Status Code {head_response.status_code}")
                        
                except requests.exceptions.Timeout as e:
                    print(f"\n[ERROR] タイムアウトエラー: {str(e)}")
                    print("  接続タイムアウトの可能性があります")
                except requests.exceptions.ConnectionError as e:
                    print(f"\n[ERROR] 接続エラー: {str(e)}")
                    print("  ネットワーク接続の問題の可能性があります")
                except Exception as e:
                    print(f"\n[ERROR] エラー: {type(e).__name__}: {str(e)}")
        
        # ステップ6: 情報をJSONファイルに保存
        print("\n[ステップ6] 情報をJSONファイルに保存")
        print("-" * 80)
        
        debug_info = {
            "request_url": search_url,
            "request_headers": dict(response.request.headers),
            "response_status": response.status_code,
            "response_headers": dict(response.headers),
            "cookies": [
                {
                    "name": cookie.name,
                    "value": cookie.value[:100] + "..." if len(cookie.value) > 100 else cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path
                }
                for cookie in http_client.session.cookies
            ],
            "hidden_inputs": {
                k: v[:100] + "..." if len(v) > 100 else v
                for k, v in hidden_inputs.items()
            },
            "recommended_headers": recommended_headers
        }
        
        output_file = Path("debug_request_info.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(debug_info, f, ensure_ascii=False, indent=2)
        
        print(f"[SUCCESS] デバッグ情報を保存: {output_file}")
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
    finally:
        http_client.close()


if __name__ == "__main__":
    analyze_browser_request()

