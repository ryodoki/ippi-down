# 技術選定書

## 1. 選定方針

本プロジェクトは、Webスクレイピング、ファイルダウンロード、クラウドストレージ連携、スケジューリング機能を実装する必要がある。**さらに、プログラミングに詳しくないユーザーやPython環境を持たないユーザーでも使用できるよう、GUIアプリケーションとして実行ファイル形式（.exe等）で配布できることが必須要件である。** 開発効率、ライブラリの充実度、保守性、パフォーマンス、GUI実装の容易さ、実行ファイル化の容易さを総合的に評価して技術スタックを選定する。

## 2. 候補言語の比較

### 2.1 Python

#### メリット
- **豊富なライブラリエコシステム**
  - HTML解析: BeautifulSoup4, lxml, html.parser
  - HTTPクライアント: requests, httpx
  - Box SDK: boxsdk（公式SDK）
  - スケジューリング: schedule, APScheduler, croniter
- **開発速度が速い**
  - シンプルな構文で可読性が高い
  - プロトタイピングが容易
- **Webスクレイピングに最適**
  - BeautifulSoupはHTML解析のデファクトスタンダード
  - 多くの実装例とドキュメントが存在
- **クロスプラットフォーム対応**
  - Windows、Linux、macOSで動作
- **CLI/GUI開発が容易**
  - CLI: argparse, click, typer
  - GUI: tkinter（標準ライブラリ）, PyQt, PySide, Kivy
- **実行ファイル化が容易**
  - PyInstaller: シングル実行ファイル化が可能
  - cx_Freeze: クロスプラットフォーム対応
  - py2exe: Windows専用だが軽量

#### デメリット
- **実行速度が比較的遅い**
  - 大量のファイル処理ではやや遅い可能性
- **依存関係管理**
  - 仮想環境の管理が必要（venv, conda）

#### 主要ライブラリ候補
| 機能 | ライブラリ | バージョン | 備考 |
|------|-----------|-----------|------|
| HTML解析 | BeautifulSoup4 | 4.x | 最も一般的 |
| HTTPクライアント | requests | 2.x | シンプルで使いやすい |
| Box SDK | boxsdk | 3.x | 公式SDK |
| スケジューリング | schedule | 1.x | シンプルなスケジューラー |
| 設定ファイル | pyyaml | 6.x | YAML形式 |
| ログ | logging | 標準 | 標準ライブラリ |
| CLI | click | 8.x | 高機能なCLIフレームワーク |

### 2.2 Node.js

#### メリット
- **非同期処理が得意**
  - 大量のファイルダウンロードに適している
  - 並列処理が容易
- **豊富なnpmパッケージ**
  - HTML解析: cheerio, jsdom
  - HTTPクライアント: axios, node-fetch
  - Box SDK: box-node-sdk（公式SDK）
  - スケジューリング: node-cron, node-schedule
- **JSON処理が自然**
  - 設定ファイルとしてJSONを使用する場合に適している

#### デメリット
- **型安全性**
  - TypeScriptを使用しない場合、型チェックがない
- **実行環境**
  - Node.jsのインストールが必要
- **エラーハンドリング**
  - 非同期処理のエラーハンドリングが複雑になりがち

#### 主要ライブラリ候補
| 機能 | ライブラリ | バージョン | 備考 |
|------|-----------|-----------|------|
| HTML解析 | cheerio | 1.x | jQueryライクなAPI |
| HTTPクライアント | axios | 1.x | Promiseベース |
| Box SDK | box-node-sdk | 2.x | 公式SDK |
| スケジューリング | node-cron | 3.x | cron形式対応 |
| 設定ファイル | js-yaml | 4.x | YAML形式 |
| ログ | winston | 3.x | 高機能なロガー |
| CLI | commander | 11.x | CLIフレームワーク |

### 2.3 Go

#### メリット
- **高いパフォーマンス**
  - コンパイル言語で実行速度が速い
  - メモリ効率が良い
- **シングルバイナリ**
  - 依存関係を含めて1つの実行ファイルにできる
  - 配布が容易
- **並列処理が得意**
  - goroutineによる並列処理が容易

#### デメリット
- **開発速度がやや遅い**
  - コンパイルが必要
  - エコシステムがPython/Node.jsより小さい
- **HTML解析ライブラリ**
  - goqueryはあるが、BeautifulSoupほど成熟していない
- **Box SDK**
  - 公式SDKはあるが、Python/Node.jsほど充実していない

#### 主要ライブラリ候補
| 機能 | ライブラリ | バージョン | 備考 |
|------|-----------|-----------|------|
| HTML解析 | goquery | 1.x | jQueryライクなAPI |
| HTTPクライアント | net/http | 標準 | 標準ライブラリ |
| Box SDK | box-go-sdk | 2.x | 公式SDK |
| スケジューリング | robfig/cron | v3 | cron形式対応 |
| 設定ファイル | viper | 1.x | 多形式対応 |
| ログ | logrus | 1.x | 構造化ログ |
| CLI | cobra | 1.x | CLIフレームワーク |

## 3. 選定結果

### 3.1 推奨: Python

**選定理由:**
1. **Webスクレイピングに最適**
   - BeautifulSoup4はHTML解析のデファクトスタンダード
   - 豊富な実装例とドキュメント
2. **開発効率が高い**
   - シンプルな構文で可読性が高い
   - プロトタイピングから本番まで対応可能
3. **ライブラリの充実度**
   - Box SDK（boxsdk）が公式で提供されている
   - 必要な機能のライブラリがすべて揃っている
4. **GUI実装が容易**
   - tkinterが標準ライブラリに含まれており追加インストール不要
   - GUI開発の実装例が豊富
   - クロスプラットフォーム対応
5. **実行ファイル化が容易**
   - PyInstallerでシングル実行ファイル（.exe）に変換可能
   - Python環境がなくても実行可能
   - Windows向けの配布が容易
6. **保守性**
   - コードが読みやすく、メンテナンスが容易
   - HTML構造が変更された場合の修正が容易
7. **クロスプラットフォーム**
   - Windows環境でも問題なく動作

### 3.2 技術スタック詳細

#### 3.2.1 コアライブラリ

| カテゴリ | ライブラリ | 用途 | バージョン |
|---------|-----------|------|-----------|
| HTML解析 | BeautifulSoup4 | HTML構造の解析 | 4.12.0+ |
| HTTPクライアント | requests | ファイルダウンロード | 2.31.0+ |
| Box SDK | boxsdk | Box API連携 | 3.9.0+ |
| スケジューリング | schedule | 定期実行 | 1.2.0+ |
| 設定管理 | pyyaml | YAML設定ファイル | 6.0.1+ |
| ログ | logging | ログ出力（標準） | 標準 |
| GUI | tkinter | グラフィカルユーザーインターフェース | 標準 |
| 実行ファイル化 | PyInstaller | .exe形式への変換 | 6.0.0+ |

#### 3.2.2 補助ライブラリ

| カテゴリ | ライブラリ | 用途 | バージョン |
|---------|-----------|------|-----------|
| 日付処理 | python-dateutil | 日付範囲の処理 | 2.8.2+ |
| 進捗表示 | tqdm | ダウンロード進捗バー | 4.66.1+ |
| リトライ | tenacity | リトライ処理 | 8.2.3+ |
| 環境変数 | python-dotenv | 環境変数管理 | 1.0.0+ |
| 暗号化 | cryptography | 認証情報の暗号化 | 41.0.0+ |
| セッション管理 | requests | セッション管理（ViewState対応） | 2.31.0+ |

## 4. アーキテクチャ概要

### 4.1 プロジェクト構造（案）

```
ppi-file-downloader/
├── src/
│   ├── __init__.py
│   ├── main.py              # エントリーポイント（GUI起動）
│   ├── main_cli.py          # CLI版エントリーポイント（開発用）
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py   # メインウィンドウ
│   │   ├── settings_dialog.py # 設定ダイアログ
│   │   ├── progress_window.py # 進捗表示ウィンドウ
│   │   └── log_viewer.py    # ログ表示ウィンドウ
│   ├── scraper.py           # HTML解析・スクレイピング
│   ├── downloader.py        # ファイルダウンロード
│   ├── box_client.py        # Box API連携
│   ├── scheduler.py         # スケジューリング
│   ├── config.py            # 設定管理
│   ├── logger.py            # ログ管理
│   └── utils.py             # ユーティリティ
├── config/
│   ├── config.yaml          # 設定ファイル（テンプレート）
│   └── config.example.yaml  # 設定ファイル例
├── logs/                    # ログファイル保存先
├── build/                   # ビルド成果物（PyInstaller）
├── dist/                    # 配布用実行ファイル
├── requirements.txt         # 依存関係
├── .env.example             # 環境変数テンプレート
├── build_exe.py             # 実行ファイルビルドスクリプト
├── README.md
├── 要件定義書.md
└── 技術選定.md
```

### 4.2 設定ファイル形式: YAML

**選定理由:**
- JSONより読みやすい
- コメントが書ける
- 階層構造が明確
- Pythonで扱いやすい（pyyaml）

**設定ファイル例（config.yaml）:**
```yaml
# ppi-file-downloader 設定ファイル

# 対象URL
target_urls:
  - https://www.i-ppi.jp/IPPI/SearchServices/Web/Index.htm

# ダウンロード条件
download_conditions:
  file_types:
    - .pdf
    - .xlsx
    - .docx
  keywords: []  # 空の場合はすべて
  date_range:
    start: null  # YYYY-MM-DD形式
    end: null

# 保存先
save_paths:
  local: ./downloads
  box:
    enabled: false
    folder_id: null

# ファイル命名規則
naming_rule: "{category}_{title}_{date}_{index}"

# スケジュール設定
schedule:
  enabled: false
  interval: "daily"  # daily, weekly, custom
  time: "09:00"      # HH:MM形式
  cron: null         # cron形式（intervalがcustomの場合）

# ログ設定
logging:
  level: INFO
  file: ./logs/app.log
  max_bytes: 10485760  # 10MB
  backup_count: 5
```

## 5. 開発環境

### 5.1 必要な環境

- Python 3.10以上（推奨: 3.11+）
- pip（パッケージマネージャー）
- 仮想環境（venv推奨）

### 5.2 セットアップ手順（案）

```bash
# プロジェクトディレクトリに移動
cd ppi-file-downloader

# 仮想環境を作成
python -m venv venv

# 仮想環境を有効化
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

# 依存関係をインストール
pip install -r requirements.txt
```

## 6. 代替案

### 6.1 Node.jsを選ぶ場合

**選定条件:**
- 非同期処理を重視する場合
- 既存のNode.js環境がある場合
- TypeScriptで型安全性を確保したい場合

### 6.2 Goを選ぶ場合

**選定条件:**
- パフォーマンスを最優先する場合
- シングルバイナリで配布したい場合
- リソース制約が厳しい環境で実行する場合

## 7. GUI実装詳細

### 7.1 GUIライブラリ選定: tkinter

**選定理由:**
1. **標準ライブラリ**
   - Pythonに標準で含まれており、追加インストール不要
   - 実行ファイル化時に依存関係が少ない
2. **シンプルで使いやすい**
   - 基本的なGUI要素（ボタン、テキストボックス、リストボックス等）が揃っている
   - 学習コストが低い
3. **クロスプラットフォーム**
   - Windows、Linux、macOSで動作
4. **実行ファイル化との相性**
   - PyInstallerとの相性が良い
   - ファイルサイズが小さい

**代替案:**
- **PyQt/PySide**: より高機能だが、ライセンスやファイルサイズの課題
- **Kivy**: モダンなUIだが、学習コストが高い

### 7.2 GUI画面構成（案）

1. **メインウィンドウ**
   - 対象URL入力欄
   - ファイルタイプ選択（チェックボックス）
   - キーワード入力欄
   - 日付範囲選択
   - 保存先フォルダ選択ボタン
   - Box連携設定ボタン
   - 「ダウンロード開始」ボタン
   - 「設定保存」ボタン
   - 「設定読み込み」ボタン

2. **進捗表示ウィンドウ**
   - 進捗バー
   - 現在ダウンロード中のファイル名
   - ダウンロード済みファイル数 / 総ファイル数
   - 「キャンセル」ボタン

3. **ログ表示ウィンドウ**
   - ログ表示エリア（テキストウィジェット）
   - ログレベルフィルター
   - ログクリアボタン

4. **設定ダイアログ**
   - 各種設定項目の入力欄
   - 「OK」「キャンセル」ボタン

### 7.3 実行ファイル化

#### 7.3.1 PyInstaller選定

**選定理由:**
1. **シングル実行ファイル化**
   - `--onefile`オプションで1つの.exeファイルにまとめられる
   - ユーザーがPython環境を用意する必要がない
2. **Windows対応**
   - Windows向けの.exeファイル生成が容易
3. **依存関係の自動検出**
   - 必要なライブラリを自動的に含める
4. **広く使われている**
   - 実績が多く、ドキュメントが充実

**使用方法（案）:**
```bash
# シングル実行ファイル生成
pyinstaller --onefile --windowed --name ppi-file-downloader src/main.py

# オプション説明
# --onefile: 1つの実行ファイルにまとめる
# --windowed: コンソールウィンドウを表示しない（GUIアプリ用）
# --name: 実行ファイル名を指定
```

#### 7.3.2 ビルド設定

**PyInstaller設定ファイル（.spec）の作成:**
- アイコンの設定
- データファイルの含め方
- 除外するモジュールの指定

## 8. Seleniumの必要性について

### 8.1 調査結果

実際のWebページ（https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4）を確認した結果：

#### 8.1.1 ページ構造の特徴

1. **ASP.NET WebForms形式**
   - `__VIEWSTATE`と`__EVENTVALIDATION`のhiddenフィールドが存在
   - POSTメソッドでフォーム送信
   - サーバーサイドでHTMLを生成

2. **JavaScriptの使用状況**
   - UI操作用のJavaScript（文字サイズ変更、ポップアップ等）は存在
   - ページの主要コンテンツはJavaScriptで動的生成されていない
   - 階層的なドロップダウン（大分類→中分類→小分類）は、最初のページ読み込み時には空の可能性がある

3. **フォーム送信**
   - 通常のHTMLフォーム（POST）で送信可能
   - ViewStateとEventValidationはrequestsライブラリで処理可能

#### 8.1.2 結論：**Seleniumは基本的に不要**

**理由:**
- ページのHTMLはサーバーサイドで生成されており、初回リクエストで取得可能
- フォーム送信は通常のPOSTリクエストで対応可能
- ViewStateとEventValidationはrequestsライブラリで処理可能
- JavaScriptで動的に生成される主要コンテンツは少ない

**ただし、以下の場合にはSeleniumが必要になる可能性がある:**
- 階層的なドロップダウン（大分類→中分類→小分類）がJavaScriptで動的に読み込まれる場合
- 検索結果ページがJavaScriptで動的に生成される場合
- ファイルリンクがJavaScriptで動的に生成される場合

### 8.2 推奨アプローチ

1. **まずはrequests + BeautifulSoupで実装**
   - 基本的なスクレイピングはrequests + BeautifulSoupで対応
   - ViewStateとEventValidationを適切に処理
   - セッション管理でCookieを維持

2. **必要に応じてSeleniumを追加**
   - 実装中にJavaScriptによる動的生成が必要と判明した場合のみ追加
   - Seleniumは実行ファイルサイズが大きくなるため、可能な限り避ける

3. **ハイブリッドアプローチ**
   - 基本的なページ取得はrequests
   - JavaScriptが必要な部分のみSeleniumを使用

### 8.3 実装時の注意点

- **ViewStateとEventValidationの処理**: ASP.NET WebFormsでは必須
- **セッション管理**: Cookieを適切に維持
- **階層的ドロップダウンの処理**: 必要に応じてAJAXリクエストを模倣
- **レート制限**: 過度なリクエストを避ける

## 9. 今後の検討事項

### 8.1 並列処理

- **concurrent.futures**: 標準ライブラリ、スレッドプール
- **asyncio**: 非同期処理（requestsの代わりにhttpxを使用）

### 8.2 テスト

- **pytest**: テストフレームワーク
- **unittest**: 標準ライブラリ

### 8.3 配布方法

- **GitHub Releases**: 実行ファイルの配布
- **インストーラー**: Inno Setup、NSIS等を使用したインストーラー作成

---

**作成日**: 2025年12月17日  
**バージョン**: 1.0  
**ステータス**: 確定

