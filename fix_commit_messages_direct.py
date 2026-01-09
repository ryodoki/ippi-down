"""コミットメッセージを直接修正するスクリプト（Windows対応）"""

import subprocess
import sys
import os

# 修正するコミットハッシュと新しいメッセージのマッピング
COMMIT_MESSAGE_FIXES = {
    "5563596980ebb2f58d326a0546d5930eca9b6ba4": "docs: add code review document",
    "2bb1124b9b793d15595bd7bf565b7168b611bf5f": "feat: improve core functionality based on code review"
}


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
        current = result.stdout.strip()
        print(f"  {current}")
        print(f"    -> {new_message}")
    
    # filter-branchで修正（Windows対応）
    print("\nコミットメッセージを修正中...")
    
    # メッセージフィルター用のコマンドを構築
    filter_cmd_parts = []
    for old_hash, new_message in COMMIT_MESSAGE_FIXES.items():
        # PowerShellの条件式を使用
        filter_cmd_parts.append(
            f'if ($env:GIT_COMMIT -eq "{old_hash}") {{ Write-Output "{new_message}" }} else {{ $input }}'
        )
    
    # すべての条件を結合
    filter_cmd = " | ".join(filter_cmd_parts) if len(filter_cmd_parts) > 1 else filter_cmd_parts[0]
    
    # より単純なアプローチ: 各コミットを個別に処理
    env = os.environ.copy()
    env["FILTER_BRANCH_SQUELCH_WARNING"] = "1"
    
    # メッセージフィルタースクリプトを直接作成
    filter_script = ""
    for old_hash, new_message in COMMIT_MESSAGE_FIXES.items():
        filter_script += f'if [ "$GIT_COMMIT" = "{old_hash}" ]; then\n'
        filter_script += f'  echo "{new_message}"\n'
        filter_script += "else\n"
        filter_script += "  cat\n"
        filter_script += "fi\n"
    
    # 一時ファイルに保存（Windowsパス対応）
    import tempfile
    temp_dir = tempfile.gettempdir()
    filter_file = os.path.join(temp_dir, "git_filter_msg.sh")
    
    with open(filter_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(filter_script)
    
    try:
        # Git Bashを使用して実行
        git_bash = "C:\\Program Files\\Git\\bin\\bash.exe"
        if not os.path.exists(git_bash):
            git_bash = "bash"
        
        # filter-branchを実行
        result = subprocess.run(
            ["git", "filter-branch", "-f", "--msg-filter", f'"{git_bash}" "{filter_file}"', "--tag-name-filter", "cat", "--", "--branches", "--tags"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            shell=True
        )
        
        if result.returncode == 0:
            print("[OK] コミットメッセージの修正が完了しました")
        else:
            # 別のアプローチ: 直接的な方法
            print("[INFO] filter-branchが失敗したため、別の方法を試します...")
            return fix_with_rebase()
        
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


def fix_with_rebase():
    """rebaseを使用した修正（代替方法）"""
    print("[INFO] この方法は手動での操作が必要です")
    print("\n以下のコマンドを実行してください:")
    print("  git rebase -i <親コミットのハッシュ>")
    print("  エディタで該当コミットの 'pick' を 'reword' に変更")
    print("  コミットメッセージを修正")
    return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
