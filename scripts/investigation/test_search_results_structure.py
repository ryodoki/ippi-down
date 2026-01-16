"""検索結果ページのHTML構造を確認するスクリプト"""

import sys
import io
from pathlib import Path

# WindowsのコンソールでUTF-8を正しく表示するための設定
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from bs4 import BeautifulSoup
from src.core.scraper import Scraper
from src.models.config_model import SearchConditions
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger
import json
from datetime import datetime


def analyze_search_results_structure(soup: BeautifulSoup, output_file: str = "search_results_structure.html"):
    """検索結果ページのHTML構造を解析"""
    print("\n" + "="*80)
    print("検索結果ページのHTML構造解析")
    print("="*80)
    
    # HTMLをファイルに保存
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(soup.prettify())
    print(f"\nHTMLを保存しました: {output_file}")
    
    # 検索結果テーブルを探す
    print("\n--- 検索結果テーブルの探索 ---")
    
    # 一般的なテーブル構造を探す
    tables = soup.find_all("table")
    print(f"テーブル数: {len(tables)}")
    
    for i, table in enumerate(tables):
        print(f"\nテーブル {i+1}:")
        print(f"  ID: {table.get('id', 'なし')}")
        print(f"  Class: {table.get('class', 'なし')}")
        rows = table.find_all("tr")
        print(f"  行数: {len(rows)}")
        if rows:
            # 最初の数行を表示
            for j, row in enumerate(rows[:3]):
                cells = row.find_all(["td", "th"])
                cell_texts = []
                for cell in cells:
                    text = cell.get_text(strip=True)[:50]
                    # エンコーディングエラーを回避
                    try:
                        text.encode('utf-8')
                        cell_texts.append(text)
                    except UnicodeEncodeError:
                        cell_texts.append(text.encode('utf-8', errors='replace').decode('utf-8'))
                print(f"    行 {j+1}: {cell_texts}")
    
    # GridViewやDataGridを探す
    print("\n--- GridView/DataGridの探索 ---")
    gridviews = soup.find_all(id=lambda x: x and ("grid" in x.lower() or "datagrid" in x.lower() or "result" in x.lower()))
    print(f"GridView/DataGrid候補: {len(gridviews)}")
    for gv in gridviews:
        print(f"  ID: {gv.get('id')}, Class: {gv.get('class')}")
    
    # 検索結果の各行を探す
    print("\n--- 検索結果行の探索 ---")
    
    # リンクを探す（詳細ページへのリンク）
    links = soup.find_all("a", href=True)
    detail_links = [link for link in links if "Detail" in link.get("href", "") or "detail" in link.get("href", "")]
    print(f"詳細ページへのリンク数: {len(detail_links)}")
    
    if detail_links:
        print("\n最初の5つの詳細リンク:")
        for i, link in enumerate(detail_links[:5]):
            print(f"  {i+1}. {link.get('href')[:100]}")
            print(f"     テキスト: {link.get_text(strip=True)[:50]}")
            # 親要素の情報を取得
            parent = link.parent
            if parent:
                print(f"     親要素: {parent.name}, テキスト: {parent.get_text(strip=True)[:100]}")
    
    # 工事名を探す
    print("\n--- 工事名の探索 ---")
    
    # 工事名が含まれそうな要素を探す
    koji_name_patterns = [
        "工事名",
        "工事名称",
        "案件名",
        "koji",
        "name"
    ]
    
    for pattern in koji_name_patterns:
        elements = soup.find_all(string=lambda text: text and pattern in text)
        if elements:
            print(f"\n'{pattern}'を含む要素: {len(elements)}個")
            for elem in elements[:3]:
                parent = elem.parent
                if parent:
                    print(f"  テキスト: {elem.strip()[:50]}")
                    print(f"  親要素: {parent.name}, 属性: {parent.attrs}")
    
    # 工事場所を探す
    print("\n--- 工事場所の探索 ---")
    
    place_patterns = [
        "工事場所",
        "場所",
        "都道府県",
        "市町村",
        "place",
        "location"
    ]
    
    for pattern in place_patterns:
        elements = soup.find_all(string=lambda text: text and pattern in text)
        if elements:
            print(f"\n'{pattern}'を含む要素: {len(elements)}個")
            for elem in elements[:3]:
                parent = elem.parent
                if parent:
                    print(f"  テキスト: {elem.strip()[:50]}")
                    print(f"  親要素: {parent.name}, 属性: {parent.attrs}")
    
    # 発注機関を探す
    print("\n--- 発注機関の探索 ---")
    
    kikan_patterns = [
        "発注機関",
        "機関",
        "kikan",
        "organization"
    ]
    
    for pattern in kikan_patterns:
        elements = soup.find_all(string=lambda text: text and pattern in text)
        if elements:
            print(f"\n'{pattern}'を含む要素: {len(elements)}個")
            for elem in elements[:3]:
                parent = elem.parent
                if parent:
                    print(f"  テキスト: {elem.strip()[:50]}")
                    print(f"  親要素: {parent.name}, 属性: {parent.attrs}")


def extract_search_result_items(soup: BeautifulSoup, search_conditions: SearchConditions):
    """検索結果から各案件の情報を抽出"""
    print("\n" + "="*80)
    print("検索結果から各案件の情報を抽出")
    print("="*80)
    
    items = []
    
    # 検索結果テーブルを探す
    # 一般的な構造: table > tbody > tr > td
    tables = soup.find_all("table")
    
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:  # ヘッダー行のみの場合はスキップ
            continue
        
        print(f"\nテーブルを解析中: ID={table.get('id')}, Class={table.get('class')}, 行数={len(rows)}")
        
        # ヘッダー行を探す
        header_row = None
        for row in rows:
            cells = row.find_all(["th", "td"])
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            if any("工事名" in text or "発注機関" in text or "場所" in text for text in cell_texts):
                header_row = row
                print(f"  ヘッダー行を発見: {cell_texts}")
                break
        
        # データ行を抽出
        data_rows = rows[1:] if header_row else rows
        
        for i, row in enumerate(data_rows):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            
            item = {
                "row_index": i,
                "cells": []
            }
            
            # 各セルの情報を取得
            for j, cell in enumerate(cells):
                cell_text = cell.get_text(strip=True)
                cell_info = {
                    "index": j,
                    "text": cell_text,
                    "html": str(cell)[:200],
                    "links": []
                }
                
                # リンクを取得
                links = cell.find_all("a", href=True)
                for link in links:
                    cell_info["links"].append({
                        "href": link.get("href"),
                        "text": link.get_text(strip=True)
                    })
                
                item["cells"].append(cell_info)
            
            # 工事名、発注機関、場所を探す
            for cell_info in item["cells"]:
                text = cell_info["text"]
                # 工事名の可能性
                if len(text) > 5 and len(text) < 100 and not any(x in text for x in ["年", "月", "日", "円", "件"]):
                    if "koji_name" not in item:
                        item["koji_name"] = text
                # 発注機関の可能性
                if any(x in text for x in ["省", "庁", "局", "市", "県", "町", "村"]):
                    if "hachu_kikan" not in item:
                        item["hachu_kikan"] = text
                # 場所の可能性
                if any(x in text for x in ["都", "道", "府", "県", "市", "区", "町", "村"]):
                    if "place" not in item:
                        item["place"] = text
            
            if item["cells"]:
                items.append(item)
    
    print(f"\n抽出した案件数: {len(items)}")
    
    # 最初の3件を詳細表示
    for i, item in enumerate(items[:3]):
        print(f"\n案件 {i+1}:")
        print(f"  工事名: {item.get('koji_name', '不明')}")
        print(f"  発注機関: {item.get('hachu_kikan', '不明')}")
        print(f"  場所: {item.get('place', '不明')}")
        print(f"  セル数: {len(item['cells'])}")
        for cell in item["cells"][:3]:
            print(f"    セル {cell['index']}: {cell['text'][:50]}")
    
    return items


def verify_search_conditions(items: list, search_conditions: SearchConditions):
    """検索条件と照合"""
    print("\n" + "="*80)
    print("検索条件との照合")
    print("="*80)
    
    print(f"\n検索条件:")
    print(f"  大分類: {search_conditions.hachu_daibunrui}")
    print(f"  中分類: {search_conditions.hachu_chubunrui}")
    print(f"  小分類: {search_conditions.hachu_shoubunrui}")
    print(f"  細分類: {search_conditions.hachu_saibunrui}")
    print(f"  工事名: {search_conditions.koji_name}")
    print(f"  工事場所（都道府県）: {search_conditions.place_todofuken}")
    
    matched = 0
    unmatched = 0
    
    for i, item in enumerate(items):
        is_matched = True
        reasons = []
        
        # 工事名の照合
        if search_conditions.koji_name:
            item_koji_name = item.get("koji_name", "")
            if search_conditions.koji_name not in item_koji_name:
                is_matched = False
                reasons.append(f"工事名不一致: '{item_koji_name}' に '{search_conditions.koji_name}' が含まれない")
        
        # 工事場所の照合
        if search_conditions.place_todofuken:
            item_place = item.get("place", "")
            if search_conditions.place_todofuken not in item_place:
                is_matched = False
                reasons.append(f"場所不一致: '{item_place}' に '{search_conditions.place_todofuken}' が含まれない")
        
        if is_matched:
            matched += 1
        else:
            unmatched += 1
            if unmatched <= 5:  # 最初の5件のみ表示
                print(f"\n案件 {i+1} - 不一致:")
                print(f"  工事名: {item.get('koji_name', '不明')}")
                print(f"  発注機関: {item.get('hachu_kikan', '不明')}")
                print(f"  場所: {item.get('place', '不明')}")
                print(f"  理由: {', '.join(reasons)}")
    
    print(f"\n照合結果:")
    print(f"  一致: {matched}件")
    print(f"  不一致: {unmatched}件")
    print(f"  合計: {len(items)}件")


def main():
    """メイン処理"""
    print("="*80)
    print("検索結果ページのHTML構造確認スクリプト")
    print("="*80)
    
    # ロガーを初期化
    logger = Logger()
    
    # HTTPクライアントを初期化
    http_client = HTTPClient(logger)
    
    # Scraperを初期化
    scraper = Scraper(http_client, logger)
    
    # 検索条件を設定（実際の検索条件に合わせて変更してください）
    search_conditions = SearchConditions(
        hachu_daibunrui="国の機関",
        hachu_chubunrui="国土交通省",
        hachu_shoubunrui="東北地方整備局",
        hachu_saibunrui="",
        koji_name="",
        place_todofuken="",  # 横浜が混ざっている問題を確認するため、都道府県を指定
    )
    
    # 検索URL
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print(f"\n検索条件:")
    print(f"  大分類: {search_conditions.hachu_daibunrui}")
    print(f"  中分類: {search_conditions.hachu_chubunrui}")
    print(f"  小分類: {search_conditions.hachu_shoubunrui}")
    print(f"  細分類: {search_conditions.hachu_saibunrui}")
    print(f"  工事名: {search_conditions.koji_name}")
    print(f"  工事場所（都道府県）: {search_conditions.place_todofuken}")
    print(f"\n検索URL: {search_url}")
    
    # 検索フォームを送信
    print("\n検索フォームを送信中...")
    soup = scraper.submit_search_form(search_url, search_conditions)
    
    if not soup:
        print("エラー: 検索結果ページの取得に失敗しました")
        return
    
    print("検索結果ページを取得しました")
    
    # HTML構造を解析
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_file = f"search_results_structure_{timestamp}.html"
    analyze_search_results_structure(soup, html_file)
    
    # 検索結果から各案件の情報を抽出
    items = extract_search_result_items(soup, search_conditions)
    
    # 検索条件と照合
    verify_search_conditions(items, search_conditions)
    
    # 結果をJSONファイルに保存
    json_file = f"search_results_items_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"\n抽出結果を保存しました: {json_file}")
    
    print("\n" + "="*80)
    print("完了")
    print("="*80)


if __name__ == "__main__":
    main()
