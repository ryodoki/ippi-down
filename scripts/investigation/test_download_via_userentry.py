"""UserEntry_Download.aspx経由でダウンロードを試行するスクリプト

別ドメインへの直接接続がタイムアウトするため、
UserEntry_Download.aspx経由でダウンロードを試みます。
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re


def test_download_via_userentry():
    """UserEntry_Download.aspx経由でダウンロードを試行"""
    print("=" * 80)
    print("UserEntry_Download.aspx経由でダウンロードを試行")
    print("=" * 80)
    
    logger = Logger(LoggingConfig(level="INFO"))
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    save_path = Path("./downloads/test_userentry")
    save_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # ステップ1: 検索を実行
        print("\n[ステップ1] 検索を実行")
        print("-" * 80)
        
        search_conditions = SearchConditions(
            hachu_daibunrui="国の機関"
        )
        
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        if not result_soup:
            print("検索に失敗しました")
            return False
        
        # ステップ2: 詳細ページからAnkenkanriNoとHachushaIdを抽出
        print("\n[ステップ2] 詳細ページから情報を抽出")
        print("-" * 80)
        
        # 検索結果テーブルから最初の案件の詳細ページを取得
        result_table = result_soup.find("table", id="dgrSearchList")
        if not result_table:
            print("検索結果テーブルが見つかりません")
            return False
        
        rows = result_table.find_all("tr")
        if len(rows) < 2:
            print("検索結果が見つかりません")
            return False
        
        # 最初の案件の詳細リンクを取得
        first_row = rows[1]  # 最初の行はヘッダー
        detail_link = first_row.find("a", href=lambda x: x and "__doPostBack" in x)
        if not detail_link:
            print("詳細リンクが見つかりません")
            return False
        
        # __doPostBackから詳細ページを取得
        href = detail_link.get("href", "")
        match = re.search(r"__doPostBack\('([^']+)','([^']+)'\)", href)
        if not match:
            print("__doPostBackの解析に失敗しました")
            return False
        
        event_target = match.group(1)
        event_argument = match.group(2)
        
        # 詳細ページを取得
        form_data = scraper._get_all_hidden_inputs(result_soup)
        form_data["__EVENTTARGET"] = event_target
        form_data["__EVENTARGUMENT"] = event_argument
        
        form = result_soup.find("form")
        if form and form.get("action"):
            post_url = urljoin(search_url, form.get("action"))
        else:
            post_url = search_url
        
        print(f"詳細ページを取得: {post_url}")
        detail_response = http_client.post(post_url, data=form_data)
        
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
        
        # JavaScriptコードからAnkenkanriNoとHachushaIdを抽出
        ankenkanri_no = None
        hachusha_id = None
        
        script_tags = detail_soup.find_all("script")
        for script in script_tags:
            script_text = script.string
            if script_text and "AnkenkanriNo" in script_text:
                match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', script_text)
                if match:
                    ankenkanri_no = match.group(1)
                    print(f"AnkenkanriNo: {ankenkanri_no}")
                
                match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', script_text)
                if match:
                    hachusha_id = match.group(1)
                    print(f"HachushaId: {hachusha_id}")
        
        if not ankenkanri_no or not hachusha_id:
            print("AnkenkanriNoまたはHachushaIdが見つかりません")
            return False
        
        # ステップ3: UserEntry_Download.aspxからファイルをダウンロード
        print(f"\n[ステップ3] UserEntry_Download.aspxからダウンロード")
        print("-" * 80)
        
        download_url = f"https://www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx?data1={ankenkanri_no}&data2={hachusha_id}"
        print(f"URL: {download_url}")
        
        # UserEntry_Download.aspxページを取得
        download_response = http_client.get(download_url)
        
        if download_response.status_code != 200:
            print(f"UserEntry_Download.aspxの取得に失敗: Status {download_response.status_code}")
            return False
        
        # ページからファイルリンクを抽出
        if download_response.encoding:
            download_response.encoding = download_response.apparent_encoding or 'utf-8'
        else:
            download_response.encoding = 'utf-8'
        
        try:
            download_soup = BeautifulSoup(download_response.content, "lxml", from_encoding=download_response.encoding)
        except (UnicodeDecodeError, LookupError):
            try:
                download_soup = BeautifulSoup(download_response.content, "lxml", from_encoding='utf-8')
            except UnicodeDecodeError:
                download_soup = BeautifulSoup(download_response.content.decode('utf-8', errors='ignore'), "lxml")
        
        # ファイルリンクを抽出
        files = scraper.extract_file_links(download_soup, download_url, [".pdf"])
        
        if not files:
            print("ファイルリンクが見つかりません")
            # HTMLを保存して確認
            html_file = save_path / "userentry_page.html"
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(str(download_soup))
            print(f"HTMLを保存: {html_file}")
            return False
        
        print(f"発見されたファイル数: {len(files)}")
        
        # ステップ4: 最初のファイルをダウンロード
        test_file = files[0]
        print(f"\n[ステップ4] ダウンロード実行: {test_file.filename}")
        print("-" * 80)
        print(f"URL: {test_file.url}")
        
        save_file = save_path / test_file.filename
        if not save_file.name.endswith('.pdf'):
            save_file = save_file.with_suffix('.pdf')
        
        def progress_callback(downloaded, total):
            if total > 0:
                percent = (downloaded / total) * 100
                print(f"  進捗: {percent:.1f}% ({downloaded:,}/{total:,} bytes)")
            else:
                print(f"  進捗: {downloaded:,} bytes (サイズ不明)")
        
        # ダウンロード実行（同じドメインなのでセッションCookieが使用される）
        success = http_client.download_file(
            test_file.url,
            str(save_file),
            progress_callback,
            referer=download_url
        )
        
        if success:
            if save_file.exists():
                size = save_file.stat().st_size
                print(f"\n[SUCCESS] ダウンロード成功!")
                print(f"  ファイル: {save_file}")
                print(f"  サイズ: {size:,} bytes ({size / 1024:.2f} KB)")
                return True
            else:
                print(f"\n[ERROR] ダウンロードは成功したが、ファイルが見つかりません")
                return False
        else:
            print(f"\n[ERROR] ダウンロードに失敗しました")
            return False
            
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()


if __name__ == "__main__":
    success = test_download_via_userentry()
    sys.exit(0 if success else 1)

