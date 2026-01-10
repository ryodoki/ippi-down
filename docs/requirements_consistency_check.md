# 要件定義書との整合性チェック結果

**確認日**: 2026年1月7日  
**確認対象**: 要件定義書_レビュー版.md、実装設計書.md

---

## 1. 重大な不足・不整合

### 1.1 HTTPClient (`src/utils/http_client.py`)

#### ❌ タイムアウト設定が固定値
- **現状**: `timeout=30`（GET/POST）、`timeout=60`（download_file）が固定
- **要件**: `download.timeout.connect`（デフォルト10秒）、`download.timeout.read`（デフォルト60秒）を設定から読み込む必要がある（NFR-005）
- **修正必要**: ✅

#### ❌ User-Agentが要件と異なる
- **現状**: `"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"`
- **要件**: `ppi-file-downloader/2.1 (+contact: internal)` のような固定文字列（7.2 法的・倫理的制約）
- **修正必要**: ✅

#### ❌ 429エラー時のRetry-Afterヘッダー処理がない
- **現状**: 429エラー時の特別な処理なし
- **要件**: `Retry-After`ヘッダーが存在する場合はその値に従って待機、なければ指数バックオフ（最大60秒）（FR-007）
- **修正必要**: ✅

#### ❌ リトライ機能がHTTPClientにない
- **現状**: `downloader.py`の`tenacity`デコレータに依存
- **要件**: HTTPClientレベルでリトライ処理が必要（設定可能な回数、指数バックオフ）
- **修正必要**: ✅

---

### 1.2 Logger (`src/utils/logger.py`)

#### ❌ 失敗ログ（JSON Lines形式）の出力機能がない
- **現状**: 通常ログ（テキスト形式）のみ
- **要件**: 失敗ログをJSON Lines形式で`failures_path`に出力（FR-005、実装設計書 3.2）
- **必須フィールド**: `run_id`, `url`, `status_code`, `error_type`, `retry_count`, `timestamp`, `message`, `phase`, `method`, `elapsed_ms`, `file_name`
- **修正必要**: ✅

#### ❌ `failures_path`設定に対応していない
- **現状**: `LoggingConfig`に`failures_path`フィールドがない
- **要件**: `logging.failures_path`（デフォルト: `./logs/failures.jsonl`）を設定可能に（実装設計書 2.1）
- **修正必要**: ✅

---

### 1.3 Downloader (`src/core/downloader.py`)

#### ❌ .partファイルの処理がない
- **現状**: 直接ファイル名で保存
- **要件**: ダウンロード中は常に`.part`拡張子で保存し、成功時にリネーム（FR-006-1）
- **修正必要**: ✅

#### ❌ キャンセル機能がない
- **現状**: キャンセル処理なし
- **要件**: `threading.Event`によるキャンセル機能、進行中の通信を中断（FR-006-1）
- **修正必要**: ✅

#### ❌ 重複判定がファイル存在のみ
- **現状**: `check_duplicate`はファイル存在のみチェック
- **要件**: 優先順位順に
  1. URL同一判定
  2. ファイル名+サイズ判定
  3. ハッシュ判定（オプション）
  （FR-008）
- **修正必要**: ✅

#### ❌ 失敗時の記録項目が不足
- **現状**: エラーメッセージのみ
- **要件**: HTTPステータス、例外種別、対象URL、再試行回数を記録（FR-005）
- **修正必要**: ✅

#### ❌ 実行結果サマリーの失敗理由別件数がない
- **現状**: 成功/失敗/スキップ件数のみ
- **要件**: 失敗理由別件数（ネットワーク/429/5xx/4xx/その他）を出力（FR-005）
- **修正必要**: ✅

#### ❌ リトライ設定が固定値
- **現状**: `tenacity`デコレータで固定（3回、1秒〜10秒）
- **要件**: `download.retry.count`（デフォルト3）、`base_seconds`（デフォルト1）、`max_wait_seconds`（デフォルト60）を設定から読み込む（FR-007、実装設計書 2.1）
- **修正必要**: ✅

---

### 1.4 ConfigValidator (`src/config/config_validator.py`)

#### ❌ schedule.interval と schedule.time の排他チェックがない
- **現状**: 排他チェックなし
- **要件**: 両方指定された場合はエラー（実装設計書 7.4）
- **修正必要**: ✅

#### ❌ file_typesの正規化チェックがない
- **現状**: 正規化処理なし
- **要件**: 小文字・ドット付きに正規化（実装設計書 7.5）
- **修正必要**: ✅

---

### 1.5 ConfigModel (`src/models/config_model.py`)

#### ⚠️ 実装設計書のスキーマと不一致
- **現状**: 
  - `target_urls`（配列）→ 要件では `target.url`（文字列）
  - `schedule.interval`（文字列: "daily", "weekly"等）→ 要件では `schedule.interval`（整数: 分単位）
  - `logging.file` → 要件では `logging.path`
  - `logging.failures_path` がない
  - `download.retry.base_seconds`, `max_wait_seconds` がない
  - `download.part_file.on_cancel`, `on_resume` がない
- **修正必要**: ✅

---

## 2. 中程度の不足・改善点

### 2.1 ファイル命名 (`src/core/naming.py`)

#### ⚠️ 禁止文字の置換処理
- **要件**: 禁止文字（`<>:"/\|?*` と末尾の `.` とスペース）は `_` に置換（実装設計書 2.1）
- **確認必要**: 実装状況を確認

#### ⚠️ パス長制限
- **要件**: パス長が260文字を超える場合は切り詰める（実装設計書 2.1）
- **確認必要**: 実装状況を確認

---

### 2.2 スクレイピング (`src/core/scraper.py`)

#### ⚠️ メタデータ抽出
- **要件**: 発注機関名、工事名称、公告日、開札日、契約日などのメタデータを抽出（FR-003）
- **確認必要**: 実装状況を確認

---

## 3. 軽微な改善点

### 3.1 GUI (`src/gui/main_window.py`)

#### ⚠️ キャンセル機能の実装
- **要件**: `threading.Event`によるキャンセル、`root.after()`によるGUI更新（実装設計書 5.2）
- **確認必要**: 実装状況を確認

---

## 4. 修正優先度

### 最優先（機能要件に直接影響）
1. ✅ **HTTPClient**: タイムアウト設定の読み込み
2. ✅ **Downloader**: .partファイル処理
3. ✅ **Logger**: 失敗ログ（JSON Lines形式）の実装
4. ✅ **ConfigModel**: 実装設計書のスキーマとの整合性

### 高優先度（要件定義に明記）
5. ✅ **Downloader**: キャンセル機能
6. ✅ **Downloader**: 重複判定の改善（URL、ファイル名+サイズ、ハッシュ）
7. ✅ **HTTPClient**: 429エラー時のRetry-After処理
8. ✅ **Downloader**: 失敗時の記録項目追加
9. ✅ **Downloader**: 実行結果サマリーの失敗理由別件数

### 中優先度（実装設計書に明記）
10. ✅ **ConfigValidator**: schedule排他チェック
11. ✅ **ConfigValidator**: file_types正規化
12. ✅ **HTTPClient**: User-Agent修正
13. ✅ **Downloader**: リトライ設定の読み込み

---

## 5. 確認が必要なファイル

以下のファイルの実装状況を確認する必要があります：

- `src/core/naming.py` - 禁止文字置換、パス長制限
- `src/core/scraper.py` - メタデータ抽出
- `src/gui/main_window.py` - キャンセル機能、スレッド分離

---

**結論**: 要件定義書と実装設計書に基づき、**13項目の修正が必要**です。特にHTTPClient、Logger、Downloader、ConfigModelの修正が最優先です。

