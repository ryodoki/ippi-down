# ppi-file-downloader 実装設計書

## 1. 概要

本ドキュメントは、ppi-file-downloaderの実装に必要な詳細設計を記述する。
要件定義書で定義された機能要件・非機能要件を実現するための技術的な設計方針を示す。

**関連文書**: [要件定義書](./要件定義書_レビュー版.md)

---

## 2. YAML設定ファイルスキーマ

### 2.1 完全なスキーマ定義

```yaml
# ============================================
# ppi-file-downloader 設定ファイル
# ============================================

# 対象URL（検索画面）
target:
  url: string  # 必須: 検索画面URL
               # 例: "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"

# フィルタ条件
filters:
  file_types: array[string]  # 必須: 拡張子リスト（空配列の場合はすべて）
                             # 例: [".pdf", ".xlsx", ".docx"]
                             # 注: 入力は .PDF でもOK、内部で .pdf に正規化（小文字・ドット付き）
  keywords: array[string]  # オプション: キーワード（空配列の場合はすべて）
                           # 例: ["工事", "設計"]
                           # 注: 文字列ではなく配列固定（GUIでカンマ区切り入力→配列に分解）
  date_range:
    start: string | null  # オプション: 開始日（YYYY-MM-DD形式、両端含む）
                          # 例: "2025-01-01"
                          # 注: ppi.jpの検索条件として「公告日」基準で適用
    end: string | null    # オプション: 終了日（YYYY-MM-DD形式、両端含む）
                          # 例: "2025-12-31"
                          # 注: 未指定の場合は今日まで

# 保存先
save:
  local_dir: string  # 必須: ローカル保存先パス
                      # 例: "./downloads"

# ファイル命名規則
naming:
  template: string  # 必須: テンプレート文字列
                   # 使用可能な変数: {filename}, {file_type}, {category}, {title}, {date}, {index}
                   # 例: "{category}_{title}_{date}_{index}"
                   # 注: 禁止文字（<>:"/\|?* と末尾の . とスペース）は _ に置換
                   #     パス長が260文字を超える場合は切り詰める

# ダウンロード設定
download:
  retry:
    count: integer  # オプション: リトライ回数（デフォルト: 3）
    base_seconds: integer  # オプション: 指数バックオフの初期待機時間（秒、デフォルト: 1）
    max_wait_seconds: integer  # オプション: 指数バックオフの最大待機時間（秒、デフォルト: 60）
  timeout:
    connect: integer  # オプション: 接続タイムアウト（秒、デフォルト: 10）
    read: integer  # オプション: 読み込みタイムアウト（秒、デフォルト: 60）
  part_file:
    on_cancel: string  # オプション: キャンセル時の.partファイル処理
                       # "keep" または "delete"（デフォルト: "keep")
    on_resume: string  # オプション: 次回実行時に.partファイルがあった場合の処理
                       # "delete_and_retry" または "overwrite"（デフォルト: "delete_and_retry")
                       # 注: HTTP Rangeによる途中再開は将来拡張

# スケジュール設定
schedule:
  enabled: boolean  # オプション: スケジュール実行を有効化（デフォルト: false）
  interval: integer | null  # オプション: 実行間隔（分単位）
                            # 例: 60（60分ごと）
                            # 注: interval と time は同時指定不可（両方指定された場合はエラー）
  time: string | null  # オプション: 実行時刻（HH:MM形式）
                       # 例: "09:00"
                       # 注: interval と time は同時指定不可（両方指定された場合はエラー）

# ログ設定
logging:
  level: string  # オプション: ログレベル（デフォルト: "INFO"）
                 # 有効値: "DEBUG", "INFO", "WARNING", "ERROR"
  path: string  # オプション: 通常ログファイルパス（デフォルト: "./logs/app.log"）
  failures_path: string  # オプション: 失敗ログファイルパス（JSON Lines形式、デフォルト: "./logs/failures.jsonl"）
  max_bytes: integer  # オプション: 最大ファイルサイズ（バイト、デフォルト: 10485760 = 10MB）
  backup_count: integer  # オプション: ローテーション世代数（デフォルト: 5）
```

### 2.2 設定ファイル例

```yaml
target:
  url: "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"

filters:
  file_types:
    - ".pdf"
    - ".xlsx"
    - ".docx"
  keywords:
    - "工事"
    - "設計"
  date_range:
    start: "2025-01-01"
    end: "2025-12-31"

save:
  local_dir: "./downloads"

naming:
  template: "{category}_{title}_{date}_{index}"

download:
  retry:
    count: 3
    base_seconds: 1
    max_wait_seconds: 60
  timeout:
    connect: 10
    read: 60
  part_file:
    on_cancel: "keep"
    on_resume: "delete_and_retry"

schedule:
  enabled: false
  interval: 60
  # time: "09:00"  # interval と time は同時指定不可

logging:
  level: "INFO"
  path: "./logs/app.log"
  failures_path: "./logs/failures.jsonl"
  max_bytes: 10485760
  backup_count: 5
```

---

## 3. ログ出力フォーマット

### 3.1 通常ログ（テキスト形式）

**フォーマット**: `[YYYY-MM-DD HH:MM:SS,mmm] [LEVEL] [MODULE] - MESSAGE`

**例**:
```
[2026-01-07 10:30:45,123] [INFO] [ppi_file_downloader.scraper] - ページを取得中: https://www.i-ppi.jp/...
[2026-01-07 10:30:46,456] [ERROR] [ppi_file_downloader.downloader] - ダウンロード失敗: Connection timeout
```

### 3.2 失敗ログ（JSON Lines形式）

**フォーマット**: 1行1イベントのJSON形式

**必須フィールド**:
- `run_id`: string - 実行単位のID（同一実行の紐付け用、UUID形式）
- `url`: string - 対象URL
- `status_code`: integer | null - HTTPステータスコード（エラーの場合）
- `error_type`: string - エラー種別
  - `timeout`: タイムアウト
  - `connection_error`: 接続エラー
  - `http_error`: HTTPエラー（4xx, 5xx）
  - `file_system_error`: ファイルシステムエラー
  - `other`: その他
- `retry_count`: integer - 再試行回数（0から開始）
- `timestamp`: string - エラー発生時刻（ISO 8601形式）
- `message`: string - エラーメッセージ
- `phase`: string - 処理段階
  - `search`: 検索処理
  - `detail`: 詳細ページ取得
  - `download`: ファイルダウンロード
- `method`: string - HTTPメソッド（"GET" または "POST"）
- `elapsed_ms`: integer - 処理時間（ミリ秒）
- `file_name`: string | null - 保存名（または予定名）

**オプションフィールド**:
- `content_type`: string - Content-Typeヘッダー（取得できた場合）
- `exception_type`: string - 例外クラス名
- `stack_trace`: string - スタックトレース（DEBUGレベル時）

**例**:
```json
{"run_id": "550e8400-e29b-41d4-a716-446655440000", "url": "https://www.i-ppi.jp/.../file.pdf", "status_code": 429, "error_type": "http_error", "retry_count": 1, "timestamp": "2026-01-07T10:30:45.123Z", "message": "Too Many Requests", "phase": "download", "method": "GET", "elapsed_ms": 5000, "file_name": "工事_設計_2025-01-01_1.pdf", "content_type": "application/pdf"}
{"run_id": "550e8400-e29b-41d4-a716-446655440000", "url": "https://www.i-ppi.jp/.../file2.pdf", "status_code": null, "error_type": "timeout", "retry_count": 3, "timestamp": "2026-01-07T10:31:00.456Z", "message": "Connection timeout after 10 seconds", "phase": "download", "method": "GET", "elapsed_ms": 10000, "file_name": "工事_設計_2025-01-02_1.pdf"}
```

### 3.3 ログファイルの配置

- **通常ログ**: `{logging.path}` に出力
- **失敗ログ**: `{logging.failures_path}` に出力（JSON Lines形式、デフォルト: `./logs/failures.jsonl`）

---

## 4. スクレイピングの状態遷移

### 4.1 状態遷移図

```
┌─────────────────────────────────────────────────────────────────┐
│                     開始（GUI/CLI起動）                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. 検索画面GET                                                  │
│     URL: Search/Search/Search.aspx?tab=4                        │
│     → __VIEWSTATE, __EVENTVALIDATION 取得                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. 検索条件POST                                                 │
│     POST: Search/Search/Search.aspx?tab=4                       │
│     Body: __VIEWSTATE, __EVENTVALIDATION, 検索条件               │
│     → 検索結果HTML取得                                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. 検索結果解析                                                │
│     → 結果行を抽出（発注機関、工事名、日付等）                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ 結果行ごとに  │
                    └──────┬───────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. 詳細表示POST（または遷移）                                   │
│     POST: __doPostBack または GET: List_Detail.aspx?tab=4       │
│     → 詳細ページHTML取得                                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. 添付ファイルURL抽出                                          │
│     → dgrKokoku, dgrKeika テーブルからリンク抽出                │
│     → KokaiBunshoServlet などのURL取得                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. ファイルダウンロード                                         │
│     GET: ファイルURL                                             │
│     → .part ファイルとして保存開始                               │
│     → ダウンロード完了後、リネーム                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ 次の結果行へ  │
                    └──────┬───────┘
                           │
                    ┌──────┴───────┐
                    │               │
                    ▼               ▼
            ┌─────────────┐  ┌─────────────┐
            │ すべて完了   │  │ キャンセル   │
            └──────┬──────┘  └──────┬──────┘
                   │                │
                   ▼                ▼
        ┌──────────────────┐  ┌──────────────────┐
        │ 実行結果サマリー  │  │ .part処理         │
        │ ログ出力         │  │ （keep/delete）   │
        └──────────────────┘  └──────────────────┘
```

### 4.2 各状態の詳細

#### 状態1: 検索画面GET
- **目的**: 初期状態を取得し、ASP.NET WebFormsの`__VIEWSTATE`と`__EVENTVALIDATION`を取得
- **HTTPメソッド**: GET
- **レスポンス**: HTML（検索フォームを含む）

#### 状態2: 検索条件POST
- **目的**: 検索条件を送信し、検索結果を取得
- **HTTPメソッド**: POST
- **リクエストボディ**: 
  - `__VIEWSTATE`, `__EVENTVALIDATION`（状態1で取得）
  - 検索条件（発注機関、キーワード、日付範囲等）
- **レスポンス**: HTML（検索結果テーブルを含む）

#### 状態3: 検索結果解析
- **目的**: 検索結果から各案件の情報を抽出
- **処理**: 
  - テーブル行を解析
  - 発注機関、工事名、日付等のメタデータを抽出
  - フィルタ条件に一致する行を特定

#### 状態4: 詳細表示POST/GET
- **目的**: 各案件の詳細ページを取得
- **HTTPメソッド**: POST（`__doPostBack`）またはGET
- **処理**: 
  - `__doPostBack`の場合は`__EVENTTARGET`と`__EVENTARGUMENT`を抽出してPOST
  - または直接URLに遷移
- **レスポンス**: HTML（詳細ページ、添付ファイル情報を含む）

#### 状態5: 添付ファイルURL抽出
- **目的**: 詳細ページからファイルダウンロードURLを抽出
- **処理**: 
  - `dgrKokoku`テーブルからリンク抽出
  - `dgrKeika`テーブルからリンク抽出
  - `KokaiBunshoServlet`などのURLを特定

#### 状態6: ファイルダウンロード
- **目的**: ファイルをダウンロードして保存
- **HTTPメソッド**: GET
- **処理**: 
  1. `.part`拡張子で一時ファイルとして保存開始
  2. `stream=True`でチャンクごとに書き込み
  3. キャンセルフラグをチェック（中断可能）
  4. ダウンロード完了後、`.part`を削除して正式ファイル名にリネーム

---

## 5. GUI設計（キャンセル対応）

### 5.1 アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                    GUI（メインスレッド）                  │
│  - tkinter ウィンドウ                                     │
│  - 進捗バー、ログ表示                                     │
│  - ボタン（開始、キャンセル）                             │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ root.after() で更新
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              ダウンロード処理（ワーカースレッド）           │
│  - スクレイピング処理                                     │
│  - ファイルダウンロード                                   │
│  - threading.Event でキャンセルフラグ管理                │
└─────────────────────────────────────────────────────────┘
```

### 5.2 実装方針

#### 5.2.1 スレッド分離
- **メインスレッド**: GUIの表示・操作のみ
- **ワーカースレッド**: ダウンロード処理（`threading.Thread`）

#### 5.2.2 GUI更新
- **方法**: `root.after(delay, callback)` を使用
- **理由**: tkinterはスレッドセーフではないため、メインスレッドから更新する必要がある
- **実装例**:
```python
def update_progress():
    # ワーカースレッドから進捗情報を取得
    progress = download_thread.get_progress()
    progress_bar['value'] = progress
    # 次回更新をスケジュール
    root.after(100, update_progress)  # 100msごとに更新
```

#### 5.2.3 キャンセル処理
- **フラグ管理**: `threading.Event` を使用
```python
# キャンセルフラグ
cancel_event = threading.Event()

# キャンセルボタンクリック時
def on_cancel():
    cancel_event.set()

# ダウンロード処理内
def download_file(url, path):
    if cancel_event.is_set():
        return  # キャンセルされた
    # ダウンロード処理...
```

#### 5.2.4 ストリーミングダウンロード
- **方法**: `requests.get(stream=True)` を使用
- **チャンク書き込み**: 一定サイズごとにファイルに書き込み、キャンセルフラグをチェック
```python
def download_file(url, path, cancel_event):
    response = requests.get(url, stream=True, timeout=(10, 60))
    with open(path + '.part', 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if cancel_event.is_set():
                # キャンセルされた場合、.partファイルを処理
                handle_cancelled_part_file(path + '.part')
                return
            f.write(chunk)
    # ダウンロード完了後、リネーム
    os.rename(path + '.part', path)
```

### 5.3 状態管理

- **アイドル**: ダウンロード待機中
- **実行中**: ダウンロード処理中
- **キャンセル中**: キャンセル処理中（GUIは応答し続ける）
- **完了**: ダウンロード完了

### 5.4 エラーハンドリング

- **ネットワークエラー**: ログに記録し、処理を継続
- **ファイルシステムエラー**: ログに記録し、処理を継続
- **予期しないエラー**: ログに記録し、GUIにエラーダイアログを表示（処理は継続）

---

## 6. モジュール構成

### 6.1 責務分割

```
src/
├── config/              # 設定管理
│   ├── config_manager.py      # YAMLロード・デフォルト適用
│   └── config_validator.py    # バリデーション
├── core/               # コア機能
│   ├── scraper.py             # HTML解析、VIEWSTATE/イベント処理
│   ├── downloader.py          # stream保存、.part、重複判定
│   └── filter.py              # フィルタ条件適用
├── http/               # HTTP通信（将来リファクタリング候補）
│   └── http_client.py         # Session/リトライ/レート制限/タイムアウト
├── ui/                 # GUI
│   ├── main_window.py         # tkinter、進捗、キャンセル
│   └── settings_dialog.py     # 設定ダイアログ
├── logging/           # ログ機能
│   └── logger.py              # 通常ログ + failures.jsonl
├── scheduler/          # スケジューリング
│   └── scheduler.py           # アプリ起動中のみ実行
└── models/            # データモデル
    ├── file_info.py           # ファイル情報
    ├── config_model.py        # 設定モデル
    └── download_result.py    # ダウンロード結果
```

### 6.2 各モジュールの責務

#### config/config_manager.py
- YAML設定ファイルの読み込み
- デフォルト値の適用
- 設定の保存

#### config/config_validator.py
- 設定値のバリデーション
- 型チェック
- 値の範囲チェック
- 排他条件チェック（schedule.interval と schedule.time）

#### core/scraper.py
- HTML解析（BeautifulSoup）
- VIEWSTATE/EVENTVALIDATIONの取得・管理
- __doPostBack処理
- 検索結果の解析
- 詳細ページの取得
- 添付ファイルURLの抽出

#### core/downloader.py
- ファイルダウンロード（ストリーミング）
- .partファイルの管理
- 重複判定（URL、ファイル名+サイズ、ハッシュ）
- リトライ処理（指数バックオフ）
- タイムアウト処理

#### core/filter.py
- フィルタ条件の適用
- ファイルタイプフィルタ
- キーワードフィルタ
- 日付範囲フィルタ

#### http/http_client.py
- HTTPセッション管理
- リトライ処理
- レート制限（1〜2 req/sec）
- タイムアウト設定
- User-Agent設定

#### ui/main_window.py
- tkinterメインウィンドウ
- 進捗表示（進捗バー、ログ表示）
- キャンセル処理（threading.Event）
- スレッド分離（メインスレッド/ワーカースレッド）

#### ui/settings_dialog.py
- 設定ダイアログ
- 設定値の入力・編集
- 設定の保存

#### logging/logger.py
- 通常ログ（テキスト形式）
- 失敗ログ（JSON Lines形式）
- ログローテーション

#### scheduler/scheduler.py
- スケジュール実行（アプリ起動中のみ）
- 間隔実行（interval）
- 時刻実行（time）

---

## 7. 設定バリデーション仕様

### 7.1 必須項目チェック

- `target.url`: 必須、文字列、URL形式
- `filters.file_types`: 必須、配列（空配列可）
- `save.local_dir`: 必須、文字列、パス形式
- `naming.template`: 必須、文字列

### 7.2 型チェック

- `filters.file_types`: 配列[string]
- `filters.keywords`: 配列[string]（文字列は不可）
- `filters.date_range.start/end`: 文字列（YYYY-MM-DD形式）またはnull
- `download.retry.count`: 整数（1以上）
- `download.retry.base_seconds`: 整数（1以上）
- `download.retry.max_wait_seconds`: 整数（base_seconds以上）
- `download.timeout.connect/read`: 整数（1以上）
- `schedule.interval`: 整数（1以上）またはnull
- `schedule.time`: 文字列（HH:MM形式）またはnull
- `logging.level`: 文字列（"DEBUG", "INFO", "WARNING", "ERROR"のいずれか）

### 7.3 値の範囲チェック

- `download.retry.count`: 1〜10
- `download.retry.base_seconds`: 1〜60
- `download.retry.max_wait_seconds`: base_seconds以上、最大300
- `download.timeout.connect`: 1〜300
- `download.timeout.read`: 1〜600
- `schedule.interval`: 1〜1440（分単位、24時間以内）
- `logging.max_bytes`: 1024以上（1KB以上）
- `logging.backup_count`: 1〜20

### 7.4 排他条件チェック

- `schedule.interval` と `schedule.time` は同時指定不可
  - 両方指定された場合はバリデーションエラー
  - エラーメッセージ: "schedule.interval と schedule.time は同時に指定できません"

### 7.5 正規化処理

- `filters.file_types`: 
  - 入力: `.PDF`, `.pdf`, `PDF`, `pdf` など
  - 正規化: 小文字に変換、ドットがない場合は追加
  - 結果: `.pdf`
- `filters.keywords`: 
  - 入力: 文字列の場合は配列に変換（GUIでカンマ区切り入力→配列に分解）
  - 正規化: 前後の空白を削除
- `naming.template`: 
  - 禁止文字（`<>:"/\|?*` と末尾の `.` とスペース）は `_` に置換
  - パス長が260文字を超える場合は切り詰める

### 7.6 パス存在チェック

- `save.local_dir`: ディレクトリが存在しない場合は作成（親ディレクトリも含む）
- `logging.path`: ディレクトリが存在しない場合は作成
- `logging.failures_path`: ディレクトリが存在しない場合は作成

### 7.7 日付範囲チェック

- `filters.date_range.start`: YYYY-MM-DD形式、有効な日付
- `filters.date_range.end`: YYYY-MM-DD形式、有効な日付、start以上
- 未指定の場合はnull（すべての日付を含む）

### 7.8 バリデーションエラーの処理

- バリデーションエラーが発生した場合:
  1. エラーメッセージをログに記録
  2. GUIの場合はエラーダイアログを表示
  3. CLIの場合は標準エラー出力に表示
  4. デフォルト値を使用するか、処理を中断するかは実装時に決定

---

## 8. 実装チェックリスト

### 8.1 設定管理
- [ ] YAML設定ファイルの読み込み実装
- [ ] 設定値のバリデーション実装（必須項目、型、範囲、排他条件）
- [ ] デフォルト値の適用
- [ ] 正規化処理（file_types、keywords、naming.template）
- [ ] パス存在チェック・自動作成
- [ ] 設定ファイルの保存機能（GUI経由）

### 8.2 ログ機能
- [ ] 通常ログ（テキスト形式）の実装
- [ ] 失敗ログ（JSON Lines形式）の実装
  - [ ] 必須フィールド（run_id, url, status_code, error_type, retry_count, timestamp, message, phase, method, elapsed_ms, file_name）
  - [ ] オプションフィールド（content_type, exception_type, stack_trace）
- [ ] ログローテーション機能
- [ ] ログレベルの設定

### 8.3 スクレイピング
- [ ] 検索画面GET実装（VIEWSTATE取得）
- [ ] 検索条件POST実装
- [ ] 検索結果解析実装
- [ ] 詳細表示POST/GET実装（__doPostBack処理）
- [ ] 添付ファイルURL抽出実装（dgrKokoku, dgrKeikaテーブル）

### 8.4 ダウンロード
- [ ] ファイルダウンロード実装（ストリーミング、stream=True）
- [ ] `.part`ファイル処理実装
  - [ ] ダウンロード中は.partで保存
  - [ ] 成功時にリネーム
  - [ ] キャンセル時の処理（keep/delete）
  - [ ] 次回実行時の処理（delete_and_retry/overwrite）
- [ ] リトライ機能実装（指数バックオフ、base_seconds, max_wait_seconds）
- [ ] タイムアウト処理実装（connect, read）
- [ ] 重複回避機能実装（URL、ファイル名+サイズ、ハッシュ）

### 8.5 GUI
- [ ] メインウィンドウ実装（tkinter）
- [ ] 設定ダイアログ実装
- [ ] 進捗表示実装（進捗バー、成功/失敗/スキップ件数）
- [ ] ログ表示実装
- [ ] キャンセル機能実装（threading.Event）
- [ ] スレッド分離実装（メインスレッド/ワーカースレッド、root.after()）

### 8.6 スケジューリング
- [ ] スケジュール実行機能実装
- [ ] アプリ起動中のみ実行（GUI常駐）
- [ ] interval実行（分単位）
- [ ] time実行（HH:MM形式）

---

---

## 9. 状態遷移の詳細（WebForms処理）

### 9.1 検索→詳細→添付の流れ

```
【検索画面GET】
GET Search/Search/Search.aspx?tab=4
→ HTML取得（フォーム、VIEWSTATE、EVENTVALIDATION）

【検索条件POST】
POST Search/Search/Search.aspx?tab=4
Body: __VIEWSTATE, __EVENTVALIDATION, 検索条件
→ 検索結果HTML取得

【検索結果解析】
→ 結果行を抽出（発注機関、工事名、日付等）
→ フィルタ条件適用

【詳細表示POST/GET】
各結果行ごとに:
  - __doPostBack の場合:
    POST Search/Search/Search.aspx?tab=4
    Body: __VIEWSTATE, __EVENTVALIDATION, __EVENTTARGET, __EVENTARGUMENT
  - または直接URL遷移:
    GET List_Detail.aspx?tab=4&...
→ 詳細ページHTML取得

【添付ファイルURL抽出】
→ dgrKokoku テーブルからリンク抽出
→ dgrKeika テーブルからリンク抽出
→ KokaiBunshoServlet などのURL特定

【ファイルダウンロード】
GET ファイルURL
→ .part で保存開始
→ ストリーミングで書き込み
→ 完了後リネーム
```

### 9.2 VIEWSTATE/EVENTVALIDATIONの管理

- **取得**: 検索画面GET時に取得
- **保持**: セッション内で保持（同一セッション内のPOSTで使用）
- **更新**: 各POSTレスポンスから新しい値を取得して更新

### 9.3 __doPostBack処理

- **EVENTTARGET抽出**: `__doPostBack('dgrSearchList','$0')` → `dgrSearchList`
- **EVENTARGUMENT抽出**: `__doPostBack('dgrSearchList','$0')` → `$0`
- **POST送信**: 抽出した値を`__EVENTTARGET`と`__EVENTARGUMENT`として送信

---

**作成日**: 2026年1月7日  
**最終更新日**: 2026年1月7日  
**バージョン**: 1.1（完成版）  
**ステータス**: 実装準備完了

