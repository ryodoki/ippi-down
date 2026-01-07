# 実装タスクリスト（優先度順）

**作成日**: 2026年1月7日  
**ベース**: 要件整合性チェック結果.md

---

## 🔴 最優先（機能要件に直接影響）

### 1. ConfigModelの修正（実装設計書のスキーマとの整合性）
**ファイル**: `src/models/config_model.py`  
**理由**: 他の修正の基盤となるため、最初に実施  
**作業内容**:
- `target_urls`（配列）→ `target.url`（文字列）に変更
- `schedule.interval`（文字列）→ `schedule.interval`（整数: 分単位）に変更
- `logging.file` → `logging.path` に変更
- `logging.failures_path` フィールドを追加
- `download.retry.base_seconds`, `max_wait_seconds` を追加
- `download.part_file.on_cancel`, `on_resume` を追加
- `download.timeout.connect`, `read` を追加

**依存関係**: なし（最初に実施）

---

### 2. HTTPClient: タイムアウト設定の読み込み
**ファイル**: `src/utils/http_client.py`  
**理由**: ネットワークエラー対策の基盤  
**作業内容**:
- 設定から `download.timeout.connect`（デフォルト10秒）を読み込む
- 設定から `download.timeout.read`（デフォルト60秒）を読み込む
- すべてのHTTPリクエスト（GET、POST、download_file）に適用

**依存関係**: ConfigModelの修正完了後

---

### 3. Downloader: .partファイル処理の実装
**ファイル**: `src/core/downloader.py`, `src/utils/http_client.py`  
**理由**: キャンセル機能の前提条件（FR-006-1）  
**作業内容**:
- ダウンロード中は常に `.part` 拡張子で保存
- 成功時に `.part` を削除して正式ファイル名にリネーム
- 設定から `download.part_file.on_cancel` を読み込み、キャンセル時の処理を実装
- 設定から `download.part_file.on_resume` を読み込み、次回実行時の処理を実装

**依存関係**: ConfigModelの修正完了後

---

### 4. Logger: 失敗ログ（JSON Lines形式）の実装
**ファイル**: `src/utils/logger.py`  
**理由**: 失敗時の記録項目要件（FR-005）  
**作業内容**:
- `LoggingConfig`に`failures_path`フィールドを追加（ConfigModel修正と連携）
- JSON Lines形式で失敗ログを出力する機能を実装
- 必須フィールド: `run_id`, `url`, `status_code`, `error_type`, `retry_count`, `timestamp`, `message`, `phase`, `method`, `elapsed_ms`, `file_name`
- オプションフィールド: `content_type`, `exception_type`, `stack_trace`

**依存関係**: ConfigModelの修正完了後

---

## 🟠 高優先度（要件定義に明記）

### 5. Downloader: キャンセル機能の実装
**ファイル**: `src/core/downloader.py`, `src/utils/http_client.py`  
**理由**: ユーザー要件（FR-006-1）  
**作業内容**:
- `threading.Event`によるキャンセルフラグ管理
- ストリーミングダウンロード中にキャンセルフラグをチェック
- キャンセル時は進行中の通信を中断
- `.part`ファイルの処理（設定に従う）

**依存関係**: .partファイル処理の実装完了後

---

### 6. Downloader: 重複判定の改善
**ファイル**: `src/core/downloader.py`  
**理由**: 重複回避要件（FR-008）  
**作業内容**:
- URL同一判定を実装（優先順位1）
- ファイル名+サイズ判定を実装（優先順位2）
- ハッシュ判定（オプション）を実装（優先順位3）
- 現在のファイル存在チェックを改善

**依存関係**: なし（独立して実装可能）

---

### 7. HTTPClient: 429エラー時のRetry-After処理
**ファイル**: `src/utils/http_client.py`  
**理由**: レート制限対応（FR-007）  
**作業内容**:
- 429エラーを検出
- `Retry-After`ヘッダーが存在する場合はその値に従って待機
- `Retry-After`ヘッダーが存在しない場合は指数バックオフを使用（最大60秒）
- リトライ処理に統合

**依存関係**: HTTPClientのリトライ機能実装後

---

### 8. Downloader: 失敗時の記録項目追加
**ファイル**: `src/core/downloader.py`, `src/utils/logger.py`  
**理由**: 失敗時の記録要件（FR-005）  
**作業内容**:
- HTTPステータスコードを記録
- 例外種別（タイムアウト、接続エラー、HTTPエラー等）を記録
- 対象URLを記録
- 再試行回数を記録
- 失敗ログ（JSON Lines形式）に出力

**依存関係**: Loggerの失敗ログ実装完了後

---

### 9. Downloader: 実行結果サマリーの失敗理由別件数
**ファイル**: `src/models/download_result.py`, `src/core/downloader.py`  
**理由**: 実行結果サマリー要件（FR-005）  
**作業内容**:
- `DownloadResult`に失敗理由別カウンターを追加
  - ネットワークエラー（タイムアウト、接続エラー）
  - 429（Too Many Requests）
  - 5xx（サーバーエラー）
  - 4xx（クライアントエラー）
  - その他
- 失敗時に理由を分類してカウント
- ログ出力時に失敗理由別件数を表示

**依存関係**: 失敗時の記録項目追加完了後

---

## 🟡 中優先度（実装設計書に明記）

### 10. ConfigValidator: schedule排他チェック
**ファイル**: `src/config/config_validator.py`  
**理由**: 設定バリデーション仕様（実装設計書 7.4）  
**作業内容**:
- `schedule.interval` と `schedule.time` の同時指定をチェック
- 両方指定された場合はバリデーションエラーを返す
- エラーメッセージ: "schedule.interval と schedule.time は同時に指定できません"

**依存関係**: ConfigModelの修正完了後

---

### 11. ConfigValidator: file_types正規化
**ファイル**: `src/config/config_validator.py`  
**理由**: 設定バリデーション仕様（実装設計書 7.5）  
**作業内容**:
- `filters.file_types`の正規化処理を実装
- 入力: `.PDF`, `.pdf`, `PDF`, `pdf` など
- 正規化: 小文字に変換、ドットがない場合は追加
- 結果: `.pdf`

**依存関係**: ConfigModelの修正完了後

---

### 12. HTTPClient: User-Agent修正
**ファイル**: `src/utils/http_client.py`  
**理由**: 法的・倫理的制約（要件定義書 7.2）  
**作業内容**:
- User-Agentを `ppi-file-downloader/2.1 (+contact: internal)` に変更
- 固定文字列として実装（一貫性のため）

**依存関係**: なし（独立して実装可能）

---

### 13. Downloader: リトライ設定の読み込み
**ファイル**: `src/core/downloader.py`  
**理由**: リトライ要件（FR-007）  
**作業内容**:
- `tenacity`デコレータの固定値を設定から読み込むように変更
- `download.retry.count`（デフォルト3）を読み込む
- `download.retry.base_seconds`（デフォルト1）を読み込む
- `download.retry.max_wait_seconds`（デフォルト60）を読み込む
- 指数バックオフの計算に反映

**依存関係**: ConfigModelの修正完了後

---

## 🔵 確認が必要な項目（実装状況を確認）

### 14. ファイル命名: 禁止文字の置換処理
**ファイル**: `src/core/naming.py`  
**確認内容**: 禁止文字（`<>:"/\|?*` と末尾の `.` とスペース）を `_` に置換する処理があるか

### 15. ファイル命名: パス長制限
**ファイル**: `src/core/naming.py`  
**確認内容**: パス長が260文字を超える場合に切り詰める処理があるか

### 16. スクレイピング: メタデータ抽出
**ファイル**: `src/core/scraper.py`  
**確認内容**: 発注機関名、工事名称、公告日、開札日、契約日などのメタデータを抽出しているか

### 17. GUI: キャンセル機能の実装
**ファイル**: `src/gui/main_window.py`  
**確認内容**: `threading.Event`によるキャンセル、`root.after()`によるGUI更新が実装されているか

---

## 📋 実装順序の推奨

### Phase 1: 基盤整備（最優先）
1. ConfigModelの修正
2. ConfigValidator: schedule排他チェック、file_types正規化
3. HTTPClient: User-Agent修正、タイムアウト設定の読み込み

### Phase 2: コア機能実装（高優先度）
4. Downloader: .partファイル処理
5. Downloader: キャンセル機能
6. Downloader: 重複判定の改善
7. Downloader: リトライ設定の読み込み

### Phase 3: ログ・エラーハンドリング（高優先度）
8. Logger: 失敗ログ（JSON Lines形式）の実装
9. Downloader: 失敗時の記録項目追加
10. Downloader: 実行結果サマリーの失敗理由別件数
11. HTTPClient: 429エラー時のRetry-After処理

### Phase 4: 確認・改善（中優先度）
12. ファイル命名: 禁止文字置換、パス長制限の確認・実装
13. スクレイピング: メタデータ抽出の確認・改善
14. GUI: キャンセル機能の確認・改善

---

## 📝 各タスクの見積もり

- **ConfigModelの修正**: 2-3時間
- **HTTPClient修正**: 3-4時間
- **Downloader修正**: 6-8時間
- **Logger修正**: 3-4時間
- **ConfigValidator修正**: 1-2時間
- **確認作業**: 2-3時間

**合計見積もり**: 約17-24時間

---

**最終更新**: 2026年1月7日

