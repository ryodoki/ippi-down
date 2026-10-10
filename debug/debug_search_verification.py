# -*- coding: utf-8 -*-
"""
検索フォームの送信を検証し、工事名フィルタが正しく機能しているか確認
"""

import requests
from bs4 import BeautifulSoup
import re

class SearchVerifier:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        })
    
    def close(self):
        self.session.close()

def get_all_hidden_inputs(soup):
    """全てのhidden inputを取得"""
    hidden = {}
    for inp in soup.find_all("input", type="hidden"):
        name = inp.get("name", "")
        value = inp.get("value", "")
        if name:
            hidden[name] = value
    return hidden

def main():
    client = SearchVerifier()
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print("="*60)
    print("検索フォーム検証: 工事名「トンネル」の検索")
    print("="*60)
    
    # 1. 検索条件ページを取得
    print("\n[1] 検索条件ページを取得")
    response = client.session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    
    # 2. フォームデータを構築
    print("\n[2] フォームデータを構築")
    hidden_inputs = get_all_hidden_inputs(soup)
    
    # 検索条件を設定
    form_data = hidden_inputs.copy()
    form_data.update({
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "drpTopKikanInf": "0",           # 国の機関
        "drpLargeKikanInf2": "21",        # 国土交通省
        "drpMiddleKikanInf": "02",        # 東北地方整備局
        "drpSmallKikanInf": "-1",         # 細分類なし
        "tbxKojiNm": "トンネル",           # 工事名 ★重要
        "KojiRadioGroup": "rbKojiDropList",  # リスト検索を選択
        "drpKojiDistrict": "-1",          # 地方なし
        "drpKojiPrefecture2": "-1",       # 都道府県なし
        "drpKojiCity": "-1",              # 市町村なし
        "drpKojiKbn": "",                 # 工事種別なし
        "drpKojiGyosyu": "",              # 工事の業種なし
        "drpCount": "20",                 # 表示件数20件
        "btnSearch": "検索開始",
    })
    
    # 送信するフォームデータの重要部分を表示
    print("  送信するフォームデータ（主要部分）:")
    important_keys = ["drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", 
                      "tbxKojiNm", "drpKojiKbn", "drpKojiGyosyu", "drpCount", "btnSearch"]
    for key in important_keys:
        if key in form_data:
            print(f"    {key} = '{form_data[key]}'")
    
    # 3. 検索を実行
    print("\n[3] 検索を実行")
    search_response = client.session.post(base_url, data=form_data, timeout=30)
    search_response.encoding = 'utf-8'
    search_soup = BeautifulSoup(search_response.text, "html.parser")
    
    print(f"  Status: {search_response.status_code}")
    print(f"  Response URL: {search_response.url}")
    print(f"  Page Title: {search_soup.title.string if search_soup.title else 'N/A'}")
    
    # 4. 検索結果を分析
    print("\n[4] 検索結果を分析")
    
    # 検索結果テーブルを探す
    result_table = search_soup.find("table", id="dgrSearchList")
    if not result_table:
        print("  [ERROR] 検索結果テーブル(dgrSearchList)が見つかりません")
        # ページの内容を確認
        print("\n  ページ内のテーブル:")
        for t in search_soup.find_all("table"):
            t_id = t.get("id", "")
            if t_id:
                print(f"    - {t_id}")
        return
    
    rows = result_table.find_all("tr")
    print(f"  検索結果テーブル: {len(rows)}行（ヘッダー含む）")
    
    # 工事名を抽出して「トンネル」が含まれているか確認
    print("\n[5] 検索結果の工事名を確認")
    koji_names = []
    tunnel_count = 0
    non_tunnel_count = 0
    
    for i, row in enumerate(rows[1:], 1):  # ヘッダーを除く
        # 工事名のリンクを探す
        detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
        if detail_link:
            koji_name = detail_link.get_text(strip=True)
            koji_names.append(koji_name)
            
            if "トンネル" in koji_name:
                tunnel_count += 1
                status = "[OK]"
            else:
                non_tunnel_count += 1
                status = "[NG]"
            
            # 最初の10件と、トンネルを含まないものを表示
            if i <= 10 or "トンネル" not in koji_name:
                print(f"  {i:2d}. {status} {koji_name[:50]}...")
    
    print(f"\n  --- 1ページ目の結果 ---")
    print(f"  総工事数: {len(koji_names)}")
    print(f"  「トンネル」を含む: {tunnel_count}")
    print(f"  「トンネル」を含まない: {non_tunnel_count}")
    
    # 6. 全ページの件数を確認
    print("\n[6] 全ページの件数を確認")
    total_koji = len(koji_names)
    page_num = 1
    current_soup = search_soup
    last_url = search_response.url
    
    # 次ページボタンを探す
    while True:
        next_btn = current_soup.find("input", {"id": "btnNext1"})
        if not next_btn or next_btn.get("disabled"):
            break
        
        page_num += 1
        
        # 次ページを取得
        form = current_soup.find("form")
        if form and form.get("action"):
            from urllib.parse import urljoin
            next_url = urljoin(last_url, form.get("action"))
        else:
            next_url = last_url
        
        next_hidden = get_all_hidden_inputs(current_soup)
        next_hidden["btnNext1"] = "次ページ"
        
        next_response = client.session.post(next_url, data=next_hidden, timeout=30)
        next_response.encoding = 'utf-8'
        current_soup = BeautifulSoup(next_response.text, "html.parser")
        last_url = next_response.url
        
        # このページの工事数をカウント
        result_table = current_soup.find("table", id="dgrSearchList")
        if result_table:
            page_rows = result_table.find_all("tr")[1:]  # ヘッダー除く
            page_koji = 0
            for row in page_rows:
                detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
                if detail_link:
                    page_koji += 1
                    koji_name = detail_link.get_text(strip=True)
                    if "トンネル" in koji_name:
                        tunnel_count += 1
                    else:
                        non_tunnel_count += 1
            
            total_koji += page_koji
            print(f"  ページ{page_num}: {page_koji}件（累計: {total_koji}件）")
        
        if page_num >= 10:  # 最大10ページ
            break
    
    print(f"\n  === 最終結果 ===")
    print(f"  総ページ数: {page_num}")
    print(f"  総工事数: {total_koji}")
    print(f"  「トンネル」を含む: {tunnel_count}")
    print(f"  「トンネル」を含まない: {non_tunnel_count}")
    
    if non_tunnel_count > 0:
        print(f"\n  [WARNING] 「トンネル」を含まない工事が{non_tunnel_count}件あります！")
        print("  → 検索条件が正しく適用されていない可能性があります")
    else:
        print(f"\n  [OK] 全ての工事に「トンネル」が含まれています")
    
    client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
