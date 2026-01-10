"""記録したブラウザリクエストを分析するスクリプト

ブラウザの開発者ツールで取得したリクエスト情報を入力し、
コードで生成しているリクエストと比較して、差異を特定します。
"""

import sys
from pathlib import Path
import json
from datetime import datetime
from typing import Dict, List, Any

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def analyze_captured_request(browser_request_file: str):
    """記録したブラウザリクエストを分析"""
    print("=" * 80)
    print("ブラウザリクエスト分析ツール")
    print("=" * 80)
    
    # ブラウザリクエスト情報を読み込み
    try:
        with open(browser_request_file, "r", encoding="utf-8") as f:
            browser_data = json.load(f)
    except FileNotFoundError:
        print(f"\n[ERROR] ファイルが見つかりません: {browser_request_file}")
        print("\nテンプレートファイルを使用する場合は:")
        print("  python scripts/dev/analyze_captured_request.py docs/dev/browser_request_template.json")
        return False
    except json.JSONDecodeError as e:
        print(f"\n[ERROR] JSONの解析エラー: {str(e)}")
        return False
    
    print(f"\n[INFO] ブラウザリクエスト情報を読み込みました: {browser_request_file}")
    
    # ブラウザのリクエスト情報を取得
    request_info = browser_data.get("request_info", {})
    actual_url = request_info.get("url", "")
    actual_method = request_info.get("method", "GET")
    actual_headers = request_info.get("request_headers", {})
    actual_cookies = request_info.get("cookies", [])
    redirects = request_info.get("redirects", [])
    
    print(f"\n[ブラウザのリクエスト情報]")
    print("-" * 80)
    print(f"URL: {actual_url}")
    print(f"Method: {actual_method}")
    if redirects:
        print(f"リダイレクトチェーン: {len(redirects)}回")
        for i, url in enumerate(redirects, 1):
            print(f"  {i}. {url[:100]}...")
    else:
        print("リダイレクト: なし")
    
    # コードで生成しているリクエスト情報をシミュレート
    print(f"\n[コードで生成するリクエスト情報]")
    print("-" * 80)
    
    # コードで使用しているヘッダー（最新の実装）
    code_headers = {
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    
    # RefererとOriginを追加
    page_url = request_info.get("referer") or browser_data.get("page_url", "")
    if page_url:
        from urllib.parse import urlparse
        parsed_referer = urlparse(page_url)
        code_headers["Referer"] = page_url
        origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
        code_headers["Origin"] = origin
        code_headers["Sec-Fetch-Site"] = "same-site" if parsed_referer.netloc.endswith(".i-ppi.jp") else "cross-site"
        code_headers["Sec-Fetch-Mode"] = "navigate"
        code_headers["Sec-Fetch-Dest"] = "document"
        code_headers["Sec-Fetch-User"] = "?1"
        print(f"Referer: {page_url}")
    
    print(f"URL: {actual_url} (ブラウザと同じURLを使用)")
    print(f"Method: GET")
    print(f"Headers:")
    for key, value in code_headers.items():
        print(f"  {key}: {value}")
    
    # 比較
    print(f"\n[差異の分析]")
    print("-" * 80)
    
    differences = []
    
    # URLの比較
    code_url = actual_url  # コードでも同じURLを使用する想定
    if code_url != actual_url:
        differences.append({
            "type": "URL",
            "browser": actual_url,
            "code": code_url,
            "recommendation": "URLをブラウザと同じに修正する必要があります"
        })
    
    # ヘッダーの比較
    missing_headers = {}
    different_headers = {}
    
    for key, browser_value in actual_headers.items():
        key_lower = key.lower()
        code_value = None
        
        # コードのヘッダーを検索（大文字小文字を無視）
        for code_key, code_val in code_headers.items():
            if code_key.lower() == key_lower:
                code_value = code_val
                break
        
        if code_value is None:
            # コードに存在しないヘッダー
            missing_headers[key] = browser_value
        elif str(code_value) != str(browser_value):
            # 値が異なるヘッダー
            different_headers[key] = {
                "browser": browser_value,
                "code": code_value
            }
    
    if missing_headers:
        differences.append({
            "type": "Missing Headers",
            "headers": missing_headers,
            "recommendation": "不足しているヘッダーを追加する必要があります"
        })
    
    if different_headers:
        differences.append({
            "type": "Different Header Values",
            "headers": different_headers,
            "recommendation": "ヘッダーの値をブラウザと同じに修正する必要があります"
        })
    
    # Cookieの比較
    code_cookie_domains = set()  # コードで使用しているCookieのドメイン（実際の実装では取得が必要）
    
    missing_cookies = []
    for browser_cookie in actual_cookies:
        cookie_name = browser_cookie.get("name", "")
        cookie_domain = browser_cookie.get("domain", "")
        
        # 重要なCookieかチェック
        if cookie_name in ["ASP.NET_SessionId", "ApplicationGatewayAffinity", "ApplicationGatewayAffinityCORS"]:
            if cookie_domain not in code_cookie_domains:
                missing_cookies.append(browser_cookie)
    
    if missing_cookies:
        differences.append({
            "type": "Missing Cookies",
            "cookies": missing_cookies,
            "recommendation": "不足しているCookieを追加する必要があります。ただし、別ドメインのCookieはSame-Origin Policyにより送信されません。"
        })
    
    # リダイレクトの確認
    if redirects and len(redirects) > 1:
        differences.append({
            "type": "Redirect Chain",
            "redirects": redirects,
            "recommendation": "リダイレクトチェーンを経由する必要があります。中継URLを経由してダウンロードすることを検討してください。"
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
                for key, value in diff['headers'].items():
                    value_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    print(f"     {key}: {value_str}")
            elif diff['type'] == 'Different Header Values':
                print(f"   値が異なるヘッダー:")
                for key, values in diff['headers'].items():
                    print(f"     {key}:")
                    print(f"       ブラウザ: {values['browser']}")
                    print(f"       コード: {values['code']}")
            elif diff['type'] == 'Missing Cookies':
                print(f"   不足しているCookie（重要）:")
                for cookie in diff['cookies']:
                    print(f"     {cookie.get('name')} (domain: {cookie.get('domain')}, path: {cookie.get('path')})")
            elif diff['type'] == 'Redirect Chain':
                print(f"   リダイレクトチェーン:")
                for j, url in enumerate(diff['redirects'], 1):
                    print(f"     {j}. {url}")
            
            print(f"   推奨: {diff['recommendation']}")
            print()
    else:
        print("✅ 差異は見つかりませんでした。")
        print("タイムアウトの原因は他の要因（ネットワーク、ファイアウォール、サーバー側の制限等）の可能性があります。")
    
    # 修正提案を生成
    if differences:
        print("\n[修正提案]")
        print("-" * 80)
        print("以下の修正を推奨します：\n")
        
        # 修正コードを生成
        print("1. HTTPClientのdownload_fileメソッドを修正:")
        print("```python")
        print("def download_file(self, url, save_path, progress_callback=None, max_retries=3, referer=None):")
        print("    # ブラウザと同じヘッダーを設定")
        print("    download_headers = {")
        
        # ブラウザのヘッダーを追加（自動設定されるものを除く）
        exclude_headers = {'host', 'content-length', 'content-type', 'connection'}
        for key, value in actual_headers.items():
            if key.lower() not in exclude_headers:
                value_escaped = str(value).replace('"', '\\"').replace('\n', '\\n')
                if len(value_escaped) > 100:
                    value_escaped = value_escaped[:100] + "..."
                print(f'        "{key}": "{value_escaped}",')
        
        print("    }")
        print("    # ... 以下、既存のコード")
        print("```")
    
    # 結果を保存
    output_file = Path("docs/dev/request_analysis_result.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    analysis_result = {
        "timestamp": datetime.now().isoformat(),
        "browser_request": browser_data.get("request_info", {}),
        "code_request": {
            "url": code_url,
            "headers": code_headers
        },
        "differences": differences,
        "recommendations": [diff.get("recommendation", "") for diff in differences]
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(analysis_result, f, ensure_ascii=False, indent=2)
    
    print(f"\n分析結果を保存: {output_file}")
    
    return len(differences) == 0


if __name__ == "__main__":
    print("ブラウザリクエスト分析ツール")
    print()
    print("使用方法:")
    print("  1. ブラウザの開発者ツールでリクエスト情報を取得")
    print("  2. browser_request_template.jsonに情報を記入")
    print("  3. このスクリプトで分析:")
    print("     python scripts/dev/analyze_captured_request.py docs/dev/browser_request_template.json")
    print()
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file = input("調査結果ファイルのパスを入力してください: ").strip()
    
    if not input_file:
        print("ファイルパスが指定されていません。")
        sys.exit(1)
    
    success = analyze_captured_request(input_file)
    sys.exit(0 if success else 1)
