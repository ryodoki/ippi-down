# -*- coding: utf-8 -*-
"""
WebページのHTML構造を完全に分析し、スクレイパーとの乖離を特定する
"""

import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path

def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    
    base_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    print("="*70)
    print("WebページHTML構造の完全分析")
    print("="*70)
    
    # 検索条件ページを取得
    print("\n[1] 検索条件ページを取得")
    response = session.get(base_url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    print(f"  Status: {response.status_code}")
    
    # HTMLを保存
    html_path = Path("debug_search_page.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(response.text)
    print(f"  HTMLを保存: {html_path}")
    
    # フォームを分析
    print("\n[2] フォーム構造を分析")
    form = soup.find("form")
    if form:
        print(f"  form id: {form.get('id', 'N/A')}")
        print(f"  form action: {form.get('action', 'N/A')}")
        print(f"  form method: {form.get('method', 'N/A')}")
    
    # すべてのフィールドを収集
    fields = {"hidden": [], "select": [], "text": [], "checkbox": [], "radio": [], "button": []}
    
    # Hidden inputs
    for inp in soup.find_all("input", type="hidden"):
        name = inp.get("name", "")
        value = inp.get("value", "")
        if name:
            fields["hidden"].append({"name": name, "value": value[:100] if value else ""})
    
    # Select fields
    for sel in soup.find_all("select"):
        name = sel.get("name", "")
        sel_id = sel.get("id", "")
        options = []
        for opt in sel.find_all("option")[:10]:  # 最初の10個
            options.append({"value": opt.get("value", ""), "text": opt.get_text(strip=True)})
        if name:
            fields["select"].append({
                "name": name, 
                "id": sel_id, 
                "options_count": len(sel.find_all("option")),
                "first_options": options
            })
    
    # Text inputs
    for inp in soup.find_all("input", type="text"):
        name = inp.get("name", "")
        inp_id = inp.get("id", "")
        if name:
            fields["text"].append({"name": name, "id": inp_id})
    
    # Checkboxes
    for inp in soup.find_all("input", type="checkbox"):
        name = inp.get("name", "")
        inp_id = inp.get("id", "")
        checked = "checked" in inp.attrs
        if name:
            fields["checkbox"].append({"name": name, "id": inp_id, "checked": checked})
    
    # Radio buttons
    for inp in soup.find_all("input", type="radio"):
        name = inp.get("name", "")
        inp_id = inp.get("id", "")
        value = inp.get("value", "")
        checked = "checked" in inp.attrs
        if name:
            fields["radio"].append({"name": name, "id": inp_id, "value": value, "checked": checked})
    
    # Submit buttons
    for inp in soup.find_all("input", type="submit"):
        name = inp.get("name", "")
        value = inp.get("value", "")
        if name:
            fields["button"].append({"name": name, "value": value})
    
    # 結果を表示
    print("\n[3] フィールド一覧")
    
    print(f"\n  === Hidden inputs ({len(fields['hidden'])}個) ===")
    important_hidden = ["__VIEWSTATE", "__EVENTVALIDATION", "__EVENTTARGET", "__EVENTARGUMENT",
                        "txtLargeKikanInf_h", "txtMiddleKikanInf_h", "txtSmallKikanInf_h",
                        "txtKikanInfSelValue_h", "txtLgKikanInfSelValue_h", "txtLgKikanInf2SelIndex_h"]
    for h in fields["hidden"]:
        if any(x in h["name"] for x in important_hidden) or "Sel" in h["name"]:
            value_preview = h["value"][:50] + "..." if len(h["value"]) > 50 else h["value"]
            print(f"    {h['name']}: '{value_preview}'")
    
    print(f"\n  === Select fields ({len(fields['select'])}個) ===")
    for s in fields["select"]:
        print(f"    name='{s['name']}', id='{s['id']}', options={s['options_count']}")
    
    print(f"\n  === Text inputs ({len(fields['text'])}個) ===")
    for t in fields["text"]:
        print(f"    name='{t['name']}', id='{t['id']}'")
    
    print(f"\n  === Checkboxes ({len(fields['checkbox'])}個) ===")
    for c in fields["checkbox"]:
        print(f"    name='{c['name']}', id='{c['id']}', checked={c['checked']}")
    
    print(f"\n  === Radio buttons ({len(fields['radio'])}個) ===")
    for r in fields["radio"]:
        print(f"    name='{r['name']}', id='{r['id']}', value='{r['value']}', checked={r['checked']}")
    
    print(f"\n  === Submit buttons ({len(fields['button'])}個) ===")
    for b in fields["button"]:
        print(f"    name='{b['name']}', value='{b['value']}'")
    
    # JSON形式で保存
    json_path = Path("debug_html_fields.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(fields, f, ensure_ascii=False, indent=2)
    print(f"\n  フィールド一覧を保存: {json_path}")
    
    # 検索ボタンのname属性を確認
    print("\n[4] 検索ボタンの詳細")
    search_btn = soup.find("input", {"value": lambda x: x and "検索" in x if x else False})
    if search_btn:
        print(f"    name: {search_btn.get('name', 'N/A')}")
        print(f"    id: {search_btn.get('id', 'N/A')}")
        print(f"    value: {search_btn.get('value', 'N/A')}")
        print(f"    type: {search_btn.get('type', 'N/A')}")
    
    # 工事名フィールドの詳細
    print("\n[5] 工事名フィールドの詳細")
    koji_name_field = soup.find("input", {"id": "tbxKojiNm"})
    if koji_name_field:
        print(f"    name: {koji_name_field.get('name', 'N/A')}")
        print(f"    id: {koji_name_field.get('id', 'N/A')}")
        print(f"    type: {koji_name_field.get('type', 'N/A')}")
    else:
        print("    [WARNING] tbxKojiNmが見つかりません")
        # 別の方法で探す
        for inp in soup.find_all("input", type="text"):
            name = inp.get("name", "")
            inp_id = inp.get("id", "")
            if "koji" in name.lower() or "koji" in inp_id.lower():
                print(f"    候補: name='{name}', id='{inp_id}'")
    
    session.close()
    print("\n完了")

if __name__ == "__main__":
    main()
