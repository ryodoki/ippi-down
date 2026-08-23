# デプロイ手順書

## 実行ファイルの作成方法

### 前提条件

1. Python 3.10以上がインストールされていること
2. 仮想環境（.venv）が作成されていること
3. 依存関係がインストールされていること

### セットアップ

```bash
# プロジェクトルートに移動
cd C:\Users\ryout\Workspaces\ippi-down2

# 仮想環境を作成（まだの場合）
python -m venv .venv

# 仮想環境を有効化
.venv\Scripts\activate

# 依存関係をインストール
pip install -r requirements.txt
```

### ビルド方法

#### 方法1: ビルドスクリプトを使用（推奨）

```bash
scripts\build\build_exe.bat
# または
.\scripts\build\build_exe.ps1
```

このスクリプトは以下を自動的に実行します：
- 仮想環境の有効化確認
- PyInstallerのインストール確認
- 既存のビルド成果物のクリーンアップ
- 実行ファイルのビルド

#### 方法2: 手動でビルド

```bash
# 仮想環境を有効化
.venv\Scripts\activate

<<<<<<< HEAD
# PyInstallerでビルド（spec は scripts/build/ 配下）
pyinstaller scripts\build\build.spec
=======
# PyInstallerでビルド（プロジェクトルートから実行）
pyinstaller scripts\build.spec
>>>>>>> 347f4a37b322b22867c26b731ac07b60317621b0
```

### ビルド結果

ビルドが成功すると、以下のファイルが生成されます：

- **実行ファイル**: `dist/ippi-down.exe`
  - このファイルは単体で動作します
  - Python環境は不要です
  - 他のPCにコピーして実行できます

### 配布方法

1. **単体配布**
   - `dist/ippi-down.exe` を配布
   - ユーザーはこのファイルをダブルクリックするだけで実行できます
   - 設定ファイルがなくてもデフォルト設定で動作します

2. **フォルダごと配布（推奨）**
   - 以下の構成で配布：
     ```
     ippi-down-dist/
     ├── ippi-down.exe          # 実行ファイル（単体で動作）
     ├── config/
     │   └── config.example.yaml # 設定テンプレート（参考用）
     └── README.txt             # 使用方法を記載
     ```
   - 初回実行時に自動生成されるフォルダ：
     ```
     ippi-down-dist/
     ├── config/
     │   └── config.yaml        # ユーザー設定（自動生成）
     ├── downloads/             # ダウンロードファイル（自動生成）
     └── logs/
         └── app.log            # ログファイル（自動生成）
     ```

### パス解決の仕組み

- **exe実行時**: exeと同じフォルダを基準にパスを解決
  - `config/config.yaml` → exeと同じフォルダの `config/` 内
  - `logs/app.log` → exeと同じフォルダの `logs/` 内
  - `downloads/` → exeと同じフォルダの `downloads/` 内
- **開発時（python実行）**: プロジェクトルートを基準にパスを解決

### 初回実行時の注意

- 実行ファイルの初回起動時は、数秒かかる場合があります
- Windows Defenderやウイルス対策ソフトが警告を出す場合があります（正常な動作です）
- 設定ファイル（`config/config.yaml`）は初回実行時に作成されます

### トラブルシューティング

#### ビルドエラーが発生する場合

1. **依存関係の確認**
   ```bash
   pip install -r requirements.txt
   ```

2. **PyInstallerの再インストール**
   ```bash
   pip uninstall pyinstaller
   pip install pyinstaller
   ```

3. **キャッシュのクリーンアップ**
   ```bash
   # build と dist フォルダを削除してから再ビルド
   rmdir /s /q build
   rmdir /s /q dist
   pyinstaller scripts\build.spec
   ```

#### 実行時にエラーが発生する場合

1. **設定ファイルの確認**
   - `config/config.yaml` が正しく作成されているか確認
   - 必要に応じて `config/config.example.yaml` をコピーして編集

2. **ログファイルの確認**
   - `logs/app.log` を確認してエラーの詳細を確認

3. **権限の確認**
   - 実行ファイルを管理者権限で実行してみる

### ファイルサイズについて

- 実行ファイルのサイズは約50-100MB程度になることがあります
- これはPythonインタープリタと必要なライブラリがすべて含まれているためです
- ファイルサイズを削減したい場合は、不要なライブラリを除外する設定を追加できます

### 更新方法

1. 新しいバージョンをビルド
2. 既存の `ippi-down.exe` を新しいバージョンで置き換え
3. 設定ファイル（`config/config.yaml`）はそのままで動作するはずです

---

**最終更新**: 2026年1月19日
