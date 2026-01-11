"""ダウンロードURLと必要な情報を解析するスクリプト

実際のダウンロードURLを取得し、必要なヘッダーやパラメータを確認
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bs4 import BeautifulSoup
from src.utils.logger import Logger
from src.utils.http_client import HTTPClient
from src.core.scraper import Scraper
import json
from urllib.parse import urlparse, parse_qs


def analyze_download_url():
    """ダウンロードURLを解析"""
    logger = Logger()
    logger.info("=== ダウンロードURL解析開始 ===")
    
    # 設定を読み込み
    from src.config.config_manager import ConfigManager
    config = ConfigManager(config_path="config/config.yaml", logger=logger).load_config()
    search_url = config.target_urls[0] if config.target_urls else "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    # HTTPClientとScraperを初期化
    http_client = HTTPClient(logger=logger)
    scraper = Scraper(http_client=http_client, logger=logger)
    
    result = {
        "download_urls": [],
        "url_analysis": [],
    }
    
    try:
        # 検索結果を取得
        soup = scraper.submit_search_form(search_url, config.search_conditions)
        if not soup:
            logger.error("検索結果ページの取得に失敗")
            return result
        
        # 検索結果からファイルリンクを抽出
        file_types = [".pdf", ".xlsx", ".docx"]
        files = scraper.extract_file_links_from_search_results(soup, search_url, file_types)
        
        logger.info(f"抽出されたファイルリンク数: {len(files)}")
        
        # 最初の5件のURLを解析
        for i, file_info in enumerate(files[:5]):
            url = file_info.url
            logger.info(f"\n=== ファイル{i+1}: {file_info.filename} ===")
            logger.info(f"URL: {url}")
            logger.info(f"page_url (Referer): {file_info.page_url}")
            
            # URLを解析
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            
            url_info = {
                "filename": file_info.filename,
                "url": url,
                "page_url": file_info.page_url,
                "domain": parsed.netloc,
                "path": parsed.path,
                "query_params": {k: v[0] if len(v) == 1 else v for k, v in query_params.items()},
            }
            
            result["download_urls"].append(url_info)
            
            # 実際のダウンロードを試行（HEADリクエスト）
            logger.info(f"HEADリクエストを送信...")
            try:
                headers = {
                    "Referer": file_info.page_url,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                
                response = http_client.session.head(url, headers=headers, timeout=(10, 30), allow_redirects=True)
                
                analysis = {
                    "url": url,
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "content_type": response.headers.get("Content-Type", ""),
                    "content_length": response.headers.get("Content-Length", ""),
                    "location": response.headers.get("Location", ""),
                }
                
                logger.info(f"  ステータスコード: {response.status_code}")
                logger.info(f"  Content-Type: {analysis['content_type']}")
                logger.info(f"  Content-Length: {analysis['content_length']}")
                if analysis['location']:
                    logger.info(f"  リダイレクト先: {analysis['location']}")
                
                result["url_analysis"].append(analysis)
                
            except Exception as e:
                logger.error(f"  HEADリクエストエラー: {str(e)}")
                result["url_analysis"].append({
                    "url": url,
                    "error": str(e),
                })
        
        # 結果をJSONファイルに保存
        output_file = PROJECT_ROOT / "tests" / "debug" / "download_url_analysis.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"\n結果を保存: {output_file}")
        
    except Exception as e:
        logger.error(f"ダウンロードURL解析エラー: {str(e)}", exc_info=True)
        result["error"] = str(e)
    
    return result


if __name__ == "__main__":
    analyze_download_url()
