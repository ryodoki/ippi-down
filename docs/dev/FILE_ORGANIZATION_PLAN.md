# ファイル整理計画

## 現状分析

### プロジェクトルートに散在しているファイル

#### 1. テストファイル（移動が必要）
- `test_*.py` (10ファイル) → `tests/integration/` または `tests/unit/`
- `test_*.html` (23ファイル) → `tests/fixtures/html/`
- JSONテストデータ (13ファイル) → `tests/fixtures/json/`

#### 2. 一時・デバッグファイル（削除提案）
- Git履歴修正用: `fix_commit_*.py`, `fix_commit_msg.bat`, `fix_msg_filter.sh`
- デバッグ用: `debug_request_info.py`, `debug_request_info.json`
- 検証用: `verify_download_capability.py`, `verify_download_results.json`

#### 3. ドキュメントファイル（整理が必要）
- Git関連: `GIT_REPOSITORY_STATUS.md`, `HISTORY_REWRITE_REPORT.md`, `COMMIT_*.md` → `docs/git/`
- テスト結果: `DOWNLOAD_TEST_RESULT_FINAL.md`, `DOWNLOAD_TEST_RESULTS.md`, `DOWNLOAD_STATUS.md` → `docs/test-results/`
- 開発用: `DEBUGGING_SUMMARY.md`, `IMPROVEMENTS_SUMMARY.md`, `NEXT_STEPS.md`, `CODE_REVIEW.md` → `docs/dev/`
- 調査用: `調査手順書.md` → `docs/dev/`

## 推奨ディレクトリ構造

```
ippi-down/
├── src/                    # ソースコード（現状維持）
├── tests/
│   ├── unit/              # ユニットテスト（新規作成）
│   ├── integration/       # 統合テスト（既存）
│   └── fixtures/          # テストデータ（既存）
│       ├── html/          # HTMLテストファイル（新規作成）
│       └── json/          # JSONテストデータ（新規作成）
├── docs/
│   ├── test-results/      # テスト結果（既存）
│   ├── git/               # Git関連ドキュメント（新規作成）
│   └── dev/               # 開発・デバッグ用ドキュメント（新規作成）
├── scripts/
│   ├── build_exe.bat      # ビルドスクリプト（既存）
│   └── dev/               # 開発・デバッグ用スクリプト（新規作成）
├── config/                # 設定ファイル（既存）
├── logs/                  # ログファイル（既存、.gitignore）
├── downloads/             # ダウンロードファイル（既存、.gitignore）
├── build/                 # ビルド成果物（既存、.gitignore）
├── dist/                  # 配布用ファイル（既存、.gitignore）
├── README.md              # プロジェクト説明（保持）
├── requirements.txt       # 依存関係（保持）
├── pytest.ini            # Pytest設定（保持）
├── pyrightconfig.json    # Pyright設定（保持）
├── build.spec            # PyInstaller設定（保持）
└── .gitignore            # Git無視設定（保持）
```

## 整理手順

### ステップ1: ディレクトリ作成
1. `tests/fixtures/html/` 作成
2. `tests/fixtures/json/` 作成
3. `docs/git/` 作成
4. `docs/dev/` 作成
5. `scripts/dev/` 作成
6. `tests/unit/` 作成

### ステップ2: ファイル移動
1. テストファイルの移動
2. テスト用HTML/JSONの移動
3. ドキュメントファイルの整理
4. デバッグスクリプトの移動（保持する場合）

### ステップ3: 削除提案
一時・デバッグファイルの削除を提案
