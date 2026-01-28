#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ファイルの文字コードをUTF-8に変換するスクリプト"""

import os
import sys
import io
from pathlib import Path
import chardet

# Windows環境でのコンソール出力の文字化けを防ぐ
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def detect_encoding(file_path: Path) -> tuple[str, float]:
    """ファイルの文字コードを検出"""
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
            if not raw_data:
                return 'utf-8', 1.0
            result = chardet.detect(raw_data)
            return result.get('encoding', 'utf-8'), result.get('confidence', 0.0)
    except Exception as e:
        print(f"警告: {file_path} の文字コード検出に失敗: {e}")
        return 'utf-8', 0.0


def is_text_file(file_path: Path) -> bool:
    """テキストファイルかどうかを判定"""
    text_extensions = {
        '.py', '.md', '.txt', '.bat', '.ps1', '.yaml', '.yml',
        '.json', '.html', '.css', '.js', '.ini', '.cfg', '.conf',
        '.spec', '.gitignore', '.editorconfig'
    }
    return file_path.suffix.lower() in text_extensions


def convert_to_utf8(file_path: Path, encoding: str, backup: bool = True) -> bool:
    """ファイルをUTF-8に変換"""
    backup_path = None
    try:
        # バックアップを作成
        if backup:
            backup_path = file_path.with_suffix(file_path.suffix + '.bak')
            if backup_path.exists():
                backup_path.unlink()
            file_path.rename(backup_path)
            source_path = backup_path
        else:
            source_path = file_path
        
        # ファイルを読み込み
        with open(source_path, 'r', encoding=encoding, errors='replace') as f:
            content = f.read()
        
        # UTF-8で書き込み
        target_path = backup_path.parent / backup_path.stem if backup else file_path
        with open(target_path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        
        # バックアップファイルを削除
        if backup and backup_path.exists():
            backup_path.unlink()
        
        return True
    except Exception as e:
        print(f"エラー: {file_path} の変換に失敗: {e}")
        # バックアップから復元
        if backup and backup_path and backup_path.exists():
            target_path = backup_path.parent / backup_path.stem
            if target_path.exists():
                target_path.unlink()
            backup_path.rename(file_path)
        return False


def should_skip_directory(dir_path: Path) -> bool:
    """スキップすべきディレクトリかどうか"""
    skip_dirs = {
        '.git', '.venv', 'venv', '__pycache__', 'node_modules',
        'build', 'dist', '.pytest_cache', '.mypy_cache',
        'release', 'downloads', 'test_downloads'
    }
    return dir_path.name in skip_dirs or dir_path.name.startswith('.')


def process_directory(root_dir: Path, dry_run: bool = False) -> dict:
    """ディレクトリ内のすべてのテキストファイルを処理"""
    stats = {
        'total': 0,
        'converted': 0,
        'skipped': 0,
        'errors': 0,
        'already_utf8': 0
    }
    
    for root, dirs, files in os.walk(root_dir):
        # スキップすべきディレクトリを除外
        dirs[:] = [d for d in dirs if not should_skip_directory(Path(root) / d)]
        
        for file in files:
            file_path = Path(root) / file
            
            if not is_text_file(file_path):
                continue
            
            stats['total'] += 1
            
            # 文字コードを検出
            encoding, confidence = detect_encoding(file_path)
            
            # UTF-8またはASCIIの場合はスキップ
            if encoding and encoding.lower() in ('utf-8', 'ascii', 'utf-8-sig'):
                if confidence > 0.9:
                    stats['already_utf8'] += 1
                    continue
            
            print(f"変換中: {file_path.relative_to(root_dir)} (検出: {encoding}, 信頼度: {confidence:.2f})")
            
            if not dry_run:
                if convert_to_utf8(file_path, encoding or 'cp932'):
                    stats['converted'] += 1
                    print(f"  ✓ UTF-8に変換しました")
                else:
                    stats['errors'] += 1
            else:
                stats['converted'] += 1
    
    return stats


def main():
    """メイン処理"""
    root_dir = Path(__file__).parent.parent.parent  # scripts/utils/ から プロジェクトルートへ
    
    print("=" * 60)
    print("ファイル文字コード変換スクリプト")
    print("=" * 60)
    print(f"対象ディレクトリ: {root_dir}")
    print()
    
    # ドライラン（最初は確認のみ）
    print("【ドライラン】変換が必要なファイルをチェック中...")
    stats = process_directory(root_dir, dry_run=True)
    
    print()
    print("統計:")
    print(f"  総ファイル数: {stats['total']}")
    print(f"  変換が必要: {stats['converted']}")
    print(f"  既にUTF-8: {stats['already_utf8']}")
    print()
    
    if stats['converted'] == 0:
        print("すべてのファイルが既にUTF-8です。")
        return
    
    # 実際に変換を実行
    response = input("変換を実行しますか？ (y/N): ")
    if response.lower() != 'y':
        print("変換をキャンセルしました。")
        return
    
    print()
    print("【実行】ファイルを変換中...")
    stats = process_directory(root_dir, dry_run=False)
    
    print()
    print("=" * 60)
    print("変換完了")
    print("=" * 60)
    print(f"  総ファイル数: {stats['total']}")
    print(f"  変換したファイル: {stats['converted']}")
    print(f"  スキップ: {stats['skipped']}")
    print(f"  エラー: {stats['errors']}")
    print(f"  既にUTF-8: {stats['already_utf8']}")


if __name__ == '__main__':
    main()
