"""HTML構造を解析するスクリプト

実際のWebページのHTMLを取得して解析し、以下の情報を確認：
1. UserEntry_Download.aspxページの実際のHTML構造
2. テーブル（dgrKokoku/dgrKeika）の存在と構造
3. リンクの実際の形式
4. 必要なパラメータやヘッダー
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
from typing import Dict, List, Any
from src.utils.logger import Logger
from src.utils.http_client import HTTPClient
from src.core.scraper import Scraper


def analyze_search_results_page(scraper: Scraper, search_url: str) -> Dict[str, Any]:
    """検索結果ページを解析"""
    logger = Logger()
    logger.info("=== 検索結果ページの解析開始 ===")
    
    result = {
        "url": search_url,
        "soup_obtained": False,
        "tables": [],
        "file_links": [],
        "detail_links": [],
    }
    
    try:
        soup = scraper.fetch_page(search_url)
        if not soup:
            logger.error("検索結果ページの取得に失敗")
            return result
        
        result["soup_obtained"] = True
        
        # テーブルの確認
        tables = soup.find_all("table")
        logger.info(f"テーブル数: {len(tables)}")
        
        for table in tables:
            table_id = table.get("id", "なし")
            table_class = table.get("class", [])
            rows = table.find_all("tr")
            logger.info(f"  テーブルID: {table_id}, クラス: {table_class}, 行数: {len(rows)}")
            
            result["tables"].append({
                "id": table_id,
                "class": table_class,
                "row_count": len(rows),
            })
        
        # dgrSearchListテーブルの確認
        search_table = soup.find("table", id="dgrSearchList")
        if search_table:
            logger.info("dgrSearchListテーブルを発見")
            rows = search_table.find_all("tr")
            logger.info(f"  行数: {len(rows)}")
            
            for i, row in enumerate(rows[:5]):  # 最初の5行のみ
                detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
                if detail_link:
                    href = detail_link.get("href", "")
                    logger.info(f"  行{i}: 詳細リンク発見: {href[:100]}...")
                    result["detail_links"].append(href[:200])
        
        # ファイルリンクの抽出
        file_types = [".pdf", ".xlsx", ".docx"]
        files = scraper.extract_file_links(soup, search_url, file_types)
        logger.info(f"抽出されたファイルリンク数: {len(files)}")
        
        for file_info in files[:5]:  # 最初の5件のみ
            logger.info(f"  ファイル: {file_info.filename} -> {file_info.url[:100]}...")
            result["file_links"].append({
                "filename": file_info.filename,
                "url": file_info.url,
                "file_type": file_info.file_type,
            })
        
    except Exception as e:
        logger.error(f"検索結果ページの解析エラー: {str(e)}", exc_info=True)
        result["error"] = str(e)
    
    return result


def analyze_detail_page(scraper: Scraper, search_url: str) -> Dict[str, Any]:
    """詳細ページを解析"""
    logger = Logger()
    logger.info("=== 詳細ページの解析開始 ===")
    
    result = {
        "soup_obtained": False,
        "tables": [],
        "file_links": [],
        "ankenkanri_no": None,
        "hachusha_id": None,
    }
    
    try:
        # 検索条件を取得
        from src.config.config_manager import ConfigManager
        config = ConfigManager(config_path="config/config.yaml", logger=logger).load_config()
        
        # 検索結果を取得
        soup = scraper.submit_search_form(search_url, config.search_conditions)
        if not soup:
            logger.error("検索結果ページの取得に失敗")
            return result
        
        # 最初の詳細ページリンクを取得
        search_table = soup.find("table", id="dgrSearchList")
        if not search_table:
            logger.error("dgrSearchListテーブルが見つかりません")
            return result
        
        rows = search_table.find_all("tr")
        if len(rows) < 2:
            logger.error("検索結果がありません")
            return result
        
        # 最初の行の詳細リンクを取得
        detail_link = rows[1].find("a", href=lambda x: x and "__doPostBack" in x)
        if not detail_link:
            logger.error("詳細リンクが見つかりません")
            return result
        
        href = detail_link.get("href", "")
        logger.info(f"詳細リンク: {href[:100]}...")
        
        # 詳細ページを取得
        detail_files = scraper._extract_files_from_detail_page_via_postback(
            search_url, href, [".pdf", ".xlsx", ".docx"], soup
        )
        
        logger.info(f"詳細ページから抽出されたファイル数: {len(detail_files)}")
        
        # 詳細ページのHTMLを取得（内部で取得されているはず）
        # ここでは結果のみを返す
        result["file_links"] = [
            {
                "filename": f.filename,
                "url": f.url,
                "file_type": f.file_type,
            }
            for f in detail_files[:10]  # 最初の10件のみ
        ]
        
        # AnkenkanriNoとHachushaIdを抽出
        # これは_scraper内で行われているが、ここでも確認
        import re
        detail_soup = scraper.fetch_page(search_url)  # 仮の取得
        if detail_soup:
            script_tags = detail_soup.find_all("script")
            for script in script_tags:
                script_text = script.string
                if script_text and "AnkenkanriNo" in script_text:
                    match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', script_text)
                    if match:
                        result["ankenkanri_no"] = match.group(1)
                    
                    match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', script_text)
                    if match:
                        result["hachusha_id"] = match.group(1)
        
    except Exception as e:
        logger.error(f"詳細ページの解析エラー: {str(e)}", exc_info=True)
        result["error"] = str(e)
    
    return result


def analyze_userentry_download_page(scraper: Scraper, ankenkanri_no: str, hachusha_id: str) -> Dict[str, Any]:
    """UserEntry_Download.aspxページを解析"""
    logger = Logger()
    logger.info("=== UserEntry_Download.aspxページの解析開始 ===")
    
    result = {
        "url": None,
        "soup_obtained": False,
        "tables": [],
        "file_links": [],
        "html_saved": False,
    }
    
    try:
        download_url = f"https://www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx?data1={ankenkanri_no}&data2={hachusha_id}"
        result["url"] = download_url
        logger.info(f"UserEntry_Download.aspx URL: {download_url}")
        
        # ページを取得
        response = scraper.http_client.get(download_url)
        if response.status_code != 200:
            logger.error(f"UserEntry_Download.aspxの取得に失敗: {response.status_code}")
            return result
        
        # HTMLを保存
        html_file = PROJECT_ROOT / "tests" / "debug" / "userentry_download.html"
        html_file.parent.mkdir(parents=True, exist_ok=True)
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(response.text)
        logger.info(f"HTMLを保存: {html_file}")
        result["html_saved"] = True
        
        # BeautifulSoupで解析
        if response.encoding:
            response.encoding = response.apparent_encoding or 'utf-8'
        else:
            response.encoding = 'utf-8'
        
        try:
            soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
        except (UnicodeDecodeError, LookupError):
            try:
                soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
            except UnicodeDecodeError:
                soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
        
        result["soup_obtained"] = True
        
        # テーブルの確認
        tables = soup.find_all("table")
        logger.info(f"テーブル数: {len(tables)}")
        
        for table in tables:
            table_id = table.get("id", "なし")
            table_class = table.get("class", [])
            rows = table.find_all("tr")
            logger.info(f"  テーブルID: {table_id}, クラス: {table_class}, 行数: {len(rows)}")
            
            table_info = {
                "id": table_id,
                "class": table_class,
                "row_count": len(rows),
                "rows_detail": [],
            }
            
            # 最初の5行の詳細を取得
            for i, row in enumerate(rows[:5]):
                cells = row.find_all(["td", "th"])
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                links = row.find_all("a", href=True)
                link_hrefs = [link.get("href", "") for link in links]
                
                table_info["rows_detail"].append({
                    "row_index": i,
                    "cell_count": len(cells),
                    "cell_texts": cell_texts[:5],  # 最初の5セル
                    "link_count": len(links),
                    "link_hrefs": [href[:200] for href in link_hrefs[:3]],  # 最初の3リンク
                })
            
            result["tables"].append(table_info)
        
        # dgrKokokuとdgrKeikaテーブルの詳細確認
        for table_id in ["dgrKokoku", "dgrKeika"]:
            table = soup.find("table", id=table_id)
            if table:
                logger.info(f"{table_id}テーブルを発見")
                rows = table.find_all("tr")[1:]  # ヘッダー行をスキップ
                logger.info(f"  データ行数: {len(rows)}")
                
                for i, row in enumerate(rows[:3]):  # 最初の3行のみ
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        document_name = cells[0].get_text(strip=True)
                        status_cell = cells[1]
                        link = status_cell.find("a", href=True)
                        
                        logger.info(f"  行{i+1}: 文書名={document_name}, リンク={link.get('href', 'なし')[:100] if link else 'なし'}")
        
        # ファイルリンクの抽出（_extract_files_from_tablesを使用）
        files = scraper._extract_files_from_tables(soup, download_url, [".pdf", ".xlsx", ".docx"])
        logger.info(f"_extract_files_from_tablesで抽出されたファイル数: {len(files)}")
        
        for file_info in files[:10]:  # 最初の10件のみ
            logger.info(f"  ファイル: {file_info.filename} -> {file_info.url[:100]}...")
            result["file_links"].append({
                "filename": file_info.filename,
                "url": file_info.url,
                "file_type": file_info.file_type,
            })
        
        # 通常のextract_file_linksも試す
        files2 = scraper.extract_file_links(soup, download_url, [".pdf", ".xlsx", ".docx"])
        logger.info(f"extract_file_linksで抽出されたファイル数: {len(files2)}")
        
    except Exception as e:
        logger.error(f"UserEntry_Download.aspxページの解析エラー: {str(e)}", exc_info=True)
        result["error"] = str(e)
    
    return result


def main():
    """メイン処理"""
    logger = Logger()
    logger.info("=== HTML構造解析スクリプト開始 ===")
    
    # 設定を読み込み
    from src.config.config_manager import ConfigManager
    config = ConfigManager(config_path="config/config.yaml", logger=logger).load_config()
    search_url = config.target_urls[0] if config.target_urls else "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    # HTTPClientとScraperを初期化
    http_client = HTTPClient(logger=logger)
    scraper = Scraper(http_client=http_client, logger=logger)
    
    results = {}
    
    # 1. 検索結果ページの解析
    logger.info("\n" + "="*60)
    results["search_results"] = analyze_search_results_page(scraper, search_url)
    
    # 2. 詳細ページの解析
    logger.info("\n" + "="*60)
    results["detail_page"] = analyze_detail_page(scraper, search_url)
    
    # 3. UserEntry_Download.aspxページの解析（AnkenkanriNoとHachushaIdが取得できた場合）
    if results["detail_page"].get("ankenkanri_no") and results["detail_page"].get("hachusha_id"):
        logger.info("\n" + "="*60)
        results["userentry_download"] = analyze_userentry_download_page(
            scraper,
            results["detail_page"]["ankenkanri_no"],
            results["detail_page"]["hachusha_id"]
        )
    else:
        logger.warning("AnkenkanriNoまたはHachushaIdが取得できなかったため、UserEntry_Download.aspxの解析をスキップ")
    
    # 結果をJSONファイルに保存
    output_file = PROJECT_ROOT / "tests" / "debug" / "html_structure_analysis.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n結果を保存: {output_file}")
    logger.info("=== HTML構造解析スクリプト完了 ===")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
