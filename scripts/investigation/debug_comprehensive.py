# -*- coding: utf-8 -*-
"""総合的なデバッグスクリプト - ブラウザとrequestsの差分を徹底調査"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

class DebugHTTPClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        })
    
    def get(self, url):
        return self.session.get(url, timeout=30)
    
    def post(self, url, data=None):
        return self.session.post(url, data=data, timeout=30)
    
    def close(self):
        self.session.close()

def get_hidden_inputs(soup):
    """Hidden inputsを取得"""
    hidden_inputs = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            hidden_inputs[name] = value
    return hidden_inputs

def analyze_search_results(soup, page_num):
    """検索結果ページを分析"""
    print(f"\n--- ページ {page_num} の分析 ---")
    
    # dgrSearchListテーブルを探す
    result_table = soup.find("table", id="dgrSearchList")
    if not result_table:
        print("  [ERROR] dgrSearchListテーブルが見つかりません！")
        # 他のテーブルを探す
        all_tables = soup.find_all("table")
        print(f"  ページ内のテーブル数: {len(all_tables)}")
        for i, t in enumerate(all_tables[:5]):
            print(f"    テーブル{i}: id={t.get('id')}, class={t.get('class')}")
        return 0
    
    rows = result_table.find_all("tr")
    print(f"  検索結果テーブル: {len(rows)}行 (ヘッダー含む)")
    
    # 工事数をカウント
    koji_count = 0
    for row in rows[1:]:  # ヘッダーを除く
        detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
        if detail_link:
            koji_count += 1
    
    print(f"  工事数: {koji_count}")
    return koji_count

def main():
    client = DebugHTTPClient()
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print("="*60)
    print("総合デバッグ: ブラウザとrequestsの差分調査")
    print("="*60)
    
    # 1. 検索条件ページを取得
    print("\n[1] 検索条件ページを取得")
    response = client.get(base_url)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  ステータス: {response.status_code}")
    
    # 2. 検索フォームを送信
    print("\n[2] 検索フォームを送信（トンネル検索）")
    hidden_inputs = get_hidden_inputs(soup)
    
    form_data = hidden_inputs.copy()
    form_data.update({
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "drpTopKikanInf": "0",  # 国の機関
        "drpLargeKikanInf2": "21",  # 国土交通省
        "drpMiddleKikanInf": "02",  # 東北地方整備局
        "drpSmallKikanInf": "-1",
        "tbxKojiNm": "トンネル",  # 工事名（正しいフィールド名）
        "rdoBasho1": "rdoBasho1",
        "drpArea": "-1",
        "drpPrefecture": "-1",
        "drpCity": "-1",
        "chkNyusatsuKeiyakuHosiki1": "on",
        "chkNyusatsuKeiyakuHosiki2": "on",
        "chkNyusatsuKeiyakuHosiki3": "on",
        "chkNyusatsuKeiyakuHosiki4": "on",
        "chkNyusatsuKeiyakuHosiki5": "on",
        "rdoDate1": "rdoDate1",
        "rdoKokokuStartDate1": "rdoKokokuStartDate1",
        "rdoKaisatsuStartDate1": "rdoKaisatsuStartDate1",
        "rdoKeiyakuStartDate1": "rdoKeiyakuStartDate1",
        "drpKojiType": "-1",
        "drpKojiGyoshu": "-1",
        "drpListCnt": "20",
        "btnSearch": "検索開始",
    })
    
    response = client.post(base_url, data=form_data)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    print(f"  レスポンスURL: {response.url}")
    print(f"  ページタイトル: {soup.title.string if soup.title else 'なし'}")
    
    # 検索結果の件数表示を探す
    total_count_elem = soup.find("span", id=lambda x: x and "Count" in str(x))
    if total_count_elem:
        print(f"  検索結果件数: {total_count_elem.text}")
    
    # 検索結果全体の件数を探す
    count_text = soup.find(string=re.compile(r'\d+件'))
    if count_text:
        print(f"  件数表示: {count_text.strip()[:50]}")
    
    total_koji = 0
    page_num = 1
    current_soup = soup
    last_url = response.url
    
    # 全ページを処理
    while page_num <= 10:  # 最大10ページ
        koji_count = analyze_search_results(current_soup, page_num)
        total_koji += koji_count
        
        if koji_count == 0:
            print(f"  [STOP] ページ{page_num}で工事が0件のため終了")
            break
        
        # 次ページボタンを探す
        next_btn = current_soup.find("input", {"id": "btnNext1"})
        if not next_btn:
            next_btn = current_soup.find("input", {"type": "submit", "value": "次ページ"})
        
        if not next_btn:
            print(f"  [INFO] 次ページボタンなし - 全ページ処理完了")
            break
        
        # 次ページのURLを決定
        form = current_soup.find("form")
        if form and form.get("action"):
            next_url = urljoin(last_url, form.get("action"))
        else:
            next_url = last_url
        
        print(f"  次ページURL: {next_url}")
        
        # 次ページを取得
        next_hidden = get_hidden_inputs(current_soup)
        next_hidden[next_btn.get("name", "btnNext1")] = next_btn.get("value", "次ページ")
        
        response = client.post(next_url, data=next_hidden)
        response.encoding = 'utf-8'
        current_soup = BeautifulSoup(response.text, "html.parser")
        last_url = response.url
        page_num += 1
    
    print(f"\n--- 総計 ---")
    print(f"  処理ページ数: {page_num}")
    print(f"  総工事数: {total_koji}")
    
    # 3. ダウンロード失敗URLの調査
    print("\n[3] ダウンロードURL調査")
    test_url = "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?AnkenKanriNo=021020002025412000000566&BunshoKanriId=40"
    
    print(f"  テストURL: {test_url}")
    print(f"  Cookies: {dict(client.session.cookies)}")
    
    # Refererを設定してリクエスト
    headers = {
        "Referer": "https://www.i-ppi.jp/",
    }
    dl_response = client.session.get(test_url, headers=headers, timeout=30, allow_redirects=True)
    print(f"  Content-Type: {dl_response.headers.get('Content-Type')}")
    print(f"  Content-Length: {dl_response.headers.get('Content-Length')}")
    print(f"  レスポンスの先頭100バイト: {dl_response.content[:100]}")
    
    if "text/html" in dl_response.headers.get("Content-Type", ""):
        print("  [WARNING] HTMLが返されました - ダウンロード失敗の可能性")
        print(f"  HTMLタイトル: {BeautifulSoup(dl_response.text, 'html.parser').title}")
    
    client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
