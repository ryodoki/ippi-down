#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pythonファイルにエンコーディング宣言を追加するスクリプト"""

import re
import sys
import io
from pathlib import Path

# Windows環境でのコンソール出力の文字化けを防ぐ
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def has_encoding_declaration(content: str) -> bool:
    """ファイルにエンコーディング宣言があるかチェック"""
    # 最初の2行をチェック
    lines = content.split('\n', 2)
    for line in lines[:2]:
        if re.search(r'^#.*coding[:=]\s*utf-8', line, re.IGNORECASE):
            return True
    return False


def add_encoding_declaration(content: str) -> str:
    """エンコーディング宣言を追加"""
    lines = content.split('\n')
    
    # シェバン行を探す
    shebang_idx = -1
    for i, line in enumerate(lines[:2]):
        if line.startswith('#!'):
            shebang_idx = i
            break
    
    encoding_line = "# -*- coding: utf-8 -*-"
    
    if shebang_idx >= 0:
        # シェバン行の後に追加
        lines.insert(shebang_idx + 1, encoding_line)
        # 空行を追加（ない場合）
        if shebang_idx + 2 < len(lines) and lines[shebang_idx + 2].strip():
            lines.insert(shebang_idx + 2, "")
    else:
        # ファイルの先頭に追加
        lines.insert(0, encoding_line)
        if len(lines) > 1 and lines[1].strip():
            lines.insert(1, "")
    
    return '\n'.join(lines)


def process_file(file_path: Path) -> bool:
    """ファイルを処理"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if has_encoding_declaration(content):
            return False  # 既に宣言がある
        
        new_content = add_encoding_declaration(content)
        
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            f.write(new_content)
        
        return True
    except Exception as e:
        print(f"エラー: {file_path} の処理に失敗: {e}")
        return False


def main():
    """メイン処理"""
    root_dir = Path(__file__).parent.parent.parent  # scripts/utils/ から プロジェクトルートへ
    
    print("Pythonファイルにエンコーディング宣言を追加中...")
    print(f"対象ディレクトリ: {root_dir}")
    print()
    
    stats = {'total': 0, 'added': 0, 'skipped': 0, 'errors': 0}
    
    # srcディレクトリとscriptsディレクトリのPythonファイルを処理
    for pattern in ['src/**/*.py', 'scripts/*.py', 'tests/**/*.py']:
        for file_path in root_dir.glob(pattern):
            if file_path.name == 'convert_to_utf8.py' or file_path.name == 'add_encoding_declarations.py':
                continue  # スクリプト自体はスキップ
            
            stats['total'] += 1
            
            if process_file(file_path):
                stats['added'] += 1
                print(f"[OK] {file_path.relative_to(root_dir)}")
            else:
                stats['skipped'] += 1
    
    print()
    print("=" * 60)
    print("処理完了")
    print("=" * 60)
    print(f"  総ファイル数: {stats['total']}")
    print(f"  追加したファイル: {stats['added']}")
    print(f"  スキップ: {stats['skipped']} (既に宣言あり)")
    print(f"  エラー: {stats['errors']}")


if __name__ == '__main__':
    main()
