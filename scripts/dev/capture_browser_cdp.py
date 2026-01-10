"""Chrome DevTools Protocol (CDP) を使用してネットワークリクエストを記録するスクリプト

CDPを使用することで、より確実にネットワークリクエストを記録できます。
EdgeとChromeの両方で動作します。
"""

import sys
from pathlib import Path
import json
from datetime import datetime
import time
from typing import Dict, List, Any

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.edge.options import Options as EdgeOptions
    try:
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        CHROME_AVAILABLE = True
    except ImportError:
        CHROME_AVAILABLE = False
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    CHROME_AVAILABLE = False


def capture_browser_network_requests_cdp():
    """CDPを使用してブラウザのネットワークリクエストを記録"""
    print("=" * 80)
    print("CDPを使用したネットワークリクエスト記録スクリプト")
    print("=" * 80)
    
    if not SELENIUM_AVAILABLE:
        print("\n[ERROR] Seleniumがインストールされていません。")
        print("以下のコマンドでインストールしてください:")
        print("  pip install selenium")
        return False
    
    print("\nこのスクリプトは以下を実行します：")
    print("  1. Edgeブラウザを起動（Chromeはフォールバック）")
    print("  2. CDPを使用してネットワークログを記録")
    print("  3. 検索ページにアクセス")
    print("  4. 検索を実行")
    print("  5. 詳細ページを開く")
    print("  6. ファイルをダウンロード（リンクをクリック）")
    print("  7. ネットワークリクエストを記録")
    print()
    
    # ネットワークリクエストを保存するリスト
    network_requests = []
    network_responses = []
    
    def log_network_request(params):
        """ネットワークリクエストを記録"""
        try:
            request = params.get('request', {})
            url = request.get('url', '')
            method = request.get('method', 'GET')
            headers = request.get('headers', {})
            
            network_requests.append({
                'timestamp': datetime.now().isoformat(),
                'url': url,
                'method': method,
                'headers': headers,
                'type': params.get('type', ''),
                'requestId': params.get('requestId', ''),
            })
            
            # PDF関連のリクエストを特定
            url_lower = url.lower()
            if any(keyword in url_lower for keyword in ['kokaiBunshoServlet', 'publish', 'download', '.pdf', 'e-bisc', 'e2ppiw01']):
                print(f"  [PDF関連リクエスト発見] {method} {url[:100]}...")
        except Exception as e:
            pass  # エラーは無視
    
    def log_network_response(params):
        """ネットワークレスポンスを記録"""
        try:
            response = params.get('response', {})
            url = response.get('url', '')
            status = response.get('status', None)
            headers = response.get('headers', {})
            mime_type = response.get('mimeType', '')
            request_id = params.get('requestId', '')
            
            network_responses.append({
                'timestamp': datetime.now().isoformat(),
                'url': url,
                'status': status,
                'headers': headers,
                'mimeType': mime_type,
                'requestId': request_id,
            })
            
            # PDF関連のレスポンスを特定
            if 'pdf' in mime_type.lower() or 'application/octet-stream' in mime_type.lower():
                print(f"  [PDF関連レスポンス発見] Status: {status}, URL: {url[:100]}...")
                print(f"    MimeType: {mime_type}")
        except Exception as e:
            pass  # エラーは無視
    
    try:
        driver = None
        browser_type = None
        
        # Edgeを優先して起動
        try:
            print("[INFO] Edgeブラウザを起動中...")
            edge_options = EdgeOptions()
            edge_options.add_argument("--enable-logging")
            edge_options.add_argument("--v=1")
            
            driver = webdriver.Edge(options=edge_options)
            print("  [SUCCESS] Edgeブラウザを起動しました")
            browser_type = "Edge"
        except Exception as e:
            print(f"  [WARNING] Edgeブラウザの起動に失敗: {str(e)}")
            driver = None
            
            if CHROME_AVAILABLE:
                try:
                    print("[INFO] Chromeブラウザを起動中...（フォールバック）")
                    chrome_options = ChromeOptions()
                    chrome_options.add_argument("--enable-logging")
                    chrome_options.add_argument("--v=1")
                    
                    driver = webdriver.Chrome(options=chrome_options)
                    print("  [SUCCESS] Chromeブラウザを起動しました")
                    browser_type = "Chrome"
                except Exception as e2:
                    print(f"  [ERROR] Chromeブラウザの起動にも失敗: {str(e2)}")
                    raise Exception("ブラウザを起動できませんでした。")
            else:
                raise Exception("Edgeの起動に失敗し、Chromeも利用できません。")
        
        if driver is None or browser_type is None:
            raise Exception("ブラウザを起動できませんでした。")
        
        try:
            # CDPを使用してネットワークログを有効化
            print("\n[INFO] CDPを使用してネットワークログを有効化中...")
            try:
                # Network.enableでネットワークログを有効化
                driver.execute_cdp_cmd('Network.enable', {})
                print("  [SUCCESS] ネットワークログを有効化しました")
            except Exception as e:
                print(f"  [WARNING] CDPのNetwork.enableに失敗: {str(e)}")
                print("  パフォーマンスログを使用します...")
            
            # ステップ1: 検索ページにアクセス
            print("\n[ステップ1] 検索ページにアクセス")
            print("-" * 80)
            search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
            driver.get(search_url)
            print(f"  URL: {search_url}")
            time.sleep(3)  # ページの完全な読み込みを待つ
            
            # ステップ2: 検索を実行
            print("\n[ステップ2] 検索を実行")
            print("-" * 80)
            print("  手動で検索を実行してください（発注機関 = '国の機関'）")
            print("  検索が完了したら、Enterキーを押してください...")
            
            try:
                _ = input()
            except EOFError:
                print("  [INFO] 非対話的環境のため、30秒待機します...")
                time.sleep(30)
            
            # ステップ3: 詳細ページを開く
            print("\n[ステップ3] 詳細ページを開く")
            print("-" * 80)
            print("  検索結果から詳細ページを開いてください")
            print("  詳細ページが開いたら、Enterキーを押してください...")
            
            try:
                _ = input()
            except EOFError:
                print("  [INFO] 非対話的環境のため、30秒待機します...")
                time.sleep(30)
            
            # ステップ4: ファイルダウンロードリンクをクリック
            print("\n[ステップ4] ファイルダウンロードリンクをクリック")
            print("-" * 80)
            print("  ファイルダウンロードリンクをクリックしてください")
            print("  ダウンロードが開始されたら、Enterキーを押してください...")
            
            try:
                _ = input()
            except EOFError:
                print("  [INFO] 非対話的環境のため、30秒待機します...")
                time.sleep(30)
            
            # ステップ5: ネットワークリクエストを収集
            print("\n[ステップ5] ネットワークリクエストを収集")
            print("-" * 80)
            
            # CDPからログを取得（可能な場合）
            try:
                # パフォーマンスログも取得
                logs = driver.get_log('performance')
                print(f"  パフォーマンスログ: {len(logs)}件")
                
                # ログからネットワークリクエストを抽出
                for log in logs:
                    try:
                        log_message = json.loads(log['message'])
                        message = log_message.get('message', {})
                        method = message.get('method', '')
                        params = message.get('params', {})
                        
                        if method == 'Network.requestWillBeSent':
                            log_network_request(params)
                        elif method == 'Network.responseReceived':
                            log_network_response(params)
                    except Exception:
                        continue
            except Exception as e:
                print(f"  [WARNING] ログの取得に失敗: {str(e)}")
            
            # 結果を表示
            print(f"\n  記録したネットワークリクエスト: {len(network_requests)}件")
            print(f"  記録したネットワークレスポンス: {len(network_responses)}件")
            
            # PDF関連のリクエストを特定
            pdf_requests = []
            for req in network_requests:
                url_lower = req['url'].lower()
                if any(keyword in url_lower for keyword in ['kokaiBunshoServlet', 'publish', 'download', '.pdf', 'e-bisc', 'e2ppiw01']):
                    pdf_requests.append(req)
            
            # レスポンスからも探す
            for resp in network_responses:
                url_lower = resp['url'].lower()
                mime_type = resp['mimeType'].lower()
                if any(keyword in url_lower for keyword in ['kokaiBunshoServlet', 'publish', 'download', '.pdf', 'e-bisc', 'e2ppiw01']) or 'pdf' in mime_type:
                    # 対応するリクエストを探す
                    matching_request = next((r for r in network_requests if r['requestId'] == resp['requestId']), None)
                    if matching_request and matching_request not in pdf_requests:
                        pdf_requests.append(matching_request)
            
            if pdf_requests:
                print(f"\n  [SUCCESS] PDF関連のリクエスト: {len(pdf_requests)}件")
                for i, req in enumerate(pdf_requests, 1):
                    print(f"\n  {i}. {req['method']} {req['url']}")
                    print(f"      Headers: {json.dumps(req['headers'], ensure_ascii=False, indent=2)[:200]}...")
            else:
                print(f"\n  [WARNING] PDF関連のリクエストが見つかりませんでした")
                print(f"  すべてのネットワークリクエスト（最初の20件）:")
                for i, req in enumerate(network_requests[:20], 1):
                    url_short = req['url'][:80] + "..." if len(req['url']) > 80 else req['url']
                    print(f"    {i}. {req['method']} {url_short}")
            
            # 結果を保存
            print("\n[ステップ6] 結果を保存")
            print("-" * 80)
            
            result = {
                "timestamp": datetime.now().isoformat(),
                "browser_type": browser_type,
                "current_url": driver.current_url,
                "network_requests": network_requests,
                "network_responses": network_responses,
                "pdf_requests": pdf_requests,
            }
            
            output_file = Path("docs/dev/browser_network_cdp_capture.json")
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            print(f"  [SUCCESS] 結果を保存しました: {output_file}")
            
            print("\n[INFO] ブラウザを閉じる前に、開発者ツールで確認してください。")
            print("  ブラウザは30秒後に自動的に閉じます（またはEnterキーで即座に閉じます）")
            try:
                import sys
                import time
                start_time = time.time()
                timeout = 30
                while time.time() - start_time < timeout:
                    if sys.stdin.isatty():
                        try:
                            import msvcrt
                            if msvcrt.kbhit():
                                msvcrt.getch()
                                break
                        except Exception:
                            pass
                    time.sleep(0.5)
            except Exception:
                time.sleep(30)
            
            return True
            
        finally:
            driver.quit()
            print("\n[INFO] ブラウザを閉じました")
            
    except Exception as e:
        print(f"\n[ERROR] エラーが発生しました: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = capture_browser_network_requests_cdp()
    sys.exit(0 if success else 1)
