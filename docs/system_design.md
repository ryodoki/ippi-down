# システム設計書

## 1. 設計方針

### 1.1 設計原則

- **保守性**: コードの可読性を重視し、モジュール化を徹底する
- **拡張性**: 将来的な機能追加に対応できる柔軟な設計
- **ユーザビリティ**: GUIを中心とした直感的な操作
- **堅牢性**: エラーハンドリングを適切に実装し、異常時も安全に動作

### 1.2 アーキテクチャパターン

- **MVC（Model-View-Controller）パターン**: GUIとビジネスロジックの分離
- **レイヤードアーキテクチャ**: プレゼンテーション層、ビジネスロジック層、データアクセス層に分離

## 2. システムアーキテクチャ

### 2.1 全体構成

```
┌─────────────────────────────────────────────────────────┐
│                    GUI Layer (tkinter)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Main Window  │  │ Settings UI  │  │ Progress UI  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              Business Logic Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Scraper    │  │  Downloader  │  │  Scheduler  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│  ┌──────────────┐  ┌──────────────┐                   │
│  │   Naming     │  │   Config     │                   │
│  └──────────────┘  └──────────────┘                   │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              Data Access Layer                           │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ HTTP Client  │  │ File System │                     │
│  │ (requests)   │  │             │                     │
│  └──────────────┘  └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
```

### 2.2 レイヤー説明

#### 2.2.1 GUI Layer（プレゼンテーション層）
- ユーザーインターフェースの表示と操作を受け付ける
- ビジネスロジック層への指示を送信
- 処理結果をユーザーに表示

#### 2.2.2 Business Logic Layer（ビジネスロジック層）
- コア機能の実装
- データアクセス層を利用してデータを取得・保存
- GUI層からの指示を受け取り、処理を実行

#### 2.2.3 Data Access Layer（データアクセス層）
- 外部リソース（Web、ファイルシステム）へのアクセス
- 低レベルの通信処理を担当

## 3. モジュール構成

### 3.1 ディレクトリ構造

```
ppi-file-downloader/
├── src/
│   ├── __init__.py
│   ├── main.py                 # エントリーポイント（GUI起動）
│   ├── main_cli.py             # CLI版エントリーポイント（開発用）
│   │
│   ├── gui/                    # GUIモジュール
│   │   ├── __init__.py
│   │   ├── main_window.py     # メインウィンドウ
│   │   ├── settings_dialog.py  # 設定ダイアログ
│   │   ├── progress_window.py # 進捗表示ウィンドウ
│   │   ├── log_viewer.py      # ログ表示ウィンドウ
│   │   └── widgets.py          # カスタムウィジェット
│   │
│   ├── core/                   # コア機能モジュール
│   │   ├── __init__.py
│   │   ├── scraper.py         # HTML解析・スクレイピング
│   │   ├── downloader.py      # ファイルダウンロード
│   │   ├── naming.py          # ファイル命名
│   │   └── filter.py          # 条件フィルタリング
│   │
│   ├── storage/                # ストレージモジュール
│   │   ├── __init__.py
│   │   └── local_storage.py   # ローカル保存
│   │
│   ├── scheduler/              # スケジューリングモジュール
│   │   ├── __init__.py
│   │   └── scheduler.py       # 定期実行管理
│   │
│   ├── config/                 # 設定管理モジュール
│   │   ├── __init__.py
│   │   ├── config_manager.py  # 設定ファイル管理
│   │   └── config_validator.py # 設定検証
│   │
│   ├── utils/                  # ユーティリティモジュール
│   │   ├── __init__.py
│   │   ├── logger.py          # ログ管理
│   │   ├── http_client.py    # HTTPクライアント（セッション管理）
│   │   └── file_utils.py      # ファイル操作ユーティリティ
│   │
│   └── models/                 # データモデル
│       ├── __init__.py
│       ├── config_model.py   # 設定データモデル
│       ├── file_info.py      # ファイル情報モデル
│       └── download_task.py  # ダウンロードタスクモデル
│
├── config/
│   ├── config.yaml            # 設定ファイル（テンプレート）
│   └── config.example.yaml    # 設定ファイル例
│
├── logs/                      # ログファイル保存先
│
├── tests/                     # テストコード
│   ├── __init__.py
│   ├── test_scraper.py
│   ├── test_downloader.py
│   └── test_config.py
│
├── build/                    # ビルド成果物（PyInstaller）
├── dist/                     # 配布用実行ファイル
│
├── requirements.txt          # 依存関係
├── .env.example             # 環境変数テンプレート
├── build_exe.py             # 実行ファイルビルドスクリプト
│
├── README.md
├── 要件定義書.md
├── 技術選定.md
└── システム設計書.md
```

## 4. データフロー

### 4.1 ダウンロード処理のフロー

```
[ユーザー操作]
    │
    ▼
[GUI: ダウンロード開始ボタンクリック]
    │
    ▼
[Config Manager: 設定ファイル読み込み]
    │
    ▼
[Scraper: HTML取得・解析]
    │  ┌─────────────────┐
    │  │ HTTP Client      │
    │  │ (requests)       │
    │  └─────────────────┘
    │
    ▼
[Filter: 条件に一致するファイルを抽出]
    │
    ▼
[Downloader: ファイルダウンロード]
    │  ┌─────────────────┐
    │  │ HTTP Client      │
    │  │ (requests)       │
    │  └─────────────────┘
    │
    ▼
[Naming: ファイル名生成]
    │
    ▼
[Local Storage: ローカルに保存]
    │
    ▼
[GUI: 進捗表示・完了通知]
```

### 4.2 設定管理のフロー

```
[ユーザー操作]
    │
    ▼
[GUI: 設定画面を開く]
    │
    ▼
[Config Manager: 設定ファイル読み込み]
    │
    ▼
[GUI: 設定項目を表示・編集]
    │
    ▼
[Config Validator: 設定値の検証]
    │
    ▼
[Config Manager: 設定ファイル保存]
    │
    ▼
[GUI: 保存完了通知]
```

## 5. クラス設計

### 5.1 コアモジュール

#### 5.1.1 Scraper（スクレイパー）

```python
class Scraper:
    """HTML解析・スクレイピングを行うクラス"""
    
    def __init__(self, http_client: HTTPClient, logger: Logger)
    def fetch_page(self, url: str) -> BeautifulSoup
    def extract_file_links(self, soup: BeautifulSoup, base_url: str) -> List[FileInfo]
    def extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]
    def parse_viewstate(self, soup: BeautifulSoup) -> Tuple[str, str]
```

#### 5.1.2 Downloader（ダウンローダー）

```python
class Downloader:
    """ファイルダウンロードを行うクラス"""
    
    def __init__(self, http_client: HTTPClient, logger: Logger)
    def download_file(self, file_info: FileInfo, save_path: str) -> bool
    def download_files(self, file_list: List[FileInfo], save_dir: str, 
                      progress_callback: Callable = None) -> DownloadResult
    def retry_download(self, file_info: FileInfo, max_retries: int = 3) -> bool
    def check_duplicate(self, file_path: str) -> bool
```

#### 5.1.3 Filter（フィルター）

```python
class Filter:
    """ダウンロード条件でフィルタリングを行うクラス"""
    
    def __init__(self, config: DownloadConfig)
    def filter_files(self, file_list: List[FileInfo]) -> List[FileInfo]
    def match_file_type(self, file_info: FileInfo) -> bool
    def match_keywords(self, file_info: FileInfo) -> bool
    def match_date_range(self, file_info: FileInfo) -> bool
```

#### 5.1.4 Naming（命名）

```python
class Naming:
    """ファイル名を生成するクラス"""
    
    def __init__(self, naming_rule: str)
    def generate_filename(self, file_info: FileInfo, metadata: Dict[str, Any]) -> str
    def sanitize_filename(self, filename: str) -> str
    def ensure_unique(self, file_path: str) -> str
```

### 5.2 ストレージモジュール

#### 5.2.1 LocalStorage（ローカルストレージ）

```python
class LocalStorage:
    """ローカルファイルシステムへの保存を行うクラス"""
    
    def __init__(self, base_path: str, logger: Logger)
    def save_file(self, file_data: bytes, file_path: str) -> bool
    def create_directory_structure(self, path: str) -> bool
    def get_save_path(self, file_info: FileInfo, naming: Naming) -> str
```

### 5.3 設定管理モジュール

#### 5.3.1 ConfigManager（設定マネージャー）

```python
class ConfigManager:
    """設定ファイルの読み込み・保存を行うクラス"""
    
    def __init__(self, config_path: str)
    def load_config(self) -> AppConfig
    def save_config(self, config: AppConfig) -> bool
    def validate_config(self, config: AppConfig) -> Tuple[bool, List[str]]
    def get_default_config(self) -> AppConfig
```

#### 5.3.2 AppConfig（設定データモデル）

```python
@dataclass
class AppConfig:
    """アプリケーション設定のデータモデル"""
    target_urls: List[str]
    download_conditions: DownloadConditions
    save_paths: SavePaths
    naming_rule: str
    schedule: ScheduleConfig
    logging: LoggingConfig
```

### 5.4 GUIモジュール

#### 5.4.1 MainWindow（メインウィンドウ）

```python
class MainWindow:
    """メインウィンドウクラス"""
    
    def __init__(self, root: tk.Tk)
    def setup_ui(self)
    def on_download_start(self)
    def on_settings_open(self)
    def update_progress(self, current: int, total: int)
    def show_message(self, message: str, level: str = "info")
```

#### 5.4.2 SettingsDialog（設定ダイアログ）

```python
class SettingsDialog:
    """設定ダイアログクラス"""
    
    def __init__(self, parent: tk.Tk, config: AppConfig)
    def setup_ui(self)
    def on_save(self) -> AppConfig
    def on_cancel(self)
    def validate_input(self) -> Tuple[bool, str]
```

### 5.5 ユーティリティモジュール

#### 5.5.1 HTTPClient（HTTPクライアント）

```python
class HTTPClient:
    """HTTP通信を行うクラス（セッション管理含む）"""
    
    def __init__(self, logger: Logger)
    def get(self, url: str, **kwargs) -> requests.Response
    def post(self, url: str, data: Dict = None, **kwargs) -> requests.Response
    def download_file(self, url: str, save_path: str, 
                     progress_callback: Callable = None) -> bool
    def get_session(self) -> requests.Session
```

#### 5.5.2 Logger（ロガー）

```python
class Logger:
    """ログ管理を行うクラス"""
    
    def __init__(self, config: LoggingConfig)
    def debug(self, message: str)
    def info(self, message: str)
    def warning(self, message: str)
    def error(self, message: str, exc_info: bool = False)
    def setup_file_handler(self, log_file: str)
```

## 6. データモデル

### 6.1 FileInfo（ファイル情報）

```python
@dataclass
class FileInfo:
    """ファイル情報を保持するデータモデル"""
    url: str                    # ファイルURL
    filename: str              # 元のファイル名
    file_type: str            # ファイルタイプ（拡張子）
    size: int = 0              # ファイルサイズ（バイト）
    metadata: Dict[str, Any] = None  # メタデータ（タイトル、カテゴリ、日付等）
    page_url: str = ""         # 元のページURL
```

### 6.2 DownloadTask（ダウンロードタスク）

```python
@dataclass
class DownloadTask:
    """ダウンロードタスクを保持するデータモデル"""
    file_info: FileInfo
    local_path: str
    status: str = "pending"    # pending, downloading, completed, failed
    error_message: str = ""
    retry_count: int = 0
```

### 6.3 DownloadResult（ダウンロード結果）

```python
@dataclass
class DownloadResult:
    """ダウンロード結果を保持するデータモデル"""
    total: int                 # 総ファイル数
    success: int               # 成功数
    failed: int                # 失敗数
    skipped: int               # スキップ数
    tasks: List[DownloadTask]  # タスクリスト
```

## 7. インターフェース設計

### 7.1 設定ファイル構造（YAML）

```yaml
# 対象URL
target_urls:
  - https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4

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

### 7.2 GUI画面設計

#### 7.2.1 メインウィンドウ

```
┌─────────────────────────────────────────────────────┐
│  ppi-file-downloader                    [×]        │
├─────────────────────────────────────────────────────┤
│                                                      │
│  [設定]  [ダウンロード開始]  [ログ表示]              │
│                                                      │
│  ┌──────────────────────────────────────────────┐  │
│  │ 対象URL:                                      │  │
│  │ [https://www.i-ppi.jp/...]  [参照]          │  │
│  └──────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────────────────────────────────────────┐  │
│  │ ファイルタイプ:                              │  │
│  │ ☑ PDF  ☑ Excel  ☑ Word  ☐ 画像            │  │
│  └──────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────────────────────────────────────────┐  │
│  │ 保存先:                                      │  │
│  │ [C:\downloads]  [参照]                      │  │
│  └──────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────────────────────────────────────────┐  │
│  │ 進捗:                                        │  │
│  │ [████████░░░░░░░░░░] 50% (10/20)            │  │
│  │ 現在: example.pdf をダウンロード中...        │  │
│  └──────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────────────────────────────────────────┐  │
│  │ ログ:                                        │  │
│  │ [INFO] ダウンロードを開始しました            │  │
│  │ [INFO] example.pdf をダウンロード中...       │  │
│  │                                               │  │
│  └──────────────────────────────────────────────┘  │
│                                                      │
└─────────────────────────────────────────────────────┘
```

## 8. エラーハンドリング

### 8.1 エラー分類

1. **ネットワークエラー**
   - 接続エラー
   - タイムアウト
   - HTTPエラー（404, 500等）

2. **ファイルシステムエラー**
   - ディレクトリ作成失敗
   - ファイル書き込み失敗
   - ディスク容量不足

3. **設定エラー**
   - 設定ファイル読み込み失敗
   - 設定値の検証エラー

### 8.2 エラー処理方針

- エラーはログに記録
- ユーザーに分かりやすいエラーメッセージを表示
- 可能な限り処理を継続（1つのファイルのエラーで全体を止めない）
- リトライ機能を実装

## 9. セキュリティ設計

### 9.1 入力検証

- URLの検証
- ファイルパスの検証（パストラバーサル対策）
- 設定値の型チェック

## 10. パフォーマンス設計

### 10.1 最適化方針

- 並列ダウンロードは初期実装では行わない（将来の拡張）
- セッション管理でHTTP接続を再利用
- 重複チェックを効率的に実装

### 10.2 リソース管理

- メモリ使用量の監視
- ファイルハンドルの適切なクローズ
- ネットワーク接続の適切な管理

---

**作成日**: 2025年12月17日  
**バージョン**: 1.0  
**ステータス**: 草案

