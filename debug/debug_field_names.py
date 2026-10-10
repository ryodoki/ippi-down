# -*- coding: utf-8 -*-
"""検索フォームのフィールド名を確認するデバッグスクリプト"""

import requests
from bs4 import BeautifulSoup

def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    
    url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    response = session.get(url, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")
    
    print("="*60)
    print("検索フォームのフィールド名を確認")
    print("="*60)
    
    # 工事名に関連するフィールドを探す
    print("\n[工事名関連のinput/textareaフィールド]")
    for tag in soup.find_all(["input", "textarea"]):
        name = tag.get("name", "")
        id_ = tag.get("id", "")
        type_ = tag.get("type", "text")
        if "koji" in name.lower() or "koji" in id_.lower() or "工事" in name or "工事" in id_:
            print(f"  name='{name}', id='{id_}', type='{type_}'")
    
    # txtで始まるフィールド
    print("\n[txtで始まるフィールド（input/textarea）]")
    for tag in soup.find_all(["input", "textarea"]):
        name = tag.get("name", "")
        id_ = tag.get("id", "")
        if name.startswith("txt") or id_.startswith("txt"):
            print(f"  name='{name}', id='{id_}'")
    
    # submitボタン
    print("\n[submitボタン]")
    for btn in soup.find_all("input", type="submit"):
        name = btn.get("name", "")
        value = btn.get("value", "")
        print(f"  name='{name}', value='{value}'")
    
    # 検索ボタン
    print("\n[検索関連ボタン]")
    for btn in soup.find_all(["input", "button"]):
        name = btn.get("name", "")
        value = btn.get("value", "")
        if "search" in name.lower() or "検索" in value:
            print(f"  name='{name}', value='{value}'")
    
    print("\n完了")

if __name__ == "__main__":
    main()
