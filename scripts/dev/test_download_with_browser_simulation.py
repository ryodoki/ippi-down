"""ブラウザの動作を再現したダウンロードテスト

実際のブラウザでの動作を可能な限り再現します。
特に、中継URL経由やリダイレクトの追従をテストします。
"""

import sys
from pathlib import Path
import json
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from src.core.downloader import Downloader  # type: ignore
from src.core.naming import Naming  # type: ignore
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import re


def test_download_with_browser_simulation():
    """ブラウザの動作を再現したダウンロードテスト"""
    print("=" * 80)
    print("ブラウザ動作再現テスト: ダウンロード機能")
    print("=" * 80)
    print("\nこのテストは以下を試行します：")
    print("  1. 詳細ページから直接リンクをクリックする流れを再現")
    print("  2. 中継URL経由のダウンロードを試行")
    print("  3. リダイレクトの追従")
    print("  4. Cookieとヘッダーの確認")
    print()
    
    logger = Logger(LoggingConfig(level="INFO"))
    http_client = HTTPClient(logger, timeout=30, download_timeout=300)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    save_path = Path("./downloads/test_browser_simulation")
    save_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # ステップ1: 検索を実行してファイルを取得
        print("\n[ステップ1] 検索を実行してファイルを取得")
        print("-" * 80)
        
        search_conditions = SearchConditions(hachu_daibunrui="国の機関")
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        
        if not result_soup:
            print("[ERROR] 検索に失敗しました")
            return False
        
        files = scraper.extract_file_links_from_search_results(
            result_soup, search_url, [".pdf"]
        )
        
        if not files or len(files) == 0:
            print("[ERROR] ファイルが見つかりませんでした")
            return False
        
        test_file = files[0]
        print(f"[INFO] テストファイル: {test_file.filename}")
        print(f"  URL: {test_file.url}")
        print(f"  Page URL: {test_file.page_url}")
        
        # ステップ2: 詳細ページから実際のダウンロードリンクを再取得
        print("\n[ステップ2] 詳細ページから実際のダウンロードリンクを再取得")
        print("-" * 80)
        
        # page_urlから詳細ページを取得
        if test_file.page_url:
            detail_response = http_client.get(test_file.page_url)
            if detail_response.status_code == 200:
                if detail_response.encoding:
                    detail_response.encoding = detail_response.apparent_encoding or 'utf-8'
                else:
                    detail_response.encoding = 'utf-8'
                
                try:
                    detail_soup = BeautifulSoup(detail_response.content, "lxml", from_encoding=detail_response.encoding)
                except (UnicodeDecodeError, LookupError):
                    try:
                        detail_soup = BeautifulSoup(detail_response.content, "lxml", from_encoding='utf-8')
                    except UnicodeDecodeError:
                        detail_soup = BeautifulSoup(detail_response.content.decode('utf-8', errors='ignore'), "lxml")
                
                # 詳細ページから実際のダウンロードリンクを抽出
                actual_download_url = extract_actual_download_link(detail_soup, test_file.page_url, logger)
                
                if actual_download_url and actual_download_url != test_file.url:
                    print(f"[INFO] 実際のダウンロードURLを発見（コードで生成したURLと異なる）")
                    print(f"  コードで生成: {test_file.url}")
                    print(f"  実際のURL: {actual_download_url}")
                    test_file.url = actual_download_url
        
        # ステップ3: 中継URL経由のテスト
        print("\n[ステップ3] 中継URL経由のダウンロードを試行")
        print("-" * 80)
        
        # 詳細ページから中継URL（www.i-ppi.jpドメイン）を探す
        intermediate_url = find_intermediate_url(detail_soup, test_file.page_url, logger)
        
        if intermediate_url:
            print(f"[INFO] 中継URLを発見: {intermediate_url}")
            
            # 中継URLにアクセス（リダイレクトを追従）
            print(f"  中継URLにアクセス中...")
            try:
                intermediate_response = http_client.get(intermediate_url, allow_redirects=True)
                print(f"  Status Code: {intermediate_response.status_code}")
                print(f"  Final URL: {intermediate_response.url}")
                print(f"  Redirects: {len(intermediate_response.history)}")
                
                if intermediate_response.history:
                    for i, resp in enumerate(intermediate_response.history, 1):
                        print(f"    {i}. {resp.status_code} -> {resp.url[:100]}...")
                
                # 最終URLがダウンロードURLか確認
                if intermediate_response.status_code == 200:
                    content_type = intermediate_response.headers.get('Content-Type', '')
                    if 'pdf' in content_type.lower() or 'application/octet-stream' in content_type.lower():
                        print(f"  [SUCCESS] 中継URL経由でPDFを取得できました")
                        # 実際のダウンロードURLを更新
                        test_file.url = intermediate_response.url
                    else:
                        print(f"  [INFO] 中継URLはダウンロードURLではありません（Content-Type: {content_type}）")
                        # HTMLページの場合は、その中からダウンロードリンクを探す
                        if 'html' in content_type.lower():
                            intermediate_soup = BeautifulSoup(intermediate_response.content, 'html.parser')
                            download_link = intermediate_soup.find("a", href=lambda x: x and ("KokaiBunshoServlet" in x or "pdf" in x.lower()))
                            if download_link:
                                download_href = download_link.get("href")
                                if download_href:
                                    actual_url = urljoin(intermediate_response.url, download_href)
                                    print(f"  [INFO] 中継ページからダウンロードリンクを発見: {actual_url}")
                                    test_file.url = actual_url
            except Exception as e:
                print(f"  [ERROR] 中継URLアクセス失敗: {type(e).__name__}: {str(e)}")
        
        # ステップ4: 実際のダウンロードを試行
        print(f"\n[ステップ4] 実際のダウンロードを試行")
        print("-" * 80)
        print(f"  ダウンロードURL: {test_file.url}")
        print(f"  Referer: {test_file.page_url}")
        
        # ブラウザと同じヘッダーを設定
        download_headers = get_browser_like_headers(test_file.page_url)
        
        print(f"\n  送信するヘッダー:")
        for key, value in download_headers.items():
            if key == "Cookie":
                print(f"    {key}: [セッションCookie自動送信]")
            else:
                print(f"    {key}: {value}")
        
        # ダウンロードを試行
        naming = Naming("{filename}", logger)
        downloader = Downloader(http_client, logger)
        
        def progress_callback(current, total, filename):
            if total > 0:
                percent = (current / total) * 100
                print(f"    進捗: {percent:.1f}% ({current:,}/{total:,} bytes)")
            else:
                print(f"    進捗: {current:,} bytes (サイズ不明)")
        
        result = downloader.download_files(
            [test_file],
            str(save_path),
            naming,
            progress_callback
        )
        
        # 結果を表示
        print("\n" + "=" * 80)
        print("ダウンロード結果")
        print("=" * 80)
        print(f"総数: {result.total}")
        print(f"成功: {result.success}")
        print(f"失敗: {result.failed}")
        print(f"スキップ: {result.skipped}")
        
        if result.success > 0:
            print("\n[SUCCESS] ダウンロードに成功しました！")
            for task in result.tasks:
                if task.status == "completed":
                    file_path = Path(task.local_path)
                    if file_path.exists():
                        size = file_path.stat().st_size
                        print(f"  ファイル: {file_path}")
                        print(f"  サイズ: {size:,} bytes ({size / 1024:.2f} KB)")
            return True
        else:
            print("\n[ERROR] ダウンロードに失敗しました")
            for task in result.tasks:
                if task.status == "failed":
                    print(f"  - {task.file_info.filename}")
                    print(f"    エラー: {task.error_message}")
            
            # 詳細な分析結果を保存
            save_analysis_result(test_file, http_client, logger)
            return False
            
    except KeyboardInterrupt:
        print("\n\n[INFO] ユーザーによって中断されました")
        return False
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()


def extract_actual_download_link(detail_soup: BeautifulSoup, base_url: str, logger) -> str:
    """詳細ページから実際のダウンロードリンクを抽出"""
    # dgrKokokuとdgrKeikaテーブルからリンクを抽出
    for table_id in ["dgrKokoku", "dgrKeika"]:
        table = detail_soup.find("table", id=table_id)
        if not table:
            continue
        
        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            
            status_cell = cells[1]
            link = status_cell.find("a", href=True)
            
            if link:
                href = link.get("href")
                onclick = link.get("onclick", "")
                
                # JavaScriptのonclick属性を確認
                if onclick and "KokaiBunshoServlet" in onclick:
                    # JavaScriptからURLを抽出
                    url_match = re.search(r"['\"]([^'\"]*KokaiBunshoServlet[^'\"]*)['\"]", onclick)
                    if url_match:
                        url = url_match.group(1)
                        if not url.startswith("http"):
                            url = urljoin(base_url, url)
                        logger.info(f"JavaScriptからダウンロードURLを抽出: {url}")
                        return url
                
                if href and ("KokaiBunshoServlet" in href or "Publish" in href):
                    absolute_url = urljoin(base_url, href)
                    logger.info(f"HTMLからダウンロードURLを抽出: {absolute_url}")
                    return absolute_url
    
    return None


def find_intermediate_url(detail_soup: BeautifulSoup, base_url: str, logger) -> str:
    """詳細ページから中継URLを探す"""
    # UserEntry_Download.aspxなどのリンクを探す
    intermediate_patterns = [
        "UserEntry_Download.aspx",
        "Download.aspx",
        "Publish.aspx"
    ]
    
    for pattern in intermediate_patterns:
        link = detail_soup.find("a", href=lambda x: x and pattern in x)
        if link:
            href = link.get("href")
            if href:
                absolute_url = urljoin(base_url, href)
                logger.info(f"中継URLを発見（{pattern}）: {absolute_url}")
                return absolute_url
    
    # JavaScriptからも探す
    scripts = detail_soup.find_all("script")
    for script in scripts:
        if script.string and "UserEntry_Download" in script.string:
            url_match = re.search(r"['\"]([^'\"]*UserEntry_Download[^'\"]*)['\"]", script.string)
            if url_match:
                url = url_match.group(1)
                if not url.startswith("http"):
                    url = urljoin(base_url, url)
                logger.info(f"JavaScriptから中継URLを抽出: {url}")
                return url
    
    return None


def get_browser_like_headers(referer: str = None):
    """ブラウザと同じヘッダーを生成"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    if referer:
        headers["Referer"] = referer
        parsed_referer = urlparse(referer)
        headers["Origin"] = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
        # Sec-Fetch-*ヘッダー（モダンブラウザで使用）
        headers["Sec-Fetch-Site"] = "same-site" if parsed_referer.netloc.endswith(".i-ppi.jp") else "cross-site"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-User"] = "?1"
    
    return headers


def save_analysis_result(file_info, http_client, logger):
    """分析結果を保存"""
    analysis = {
        "timestamp": datetime.now().isoformat(),
        "file_info": {
            "filename": file_info.filename,
            "url": file_info.url,
            "page_url": file_info.page_url,
            "metadata": file_info.metadata
        },
        "session_info": {
            "cookies": [
                {
                    "name": cookie.name,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "secure": cookie.secure
                }
                for cookie in http_client.session.cookies
            ]
        },
        "recommendation": "ブラウザの開発者ツールで実際のリクエストを確認してください"
    }
    
    output_file = Path("./docs/dev/browser_simulation_analysis.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    
    logger.info(f"分析結果を保存: {output_file}")


if __name__ == "__main__":
    success = test_download_with_browser_simulation()
    sys.exit(0 if success else 1)
