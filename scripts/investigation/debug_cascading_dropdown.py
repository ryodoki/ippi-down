# -*- coding: utf-8 -*-
"""
階層的ドロップダウンの正確な処理を検証するスクリプト
"""

import requests
from bs4 import BeautifulSoup

def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print("="*70)
    print("階層的ドロップダウンの正確な処理検証")
    print("="*70)
    
    # Step 1: 初期ページを取得
    print("\n[1] 初期ページを取得")
    response = session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    
    def get_hidden_inputs(s):
        hidden = {}
        for inp in s.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden[name] = value
        return hidden
    
    # Step 2: 大分類を選択してPOSTバック
    print("\n[2] 大分類を選択: '国の機関' -> value='0'")
    form_data = get_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = "drpTopKikanInf"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"  # 国の機関
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    
    # 中分類のオプションを確認
    chubunrui_select = soup.find("select", id="drpLargeKikanInf2")
    if chubunrui_select:
        options = chubunrui_select.find_all("option")
        print(f"  中分類オプション ({len(options)}個):")
        for opt in options[:6]:
            value = opt.get("value", "")
            text = opt.get_text(strip=True)
            print(f"    value='{value}', text='{text}'")
    
    # Step 3: 中分類を選択してPOSTバック
    print("\n[3] 中分類を選択: '国土交通省' -> value='21'")
    
    # すべてのフォームフィールドを収集
    form_data = get_hidden_inputs(soup)
    
    # selectフィールドも追加
    for sel in soup.find_all("select"):
        name = sel.get("name", "")
        if name:
            selected = sel.find("option", selected=True)
            if selected:
                form_data[name] = selected.get("value", "")
            else:
                first_opt = sel.find("option")
                if first_opt:
                    form_data[name] = first_opt.get("value", "")
    
    # textboxフィールドも追加
    for inp in soup.find_all("input"):
        name = inp.get("name", "")
        inp_type = inp.get("type", "text")
        if name and inp_type in ["text", "hidden"]:
            form_data[name] = inp.get("value", "")
    
    # POSTバック用のフィールドを設定
    form_data["__EVENTTARGET"] = "drpLargeKikanInf2"
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"  # 国土交通省
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    
    # 小分類のオプションを確認
    shoubunrui_select = soup.find("select", id="drpMiddleKikanInf")
    if shoubunrui_select:
        options = shoubunrui_select.find_all("option")
        print(f"  小分類オプション ({len(options)}個):")
        tohoku_value = None
        for opt in options:
            value = opt.get("value", "")
            text = opt.get_text(strip=True)
            if "東北" in text:
                tohoku_value = value
                print(f"    [TARGET] value='{value}', text='{text}'")
            elif len(options) <= 15 or value in ["-1", "01", "02"]:
                print(f"    value='{value}', text='{text}'")
    
    # hiddenフィールドを確認
    hidden_fields = get_hidden_inputs(soup)
    print(f"\n  hiddenフィールドの確認:")
    for key in ["txtLargeKikanInf_h", "txtMiddleKikanInf_h", "txtKikanInfSelValue_h", "txtLgKikanInfSelValue_h"]:
        if key in hidden_fields and hidden_fields[key]:
            value = hidden_fields[key][:200] + "..." if len(hidden_fields[key]) > 200 else hidden_fields[key]
            print(f"    {key} = '{value}'")
    
    if tohoku_value is None:
        print("  [ERROR] 東北地方整備局が見つかりませんでした")
        return
    
    # Step 4: 小分類を選択してPOSTバック (必要に応じて)
    print(f"\n[4] 小分類を選択: '東北地方整備局' -> value='{tohoku_value}'")
    
    # Step 5: 検索を実行
    print("\n[5] 検索を実行: 工事名='トンネル'")
    form_data = get_hidden_inputs(soup)
    form_data["__EVENTTARGET"] = ""
    form_data["__EVENTARGUMENT"] = ""
    form_data["drpTopKikanInf"] = "0"
    form_data["drpLargeKikanInf2"] = "21"
    form_data["drpMiddleKikanInf"] = tohoku_value  # 東北地方整備局
    form_data["drpSmallKikanInf"] = "-1"
    form_data["tbxKojiNm"] = "トンネル"
    form_data["drpCount"] = "20"
    form_data["btnSearch"] = "検索開始"
    
    print(f"  送信データ (重要部分):")
    print(f"    drpTopKikanInf = '{form_data['drpTopKikanInf']}'")
    print(f"    drpLargeKikanInf2 = '{form_data['drpLargeKikanInf2']}'")
    print(f"    drpMiddleKikanInf = '{form_data['drpMiddleKikanInf']}'")
    print(f"    tbxKojiNm = '{form_data['tbxKojiNm']}'")
    
    response = session.post(base_url, data=form_data, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    print(f"  Response URL: {response.url}")
    
    # 検索結果の件数を確認
    result_info = soup.find("td", string=lambda x: x and "該当する案件が" in x if x else False)
    if result_info:
        print(f"\n  === 検索結果 ===")
        print(f"  {result_info.get_text(strip=True)}")
    else:
        # 検索結果テーブルを確認
        result_table = soup.find("table", id="dgrSearchList")
        if result_table:
            rows = result_table.find_all("tr")
            print(f"\n  === 検索結果 ===")
            print(f"  検索結果テーブル: {len(rows)-1}件表示")
        else:
            print("\n  [WARNING] 検索結果が見つかりません")
            # ページ内容をデバッグ
            title = soup.find("title")
            print(f"  ページタイトル: {title.string if title else 'N/A'}")
    
    session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
