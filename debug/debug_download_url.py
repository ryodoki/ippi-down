# -*- coding: utf-8 -*-
"""
ダウンロードURL問題を調査するスクリプト
"""

import sys
from pathlib import Path
import io
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# UTF-8出力を強制
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print("="*70)
    print("ダウンロードURL調査")
    print("="*70)
    
    # 検索ページを取得
    response = session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # hidden inputsを取得
    form_data = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            form_data[name] = value
    
    # 大分類選択: 国の機関
    form_data["__EVENTTARGET"] = "drpTopKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"  # 国の機関
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # hidden inputsを再取得
    form_data = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            form_data[name] = value
    
    # 中分類選択: 国土交通省
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"  # 国土交通省
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # hidden inputsを再取得
    form_data = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            form_data[name] = value
    
    # 小分類選択: 東北地方整備局
    form_data["__EVENTTARGET"] = "drpMiddleKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"
    form_data["drpMiddleKikanInf"] = "02"  # 東北地方整備局
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 検索実行
    form_data = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            form_data[name] = value
    
    form_data["__EVENTTARGET"] = ""
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"
    form_data["drpMiddleKikanInf"] = "02"
    form_data["tbxKojiNm"] = "トンネル"
    form_data["btnSearch"] = "検索開始"
    
    response = session.post(base_url, data=form_data, timeout=30, allow_redirects=True)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    last_url = response.url
    
    print(f"\n[1] 検索結果ページURL: {last_url}")
    
    # 最初の工事の詳細ページにアクセス
    result_table = soup.find("table", id="dgrSearchList")
    if not result_table:
        print("検索結果テーブルが見つかりません")
        return
    
    rows = result_table.find_all("tr")[1:]  # ヘッダー除く
    print(f"検索結果: {len(rows)}件")
    
    if not rows:
        return
    
    # 最初の行の詳細ページにアクセス
    first_row = rows[0]
    detail_link = first_row.find("a", href=lambda x: x and "__doPostBack" in x)
    if not detail_link:
        print("詳細リンクが見つかりません")
        return
    
    koji_name = detail_link.get_text(strip=True)
    href = detail_link.get("href", "")
    print(f"\n[2] 最初の工事: {koji_name}")
    print(f"  リンク: {href}")
    
    # __doPostBackのパラメータを解析
    import re
    match = re.search(r"__doPostBack\('([^']+)','([^']+)'\)", href)
    if not match:
        print("__doPostBackのパラメータを解析できません")
        return
    
    event_target = match.group(1)
    event_argument = match.group(2)
    
    # 詳細ページにPOSTアクセス
    form_data = {}
    for hidden in soup.find_all("input", type="hidden"):
        name = hidden.get("name", "")
        value = hidden.get("value", "")
        if name:
            form_data[name] = value
    
    form_data["__EVENTTARGET"] = event_target
    form_data["__EVENTARGUMENT"] = event_argument
    
    form = soup.find("form")
    if form and form.get("action"):
        post_url = urljoin(last_url, form.get("action"))
    else:
        post_url = last_url
    
    print(f"\n[3] 詳細ページにPOSTアクセス: {post_url}")
    
    response = session.post(post_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    detail_soup = BeautifulSoup(response.text, "html.parser")
    
    print(f"  レスポンスURL: {response.url}")
    
    # 詳細ページのタイトルを確認
    title = detail_soup.find("title")
    print(f"  ページタイトル: {title.get_text().strip() if title else '不明'}")
    
    # ファイルリンクを探す
    print(f"\n[4] ファイルリンクの調査")
    
    # dgrKokokuとdgrKeikaテーブルを探す
    for table_id in ["dgrKokoku", "dgrKeika"]:
        table = detail_soup.find("table", id=table_id)
        if table:
            print(f"\n  テーブル '{table_id}' を発見")
            links = table.find_all("a", href=True)
            for i, link in enumerate(links[:5]):
                href = link.get("href", "")
                text = link.get_text(strip=True)
                full_url = urljoin(response.url, href)
                
                print(f"\n    リンク{i+1}: {text}")
                print(f"      href: {href[:100]}...")
                print(f"      完全URL: {full_url[:100]}...")
                
                # URLのドメインを確認
                parsed = urlparse(full_url)
                print(f"      ドメイン: {parsed.netloc}")
                
                # PDFリンクの場合、ダウンロードを試行
                if ".pdf" in href.lower() or "servlet" in href.lower():
                    print(f"\n  [5] ダウンロード試行: {full_url[:80]}...")
                    
                    dl_response = session.get(full_url, stream=True, timeout=30, allow_redirects=True)
                    print(f"      ステータス: {dl_response.status_code}")
                    print(f"      最終URL: {dl_response.url}")
                    print(f"      Content-Type: {dl_response.headers.get('Content-Type', '不明')}")
                    print(f"      Content-Length: {dl_response.headers.get('Content-Length', '不明')}")
                    
                    # 最初の100バイトを確認
                    first_bytes = dl_response.content[:100]
                    if first_bytes.startswith(b'%PDF'):
                        print(f"      内容: PDF (正常)")
                    elif b'<html' in first_bytes.lower() or b'<!doctype' in first_bytes.lower():
                        print(f"      内容: HTML (失敗)")
                        # HTMLの最初の部分を表示
                        try:
                            html_preview = first_bytes.decode('utf-8', errors='replace')[:200]
                            print(f"      HTMLプレビュー: {html_preview}")
                        except:
                            pass
                    else:
                        print(f"      内容: 不明 ({first_bytes[:20]})")
                    
                    break  # 最初のリンクだけテスト
    
    # 全てのリンクを確認
    print(f"\n[6] ページ内の全てのPDF/ダウンロードリンク")
    all_links = detail_soup.find_all("a", href=True)
    pdf_links = []
    for link in all_links:
        href = link.get("href", "")
        if ".pdf" in href.lower() or "download" in href.lower() or "servlet" in href.lower():
            full_url = urljoin(response.url, href)
            text = link.get_text(strip=True)
            pdf_links.append((text, href, full_url))
    
    print(f"  PDF/ダウンロードリンク数: {len(pdf_links)}")
    for i, (text, href, full_url) in enumerate(pdf_links[:10]):
        parsed = urlparse(full_url)
        print(f"    {i+1}. {text[:30]:30s} -> {parsed.netloc}")
    
    session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
