"""UserEntry_Download.aspxページの構造を確認するスクリプト"""
import sys
from pathlib import Path
from bs4 import BeautifulSoup
import re

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig  # type: ignore
from src.core.scraper import Scraper  # type: ignore

def main():
    logger = Logger(LoggingConfig(level="INFO"))
    
    logger.info("============================================================")
    logger.info("UserEntry_Download.aspxページの構造確認")
    logger.info("============================================================")
    
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    try:
        # 詳細ページのHTMLを読み込む
        detail_html_path = Path("test_detail_page_from_har_44_10.html")
        if not detail_html_path.exists():
            logger.error(f"詳細ページHTMLが見つかりません: {detail_html_path}")
            return
        
        with open(detail_html_path, "r", encoding="utf-8") as f:
            detail_html = f.read()
        
        detail_soup = BeautifulSoup(detail_html, "html.parser")
        
        # AnkenkanriNoとHachushaIdを抽出
        ankenkanri_no = None
        hachusha_id = None
        
        script_tags = detail_soup.find_all("script")
        for script in script_tags:
            script_text = script.string
            if script_text and "AnkenkanriNo" in script_text:
                match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', script_text)
                if match:
                    ankenkanri_no = match.group(1)
                    logger.info(f"AnkenkanriNo: {ankenkanri_no}")
                
                match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', script_text)
                if match:
                    hachusha_id = match.group(1)
                    logger.info(f"HachushaId: {hachusha_id}")
        
        if not ankenkanri_no or not hachusha_id:
            logger.error("AnkenkanriNoまたはHachushaIdが見つかりませんでした")
            return
        
        # UserEntry_Download.aspxにアクセス
        download_url = f"https://www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx?data1={ankenkanri_no}&data2={hachusha_id}"
        logger.info(f"UserEntry_Download.aspxにアクセス: {download_url}")
        
        response = http_client.get(download_url)
        if response.status_code != 200:
            logger.error(f"UserEntry_Download.aspxへのアクセスに失敗しました: {response.status_code}")
            return
        
        if response.encoding:
            response.encoding = response.apparent_encoding or 'utf-8'
        else:
            response.encoding = 'utf-8'
        
        try:
            download_soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
        except (UnicodeDecodeError, LookupError):
            try:
                download_soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
            except UnicodeDecodeError:
                download_soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
        
        # HTMLを保存
        output_file = Path("test_userentry_download.html")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(str(download_soup))
        logger.info(f"✓ UserEntry_Download.aspxのHTMLを保存: {output_file}")
        
        # ファイルリンクを探す
        file_links = download_soup.find_all("a", href=re.compile(r'\.(pdf|xlsx|docx|doc|xls)$', re.I))
        logger.info(f"ファイルリンク数: {len(file_links)}")
        
        if file_links:
            logger.info("\n発見されたファイルリンク（最初の10件）:")
            for link in file_links[:10]:
                logger.info(f"  - {link.get('href')} ({link.get_text(strip=True)})")
        else:
            logger.warning("ファイルリンクが見つかりませんでした")
            # HTMLの構造を確認
            logger.info("\nHTMLの構造を確認中...")
            logger.info(f"タイトル: {download_soup.find('title').get_text() if download_soup.find('title') else 'N/A'}")
            
            # テーブルを探す
            tables = download_soup.find_all("table")
            logger.info(f"テーブル数: {len(tables)}")
            for i, table in enumerate(tables[:5]):
                logger.info(f"  テーブル #{i}: id={table.get('id')}, class={table.get('class')}")
            
            # すべてのリンクを確認
            all_links = download_soup.find_all("a", href=True)
            logger.info(f"\nすべてのリンク数: {len(all_links)}")
            for link in all_links[:20]:
                href = link.get('href', '')
                text = link.get_text(strip=True)
                logger.info(f"  - {href} ({text})")
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
    finally:
        http_client.close()
    
    logger.info("\nテスト終了")

if __name__ == "__main__":
    main()

