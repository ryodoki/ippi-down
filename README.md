# ippi-down

建設情報サービス「ppi.jp」から条件に基づいてファイルを自動ダウンロードするツール

## 概要

ppi.jpのWebサイトを解析し、ユーザーが指定した条件に一致するファイルを自動的にダウンロードして、指定したフォルダ（ローカル）に整理して保存します。

**注意**: Box保存機能は将来対応予定です。現在はローカル保存のみサポートしています。

## 主な機能

- HTML構造の解析
- 条件に基づくファイルの自動ダウンロード
- HTML構造に基づく自動ファイル命名（テンプレート文字列対応）
- ローカルフォルダへの保存
- 定期実行（スケジューリング、cron形式対応）
- HTTPレート制限（429エラー）の自動処理
- Windowsパス長制限（260文字）の自動対応
- ダウンロード中のキャンセル機能
- 詳細なメタデータ抽出（発注機関、工事名、日付など）
- 日付範囲フィルタリング
- PostBackリンク対応（javascript:__doPostBack形式）

## プロジェクト構成

```
ippi-down/
├── src/                   # ソースコード
│   ├── main.py           # エントリーポイント（GUI版）
│   ├── gui/              # GUIモジュール
│   ├── core/             # コア機能（scraper, downloader等）
│   ├── storage/          # ストレージ（local、Boxは将来対応予定）
│   ├── config/           # 設定管理
│   ├── utils/            # ユーティリティ
│   ├── models/           # データモデル
│   └── scheduler/        # スケジューラー
├── docs/                  # ドキュメント
│   ├── requirements.md          # 要件定義書
│   ├── requirements_revision.md # 要件定義見直し
│   ├── technology_selection.md  # 技術選定書
│   ├── system_design.md         # システム設計書
│   ├── implementation_design.md # 実装設計書
│   ├── settings_requirements.md # 設定機能要件定義書
│   ├── dev/                     # 開発ドキュメント
│   ├── git/                     # Git関連ドキュメント
│   └── test-results/            # テスト結果
├── config/               # 設定ファイル
│   └── config.example.yaml
├── scripts/              # スクリプト
│   ├── build/            # ビルドスクリプト
│   │   ├── build_exe.bat     # 実行ファイルビルド（バッチ）
│   │   ├── build_exe.ps1     # 実行ファイルビルド（PowerShell）
│   │   ├── rebuild_exe.bat   # 実行ファイル再ビルド（バッチ）
│   │   ├── rebuild_exe.ps1   # 実行ファイル再ビルド（PowerShell）
│   │   └── build.spec        # PyInstaller設定
│   ├── utils/            # ユーティリティスクリプト
│   ├── tools/            # 配布用ツール
│   ├── start_background.bat  # バックグラウンド起動（バッチ）
│   └── start_background.ps1  # バックグラウンド起動（PowerShell）
├── tests/                # テストコード
│   ├── test_config.py    # 設定テスト
│   ├── test_settings.py  # 設定ダイアログテスト
│   ├── test_file_utils.py # FileUtilsテスト
│   ├── test_config_model.py # ConfigModelテスト
│   └── test_http_client.py # HTTPClientテスト
├── logs/                 # ログファイル（実行時に生成、Git追跡対象外）
├── downloads/            # ダウンロード結果ファイル（Git追跡対象外）
├── build/                # PyInstallerビルド作業ディレクトリ（Git追跡対象外）
├── dist/                 # PyInstaller生成物（Git追跡対象外）
├── .venv/                # 仮想環境（Git追跡対象外）
├── requirements.txt      # 依存関係
├── pytest.ini           # pytest設定
├── pyrightconfig.json   # Pyright設定
└── README.md             # プロジェクト概要

```

## セットアップ

### 必要な環境

- Python 3.10以上（推奨: 3.11+）
- pip（パッケージマネージャー）

**Windows PowerShell を使用する場合:**
- PowerShellスクリプト（.ps1）を実行するには、実行ポリシーの設定が必要な場合があります
- 実行ポリシーを確認:
  ```powershell
  Get-ExecutionPolicy
  ```
- 実行ポリシーを変更（現在のセッションのみ）:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
  ```
- または、スクリプトを直接実行:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
  ```

### インストール手順

1. リポジトリをクローンまたはダウンロード

2. 仮想環境を作成（推奨）
```bash
python -m venv .venv
```

3. 仮想環境を有効化
```bash
# Windows (コマンドプロンプト)
.venv\Scripts\activate.bat

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# または
.venv\Scripts\activate.bat
```

4. 依存関係をインストール
```bash
pip install -r requirements.txt
```

5. 開発環境のセットアップ（開発・テストを行う場合）

開発・テストを行う場合は、追加の依存関係をインストールしてください:

```powershell
# 開発用依存関係をインストール
pip install -r requirements-dev.txt
```

これにより、pytest-timeout などの開発ツールがインストールされます。

**重要**: テストを実行する場合は、必ず `requirements-dev.txt` をインストールしてください。  
`pytest.ini` の `addopts` に `--timeout` オプションが含まれているため、`pytest-timeout` が必要です。

6. 設定ファイルをコピーして作成

   **重要**: Gitで管理されるのは `config/config.example.yaml` のみです。  
   実際に使用する設定ファイル `config/config.yaml` はローカルで作成してください。

   ```bash
   # Windows (コマンドプロンプト)
   copy config\config.example.yaml config\config.yaml

   # Windows (PowerShell)
   Copy-Item config\config.example.yaml config\config.yaml
   ```

6. 設定ファイルを編集（必要に応じて）

   `config/config.yaml` を開いて、必要に応じて設定を変更してください。  
   このファイルは Git で追跡されません（ローカル専用設定）。

### 実行方法

```bash
python src/main.py
```

## 使用方法

### 通常の使用（GUIモード）

1. アプリケーションを起動
2. 検索条件を設定（発注機関、工事名、日付範囲など）
3. ダウンロードするファイルタイプを選択
4. 保存先フォルダを指定
5. 「ダウンロード開始」ボタンをクリック
6. ダウンロード中は「キャンセル」ボタンで中断可能

### スケジュール機能

1. **スケジュール設定**
   - 「スケジュールを有効にする」にチェック
   - 実行間隔を選択（1日、1週間、1か月）
   - 実行時間を指定（HH:MM形式、例: 09:00）

2. **PC起動時の自動実行**
   - `start_background.bat`または`start_background.ps1`をスタートアップフォルダに登録
   - または、`StartupManager`を使用してプログラムから登録

3. **バックグラウンド実行**
   - バックグラウンドモードで実行する場合:
     ```bash
     python src/main.py --background
     ```
   - または環境変数を設定:
     ```cmd
     # コマンドプロンプト
     set PPI_BACKGROUND_MODE=true
     python src/main.py
     ```
     ```powershell
     # PowerShell
     $env:PPI_BACKGROUND_MODE = "true"
     python src/main.py
     ```
   - またはスクリプトを使用:
     ```cmd
     # コマンドプロンプト
     scripts\start_background.bat
     ```
     ```powershell
     # PowerShell
     .\scripts\start_background.ps1
     ```

4. **通知**
   - ダウンロード完了時にWindows通知が表示されます
   - GUIが表示されていない場合でも通知で結果を確認できます

## 実行ファイル化

PyInstallerを使用して実行ファイル（.exe）を作成できます。

### ビルド方法

1. **ビルドスクリプトを使用（推奨）**
   
   **Windows (コマンドプロンプト):**
   ```cmd
   scripts\build\build_exe.bat
   ```
   
   **Windows (PowerShell):**
   ```powershell
   .\scripts\build\build_exe.ps1
   ```
   
   **再ビルド（依存関係を再インストール）:**
   ```cmd
   # コマンドプロンプト
   scripts\build\rebuild_exe.bat
   
   # PowerShell
   .\scripts\build\rebuild_exe.ps1
   ```

2. **手動でビルド**
   ```bash
   # 仮想環境を有効化
   # Windows (コマンドプロンプト)
   .venv\Scripts\activate.bat
   
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1

   # PyInstallerでビルド
   pyinstaller scripts\build\build.spec
   ```

ビルドが完了すると、`dist/ippi-down.exe` が生成されます。

### ビルド結果

- 実行ファイル: `dist/ippi-down.exe`
- 実行ファイルは単体で動作し、Python環境は不要です
- 初回実行時は起動に数秒かかる場合があります

## テスト

pytestを使用したテストスイートが用意されています。

### テスト環境のセットアップ

テストを実行する前に、開発用依存関係をインストールしてください：

```powershell
# 開発用依存関係をインストール（pytest-timeout等を含む）
pip install -r requirements-dev.txt
```

**重要**: `pytest.ini` の `addopts` に `--timeout` オプションが含まれているため、`pytest-timeout` が必要です。  
`requirements-dev.txt` をインストールすることで、必要な依存関係がすべてインストールされます。

### テストの実行

**推奨**: `python -m pytest` を使用してください（コマンドPATH依存を避けるため）

```powershell
# すべてのテストを実行（GUI除外）
python -m pytest -q -m "not gui"

# すべてのテストを実行（詳細表示）
python -m pytest tests/ -v

# カバレッジレポート付きで実行
python -m pytest tests/ --cov=src --cov-report=html

# 特定のテストファイルを実行
python -m pytest tests/test_file_utils.py -v

# GUIテストを含むすべてのテストを実行
python -m pytest tests/ -v
```

**注意**: デフォルトでは `pytest.ini` の設定により、GUI依存テスト・ネットワーク依存テスト・統合テストはスキップされます。

### テストカバレッジ

現在のテストカバレッジ:
- FileUtils: ファイル名のサニタイズ、一意性確保、ファイルサイズフォーマット
- ConfigModel: スケジュール設定の検証
- HTTPClient: 初期化、タイムアウト設定

## 設定項目の説明

### 使用される設定項目

- **target_urls**: 対象URLリスト（使用中）
- **download_conditions.file_types**: ファイルタイプフィルタ（使用中）
- **download_conditions.keywords**: キーワードフィルタ（使用中）
- **download_conditions.date_range**: 日付範囲フィルタ（**実装済み**）
- **save_paths.local**: ローカル保存先（使用中）
- **naming_rule**: ファイル命名規則テンプレート（**実装済み**）
- **schedule.enabled**: スケジュール有効化（使用中）
- **schedule.interval**: 実行間隔（daily/weekly/monthly/custom、**custom cron対応済み**）
- **schedule.time**: 実行時刻（HH:MM形式、使用中）
- **schedule.cron**: cron形式（interval="custom"の場合、**実装済み**）
- **logging.level**: ログレベル（使用中）
- **logging.file**: ログファイルパス（使用中）

### 使用されていない設定項目

- **tqdm**: 進捗表示ライブラリ（現在未使用、requirements.txtでコメントアウト）

## 最近の改善点

### v0.3.0 (2025-01-XX)

- ✅ naming_rule テンプレート文字列の実装
- ✅ date_range フィルタリングの実装
- ✅ custom cron 形式のスケジュール対応（croniter導入）
- ✅ PostBackリンク対応（javascript:__doPostBack形式）
- ✅ リトライ設計の見直し（tenacity の実効性向上）
- ✅ ログ設計の統一（handlers.clear の副作用排除）
- ✅ Accept-Encoding の矛盾解消（br を削除）
- ✅ 配布/レビューZIP作成スクリプトの不具合修正

### v0.2.0 (2026-01-08)

- ✅ HTTPステータス429（レート制限）の自動処理を追加
- ✅ Windowsパス長制限（260文字）の自動対応
- ✅ メタデータ抽出機能の改善（発注機関、工事名、日付など）
- ✅ ダウンロード中のキャンセル機能を追加
- ✅ スケジュール設定の検証機能を追加
- ✅ pytestテストスイートの追加

## 今後の予定

- Box認証フローの実装
- 並列ダウンロード機能
- テストカバレッジの拡大
- 実運用での検証と改善

## 開発ステータス

- [x] 要件定義
- [x] 技術選定
- [x] 設計
- [x] 実装（基本機能）
- [x] GUI実装
- [x] 設定機能実装
- [x] 実行ファイル化（PyInstaller）
- [x] テストスイートの整備
- [x] コードレビューと改善
- [ ] テストカバレッジの拡大
- [ ] ドキュメント整備

## トラブルシューティング

### HTTPレート制限エラー

アプリケーションは自動的にHTTPステータス429（レート制限）を検出し、`Retry-After`ヘッダーに基づいて自動的にリトライします。最大3回までリトライを試みます。

### Windowsパス長制限エラー

Windowsのパス長制限（260文字）を超えるファイル名は自動的に短縮されます。ファイル名は拡張子を除いて200文字以内に制限されます。

### ダウンロードのキャンセル

ダウンロード中に「キャンセル」ボタンをクリックすると、現在のダウンロード処理が中断されます。既にダウンロード済みのファイルは保持されます。

## リポジトリの管理

### 設定ファイルの扱い

**重要**: 
- Gitで管理されるのは `config/config.example.yaml`（テンプレート）のみです
- 実際に使用する `config/config.yaml` はローカルで作成し、Gitで追跡されません
- `config/config.yaml` には機密情報を含める可能性があるため、Gitに含めません

初回セットアップ時は、`config/config.example.yaml` をコピーして `config/config.yaml` を作成してください。

### 不要なファイルの追跡解除

過去に誤って以下のファイルがGitに追加されてしまった場合、追跡を解除できます。

**重要**: これらのコマンドはローカルファイルを削除しません。Gitの追跡から外すだけです。

詳細は [リポジトリクリーンアップ手順](./docs/dev/REPOSITORY_CLEANUP.md) を参照してください。

```bash
# 仮想環境の追跡解除
git rm -r --cached .venv

# ビルド生成物の追跡解除
git rm -r --cached build dist

# ログ・ダウンロード・キャッシュの追跡解除
git rm -r --cached logs downloads .pytest_cache

# 設定ファイルの追跡解除（ローカル設定のみ）
git rm --cached config/config.yaml

# Pythonキャッシュの追跡解除（すべての__pycache__と*.pyc）
git rm -r --cached **/__pycache__
find . -name "*.pyc" -exec git rm --cached {} \;
```

**PowerShellで一括実行する場合**:

```powershell
# PowerShellで実行（一括）
git rm -r --cached .venv, build, dist, logs, downloads, .pytest_cache -ErrorAction SilentlyContinue
git rm --cached config/config.yaml -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | ForEach-Object { git rm -r --cached $_.FullName -ErrorAction SilentlyContinue }
Get-ChildItem -Recurse -Filter "*.pyc" | ForEach-Object { git rm --cached $_.FullName -ErrorAction SilentlyContinue }
```

### 配布/レビューZIPの作成

共有用ZIPを作成する場合は、`pack_for_review2.ps1` を使用してください:

```powershell
# 実行ポリシーを設定（初回のみ）
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

# レビュー用ZIPを作成
powershell -ExecutionPolicy Bypass -File .\pack_for_review2.ps1
```

**注意:**
- `pack_for_review2.ps1` は `config/config.yaml`（実設定ファイル）を自動的に除外します
- テンプレートファイル（`config.example.yaml`）のみが含まれます
- `.git`, `.venv`, `dist`, `logs`, `downloads` などの不要なファイルは自動的に除外されます

**生成物の確認:**
```powershell
# MANIFEST.txt で除外/同梱状況を確認
Get-Content .\_review_pack\MANIFEST.txt

# 不要物が含まれていないことを確認
Get-ChildItem .\_review_pack -Recurse -Directory | Where-Object { $_.Name -in @(".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".idea", ".vscode", "node_modules", "dist", "build", ".git", "logs") }

# config.yaml が含まれていないことを確認
Get-ChildItem .\_review_pack -Recurse -Filter "config.yaml" | Select-Object FullName

# config.example.yaml が含まれていることを確認
Get-ChildItem .\_review_pack -Recurse -Filter "config.example.yaml" | Select-Object FullName
```

**非推奨:**
- `pack_for_review.ps1` は `config` ディレクトリを含めるため、`config.yaml` が混入するリスクがあります
- 可能な限り `pack_for_review2.ps1` を使用してください
- `build/`, `dist/` - PyInstaller生成物
- `logs/`, `downloads/` - 実行結果
- `config/config.yaml` - ローカル設定

生成物は `release/ippi-down-clean.zip` に出力されます。

詳細は [リポジトリクリーンアップ手順](./docs/dev/REPOSITORY_CLEANUP.md) を参照してください。

## 参考資料

- [要件定義書](./docs/requirements.md)
- [技術選定書](./docs/technology_selection.md)
- [システム設計書](./docs/system_design.md)
- [実装設計書](./docs/implementation_design.md)
- [設定機能要件定義書](./docs/settings_requirements.md)
- [リポジトリクリーンアップ手順](./docs/dev/REPOSITORY_CLEANUP.md)
- [Gitクリーンアップレポート](./docs/dev/GIT_CLEANUP_REPORT.md)

## ライセンス

（ライセンス情報を追加してください）

---

**作成日**: 2025年12月17日  
**最終更新**: 2026年1月8日

