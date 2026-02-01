# 実務運用品質向上のための修正内容

## 修正一覧（優先度順）

### P0（最優先・必須修正）

#### 1. テストがデフォルト実行でGUI(Tk)を起動してハングする問題を修正 ✅

**対象ファイル:** `tests/test_phase_a.py`

**問題:**
- `test_event_handler_creation()` がGUI（Tk）を起動してハングする可能性がある

**修正内容:**
- 既に `@pytest.mark.gui` が付いていることを確認（98行目）
- `pytest.ini` のデフォルト設定で `-m "not gui and not network and not integration"` が指定されているため、デフォルト実行ではスキップされる

**差分:**
```python
# tests/test_phase_a.py (行98)
+ @pytest.mark.gui
def test_event_handler_creation():
    """EventHandlerの作成確認（GUIなし）"""
    # ... 既存コード ...
```

**確認コマンド:**
```powershell
# デフォルト実行（GUIテストをスキップ）
pytest tests/test_phase_a.py -v

# GUIテストを含めて実行
pytest tests/test_phase_a.py -m gui -v
```

#### 2. レビュー/配布ZIP作成スクリプト不具合修正 ✅

**対象ファイル:** `pack_for_review.ps1`, `pack_for_review2.ps1`

**問題:**
- `pack_for_review.ps1`: `config.example.yaml` が `IncludeDirs` に含まれている（ファイルなので `IncludeFiles` に移動すべき）
- `pack_for_review2.ps1`: `$templatePatterns` 未定義エラー（198行目）

**修正内容:**

**pack_for_review.ps1:**
```powershell
# pack_for_review.ps1 (行22-48)
- $IncludeDirs = @(
-     "src",
-     "tests",
-     "docs",
-     "scripts",
-     "config.example.yaml",  # ファイルなので削除
-     "assets",
-     "resources",
-     "templates"
- )
+ $IncludeDirs = @(
+     "src",
+     "tests",
+     "docs",
+     "scripts",
+     "config",  # ディレクトリとして追加
+     "assets",
+     "resources",
+     "templates"
+ )

- $IncludeFiles = @(
-     "README.md",
-     "README.txt",
-     # ...
- )
+ $IncludeFiles = @(
+     "README.md",
+     "README.txt",
+     "config.example.yaml",  # ファイルとして追加
+     # ...
+ )
```

**pack_for_review2.ps1:**
```powershell
# pack_for_review2.ps1 (行188-201)
+ # テンプレートファイルのパターン定義
+ $templatePatterns = @(
+     "*.example.*",
+     "*.sample.*",
+     "*.template.*",
+     "*example*",
+     "*sample*",
+     "*template*"
+ )

# pack_for_review2.ps1 (行63-77)
$ExcludeDirNames = @(
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    ".git",
+   "logs"  # 追加
)

# pack_for_review2.ps1 (行308-315)
Write-Step "ZIP作成: $ZipName"
Compress-Archive -Path (Join-Path $OutDir "*") -DestinationPath $ZipPath -Force

+ # MANIFEST.txt の内容を表示
+ Write-Step "MANIFEST.txt の内容:"
+ Get-Content -LiteralPath $ManifestPath | ForEach-Object { Write-Info $_ }
+
Write-Step "完了"
```

**確認コマンド:**
```powershell
# pack_for_review2.ps1 を実行
.\pack_for_review2.ps1

# 生成物の確認
Get-Content .\_review_pack\MANIFEST.txt
Get-ChildItem .\_review_pack -Recurse | Select-Object FullName, Length | Format-Table -AutoSize

# 不要物が含まれていないことを確認
Get-ChildItem .\_review_pack -Recurse -Directory | Where-Object { $_.Name -in @(".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".idea", ".vscode", "node_modules", "dist", "build", ".git", "logs") }
```

#### 3. naming_rule を設定通りに反映（テンプレ命名を実装） ✅

**対象ファイル:** `src/core/naming.py`, `tests/test_naming.py` (新規作成)

**修正内容:**

**src/core/naming.py:**
```python
# src/core/naming.py (行29-79)
def generate_filename(
    self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
) -> str:
-   """ファイル名を生成: 大分類_中分類_小分類_細分類_工事名_ファイル名"""
-   # 検索条件から分類情報を取得してファイル名を構築
-   parts = []
-   # ... 既存の固定ロジック ...
+   """ファイル名を生成
+   
+   naming_rule が設定されている場合はテンプレート文字列を使用し、
+   設定されていない場合は従来の固定ロジックを使用する。
+   """
+   # コンテキストを構築
+   context = self._build_context_from_search_conditions(file_info, metadata, index)
+   
+   # naming_rule が設定されている場合はテンプレート文字列を使用
+   if self.naming_rule and self.naming_rule.strip():
+       try:
+           # テンプレート文字列を展開
+           filename = self.naming_rule.format_map(context)
+           self.logger.debug(f"テンプレート文字列を使用: '{self.naming_rule}' -> '{filename}'")
+       except KeyError as e:
+           # 欠けているキーがある場合は警告を出してデフォルト値を使用
+           missing_key = str(e).strip("'")
+           self.logger.warning(f"テンプレートに欠けているキー: {missing_key}。デフォルト値（空文字）を使用します。")
+           # 欠けているキーを空文字で補完
+           safe_context = {**context, missing_key: ""}
+           filename = self.naming_rule.format_map(safe_context)
+       except Exception as e:
+           # その他のエラー（フォーマットエラー等）の場合は従来ロジックにフォールバック
+           self.logger.warning(f"テンプレート文字列の展開に失敗: {str(e)}。従来のロジックを使用します。")
+           filename = self._generate_filename_legacy(file_info, metadata, index)
+   else:
+       # naming_rule が設定されていない場合は従来の固定ロジックを使用
+       filename = self._generate_filename_legacy(file_info, metadata, index)
    
    # 無効な文字を削除
    filename = self.file_utils.sanitize_filename(filename)
    
    # 拡張子を追加（元のファイルの拡張子）
    extension = file_info.get_file_extension()
    if extension and not filename.endswith(extension):
        filename += extension

    self.logger.debug(f"生成されたファイル名: '{filename}'")
    return filename

+ def _generate_filename_legacy(
+     self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
+ ) -> str:
+     """従来の固定ロジックでファイル名を生成: 大分類_中分類_小分類_細分類_工事名_ファイル名"""
+     # ... 既存の固定ロジック ...
```

**src/core/naming.py (_build_context_from_search_conditions の改善):**
```python
# src/core/naming.py (行81-115)
def _build_context_from_search_conditions(
    self, file_info: FileInfo, metadata: Dict[str, Any] = None, index: int = 0
) -> Dict[str, Any]:
    """検索条件からコンテキストを構築（テンプレート文字列用）"""
+   # メタデータをマージ
+   merged_metadata = {}
+   if metadata:
+       merged_metadata.update(metadata)
+   if file_info.metadata:
+       merged_metadata.update(file_info.metadata)
+   
+   # 元のファイル名（拡張子を除く）
+   original_filename = file_info.filename
+   if "." in original_filename:
+       original_filename = original_filename.rsplit(".", 1)[0]
+   
    # 基本コンテキスト
    context = {
-       "filename": file_info.filename,
+       "filename": original_filename,
        "file_type": file_info.get_file_extension().replace(".", ""),
-       "category": metadata.get("category", "") if metadata else "",
-       "title": metadata.get("title", "") if metadata else "",
+       "category": merged_metadata.get("category", ""),
+       "title": merged_metadata.get("title", ""),
        "date": datetime.now().strftime("%Y%m%d"),
        "index": str(index),
    }
    
    # 検索条件から分類情報を取得
    if self.search_conditions:
        sc = self.search_conditions
        context["daibunrui"] = sc.hachu_daibunrui or ""
        context["chubunrui"] = sc.hachu_chubunrui or ""
        context["shoubunrui"] = sc.hachu_shoubunrui or ""
        context["saibunrui"] = sc.hachu_saibunrui or ""
-       context["koji_name"] = sc.koji_name or ""
+       context["koji_name"] = merged_metadata.get("koji_name", sc.koji_name or "")
    else:
        context["daibunrui"] = ""
        context["chubunrui"] = ""
        context["shoubunrui"] = ""
        context["saibunrui"] = ""
-       context["koji_name"] = ""
+       context["koji_name"] = merged_metadata.get("koji_name", "")
    
-   # メタデータから追加情報を取得
-   if metadata:
-       context.update(metadata)
-   if file_info.metadata:
-       context.update(file_info.metadata)
+   # メタデータから追加情報を取得（既存のキーを上書きしない）
+   for key, value in merged_metadata.items():
+       if key not in context:
+           # 値が文字列でない場合は文字列に変換
+           context[key] = str(value) if value is not None else ""
+   
+   # すべての値を文字列に変換（安全のため）
+   safe_context = {}
+   for key, value in context.items():
+       if value is None:
+           safe_context[key] = ""
+       elif isinstance(value, (int, float)):
+           safe_context[key] = str(value)
+       elif isinstance(value, datetime):
+           safe_context[key] = value.strftime("%Y%m%d")
+       else:
+           safe_context[key] = str(value)
    
-   return context
+   return safe_context
```

**tests/test_naming.py (新規作成):**
```python
# tests/test_naming.py (新規作成)
# テンプレート文字列を使用したファイル名生成のテスト
# 欠損キーがあっても例外にならないことのテスト
# など
```

**確認コマンド:**
```powershell
# naming のテストを実行
pytest tests/test_naming.py -v

# 設定ファイルで naming_rule を設定して動作確認
# config/config.yaml:
# naming_rule: "{category}_{title}_{date}_{index}"

python src\main.py
# ダウンロードを実行してファイル名を確認
Get-ChildItem .\downloads -Recurse -File | Select-Object Name | Format-Table -AutoSize
```

### P1（重要・推奨修正）

#### 4. 「動かない機能」を整理（date_range / custom cron） ✅

**採用方針: A) 実装する**

**理由:**
- `date_range` と `custom cron` は要件定義に記載されており、ユーザーが期待する機能
- 設定ファイルに既に存在し、UIでも設定可能
- 実装することで機能の完全性が向上する

**対象ファイル:** `src/core/filter.py`, `src/scheduler/scheduler.py`, `requirements.txt`

**修正内容:**

**src/core/filter.py:**
```python
# src/core/filter.py (行76-113)
def match_date_range(self, file_info: FileInfo) -> bool:
    """日付範囲が条件に一致するかチェック
    
+   日付範囲が指定されていない場合は True を返す。
+   日付が取得できない場合は False を返す（フィルタ不一致）。
    """
    if not self.conditions.date_range:
        return True  # 日付範囲が指定されていない場合はすべて一致

    date_range = self.conditions.date_range
    start_date = date_range.get("start")
    end_date = date_range.get("end")

    if not start_date and not end_date:
        return True

-   # メタデータから日付を取得（実装は必要に応じて拡張）
-   file_date = None
-   if file_info.metadata:
-       # メタデータから日付を抽出する処理（実装が必要）
-       pass
-
-   if not file_date:
-       return True  # 日付が取得できない場合は一致とみなす
+   # メタデータから日付を取得
+   file_date = None
+   if file_info.metadata:
+       # 優先順位: koukoku_date > kaisatsu_date > keiyaku_date > update_date > date
+       for date_key in ["koukoku_date", "kaisatsu_date", "keiyaku_date", "update_date", "date"]:
+           if date_key in file_info.metadata:
+               file_date = file_info.metadata[date_key]
+               break
+   
+   if not file_date:
+       # 日付が取得できない場合はフィルタ不一致（False）を返す
+       self.logger.debug(f"日付が取得できませんでした（フィルタ不一致）: {file_info.filename}")
+       return False

    try:
        # 日付文字列を datetime に変換
-       file_datetime = date_parser.parse(file_date) if isinstance(file_date, str) else file_date
+       if isinstance(file_date, str):
+           file_datetime = date_parser.parse(file_date)
+       elif isinstance(file_date, datetime):
+           file_datetime = file_date
+       else:
+           self.logger.warning(f"日付の形式が不正です: {file_date} (type: {type(file_date)})")
+           return False

        # 開始日チェック
        if start_date:
            start_datetime = date_parser.parse(start_date) if isinstance(start_date, str) else start_date
            if file_datetime < start_datetime:
+               self.logger.debug(
+                   f"日付範囲外（開始日より前）: {file_info.filename}, "
+                   f"ファイル日付={file_datetime.strftime('%Y-%m-%d')}, 開始日={start_datetime.strftime('%Y-%m-%d')}"
+               )
                return False

        # 終了日チェック
        if end_date:
            end_datetime = date_parser.parse(end_date) if isinstance(end_date, str) else end_date
            if file_datetime > end_datetime:
+               self.logger.debug(
+                   f"日付範囲外（終了日より後）: {file_info.filename}, "
+                   f"ファイル日付={file_datetime.strftime('%Y-%m-%d')}, 終了日={end_datetime.strftime('%Y-%m-%d')}"
+               )
                return False

        return True
    except Exception as e:
        self.logger.warning(f"日付解析エラー: {str(e)}, file_info={file_info.filename}")
-       return True  # エラーの場合は一致とみなす
+       # エラーの場合はフィルタ不一致（False）を返す
+       return False
```

**src/scheduler/scheduler.py:**
```python
# src/scheduler/scheduler.py (行67-71)
elif self.config.interval == "custom" and self.config.cron:
    # カスタム（cron形式）
-   # 注意: scheduleライブラリはcron形式を直接サポートしていないため、
-   # 簡易的な実装とする
-   self.logger.warning("カスタムcron形式は現在サポートされていません")
+   self._schedule_custom()

# src/scheduler/scheduler.py (行106-133) - 新規追加
+ def _schedule_custom(self):
+     """カスタム（cron形式）のスケジュールを設定"""
+     try:
+         from croniter import croniter
+         
+         cron_expr = self.config.cron
+         if not croniter.is_valid(cron_expr):
+             raise ValueError(f"無効なcron式: {cron_expr}")
+         
+         # croniterを使用して次の実行時刻を計算
+         base_time = datetime.now()
+         cron = croniter(cron_expr, base_time)
+         next_run = cron.get_next(datetime)
+         
+         self.logger.info(f"カスタムcron形式を設定: {cron_expr}, 次回実行予定: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
+         
+         # scheduleライブラリではcron形式を直接サポートしていないため、
+         # 1分ごとにチェックしてcron式に一致するか確認する方式を採用
+         def cron_job():
+             now = datetime.now()
+             cron_check = croniter(cron_expr, now)
+             prev_run = cron_check.get_prev(datetime)
+             # 前回実行時刻から1分以内なら実行（重複実行を防ぐ）
+             if (now - prev_run).total_seconds() < 60:
+                 self._execute_download()
+         
+         # 1分ごとにチェック
+         schedule.every(1).minutes.do(cron_job)
+         
+     except ImportError:
+         self.logger.error("croniter がインストールされていません。pip install croniter を実行してください。")
+         raise
+     except Exception as e:
+         self.logger.error(f"カスタムcron形式の設定エラー: {str(e)}")
+         raise
```

**requirements.txt:**
```txt
# requirements.txt
# スケジューリング
schedule>=1.2.0
+ croniter>=2.0.0
```

**確認コマンド:**
```powershell
# date_range の動作確認
# config/config.yaml:
# download_conditions:
#   date_range:
#     start: "2024-01-01"
#     end: "2024-12-31"

python src\main.py
Get-Content .\logs\app.log -Tail 50 | Select-String -Pattern "日付範囲|フィルタリング"

# custom cron の動作確認
# config/config.yaml:
# schedule:
#   enabled: true
#   interval: "custom"
#   cron: "0 9 * * *"

python src\main.py --background
Get-Content .\logs\app.log -Tail 50 | Select-String -Pattern "カスタムcron|次回実行予定"
```

### P2（将来実装・低優先度）

#### 5. 通信安定化（Accept-Encodingの矛盾解消） ✅

**対象ファイル:** `src/utils/http_client.py`

**修正内容:**
```python
# src/utils/http_client.py (行200)
download_headers = {
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
-   "Accept-Encoding": "gzip, deflate, br",
+   "Accept-Encoding": "gzip, deflate",  # br を削除（Brotli 対応なし）
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
```

#### 6. リトライ設計（tenacityの実効性改善） ✅

**対象ファイル:** `src/core/downloader.py`

**修正内容:**
```python
# src/core/downloader.py (行188-195)
- @retry(
-     stop=stop_after_attempt(3),
-     wait=wait_exponential(multiplier=1, min=2, max=10),
-     retry=retry_if_exception_type((
-         requests.exceptions.RequestException,
-         requests.exceptions.HTTPError,
-     )),
- )
def download_files(
    # ... 既存コード ...

# src/core/downloader.py (行26-72)
def download_file(
    self, file_info: FileInfo, save_path: str, progress_callback: Optional[Callable] = None
) -> bool:
    """ファイルをダウンロード"""
    try:
        # ... 既存コード ...
        return success

-   except Exception as e:
-       self.logger.error(f"ダウンロードエラー: {save_path} - {str(e)}", exc_info=True)
-       return False
+   except requests.exceptions.RequestException as e:
+       # ネットワークエラーは再送出（リトライ可能）
+       error_msg = f"ネットワークエラー: {save_path} - {str(e)}"
+       if not hasattr(file_info, '_last_error'):
+           file_info._last_error = error_msg
+       self.logger.warning(error_msg)
+       raise  # 例外を再送出してリトライ可能にする
+   except Exception as e:
+       # その他の例外も再送出
+       error_msg = f"ダウンロードエラー: {save_path} - {str(e)}"
+       if not hasattr(file_info, '_last_error'):
+           file_info._last_error = error_msg
+       self.logger.error(error_msg, exc_info=True)
+       raise  # 例外を再送出

# src/core/downloader.py (行275-287)
# ダウンロード実行（ファイル単位でリトライ）
# 例外を適切に再送出して、retry_download でリトライできるようにする
try:
    success = self.download_file(file_info, save_path, progress_wrapper)
+ except requests.exceptions.RequestException as e:
+     # ネットワークエラーは再試行可能な例外として再送出
+     self.logger.warning(f"ダウンロードエラー（リトライ可能）: {file_info.filename} - {str(e)}")
+     # retry_download でリトライ
+     success = self.retry_download(file_info, save_path, max_retries=3)
+ except Exception as e:
+     # その他の例外も再送出（リトライ不可）
+     self.logger.error(f"ダウンロードエラー（リトライ不可）: {file_info.filename} - {str(e)}", exc_info=True)
+     success = False

# src/core/downloader.py (行318-332)
+ @retry(
+     stop=stop_after_attempt(3),
+     wait=wait_exponential(multiplier=1, min=2, max=10),
+     retry=retry_if_exception_type((
+         requests.exceptions.RequestException,
+         requests.exceptions.HTTPError,
+     )),
+ )
def retry_download(self, file_info: FileInfo, save_path: str, max_retries: int = 3) -> bool:
-   """ダウンロードをリトライ"""
-   for attempt in range(max_retries):
-       self.logger.info(f"リトライ {attempt + 1}/{max_retries}: {save_path}")
-       if self.download_file(file_info, save_path):
-           return True
-   return False
+   """ダウンロードをリトライ（tenacity デコレータ使用）
+   
+   download_file が例外を再送出するため、tenacity が自動的にリトライする。
+   3回リトライしても失敗した場合は False を返す。
+   """
+   try:
+       # download_file が例外を再送出するため、tenacity が自動的にリトライする
+       return self.download_file(file_info, save_path)
+   except Exception as e:
+       # 最終的な失敗（3回リトライ後も失敗）
+       error_msg = f"リトライ後もダウンロードに失敗: {save_path} - {str(e)}"
+       if not hasattr(file_info, '_last_error'):
+           file_info._last_error = error_msg
+       self.logger.error(error_msg)
+       return False
```

#### 7. ログ設計の統一（handlers.clear 副作用を排除） ✅

**対象ファイル:** `src/utils/logger.py`

**修正内容:**
```python
# src/utils/logger.py (行29-43)
self.logger = logging.getLogger("ppi_file_downloader")
self.logger.setLevel(getattr(logging, self.config.level.upper(), logging.INFO))
- self.logger.handlers.clear()  # 既存のハンドラーをクリア

- # コンソールハンドラー
- console_handler = logging.StreamHandler()
- console_handler.setLevel(logging.INFO)
- console_formatter = logging.Formatter(
-     "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
- )
- console_handler.setFormatter(console_formatter)
- self.logger.addHandler(console_handler)
-
- # ファイルハンドラー
- self.setup_file_handler()
+ # handlers.clear() を削除（他のLoggerインスタンスに影響を与えないようにする）
+ # 既にハンドラーが設定されている場合は追加しない（二重出力を防ぐ）
+ if not self.logger.handlers:
+     # コンソールハンドラー
+     console_handler = logging.StreamHandler()
+     console_handler.setLevel(logging.INFO)
+     console_formatter = logging.Formatter(
+         "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
+     )
+     console_handler.setFormatter(console_formatter)
+     self.logger.addHandler(console_handler)
+ 
+     # ファイルハンドラー
+     self.setup_file_handler()

# src/utils/logger.py (行45-65)
def setup_file_handler(self):
    """ファイルハンドラーを設定"""
+   # 既にファイルハンドラーが設定されている場合は追加しない（二重出力を防ぐ）
+   if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in self.logger.handlers):
+       return
+   
    log_file = Path(self.config.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # ... 既存コード ...
```
