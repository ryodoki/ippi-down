# -*- coding: utf-8 -*-
"""
検索結果の内容を確認し、フィルタリングが正しく動作しているか検証
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
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
    print("検索結果の内容検証")
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
            for option in dropdown.find_all("option"):
                if option.get_text().strip() == display_text:
                    return option.get("value", "")
        return None
    
    # 1. 初期ページを取得
    print("\n[1] 検索条件: 大分類=国の機関, 中分類=国土交通省, 小分類=東北地方整備局, 工事名=トンネル")
    
    response = session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 大分類を選択
    daibunrui_value = get_dropdown_value_from_text(soup, "drpTopKikanInf", "国の機関")
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpTopKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 中分類を選択
    chubunrui_value = get_dropdown_value_from_text(soup, "drpLargeKikanInf2", "国土交通省")
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 小分類を選択
    shoubunrui_value = get_dropdown_value_from_text(soup, "drpMiddleKikanInf", "東北地方整備局")
    print(f"  小分類 value: '{shoubunrui_value}'")
    
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
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = ""
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    form_data["drpMiddleKikanInf"] = shoubunrui_value
    form_data["drpSmallKikanInf"] = "-1"
    form_data["tbxKojiNm"] = "トンネル"
    form_data["btnSearch"] = "検索開始"
    
    print("\n[2] 送信するフォームデータ（発注機関関連）:")
    print(f"  drpTopKikanInf: '{form_data.get('drpTopKikanInf', '')}'")
    print(f"  drpLargeKikanInf2: '{form_data.get('drpLargeKikanInf2', '')}'")
    print(f"  drpMiddleKikanInf: '{form_data.get('drpMiddleKikanInf', '')}'")
    print(f"  drpSmallKikanInf: '{form_data.get('drpSmallKikanInf', '')}'")
    print(f"  tbxKojiNm: '{form_data.get('tbxKojiNm', '')}'")
    
    response = session.post(base_url, data=form_data, timeout=30, allow_redirects=True)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    print(f"\n[3] レスポンスURL: {response.url}")
    
    # 検索結果ページの検索条件を確認
    print("\n[4] 検索結果ページの選択状態:")
    
    # 各ドロップダウンの選択状態を確認
    dropdowns = [
        ("drpTopKikanInf", "大分類"),
        ("drpLargeKikanInf2", "中分類"),
        ("drpMiddleKikanInf", "小分類"),
        ("drpSmallKikanInf", "細分類"),
    ]
    
    for dropdown_id, label in dropdowns:
        dropdown = soup.find("select", {"id": dropdown_id})
        if dropdown:
            selected = dropdown.find("option", selected=True)
            if selected:
                print(f"  {label}: '{selected.get_text(strip=True)}' (value='{selected.get('value', '')}')")
            else:
                # selectedがない場合、最初のオプションを表示
                first = dropdown.find("option")
                if first:
                    print(f"  {label}: (selected なし) 最初='{first.get_text(strip=True)}'")
        else:
            print(f"  {label}: ドロップダウンが見つかりません")
    
    # 工事名の値を確認
    koji_name_input = soup.find("input", {"id": "tbxKojiNm"})
    if koji_name_input:
        print(f"  工事名: '{koji_name_input.get('value', '')}'")
    
    # 検索結果の件数と内容を確認
    result_table = soup.find("table", id="dgrSearchList")
    if result_table:
        rows = result_table.find_all("tr")[1:]  # ヘッダー除く
        print(f"\n[5] 検索結果: {len(rows)}件 (最初のページ)")
        
        # 最初の10件の内容を表示
        print("\n  === 最初の10件 ===")
        for i, row in enumerate(rows[:10]):
            link = row.find("a")
            if link:
                text = link.get_text(strip=True)
                print(f"    {i+1}. {text[:60]}...")
        
        # 「トンネル」を含まない件数をカウント
        non_tunnel_count = 0
        non_tunnel_names = []
        for row in rows:
            link = row.find("a")
            if link:
                text = link.get_text(strip=True)
                if "トンネル" not in text:
                    non_tunnel_count += 1
                    non_tunnel_names.append(text)
        
        print(f"\n  「トンネル」を含まない件数: {non_tunnel_count}/{len(rows)}件")
        if non_tunnel_names:
            print("  含まないもの:")
            for name in non_tunnel_names[:5]:
                print(f"    - {name[:50]}...")
    else:
        print("\n[5] 検索結果テーブルが見つかりません")
        title = soup.find("title")
        if title:
            print(f"  ページタイトル: {title.get_text()}")
        
        # HTMLの一部を保存
        with open("debug_result_page.html", "w", encoding="utf-8") as f:
            f.write(str(soup))
        print("  HTMLを debug_result_page.html に保存しました")
    
    session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
