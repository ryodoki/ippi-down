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

**正として固定するもの**: ソース（`src/`）、テスト（`tests/`）、ドキュメント（`docs/`）、設定テンプレ（`config/config.example.yaml`）、スクリプト（`scripts/`）。

文書の索引は [docs/README.md](docs/README.md) を参照（歴史文書は `docs/archive/` に隔離）。

```
ippi-down/
├── src/
│   ├── main.py            # GUI エントリーポイント
│   ├── cli/               # CLI（--once / --dry-run / --report）
│   ├── app/               # ApplicationService などアプリ層
│   ├── gui/               # GUI（設定ダイアログ・検索条件タブ含む）
│   ├── core/              # scraper / downloader / naming 等
│   ├── infrastructure/    # ppi.jp 向け HTML・検索・詳細・ドロップダウン
│   ├── storage/           # ローカル保存（Box は将来対応予定）
│   ├── config/            # 設定の読込・検証
│   ├── models/            # AppConfig / SearchConditions 等
│   ├── scheduler/         # GUI/--background 用の常駐スケジューラ
│   └── utils/
│       ├── http_client.py     # 通信の唯一の出口（URL検査・robots・レート制限・監査）
│       ├── netguard.py        # 許可リスト方式のエグレスガード
│       ├── robots.py          # robots.txt の取得・キャッシュ・判定
│       ├── rate_limiter.py    # ホスト単位の間隔・同時接続・総量制限
│       └── network_audit.py   # 監査ログ
├── docs/
│   ├── README.md                 # 文書索引（現行 / アーカイブ）
│   ├── network-policy.md
│   ├── batch-operation.md
│   └── archive/                  # 歴史文書（実装と一致しない可能性あり）
├── config/
│   └── config.example.yaml
├── scripts/
│   ├── schedule/          # タスクスケジューラ用（register / run / status / unregister）
│   ├── build/             # PyInstaller（build_exe.ps1, build.spec 等）
│   ├── tools/             # 梱包・リリース
│   ├── investigate/       # サイト調査ツール
│   ├── check_guardrails.ps1
│   ├── start_background.bat
│   └── start_background.ps1
├── tests/
├── requirements.txt
├── pytest.ini
└── README.md
```

### 生成物の場所（Git 管理外・再生成可能）

| 場所 | 説明 |
|------|------|
| `.venv/` | 仮想環境（`python -m venv .venv` で再作成） |
| `build/`, `dist/` | PyInstaller ビルド成果物 |
| `logs/` | アプリログ |
| `downloads/` | ダウンロード保存先 |
| `scripts/snapshots/` | サイト変更監視のスナップショット |
| `release/`, `*.zip`, `_review_pack/` | 配布ZIP・レビュー用パック |
| `artifacts/`, `debug/*.html` | デバッグ出力 |

`.gitignore` で上記を除外しています。**`config/config.yaml` は同梱せず、`config.example.yaml` からローカルでコピーして編集してください。**

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
  powershell -ExecutionPolicy Bypass -File .\scripts\build\build_exe.ps1
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

### 実行手順（PowerShell・コピペ可）

第三者でもそのままコピペして実行できる手順です。**まずプロジェクトルート（ippi-down フォルダ）に移動してから**以下を実行してください。

```powershell
# プロジェクトルートに移動（例: ダウンロードした ippi-down のパスに置き換え）
cd <プロジェクトのパス>

# 仮想環境が無い場合のみ作成
if (-not (Test-Path .venv)) { python -m venv .venv }

# 有効化（PowerShell）
.\.venv\Scripts\Activate.ps1

# 依存関係インストール
pip install -r requirements.txt

# 設定ファイルが無い場合のみコピー（config.yaml は同梱せず example のみ配布）
if (-not (Test-Path config\config.yaml)) { Copy-Item config\config.example.yaml config\config.yaml }

# GUI 起動
python src/main.py
```

**CLI で1回だけ実行する場合:**

```powershell
.\.venv\Scripts\Activate.ps1
python src/cli/main.py --config config/config.yaml --once
```

**設定例（config/config.yaml）:**  
`config.example.yaml` をコピーしたあと、`target_urls`・`download_conditions`・`save_paths.local`・**`naming_rule`**・**`save_paths.run_subfolder_mode`** を編集してください。

- **命名規則**: 使用可能な変数は `{category}`, `{title}`, `{date}`, `{index}`, `{filename}`, `{file_type}`, `{ext}`, `{koji_name}`, `{daibunrui}`, `{chubunrui}`, `{shoubunrui}`, `{saibunrui}`。`{ext}` はドット付き（例: `.pdf`）。未知の変数は設定保存時にエラーになります。
- **保存先**: 相対パス（例: `./downloads`）の場合は exe/プロジェクトルート基準で絶対パスに解決されます。
- **実行単位フォルダ**: `run_subfolder_mode: datetime` で保存先の下に `YYYYMMDD_HHMMSS` フォルダを自動作成。`search` で検索条件からフォルダ名を生成。
- **発注機関フォルダ**: `save_paths.enable_agency_root_folders: true` にすると、保存先が発注機関の階層（大分類/中分類/小分類/細分類）＋工事/業務＋日付で枝分かれします。設定例は `config/config.example.yaml` の `save_paths` を参照。GUI の「発注機関ごとにルートフォルダを作成」で ON/OFF 可能。

**回帰テスト（pytest）:**

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest tests/ -v --tb=short
```

**動作確認（命名規則・保存先フォルダ）:**

1. 上記の手順で venv 作成 → `pip install -r requirements.txt` → `config\config.yaml` を example からコピー
2. `config\config.yaml` を編集: `naming_rule`（例: `"{index}{ext}"` や `"{category}_{title}_{date}_{index}"`）、`save_paths.local`、必要なら `run_subfolder_mode: datetime` を設定
3. GUI 起動: `python src/main.py`
4. 設定画面で「ファイル命名規則」と「実行単位のルートフォルダ」を確認・保存（未知の変数があると保存時にエラーで止まる）
5. ダウンロードを1回実行
6. 確認: 保存先に意図したファイル名・フォルダができていること。ログ（`logs/app.log` またはコンソール）に「テンプレート文字列を使用」および「保存先:」が出ていること

### 実行方法（要約）

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

### 調査ツール（i-ppi サイト確認用）

検索・HTML 構造・ファイル抽出をコマンドラインで確認する統合ツールです。

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/investigate/investigate_i_ppi.py search
python scripts/investigate/investigate_i_ppi.py paginate --output-json
python scripts/investigate/investigate_i_ppi.py html
python scripts/investigate/investigate_i_ppi.py extract-files --url "https://www.i-ppi.jp/.../Detail.aspx?..." --out result.json
```

**サイト変更監視**（スナップショット取得・差分検知・影響範囲の特定）:

```powershell
# スナップショット取得（定期実行で変更検知に利用）
python scripts/investigate/investigate_i_ppi.py snapshot "https://www.i-ppi.jp/.../Search.aspx?tab=4" --out-dir scripts/snapshots
# 2 つのスナップショットを比較して差分レポート生成
python scripts/investigate/investigate_i_ppi.py diff scripts/snapshots/旧ディレクトリ scripts/snapshots/新ディレクトリ -o report.md
# 差分 JSON から Scraper/Parser の修正ポイントを列挙
python scripts/investigate/investigate_i_ppi.py impact report.json -o impact.json
```

詳細は [調査ツールの使い方](./docs/archive/reports/INVESTIGATION_TOOL.md)（アーカイブ）と [サイト変更監視の使い方](./docs/SITE_CHANGE_MONITORING.md) を参照してください。

### テストカバレッジ

現在のテストカバレッジ:
- FileUtils: ファイル名のサニタイズ、一意性確保、ファイルサイズフォーマット
- ConfigModel: スケジュール設定の検証
- HTTPClient: 初期化、タイムアウト設定

## 設定項目の説明

### 発注機関ごとのルートフォルダ（オプション）

`save_paths.enable_agency_root_folders` を有効にすると、i-ppi の発注機関階層に沿って保存先フォルダが自動作成されます。**デフォルトは OFF** で、従来どおりの保存先（`save_paths.local` ＋ 実行単位フォルダ ＋ サブフォルダ）です。

**ON 時の出力例（ツリー）:**

```
<保存先（local）>/
  （実行単位フォルダがある場合はその直下）
  発注機関/
    国の機関/
      国交省/
        東北/
          トンネル/
            工事_入札公告等/    # または 業務_入札公告等
              （日付分割する場合は 2025_02 など）
                <naming_rule で命名されたファイル>
```

- **フォルダ階層**: 発注機関（大分類→中分類→小分類→細分類）・検索種別（工事/業務）・日付パーティション（任意）で決まります。メタデータが欠損している項目は `unknown` にフォールバックし、Windows 禁則文字は除去されます。
- **ファイル名**: 従来どおり **naming_rule** のテンプレート（`{category}`, `{title}`, `{date}`, `{index}` 等）で決まります。フォルダ階層とファイル名は役割が分離されており、naming_rule は「そのフォルダ内のファイル名」にのみ適用されます。
- 設定項目の詳細は `config/config.example.yaml` の `save_paths` コメントを参照してください。

### 使用される設定項目

- **target_urls**: 対象URLリスト（使用中）
- **download_conditions.file_types**: ファイルタイプフィルタ（使用中）
- **download_conditions.keywords**: キーワードフィルタ（使用中）
- **download_conditions.date_range**: 日付範囲フィルタ（**実装済み**）
- **save_paths.local**: ローカル保存先（使用中）
- **save_paths.enable_agency_root_folders**: 発注機関ごとにルートフォルダを自動作成（**実装済み**、デフォルト OFF）
- **save_paths.agency_folder_levels / date_partition / include_search_tab_folder**: 発注機関フォルダ ON 時の階層・日付分割・工事/業務分け（**実装済み**）
- **naming_rule**: ファイル命名規則テンプレート（**実装済み**）
- **schedule.enabled**: スケジュール有効化（使用中）
- **schedule.interval**: 実行間隔（daily/weekly/monthly/custom、**custom cron対応済み**）
- **schedule.time**: 実行時刻（HH:MM形式、使用中）
- **schedule.cron**: cron形式（interval="custom"の場合、**実装済み**）
- **logging.level**: ログレベル（使用中）
- **logging.file**: ログファイルパス（使用中）
- **network.\***: 通信ポリシー（許可ホスト・robots・レート制限・監査ログ、**実装済み**）→ [ネットワークポリシー](#ネットワークポリシー)

### 使用されていない設定項目

- **tqdm**: 進捗表示ライブラリ（現在未使用、requirements.txtでコメントアウト）

## 定期実行（バッチ）

Windows タスクスケジューラで定期実行できます。ローカル PC でも Azure VM でも同じスクリプトを使います。

```powershell
cd scripts\schedule
.\register_task.ps1 -Time "09:30" -Interval Daily   # 登録
.\status_task.ps1                                   # 状態と履歴の確認
.\unregister_task.ps1                               # 削除
```

- CLI の `--report` により、実行ごとに `logs\reports\batch_*.json`（件数・失敗理由・所要時間）を出力
- `network.allowed_hours` が実行時刻を含む必要があります（登録時に整合を検査して警告）
- 詳細は [docs/batch-operation.md](docs/batch-operation.md)、Azure VM での運用は [../azure-batch-vm/docs/runbook.md](../azure-batch-vm/docs/runbook.md) を参照（Workspaces 直下の兄弟フォルダ）

## ネットワークポリシー

相手のサーバーは共有資源なので、「許可した宛先だけ」「robots.txt に従う」「負荷をかけない」
「身元を明かす」の4点を設定ではなく仕組みとして強制しています。

| 項目 | 既定値 |
|---|---|
| 許可ホスト / スキーム | `www.i-ppi.jp` / `https` のみ |
| 内部ネットワーク宛（プライベート IP） | 遮断（SSRF 対策） |
| 同一ホストへの最小間隔 / 同時接続 | 1.0 秒（`Crawl-delay` が長ければそちら） / 1 |
| 1回の実行のリクエスト上限 | 500 |
| robots.txt | 遵守（取得失敗時は既定でブロック） |
| 監査ログ | `./logs/network.log`（allow / blocked / robots_denied / rate_limited） |

- 許可外のホストは**名前解決の時点で**遮断されます（`src/utils/netguard.py`）。IP 直打ちでも回避できません。
- `target_urls` のホストが `network.allowed_hosts` に無い場合、**起動時にエラーで停止**します。
- 設定は `config/config.example.yaml` の `network` セクションを参照してください。

```powershell
# ガードレールのテストだけを実行
.\scripts\check_guardrails.ps1
```

許可先の追加やレート緩和の手順、やらないこと（認証回避・CAPTCHA 回避・`Disallow` 領域の取得・
取得データの再配布・過負荷）は [docs/network-policy.md](./docs/network-policy.md) にまとめています。

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

### リリース・レビュー用ZIPの作成（PowerShell コピペ可）

梱包スクリプトは **`scripts/tools/`** に一本化しています。**`config/config.yaml` は同梱しません。** 含まれるのは `config.example.yaml` のみです。

```powershell
# プロジェクトルートで実行
cd <プロジェクトのパス>

# レビュー用ZIP作成（_review_pack に展開後、ippi-down_review.zip を出力）
powershell -ExecutionPolicy Bypass -File .\scripts\tools\pack_for_review.ps1
```

- 出力: ルートに `ippi-down_review.zip`、一時フォルダ `_review_pack/`（ZIP作成後に削除可）
- 除外: `.venv`, `build`, `dist`, `logs`, `downloads`, `config/config.yaml`, `__pycache__` 等

**クリーンな配布用ZIP**（別名で出力したい場合）:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\tools\make_release_zip.ps1 -OutputName ippi-down-clean.zip
```

- 出力: `release/ippi-down-clean.zip`

詳細は [リリース・梱包手順](./docs/RELEASE_AND_PACK.md) を参照してください。

## 参考資料

現行ドキュメントの一覧は [docs/README.md](./docs/README.md) を参照してください。

- [要件定義書](./docs/requirements.md)
- [要件トレーサビリティ表](./docs/REQUIREMENTS_TRACEABILITY.md)（FR/FR-SET と実装・テストの対応）
- [サイト変更監視の使い方](./docs/SITE_CHANGE_MONITORING.md)（snapshot / diff / impact）
- [デプロイ手順](./docs/DEPLOYMENT.md)
- [リリース・梱包手順](./docs/RELEASE_AND_PACK.md)
- [ネットワークポリシー](./docs/network-policy.md)
- [定期バッチ運用](./docs/batch-operation.md)

歴史文書（ギャップレポート・旧設計書・調査メモなど）は [docs/archive/](./docs/archive/) にあります。実装と一致しない可能性があります。

## ライセンス

（ライセンス情報を追加してください）

---

**作成日**: 2025年12月17日  
**最終更新**: 2026年2月15日

