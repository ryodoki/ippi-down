"""HARファイルを解析して、中分類選択時のPOSTリクエストとレスポンスを確認するスクリプト"""

import json
import sys
from pathlib import Path
from bs4 import BeautifulSoup

def analyze_har(har_file_path: str):
    """HARファイルを解析して、POSTリクエストとレスポンスを確認"""
    
    print("=" * 80)
    print("HARファイル解析")
    print("=" * 80)
    
    # HARファイルを読み込む
    with open(har_file_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)
    
    # エントリを取得
    entries = har_data.get('log', {}).get('entries', [])
    print(f"\n総エントリ数: {len(entries)}")
    
    # POSTリクエストを探す
    post_requests = []
    for entry in entries:
        request = entry.get('request', {})
        method = request.get('method', '')
        url = request.get('url', '')
        
        if method == 'POST' and 'Search.aspx' in url:
            post_requests.append(entry)
    
    print(f"\nPOSTリクエスト数: {len(post_requests)}")
    
    # 各POSTリクエストを解析
    for i, entry in enumerate(post_requests):
        print("\n" + "=" * 80)
        print(f"POSTリクエスト {i+1}")
        print("=" * 80)
        
        request = entry.get('request', {})
        response = entry.get('response', {})
        
        # リクエスト情報
        print(f"\nURL: {request.get('url', '')}")
        print(f"Method: {request.get('method', '')}")
        
        # リクエストのパラメータ
        post_data = request.get('postData', {})
        params = post_data.get('params', [])
        
        print(f"\nリクエストパラメータ数: {len(params)}")
        
        # __EVENTTARGETを確認
        event_target = None
        drp_large_kikan_inf2 = None
        drp_top_kikan_inf = None
        viewstate = None
        eventvalidation = None
        
        for param in params:
            name = param.get('name', '')
            value = param.get('value', '')
            
            if name == '__EVENTTARGET':
                event_target = value
                print(f"\n__EVENTTARGET: {value}")
            elif name == 'drpLargeKikanInf2':
                drp_large_kikan_inf2 = value
                print(f"drpLargeKikanInf2: {value}")
            elif name == 'drpTopKikanInf':
                drp_top_kikan_inf = value
                print(f"drpTopKikanInf: {value}")
            elif name == '__VIEWSTATE':
                viewstate = value[:100] + '...' if len(value) > 100 else value
                print(f"__VIEWSTATE: {viewstate} (長さ: {len(param.get('value', ''))})")
            elif name == '__EVENTVALIDATION':
                eventvalidation = value[:100] + '...' if len(value) > 100 else value
                print(f"__EVENTVALIDATION: {eventvalidation} (長さ: {len(param.get('value', ''))})")
        
        # 中分類選択時のPOSTリクエストか確認
        if event_target == 'drpLargeKikanInf2':
            print("\n" + "-" * 80)
            print("[OK] 中分類選択時のPOSTリクエストを発見")
            print("-" * 80)
            
            # レスポンスを確認
            response_content = response.get('content', {})
            response_text = response_content.get('text', '')
            
            if response_text:
                # HTMLを解析
                try:
                    soup = BeautifulSoup(response_text, 'html.parser')
                    
                    # 小分類のドロップダウンを確認
                    dropdown = soup.find('select', {'name': 'drpMiddleKikanInf'})
                    if dropdown:
                        options = dropdown.find_all('option')
                        print(f"\n小分類のオプション数: {len(options)}")
                        print("\n小分類のオプション:")
                        for j, option in enumerate(options[:20]):  # 最初の20件を表示
                            value = option.get('value', '')
                            text = option.get_text().strip()
                            print(f"  {j+1}: value={value}, text={text}")
                        
                        # ファイルに保存
                        output_file = Path(f"chubunrui_post_response_{i+1}.html")
                        with open(output_file, 'w', encoding='utf-8') as f:
                            f.write(response_text)
                        print(f"\n[OK] レスポンスHTMLを保存: {output_file}")
                    else:
                        print("\n[NG] 小分類のドロップダウンが見つかりません")
                    
                    # hidden inputを確認
                    hidden_inputs = {}
                    for hidden in soup.find_all('input', type='hidden'):
                        name = hidden.get('name', '')
                        value = hidden.get('value', '')
                        if name:
                            hidden_inputs[name] = value
                    
                    print(f"\nhidden inputの数: {len(hidden_inputs)}")
                    
                    # txtLargeKikanInf_hを確認
                    txt_large_kikan_inf_h = hidden_inputs.get('txtLargeKikanInf_h', '')
                    if txt_large_kikan_inf_h:
                        print(f"\ntxtLargeKikanInf_hの値（最初の500文字）:")
                        print(txt_large_kikan_inf_h[:500])
                        
                        # データ形式を解析
                        entries = txt_large_kikan_inf_h.split(':')
                        print(f"\nエントリ数: {len(entries)}")
                        for j, entry in enumerate(entries[:5]):
                            parts = entry.split(',')
                            print(f"  エントリ{j+1}: {len(parts)}個のパーツ")
                            if len(parts) >= 3:
                                print(f"    大分類value: {parts[0]}, 中分類名: {parts[1]}, 中分類value: {parts[2]}")
                                if len(parts) > 3:
                                    print(f"    追加データ: {parts[3:]}")
                    
                    # setListItemSubの呼び出しを確認
                    if 'setListItemSub' in response_text:
                        print("\n[OK] レスポンスにsetListItemSubが含まれています")
                        import re
                        pattern = r"setListItemSub\s*\([^)]+\)"
                        matches = re.findall(pattern, response_text)
                        print(f"setListItemSubの呼び出し数: {len(matches)}")
                        for j, match in enumerate(matches[:5]):
                            print(f"  {j+1}: {match[:200]}")
                    else:
                        print("\n[NG] レスポンスにsetListItemSubが含まれていません")
                    
                except Exception as e:
                    print(f"\n[NG] HTML解析エラー: {str(e)}")
                    # レスポンステキストの一部を表示
                    print(f"\nレスポンステキスト（最初の1000文字）:")
                    print(response_text[:1000])
    
    # すべてのPOSTリクエストのパラメータをファイルに保存
    print("\n" + "=" * 80)
    print("すべてのPOSTリクエストのパラメータを保存")
    print("=" * 80)
    
    for i, entry in enumerate(post_requests):
        request = entry.get('request', {})
        post_data = request.get('postData', {})
        params = post_data.get('params', [])
        
        output_file = Path(f"post_request_{i+1}_params.json")
        params_dict = {}
        for param in params:
            name = param.get('name', '')
            value = param.get('value', '')
            # 長い値は切り詰める
            if len(value) > 500:
                params_dict[name] = value[:500] + f"... (長さ: {len(value)})"
            else:
                params_dict[name] = value
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(params_dict, f, ensure_ascii=False, indent=2)
        print(f"[OK] POSTリクエスト {i+1} のパラメータを保存: {output_file}")
    
    print("\n" + "=" * 80)
    print("解析完了")
    print("=" * 80)

if __name__ == '__main__':
    har_file_path = r'C:\Users\ryout\Downloads\検索結果＝www.i-ppi.jp.har'
    
    if not Path(har_file_path).exists():
        print(f"エラー: HARファイルが見つかりません: {har_file_path}")
        sys.exit(1)
    
    analyze_har(har_file_path)

