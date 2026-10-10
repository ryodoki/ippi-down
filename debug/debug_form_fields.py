# -*- coding: utf-8 -*-
"""
Webページのフォームフィールドを完全に調査し、GUIとの差分を検出するスクリプト
"""

import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path

class FormFieldAnalyzer:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        })
    
    def get(self, url):
        return self.session.get(url, timeout=30)
    
    def post(self, url, data):
        return self.session.post(url, data=data, timeout=30)
    
    def close(self):
        self.session.close()

def analyze_form_fields(soup, output_prefix=""):
    """フォームの全フィールドを分析"""
    form = soup.find("form")
    if not form:
        print(f"{output_prefix}[ERROR] フォームが見つかりません")
        return {}
    
    fields = {}
    
    # 1. 全てのinputフィールド
    print(f"\n{output_prefix}=== INPUT フィールド ===")
    for inp in form.find_all("input"):
        name = inp.get("name", "")
        inp_type = inp.get("type", "text")
        inp_id = inp.get("id", "")
        value = inp.get("value", "")
        
        if not name:
            continue
        
        fields[name] = {
            "type": "input",
            "input_type": inp_type,
            "id": inp_id,
            "default_value": value[:50] if value else ""
        }
        
        # 重要なフィールドのみ表示
        if inp_type not in ["hidden"] or any(x in name.lower() for x in ["koji", "gyoshu", "type", "search", "btn"]):
            print(f"  name='{name}', type='{inp_type}', id='{inp_id}'")
    
    # 2. 全てのselectフィールド
    print(f"\n{output_prefix}=== SELECT フィールド ===")
    for sel in form.find_all("select"):
        name = sel.get("name", "")
        sel_id = sel.get("id", "")
        
        if not name:
            continue
        
        options = []
        for opt in sel.find_all("option"):
            opt_value = opt.get("value", "")
            opt_text = opt.get_text(strip=True)
            options.append({"value": opt_value, "text": opt_text})
        
        fields[name] = {
            "type": "select",
            "id": sel_id,
            "options_count": len(options),
            "options": options[:10]  # 最初の10個のみ保存
        }
        
        print(f"  name='{name}', id='{sel_id}', options={len(options)}")
        for opt in options[:5]:
            print(f"    - value='{opt['value']}', text='{opt['text']}'")
        if len(options) > 5:
            print(f"    ... (+{len(options)-5} more)")
    
    # 3. 全てのボタン
    print(f"\n{output_prefix}=== ボタン ===")
    for btn in form.find_all(["input", "button"]):
        btn_type = btn.get("type", "")
        if btn_type in ["submit", "button"]:
            name = btn.get("name", "")
            value = btn.get("value", "")
            btn_id = btn.get("id", "")
            print(f"  name='{name}', value='{value}', id='{btn_id}'")
    
    return fields

def compare_with_gui():
    """GUIで使用しているフィールド名との比較"""
    print("\n" + "="*60)
    print("GUIで使用しているフィールド名との比較")
    print("="*60)
    
    # GUIで使用しているフィールド名（src/core/scraper.pyから抽出）
    gui_fields = {
        "drpTopKikanInf": "大分類（発注機関）",
        "drpLargeKikanInf2": "中分類（発注機関）",
        "drpMiddleKikanInf": "小分類（発注機関）",
        "drpSmallKikanInf": "細分類（発注機関）",
        "tbxKojiNm": "工事名（文字列検索）",
        "drpArea": "地方",
        "drpPrefecture": "都道府県",
        "drpCity": "市町村",
        "drpKojiType": "工事種別",
        "drpKojiGyoshu": "工事の業種",
        "drpListCnt": "表示件数",
        "btnSearch": "検索ボタン",
    }
    
    return gui_fields

def main():
    client = FormFieldAnalyzer()
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print("="*60)
    print("フォームフィールド完全調査")
    print("="*60)
    
    # 検索条件ページを取得
    print("\n[1] 検索条件ページを取得")
    response = client.get(base_url)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    print(f"ステータス: {response.status_code}")
    print(f"URL: {response.url}")
    
    # フォームフィールドを分析
    web_fields = analyze_form_fields(soup, "[WEB] ")
    
    # GUIフィールドとの比較
    gui_fields = compare_with_gui()
    
    print("\n" + "="*60)
    print("差分分析")
    print("="*60)
    
    print("\n[GUIで使用しているフィールド -> Webページでの存在確認]")
    for gui_name, description in gui_fields.items():
        if gui_name in web_fields:
            print(f"  [OK] {gui_name} ({description}) - 存在")
        else:
            print(f"  [NG] {gui_name} ({description}) - 存在しない！")
            # 類似のフィールドを探す
            similar = [n for n in web_fields.keys() if gui_name.lower() in n.lower() or n.lower() in gui_name.lower()]
            if similar:
                print(f"    → 類似: {similar}")
    
    print("\n[Webページにあるが、GUIで使用していない可能性のあるフィールド]")
    gui_names = set(gui_fields.keys())
    for web_name, info in web_fields.items():
        if web_name not in gui_names and info["type"] == "select":
            # hidden以外で未使用のselect
            print(f"  ? {web_name} - {info.get('options_count', 0)}個のオプション")
    
    # 結果をJSONに保存
    output_file = Path("debug_form_fields.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "web_fields": web_fields,
            "gui_fields": gui_fields
        }, f, ensure_ascii=False, indent=2)
    print(f"\n詳細結果を {output_file} に保存しました")
    
    client.close()
    print("\n完了")

if __name__ == "__main__":
    main()
