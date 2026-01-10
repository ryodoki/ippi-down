"""ブラウザのネットワークリクエストを自動的に記録するスクリプト

Seleniumを使用してブラウザを自動操作し、開発者ツールのネットワークタブの
情報を記録します。
"""

import sys
from pathlib import Path
import json
from datetime import datetime
from typing import Dict, List, Any
import time

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service as EdgeService
    try:
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
        CHROME_AVAILABLE = True
    except ImportError:
        CHROME_AVAILABLE = False
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    CHROME_AVAILABLE = False


def capture_browser_network_requests():
    """ブラウザのネットワークリクエストを自動的に記録"""
    print("=" * 80)
    print("ブラウザのネットワークリクエスト記録スクリプト")
    print("=" * 80)
    
    if not SELENIUM_AVAILABLE:
        print("\n[ERROR] Seleniumがインストールされていません。")
        print("以下のコマンドでインストールしてください:")
        print("  pip install selenium")
        print("\nまたは、手動でブラウザの開発者ツールを使用してください。")
        print("手順書: docs/dev/BROWSER_MANUAL_INVESTIGATION.md")
        return False
    
    print("\nこのスクリプトは以下を実行します：")
    print("  1. Edgeブラウザを起動（Chromeはフォールバック）")
    print("  2. 検索ページにアクセス")
    print("  3. 検索を実行")
    print("  4. 詳細ページを開く")
    print("  5. ファイルをダウンロード（リンクをクリック）")
    print("  6. ネットワークリクエストを記録")
    print()
    
    try:
        driver = None
        browser_type = None
        
        # Edgeを優先して起動
        try:
            print("[INFO] Edgeブラウザを起動中...")
            edge_options = EdgeOptions()
            edge_options.add_argument("--enable-logging")
            edge_options.add_argument("--v=1")
            # Edgeの場合、ログ設定が異なる可能性がある
            try:
                edge_options.set_capability('ms:loggingPrefs', {'performance': 'ALL'})
            except Exception:
                # Edgeの新しいバージョンでは設定方法が異なる可能性
                pass
            # ヘッドレスモードを無効化（実際のブラウザを表示）
            # edge_options.add_argument("--headless")  # コメントアウト: 実際の動作を確認
            
            driver = webdriver.Edge(options=edge_options)
            print("  [SUCCESS] Edgeブラウザを起動しました")
            browser_type = "Edge"
        except Exception as e:
            print(f"  [WARNING] Edgeブラウザの起動に失敗: {str(e)}")
            driver = None
            
            # Chromeにフォールバック
            if CHROME_AVAILABLE:
                try:
                    print("[INFO] Chromeブラウザを起動中...（フォールバック）")
                    chrome_options = ChromeOptions()
                    chrome_options.add_argument("--enable-logging")
                    chrome_options.add_argument("--v=1")
                    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
                    
                    driver = webdriver.Chrome(options=chrome_options)
                    print("  [SUCCESS] Chromeブラウザを起動しました")
                    browser_type = "Chrome"
                except Exception as e2:
                    print(f"  [ERROR] Chromeブラウザの起動にも失敗: {str(e2)}")
                    raise Exception("ブラウザを起動できませんでした。EdgeまたはChromeがインストールされているか確認してください。")
            else:
                raise Exception("Edgeの起動に失敗し、Chromeも利用できません。")
        
        if driver is None or browser_type is None:
            raise Exception("ブラウザを起動できませんでした。")
        
        try:
            # ステップ1: 検索ページにアクセス
            print("\n[ステップ1] 検索ページにアクセス")
            print("-" * 80)
            search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
            driver.get(search_url)
            print(f"  URL: {search_url}")
            
            # ページが読み込まれるまで待機
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "drpTopKikanInf"))
            )
            print("  [SUCCESS] 検索ページを読み込みました")
            
            # ステップ2: 検索条件を設定
            print("\n[ステップ2] 検索条件を設定")
            print("-" * 80)
            
            # 発注機関を選択
            try:
                daibunrui_dropdown = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "drpTopKikanInf"))
                )
                from selenium.webdriver.support.ui import Select
                select = Select(daibunrui_dropdown)
                select.select_by_visible_text("国の機関")
                print("  発注機関: 国の機関を選択")
                # 選択後の待機（ページが更新されるまで）
                import time
                time.sleep(2)
            except Exception as e:
                print(f"  [WARNING] 発注機関の選択に失敗: {str(e)}")
                print("  手動で選択してください。")
                try:
                    _ = input("  検索条件を設定したら、Enterキーを押してください...")
                except EOFError:
                    print("  [INFO] 非対話的環境のため、自動的に次のステップに進みます...")
                    time.sleep(5)  # 手動操作の時間を与える
            
            # 検索ボタンをクリック
            try:
                search_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "btnSearch"))
                )
                # ボタンが表示されるまでスクロール
                driver.execute_script("arguments[0].scrollIntoView(true);", search_button)
                time.sleep(1)
                # JavaScriptでクリック（より確実）
                driver.execute_script("arguments[0].click();", search_button)
                print("  検索ボタンをクリックしました")
            except Exception as e:
                print(f"  [WARNING] 検索ボタンのクリックに失敗: {str(e)}")
                print("  手動で検索を実行してください。")
                try:
                    _ = input("  検索を実行したら、Enterキーを押してください...")
                except EOFError:
                    print("  [INFO] 非対話的環境のため、自動的に次のステップに進みます...")
                    time.sleep(5)
            
            # 検索結果が表示されるまで待機
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.ID, "dgrSearchList"))
                )
                print("  [SUCCESS] 検索結果が表示されました")
                time.sleep(2)  # ページの完全な読み込みを待つ
            except Exception:
                print("  [INFO] 検索結果のテーブルが見つかりませんでした")
                try:
                    _ = input("  検索結果が表示されたら、Enterキーを押してください...")
                except EOFError:
                    print("  [INFO] 非対話的環境のため、自動的に次のステップに進みます...")
                    time.sleep(5)
            
            # ステップ3: 詳細ページを開く
            print("\n[ステップ3] 詳細ページを開く")
            print("-" * 80)
            
            # ネットワークログの記録を開始
            print("  ネットワークログの記録を開始しました")
            
            # 最初の案件の詳細リンクをクリック
            try:
                # 複数の方法でリンクを探す
                first_link = None
                
                # 方法1: __doPostBackを含むリンクを探す（ソートリンクを除外）
                try:
                    links = driver.find_elements(By.XPATH, "//table[@id='dgrSearchList']//a[contains(@href, '__doPostBack')]")
                    # ソートリンク（'Sort$'を含む）を除外
                    for link in links:
                        href = link.get_attribute("href") or ""
                        if "__doPostBack" in href and "Sort$" not in href:
                            first_link = link
                            break
                except Exception:
                    pass
                
                # 方法2: 工事名のリンクを探す
                if not first_link:
                    try:
                        first_link = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, "//table[@id='dgrSearchList']//tr[2]//a[contains(@href, '__doPostBack') and not(contains(@href, 'Sort$'))]"))
                        )
                    except Exception:
                        pass
                
                if first_link:
                    # リンクが表示されるまでスクロール
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", first_link)
                    time.sleep(1)
                    
                    # より確実なクリック方法を試す
                    try:
                        # まず通常のクリックを試す
                        first_link.click()
                    except Exception:
                        # JavaScriptでクリック
                        driver.execute_script("arguments[0].click();", first_link)
                    
                    print("  詳細ページへのリンクをクリックしました")
                    
                    # 詳細ページが読み込まれるまで待機
                    WebDriverWait(driver, 15).until(
                        lambda d: "List_Detail" in d.current_url or "List.aspx" in d.current_url or d.current_url != search_url
                    )
                    print(f"  [SUCCESS] 詳細ページを開きました: {driver.current_url}")
                    time.sleep(2)  # ページの完全な読み込みを待つ
                else:
                    raise Exception("詳細ページへのリンクが見つかりませんでした")
            except Exception as e:
                print(f"  [WARNING] 詳細ページの自動操作に失敗: {str(e)}")
                print("  手動で詳細ページを開いてください。")
                try:
                    _ = input("  詳細ページを開いたら、Enterキーを押してください...")
                except EOFError:
                    print("  [INFO] 非対話的環境のため、自動的に次のステップに進みます...")
                    time.sleep(5)
            
            # ステップ4: ファイルダウンロードリンクをクリック
            print("\n[ステップ4] ファイルダウンロードリンクをクリック")
            print("-" * 80)
            print("  ネットワークタブでリクエストを記録しています...")
            print("  ファイルダウンロードリンクをクリックしてください。")
            print("  （手動操作の場合は、クリックしたら Enterキーを押してください）")
            
            # ダウンロードリンクを探す
            download_link_clicked = False
            try:
                # 複数の方法でダウンロードリンクを探す
                download_link = None
                
                # 方法1: KokaiBunshoServletを含むリンクを探す
                try:
                    download_link = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'KokaiBunshoServlet')]"))
                    )
                except Exception:
                    # 方法2: dgrKokokuまたはdgrKeikaテーブル内のリンクを探す
                    try:
                        download_link = driver.find_element(By.XPATH, "//table[@id='dgrKokoku']//a[contains(@href, 'KokaiBunshoServlet')] | //table[@id='dgrKeika']//a[contains(@href, 'KokaiBunshoServlet')]")
                    except Exception:
                        pass
                
                if download_link:
                    print("  ダウンロードリンクを発見しました")
                    href = download_link.get_attribute("href")
                    print(f"    リンクURL: {href}")
                    
                    # リンクが表示されるまでスクロール
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", download_link)
                    time.sleep(2)
                    
                    print("  3秒後に自動的にクリックします...")
                    time.sleep(3)
                    
                    # より確実なクリック方法を試す
                    try:
                        # まず要素がクリック可能になるまで待つ
                        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(download_link))
                        download_link.click()
                        print("  通常のクリックで成功")
                    except Exception as e1:
                        print(f"  通常のクリックに失敗: {str(e1)}")
                        try:
                            # JavaScriptでクリック
                            driver.execute_script("arguments[0].click();", download_link)
                            print("  JavaScriptクリックで成功")
                        except Exception as e2:
                            print(f"  JavaScriptクリックにも失敗: {str(e2)}")
                            # URLを直接取得して新しいタブで開く
                            if href:
                                print(f"  新しいタブでURLを開きます: {href}")
                                driver.execute_script(f"window.open('{href}', '_blank');")
                    
                    download_link_clicked = True
                    
                    # ダウンロードが開始されるまで待機（リクエストが記録されるまで十分な時間を確保）
                    window_count_before = len(driver.window_handles)
                    print(f"  現在のウィンドウ数: {window_count_before}")
                    print("  ダウンロードリクエストが記録されるまで15秒待機します...")
                    time.sleep(15)
                    
                    # 追加で、新しいタブが開かれた場合のために待機
                    window_count_after = len(driver.window_handles)
                    if window_count_after > window_count_before:
                        print(f"  新しいタブが開かれました（合計{window_count_after}個のウィンドウ）")
                        # すべてのウィンドウを確認
                        original_window = driver.current_window_handle
                        for window_handle in driver.window_handles:
                            if window_handle != original_window:
                                driver.switch_to.window(window_handle)
                                print(f"    タブのURL: {driver.current_url}")
                                time.sleep(3)  # 新しいタブのリクエストが記録されるまで待機
                        driver.switch_to.window(original_window)
                else:
                    raise Exception("ダウンロードリンクが見つかりませんでした")
            except Exception as e:
                print(f"  ダウンロードリンクの自動操作に失敗: {str(e)}")
                print("  手動でダウンロードリンクをクリックしてください。")
                if not download_link_clicked:
                    try:
                        _ = input("  ダウンロードリンクをクリックしたら、Enterキーを押してください...")
                    except EOFError:
                        print("  [INFO] 非対話的環境のため、自動的に次のステップに進みます...")
                        time.sleep(10)  # 手動操作の時間を与える
            
            # ステップ5: ネットワークログを取得
            print("\n[ステップ5] ネットワークログを取得")
            print("-" * 80)
            
            # パフォーマンスログを取得（EdgeとChromeでログタイプが異なる可能性がある）
            logs = []
            try:
                if browser_type == "Edge":
                    # Edgeの場合、ログタイプが異なる可能性がある
                    try:
                        # Edgeでもperformanceログを試す
                        logs = driver.get_log('performance')
                        print(f"  [INFO] Edgeのperformanceログを取得: {len(logs)}件")
                    except Exception as e1:
                        print(f"  [WARNING] Edgeのperformanceログを取得できませんでした: {str(e1)}")
                        try:
                            # browserログを試す
                            logs = driver.get_log('browser')
                            print(f"  [INFO] Edgeのbrowserログを取得: {len(logs)}件")
                        except Exception as e2:
                            print(f"  [WARNING] Edgeのbrowserログも取得できませんでした: {str(e2)}")
                            print("  ブラウザの開発者ツール（F12）から手動で情報を取得してください。")
                            logs = []
                else:
                    # Chromeの場合
                    logs = driver.get_log('performance')
                    print(f"  [INFO] Chromeのperformanceログを取得: {len(logs)}件")
            except Exception as e:
                print(f"  [WARNING] パフォーマンスログを取得できませんでした: {str(e)}")
                print("  ブラウザの開発者ツール（F12）から手動で情報を取得してください。")
                logs = []
            print(f"  取得したログ数: {len(logs)}")
            
            # PDFファイルのリクエストを探す
            pdf_requests = []
            all_network_requests = []
            
            for log in logs:
                try:
                    log_message = json.loads(log['message'])
                    message = log_message.get('message', {})
                    method = message.get('method', '')
                    
                    # Network.responseReceived または Network.requestWillBeSent を探す
                    if method in ['Network.responseReceived', 'Network.requestWillBeSent', 'Network.loadingFinished']:
                        params = message.get('params', {})
                        request = params.get('request', {})
                        response = params.get('response', {})
                        
                        url = request.get('url', '') or response.get('url', '')
                        
                        # すべてのネットワークリクエストを記録（デバッグ用）
                        if url:
                            all_network_requests.append({
                                'timestamp': log['timestamp'],
                                'method': method,
                                'url': url[:200],  # URLが長い場合に備えて切り詰め
                                'mimeType': response.get('mimeType', '') if response else '',
                                'status': response.get('status', None) if response else None,
                            })
                        
                        # PDFファイル関連のリクエストを特定
                        is_pdf_request = False
                        
                        # 方法1: URLに特定のキーワードが含まれているか
                        url_lower = url.lower()
                        pdf_keywords = [
                            'kokaiBunshoServlet',
                            'kokaiBunshoServlet'.lower(),
                            'publish',
                            'download',
                            '.pdf',
                            'e-bisc.go.jp',
                            'e2ppiw01',
                            'servlet'
                        ]
                        if any(keyword in url_lower for keyword in pdf_keywords):
                            is_pdf_request = True
                        
                        # 方法2: MIMEタイプがPDFまたはバイナリか
                        if response:
                            mime_type = response.get('mimeType', '').lower()
                            if 'pdf' in mime_type or 'application/octet-stream' in mime_type or 'binary' in mime_type:
                                is_pdf_request = True
                        
                        # 方法3: レスポンスヘッダーからContent-Typeを確認
                        if response:
                            response_headers = response.get('headers', {})
                            if isinstance(response_headers, dict):
                                content_type = response_headers.get('content-type', '').lower()
                                if 'pdf' in content_type or 'application/octet-stream' in content_type:
                                    is_pdf_request = True
                            elif isinstance(response_headers, list):
                                # ヘッダーがリスト形式の場合
                                for header in response_headers:
                                    if isinstance(header, dict) and header.get('name', '').lower() == 'content-type':
                                        content_type_value = header.get('value', '').lower()
                                        if 'pdf' in content_type_value:
                                            is_pdf_request = True
                        
                        # 方法4: リクエストタイプがDocumentまたはXHRで、URLに特定のパターンがある
                        request_type = params.get('type', '')
                        if request_type in ['Document', 'XHR', 'Fetch'] and 'servlet' in url_lower:
                            is_pdf_request = True
                        
                        if is_pdf_request:
                            pdf_requests.append({
                                'timestamp': log['timestamp'],
                                'method': method,
                                'url': url,
                                'request_headers': request.get('headers', {}) if request else {},
                                'response_headers': response.get('headers', {}) if response else {},
                                'status': response.get('status', None) if response else None,
                                'mimeType': response.get('mimeType', '') if response else '',
                                'redirectResponse': response.get('redirectResponse', None) if response else None,
                            })
                except Exception as e:
                    # ログの解析エラーは無視（一部のログが不正な形式の可能性）
                    continue
            
            # デバッグ: すべてのネットワークリクエストを表示
            if all_network_requests:
                print(f"  取得したネットワークリクエスト: {len(all_network_requests)}件")
                
                # PDF関連の可能性があるリクエストを探す
                potential_pdf_requests = []
                for req in all_network_requests:
                    url_lower = req['url'].lower()
                    if any(keyword in url_lower for keyword in ['servlet', 'publish', 'download', 'e-bisc', 'e2ppiw01']):
                        potential_pdf_requests.append(req)
                
                if potential_pdf_requests:
                    print(f"  PDF関連の可能性があるリクエスト: {len(potential_pdf_requests)}件")
                    for req in potential_pdf_requests[:10]:  # 最初の10件のみ
                        url_short = req['url'][:100] + "..." if len(req['url']) > 100 else req['url']
                        print(f"    - {req['method']}: {url_short}")
                        print(f"      MimeType: {req['mimeType']}, Status: {req['status']}")
                
                # PDFリクエストが見つからない場合、すべてのリクエストを表示
                if len(pdf_requests) == 0:
                    print(f"\n  [DEBUG] ネットワークリクエスト（最初の30件、PDFリクエストが見つからないため）:")
                    for i, req in enumerate(all_network_requests[:30], 1):
                        url_short = req['url'][:80] + "..." if len(req['url']) > 80 else req['url']
                        print(f"    {i}. {req['method']}: {url_short[:100]}")
                        if req['mimeType']:
                            print(f"       MimeType: {req['mimeType']}")
                        if req['status']:
                            print(f"       Status: {req['status']}")
            
            print(f"  PDFファイル関連のリクエスト: {len(pdf_requests)}件")
            
            # ステップ6: 結果を保存
            print("\n[ステップ6] 結果を保存")
            print("-" * 80)
            
            if pdf_requests:
                # 最新のリクエストを詳細に記録
                latest_request = pdf_requests[-1]
                
                result = {
                    "timestamp": datetime.now().isoformat(),
                    "browser_type": browser_type,
                    "current_url": driver.current_url,
                    "pdf_requests": pdf_requests,
                    "latest_request": latest_request,
                    "all_logs_count": len(logs),
                }
                
                output_file = Path("docs/dev/browser_network_capture.json")
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                
                print(f"  [SUCCESS] 結果を保存しました: {output_file}")
                
                # 最新のリクエスト情報を表示
                print(f"\n  最新のリクエスト情報:")
                print(f"    URL: {latest_request['url']}")
                print(f"    Status: {latest_request['status']}")
                print(f"    MimeType: {latest_request['mimeType']}")
                print(f"    リクエストヘッダー:")
                for key, value in latest_request['request_headers'].items():
                    print(f"      {key}: {value[:100]}..." if len(str(value)) > 100 else f"      {key}: {value}")
            else:
                print("  [WARNING] PDFファイル関連のリクエストが見つかりませんでした")
                print("  手動でブラウザの開発者ツールから情報を取得してください。")
                
                # すべてのログを保存（デバッグ用）
                all_logs_file = Path("docs/dev/browser_all_logs.json")
                with open(all_logs_file, "w", encoding="utf-8") as f:
                    json.dump(logs[:100], f, ensure_ascii=False, indent=2)  # 最初の100件のみ
                print(f"  すべてのログ（最初の100件）を保存しました: {all_logs_file}")
            
            print("\n[INFO] ブラウザを閉じる前に、開発者ツールで確認してください。")
            print("  ブラウザは30秒後に自動的に閉じます（またはEnterキーで即座に閉じます）")
            try:
                import sys
                import select
                if sys.platform == "win32":
                    # Windowsの場合、mswsvcを使用（インストールされていない場合はタイムアウト）
                    import time
                    start_time = time.time()
                    timeout = 30
                    while time.time() - start_time < timeout:
                        try:
                            # Windowsでは、キー入力を待つ代わりにタイムアウト
                            if sys.stdin.isatty():
                                import msvcrt
                                if msvcrt.kbhit():
                                    msvcrt.getch()
                                    break
                            time.sleep(0.5)
                        except Exception:
                            time.sleep(0.5)
                else:
                    import select
                    if select.select([sys.stdin], [], [], 30)[0]:
                        _ = input()
            except Exception:
                # 非対話的環境の場合、30秒待機
                import time
                print("  30秒待機します...")
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
    success = capture_browser_network_requests()
    sys.exit(0 if success else 1)
