# ippi-down

建設情報サービス「ppi.jp」から条件に基づいてファイルを自動ダウンロードするツール

## 概要

ppi.jpのWebサイトを解析し、ユーザーが指定した条件に一致するファイルを自動的にダウンロードして、指定したフォルダ（ローカルまたはBox）に整理して保存します。

## 主な機能

- HTML構造の解析
- 条件に基づくファイルの自動ダウンロード
- HTML構造に基づく自動ファイル命名
- ローカルフォルダへの保存
- Boxクラウドストレージへの保存
- 定期実行（スケジューリング）

## プロジェクト構成

```
ippi-down/
├── src/                   # ソースコード
│   ├── main.py           # エントリーポイント（GUI版）
│   ├── gui/              # GUIモジュール
│   ├── core/             # コア機能（scraper, downloader等）
│   ├── storage/          # ストレージ（local, box）
│   ├── config/           # 設定管理
│   ├── utils/            # ユーティリティ
│   ├── models/           # データモデル
│   └── scheduler/        # スケジューラー
├── docs/                  # ドキュメント
│   ├── 要件定義書.md
│   ├── 要件定義見直し.md
│   ├── 技術選定.md
│   ├── システム設計書.md
│   └── 設定機能要件定義書.md
├── config/               # 設定ファイル
│   └── config.example.yaml
├── scripts/              # スクリプト
│   ├── build_exe.bat     # 実行ファイルビルド（バッチ）
│   ├── build_exe.ps1     # 実行ファイルビルド（PowerShell）
│   ├── rebuild_exe.bat   # 実行ファイル再ビルド（バッチ）
│   ├── rebuild_exe.ps1   # 実行ファイル再ビルド（PowerShell）
│   ├── start_background.bat  # バックグラウンド起動（バッチ）
│   └── start_background.ps1  # バックグラウンド起動（PowerShell）
├── tests/                # テストコード
├── logs/                 # ログファイル（実行時に生成）
├── requirements.txt      # 依存関係
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

# Linux/macOS
source .venv/bin/activate
```

4. 依存関係をインストール
```bash
pip install -r requirements.txt
```

5. 設定ファイルをコピー
```bash
# Windows (コマンドプロンプト)
copy config\config.example.yaml config\config.yaml

# Windows (PowerShell)
Copy-Item config\config.example.yaml config\config.yaml

# Linux/macOS
cp config/config.example.yaml config/config.yaml
```

6. 設定ファイルを編集（必要に応じて）

### 実行方法

```bash
python src/main.py
```

## 使用方法

### 通常の使用（GUIモード）

1. アプリケーションを起動
2. 対象URLを入力
3. ダウンロードするファイルタイプを選択
4. 保存先フォルダを指定
5. 「ダウンロード開始」ボタンをクリック

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
   scripts\build_exe.bat
   ```
   
   **Windows (PowerShell):**
   ```powershell
   .\scripts\build_exe.ps1
   ```
   
   **再ビルド（依存関係を再インストール）:**
   ```cmd
   # コマンドプロンプト
   scripts\rebuild_exe.bat
   
   # PowerShell
   .\scripts\rebuild_exe.ps1
   ```

2. **手動でビルド**
   ```bash
   # 仮想環境を有効化
   # Windows (コマンドプロンプト)
   .venv\Scripts\activate.bat
   
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   
   # Linux/macOS
   source .venv/bin/activate

   # PyInstallerでビルド
   pyinstaller build.spec
   ```

ビルドが完了すると、`dist/ippi-down.exe` が生成されます。

### ビルド結果

- 実行ファイル: `dist/ippi-down.exe`
- 実行ファイルは単体で動作し、Python環境は不要です
- 初回実行時は起動に数秒かかる場合があります

## 今後の予定

- Box認証フローの実装
- テストコードの追加
- 実運用での検証と改善

## 開発ステータス

- [x] 要件定義
- [x] 技術選定
- [x] 設計
- [x] 実装（基本機能）
- [x] GUI実装
- [x] 設定機能実装
- [x] 実行ファイル化（PyInstaller）
- [ ] テスト
- [ ] ドキュメント整備

## 参考資料

- [要件定義書](./docs/要件定義書.md)
- [技術選定書](./docs/技術選定.md)
- [システム設計書](./docs/システム設計書.md)

---

**作成日**: 2025年12月17日

