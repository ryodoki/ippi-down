"""Common.jsをダウンロードして解析するスクリプト"""

import sys
import io
from pathlib import Path

# WindowsのコンソールでUTF-8を正しく表示するための設定
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import requests
import re

def download_and_analyze_common_js():
    """Common.jsをダウンロードして解析"""
    print("="*80)
    print("Common.jsのダウンロードと解析")
    print("="*80)
    
    url = "https://www.i-ppi.jp/IPPI/SearchServices/js/Common.js"
    
    print(f"\n1. Common.jsをダウンロード中: {url}")
    try:
        response = requests.get(url, timeout=30)
        response.encoding = 'utf-8'
        js_content = response.text
        
        # ファイルに保存
        output_file = "Common.js"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(js_content)
        print(f"Common.jsを保存しました: {output_file}")
        
        # createListItem2関数を探す
        print("\n2. createListItem2関数を解析...")
        pattern = r"function\s+createListItem2\s*\([^)]*\)\s*\{[^}]*\}"
        matches = re.findall(pattern, js_content, re.DOTALL)
        
        if matches:
            print(f"createListItem2関数を発見: {len(matches)}個")
            for i, match in enumerate(matches):
                print(f"\n関数 {i+1}:")
                # 関数の内容を表示（最初の500文字）
                print(match[:500])
                if len(match) > 500:
                    print("  ... (続く)")
        else:
            # より広いパターンで探す
            pattern2 = r"createListItem2\s*=\s*function\s*\([^)]*\)\s*\{[^}]*\}"
            matches2 = re.findall(pattern2, js_content, re.DOTALL)
            if matches2:
                print(f"createListItem2関数を発見（別形式）: {len(matches2)}個")
                for i, match in enumerate(matches2):
                    print(f"\n関数 {i+1}:")
                    print(match[:500])
            else:
                print("createListItem2関数が見つかりません")
                # 関数名を含む行を探す
                lines = js_content.split("\n")
                for i, line in enumerate(lines):
                    if "createListItem2" in line:
                        print(f"\n行 {i+1}: {line[:200]}")
                        # 前後5行を表示
                        start = max(0, i - 5)
                        end = min(len(lines), i + 6)
                        print("前後5行:")
                        for j in range(start, end):
                            marker = ">>> " if j == i else "    "
                            print(f"{marker}{j+1}: {lines[j][:150]}")
                        break
        
        # createListItem1_3関数を探す
        print("\n3. createListItem1_3関数を解析...")
        pattern = r"function\s+createListItem1_3\s*\([^)]*\)\s*\{[^}]*\}"
        matches = re.findall(pattern, js_content, re.DOTALL)
        
        if matches:
            print(f"createListItem1_3関数を発見: {len(matches)}個")
            for i, match in enumerate(matches):
                print(f"\n関数 {i+1}:")
                print(match[:500])
                if len(match) > 500:
                    print("  ... (続く)")
        else:
            # より広いパターンで探す
            pattern2 = r"createListItem1_3\s*=\s*function\s*\([^)]*\)\s*\{[^}]*\}"
            matches2 = re.findall(pattern2, js_content, re.DOTALL)
            if matches2:
                print(f"createListItem1_3関数を発見（別形式）: {len(matches2)}個")
                for i, match in enumerate(matches2):
                    print(f"\n関数 {i+1}:")
                    print(match[:500])
            else:
                print("createListItem1_3関数が見つかりません")
                # 関数名を含む行を探す
                lines = js_content.split("\n")
                for i, line in enumerate(lines):
                    if "createListItem1_3" in line:
                        print(f"\n行 {i+1}: {line[:200]}")
                        # 前後10行を表示
                        start = max(0, i - 10)
                        end = min(len(lines), i + 11)
                        print("前後10行:")
                        for j in range(start, end):
                            marker = ">>> " if j == i else "    "
                            print(f"{marker}{j+1}: {lines[j][:150]}")
                        break
        
        # getListItemStr関数を探す（txtLargeKikanInf_hから選択肢を取得する関数の可能性）
        print("\n4. getListItemStr関数を解析...")
        pattern = r"function\s+getListItemStr\s*\([^)]*\)\s*\{[^}]*\}"
        matches = re.findall(pattern, js_content, re.DOTALL)
        
        if matches:
            print(f"getListItemStr関数を発見: {len(matches)}個")
            for i, match in enumerate(matches):
                print(f"\n関数 {i+1}:")
                print(match[:800])
                if len(match) > 800:
                    print("  ... (続く)")
        else:
            print("getListItemStr関数が見つかりません")
        
        print("\n" + "="*80)
        print("解析完了")
        print("="*80)
        
    except Exception as e:
        print(f"エラー: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    download_and_analyze_common_js()
