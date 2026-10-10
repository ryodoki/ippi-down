# ppi-file-downloader 実装設計書

## 1. 概要

本ドキュメントは、ppi-file-downloaderの実装に必要な詳細設計を記述する。
要件定義書で定義された機能要件・非機能要件を実現するための技術的な設計方針を示す。

**関連文書**: [要件定義書](requirements.md)、[ダウンロードフォルダー仕様](download_folder_spec.md)

保存パス、命名、履歴およびlayout版の外部仕様はダウンロードフォルダー仕様を正本とし、本書では実装上の責務だけを扱う。

現行実装では`SearchTarget`と不変の`SearchProfile`により、工事・入札の経過（`koji_keika` / `tab=4`）と業務・入札の経過（`gyomu_keika` / `tab=7`）を分離する。対象固有のWebForms項目だけをプロファイル化し、発注機関の名称・コード・件数・順序は定数化しない。候補は対象別Sessionで起動時または初回利用時に取得し、手動更新の全体解析成功時だけ新世代へ全置換する。削除された保存値と更新失敗はそれぞれ`AGENCY_SELECTION_REMOVED`、`AGENCY_CATALOG_REFRESH_FAILED`として実行前に停止する。

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
                          # 注: i-ppi.jpの検索条件として「公告日」基準で適用
    end: string | null    # オプション: 終了日（YYYY-MM-DD形式、両端含む）
                          # 例: "2025-12-31"
                          # 注: 未指定の場合は今日まで

# ダウンロードデータルートと保存構成
save_paths:
  local: string  # 必須: 通常実行と定期実行をまとめるデータルート
                 # 例: "./downloads"
  layout_version: integer  # 新規設定は4。明示済みv3は維持、キーがない旧設定は2
  normal_folder: string  # 既定: "01_通常ダウンロード"
  scheduled_folder: string  # 既定: "02_定期実行"
  schedule_storage_key: string  # 定期設定だけ。S001形式の不変キー
  schedule_storage_folder: string  # 定期設定だけ。キーと初回名称から生成

# ファイル命名規則
naming_rule: string  # 必須。既定: "{document_name}_{document_updated_at}"
                    # 詳細な変数と安全化規則は正本仕様を参照

# ダウンロード設定
download:
  retry:
    count: integer  # オプション: リトライ回数（デフォルト: 3）
    base_seconds: integer  # オプション: 指数バックオフの初期待機時間（秒、デフォルト: 1）
    max_wait_seconds: integer  # オプション: 指数バックオフの最大待機時間（秒、デフォルト: 60）
  timeout:
    connect: integer  # オプション: 接続タイムアウト（秒、デフォルト: 10）
    read: integer  # オプション: 読み込みタイムアウト（秒、デフォルト: 60）

# 旧単一定期実行との互換設定
schedule:
  enabled: boolean  # オプション: スケジュール実行を有効化（デフォルト: false）
  backend: "windows_task_scheduler"
  timezone: "Asia/Tokyo"
  interval: string  # daily, weekly, monthly
  time: string  # HH:MM形式
  weekday: string  # weekly時、monday～sunday
  day_of_month: integer  # monthly時、1～28
  start_when_available: boolean  # 実行漏れを次回利用可能時に1回補完
  wake_to_run: boolean
  retry_count: integer  # 一時障害のジョブ再試行回数
  retry_interval_minutes: integer
  notification_policy: string  # off / important_only / all_results / failures_only
  active_profile_id: string | null  # 新しい複数設定の正本には使用しない

# config/schedule-registration.json schema v2
schedule_registry:
  schema_version: 2
  revision: integer
  registrations:
    <schedule_id>:
      name: string
      enabled: boolean
      task_name: string
      snapshot_id: string
      snapshot_path: string
      snapshot_fingerprint: string
      storage_key: string  # S001形式の不変保存キー
      storage_folder: string  # 表示名変更でも変えない固定保存フォルダ
      created_at: datetime
      updated_at: datetime

# config/schedule-instance-id
task_namespace_id: string  # 配置単位。Windowsタスク名の所有namespace

# config/install-location.json
installation_location:
  schema_version: 1
  task_namespace_id: string  # schedule-instance-idとの一致を検証
  app_root: absolute path  # 最後に利用者が確認した配置場所
  status: active | retired
  moved_to: optional absolute path  # retired時の現在配置
  updated_at: datetime

# config/installation-relocation-journal.json（移行中だけ存在）
installation_relocation_journal:
  schema_version: 1
  task_namespace_id: string
  old_root: absolute path
  current_root: absolute path
  started_at: datetime

# %LOCALAPPDATA%/ippi-down/install-id
coordination_id: string  # ユーザー単位。FIFOとプロセス間排他専用

# 不変スナップショット schema v3
schedule_snapshot:
  schedule_id: string
  snapshot_id: string
  display_name: string
  fingerprint: string  # 検索・文書・命名・保存・予定・再試行・通知条件
  save_paths: mapping  # schedule_storage_key/folderを含めて封印

# schema v1/v2は旧projectionでfingerprintを検証し、通知方針をoffとして読む

# ログ設定
logging:
  level: string  # オプション: ログレベル（デフォルト: "INFO"）
                 # 有効値: "DEBUG", "INFO", "WARNING", "ERROR"
  path: string  # オプション: 通常ログファイルパス（デフォルト: "./logs/app.log"）
  failures_path: string  # オプション: 失敗ログファイルパス（JSON Lines形式、デフォルト: "./logs/failures.jsonl"）
  max_bytes: integer  # オプション: 最大ファイルサイズ（バイト、デフォルト: 10485760 = 10MB）
  backup_count: integer  # オプション: ローテーション世代数（デフォルト: 5）
```

有効な定期実行は1設定につき1つの
`\ippi-down\Download-<task-namespace-id>-<schedule-id>`へ登録する。task namespace
IDは`config/schedule-instance-id`へ配置単位で保持する。既存台帳では、登録済み
`task_name`から従来IDを検証して継承し、タスク名を変更しない。フォルダー一式の
移動は`config/install-location.json`の確認済み位置との差として検出し、利用者の
確認後に同じ配置として扱う。旧配置が存在しても、台帳のcommand、snapshot、引数、
作業フォルダーを現在配置から導いた期待値と比較して旧パスを正常扱いしない。旧配置
内の保存先・ログだけを現在配置基準の相対パスへ変換し、外部保存先は維持する。
封印済みsnapshotは直接編集せず新規作成し、失敗時は設定、台帳、Windowsタスクを
rollbackする。変更開始前に配置移行journalを原子的に作成し、強制終了後は非GUI実行を
停止して、次回GUI確認時に同じ旧・新ルートで残処理を再開する。commit後にだけjournalを
削除する。exe単体コピー先に管理ファイルがなければ新しい配置としてIDを発行
する。タスクの引数は
`--scheduled-run --schedule-id <id> --config <snapshot-path>`とし、IDまたは
fingerprintが一致しないスナップショットは実行しない。異なる設定が同時に開始
された場合は、ユーザー単位のcoordination IDを使う
`%LOCALAPPDATA%\ippi-down\run-queue\<coordination-id>`の秘密情報を含まないticketを
プロセス間mutexで更新し、全配置を通してFIFOで1件ずつ処理する。coordination IDは
別配置のタスクを発見するためにも使用できるが、タスクの所有権判定には使用しない。
キュー待機上限は2時間、実処理上限は2時間、Windowsタスク全体の上限は4時間とする。

別配置の設定は自動で取り込まない。GUIから移行元`config`を明示選択し、台帳、
封印済みスナップショット、ID、保存先、タスク定義を読み取り専用で検証したうえで
previewを返す。選択した設定を現在の台帳へ一時無効で作成し、旧タスクを無効化した
後に移行元の有効／無効状態を引き継ぐ。previewは設定名、有効状態、実行予定、
実効保存先、可否、Windowsタスク名、診断を表示する。同名設定は「要改名」とし、
移行先名称を1～80文字で明示入力させて名称一意制約を再検証する。
移行元が有効なら現在のexeをactionとする
移行先を有効化し、移行元が無効なら移行先も無効のままとする。その後、移行元を
`MIGRATED_OUT`として記録し、旧タスクを削除する。削除失敗時は旧タスクの無効状態を
維持し、`EXTERNAL_TASK_CLEANUP_PENDING`を後処理警告として返す。同じ`schedule_id`の
旧実行履歴は現在のledgerへ重複なく統合する。履歴統合の失敗は
`EXTERNAL_HISTORY_IMPORT_FAILED`としてownership移行の成功と分離する。
台帳または検証可能なスナップショットがない純粋な孤立タスクはimport対象にせず、
確認付き解除だけを許可する。元の取得済み文書と履歴は移動、改名、削除しない。

外部設定の読取・preview・移行・解除は`preview_external_imports()`、
`list_external_schedule_candidates()`、`inspect_external_schedule()`、
`plan_external_import()`、`import_external_schedule()`、`remove_external_task()`を通して
行う。複数選択時は`import_external_schedules()`を使用し、GUIから台帳やWindowsタスクを
直接変更しない。`ScheduleMigrationResult`は成功状態、理由コード、警告、rollback有無、
履歴統合件数を返す。

履歴JSONLは全件を読み込まず、ダウンロード履歴は今回必要なキーだけ、定期実行履歴は末尾の必要件数だけをストリーム処理する。GUIイベントは差分進捗と上限付きキューを使用し、通常ログ表示を5,000行または2 MiB、定期実行の詳細ログを200件または2 MiBに制限する。表示から除いた過去ログはファイルに残す。原子的書込みの`.tmp`、Edge変換用一時root、保留スナップショットは、作成日時・所有状態・実行mutex／FIFO ticketを確認して安全な場合だけ回収する。詳細な運用上限は[メモリ・一時資源の運用仕様](memory_resource_management.md)を正本とする。

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

save_paths:
  local: "./downloads"
  layout_version: 4
  normal_folder: "01_通常ダウンロード"
  scheduled_folder: "02_定期実行"
  schedule_storage_key: ""
  schedule_storage_folder: ""

naming_rule: "{document_name}_{document_updated_at}"

download:
  retry:
    count: 3
    base_seconds: 1
    max_wait_seconds: 60
  timeout:
    connect: 10
    read: 60

schedule:
  enabled: false
  backend: "windows_task_scheduler"
  timezone: "Asia/Tokyo"
  interval: "daily"
  time: "09:00"
  weekday: "monday"
  day_of_month: 1
  start_when_available: true
  wake_to_run: false
  retry_count: 2
  retry_interval_minutes: 15
  notification_policy: off

logging:
  level: "INFO"
  path: "./logs/app.log"
  failures_path: "./logs/failures.jsonl"
  max_bytes: 10485760
  backup_count: 5
```

### 2.3 保存レイアウトv4

完全なパス文法、変換順、安全化、履歴、v2互換は[ダウンロードフォルダー仕様](download_folder_spec.md)に従う。

実装上は`resolve_run_root`が`SearchTarget`、`RunKind.MANUAL`、`RunKind.SCHEDULED`から検索対象別の実行ルートを決定し、`Naming.generate_folder_parts`が`AgencyPath`、案件名、文書区分を相対パス要素へ変換する。`FileUtils.build_safe_download_path_parts`は各要素の安全化、ルート内包含、絶対パス240文字以内への安定ハッシュ短縮を担当する。`Downloader`は実行ルート直下の履歴と完成ファイルと同じフォルダーの`.part`を管理する。

設定検証はlayout版を`2`、`3`、`4`に限定する。v3/v4では通常・定期のフォルダー名を個別に検証し、安全化後の値をWindowsの大文字小文字非依存で比較して同一になる設定を拒否する。v4の検索対象フォルダーは固定マップから取得する。定期実行で固定保存キーまたは固定保存フォルダーが欠ける場合は通常側へフォールバックせずエラーとする。

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
        │ 実行結果サマリー  │  │ 処理中.part削除    │
        │ ログ出力         │  │ 既存ファイル保持   │
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
                # 処理中の.partだけを削除し、既存の正式ファイルは保持
                remove_part_file(path + '.part')
                return
            f.write(chunk)
    # 内容検証後、同じ保存先内で原子的に置換
    os.replace(path + '.part', path)
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

### 5.5 設定画面と定期実行操作の配置

`fit_to_screen`はWindowsの作業領域を取得して初期寸法と最小寸法を収める。設定画面の定期実行タブは操作ボタンを上部へ固定し、幅に応じて`WrapButtonBar`で折り返す。本文は縦スクロール領域とし、登録内容は高さを制限したテキスト欄、履歴は縦・横スクロール付きの表へ表示する。保存・キャンセルはタブの外のフッターに置く。メイン画面でもツールバーと定期実行の操作列を折り返す。

管理対象の定期実行に対する複製・編集・削除・有効化／無効化は、実行中・FIFO順番待ち・再試行待機中でもバックエンドの操作可否に従って有効にする。編集・削除・無効化は、既に開始または受付済みの実行が旧スナップショットで継続することを確認画面で示す。登録更新時は新しい不変スナップショットに切り替え、キューや実行中タスクが参照する旧スナップショットは後で安全に回収する。「今すぐ実行」は実行中・順番待ちの間は無効にする。管理外のタスクは通常の編集対象へ含めない。

定期実行の追加・編集などは操作ごとに登録台帳へ保存する。設定画面フッターの保存は一般設定を保存し、キャンセルは未保存の一般設定を破棄する。既に完了した定期実行の操作はキャンセルで巻き戻さない。

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
│   ├── service.py             # 登録・更新・削除・状態照会
│   ├── task_scheduler.py      # schtasks.exe / Task Scheduler XML
│   ├── profile.py             # 不変の検索条件スナップショット
│   └── ledger.py              # schedule-runs.jsonl
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
- scheduleの方式、時刻、曜日／日、再試行範囲チェック

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
- 履歴キーとサイズ、SHA-256、形式、更新日時による再利用判定
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
- 自配置の保存条件と管理外の旧Windowsタスクを別枠で表示
- 旧`config`選択、候補preview、1件import、外部タスクの確認付き解除を非同期実行
- 実行中・順番待ちの管理対象の編集可否と、新旧スナップショットの継続確認を表示

#### logging/logger.py
- 通常ログ（テキスト形式）
- 失敗ログ（JSON Lines形式）
- ログローテーション

#### scheduler/service.py / task_scheduler.py
- Windowsタスクの登録、更新、削除、照会、今すぐ実行
- daily／weekly／monthlyのCalendarTrigger XML生成
- 実行ファイル、Python、スナップショット、定義差分の診断
- 自配置の管理対象と別配置のタスクを分離した照会
- 旧配置の検証、preview、選択importと孤立タスクの確認付き解除
- 実行中の外部タスクに対する解除拒否と、操作可否のGUI向け公開
- 登録失敗時の旧タスク・メタデータ・プロファイル保護

#### utils/scheduled_notifier.py
- `ScheduleNotificationPolicy`に従い最終`ScheduledRunRecord`の通知要否を判定
- `ScheduledRunNotifier.notify(record, policy)`は履歴確定後の1箇所から呼び出す
- `NotificationDeliveryResult`で送信状態、`NOTIFICATION_*`理由コード、処理時間を返す
- Windows標準`Shell_NotifyIconW`を使用し、非表示windowとiconを最大10秒で必ず解放
- 通知失敗をダウンロード結果・終了コードから分離し、常駐processを作らない

---

## 7. 設定バリデーション仕様

### 7.1 必須項目チェック

- `target.url`: 必須、文字列、URL形式
- `filters.file_types`: 必須、配列（空配列可）
- `save_paths.local`: 必須、文字列、データルートのパス形式
- `save_paths.layout_version`: 整数。新規設定は4
- `save_paths.normal_folder`: v3/v4では空でない文字列
- `save_paths.scheduled_folder`: v3/v4では空でない文字列
- `naming_rule`: 必須、文字列

### 7.2 型チェック

- `filters.file_types`: 配列[string]
- `filters.keywords`: 配列[string]（文字列は不可）
- `filters.date_range.start/end`: 文字列（YYYY-MM-DD形式）またはnull
- `download.retry.count`: 整数（1以上）
- `download.retry.base_seconds`: 整数（1以上）
- `download.retry.max_wait_seconds`: 整数（base_seconds以上）
- `download.timeout.connect/read`: 整数（1以上）
- `schedule.interval`: `daily`、`weekly`、`monthly`のいずれか
- `schedule.time`: 文字列（HH:MM形式）
- `schedule.weekday`: monday～sunday
- `schedule.day_of_month`: 整数（1～28）
- `schedule.retry_count`: 整数（0～10）
- `schedule.retry_interval_minutes`: 整数（1～1440）
- `schedule.notification_policy`: `off`、`important_only`、`all_results`、`failures_only`
- `save_paths.layout_version`: 整数（`2`、`3`、`4`）
- `logging.level`: 文字列（"DEBUG", "INFO", "WARNING", "ERROR"のいずれか）

### 7.3 値の範囲チェック

- `download.retry.count`: 1〜10
- `download.retry.base_seconds`: 1〜60
- `download.retry.max_wait_seconds`: base_seconds以上、最大300
- `download.timeout.connect`: 1〜300
- `download.timeout.read`: 1〜600
- `schedule.day_of_month`: 1～28
- `schedule.retry_count`: 0～10
- `schedule.retry_interval_minutes`: 1～1440
- `logging.max_bytes`: 1024以上（1KB以上）
- `logging.backup_count`: 1〜20

### 7.4 スケジュール条件チェック

- weeklyでは有効な曜日、monthlyでは1～28日を必須とする
- `custom`および旧プロセス内設定は自動登録せず、明示移行を求める
- タイムゾーンは`Asia/Tokyo`に固定する

### 7.5 正規化処理

- `filters.file_types`: 
  - 入力: `.PDF`, `.pdf`, `PDF`, `pdf` など
  - 正規化: 小文字に変換、ドットがない場合は追加
  - 結果: `.pdf`
- `filters.keywords`: 
  - 入力: 文字列の場合は配列に変換（GUIでカンマ区切り入力→配列に分解）
  - 正規化: 前後の空白を削除
- `naming_rule`:
  - 構文と未知のプレースホルダーを設定保存時に検証する
  - 禁止文字、予約名、長いパスの変換は正本仕様に従う

### 7.6 パス存在チェック

- `save_paths.local`: データルートが存在しない場合は作成（親ディレクトリも含む）
- v3/v4の`normal_folder`と`scheduled_folder`は、安全化後かつWindowsの大文字小文字非依存比較でも異なること
- v3/v4の定期実行では`schedule_storage_key`と`schedule_storage_folder`を両方必須とし、一方だけの状態を許可しない
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
- [ ] 正規化処理（file_types、keywords、naming_rule）
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
  - [ ] 失敗・キャンセル時は処理中の.partだけを削除
  - [ ] 既存の正常ファイルは保持
- [ ] リトライ機能実装（指数バックオフ、base_seconds, max_wait_seconds）
- [ ] タイムアウト処理実装（connect, read）
- [ ] 履歴キー、SHA-256、サイズ、形式、更新日時による保存済みファイル再利用

### 8.5 GUI
- [ ] メインウィンドウ実装（tkinter）
- [ ] 設定ダイアログ実装
- [ ] 進捗表示実装（進捗バー、成功/失敗/スキップ件数）
- [ ] ログ表示実装
- [ ] キャンセル機能実装（threading.Event）
- [ ] スレッド分離実装（メインスレッド/ワーカースレッド、root.after()）

### 8.6 スケジューリング
- [x] WindowsタスクによるGUI非依存の実行
- [x] daily／weekly／monthly CalendarTrigger
- [x] 不変の検索条件スナップショット
- [x] プロセス間mutex、終了コード、実行履歴
- [x] GUIでの登録状態・履歴・修復案内

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
**最終更新日**: 2026年8月5日
**バージョン**: 1.2（実装準拠版）
**ステータス**: 現行
