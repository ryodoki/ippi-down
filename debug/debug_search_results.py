# -*- coding: utf-8 -*-
"""検索結果ページの工事名を確認するデバッグスクリプト"""

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

def main():
    client = SimpleHTTPClient()
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print("="*60)
    print("ステップ1: 検索条件ページを取得")
    print("="*60)
    response = client.get(base_url)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # hidden inputs を取得
    hidden_inputs = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            hidden_inputs[name] = value
    
    # 検索フォームを送信
    print("\n" + "="*60)
    print("ステップ2: 検索フォームを送信（トンネル検索）")
    print("="*60)
    
    form_data = hidden_inputs.copy()
    form_data.update({
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "drpTopKikanInf": "0",  # 国の機関
        "drpLargeKikanInf2": "21",  # 国土交通省
        "drpMiddleKikanInf": "02",  # 東北地方整備局
        "drpSmallKikanInf": "-1",  # 細分類なし
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
    
    print(f"レスポンスURL: {response.url}")
    print(f"ページタイトル: {soup.title.string if soup.title else 'なし'}")
    
    # dgrSearchListテーブルを探す
    result_table = soup.find("table", id="dgrSearchList")
    if not result_table:
        print("検索結果テーブルが見つかりません！")
        # HTMLの一部を出力
        print(f"HTML先頭1000文字:\n{response.text[:1000]}")
        return
    
    rows = result_table.find_all("tr")
    print(f"検索結果テーブル: {len(rows)}行 (ヘッダー含む)")
    
    # 各行から工事名を抽出
    print("\n" + "="*60)
    print("ステップ3: 検索結果ページの工事名を確認")
    print("="*60)
    
    koji_names = []
    for i, row in enumerate(rows[1:], 1):  # ヘッダーを除く
        # __doPostBackリンクを探す
        detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
        if detail_link:
            koji_name = detail_link.get_text(strip=True)
            koji_names.append(koji_name)
            # 「トンネル」が含まれているか確認
            has_tunnel = "トンネル" in koji_name
            status = "OK" if has_tunnel else "NG"
            print(f"  [{i:2d}] {status} {koji_name[:60]}")
    
    print("\n" + "="*60)
    print("ステップ4: 分析")
    print("="*60)
    
    tunnel_count = sum(1 for name in koji_names if "トンネル" in name)
    print(f"工事数: {len(koji_names)}")
    print(f"'トンネル'を含む工事: {tunnel_count}")
    print(f"'トンネル'を含まない工事: {len(koji_names) - tunnel_count}")
    
    # ブラウザと同じように検索結果に「トンネル」が含まれているか確認
    if tunnel_count == 0:
        print("\n⚠ 警告: 検索結果に'トンネル'を含む工事がありません！")
        print("これは、検索条件が正しくサーバーに送信されていない可能性があります。")
        print("\n最初の5件の工事名:")
        for i, name in enumerate(koji_names[:5], 1):
            print(f"  {i}. {name}")
    
    client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
