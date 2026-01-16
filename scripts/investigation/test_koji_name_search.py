"""工事名（文字列検索）の動作を調査するスクリプト"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.logger import Logger
from src.utils.http_client import HTTPClient
from src.core.scraper import Scraper
from src.models.config_model import SearchConditions
from bs4 import BeautifulSoup
import re

def test_koji_name_search():
    """工事名検索の動作をテスト"""
    
    # ロガーとHTTPクライアントを初期化
    logger = Logger()
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    # 検索URL
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    # 検索条件を設定（工事名="トンネル"）
    search_conditions = SearchConditions()
    search_conditions.koji_name = "トンネル"
    
    print("=" * 80)
    print("工事名検索テスト: 検索条件")
    print("=" * 80)
    print(f"工事名: '{search_conditions.koji_name}'")
    print()
    
    # 検索フォームを送信
    print("検索フォームを送信中...")
    soup = scraper.submit_search_form(search_url, search_conditions)
    
    if not soup:
        print("エラー: 検索結果ページを取得できませんでした")
        return
    
    # 検索結果ページのHTMLを保存（デバッグ用）
    output_file = Path("test_koji_name_search_result.html")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(str(soup))
    print(f"検索結果ページのHTMLを保存: {output_file}")
    print()
    
    # 検索結果テーブルを探す
    result_table = soup.find("table", id="dgrSearchList")
    
    if not result_table:
        print("警告: dgrSearchListテーブルが見つかりませんでした")
        print("検索結果ページの構造を確認してください")
        return
    
    # テーブル内のすべての行を取得
    rows = result_table.find_all("tr")
    print(f"検索結果テーブルから{len(rows)}行を発見")
    print()
    
    # 工事名を抽出して確認
    print("=" * 80)
    print("検索結果の工事名一覧")
    print("=" * 80)
    
    koji_names = []
    for idx, row in enumerate(rows):
        # 工事名のリンクを探す
        detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
        if detail_link:
            koji_name = detail_link.get_text(strip=True)
            if not koji_name:
                # リンクのテキストが空の場合は、同じ行の他のセルから工事名を探す
                cells = row.find_all("td")
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if text and text != "":
                        koji_name = text
                        break
            
            if koji_name:
                koji_names.append(koji_name)
                # 「トンネル」を含むかチェック
                contains_tunnel = "トンネル" in koji_name
                status = "[OK]" if contains_tunnel else "[NG]"
                print(f"{idx+1:3d}. {status} {koji_name}")
    
    print()
    print("=" * 80)
    print("検索結果の統計")
    print("=" * 80)
    print(f"総件数: {len(koji_names)}")
    
    # 「トンネル」を含む工事名をカウント
    tunnel_count = sum(1 for name in koji_names if "トンネル" in name)
    non_tunnel_count = len(koji_names) - tunnel_count
    
    print(f"「トンネル」を含む: {tunnel_count}件")
    print(f"「トンネル」を含まない: {non_tunnel_count}件")
    print()
    
    if non_tunnel_count > 0:
        print("=" * 80)
        print("問題: 「トンネル」を含まない工事が検索結果に含まれています")
        print("=" * 80)
        print("「トンネル」を含まない工事名:")
        for name in koji_names:
            if "トンネル" not in name:
                print(f"  - {name}")
        print()
        print("考えられる原因:")
        print("1. サーバー側の検索フィルタリングが正しく動作していない")
        print("2. 検索フォームのパラメータ名が間違っている")
        print("3. 検索フォームのパラメータが正しく送信されていない")
    else:
        print("✓ すべての検索結果が「トンネル」を含んでいます")
    
    # 検索フォームのパラメータを確認
    print()
    print("=" * 80)
    print("検索フォームのパラメータ確認")
    print("=" * 80)
    
    # 検索結果ページのフォームを確認
    form = soup.find("form")
    if form:
        # hidden inputを確認
        hidden_inputs = form.find_all("input", type="hidden")
        print("Hidden inputs (一部):")
        for inp in hidden_inputs[:10]:  # 最初の10個のみ表示
            name = inp.get("name", "")
            value = inp.get("value", "")
            if "KojiName" in name or "koji" in name.lower():
                print(f"  {name} = {value[:50]}...")  # 最初の50文字のみ
    
    # 検索条件の入力フィールドを確認
    koji_name_input = soup.find("input", id=lambda x: x and "txtKojiName" in x)
    if koji_name_input:
        value = koji_name_input.get("value", "")
        print(f"工事名入力フィールドの値: '{value}'")
    else:
        print("警告: 工事名入力フィールドが見つかりませんでした")

if __name__ == "__main__":
    test_koji_name_search()
