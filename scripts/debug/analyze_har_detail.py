"""HARファイルを解析して詳細ページの構造を確認するスクリプト"""
import json
import sys
from pathlib import Path
from bs4 import BeautifulSoup
import re
import urllib.parse

# エンコーディング設定
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def analyze_har_file(har_path: str):
    """HARファイルを解析して詳細ページの構造を確認"""
    with open(har_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)
    
    entries = har_data.get('log', {}).get('entries', [])
    print(f"HARファイルから{len(entries)}個のエントリを発見しました\n")
    
    # すべてのPOSTリクエストを確認
    print("=== すべてのPOSTリクエスト ===")
    for i, entry in enumerate(entries):
        request = entry.get('request', {})
        response = entry.get('response', {})
        url = request.get('url', '')
        method = request.get('method', '')
        
        if method == 'POST':
            post_data = request.get('postData', {})
            post_text = post_data.get('text', '')
            if '__EVENTTARGET' in post_text:
                # __EVENTTARGETの値を抽出
                parsed = urllib.parse.parse_qs(post_text)
                event_target = parsed.get('__EVENTTARGET', [''])[0]
                event_argument = parsed.get('__EVENTARGUMENT', [''])[0]
                print(f"\n【POSTリクエスト #{i}】")
                print(f"URL: {url}")
                print(f"__EVENTTARGET: {event_target}")
                print(f"__EVENTARGUMENT: {event_argument}")
                
                # レスポンスのHTMLを確認
                if response.get('status') == 200:
                    content = response.get('content', {})
                    text = content.get('text', '')
                    if text:
                        soup = BeautifulSoup(text, 'html.parser')
                        title = soup.find('title')
                        if title:
                            print(f"レスポンスのタイトル: {title.get_text()}")
                        
                        # ファイルリンクを探す
                        file_links_in_response = soup.find_all('a', href=re.compile(r'\.(pdf|xlsx|docx|doc|xls)$', re.I))
                        if file_links_in_response:
                            print(f"✓ レスポンス内のファイルリンク数: {len(file_links_in_response)}")
                            for link in file_links_in_response[:5]:  # 最初の5件
                                print(f"  - {link.get('href')} ({link.get_text(strip=True)})")
                        
                        # 詳細ページの特徴を探す（dgrSearchListの$0, $1などのリクエスト）
                        if event_target == 'dgrSearchList' and event_argument.startswith('$'):
                            print(f"✓ 詳細ページへのリクエストの可能性があります（{event_argument}）")
                            # HTMLを保存
                            output_file = Path(f"test_detail_page_from_har_{i}_{event_argument.replace('$', '')}.html")
                            with open(output_file, 'w', encoding='utf-8') as f:
                                f.write(text)
                            print(f"  HTMLを保存: {output_file}")
                            
                            # ファイルリンクを探す
                            file_links_in_response = soup.find_all('a', href=re.compile(r'\.(pdf|xlsx|docx|doc|xls)$', re.I))
                            if file_links_in_response:
                                print(f"  ✓ ファイルリンク数: {len(file_links_in_response)}")
                                for link in file_links_in_response[:10]:
                                    print(f"    - {link.get('href')} ({link.get_text(strip=True)})")
                            else:
                                print(f"  × ファイルリンクが見つかりませんでした")
                                # 詳細ページの構造を確認
                                print(f"  HTMLの最初の1000文字:")
                                print(text[:1000])
    
    # すべてのHTMLレスポンスを確認
    print("\n=== すべてのHTMLレスポンス ===")
    for i, entry in enumerate(entries):
        response = entry.get('response', {})
        if response.get('status') == 200:
            content = response.get('content', {})
            mime_type = content.get('mimeType', '')
            if 'text/html' in mime_type:
                text = content.get('text', '')
                if text:
                    soup = BeautifulSoup(text, 'html.parser')
                    title = soup.find('title')
                    if title:
                        title_text = title.get_text()
                        # ファイルリンクを探す
                        file_links_in_response = soup.find_all('a', href=re.compile(r'\.(pdf|xlsx|docx|doc|xls)$', re.I))
                        if file_links_in_response:
                            print(f"\n【HTMLレスポンス #{i}】")
                            print(f"タイトル: {title_text}")
                            print(f"ファイルリンク数: {len(file_links_in_response)}")
                            for link in file_links_in_response[:10]:  # 最初の10件
                                print(f"  - {link.get('href')} ({link.get_text(strip=True)})")
    
    # UserEntry_Download.aspxへのリクエストを確認
    print("\n=== UserEntry_Download.aspxへのリクエスト ===")
    for i, entry in enumerate(entries):
        request = entry.get('request', {})
        url = request.get('url', '')
        if 'UserEntry_Download.aspx' in url:
            print(f"\n【UserEntry_Downloadリクエスト #{i}】")
            print(f"URL: {url}")
            response = entry.get('response', {})
            if response.get('status') == 200:
                content = response.get('content', {})
                mime_type = content.get('mimeType', '')
                print(f"MIMEタイプ: {mime_type}")
                text = content.get('text', '')
                if text:
                    if 'text/html' in mime_type:
                        soup = BeautifulSoup(text, 'html.parser')
                        title = soup.find('title')
                        if title:
                            print(f"タイトル: {title.get_text()}")
                        # ファイルリンクを探す
                        file_links_in_response = soup.find_all('a', href=re.compile(r'\.(pdf|xlsx|docx|doc|xls)$', re.I))
                        if file_links_in_response:
                            print(f"✓ ファイルリンク数: {len(file_links_in_response)}")
                            for link in file_links_in_response[:10]:
                                print(f"  - {link.get('href')} ({link.get_text(strip=True)})")
                        else:
                            # HTMLを保存して確認
                            output_file = Path(f"test_userentry_download_{i}.html")
                            with open(output_file, 'w', encoding='utf-8') as f:
                                f.write(text)
                            print(f"  HTMLを保存: {output_file}")
                            print(f"  HTMLの最初の2000文字:")
                            print(text[:2000])
                    elif 'application/pdf' in mime_type or 'application/vnd.openxmlformats-officedocument' in mime_type:
                        print(f"✓ ファイルが直接ダウンロードされています")
                        print(f"  ファイルサイズ: {len(text)} bytes")
    
    # 検索結果ページのHTMLを確認
    print("\n=== 検索結果ページの確認 ===")
    for i, entry in enumerate(entries):
        response = entry.get('response', {})
        if response.get('status') == 200:
            content = response.get('content', {})
            mime_type = content.get('mimeType', '')
            if 'text/html' in mime_type:
                text = content.get('text', '')
                if text and 'dgrSearchList' in text:
                    soup = BeautifulSoup(text, 'html.parser')
                    title = soup.find('title')
                    if title:
                        print(f"\n【検索結果ページ #{i}】")
                        print(f"タイトル: {title.get_text()}")
                        # dgrSearchListテーブルを確認
                        result_table = soup.find('table', id='dgrSearchList')
                        if result_table:
                            rows = result_table.find_all('tr')
                            print(f"検索結果テーブルの行数: {len(rows)}")
                            # 最初の数行の__doPostBackリンクを確認
                            postback_links = result_table.find_all('a', href=re.compile(r'__doPostBack'))
                            print(f"__doPostBackリンク数: {len(postback_links)}")
                            for link in postback_links[:5]:  # 最初の5件
                                print(f"  - {link.get('href')} ({link.get_text(strip=True)})")

if __name__ == '__main__':
    har_path = r"C:\Users\ryout\Downloads\検索結果gihu＝www.i-ppi.jp.har"
    if not Path(har_path).exists():
        print(f"エラー: HARファイルが見つかりません: {har_path}")
        sys.exit(1)
    
    analyze_har_file(har_path)
