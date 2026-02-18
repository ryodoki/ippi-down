# 実行手順と回帰防止テスト

## A. 実行手順（PowerShell コピペ可）

### 初回セットアップ〜GUI起動

```powershell
# プロジェクトルートに移動（パスは環境に合わせて変更）
cd C:\Users\ryout\Workspaces\ippi-down

# 仮想環境が無い場合のみ作成
if (-not (Test-Path .venv)) { python -m venv .venv }

# 有効化（PowerShell）
.\.venv\Scripts\Activate.ps1

# 依存関係インストール
pip install -r requirements.txt

# 設定ファイルが無い場合のみコピー（秘密情報を含めない）
if (-not (Test-Path config\config.yaml)) { Copy-Item config\config.example.yaml config\config.yaml }

# GUI 起動
python src/main.py
```

### CLI で1回だけ実行

```powershell
.\.venv\Scripts\Activate.ps1
python src/cli/main.py --config config/config.yaml --once
```

### ドライラン（ダウンロードせず対象件数のみ確認）

```powershell
.\.venv\Scripts\Activate.ps1
python src/cli/main.py --config config/config.yaml --once --dry-run
```

### 設定例

- 設定ファイルは `config/config.example.yaml` を `config/config.yaml` にコピーして使用する。
- 本番用の秘密情報は `config.yaml` に含めず、ローカルのみで管理する。
- 主要項目: `target_urls`, `download_conditions.file_types`, `download_conditions.date_range`, `save_paths.local`, `naming_rule`, `schedule.*`, `logging.level` / `logging.file`。

---

## B. 回帰防止テスト（最低限）

以下はリリース前・PR 前に実行することを推奨するテスト群です。

| 分類 | テスト | ファイル/マーカー | 内容 |
|------|--------|-------------------|------|
| 命名 | テンプレート文字列 | test_naming.py | naming_rule を使用したファイル名生成（FR-009） |
| 命名 | 空テンプレート（従来ロジック） | test_naming.py | naming_rule 空のとき従来結合 |
| 命名 | サニタイズ・重複回避 | test_naming.py, test_file_utils.py | 無効文字削除・ensure_unique |
| 保存パス | folder_name 反映 | test_downloader.py | save_dir / folder_name が保存先に含まれる |
| 保存パス | use_subfolders | test_downloader.py | use_subfolders=False でサブフォルダなし |
| 設定 | 読み書き・検証 | test_config_model.py, config_validator | URL・パス・スケジュール・必須項目 |
| スケジュール | cron / time 検証 | test_config_model.py (TestScheduleConfig) | custom+cron, daily+time, 不正値で ValueError |

### 実行コマンド（GUI・ネットワーク依存を除く）

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest tests/ -v -m "not gui" --timeout=30
```

---

## C. 修正PR相当の差分（今回の変更）

| ファイル | 変更内容・理由 |
|----------|----------------|
| src/core/downloader.py | `folder_name` を保存パスに反映。base_dir = save_dir; folder_name 指定時は base_dir = save_dir / sanitize(folder_name)。use_subfolders は base_dir 基準に変更（FR-012/FR-013）。 |
| src/config/config_validator.py | 命名規則を「必須」から外した。空の場合は従来ロジックを使用するため（FR-009/FR-010）。 |
| docs/REQUIREMENTS_TRACEABILITY.md | 新規。要件（FR/FR-SET）と実装・テストの対応表。 |
| docs/EXECUTION_AND_REGRESSION.md | 新規。実行手順（PowerShell）と回帰防止テスト一覧。 |
| tests/test_downloader.py | 新規。保存パス（folder_name / use_subfolders）の組み立てテスト。 |
| README.md | 実行手順（PowerShell コピペ可）を追加。プロジェクト構成に test_downloader.py、参考資料に REQUIREMENTS_TRACEABILITY.md を追加。 |

---

## D. 完了条件の確認

- [x] README の主張と実装が矛盾していない（命名テンプレート・保存先・設定項目を反映）
- [x] PowerShell の手順通りに GUI/CLI が起動し、設定例で1回実行できる
- [x] 主要な要件はトレーサビリティ表とテストで担保され、未対応要件は REQUIREMENTS_TRACEABILITY.md に明記

---

**作成日**: 2026年2月
