"""POSTバック後のレスポンスを詳細に分析するスクリプト（Playwright使用）"""

import sys
import io
from pathlib import Path
import json
import time
import re

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
    print("警告: Playwrightがインストールされていません")


def test_postback_response_analysis():
    """POSTバック後のレスポンスを詳細に分析"""
    if not PLAYWRIGHT_AVAILABLE:
        print("Playwrightが利用できないため、このテストをスキップします")
        return
    
    print("="*80)
    print("POSTバック後のレスポンス詳細分析")
    print("="*80)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        # ネットワークレスポンスを記録
        postback_responses = []
        
        def handle_response(response):
            if "Search.aspx" in response.url and response.request.method == "POST":
                try:
                    # レスポンスのHTMLを取得
                    html = response.text()
                    postback_responses.append({
                        "url": response.url,
                        "status": response.status,
                        "headers": dict(response.headers),
                        "html": html,
                    })
                except:
                    pass
        
        page.on("response", handle_response)
        
        # ページに移動
        print("\n1. ページに移動中...")
        page.goto(search_url, wait_until="networkidle")
        time.sleep(2)
        
        # 大分類を選択
        print("\n2. 大分類を選択中...")
        page.select_option("select#drpTopKikanInf", "0")
        time.sleep(2)
        
        # 中分類を選択（POSTバックが発生）
        print("\n3. 中分類を選択中（POSTバック）...")
        page.select_option("select#drpLargeKikanInf2", "21")
        time.sleep(3)  # POSTバックの完了を待つ
        
        # POSTバック後のレスポンスを分析
        print(f"\n4. POSTバック後のレスポンスを分析...")
        print(f"   記録されたレスポンス数: {len(postback_responses)}")
        
        for i, resp in enumerate(postback_responses):
            print(f"\n   レスポンス {i+1}:")
            print(f"     URL: {resp['url']}")
            print(f"     ステータス: {resp['status']}")
            
            html = resp['html']
            
            # 小分類のselect要素を確認
            if "drpMiddleKikanInf" in html:
                # HTMLから小分類の選択肢を抽出
                pattern = r'<select[^>]*id="drpMiddleKikanInf"[^>]*>(.*?)</select>'
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    select_content = match.group(1)
                    options = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', select_content)
                    print(f"     小分類の選択肢数: {len(options)}")
                    for value, text in options[:5]:
                        marker = "★" if "東北" in text else " "
                        print(f"       {marker} value='{value}', text='{text}'")
            
            # setListItemSub()の呼び出しを確認
            if "setListItemSub" in html:
                pattern = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*\[(.*?)\]\s*\)"
                matches = re.findall(pattern, html, re.DOTALL)
                if matches:
                    print(f"     setListItemSub()の呼び出し数: {len(matches)}")
                    for call_id, list_content in matches:
                        if "MiddleKikanInf" in call_id:
                            print(f"       ★ 小分類のsetListItemSub()を発見！")
                            items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
                            print(f"       アイテム数: {len(items)}")
                            for item in items[:5]:
                                if ":" in item:
                                    value, text = item.split(":", 1)
                                    marker = "★" if "東北" in text else " "
                                    print(f"         {marker} '{value}:{text}'")
            
            # HTMLを保存
            output_file = f"postback_response_{i+1}.html"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"     HTMLを保存: {output_file}")
        
        # 現在のページの小分類の選択肢を確認
        print("\n5. 現在のページの小分類の選択肢を確認...")
        try:
            select_element = page.query_selector("select#drpMiddleKikanInf")
            if select_element:
                options = select_element.query_selector_all("option")
                print(f"   選択肢数: {len(options)}")
                for opt in options:
                    value = opt.get_attribute("value")
                    text = opt.inner_text()
                    marker = "★" if "東北" in text else " "
                    print(f"     {marker} value='{value}', text='{text}'")
        except Exception as e:
            print(f"   エラー: {str(e)}")
        
        print("\n10秒後にブラウザを閉じます...")
        time.sleep(10)
        
        browser.close()
    
    print("\n" + "="*80)
    print("分析完了")
    print("="*80)


if __name__ == "__main__":
    test_postback_response_analysis()
