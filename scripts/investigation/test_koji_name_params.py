"""工事名検索のパラメータを確認するスクリプト"""

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
import json

def test_koji_name_params():
    """工事名検索のパラメータを確認"""
    
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
    print("工事名検索パラメータ確認テスト")
    print("=" * 80)
    print(f"検索条件 - 工事名: '{search_conditions.koji_name}'")
    print()
    
    # 初期ページを取得
    print("1. 初期ページを取得中...")
    soup = scraper.fetch_page(search_url)
    if not soup:
        print("エラー: 初期ページを取得できませんでした")
        return
    
    # 検索フォームのデータを構築
    print("2. 検索フォームのデータを構築中...")
    form_data = scraper._get_all_hidden_inputs(soup)
    search_form_data = scraper._build_search_form_data(search_conditions, soup)
    form_data.update(search_form_data)
    
    # 検索ボタンをクリック
    form_data["btnSearch"] = "検索開始"
    
    # 工事名関連のパラメータを確認
    print()
    print("=" * 80)
    print("送信されるパラメータ（工事名関連）")
    print("=" * 80)
    
    koji_name_params = {k: v for k, v in form_data.items() if "KojiName" in k or "koji" in k.lower()}
    if koji_name_params:
        for key, value in koji_name_params.items():
            print(f"  {key} = '{value}'")
    else:
        print("  工事名関連のパラメータが見つかりませんでした")
    
    # すべてのパラメータを確認（デバッグ用）
    print()
    print("=" * 80)
    print("送信されるパラメータ（すべて、最初の50個）")
    print("=" * 80)
    for idx, (key, value) in enumerate(list(form_data.items())[:50]):
        value_str = str(value)[:100] if value else ""
        print(f"  {idx+1:3d}. {key} = {value_str}")
    
    # パラメータをJSONファイルに保存
    output_file = Path("test_koji_name_params.json")
    # 値を文字列に変換（JSONシリアライズ可能にする）
    params_dict = {k: str(v) for k, v in form_data.items()}
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(params_dict, f, ensure_ascii=False, indent=2)
    print()
    print(f"パラメータをJSONファイルに保存: {output_file}")
    
    # 検索フォームのHTMLを確認
    print()
    print("=" * 80)
    print("検索フォームのHTML確認")
    print("=" * 80)
    
    # 工事名入力フィールドを探す
    koji_name_inputs = soup.find_all("input", id=lambda x: x and "KojiName" in x)
    if not koji_name_inputs:
        # name属性で探す
        all_inputs = soup.find_all("input")
        koji_name_inputs = [inp for inp in all_inputs if inp.get("name") and "KojiName" in inp.get("name", "")]
    
    if koji_name_inputs:
        print(f"工事名入力フィールドを{len(koji_name_inputs)}個発見:")
        for inp in koji_name_inputs:
            print(f"  id: {inp.get('id', 'N/A')}")
            print(f"  name: {inp.get('name', 'N/A')}")
            print(f"  value: {inp.get('value', 'N/A')}")
            print()
    else:
        print("工事名入力フィールドが見つかりませんでした")
        print("検索フォームのHTMLを確認してください")
        
        # すべてのinput要素を確認
        all_inputs = soup.find_all("input")
        print(f"\nすべてのinput要素（{len(all_inputs)}個）:")
        for inp in all_inputs[:20]:  # 最初の20個のみ
            inp_id = inp.get("id", "")
            inp_name = inp.get("name", "")
            if "koji" in inp_id.lower() or "koji" in inp_name.lower() or "工事" in inp_id or "工事" in inp_name:
                print(f"  id: {inp_id}, name: {inp_name}, type: {inp.get('type', 'N/A')}")
    
    # 実際に検索を実行して結果を確認
    print()
    print("=" * 80)
    print("検索を実行して結果を確認")
    print("=" * 80)
    
    response = http_client.post(search_url, data=form_data)
    if response.encoding:
        response.encoding = response.apparent_encoding or 'utf-8'
    else:
        response.encoding = 'utf-8'
    
    try:
        result_soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
    except (UnicodeDecodeError, LookupError):
        try:
            result_soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
        except UnicodeDecodeError:
            result_soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
    
    # 検索結果テーブルを確認
    result_table = result_soup.find("table", id="dgrSearchList")
    if result_table:
        rows = result_table.find_all("tr")
        print(f"検索結果: {len(rows)}行")
        
        # 最初の5件の工事名を表示
        print("\n最初の5件の工事名:")
        count = 0
        for row in rows:
            detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
            if detail_link:
                koji_name = detail_link.get_text(strip=True)
                if koji_name:
                    count += 1
                    contains_tunnel = "トンネル" in koji_name
                    status = "[OK]" if contains_tunnel else "[NG]"
                    print(f"  {count}. {status} {koji_name}")
                    if count >= 5:
                        break
    else:
        print("検索結果テーブルが見つかりませんでした")

if __name__ == "__main__":
    test_koji_name_params()
