# -*- coding: utf-8 -*-
"""
工事件数を正確にカウントするデバッグスクリプト
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
    print("工事件数カウントテスト")
    print("="*70)
    
    def get_all_hidden_inputs(soup):
        hidden_inputs = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                hidden_inputs[name] = value
        return hidden_inputs
    
    def get_all_form_inputs(soup):
        form_data = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                form_data[name] = value
        for select in soup.find_all("select"):
            name = select.get("name", "")
            if name:
                selected_option = select.find("option", selected=True)
                if selected_option:
                    form_data[name] = selected_option.get("value", "")
                else:
                    first_option = select.find("option")
                    if first_option:
                        form_data[name] = first_option.get("value", "")
        for text_input in soup.find_all("input", type="text"):
            name = text_input.get("name", "")
            value = text_input.get("value", "")
            if name:
                form_data[name] = value
        for checkbox in soup.find_all("input", type="checkbox"):
            name = checkbox.get("name", "")
            if name and checkbox.get("checked"):
                form_data[name] = checkbox.get("value", "on")
        for radio in soup.find_all("input", type="radio"):
            name = radio.get("name", "")
            if name and radio.get("checked"):
                form_data[name] = radio.get("value", "")
        return form_data
    
    def get_dropdown_value_from_text(soup, dropdown_name, display_text):
        dropdown = soup.find("select", {"id": dropdown_name})
        if not dropdown:
            dropdown = soup.find("select", {"name": dropdown_name})
        if dropdown:
            for option in dropdown.find_all("option"):
                if option.get_text().strip() == display_text:
                    return option.get("value", "")
        return None
    
    # 検索条件を設定
    print("\n検索条件: 国の機関 → 国土交通省 → 東北地方整備局 + トンネル")
    
    # 1. 初期ページを取得
    response = session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 2. 大分類を選択
    daibunrui_value = get_dropdown_value_from_text(soup, "drpTopKikanInf", "国の機関")
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpTopKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 3. 中分類を選択
    chubunrui_value = get_dropdown_value_from_text(soup, "drpLargeKikanInf2", "国土交通省")
    
    # 中分類の選択インデックスを取得
    dropdown = soup.find("select", id="drpLargeKikanInf2")
    chubunrui_index = None
    if dropdown:
        for idx, opt in enumerate(dropdown.find_all("option")):
            if opt.get("value", "") == chubunrui_value:
                chubunrui_index = idx
                break
    
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    form_data["txtLgKikanInfSelValue_h"] = f"国土交通省,{chubunrui_value}"
    if chubunrui_index is not None:
        form_data["txtLgKikanInf2SelIndex_h"] = str(chubunrui_index)
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 4. 小分類を選択
    shoubunrui_value = get_dropdown_value_from_text(soup, "drpMiddleKikanInf", "東北地方整備局")
    
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
    
    # 5. 検索フォームを送信
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = ""
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    form_data["drpLargeKikanInf2"] = chubunrui_value
    form_data["drpMiddleKikanInf"] = shoubunrui_value
    form_data["drpSmallKikanInf"] = "-1"
    form_data["tbxKojiNm"] = "トンネル"
    form_data["btnSearch"] = "検索開始"
    
    response = session.post(base_url, data=form_data, timeout=30, allow_redirects=True)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    last_url = response.url
    
    # 全ページから工事件数をカウント
    total_koji_count = 0
    all_koji_names = []
    page_num = 1
    max_pages = 20
    
    print(f"\n[検索結果の取得]")
    
    while page_num <= max_pages:
        result_table = soup.find("table", id="dgrSearchList")
        if result_table:
            rows = result_table.find_all("tr")[1:]  # ヘッダー除く
            page_koji_count = len(rows)
            total_koji_count += page_koji_count
            
            # 工事名を取得
            for row in rows:
                link = row.find("a")
                if link:
                    koji_name = link.get_text(strip=True)
                    all_koji_names.append(koji_name)
            
            print(f"  ページ{page_num}: {page_koji_count}件 (累計: {total_koji_count}件)")
        else:
            print(f"  ページ{page_num}: 検索結果テーブルが見つかりません")
            break
        
        # 次ページを取得
        next_button = soup.find("input", {"type": "submit", "value": "次ページ"})
        if not next_button or next_button.get("disabled"):
            print(f"\n  全{page_num}ページの処理が完了しました")
            break
        
        button_name = next_button.get("name", "")
        form_data = get_all_form_inputs(soup)
        form_data[button_name] = next_button.get("value", "次ページ")
        
        # フォームのaction属性からURLを取得
        form = soup.find("form")
        if form and form.get("action"):
            post_url = urljoin(last_url, form.get("action"))
        else:
            post_url = last_url
        
        response = session.post(post_url, data=form_data, timeout=30)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        last_url = response.url
        page_num += 1
    
    print(f"\n[結果]")
    print(f"  総工事件数: {total_koji_count}件")
    print(f"  ユニークな工事名数: {len(set(all_koji_names))}件")
    
    # 最初の10件の工事名を表示
    print(f"\n[工事名（最初の10件）]")
    for i, name in enumerate(all_koji_names[:10]):
        print(f"  {i+1}. {name[:60]}...")
    
    # 「トンネル」を含まない工事名をチェック
    non_tunnel = [n for n in all_koji_names if "トンネル" not in n]
    print(f"\n[「トンネル」を含まない工事名]")
    print(f"  {len(non_tunnel)}件")
    if non_tunnel:
        for name in non_tunnel[:5]:
            print(f"    - {name[:60]}...")
    
    session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
