"""ブラウザのリクエストとコードのリクエストを比較するスクリプト

実際のブラウザでのリクエスト情報を入力し、コードで生成しているリクエストと比較します。
"""

import sys
from pathlib import Path
import json
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig  # type: ignore


def compare_requests(browser_request_info: dict, download_url: str):
    """ブラウザのリクエストとコードのリクエストを比較"""
    print("=" * 80)
    print("ブラウザリクエスト vs コードリクエスト 比較")
    print("=" * 80)
    
    logger = Logger(LoggingConfig(level="INFO"))
    http_client = HTTPClient(logger)
    
    print("\n[ブラウザのリクエスト情報]")
    print("-" * 80)
    print(f"URL: {browser_request_info.get('url', 'N/A')}")
    print(f"Method: {browser_request_info.get('method', 'GET')}")
    print(f"Headers:")
    browser_headers = browser_request_info.get('headers', {})
    for key, value in browser_headers.items():
        print(f"  {key}: {value}")
    
    print(f"\nCookies:")
    browser_cookies = browser_request_info.get('cookies', {})
    for name, value in browser_cookies.items():
        print(f"  {name}: {value}")
    
    print("\n[コードで生成するリクエスト]")
    print("-" * 80)
    
    # コードで使用しているヘッダー
    code_headers = {
        "User-Agent": http_client.session.headers.get("User-Agent"),
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    # Refererを追加（page_urlから）
    referer = browser_request_info.get('referer', '')
    if referer:
        code_headers["Referer"] = referer
    
    print(f"URL: {download_url}")
    print(f"Method: GET")
    print(f"Headers:")
    for key, value in code_headers.items():
        print(f"  {key}: {value}")
    
    print(f"\nCookies:")
    for cookie in http_client.session.cookies:
        print(f"  {cookie.name}: {cookie.value[:50]}...")
    
    # 比較
    print("\n[差異の分析]")
    print("-" * 80)
    
    differences = []
    
    # URLの比較
    if browser_request_info.get('url') != download_url:
        differences.append({
            "type": "URL",
            "browser": browser_request_info.get('url'),
            "code": download_url,
            "recommendation": "URLをブラウザと同じに修正する必要があります"
        })
    
    # ヘッダーの比較
    missing_headers = []
    for key, value in browser_headers.items():
        if key.lower() not in [h.lower() for h in code_headers.keys()]:
            missing_headers.append({key: value})
    
    if missing_headers:
        differences.append({
            "type": "Missing Headers",
            "headers": missing_headers,
            "recommendation": "不足しているヘッダーを追加する必要があります"
        })
    
    # Cookieの比較
    code_cookie_domains = [cookie.domain for cookie in http_client.session.cookies]
    browser_cookie_domains = [c.get('domain', '') for c in browser_request_info.get('cookie_list', [])]
    
    missing_cookies = []
    for browser_cookie in browser_request_info.get('cookie_list', []):
        cookie_name = browser_cookie.get('name', '')
        cookie_domain = browser_cookie.get('domain', '')
        
        # 同じドメインのCookieがコードに存在するか確認
        found = False
        for code_cookie in http_client.session.cookies:
            if code_cookie.name == cookie_name and code_cookie.domain == cookie_domain:
                found = True
                break
        
        if not found:
            missing_cookies.append(browser_cookie)
    
    if missing_cookies:
        differences.append({
            "type": "Missing Cookies",
            "cookies": missing_cookies,
            "recommendation": "不足しているCookieを追加する必要があります"
        })
    
    # 結果を表示
    if differences:
        print("以下の差異が見つかりました：\n")
        for i, diff in enumerate(differences, 1):
            print(f"{i}. {diff['type']}")
            if diff['type'] == 'URL':
                print(f"   ブラウザ: {diff['browser']}")
                print(f"   コード: {diff['code']}")
            elif diff['type'] == 'Missing Headers':
                print(f"   不足しているヘッダー:")
                for header in diff['headers']:
                    for key, value in header.items():
                        print(f"     {key}: {value}")
            elif diff['type'] == 'Missing Cookies':
                print(f"   不足しているCookie:")
                for cookie in diff['cookies']:
                    print(f"     {cookie.get('name')} (domain: {cookie.get('domain')})")
            print(f"   推奨: {diff['recommendation']}")
            print()
    else:
        print("差異は見つかりませんでした。")
        print("タイムアウトの原因は他の要因（ネットワーク、ファイアウォール等）の可能性があります。")
    
    # 修正提案を生成
    print("\n[修正提案]")
    print("-" * 80)
    
    if differences:
        print("以下の修正を推奨します：\n")
        
        # 修正コードを生成
        print("1. HTTPClientのdownload_fileメソッドを修正:")
        print("```python")
        print("def download_file(self, url, save_path, progress_callback=None, max_retries=3, referer=None):")
        print("    # ブラウザと同じヘッダーを設定")
        print("    download_headers = {")
        
        # ブラウザのヘッダーを追加
        for key, value in browser_headers.items():
            if key.lower() not in ['host', 'content-length', 'content-type']:  # 自動設定されるヘッダーは除外
                value_escaped = value.replace('"', '\\"')
                print(f'        "{key}": "{value_escaped}",')
        
        if not any(h.lower() == 'referer' for h in browser_headers.keys()):
            if referer:
                print(f'        "Referer": "{referer}",')
        
        print("    }")
        print("    # ... 以下、既存のコード")
        print("```")
        
        # Cookieの修正
        if missing_cookies:
            print("\n2. Cookieを手動で設定:")
            print("```python")
            print("from http.cookiejar import Cookie")
            for cookie in missing_cookies:
                domain = cookie.get('domain', '')
                name = cookie.get('name', '')
                value = cookie.get('value', '')
                path = cookie.get('path', '/')
                secure = cookie.get('secure', False)
                print(f"# {domain} のCookieを追加")
                print(f"cookie = Cookie(")
                print(f"    version=0,")
                print(f"    name='{name}',")
                print(f"    value='{value}',")
                print(f"    port=None,")
                print(f"    port_specified=False,")
                print(f"    domain='{domain}',")
                print(f"    domain_specified=True,")
                print(f"    domain_initial_dot=False,")
                print(f"    path='{path}',")
                print(f"    path_specified=True,")
                print(f"    secure={secure},")
                print(f"    expires=None,")
                print(f"    discard=True,")
                print(f"    comment=None,")
                print(f"    comment_url=None,")
                print(f"    rest={{}},")
                print(f")")
                print(f"http_client.session.cookies.set_cookie(cookie)")
            print("```")
    
    # 結果を保存
    output_file = project_root / "docs" / "dev" / "request_comparison.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    comparison_result = {
        "timestamp": datetime.now().isoformat(),
        "browser_request": browser_request_info,
        "code_request": {
            "url": download_url,
            "headers": code_headers,
            "cookies": [
                {
                    "name": cookie.name,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "value": cookie.value[:50] + "..."
                }
                for cookie in http_client.session.cookies
            ]
        },
        "differences": differences
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(comparison_result, f, ensure_ascii=False, indent=2)
    
    print(f"\n比較結果を保存: {output_file}")
    
    http_client.close()
    return differences


if __name__ == "__main__":
    print("このスクリプトは、ブラウザで取得したリクエスト情報を入力して、")
    print("コードで生成しているリクエストと比較します。")
    print()
    print("使用方法:")
    print("1. ブラウザの開発者ツールでリクエスト情報を取得")
    print("2. 以下の情報をJSON形式で入力:")
    print("   - url: 最終的なダウンロードURL")
    print("   - method: リクエストメソッド（通常はGET）")
    print("   - headers: すべてのリクエストヘッダー")
    print("   - cookies: Cookieのリスト（name, value, domain, path等）")
    print("   - referer: Refererヘッダーの値")
    print()
    print("例:")
    print("```json")
    print('{')
    print('  "url": "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?...",')
    print('  "method": "GET",')
    print('  "headers": {')
    print('    "User-Agent": "...",')
    print('    "Accept": "...",')
    print('    "Referer": "..."')
    print('  },')
    print('  "cookies": [...]')
    print('}')
    print("```")
    print()
    print("入力ファイルのパスを指定してください:")
    input_file = input("> ").strip()
    
    if not input_file:
        print("ファイルパスが指定されていません。")
        sys.exit(1)
    
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            browser_request_info = json.load(f)
        
        download_url = browser_request_info.get('url', '')
        if not download_url:
            print("URLが指定されていません。")
            sys.exit(1)
        
        differences = compare_requests(browser_request_info, download_url)
        
        if differences:
            print(f"\n{differences}個の差異が見つかりました。修正を推奨します。")
            sys.exit(1)
        else:
            print("\n差異は見つかりませんでした。")
            sys.exit(0)
            
    except FileNotFoundError:
        print(f"ファイルが見つかりません: {input_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"JSONの解析エラー: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"エラーが発生しました: {type(e).__name__}: {str(e)}")
        sys.exit(1)
