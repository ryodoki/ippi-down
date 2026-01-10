"""詳細ページのHTMLを保存するスクリプト

実際の詳細ページのHTMLを保存し、リンク構造を確認します。
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from bs4 import BeautifulSoup
import re


def save_detail_page_html():
    """詳細ページのHTMLを保存"""
    print("=" * 80)
    print("詳細ページHTML保存スクリプト")
    print("=" * 80)
    
    logger = Logger(LoggingConfig(level="INFO"))
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    
    try:
        # 検索を実行
        print("\n[ステップ1] 検索を実行")
        print("-" * 80)
        
        search_conditions = SearchConditions(hachu_daibunrui="国の機関")
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        
        if not result_soup:
            print("[ERROR] 検索に失敗しました")
            return False
        
        # 検索結果から最初の案件の詳細ページを取得
        print("\n[ステップ2] 詳細ページを取得")
        print("-" * 80)
        
        result_table = result_soup.find("table", id="dgrSearchList")
        if not result_table:
            print("[ERROR] 検索結果テーブルが見つかりません")
            return False
        
        rows = result_table.find_all("tr")
        if len(rows) < 2:
            print("[ERROR] 検索結果が見つかりません")
            return False
        
        # 最初の案件の詳細リンクを取得
        first_row = rows[1]
        detail_link = first_row.find("a", href=lambda x: x and "__doPostBack" in x)
        if not detail_link:
            print("[ERROR] 詳細リンクが見つかりません")
            return False
        
        # __doPostBackから詳細ページを取得
        href = detail_link.get("href", "")
        match = re.search(r"__doPostBack\('([^']+)','([^']+)'\)", href)
        if not match:
            print("[ERROR] __doPostBackの解析に失敗しました")
            return False
        
        event_target = match.group(1)
        event_argument = match.group(2)
        
        # 詳細ページを取得
        form_data = scraper._get_all_hidden_inputs(result_soup)
        form_data["__EVENTTARGET"] = event_target
        form_data["__EVENTARGUMENT"] = event_argument
        
        form = result_soup.find("form")
        if form and form.get("action"):
            from urllib.parse import urljoin
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
        
        # HTMLを保存
        output_dir = Path("tests/fixtures/html")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "detail_page_actual.html"
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(str(detail_soup))
        
        print(f"\n[SUCCESS] 詳細ページHTMLを保存しました: {output_file}")
        
        # ダウンロードリンクを探す
        print("\n[ステップ3] ダウンロードリンクの分析")
        print("-" * 80)
        
        # dgrKokokuとdgrKeikaテーブルからリンクを探す
        for table_id in ["dgrKokoku", "dgrKeika"]:
            table = detail_soup.find("table", id=table_id)
            if not table:
                print(f"  {table_id}: テーブルが見つかりません")
                continue
            
            print(f"  {table_id}: テーブルを発見")
            rows = table.find_all("tr")[1:]
            print(f"    行数: {len(rows)}")
            
            for i, row in enumerate(rows[:3], 1):  # 最初の3行のみ
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                
                document_name = cells[0].get_text(strip=True)
                status_cell = cells[1]
                link = status_cell.find("a", href=True)
                
                if link:
                    href = link.get("href", "")
                    onclick = link.get("onclick", "")
                    
                    print(f"\n    行{i}: {document_name}")
                    print(f"      href: {href}")
                    if onclick:
                        print(f"      onclick: {onclick[:200]}...")
                    
                    # JavaScriptからURLを抽出
                    if onclick and "KokaiBunshoServlet" in onclick:
                        url_match = re.search(r"['\"]([^'\"]*KokaiBunshoServlet[^'\"]*)['\"]", onclick)
                        if url_match:
                            js_url = url_match.group(1)
                            print(f"      JavaScriptから抽出したURL: {js_url}")
        
        return True
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()


if __name__ == "__main__":
    success = save_detail_page_html()
    sys.exit(0 if success else 1)
