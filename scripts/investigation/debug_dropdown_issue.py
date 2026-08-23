# -*- coding: utf-8 -*-
"""
ドロップダウンの問題を詳細に調査
"""

import requests
from bs4 import BeautifulSoup
import sys
import io

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
    print("ドロップダウン問題の詳細調査")
    print("="*70)
    
    def get_all_hidden_inputs(soup):
        hidden_inputs = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                hidden_inputs[name] = value
        return hidden_inputs
    
    def get_dropdown_value_from_text(soup, dropdown_name, display_text):
        dropdown = soup.find("select", {"id": dropdown_name})
        if not dropdown:
            dropdown = soup.find("select", {"name": dropdown_name})
        
        if dropdown:
            print(f"    ドロップダウン '{dropdown_name}' 検索中...")
            for option in dropdown.find_all("option"):
                text = option.get_text().strip()
                value = option.get("value", "")
                # 部分一致でも検索
                if display_text in text or text in display_text:
                    print(f"      マッチ: '{text}' -> value='{value}'")
                    return value
            print(f"    マッチなし: '{display_text}' を探しましたが見つかりませんでした")
        else:
            print(f"    ドロップダウン '{dropdown_name}' が見つかりません")
        return None
    
    # 1. 初期ページを取得
    print("\n[1] 初期ページを取得")
    response = session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 大分類を選択
    print("\n[2] 大分類 '国の機関' を選択")
    daibunrui_value = get_dropdown_value_from_text(soup, "drpTopKikanInf", "国の機関")
    print(f"  取得した値: '{daibunrui_value}'")
    
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpTopKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 中分類の選択肢を表示
    print("\n[3] 中分類の選択肢を確認")
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        options = dropdown.find_all("option")
        print(f"  {len(options)}個の選択肢:")
        for opt in options:
            print(f"    value='{opt.get('value')}': '{opt.get_text(strip=True)}'")
    else:
        print("  drpLargeKikanInf2が見つかりません")
    
    # 中分類を選択
    print("\n[4] 中分類 '国土交通省' を選択")
    chubunrui_value = get_dropdown_value_from_text(soup, "drpLargeKikanInf2", "国土交通省")
    print(f"  取得した値: '{chubunrui_value}'")
    
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 小分類の選択肢を表示
    print("\n[5] 小分類の選択肢を確認")
    dropdown = soup.find("select", id="drpMiddleKikanInf")
    if dropdown:
        options = dropdown.find_all("option")
        print(f"  {len(options)}個の選択肢:")
        for opt in options:
            text = opt.get_text(strip=True)
            value = opt.get("value", "")
            if "東北" in text:
                print(f"    [TARGET] value='{value}': '{text}'")
            else:
                print(f"    value='{value}': '{text}'")
    else:
        print("  drpMiddleKikanInfが見つかりません")
        # 他のselectを確認
        all_selects = soup.find_all("select")
        print(f"  ページ内のselect要素: {len(all_selects)}個")
        for sel in all_selects:
            print(f"    id='{sel.get('id')}', name='{sel.get('name')}'")
    
    # 小分類を選択（テキストの完全一致を試す）
    print("\n[6] 小分類 '東北地方整備局' を選択")
    shoubunrui_value = get_dropdown_value_from_text(soup, "drpMiddleKikanInf", "東北地方整備局")
    print(f"  取得した値: '{shoubunrui_value}'")
    
    if shoubunrui_value is None:
        print("  [WARNING] 小分類の値が取得できませんでした")
        # 手動で値を設定して試す
        shoubunrui_value = "02"
        print(f"  手動で '{shoubunrui_value}' を設定して続行します")
    
    # 小分類を選択してPOST
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpMiddleKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    form_data["drpMiddleKikanInf"] = shoubunrui_value
    form_data["drpSmallKikanInf"] = "-1"
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 検索フォームを送信
    print("\n[7] 検索フォームを送信: 工事名='トンネル'")
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = ""
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    form_data["drpMiddleKikanInf"] = shoubunrui_value
    form_data["drpSmallKikanInf"] = "-1"
    form_data["tbxKojiNm"] = "トンネル"
    form_data["btnSearch"] = "検索開始"
    
    print(f"  送信する値:")
    print(f"    drpTopKikanInf: '{daibunrui_value}'")
    print(f"    drpLargeKikanInf2: '{chubunrui_value}'")
    print(f"    drpMiddleKikanInf: '{shoubunrui_value}'")
    print(f"    drpSmallKikanInf: '-1'")
    print(f"    tbxKojiNm: 'トンネル'")
    
    response = session.post(base_url, data=form_data, timeout=30, allow_redirects=True)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    print(f"\n  レスポンスURL: {response.url}")
    
    # 検索結果を確認
    result_table = soup.find("table", id="dgrSearchList")
    if result_table:
        rows = result_table.find_all("tr")[1:]  # ヘッダー除く
        print(f"\n[8] 検索結果: {len(rows)}件 (最初のページ)")
        
        # 最初の5件を表示
        print("\n  === 最初の5件 ===")
        for i, row in enumerate(rows[:5]):
            link = row.find("a")
            if link:
                text = link.get_text(strip=True)
                print(f"    {i+1}. {text[:50]}...")
        
        # 東北地方整備局のものか確認（発注機関を確認）
        print("\n  === 発注機関を確認（最初の5件）===")
        for i, row in enumerate(rows[:5]):
            cells = row.find_all("td")
            # 発注機関は通常2番目のセル
            if len(cells) >= 2:
                hachu_kikan = cells[1].get_text(strip=True)
                print(f"    {i+1}. {hachu_kikan}")
    else:
        print("\n[8] 検索結果テーブルが見つかりません")
    
    session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
