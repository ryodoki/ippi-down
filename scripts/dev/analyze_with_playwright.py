"""Playwrightを使用してHTML構造を解析するスクリプト

実際のブラウザでページを開き、JavaScriptを実行した後のHTMLを取得して解析
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bs4 import BeautifulSoup
import json
import re
from typing import Dict, List, Any, Optional
from src.utils.logger import Logger


def check_playwright_installed() -> bool:
    """Playwrightがインストールされているか確認"""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def analyze_with_playwright(search_url: str) -> Dict[str, Any]:
    """Playwrightを使用してページを解析"""
    logger = Logger()
    logger.info("=== Playwrightを使用したHTML構造解析開始 ===")
    
    result = {
        "playwright_available": False,
        "search_page": {},
        "detail_page": {},
        "userentry_download": {},
    }
    
    if not check_playwright_installed():
        logger.error("Playwrightがインストールされていません。pip install playwright を実行してください")
        logger.info("python -m playwright install chromium も実行してください")
        return result
    
    try:
        from playwright.sync_api import sync_playwright
        
        result["playwright_available"] = True
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ja-JP",
            )
            page = context.new_page()
            
            try:
                # 1. 検索ページを開く
                logger.info(f"検索ページを開く: {search_url}")
                page.goto(search_url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)  # JavaScriptの実行を待つ
                
                # 検索ボタンをクリック（検索フォームを送信）
                logger.info("検索ボタンをクリック...")
                search_button = page.locator("input[type='submit'][value*='検索'], button[type='submit'], input[name='btnSearch']").first
                if search_button.count() > 0:
                    search_button.click()
                    page.wait_for_timeout(3000)  # 検索結果の読み込みを待つ
                else:
                    logger.warning("検索ボタンが見つかりませんでした")
                
                search_html = page.content()
                search_soup = BeautifulSoup(search_html, "lxml")
                
                # 検索結果テーブルを確認
                search_table = search_soup.find("table", id="dgrSearchList")
                if search_table:
                    rows = search_table.find_all("tr")
                    logger.info(f"検索結果テーブルの行数: {len(rows)}")
                    
                    result["search_page"] = {
                        "table_found": True,
                        "row_count": len(rows),
                    }
                    
                    # 最初の詳細リンクを取得
                    if len(rows) > 1:
                        detail_link = rows[1].find("a", href=lambda x: x and "__doPostBack" in x)
                        if detail_link:
                            href = detail_link.get("href", "")
                            logger.info(f"詳細リンク発見: {href[:100]}...")
                            
                            # 2. 詳細ページを開く（JavaScriptでクリック）
                            logger.info("詳細ページを開く...")
                            # __doPostBackを実行
                            page.evaluate("""
                                __doPostBack('dgrSearchList', '$0');
                            """)
                            
                            # ページ遷移を待つ
                            page.wait_for_timeout(3000)
                            
                            detail_html = page.content()
                            detail_soup = BeautifulSoup(detail_html, "lxml")
                            
                            # AnkenkanriNoとHachushaIdを抽出
                            ankenkanri_no = None
                            hachusha_id = None
                            
                            # JavaScriptから抽出
                            script_tags = detail_soup.find_all("script")
                            for script in script_tags:
                                script_text = script.string
                                if script_text and "AnkenkanriNo" in script_text:
                                    match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', script_text)
                                    if match:
                                        ankenkanri_no = match.group(1)
                                        logger.info(f"AnkenkanriNoを抽出: {ankenkanri_no}")
                                    
                                    match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', script_text)
                                    if match:
                                        hachusha_id = match.group(1)
                                        logger.info(f"HachushaIdを抽出: {hachusha_id}")
                            
                            # 詳細ページのHTMLを保存
                            detail_html_file = PROJECT_ROOT / "tests" / "debug" / "detail_page_playwright.html"
                            detail_html_file.parent.mkdir(parents=True, exist_ok=True)
                            with open(detail_html_file, "w", encoding="utf-8") as f:
                                f.write(detail_html)
                            logger.info(f"詳細ページHTMLを保存: {detail_html_file}")
                            
                            # テーブルの確認
                            kokoku_table = detail_soup.find("table", id="dgrKokoku")
                            keika_table = detail_soup.find("table", id="dgrKeika")
                            
                            result["detail_page"] = {
                                "html_saved": True,
                                "ankenkanri_no": ankenkanri_no,
                                "hachusha_id": hachusha_id,
                                "dgrKokoku_found": kokoku_table is not None,
                                "dgrKeika_found": keika_table is not None,
                            }
                            
                            if kokoku_table:
                                rows = kokoku_table.find_all("tr")[1:]
                                logger.info(f"dgrKokokuテーブルのデータ行数: {len(rows)}")
                                result["detail_page"]["dgrKokoku_row_count"] = len(rows)
                            
                            if keika_table:
                                rows = keika_table.find_all("tr")[1:]
                                logger.info(f"dgrKeikaテーブルのデータ行数: {len(rows)}")
                                result["detail_page"]["dgrKeika_row_count"] = len(rows)
                            
                            # 3. UserEntry_Download.aspxを開く
                            if ankenkanri_no and hachusha_id:
                                download_url = f"https://www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx?data1={ankenkanri_no}&data2={hachusha_id}"
                                logger.info(f"UserEntry_Download.aspxを開く: {download_url}")
                                
                                page.goto(download_url, wait_until="networkidle", timeout=60000)
                                page.wait_for_timeout(2000)
                                
                                download_html = page.content()
                                download_soup = BeautifulSoup(download_html, "lxml")
                                
                                # HTMLを保存
                                download_html_file = PROJECT_ROOT / "tests" / "debug" / "userentry_download_playwright.html"
                                download_html_file.parent.mkdir(parents=True, exist_ok=True)
                                with open(download_html_file, "w", encoding="utf-8") as f:
                                    f.write(download_html)
                                logger.info(f"UserEntry_Download.aspx HTMLを保存: {download_html_file}")
                                
                                # テーブルの確認
                                kokoku_table = download_soup.find("table", id="dgrKokoku")
                                keika_table = download_soup.find("table", id="dgrKeika")
                                
                                result["userentry_download"] = {
                                    "url": download_url,
                                    "html_saved": True,
                                    "dgrKokoku_found": kokoku_table is not None,
                                    "dgrKeika_found": keika_table is not None,
                                }
                                
                                if kokoku_table:
                                    rows = kokoku_table.find_all("tr")[1:]
                                    logger.info(f"UserEntry_Download.aspx - dgrKokokuテーブルのデータ行数: {len(rows)}")
                                    result["userentry_download"]["dgrKokoku_row_count"] = len(rows)
                                    
                                    # 最初の3行の詳細を取得
                                    for i, row in enumerate(rows[:3]):
                                        cells = row.find_all("td")
                                        if len(cells) >= 2:
                                            document_name = cells[0].get_text(strip=True)
                                            status_cell = cells[1]
                                            link = status_cell.find("a", href=True)
                                            
                                            logger.info(f"  行{i+1}: 文書名={document_name}, リンク={link.get('href', 'なし')[:100] if link else 'なし'}")
                                
                                if keika_table:
                                    rows = keika_table.find_all("tr")[1:]
                                    logger.info(f"UserEntry_Download.aspx - dgrKeikaテーブルのデータ行数: {len(rows)}")
                                    result["userentry_download"]["dgrKeika_row_count"] = len(rows)
                                    
                                    # 最初の3行の詳細を取得
                                    for i, row in enumerate(rows[:3]):
                                        cells = row.find_all("td")
                                        if len(cells) >= 2:
                                            document_name = cells[0].get_text(strip=True)
                                            status_cell = cells[1]
                                            link = status_cell.find("a", href=True)
                                            
                                            logger.info(f"  行{i+1}: 文書名={document_name}, リンク={link.get('href', 'なし')[:100] if link else 'なし'}")
                            else:
                                logger.warning("AnkenkanriNoまたはHachushaIdが取得できませんでした")
                        else:
                            logger.warning("詳細リンクが見つかりませんでした")
                    else:
                        logger.warning("検索結果がありません")
                else:
                    logger.warning("dgrSearchListテーブルが見つかりません")
            finally:
                browser.close()
            
    except Exception as e:
        logger.error(f"Playwright解析エラー: {str(e)}", exc_info=True)
        result["error"] = str(e)
    
    return result


def main():
    """メイン処理"""
    logger = Logger()
    logger.info("=== Playwrightを使用したHTML構造解析スクリプト開始 ===")
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    results = analyze_with_playwright(search_url)
    
    # 結果をJSONファイルに保存
    output_file = PROJECT_ROOT / "tests" / "debug" / "html_structure_playwright_analysis.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n結果を保存: {output_file}")
    logger.info("=== Playwrightを使用したHTML構造解析スクリプト完了 ===")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
