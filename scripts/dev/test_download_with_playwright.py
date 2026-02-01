"""Playwrightを使用して実際のダウンロードを試行し、必要な情報を取得するスクリプト"""

import sys
from pathlib import Path
import json
from urllib.parse import urljoin
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
from bs4 import BeautifulSoup
from src.utils.logger import Logger  # pyright: ignore[reportMissingImports]


def check_playwright_installed() -> bool:
    """Playwrightがインストールされているか確認"""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def test_download_with_playwright() -> Dict[str, Any]:
    """Playwrightを使用して実際のダウンロードを試行"""
    logger = Logger()
    logger.info("=== Playwrightを使用したダウンロードテスト開始 ===")
    
    result = {
        "playwright_available": False,
        "download_success": False,
        "download_info": {},
        "network_requests": [],
    }
    
    if not check_playwright_installed():
        logger.error("Playwrightがインストールされていません。pip install playwright を実行してください")
        logger.info("python -m playwright install chromium も実行してください")
        return result
    
    try:
        from playwright.sync_api import sync_playwright
        
        result["playwright_available"] = True
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # ヘッドレスをfalseにして確認しやすく
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ja-JP",
                accept_downloads=True,
            )
            page = context.new_page()
            
            # ネットワークリクエストを記録
            network_requests = []
            
            def handle_request(request):
                network_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "headers": request.headers,
                    "post_data": request.post_data,
                })
            
            def handle_response(response):
                if "KokaiBunshoServlet" in response.url or "Publish" in response.url:
                    network_requests.append({
                        "type": "response",
                        "url": response.url,
                        "status": response.status,
                        "headers": response.headers,
                    })
            
            page.on("request", handle_request)
            page.on("response", handle_response)
            
            try:
                # 1. 検索ページを開く
                search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
                logger.info(f"検索ページを開く: {search_url}")
                page.goto(search_url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)
                
                # 検索ボタンをクリック
                logger.info("検索ボタンをクリック...")
                search_button = page.locator("input[type='submit'][value*='検索'], button[type='submit'], input[name='btnSearch']").first
                if search_button.count() > 0:
                    search_button.click()
                    page.wait_for_timeout(3000)
                
                # 2. 詳細ページを開く
                logger.info("詳細ページを開く...")
                page.evaluate("""
                    __doPostBack('dgrSearchList', '$0');
                """)
                page.wait_for_timeout(3000)
                
                # 詳細ページのHTMLを取得
                detail_html = page.content()
                detail_soup = BeautifulSoup(detail_html, "lxml")
                
                # ファイルリンクを探す
                kokoku_table = detail_soup.find("table", id="dgrKokoku")
                download_url = None
                download_link_text = None
                
                if kokoku_table:
                    rows = kokoku_table.find_all("tr")[1:]
                    if rows:
                        first_row = rows[0]
                        cells = first_row.find_all("td")
                        if len(cells) >= 2:
                            status_cell = cells[1]
                            link = status_cell.find("a", href=True)
                            link = status_cell.find("a", href=True)
                            if link:
                                href_raw = link.get("href")  # ここはデフォルト "" を付けない
                                href = href_raw.strip() if isinstance(href_raw, str) else None

                                if href and not href.startswith(("javascript:", "#")):
                                    download_url = urljoin("https://www.i-ppi.jp", href)
                                    download_link_text = link.get_text(strip=True)
                                    logger.info(f"ダウンロードリンク発見: {download_link_text} -> {download_url}")
                                else:
                                    download_url = None
                
                if not download_url:
                    logger.error("ダウンロードリンクが見つかりませんでした")
                    browser.close()
                    return result
                
                result["download_info"]["url"] = download_url
                result["download_info"]["link_text"] = download_link_text
                
                # 3. ダウンロードを試行（リクエストAPIを使用）
                logger.info(f"ダウンロードを試行: {download_url}")
                
                # ダウンロードディレクトリを設定
                download_dir = PROJECT_ROOT / "tests" / "debug" / "downloads"
                download_dir.mkdir(parents=True, exist_ok=True)
                
                # 現在のページのURLをRefererとして使用
                referer_url = page.url
                logger.info(f"Referer URL: {referer_url}")
                
                # リクエストAPIを使用してダウンロード
                try:
                    response = page.request.get(
                        download_url,
                        headers={
                            "Referer": referer_url,
                        },
                        timeout=60000
                    )
                    
                    logger.info(f"レスポンスステータス: {response.status}")
                    logger.info(f"レスポンスヘッダー: {dict(response.headers)}")
                    
                    if response.status == 200:
                        # ファイルを保存
                        content = response.body()
                        content_type = response.headers.get("content-type", "")
                        
                        # ファイル名を決定
                        suggested_filename = "download"
                        if "pdf" in content_type.lower():
                            suggested_filename = "download.pdf"
                        elif "application/pdf" in content_type:
                            suggested_filename = "download.pdf"
                        
                        save_path = download_dir / suggested_filename
                        save_path.write_bytes(content)
                        
                        # ファイルサイズを確認
                        file_size = save_path.stat().st_size if save_path.exists() else 0
                        logger.info(f"ダウンロード完了: {save_path} ({file_size:,} bytes)")
                        
                        result["download_success"] = save_path.exists() and file_size > 0
                        result["download_info"]["saved_path"] = str(save_path)
                        result["download_info"]["file_size"] = file_size
                        result["download_info"]["suggested_filename"] = suggested_filename
                        result["download_info"]["content_type"] = content_type
                        result["download_info"]["response_status"] = response.status
                        result["download_info"]["response_headers"] = dict(response.headers)
                        
                        # ファイルの先頭バイトを確認
                        if save_path.exists():
                            with open(save_path, "rb") as f:
                                first_bytes = f.read(16)
                                is_pdf = first_bytes.startswith(b"%PDF")
                                is_html = first_bytes.startswith(b"<html") or first_bytes.startswith(b"<!DOCTYPE")
                                
                                result["download_info"]["is_pdf"] = is_pdf
                                result["download_info"]["is_html"] = is_html
                                result["download_info"]["first_bytes"] = first_bytes.hex()
                                
                                logger.info(f"  先頭バイト: PDF={is_pdf}, HTML={is_html}")
                    else:
                        logger.error(f"ダウンロード失敗: ステータスコード {response.status}")
                        result["download_info"]["response_status"] = response.status
                        result["download_info"]["response_headers"] = dict(response.headers)
                        
                except Exception as e:
                    logger.error(f"リクエストAPIエラー: {str(e)}", exc_info=True)
                    result["download_info"]["error"] = str(e)
                
                # ネットワークリクエストを記録
                result["network_requests"] = network_requests
                
                # PDFダウンロード関連のリクエストを探す
                pdf_requests = [r for r in network_requests if "KokaiBunshoServlet" in r.get("url", "") or "Publish" in r.get("url", "")]
                logger.info(f"\nPDFダウンロード関連のリクエスト数: {len(pdf_requests)}")
                for i, req in enumerate(pdf_requests[:3]):
                    logger.info(f"  リクエスト{i+1}: {req.get('method', 'N/A')} {req.get('url', '')[:100]}")
                    if "headers" in req:
                        logger.info(f"    ヘッダー: {json.dumps(req['headers'], ensure_ascii=False, indent=2)[:200]}")
                
            finally:
                browser.close()
            
    except Exception as e:
        logger.error(f"Playwrightダウンロードテストエラー: {str(e)}", exc_info=True)
        result["error"] = str(e)
    
    return result


def main():
    """メイン処理"""
    logger = Logger()
    logger.info("=== Playwrightを使用したダウンロードテストスクリプト開始 ===")
    
    results = test_download_with_playwright()
    
    # 結果をJSONファイルに保存
    output_file = PROJECT_ROOT / "tests" / "debug" / "playwright_download_test.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n結果を保存: {output_file}")
    logger.info("=== Playwrightを使用したダウンロードテストスクリプト完了 ===")
    
    # 結果を表示
    if results.get("download_success"):
        logger.info("\n✅ ダウンロード成功!")
        logger.info(f"  ファイル: {results['download_info'].get('saved_path', 'N/A')}")
        logger.info(f"  サイズ: {results['download_info'].get('file_size', 0):,} bytes")
        logger.info(f"  PDF: {results['download_info'].get('is_pdf', False)}")
    else:
        logger.warning("\n❌ ダウンロード失敗")
        if "error" in results:
            logger.error(f"  エラー: {results['error']}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
