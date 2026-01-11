"""保存されたHTMLファイルを解析するスクリプト"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bs4 import BeautifulSoup


def analyze_userentry_download_html():
    """UserEntry_Download.aspxのHTMLを解析"""
    html_file = PROJECT_ROOT / "tests" / "debug" / "userentry_download_playwright.html"
    
    if not html_file.exists():
        print(f"ファイルが見つかりません: {html_file}")
        return
    
    print("=== UserEntry_Download.aspx HTML解析 ===")
    html = html_file.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    
    # テーブルの確認
    tables = soup.find_all("table")
    print(f"\nテーブル数: {len(tables)}")
    for i, table in enumerate(tables[:10]):
        table_id = table.get("id", "なし")
        table_class = table.get("class", [])
        rows = table.find_all("tr")
        print(f"  テーブル{i+1}: ID={table_id}, クラス={table_class}, 行数={len(rows)}")
    
    # dgrKokokuとdgrKeikaテーブルの確認
    kokoku = soup.find("table", id="dgrKokoku")
    keika = soup.find("table", id="dgrKeika")
    print(f"\ndgrKokokuテーブル: {'見つかった' if kokoku else '見つからない'}")
    print(f"dgrKeikaテーブル: {'見つかった' if keika else '見つからない'}")
    
    # リンクの確認
    links = soup.find_all("a", href=True)
    print(f"\nリンク数: {len(links)}")
    for i, link in enumerate(links[:10]):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        print(f"  リンク{i+1}: {text[:50]} -> {href[:100]}")
    
    # ファイルダウンロード関連のリンクを探す
    download_keywords = ["KokaiBunshoServlet", "Publish", "Download", ".pdf", ".xlsx", ".docx"]
    print(f"\nファイルダウンロード関連のリンク:")
    found_count = 0
    for link in links:
        href = link.get("href", "")
        if any(keyword in href for keyword in download_keywords):
            found_count += 1
            text = link.get_text(strip=True)
            print(f"  {found_count}: {text[:50]} -> {href[:150]}")
    
    if found_count == 0:
        print("  ファイルダウンロード関連のリンクが見つかりませんでした")


def analyze_detail_page_html():
    """詳細ページのHTMLを解析"""
    html_file = PROJECT_ROOT / "tests" / "debug" / "detail_page_playwright.html"
    
    if not html_file.exists():
        print(f"ファイルが見つかりません: {html_file}")
        return
    
    print("\n=== 詳細ページ HTML解析 ===")
    html = html_file.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    
    # dgrKokokuとdgrKeikaテーブルの確認
    kokoku = soup.find("table", id="dgrKokoku")
    keika = soup.find("table", id="dgrKeika")
    
    print(f"\ndgrKokokuテーブル: {'見つかった' if kokoku else '見つからない'}")
    if kokoku:
        rows = kokoku.find_all("tr")[1:]  # ヘッダー行をスキップ
        print(f"  データ行数: {len(rows)}")
        for i, row in enumerate(rows[:3]):
            cells = row.find_all("td")
            if len(cells) >= 2:
                document_name = cells[0].get_text(strip=True)
                status_cell = cells[1]
                link = status_cell.find("a", href=True)
                href = link.get("href", "") if link else "なし"
                print(f"    行{i+1}: 文書名={document_name[:50]}, リンク={href[:100]}")
    
    print(f"\ndgrKeikaテーブル: {'見つかった' if keika else '見つからない'}")
    if keika:
        rows = keika.find_all("tr")[1:]  # ヘッダー行をスキップ
        print(f"  データ行数: {len(rows)}")
        for i, row in enumerate(rows[:3]):
            cells = row.find_all("td")
            if len(cells) >= 2:
                document_name = cells[0].get_text(strip=True)
                status_cell = cells[1]
                link = status_cell.find("a", href=True)
                href = link.get("href", "") if link else "なし"
                print(f"    行{i+1}: 文書名={document_name[:50]}, リンク={href[:100]}")


if __name__ == "__main__":
    analyze_userentry_download_html()
    analyze_detail_page_html()
