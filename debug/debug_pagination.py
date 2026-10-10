# -*- coding: utf-8 -*-
"""ページネーションのデバッグスクリプト"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

class SimpleHTTPClient:
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

HTTPClient = SimpleHTTPClient

def main():
    client = HTTPClient()
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print("="*60)
    print("ステップ1: 検索条件ページを取得")
    print("="*60)
    response = client.get(base_url)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"レスポンスステータス: {response.status_code}")
    print(f"コンテンツ長: {len(response.content)} bytes")
    print(f"ページタイトル: {soup.title.string if soup.title else 'なし'}")
    
    # フォームaction属性を確認
    form = soup.find("form")
    print(f"フォームaction: {form.get('action') if form else 'フォームなし'}")
    
    # hidden inputs を取得
    hidden_inputs = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            hidden_inputs[name] = value
    
    print(f"Hidden inputs: {list(hidden_inputs.keys())}")
    
    # 検索フォームを送信（大分類=国の機関、中分類=国土交通省、小分類=東北地方整備局、工事名=トンネル）
    print("\n" + "="*60)
    print("ステップ2: 検索フォームを送信")
    print("="*60)
    
    form_data = hidden_inputs.copy()
    form_data.update({
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "drpTopKikanInf": "0",  # 国の機関
        "drpLargeKikanInf2": "21",  # 国土交通省
        "drpMiddleKikanInf": "02",  # 東北地方整備局
        "drpSmallKikanInf": "-1",  # 細分類なし
        "txtKojiNm": "トンネル",  # 工事名
        "rdoBasho1": "rdoBasho1",  # 地方（リスト検索）
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
        "drpListCnt": "20",  # 20件表示
        "btnSearch": "検索開始",
    })
    
    response = client.post(base_url, data=form_data)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    print(f"レスポンスステータス: {response.status_code}")
    print(f"レスポンスURL: {response.url}")
    print(f"コンテンツ長: {len(response.content)} bytes")
    print(f"ページタイトル: {soup.title.string if soup.title else 'なし'}")
    
    # dgrSearchListテーブルを探す
    result_table = soup.find("table", id="dgrSearchList")
    if result_table:
        rows = result_table.find_all("tr")
        print(f"検索結果テーブル: {len(rows)}行 (ヘッダー含む)")
    else:
        print("検索結果テーブルが見つかりません")
    
    # フォームaction属性を確認
    form = soup.find("form")
    form_action = form.get('action') if form else None
    print(f"フォームaction: {form_action}")
    
    # 次ページボタンを探す
    next_btn = soup.find("input", {"id": "btnNext1"})
    if not next_btn:
        next_btn = soup.find("input", {"type": "submit", "value": "次ページ"})
    print(f"次ページボタン: {next_btn.get('name') if next_btn else 'なし'}")
    
    print("\n" + "="*60)
    print("ステップ3: 次ページをクリック")
    print("="*60)
    
    if next_btn:
        # 次ページのPOST先URLを決定
        if form_action:
            next_page_url = urljoin(base_url, form_action)
        else:
            next_page_url = response.url
        
        print(f"POST先URL: {next_page_url}")
        
        # フォームデータを準備
        form_data = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                form_data[name] = value
        
        # 次ページボタンを追加
        btn_name = next_btn.get("name", "")
        btn_value = next_btn.get("value", "次ページ")
        form_data[btn_name] = btn_value
        
        print(f"ボタン: {btn_name}={btn_value}")
        print(f"フォームデータ: {len(form_data)}個")
        
        response = client.post(next_page_url, data=form_data)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        
        print(f"\nレスポンスステータス: {response.status_code}")
        print(f"レスポンスURL: {response.url}")
        print(f"コンテンツ長: {len(response.content)} bytes")
        print(f"ページタイトル: {soup.title.string if soup.title else 'なし'}")
        
        # dgrSearchListテーブルを探す
        result_table = soup.find("table", id="dgrSearchList")
        if result_table:
            rows = result_table.find_all("tr")
            print(f"検索結果テーブル: {len(rows)}行 (ヘッダー含む)")
            
            # 2ページ目のフォームaction属性を確認
            form = soup.find("form")
            form_action_2 = form.get('action') if form else None
            print(f"2ページ目のフォームaction: {form_action_2}")
            
            # 次ページボタンを探す
            next_btn_2 = soup.find("input", {"id": "btnNext1"})
            if not next_btn_2:
                next_btn_2 = soup.find("input", {"type": "submit", "value": "次ページ"})
            print(f"次ページボタン: {next_btn_2.get('name') if next_btn_2 else 'なし'}")
        else:
            print("検索結果テーブルが見つかりません")
            # ページの内容を一部表示
            body_text = soup.get_text()[:500]
            print(f"ページ内容（先頭500文字）:\n{body_text}")
    
    client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
