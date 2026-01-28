# -*- coding: utf-8 -*-
"""
ダウンロード失敗の原因を調査するスクリプト
HTMLが返される原因を特定する
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import time

class DownloadDebugger:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        })
    
    def close(self):
        self.session.close()

def main():
    client = DownloadDebugger()
    
    # テスト用のダウンロードURL（ログから抽出した失敗URL）
    test_urls = [
        "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?AnkenKanriNo=021020002025412000000566&BunshoKanriId=40",
        "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?AnkenKanriNo=021020002025412000000537&BunshoKanriId=40",
    ]
    
    print("="*60)
    print("ダウンロード失敗の原因調査")
    print("="*60)
    
    # まず、ppi.jpで検索を行いセッションを確立
    print("\n[1] ppi.jpにアクセスしてセッションを確立")
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    response = client.session.get(base_url, timeout=30)
    print(f"  Status: {response.status_code}")
    print(f"  Cookies: {dict(client.session.cookies)}")
    
    # 検索を実行してセッションを維持
    print("\n[2] 検索を実行")
    soup = BeautifulSoup(response.text, "html.parser")
    hidden_inputs = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            hidden_inputs[name] = value
    
    form_data = hidden_inputs.copy()
    form_data.update({
        "drpTopKikanInf": "0",  # 国の機関
        "drpLargeKikanInf2": "21",  # 国土交通省
        "drpMiddleKikanInf": "02",  # 東北地方整備局
        "tbxKojiNm": "トンネル",
        "btnSearch": "検索開始",
    })
    
    search_response = client.session.post(base_url, data=form_data, timeout=30)
    print(f"  Status: {search_response.status_code}")
    print(f"  URL: {search_response.url}")
    
    # 詳細ページにアクセス
    print("\n[3] 詳細ページにアクセス")
    search_soup = BeautifulSoup(search_response.text, "html.parser")
    
    # 最初の工事リンクを探す
    result_table = search_soup.find("table", id="dgrSearchList")
    if result_table:
        first_link = result_table.find("a", href=lambda x: x and "__doPostBack" in x)
        if first_link:
            import re
            match = re.search(r"__doPostBack\('([^']+)','([^']+)'\)", first_link.get("href", ""))
            if match:
                event_target = match.group(1)
                event_argument = match.group(2)
                
                # 詳細ページに遷移
                form = search_soup.find("form")
                post_url = search_response.url
                
                detail_hidden = {}
                for hidden in search_soup.find_all("input", type="hidden"):
                    name = hidden.get("name", "")
                    value = hidden.get("value", "")
                    if name:
                        detail_hidden[name] = value
                
                detail_hidden["__EVENTTARGET"] = event_target
                detail_hidden["__EVENTARGUMENT"] = event_argument
                
                detail_response = client.session.post(post_url, data=detail_hidden, timeout=30)
                print(f"  Status: {detail_response.status_code}")
                print(f"  URL: {detail_response.url}")
                
                detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                
                # 詳細ページからダウンロードリンクを探す
                print("\n[4] 詳細ページからダウンロードリンクを抽出")
                download_links = []
                for a in detail_soup.find_all("a", href=True):
                    href = a.get("href", "")
                    if "KokaiBunshoServlet" in href or href.endswith(".pdf"):
                        download_links.append(href)
                        print(f"  Found: {href[:80]}...")
                
                if download_links:
                    print(f"\n[5] ダウンロードURLに直接アクセス（セッション維持）")
                    test_url = download_links[0]
                    if not test_url.startswith("http"):
                        from urllib.parse import urljoin
                        test_url = urljoin(detail_response.url, test_url)
                    
                    print(f"  URL: {test_url}")
                    print(f"  Cookies: {dict(client.session.cookies)}")
                    
                    # Refererを設定してダウンロード
                    headers = {
                        "Referer": detail_response.url,
                        "Accept": "application/pdf,*/*",
                    }
                    
                    dl_response = client.session.get(test_url, headers=headers, timeout=60, allow_redirects=True)
                    print(f"  Status: {dl_response.status_code}")
                    print(f"  Content-Type: {dl_response.headers.get('Content-Type')}")
                    print(f"  Content-Length: {dl_response.headers.get('Content-Length')}")
                    print(f"  Final URL: {dl_response.url}")
                    
                    if "text/html" in dl_response.headers.get("Content-Type", ""):
                        print("\n  [!] HTMLが返されました")
                        dl_soup = BeautifulSoup(dl_response.text, "html.parser")
                        print(f"  Title: {dl_soup.title.string if dl_soup.title else 'なし'}")
                        
                        # HTMLの内容を分析
                        print("\n  HTML内容の分析:")
                        body = dl_soup.find("body")
                        if body:
                            text = body.get_text(strip=True)[:500]
                            print(f"  {text}")
                    else:
                        print("\n  [OK] PDFファイルが返されました")
                        print(f"  ファイルサイズ: {len(dl_response.content)} bytes")
    
    client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
