"""検索結果ページの構造を確認するテストスクリプト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from bs4 import BeautifulSoup  # type: ignore

def main():
    """検索結果ページの構造を確認"""
    logger = Logger(LoggingConfig(level="DEBUG"))
    logger.info("=" * 60)
    logger.info("検索結果ページの構造確認")
    logger.info("=" * 60)
    
    # テスト用の検索条件を設定
    search_conditions = SearchConditions(
        hachu_daibunrui="国の機関",  # 大分類
    )
    
    # 初期化
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    try:
        # 検索URL
        search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        
        logger.info(f"検索URL: {search_url}")
        logger.info(f"検索条件: 大分類={search_conditions.hachu_daibunrui}")
        
        # 検索フォームを送信
        logger.info("検索フォームを送信中...")
        soup = scraper.submit_search_form(search_url, search_conditions)
        
        if not soup:
            logger.error("検索フォームの送信に失敗しました")
            return
        
        logger.info("✓ 検索フォームの送信に成功しました")
        
        # HTMLをファイルに保存
        output_file = Path("test_search_result.html")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(str(soup))
        logger.info(f"✓ 検索結果HTMLを保存: {output_file}")
        
        # 検索結果ページの構造を確認
        logger.info("\n検索結果ページの構造を確認中...")
        
        # テーブルを探す
        tables = soup.find_all("table")
        logger.info(f"テーブル数: {len(tables)}")
        
        # リンクを探す
        links = soup.find_all("a", href=True)
        logger.info(f"リンク数: {len(links)}")
        
        # PDF、Excel、Wordファイルへのリンクを探す
        file_extensions = [".pdf", ".xlsx", ".xls", ".docx", ".doc"]
        file_links = []
        for link in links:
            href = link.get("href", "")
            text = link.get_text().strip()
            if any(ext in href.lower() for ext in file_extensions):
                file_links.append((href, text))
        
        logger.info(f"ファイルリンク数: {len(file_links)}")
        if file_links:
            logger.info("\n発見されたファイルリンク（最初の10件）:")
            for i, (href, text) in enumerate(file_links[:10], 1):
                logger.info(f"  {i}. {text}")
                logger.info(f"     URL: {href}")
        
        # 詳細ページへのリンクを探す
        detail_links = []
        for link in links:
            href = link.get("href", "")
            if "Detail" in href or "detail" in href:
                detail_links.append((href, link.get_text().strip()))
        
        logger.info(f"\n詳細ページへのリンク数: {len(detail_links)}")
        if detail_links:
            logger.info("\n詳細ページへのリンク（最初の5件）:")
            for i, (href, text) in enumerate(detail_links[:5], 1):
                logger.info(f"  {i}. {text}")
                logger.info(f"     URL: {href}")
        
        # 検索結果のリストを探す
        # GridViewやDataListなどのASP.NETコントロールを探す
        grid_views = soup.find_all(id=lambda x: x and "GridView" in x)
        data_lists = soup.find_all(id=lambda x: x and "DataList" in x)
        repeater = soup.find_all(id=lambda x: x and "Repeater" in x)
        
        logger.info(f"\nASP.NETコントロール:")
        logger.info(f"  GridView: {len(grid_views)}")
        logger.info(f"  DataList: {len(data_lists)}")
        logger.info(f"  Repeater: {len(repeater)}")
        
        if grid_views:
            logger.info("\n最初のGridViewの構造:")
            grid = grid_views[0]
            rows = grid.find_all("tr")
            logger.info(f"  行数: {len(rows)}")
            if rows:
                logger.info(f"  最初の行のHTML（最初の500文字）:")
                logger.info(str(rows[0])[:500])
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
    finally:
        http_client.close()
        logger.info("\nテスト完了")

if __name__ == "__main__":
    main()

