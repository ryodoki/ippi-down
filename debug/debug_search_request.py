# -*- coding: utf-8 -*-
"""
検索リクエストの詳細をデバッグするスクリプト
GUIと同じ条件でリクエストを送信し、送信データを詳細に出力する
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
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
    print("検索リクエストデバッグ")
    print("="*70)
    
    # 1. 初期ページを取得
    print("\n[1] 初期ページを取得")
    response = session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    
    # Hidden inputsを取得
    def get_all_hidden_inputs(soup):
        hidden_inputs = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                hidden_inputs[name] = value
        return hidden_inputs
    
    def get_dropdown_value_from_text(soup, dropdown_name, display_text):
        """ドロップダウンから表示テキストに対応するvalueを取得"""
        dropdown = soup.find("select", {"id": dropdown_name})
        if not dropdown:
            dropdown = soup.find("select", {"name": dropdown_name})
        if dropdown:
            for option in dropdown.find_all("option"):
                if option.get_text().strip() == display_text:
                    return option.get("value", "")
        return None
    
    # 2. 大分類を選択してPOST
    print("\n[2] 大分類を選択: '国の機関'")
    daibunrui_value = get_dropdown_value_from_text(soup, "drpTopKikanInf", "国の機関")
    print(f"  大分類 value: '{daibunrui_value}'")
    
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpTopKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    
    # 中分類の選択肢を確認
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        options = dropdown.find_all("option")
        print(f"  中分類選択肢: {len(options)}個")
        for opt in options[:5]:
            print(f"    '{opt.get('value')}': '{opt.get_text(strip=True)}'")
    
    # 3. 中分類を選択してPOST
    print("\n[3] 中分類を選択: '国土交通省'")
    chubunrui_value = get_dropdown_value_from_text(soup, "drpLargeKikanInf2", "国土交通省")
    print(f"  中分類 value: '{chubunrui_value}'")
    
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    form_data["txtLgKikanInfSelValue_h"] = f"国土交通省,{chubunrui_value}"
    
    # 中分類の選択インデックスを設定
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    if dropdown:
        for idx, opt in enumerate(dropdown.find_all("option")):
            if opt.get("value", "") == chubunrui_value:
                form_data["txtLgKikanInf2SelIndex_h"] = str(idx)
                print(f"  中分類インデックス: {idx}")
                break
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    
    # 小分類の選択肢を確認
    dropdown = soup.find("select", id="drpMiddleKikanInf")
    if dropdown:
        options = dropdown.find_all("option")
        print(f"  小分類選択肢: {len(options)}個")
        shoubunrui_value = None
        for opt in options:
            text = opt.get_text(strip=True)
            value = opt.get("value", "")
            if "東北地方整備局" in text:
                shoubunrui_value = value
                print(f"    [TARGET] '{value}': '{text}'")
            elif len([o for o in options if o.get('value') == value]) <= 5:
                print(f"    '{value}': '{text}'")
    else:
        print("  [WARNING] drpMiddleKikanInfが見つかりません")
        # 他の方法で探す
        all_selects = soup.find_all("select")
        for sel in all_selects:
            print(f"    select: name={sel.get('name')}, id={sel.get('id')}")
    
    # 4. 小分類を選択してPOST
    print("\n[4] 小分類を選択: '東北地方整備局'")
    if not shoubunrui_value:
        # ドロップダウンから再度取得
        dropdown = soup.find("select", id="drpMiddleKikanInf")
        if dropdown:
            for opt in dropdown.find_all("option"):
                if "東北地方整備局" in opt.get_text(strip=True):
                    shoubunrui_value = opt.get("value", "")
                    break
    
    print(f"  小分類 value: '{shoubunrui_value}'")
    
    if shoubunrui_value:
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
        print(f"  Status: {response.status_code}")
    
    # 5. 検索フォームを送信
    print("\n[5] 検索フォームを送信: 工事名='トンネル'")
    
    form_data = get_all_hidden_inputs(soup)
    
    # 検索条件を設定
    form_data["__EVENTTARGET"] = ""
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    form_data["drpMiddleKikanInf"] = shoubunrui_value if shoubunrui_value else "-1"
    form_data["drpSmallKikanInf"] = "-1"
    form_data["tbxKojiNm"] = "トンネル"  # 工事名
    form_data["btnSearch"] = "検索開始"  # 検索ボタン
    
    # 送信するフォームデータを表示（重要なものだけ）
    print("\n  === 送信するフォームデータ（重要なもの）===")
    important_keys = [
        "drpTopKikanInf", "drpLargeKikanInf2", "drpMiddleKikanInf", "drpSmallKikanInf",
        "tbxKojiNm", "btnSearch", "__EVENTTARGET", "__EVENTARGUMENT",
        "txtLgKikanInfSelValue_h", "txtLgKikanInf2SelIndex_h"
    ]
    for key in important_keys:
        if key in form_data:
            value = form_data[key]
            if len(value) > 50:
                value = value[:50] + "..."
            print(f"    {key}: '{value}'")
    
    response = session.post(base_url, data=form_data, timeout=30, allow_redirects=True)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"\n  Status: {response.status_code}")
    print(f"  最終URL: {response.url}")
    
    # 検索結果を確認
    result_table = soup.find("table", id="dgrSearchList")
    if result_table:
        rows = result_table.find_all("tr")[1:]  # ヘッダー除く
        print(f"\n[6] 検索結果: {len(rows)}件")
        
        # 最初の5件を表示
        print("\n  === 最初の5件 ===")
        for i, row in enumerate(rows[:5]):
            link = row.find("a")
            if link:
                text = link.get_text(strip=True)
                print(f"    {i+1}. {text}")
        
        # 「トンネル」を含まない件数をカウント
        non_tunnel_count = 0
        for row in rows:
            link = row.find("a")
            if link:
                text = link.get_text(strip=True)
                if "トンネル" not in text:
                    non_tunnel_count += 1
        
        print(f"\n  「トンネル」を含まない件数: {non_tunnel_count}/{len(rows)}件")
    else:
        print("\n[6] 検索結果テーブルが見つかりません")
        title = soup.find("title")
        if title:
            print(f"  ページタイトル: {title.get_text()}")
    
    session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
