"""実際のブラウザで中分類選択後の動作を詳細に調査するスクリプト（Playwright使用）"""

import sys
import io
from pathlib import Path
import json
import time

# WindowsのコンソールでUTF-8を正しく表示するための設定
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("警告: Playwrightがインストールされていません。")
    print("インストール方法: pip install playwright")
    print("その後: playwright install chromium")


def test_browser_simulation_detailed():
    """実際のブラウザで中分類選択後の動作を詳細に調査"""
    if not PLAYWRIGHT_AVAILABLE:
        print("Playwrightが利用できないため、このテストをスキップします")
        return
    
    print("="*80)
    print("実際のブラウザで中分類選択後の動作を詳細に調査")
    print("="*80)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    with sync_playwright() as p:
        # ブラウザを起動
        print("\n1. ブラウザを起動中...")
        browser = p.chromium.launch(headless=False)  # headless=Falseでブラウザを表示
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # ネットワークリクエストを記録
        network_requests = []
        network_responses = []
        
        def handle_request(request):
            if "Search.aspx" in request.url:
                network_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "headers": request.headers,
                    "post_data": request.post_data,
                })
        
        def handle_response(response):
            if "Search.aspx" in response.url:
                try:
                    network_responses.append({
                        "url": response.url,
                        "status": response.status,
                        "headers": dict(response.headers),
                    })
                except:
                    pass
        
        page.on("request", handle_request)
        page.on("response", handle_response)
        
        # ページに移動
        print(f"\n2. ページに移動中: {search_url}")
        page.goto(search_url, wait_until="networkidle")
        time.sleep(2)
        
        # 初期状態のHTMLを保存
        initial_html = page.content()
        with open("browser_initial_state.html", "w", encoding="utf-8") as f:
            f.write(initial_html)
        print("初期状態のHTMLを保存しました: browser_initial_state.html")
        
        # 大分類を選択
        print("\n3. 大分類を選択中...")
        page.select_option("select#drpTopKikanInf", "0")
        time.sleep(1)
        
        # 大分類選択後のHTMLを保存
        after_daibunrui_html = page.content()
        with open("browser_after_daibunrui.html", "w", encoding="utf-8") as f:
            f.write(after_daibunrui_html)
        print("大分類選択後のHTMLを保存しました: browser_after_daibunrui.html")
        
        # 中分類を選択
        print("\n4. 中分類を選択中...")
        page.select_option("select#drpLargeKikanInf2", "21")
        time.sleep(2)  # JavaScriptの実行を待つ
        
        # 中分類選択後のHTMLを保存
        after_chubunrui_html = page.content()
        with open("browser_after_chubunrui.html", "w", encoding="utf-8") as f:
            f.write(after_chubunrui_html)
        print("中分類選択後のHTMLを保存しました: browser_after_chubunrui.html")
        
        # 小分類のselect要素を確認
        print("\n5. 小分類のselect要素を確認...")
        try:
            select_element = page.query_selector("select#drpMiddleKikanInf")
            if select_element:
                options = select_element.query_selector_all("option")
                print(f"小分類の選択肢数: {len(options)}")
                print("\n小分類の選択肢:")
                for i, option in enumerate(options):
                    value = option.get_attribute("value")
                    text = option.inner_text()
                    selected = option.get_attribute("selected")
                    marker = "★" if "東北" in text else " "
                    print(f"  {marker} {i+1}. value='{value}', text='{text}', selected={selected}")
                    if "東北" in text:
                        print(f"      ★「東北地方整備局」を発見！")
        except Exception as e:
            print(f"エラー: {str(e)}")
        
        # JavaScriptの実行結果を確認
        print("\n6. JavaScriptの実行結果を確認...")
        try:
            # txtLargeKikanInf_hの値を取得
            txtLargeKikanInf_h = page.evaluate("""
                () => {
                    const input = document.getElementById('txtLargeKikanInf_h');
                    return input ? input.value : null;
                }
            """)
            if txtLargeKikanInf_h:
                print(f"txtLargeKikanInf_hの値: {txtLargeKikanInf_h[:200]}...")
            
            # 小分類のselect要素の選択肢をJavaScriptで取得
            shoubunrui_options = page.evaluate("""
                () => {
                    const select = document.getElementById('drpMiddleKikanInf');
                    if (!select) return [];
                    const options = [];
                    for (let i = 0; i < select.options.length; i++) {
                        options.push({
                            value: select.options[i].value,
                            text: select.options[i].text,
                            selected: select.options[i].selected
                        });
                    }
                    return options;
                }
            """)
            print(f"\nJavaScriptで取得した小分類の選択肢数: {len(shoubunrui_options)}")
            for opt in shoubunrui_options:
                marker = "★" if "東北" in opt["text"] else " "
                print(f"  {marker} value='{opt['value']}', text='{opt['text']}', selected={opt['selected']}")
        except Exception as e:
            print(f"エラー: {str(e)}")
        
        # コンソールメッセージを確認
        print("\n7. コンソールメッセージを確認...")
        console_messages = []
        
        def handle_console(msg):
            console_messages.append({
                "type": msg.type,
                "text": msg.text,
            })
        
        page.on("console", handle_console)
        
        # ネットワークリクエストを保存
        print("\n8. ネットワークリクエストを保存...")
        with open("browser_network_requests.json", "w", encoding="utf-8") as f:
            json.dump(network_requests, f, ensure_ascii=False, indent=2)
        print(f"ネットワークリクエストを保存しました: browser_network_requests.json ({len(network_requests)}件)")
        
        with open("browser_network_responses.json", "w", encoding="utf-8") as f:
            json.dump(network_responses, f, ensure_ascii=False, indent=2)
        print(f"ネットワークレスポンスを保存しました: browser_network_responses.json ({len(network_responses)}件)")
        
        # スクリーンショットを撮影
        print("\n9. スクリーンショットを撮影...")
        page.screenshot(path="browser_after_chubunrui.png", full_page=True)
        print("スクリーンショットを保存しました: browser_after_chubunrui.png")
        
        # ブラウザを閉じる前に少し待つ
        print("\n10秒後にブラウザを閉じます...")
        time.sleep(10)
        
        browser.close()
    
    print("\n" + "="*80)
    print("調査完了")
    print("="*80)


if __name__ == "__main__":
    test_browser_simulation_detailed()
