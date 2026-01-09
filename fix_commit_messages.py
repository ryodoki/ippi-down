"""コミットメッセージを修正するスクリプト

文字化けしているコミットメッセージを適切な日本語に変換します。
"""

import subprocess
import sys
import re

# 修正するコミットハッシュと新しいメッセージのマッピング
COMMIT_MESSAGE_FIXES = {
    "5563596980ebb2f58d326a0546d5930eca9b6ba4": "docs: add code review document",
    "2bb1124b9b793d15595bd7bf565b7168b611bf5f": "feat: improve core functionality based on code review"
}


def get_current_commit_hash():
    """現在のコミットハッシュを取得"""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H"],
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    return result.stdout.strip()


def fix_commit_message(old_hash, new_message):
    """コミットメッセージを修正"""
    # コミットメッセージを変更するためのスクリプト
    script = f'''#!/bin/sh
if [ "$GIT_COMMIT" = "{old_hash}" ]; then
    echo "{new_message}"
else
    cat
fi
'''
    return script


def main():
    """メイン処理"""
    print("=" * 80)
    print("コミットメッセージの修正")
    print("=" * 80)
    
    # 修正対象のコミットを確認
    print("\n修正対象のコミット:")
    for old_hash, new_message in COMMIT_MESSAGE_FIXES.items():
        result = subprocess.run(
            ["git", "log", "--format=%h|%s", "-1", old_hash],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        print(f"  {result.stdout.strip()}")
        print(f"    -> {new_message}")
    
    # filter-branchで修正
    print("\nコミットメッセージを修正中...")
    
    # メッセージフィルター用のスクリプトを作成
    filter_script = "#!/bin/sh\n"
    for old_hash, new_message in COMMIT_MESSAGE_FIXES.items():
        filter_script += f'if [ "$GIT_COMMIT" = "{old_hash}" ]; then\n'
        filter_script += f'    echo "{new_message}"\n'
        filter_script += "else\n"
        filter_script += "    cat\n"
        filter_script += "fi\n"
    
    # 一時ファイルに保存
    import tempfile
    import os
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.sh') as f:
        f.write(filter_script)
        filter_file = f.name
    
    try:
        # 実行権限を付与（Windowsでは不要だが、念のため）
        if sys.platform != "win32":
            os.chmod(filter_file, 0o755)
        
        # filter-branchを実行
        env = os.environ.copy()
        env["FILTER_BRANCH_SQUELCH_WARNING"] = "1"
        
        result = subprocess.run(
            ["git", "filter-branch", "-f", "--msg-filter", f"sh {filter_file}", "--tag-name-filter", "cat", "--", "--branches", "--tags"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        
        if result.returncode == 0:
            print("[OK] コミットメッセージの修正が完了しました")
        else:
            print(f"[ERROR] エラーが発生しました: {result.stderr}")
            return False
        
    finally:
        # 一時ファイルを削除
        if os.path.exists(filter_file):
            os.unlink(filter_file)
    
    # 結果を確認
    print("\n修正後のコミットメッセージ:")
    for old_hash, new_message in COMMIT_MESSAGE_FIXES.items():
        result = subprocess.run(
            ["git", "log", "--format=%h|%s", "-1", old_hash],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        current_message = result.stdout.strip().split("|", 1)[1] if "|" in result.stdout else result.stdout.strip()
        status = "[OK]" if new_message in current_message or current_message == new_message else "[NG]"
        print(f"  {status} {current_message}")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
