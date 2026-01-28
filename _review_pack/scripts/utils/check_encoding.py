#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ファイルのエンコーディングを確認するスクリプト"""

import sys
import io
import chardet
from pathlib import Path

# Windows環境でのコンソール出力の文字化けを防ぐ
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def check_encoding(file_path):
    """ファイルの文字コードを検出"""
    try:
        with open(file_path, 'rb') as f:
            raw = f.read()
            if not raw:
                return 'empty', 0.0
            result = chardet.detect(raw)
            return result.get('encoding', 'unknown'), result.get('confidence', 0.0)
    except Exception as e:
        return f'error: {e}', 0.0

def main():
    root = Path(__file__).parent.parent.parent  # scripts/utils/ から プロジェクトルートへ
    
    print("=" * 60)
    print("ファイルエンコーディング確認")
    print("=" * 60)
    print()
    
    # 特定のファイルを確認
    files_to_check = [
        'release/ippi-down-dist/README.txt',
        'release/ippi-down-dist/config/config.example.yaml',
        'release/ippi-down-dist/config/config.yaml',
        'release/ippi-down-dist/logs/app.log',
        'logs/app.log',
        'logs/test.log',
        'scripts/build/build_exe.bat',
        'scripts/build/rebuild_exe.bat',
        'scripts/start_background.bat',
        'README.md',
        'docs/DEPLOYMENT.md',
    ]
    
    print("個別ファイルの確認:")
    for fp in files_to_check:
        p = root / fp
        if p.exists():
            enc, conf = check_encoding(p)
            status = "[OK]" if enc in ('utf-8', 'ascii', 'UTF-8-SIG', 'utf-8-sig', 'empty') else "[NG]"
            print(f"  {status} {fp}: {enc} (信頼度: {conf:.2f})")
        else:
            print(f"  [--] {fp}: ファイルなし")
    
    print()
    print("=" * 60)
    print("プロジェクト全体のスキャン")
    print("=" * 60)
    
    text_exts = {'.py', '.md', '.txt', '.bat', '.ps1', '.yaml', '.yml', '.json', '.html', '.spec'}
    skip_dirs = {'.git', '.venv', 'venv', '__pycache__', 'build', 'dist', 'downloads', 'test_downloads'}
    
    problematic = []
    total = 0
    
    import os
    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            fp = Path(root_dir) / f
            if fp.suffix.lower() in text_exts:
                total += 1
                enc, conf = check_encoding(fp)
                if enc and enc.lower() not in ('utf-8', 'ascii', 'utf-8-sig', 'empty') and conf > 0.7:
                    problematic.append((fp.relative_to(root), enc, conf))
    
    print()
    if problematic:
        print(f"問題のあるファイル ({len(problematic)}件):")
        for fp, enc, conf in problematic:
            print(f"  [NG] {fp}: {enc} (信頼度: {conf:.2f})")
    else:
        print(f"すべてのファイルがUTF-8またはASCIIです (合計: {total}件)")
    
    print()
    print("完了")

if __name__ == '__main__':
    main()
