# 要件定義 vs 実装 乖離分析レポート

作成日: 2026-01-XX  
対象: ippi-down リポジトリ  
解析対象: `docs/requirements.md`, `docs/settings_requirements.md`, `src/` 配下の実装コード

## 1. 要件一覧テーブル

| 要件ID | 要件名 | ステータス | 根拠（ファイル:行/関数） | メモ |
|--------|--------|-----------|------------------------|------|
| **FR-001** | HTML構造解析機能 | ✅ Implemented | `src/core/scraper.py:75-84` `fetch_page()` | BeautifulSoupを使用して実装 |
| **FR-002** | ファイルリンク検出機能 | ✅ Implemented | `src/core/scraper.py:628-673` `_extract_files_from_tables()`, `src/core/downloader.py:56-133` `_download_postback_file()` | PostBackリンク対応完了 |
| **FR-003** | メタデータ抽出機能 | ✅ Implemented | `src/core/scraper.py:479-583` `extract_metadata()` | 発注機関、工事名、日付などを抽出 |
| **FR-004** | 条件指定機能 | ✅ Implemented | `src/models/config_model.py:10-85` `SearchConditions` | GUI/設定ファイルで設定可能 |
| **FR-005** | 自動ダウンロード機能 | ⚠️ Partial | `src/core/downloader.py:203-299` `download_files()` | **乖離**: 失敗理由別サマリーが未実装 |
| **FR-006** | 進捗表示機能 | ✅ Implemented | `src/gui/main_window.py` 進捗バー表示 | GUIで実装 |
| **FR-006-1** | キャンセル機能 | ✅ Implemented | `src/core/downloader.py:86-97` キャンセルチェック | `.part`ファイルの扱いは実装済み |
| **FR-007** | リトライ機能 | ✅ Implemented | `src/core/downloader.py:54-61` `@retry`デコレータ, `src/utils/http_client.py:47-133` | 指数バックオフ実装済み、429対応実装済み |
| **FR-008** | 重複回避機能 | ⚠️ Partial | `src/core/downloader.py:330-393` `check_duplicate()` | **乖離**: URL同一判定・ファイル名+サイズ判定が未実装。ファイル存在チェックのみ |
| **FR-009** | ファイル名自動生成 | ✅ Implemented | `src/core/naming.py:29-79` `generate_filename()` | テンプレート文字列を使用 |
| **FR-010** | 命名規則カスタマイズ | ✅ Implemented | `src/models/config_model.py:159` `naming_rule: str` | `Naming`クラスでテンプレート文字列を使用 |
| **FR-011** | ファイル名重複回避 | ✅ Implemented | `src/core/downloader.py:111` `ensure_unique()` | 連番を付与して重複回避 |
| **FR-012** | 保存先指定機能 | ✅ Implemented | `src/models/config_model.py:98-101` `SavePaths` | GUI/設定ファイルで設定可能 |
| **FR-013** | フォルダ構造自動生成 | ✅ Implemented | `src/core/naming.py:117-164` `generate_folder_name()` | メタデータに基づいてサブフォルダ作成 |
| **FR-016** | スケジューリング機能 | ⚠️ Partial | `src/scheduler/scheduler.py:54-105` `_setup_schedule()` | **乖離**: custom cronは実装済みだが、GUIから設定できない可能性 |
| **FR-017** | 実行ログ記録 | ✅ Implemented | `src/utils/logger.py` | ログファイルに記録 |
| **FR-018** | 実行結果通知 | ✅ Implemented | `src/utils/notifier.py` | GUI/ログファイルで通知 |
| **FR-019** | 設定ファイル保存/読み込み | ✅ Implemented | `src/config/config_manager.py` | YAML形式で実装 |
| **FR-020** | 設定プロファイル管理 | ❌ Not Implemented | - | 要件定義では「将来拡張」とされているが、実装なし |
| **FR-021** | ログ記録機能 | ✅ Implemented | `src/utils/logger.py` | ログレベル、ローテーション実装済み |
| **FR-021-1** | ログ保存先設定 | ✅ Implemented | `src/models/config_model.py:141-144` `LoggingConfig` | 設定ファイルで変更可能 |
| **FR-021-2** | ログローテーション | ✅ Implemented | `src/utils/logger.py` `RotatingFileHandler` | サイズベースローテーション実装 |
| **FR-022** | エラーログ記録 | ✅ Implemented | `src/utils/logger.py` | スタックトレース含む詳細情報を記録 |
| **FR-023** | ログレベル設定 | ✅ Implemented | `src/models/config_model.py:141` `level: str` | DEBUG/INFO/WARNING/ERROR対応 |
| **FR-024** | CLI提供 | ✅ Implemented | `src/cli/main.py` | `--config`, `--once`, `--dry-run` 等をサポート（開発・デバッグ用） |
| **FR-025** | GUI提供 | ✅ Implemented | `src/gui/main_window.py` | tkinterで実装 |
| **FR-026** | 実行ファイル形式 | ✅ Implemented | `scripts/build/build.spec` PyInstaller設定 | Windows 10/11対応 |
| **FR-SET-001** | 設定ダイアログ表示 | ✅ Implemented | `src/gui/settings_dialog.py:23-58` | 実装済み |
| **FR-SET-002** | 設定項目表示 | ⚠️ Partial | `src/gui/settings_dialog.py:89-925` | **乖離**: custom cron設定がGUIにない可能性 |
| **FR-SET-003** | 設定値検証 | ✅ Implemented | `src/config/config_validator.py` | 実装済み |
| **FR-SET-004** | 設定保存 | ✅ Implemented | `src/gui/settings_dialog.py:837-970` | 実装済み |
| **FR-SET-005** | 設定読み込み | ✅ Implemented | `src/gui/settings_dialog.py:746-835` | 実装済み |
| **FR-SET-006** | 設定キャンセル | ✅ Implemented | `src/gui/settings_dialog.py:972-975` | 実装済み |
| **FR-SET-007** | 設定リセット | ✅ Implemented | `src/gui/settings_dialog.py:976-978` `on_reset()` | 実装済み（デフォルト設定を取得してUIに反映） |
| **FR-SET-008** | 設定プロファイル管理 | ❌ Not Implemented | - | 要件定義では「中優先度」だが未実装 |
| **FR-SET-009** | 設定インポート/エクスポート | ❌ Not Implemented | - | 要件定義では「低優先度」で未実装 |
| **FR-SET-010** | 設定プレビュー | ❌ Not Implemented | - | 要件定義では「低優先度」で未実装 |

## 2. 乖離一覧（優先度順）

### P0（緊急・必須修正）

#### 1. FR-005: 失敗理由別サマリー未実装

**乖離内容:**
- 要件: 「実行結果サマリー: 失敗理由別件数を出力すること（ネットワークエラー、429、5xx、4xx、その他）」
- 現状: `DownloadResult` には `total`, `success`, `failed`, `skipped` のみ。失敗理由別の集計がない

**現状実装:**
- `src/models/download_result.py:10-41` - 失敗理由別の集計フィールドがない
- `src/core/downloader.py:203-299` - 失敗理由を分類していない

**影響:**
- 運用で失敗原因を把握できない
- 429エラーやネットワークエラーの発生頻度が分からない
- 問題の特定が困難

**修正方針:**
- `DownloadResult` に失敗理由別の集計フィールドを追加
- `DownloadTask` に `error_type` フィールドを追加
- `downloader.py` で失敗理由を分類して記録

**実装ステップ:**
1. `DownloadTask` に `error_type` フィールドを追加（`network_error`, `http_429`, `http_5xx`, `http_4xx`, `other`）
2. `DownloadResult` に失敗理由別の集計フィールドを追加
3. `downloader.py` で失敗理由を分類して `error_type` を設定
4. サマリー出力時に失敗理由別件数を表示

**テスト方針:**
- 各種エラーを模擬して、正しく分類されることを確認
- サマリー出力が正しいことを確認

**受け入れ確認:**
```powershell
# テスト実行
pytest tests/test_downloader.py::test_error_categorization -v

# 実際のダウンロード実行でサマリーを確認
python src\main.py
# ログで失敗理由別件数が表示されることを確認
```

#### 2. FR-008: 重複回避の実装不足

**乖離内容:**
- 要件: 「重複判定方法（優先順位順）: 1. URL同一判定、2. ファイル名+サイズ判定、3. ハッシュ判定（オプション）」
- 現状: ファイル存在チェックのみ。URL同一判定・ファイル名+サイズ判定が未実装

**現状実装:**
- `src/core/downloader.py:330-393` `check_duplicate()` - ファイル存在チェックのみ

**影響:**
- 同一URLのファイルを再ダウンロードしてしまう
- 同名+同サイズのファイルを検出できない
- ディスク容量の無駄

**修正方針:**
- ダウンロード履歴を記録（JSONL形式、`logs/download_history.jsonl`）
- URL同一判定を実装
- ファイル名+サイズ判定を実装
- ハッシュ判定はオプション（設定で有効化）

**実装ステップ:**
1. `src/core/download_history.py` を新規作成（ダウンロード履歴管理クラス）
2. `Downloader` に `history` フィールドを追加
3. `check_duplicate()` を拡張してURL同一判定・ファイル名+サイズ判定を実装
4. ダウンロード成功時に履歴を記録

**テスト方針:**
- 同一URLのファイルを2回ダウンロードして、2回目がスキップされることを確認
- 同名+同サイズのファイルを2回ダウンロードして、2回目がスキップされることを確認

**受け入れ確認:**
```powershell
# テスト実行
pytest tests/test_downloader.py::test_duplicate_detection -v

# 実際のダウンロード実行で重複回避を確認
python src\main.py
# 2回目実行時にスキップされることを確認
```

#### 3. FR-024: CLI提供（実装済み）

**実装状況:**
- 要件: 「コマンドラインインターフェース（CLI）を提供すること（開発・デバッグ用）」
- 現状: `src/cli/main.py` で CLI を実装済み

**実装箇所:**
- `src/cli/main.py` - `--config`, `--once`, `--dry-run` 等をサポート
- `src/main.py` - GUI/バックグラウンドモード用

**受け入れ確認:**
```powershell
# CLI実行（1回だけ検索・ダウンロード）
python src\cli\main.py --config config\config.yaml --once

# ドライラン実行
python src\cli\main.py --config config\config.yaml --once --dry-run
```

### P1（重要・推奨修正）

#### 4. FR-016: custom cron のGUI設定

**乖離内容:**
- 要件: 「スケジュール設定: 実行間隔の指定、実行時刻の指定、custom cron形式」
- 現状: custom cronは実装済みだが、GUIから設定できない可能性

**現状実装:**
- `src/scheduler/scheduler.py:105-133` `_schedule_custom()` - croniterを使用して実装済み
- `src/gui/settings_dialog.py:203-230` - スケジュール設定UI（要確認）

**影響:**
- GUIからcustom cronを設定できない場合、設定ファイルを直接編集する必要がある

**修正方針:**
- GUIのスケジュール設定に「カスタム（cron形式）」オプションを追加
- cron式の入力欄を追加
- cron式の検証を実装

**実装ステップ:**
1. `settings_dialog.py` のスケジュール設定UIを確認
2. 「カスタム（cron形式）」オプションを追加
3. cron式の入力欄を追加
4. cron式の検証を実装（`croniter.is_valid()` を使用）

**テスト方針:**
- GUIからcustom cronを設定できることを確認
- 無効なcron式でエラーが表示されることを確認

**受け入れ確認:**
```powershell
# GUIを起動して設定ダイアログを開く
python src\main.py
# 設定ダイアログで「カスタム（cron形式）」を選択し、cron式を入力
# 設定を保存して、スケジューラーが正しく動作することを確認
```

#### 5. FR-SET-007: 設定リセット機能

**乖離内容:**
- 要件: 「設定のリセット: すべての設定項目をデフォルト値にリセットできること」
- 現状: ✅ 実装済み

**現状実装:**
- `src/gui/settings_dialog.py:976-978` - `on_reset()` メソッドが実装済み
- `ConfigManager.get_default_config()` を使用してデフォルト設定を取得し、UIに反映

**影響:**
- なし（実装済み）

**修正方針:**
- 修正不要

**備考:**
- 実装済みのため、修正は不要

### P2（将来実装・低優先度）

#### 6. FR-020: 設定プロファイル管理

**乖離内容:**
- 要件: 「複数の設定プロファイルを管理できること（将来拡張）」
- 現状: 未実装

**修正方針:**
- 設定ファイルのパスを指定できる機能を追加
- プロファイル切り替えUIを追加（将来実装）

#### 7. FR-SET-008/009/010: 設定ダイアログの高度な機能

**乖離内容:**
- 要件: 「設定プロファイル管理、インポート/エクスポート、プレビュー機能」
- 現状: 未実装

**修正方針:**
- 要件定義に従って段階的に実装（将来実装）

## 3. 修正ステップ（作業順にチェックリスト形式）

### P0: 失敗理由別サマリー実装

- [ ] 1. `src/models/download_task.py` に `error_type` フィールドを追加
- [ ] 2. `src/models/download_result.py` に失敗理由別の集計フィールドを追加
- [ ] 3. `src/core/downloader.py` で失敗理由を分類して `error_type` を設定
- [ ] 4. サマリー出力時に失敗理由別件数を表示
- [ ] 5. テストを追加（`tests/test_downloader.py`）

### P0: 重複回避の拡張

- [ ] 1. `src/core/download_history.py` を新規作成
- [ ] 2. `Downloader` に `history` フィールドを追加
- [ ] 3. `check_duplicate()` を拡張してURL同一判定・ファイル名+サイズ判定を実装
- [ ] 4. ダウンロード成功時に履歴を記録
- [ ] 5. テストを追加（`tests/test_downloader.py`）

### P0: CLI実装

- [ ] 1. `src/cli/main.py` を新規作成
- [ ] 2. `argparse` でコマンドライン引数を解析
- [ ] 3. `ApplicationService` を使用してダウンロードを実行
- [ ] 4. 結果をJSON形式で出力
- [ ] 5. テストを追加（`tests/test_cli.py`）

### P1: custom cron のGUI設定

- [ ] 1. `settings_dialog.py` のスケジュール設定UIを確認
- [ ] 2. 「カスタム（cron形式）」オプションを追加
- [ ] 3. cron式の入力欄を追加
- [ ] 4. cron式の検証を実装

### P1: 設定リセット機能

- [x] 1. `on_reset()` メソッドの実装内容を確認（実装済み）
- [x] 2. 未実装の場合は実装（不要）

## 4. 変更差分（ファイルパス単位）

### P0: 失敗理由別サマリー実装

**src/models/download_task.py:**
```python
# src/models/download_task.py (行1-20)
@dataclass
class DownloadTask:
    """ダウンロードタスクを保持するデータモデル"""
    file_info: FileInfo
    local_path: str
    box_folder_id: str = None
    status: str = "pending"
    error_message: str = ""
+   error_type: str = ""  # エラー種別（network_error, http_429, http_5xx, http_4xx, other）
    retry_count: int = 0
```

**src/models/download_result.py:**
```python
# src/models/download_result.py (行10-18)
@dataclass
class DownloadResult:
    """ダウンロード結果を保持するデータモデル"""
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
+   error_summary: Dict[str, int] = field(default_factory=lambda: {
+       "network_error": 0,
+       "http_429": 0,
+       "http_5xx": 0,
+       "http_4xx": 0,
+       "other": 0
+   })
    tasks: List[DownloadTask] = field(default_factory=list)

+   def update_error_summary(self, task: DownloadTask):
+       """エラーサマリーを更新"""
+       if task.status == "failed" and task.error_type:
+           self.error_summary[task.error_type] = self.error_summary.get(task.error_type, 0) + 1
```

**src/core/downloader.py:**
```python
# src/core/downloader.py (行275-296)
                try:
                    success = self.download_file(file_info, save_path, progress_wrapper)
                except requests.exceptions.RequestException as e:
                    # ネットワークエラーは再試行可能な例外として再送出
                    self.logger.warning(f"ダウンロードエラー（リトライ可能）: {file_info.filename} - {str(e)}")
                    # retry_download でリトライ
                    success = self.retry_download(file_info, save_path, max_retries=3)
+                   # エラー種別を判定
+                   if not success:
+                       task.error_type = self._classify_error(e)
                except Exception as e:
                    # その他の例外も再送出（リトライ不可）
                    self.logger.error(f"ダウンロードエラー（リトライ不可）: {file_info.filename} - {str(e)}", exc_info=True)
                    success = False
+                   task.error_type = "other"

                if success:
                    task.mark_completed()
                else:
                    # 最終的な失敗理由を取得
                    error_message = "ダウンロードに失敗しました"
                    if hasattr(file_info, '_last_error'):
                        error_message = file_info._last_error
                    task.mark_failed(error_message)
+                   if not task.error_type:
+                       task.error_type = "other"

                result.add_task(task)
                result.update_status(task)
+               result.update_error_summary(task)

+   def _classify_error(self, exception: Exception) -> str:
+       """エラーを分類"""
+       if isinstance(exception, requests.exceptions.Timeout):
+           return "network_error"
+       if isinstance(exception, requests.exceptions.ConnectionError):
+           return "network_error"
+       if isinstance(exception, requests.exceptions.HTTPError):
+           if exception.response:
+               status_code = exception.response.status_code
+               if status_code == 429:
+                   return "http_429"
+               elif 500 <= status_code < 600:
+                   return "http_5xx"
+               elif 400 <= status_code < 500:
+                   return "http_4xx"
+       return "other"
```

### P0: 重複回避の拡張

**src/core/download_history.py (新規作成):**
```python
# src/core/download_history.py (新規作成)
# -*- coding: utf-8 -*-

"""ダウンロード履歴を管理するクラス"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from ..utils.logger import Logger


class DownloadHistory:
    """ダウンロード履歴を管理するクラス"""

    def __init__(self, history_file: str = "logs/download_history.jsonl", logger: Optional[Logger] = None):
        """初期化"""
        self.history_file = Path(history_file)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logger or Logger()

    def add_record(
        self,
        url: str,
        filename: str,
        file_path: str,
        file_size: int,
        file_hash: Optional[str] = None,
        status: str = "completed",
        error_message: Optional[str] = None,
    ):
        """ダウンロード履歴を追加"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "url": url,
            "filename": filename,
            "file_path": str(file_path),
            "file_size": file_size,
            "file_hash": file_hash,
            "status": status,
            "error_message": error_message,
        }
        
        try:
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            self.logger.warning(f"ダウンロード履歴の記録に失敗: {str(e)}")

    def find_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """URLで履歴を検索（最新の1件）"""
        if not self.history_file.exists():
            return None
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in reversed(list(f)):
                    record = json.loads(line.strip())
                    if record.get("url") == url:
                        return record
        except Exception as e:
            self.logger.warning(f"ダウンロード履歴の読み込みに失敗: {str(e)}")
        
        return None

    def find_by_filename_and_size(self, filename: str, file_size: int) -> Optional[Dict[str, Any]]:
        """ファイル名+サイズで履歴を検索（最新の1件）"""
        if not self.history_file.exists():
            return None
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in reversed(list(f)):
                    record = json.loads(line.strip())
                    if record.get("filename") == filename and record.get("file_size") == file_size:
                        return record
        except Exception as e:
            self.logger.warning(f"ダウンロード履歴の読み込みに失敗: {str(e)}")
        
        return None
```

**src/core/downloader.py:**
```python
# src/core/downloader.py (行1-25)
from typing import List, Optional, Callable
from pathlib import Path
+ import hashlib
from ..models.file_info import FileInfo
# ... 既存のインポート ...
+ from ..core.download_history import DownloadHistory

class Downloader:
    """ファイルダウンロードを行うクラス"""

-   def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None):
+   def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None, history_file: Optional[str] = None):
        """初期化"""
        self.http_client = http_client
        self.logger = logger or Logger()
        self.file_utils = FileUtils()
+       self.history = DownloadHistory(history_file or "logs/download_history.jsonl", self.logger)

+   def _calculate_file_hash(self, file_path: str) -> Optional[str]:
+       """ファイルのハッシュ値を計算"""
+       try:
+           hash_md5 = hashlib.md5()
+           with open(file_path, "rb") as f:
+               for chunk in iter(lambda: f.read(4096), b""):
+                   hash_md5.update(chunk)
+           return hash_md5.hexdigest()
+       except Exception as e:
+           self.logger.warning(f"ファイルハッシュの計算に失敗: {file_path} - {str(e)}")
+           return None

# src/core/downloader.py (行330-393)
    def check_duplicate(self, file_path: str) -> bool:
        """重複チェック（ファイル存在、URL同一、ファイル名+サイズ）"""
        path = Path(file_path)
        
        # 1. ファイル存在チェック（既存実装）
        if path.exists() and path.stat().st_size > 0:
            # ... 既存の実装 ...
            return True
        
+       # 2. URL同一判定
+       if hasattr(self, 'current_file_info') and self.current_file_info:
+           history_record = self.history.find_by_url(self.current_file_info.url)
+           if history_record and history_record.get("status") == "completed":
+               self.logger.debug(f"スキップ（URL同一）: {self.current_file_info.url}")
+               return True
+       
+       # 3. ファイル名+サイズ判定
+       filename = path.name
+       if path.exists():
+           file_size = path.stat().st_size
+           history_record = self.history.find_by_filename_and_size(filename, file_size)
+           if history_record and history_record.get("status") == "completed":
+               self.logger.debug(f"スキップ（ファイル名+サイズ同一）: {filename} ({file_size} bytes)")
+               return True
        
        return False

# src/core/downloader.py (download_file メソッド内、成功時)
        if success:
            self.logger.info(f"ダウンロード完了: {save_path}")
+           # ダウンロード履歴を記録
+           file_hash = self._calculate_file_hash(save_path)
+           file_size = Path(save_path).stat().st_size if Path(save_path).exists() else 0
+           self.history.add_record(
+               url=file_info.url,
+               filename=file_info.filename,
+               file_path=save_path,
+               file_size=file_size,
+               file_hash=file_hash,
+               status="completed",
+           )
```

### P0: CLI実装

**src/cli/main.py (新規作成):**
```python
# src/cli/main.py (新規作成)
# -*- coding: utf-8 -*-

"""CLIエントリーポイント（開発・デバッグ用）"""

import argparse
import json
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.config.config_manager import ConfigManager
from src.utils.logger import Logger
from src.app.service import ApplicationService
from src.app.events import ProgressEvent


def main():
    """CLIメイン関数"""
    parser = argparse.ArgumentParser(
        description="ppi-file-downloader CLI（開発・デバッグ用）"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.yaml",
        help="設定ファイルのパス（デフォルト: config/config.yaml）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ドライラン実行（実際にはダウンロードしない）"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="結果をJSON形式で出力するファイルパス"
    )
    
    args = parser.parse_args()
    
    # 設定を読み込み
    config_manager = ConfigManager(args.config)
    config = config_manager.load_config()
    logger = Logger(config.logging)
    
    # ApplicationServiceを使用
    service = ApplicationService(logger)
    
    # 進捗コールバック（ログのみ）
    def progress_callback(event: ProgressEvent):
        if event.message:
            logger.info(event.message)
    
    # 実行
    if args.dry_run:
        logger.info("ドライラン実行モード")
        # 実際のダウンロードは行わない
        # TODO: ファイル抽出のみ実行して結果を表示
        return
    
    run_result = service.run(config, progress_callback, cancel_flag=None)
    
    # 結果を出力
    if args.output:
        result_data = {
            "success": run_result.success,
            "message": run_result.message,
            "error": run_result.error,
            "result": {
                "total": run_result.result.total if run_result.result else 0,
                "success": run_result.result.success if run_result.result else 0,
                "failed": run_result.result.failed if run_result.result else 0,
                "skipped": run_result.result.skipped if run_result.result else 0,
                "error_summary": run_result.result.error_summary if run_result.result else {},
            } if run_result.result else None
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        logger.info(f"結果を {args.output} に出力しました")
    else:
        # コンソールに結果を表示
        if run_result.result:
            result = run_result.result
            print(f"ダウンロード完了: 成功={result.success}, 失敗={result.failed}, スキップ={result.skipped}")
            if result.error_summary:
                print("失敗理由別:")
                for error_type, count in result.error_summary.items():
                    if count > 0:
                        print(f"  {error_type}: {count}")


if __name__ == "__main__":
    main()
```

## 5. テスト計画（追加/変更）

### テストファイル: `tests/test_downloader.py`

**追加テスト:**
```python
def test_error_categorization():
    """失敗理由の分類テスト"""
    # 各種エラーを模擬して、正しく分類されることを確認
    pass

def test_duplicate_detection_by_url():
    """URL同一判定のテスト"""
    # 同一URLのファイルを2回ダウンロードして、2回目がスキップされることを確認
    pass

def test_duplicate_detection_by_filename_and_size():
    """ファイル名+サイズ判定のテスト"""
    # 同名+同サイズのファイルを2回ダウンロードして、2回目がスキップされることを確認
    pass
```

### テストファイル: `tests/test_cli.py` (新規作成)

```python
def test_cli_basic():
    """CLI基本動作テスト"""
    # CLIコマンドが正常に実行されることを確認
    pass

def test_cli_dry_run():
    """CLIドライラン実行テスト"""
    # ドライラン実行が正常に動作することを確認
    pass

def test_cli_output_json():
    """CLI JSON出力テスト"""
    # 結果がJSON形式で正しく出力されることを確認
    pass
```

## 6. 動作確認手順（PowerShellコマンド）

### P0: 失敗理由別サマリー実装

```powershell
# 1. テスト実行
pytest tests/test_downloader.py::test_error_categorization -v

# 2. 実際のダウンロード実行でサマリーを確認
python src\main.py
# ログで失敗理由別件数が表示されることを確認
Get-Content logs\app.log | Select-String -Pattern "失敗理由別|error_summary" | Select-Object -Last 10
```

### P0: 重複回避の拡張

```powershell
# 1. テスト実行
pytest tests/test_downloader.py::test_duplicate_detection_by_url -v
pytest tests/test_downloader.py::test_duplicate_detection_by_filename_and_size -v

# 2. 実際のダウンロード実行で重複回避を確認
python src\main.py
# 1回目実行
python src\main.py
# 2回目実行時にスキップされることを確認
Get-Content logs\download_history.jsonl | ConvertFrom-Json | Format-Table -AutoSize
```

### P0: CLI実装

```powershell
# 1. CLI実行
python src\cli\main.py --config config\config.yaml

# 2. ドライラン実行
python src\cli\main.py --config config\config.yaml --dry-run

# 3. 結果をJSON形式で出力
python src\cli\main.py --config config\config.yaml --output result.json
Get-Content result.json | ConvertFrom-Json | Format-Table -AutoSize
```

### P1: custom cron のGUI設定

```powershell
# GUIを起動して設定ダイアログを開く
python src\main.py
# 設定ダイアログで「カスタム（cron形式）」を選択し、cron式を入力
# 設定を保存して、スケジューラーが正しく動作することを確認
```

### P1: 設定リセット機能

```powershell
# GUIを起動して設定ダイアログを開く
python src\main.py
# 設定ダイアログで「デフォルトに戻す」ボタンをクリック
# すべての設定がデフォルト値にリセットされることを確認
```

## 7. コミットメッセージ案（修正項目ごと）

### P0: 失敗理由別サマリー実装

```
feat: 失敗理由別サマリー機能を実装

- DownloadTask に error_type フィールドを追加
- DownloadResult に error_summary フィールドを追加
- downloader.py で失敗理由を分類（network_error, http_429, http_5xx, http_4xx, other）
- サマリー出力時に失敗理由別件数を表示

これにより、運用で失敗原因を把握できるようになる。
要件: FR-005
```

### P0: 重複回避の拡張

```
feat: 重複回避機能を拡張（URL同一判定・ファイル名+サイズ判定）

- DownloadHistory クラスを新規作成（ダウンロード履歴管理）
- check_duplicate() を拡張してURL同一判定・ファイル名+サイズ判定を実装
- ダウンロード成功時に履歴を記録（JSONL形式）

これにより、同一URLのファイルや同名+同サイズのファイルを検出できるようになる。
要件: FR-008
```

### P0: CLI実装

```
feat: CLIエントリーポイントを実装

- src/cli/main.py を新規作成
- argparse でコマンドライン引数を解析（--config, --dry-run, --output）
- ApplicationService を使用してダウンロードを実行
- 結果をJSON形式で出力

これにより、開発・デバッグ時にGUIを起動せずに実行できるようになる。
要件: FR-024
```

### P1: custom cron のGUI設定

```
feat: GUIからcustom cron形式を設定できるように改善

- settings_dialog.py のスケジュール設定UIに「カスタム（cron形式）」オプションを追加
- cron式の入力欄を追加
- cron式の検証を実装（croniter.is_valid() を使用）

これにより、GUIからcustom cronを設定できるようになる。
要件: FR-016, FR-SET-002
```

### P1: 設定リセット機能

```
（実装済みのため、コミット不要）
```
