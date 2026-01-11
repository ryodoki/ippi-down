"""
Playwright環境確認スクリプト

Playwrightが実際に使用できる環境になっているか確認します。
"""

import sys
from pathlib import Path

def check_playwright_installation():
    """Playwrightのインストール状況を確認"""
    print("=== Playwright環境確認 ===")
    print()
    
    # 1. Pythonパッケージの確認
    print("1. Pythonパッケージの確認...")
    try:
        import playwright
        # バージョン情報の取得を試行
        try:
            import pkg_resources
            version = pkg_resources.get_distribution("playwright").version
            print(f"   [OK] playwright パッケージ: インストール済み (version: {version})")
        except:
            print("   [OK] playwright パッケージ: インストール済み")
    except ImportError:
        print("   [NG] playwright パッケージ: インストールされていません")
        print("     インストール方法: pip install playwright")
        return False
    
    # 2. Playwright APIのインポート確認
    print("2. Playwright APIのインポート確認...")
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
        print("   [OK] sync_playwright: インポート成功")
    except ImportError as e:
        print(f"   [NG] sync_playwright: インポート失敗 - {str(e)}")
        return False
    
    # 3. ブラウザのインストール確認
    print("3. ブラウザのインストール確認...")
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            # Chromiumの起動を試行
            try:
                browser = p.chromium.launch(headless=True)
                print("   [OK] Chromium: インストール済み、起動成功")
                browser.close()
            except Exception as e:
                print(f"   [NG] Chromium: 起動失敗 - {str(e)}")
                print("     インストール方法: playwright install chromium")
                return False
    except Exception as e:
        print(f"   [NG] ブラウザ確認エラー: {str(e)}")
        return False
    
    # 4. 実際のページアクセステスト
    print("4. 実際のページアクセステスト...")
    try:
        from playwright.sync_api import sync_playwright
        
        test_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # ページにアクセス
            response = page.goto(test_url, timeout=30000, wait_until="networkidle")
            
            if response and response.status == 200:
                print(f"   [OK] ページアクセス: 成功 (status: {response.status})")
                print(f"   [OK] ページタイトル: {page.title()[:50]}...")
                print(f"   [OK] ページサイズ: {len(page.content())} bytes")
            else:
                print(f"   [NG] ページアクセス: 失敗 (status: {response.status if response else 'None'})")
                browser.close()
                return False
            
            browser.close()
    except Exception as e:
        print(f"   [NG] ページアクセステスト: 失敗 - {str(e)}")
        return False
    
    # 5. 必要な機能の確認
    print("5. 必要な機能の確認...")
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # JavaScript実行の確認
            result = page.evaluate("1 + 1")
            if result == 2:
                print("   [OK] JavaScript実行: 可能")
            else:
                print(f"   [NG] JavaScript実行: 結果が期待と異なる ({result})")
                browser.close()
                return False
            
            # ネットワークリクエストの監視
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            page.goto("https://example.com", timeout=10000)
            if len(requests) > 0:
                print("   [OK] ネットワークリクエスト監視: 可能")
            else:
                print("   [WARN] ネットワークリクエスト監視: リクエストが記録されませんでした")
            
            browser.close()
    except Exception as e:
        print(f"   [NG] 機能確認: 失敗 - {str(e)}")
        return False
    
    print()
    print("=== 環境確認完了 ===")
    print("[OK] Playwrightは使用可能な状態です")
    return True


def check_missing_components():
    """不足しているコンポーネントを確認"""
    print()
    print("=== 不足コンポーネントの確認 ===")
    print()
    
    missing = []
    
    # Playwrightパッケージ
    try:
        import playwright
    except ImportError:
        missing.append({
            "component": "playwright Pythonパッケージ",
            "install_command": "pip install playwright",
            "description": "PlaywrightのPythonバインディング"
        })
    
    # ブラウザ
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as e:
        if "executable doesn't exist" in str(e) or "Browser not found" in str(e):
            missing.append({
                "component": "Chromiumブラウザ",
                "install_command": "playwright install chromium",
                "description": "Playwrightが使用するChromiumブラウザ"
            })
        else:
            missing.append({
                "component": "ブラウザ起動",
                "error": str(e),
                "description": "ブラウザの起動に失敗"
            })
    
    if missing:
        print("不足しているコンポーネント:")
        for i, item in enumerate(missing, 1):
            print(f"\n{i}. {item['component']}")
            print(f"   説明: {item.get('description', '不明')}")
            print(f"   インストールコマンド: {item.get('install_command', 'N/A')}")
            if 'error' in item:
                print(f"   エラー: {item['error']}")
        return missing
    else:
        print("[OK] すべてのコンポーネントが揃っています")
        return []


if __name__ == "__main__":
    success = check_playwright_installation()
    missing = check_missing_components()
    
    print()
    print("=== まとめ ===")
    if success and not missing:
        print("[OK] Playwrightは使用可能な状態です")
        sys.exit(0)
    else:
        print("[NG] Playwrightの環境に問題があります")
        if missing:
            print(f"\n不足しているコンポーネント: {len(missing)}件")
            print("\nインストール手順:")
            for item in missing:
                if 'install_command' in item:
                    print(f"  {item['install_command']}")
        sys.exit(1)
