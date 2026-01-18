# -*- coding: utf-8 -*-
"""
JavaScriptで動的に追加される選択肢を確認
"""

import requests
from bs4 import BeautifulSoup
import re
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
    print("JavaScript動的選択肢の調査")
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
    print("\n[1] 初期ページを取得")
    response = session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 2. 大分類を選択
    print("\n[2] 大分類 '国の機関' を選択")
    daibunrui_value = get_dropdown_value_from_text(soup, "drpTopKikanInf", "国の機関")
    
    form_data = get_all_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpTopKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = daibunrui_value
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    # 3. 中分類を選択（正しいhiddenフィールドを設定）
    print("\n[3] 中分類 '国土交通省' を選択（正しいhiddenフィールドを含む）")
    
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
    
    print(f"  drpLargeKikanInf2: '{chubunrui_value}'")
    print(f"  txtLgKikanInfSelValue_h: '{form_data.get('txtLgKikanInfSelValue_h', '')}'")
    print(f"  txtLgKikanInf2SelIndex_h: '{form_data.get('txtLgKikanInf2SelIndex_h', '')}'")
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    response_text = response.text
    soup = BeautifulSoup(response_text, "html.parser")
    
    # 4. HTMLレスポンスを確認
    print("\n[4] HTMLレスポンスを確認")
    
    # 小分類のドロップダウンを確認
    dropdown = soup.find("select", id="drpMiddleKikanInf")
    if dropdown:
        options = dropdown.find_all("option")
        print(f"  小分類ドロップダウン: {len(options)}個の選択肢")
        for opt in options[:5]:
            print(f"    value='{opt.get('value')}': '{opt.get_text(strip=True)}'")
    else:
        print("  小分類ドロップダウンが見つかりません")
    
    # JavaScriptで動的に追加される選択肢を確認（setListItemSub）
    print("\n[5] JavaScript（setListItemSub）を確認")
    if "setListItemSub" in response_text:
        print("  setListItemSubが含まれています")
        
        # setListItemSubの呼び出しパターンを検索
        # パターン1: setListItemSub('ID', ['value:text', ...]);
        pattern = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*\[(.*?)\]\s*\)"
        matches = re.findall(pattern, response_text, re.DOTALL)
        
        if matches:
            print(f"  {len(matches)}件のsetListItemSub呼び出しを発見:")
            for call_id, list_content in matches:
                print(f"\n    ID: '{call_id}'")
                # リストの最初の5個を表示
                items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
                for i, item in enumerate(items[:5]):
                    print(f"      {i+1}. '{item}'")
                if len(items) > 5:
                    print(f"      ... (合計{len(items)}個)")
        else:
            # パターン2: setListItemSub('ID', VAR);
            pattern_var = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
            matches_var = re.findall(pattern_var, response_text)
            if matches_var:
                print(f"  {len(matches_var)}件のsetListItemSub呼び出し（変数形式）を発見:")
                for call_id, var_name in matches_var:
                    print(f"    ID: '{call_id}', VAR: '{var_name}'")
    else:
        print("  setListItemSubは含まれていません")
    
    # txtLargeKikanInf_hの内容を確認（小分類のデータがここに含まれている可能性）
    print("\n[6] txtLargeKikanInf_hを確認")
    hidden_inputs = get_all_hidden_inputs(soup)
    if "txtLargeKikanInf_h" in hidden_inputs:
        txt_large_kikan = hidden_inputs["txtLargeKikanInf_h"]
        print(f"  長さ: {len(txt_large_kikan)}文字")
        # 最初の500文字を表示
        print(f"  内容（最初の500文字）: {txt_large_kikan[:500]}...")
        
        # 東北地方整備局を探す
        if "東北地方整備局" in txt_large_kikan:
            print("\n  「東北地方整備局」が含まれています！")
            # 該当部分を抽出
            start = txt_large_kikan.find("東北地方整備局")
            extract = txt_large_kikan[max(0, start-50):start+50]
            print(f"  周辺: ...{extract}...")
        else:
            print("\n  「東北地方整備局」は含まれていません")
    else:
        print("  txtLargeKikanInf_hが見つかりません")
    
    session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
