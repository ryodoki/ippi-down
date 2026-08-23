# -*- coding: utf-8 -*-
"""
検索結果の全ページを取得し、件数を確認するスクリプト
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
    print("検索結果全件取得テスト")
    print("="*70)
    
    # Hidden inputsを取得
    def get_all_hidden_inputs(soup):
        hidden_inputs = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                hidden_inputs[name] = value
        return hidden_inputs
    
    def get_all_form_inputs(soup):
        """すべてのフォームフィールドの値を取得"""
        form_data = {}
        
        # Hidden inputs
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                form_data[name] = value
        
        # Select elements
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
        
        # Text inputs
        for text_input in soup.find_all("input", type="text"):
            name = text_input.get("name", "")
            value = text_input.get("value", "")
            if name:
                form_data[name] = value
        
        # Checked checkboxes
        for checkbox in soup.find_all("input", type="checkbox"):
            name = checkbox.get("name", "")
            if name and checkbox.get("checked"):
                form_data[name] = checkbox.get("value", "on")
        
        # Checked radio buttons
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
    
    # 検索条件
    test_cases = [
        {
            "name": "大分類のみ (国の機関)",
            "daibunrui": "国の機関",
            "chubunrui": None,
            "shoubunrui": None,
            "koji_name": "トンネル"
        },
        {
            "name": "大分類+中分類 (国の機関 -> 国土交通省)",
            "daibunrui": "国の機関",
            "chubunrui": "国土交通省",
            "shoubunrui": None,
            "koji_name": "トンネル"
        },
        {
            "name": "大分類+中分類+小分類 (国の機関 -> 国土交通省 -> 東北地方整備局)",
            "daibunrui": "国の機関",
            "chubunrui": "国土交通省",
            "shoubunrui": "東北地方整備局",
            "koji_name": "トンネル"
        }
    ]
    
    for test_case in test_cases:
        print(f"\n{'='*70}")
        print(f"テスト: {test_case['name']}")
        print(f"{'='*70}")
        
        # 1. 初期ページを取得
        response = session.get(base_url, timeout=30)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 2. 大分類を選択
        daibunrui_value = get_dropdown_value_from_text(soup, "drpTopKikanInf", test_case["daibunrui"])
        form_data = get_all_hidden_inputs(soup)
        form_data["__EVENTTARGET"] = "drpTopKikanInf"
        form_data["__EVENTARGUMENT"] = ""
        form_data["drpTopKikanInf"] = daibunrui_value
        
        response = session.post(base_url, data=form_data, timeout=30)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        
        chubunrui_value = None
        shoubunrui_value = None
        
        # 3. 中分類を選択（指定されている場合）
        if test_case["chubunrui"]:
            chubunrui_value = get_dropdown_value_from_text(soup, "drpLargeKikanInf2", test_case["chubunrui"])
            form_data = get_all_hidden_inputs(soup)
            form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
            form_data["__EVENTARGUMENT"] = ""
            form_data["drpTopKikanInf"] = daibunrui_value
            form_data["drpLargeKikanInf2"] = chubunrui_value
            
            response = session.post(base_url, data=form_data, timeout=30)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, "html.parser")
        
        # 4. 小分類を選択（指定されている場合）
        if test_case["shoubunrui"]:
            shoubunrui_value = get_dropdown_value_from_text(soup, "drpMiddleKikanInf", test_case["shoubunrui"])
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
        if chubunrui_value:
            form_data["drpLargeKikanInf2"] = chubunrui_value
        if shoubunrui_value:
            form_data["drpMiddleKikanInf"] = shoubunrui_value
        form_data["drpSmallKikanInf"] = "-1"
        form_data["tbxKojiNm"] = test_case["koji_name"]
        form_data["btnSearch"] = "検索開始"
        
        response = session.post(base_url, data=form_data, timeout=30, allow_redirects=True)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        last_url = response.url
        
        # 全ページの件数を取得
        total_count = 0
        page_num = 1
        max_pages = 20
        
        while page_num <= max_pages:
            result_table = soup.find("table", id="dgrSearchList")
            if result_table:
                rows = result_table.find_all("tr")[1:]  # ヘッダー除く
                total_count += len(rows)
                print(f"  ページ{page_num}: {len(rows)}件 (累計: {total_count}件)")
            else:
                break
            
            # 次ページを取得
            next_button = soup.find("input", {"type": "submit", "value": "次ページ"})
            if not next_button or next_button.get("disabled"):
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
        
        print(f"\n  合計: {total_count}件")
    
    session.close()
    print("\n\n完了")

if __name__ == "__main__":
    main()
