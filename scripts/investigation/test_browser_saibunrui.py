"""実際のブラウザで小分類選択後の細分類の選択肢を確認するスクリプト（Playwright使用）"""

import sys
import io
from pathlib import Path
import time

# WindowsのコンソールでUTF-8を正しく表示するための設定
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("警告: Playwrightがインストールされていません")


def test_browser_saibunrui():
    """実際のブラウザで小分類選択後の細分類の選択肢を確認"""
    if not PLAYWRIGHT_AVAILABLE:
        print("Playwrightが利用できないため、このテストをスキップします")
        return
    
    print("="*80)
    print("実際のブラウザで小分類選択後の細分類の選択肢を確認")
    print("="*80)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        # ページに移動
        print("\n1. ページに移動中...")
        page.goto(search_url, wait_until="networkidle")
        time.sleep(2)
        
        # 大分類を選択
        print("\n2. 大分類を選択中...")
        page.select_option("select#drpTopKikanInf", "0")
        time.sleep(2)
        
        # 中分類を選択
        print("\n3. 中分類を選択中...")
        page.select_option("select#drpLargeKikanInf2", "21")
        time.sleep(2)
        
        # 小分類を選択
        print("\n4. 小分類を選択中...")
        page.select_option("select#drpMiddleKikanInf", "02")
        time.sleep(3)  # 細分類の選択肢が読み込まれるのを待つ
        
        # 細分類のselect要素を確認
        print("\n5. 細分類のselect要素を確認...")
        try:
            select_element = page.query_selector("select#drpSmallKikanInf")
            if select_element:
                options = select_element.query_selector_all("option")
                print(f"細分類の選択肢数: {len(options)}")
                print("\n細分類の選択肢:")
                for i, option in enumerate(options[:20]):  # 最初の20個を表示
                    value = option.get_attribute("value")
                    text = option.inner_text()
                    print(f"  {i+1}. value='{value}', text='{text}'")
            else:
                print("細分類のselect要素が見つかりません")
        except Exception as e:
            print(f"エラー: {str(e)}")
        
        # JavaScriptの実行結果を確認
        print("\n6. JavaScriptの実行結果を確認...")
        try:
            # 細分類のselect要素の選択肢をJavaScriptで取得
            saibunrui_options = page.evaluate("""
                () => {
                    const select = document.getElementById('drpSmallKikanInf');
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
            print(f"JavaScriptで取得した細分類の選択肢数: {len(saibunrui_options)}")
            for opt in saibunrui_options[:20]:
                print(f"  value='{opt['value']}', text='{opt['text']}', selected={opt['selected']}")
        except Exception as e:
            print(f"エラー: {str(e)}")
        
        # HTMLを保存
        html = page.content()
        with open("browser_after_shoubunrui.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("\nHTMLを保存しました: browser_after_shoubunrui.html")
        
        # スクリーンショットを撮影
        page.screenshot(path="browser_after_shoubunrui.png", full_page=True)
        print("スクリーンショットを保存しました: browser_after_shoubunrui.png")
        
        print("\n10秒後にブラウザを閉じます...")
        time.sleep(10)
        
        browser.close()
    
    print("\n" + "="*80)
    print("確認完了")
    print("="*80)


if __name__ == "__main__":
    test_browser_saibunrui()
