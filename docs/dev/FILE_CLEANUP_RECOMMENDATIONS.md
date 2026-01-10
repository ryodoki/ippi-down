# ファイル削除提案

## 削除を提案するファイル

以下のファイルは**一時・デバッグ用**であり、プロジェクトに含める必要がないため、**削除を提案**します。

### 1. Git履歴修正用スクリプト（作業完了後不要）

プロジェクトルートに残っている以下のファイルは、コミットメッセージの修正作業が完了したため、もう不要です：

- ❌ `fix_commit_messages.py`
- ❌ `fix_commit_messages_direct.py`
- ❌ `fix_commit_msg.bat`
- ❌ `fix_msg_filter.sh`

**削除コマンド**:
```powershell
cd c:\Users\ryout\Workspaces\ippi-down
Remove-Item "fix_commit_messages.py", "fix_commit_messages_direct.py", "fix_commit_msg.bat", "fix_msg_filter.sh" -ErrorAction SilentlyContinue
```

### 2. 整理サマリー（作業完了後）

以下のファイルは整理作業のサマリーですが、作業完了後は削除または`docs/dev/`に移動済みです：

- ✅ `FILE_ORGANIZATION_SUMMARY.md` → 既に`docs/dev/`に移動済み

## 削除後の確認

削除後、プロジェクトルートには以下のファイルのみが残るべきです：

### ✅ 保持すべきファイル（必要最小限）

- `.gitignore` - Git無視設定
- `README.md` - プロジェクト説明
- `DEPLOYMENT.md` - デプロイメント手順
- `requirements.txt` - 依存関係
- `pytest.ini` - Pytest設定
- `pyrightconfig.json` - Pyright設定
- `build.spec` - PyInstaller設定

## まとめ

削除を実行すると、プロジェクトルートは必要最小限のファイルのみが残り、整理が完了します。
