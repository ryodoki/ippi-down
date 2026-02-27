# 実務運用品質向上のための修正提案

## 1. 全体把握

### 1.1 エントリポイントと処理フロー

#### GUIモード（デフォルト）
```
src/main.py::main()
  → ConfigManager.load_config()
    → config/config.yaml を読み込み（YAML形式）
    → yaml.safe_load() で辞書に変換
    → ConfigManager._dict_to_config() で AppConfig に変換
    → ConfigValidator.validate_config() で検証
  → AppConfig を返す
  → MainWindow（GUI起動）
    → ApplicationService.run()
      → Scraper.extract_files()
      → Filter.filter_files()
      → Downloader.download_files()
```

#### バックグラウンドモード
```
src/main.py::main() (--background または PPI_BACKGROUND_MODE=true)
  → ConfigManager.load_config()
  → AppConfig を返す
  → Scheduler.start()（スケジュール有効時）
    → run_scheduled_download()
      → ApplicationService.run()
```

#### CLI（実装済み）
- 要件定義では「開発・デバッグ用」として定義。`src/cli/main.py` で実装済み（`--config`, `--once`, `--dry-run` 等）
- `src/main.py` は GUI/バックグラウンドモードのみ

### 1.2 設定読み込み経路

```
ConfigManager.load_config()
  → config/config.yaml を読み込み（YAML形式）
  → yaml.safe_load() で辞書に変換
  → ConfigManager._dict_to_config() で AppConfig に変換
  → ConfigValidator.validate_config() で検証
  → AppConfig を返す
    ↓
各コンポーネントに渡される:
  - ApplicationService._initialize_components()
    → Naming(config.naming_rule, ...)
    → Filter(config.download_conditions, ...)
    → Scheduler(config.schedule, ...)
```

### 1.3 設定に存在するが使われていない/挙動とズレている項目

| 設定項目 | 状態 | 影響範囲 | 備考 |
|---------|------|---------|------|
| `naming_rule` | ✅ 実装済み | `src/core/naming.py` | テンプレート文字列を使用 |
| `date_range` | ✅ 実装済み | `src/core/filter.py` | メタデータから日付を取得してフィルタ |
| `schedule.cron` | ✅ 実装済み | `src/scheduler/scheduler.py` | croniter を使用 |
| `tqdm` | ⚠️ 未使用 | - | requirements.txt でコメントアウト |
| Box保存 | ❌ 未実装 | - | READMEに記載があるが実装なし |

### 1.4 ドキュメントと実装の整合差

| ドキュメント | 記載内容 | 実装状況 | 整合性 |
|------------|---------|---------|--------|
| `README.md` | 「ローカルまたはBox」 | Box保存未実装 | ❌ 不一致 |
| `docs/requirement_gap_report.md` | FR-009/010: naming_rule 未実装 | ✅ 実装済み | ❌ 不一致 |
| `docs/requirement_gap_report.md` | FR-016: custom cron 未サポート | ✅ 実装済み | ❌ 不一致 |

## 2. P0: pytest が素で走らない問題を修正

### 何を
- `pytest.ini` の `addopts` に `--timeout=30` / `--timeout-method=thread` があり、`pytest-timeout` 未導入だと pytest がエラーで止まる

### なぜ
- 初見の環境で `pytest` を実行すると、`pytest-timeout` がインストールされていない場合にエラーが発生する
- 開発環境のセットアップが複雑になる

### どう直す
**方針: A) requirements-dev.txt を新設し、pytest-timeout を導入してREADMEに手順追記**

**理由:**
- ハング対策を維持できる
- 開発環境と本番環境の依存関係を分離できる
- 既存の `requirements.txt` を変更せずに済む

**変更差分:**

**requirements-dev.txt (新規作成):**
```txt
# 開発用依存関係

# テスト
pytest>=7.4.0
pytest-cov>=4.1.0
pytest-mock>=3.12.0
pytest-timeout>=2.2.0
```

**pytest.ini:**
```ini
# pytest設定

# テストディレクトリ
testpaths = tests

# Pythonパス
pythonpath = .

# テストファイルのパターン
python_files = test_*.py

# テストクラスのパターン
python_classes = Test*

# テスト関数のパターン
python_functions = test_*

# マーカー定義
markers =
    gui: GUI依存テスト（デフォルトでスキップ）
    network: ネットワーク依存テスト（デフォルトでスキップ）
    integration: 統合テスト（デフォルトでスキップ）
    slow: 実行に時間がかかるテスト

# デフォルトでスキップするマーカー
# 注意: --timeout オプションを使用する場合は pytest-timeout が必要です
# 開発環境では requirements-dev.txt をインストールしてください
addopts = 
    -m "not gui and not network and not integration"
    --tb=short
    -v
    --timeout=30
    --timeout-method=thread
    --durations=10
```

**README.md (セットアップ手順に追加):**
```markdown
### 開発環境のセットアップ

開発・テストを行う場合は、追加の依存関係をインストールしてください:

```powershell
# 開発用依存関係をインストール
pip install -r requirements-dev.txt
```

これにより、pytest-timeout などの開発ツールがインストールされます。
```

### どう確認する
```powershell
# 1. 開発用依存関係をインストール
pip install -r requirements-dev.txt

# 2. pytest が正常に実行できることを確認
pytest

# 3. デフォルトのマーカー設定で実行
pytest -m "not gui and not network and not integration"

# 4. タイムアウト機能が動作することを確認（長時間実行されるテストで）
pytest tests/ -v --timeout=10
```

## 3. P0: 配布/レビューZIPの安全化（漏えい防止）

### 何を
- 共有用ZIPに `.git/.venv/dist/logs/downloads` や `config/config.yaml` が混入し得る
- `pack_for_review.ps1` は `config` ディレクトリを含めるため事故りやすい

### なぜ
- 機密情報（認証情報、設定ファイル）が漏えいするリスクがある
- 不要なファイル（`.git`, `.venv`, `dist`, `logs`, `downloads`）が含まれるとZIPサイズが大きくなる

### どう直す
- `pack_for_review2.ps1` を正式手順としてREADMEに明記
- `pack_for_review.ps1` には `config.yaml` 除外ルールを追加（または非推奨化）

**変更差分:**

**pack_for_review.ps1:**
```powershell
# pack_for_review.ps1 (行22-32, 68-81)
# 2) 含める対象（必要に応じて調整）
$IncludeDirs = @(
    "src",
    "tests",
    "docs",
    "scripts",
-   "config",  # 削除（config.yaml が混入するリスクがあるため）
    "assets",
    "resources",
    "templates"
)

# 4) 除外したいファイルパターン（秘密情報・生成物）
$ExcludeFilePatterns = @(
    "*.pyc",
    "*.pyo",
    "*.log",
+   "config.yaml",  # 実設定ファイルを除外
+   "*.yaml",  # すべてのYAMLファイルを除外（config.example.yaml は手動で追加）
    "*.pfx",
    "*.pem",
    "*.key",
    ".env",
    ".env.*",
    "*secret*",
    "*token*",
    "*credential*"
)

# 単体ファイルのコピー開始
foreach ($f in $IncludeFiles) {
    $src = Join-Path $ProjectRoot $f
    if (Test-Path $src) {
+       # config.yaml は除外
+       if ($f -eq "config.yaml") {
+           Write-Step "スキップ（実設定ファイル）: $f"
+           continue
+       }
        Copy-Item -LiteralPath $src -Destination $OutDir -Force
        Write-Step "コピー: $f"
    }
}

# config.example.yaml のみ手動でコピー
+ $configExample = Join-Path $ProjectRoot "config.example.yaml"
+ if (Test-Path $configExample) {
+     Copy-Item -LiteralPath $configExample -Destination $OutDir -Force
+     Write-Step "コピー: config.example.yaml（テンプレート）"
+ }
```

**README.md (配布/レビューZIP作成手順に追加):**
```markdown
### 配布/レビューZIPの作成

共有用ZIPを作成する場合は、`pack_for_review2.ps1` を使用してください:

```powershell
# 実行ポリシーを設定（初回のみ）
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

# レビュー用ZIPを作成
powershell -ExecutionPolicy Bypass -File .\pack_for_review2.ps1
```

**注意:**
- `pack_for_review2.ps1` は `config/config.yaml`（実設定ファイル）を自動的に除外します
- テンプレートファイル（`config.example.yaml`）のみが含まれます
- `.git`, `.venv`, `dist`, `logs`, `downloads` などの不要なファイルは自動的に除外されます

**生成物の確認:**
```powershell
# MANIFEST.txt で除外/同梱状況を確認
Get-Content .\_review_pack\MANIFEST.txt

# 不要物が含まれていないことを確認
Get-ChildItem .\_review_pack -Recurse -Directory | Where-Object { $_.Name -in @(".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".idea", ".vscode", "node_modules", "dist", "build", ".git", "logs") }

# config.yaml が含まれていないことを確認
Get-ChildItem .\_review_pack -Recurse -Filter "config.yaml" | Select-Object FullName
```

**非推奨:**
- `pack_for_review.ps1` は `config` ディレクトリを含めるため、`config.yaml` が混入するリスクがあります
- 可能な限り `pack_for_review2.ps1` を使用してください
```

### どう確認する
```powershell
# 1. pack_for_review2.ps1 を実行
powershell -ExecutionPolicy Bypass -File .\pack_for_review2.ps1

# 2. MANIFEST.txt で除外/同梱状況を確認
Get-Content .\_review_pack\MANIFEST.txt

# 3. 不要物が含まれていないことを確認
Get-ChildItem .\_review_pack -Recurse -Directory | Where-Object { $_.Name -in @(".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".idea", ".vscode", "node_modules", "dist", "build", ".git", "logs") }

# 4. config.yaml が含まれていないことを確認
Get-ChildItem .\_review_pack -Recurse -Filter "config.yaml" | Select-Object FullName

# 5. config.example.yaml が含まれていることを確認
Get-ChildItem .\_review_pack -Recurse -Filter "config.example.yaml" | Select-Object FullName
```

## 4. P0: ドキュメントと実装の整合を取る

### 何を
- `docs/requirement_gap_report.md` に実装済み/未実装の誤認がある（例: naming_rule や cron 等）
- READMEに「Box保存」等、実装が存在しない記載がある可能性

### なぜ
- ドキュメントと実装の不一致により、開発者やユーザーが混乱する
- 実装状況を正確に把握できない

### どう直す
- 実装の事実に合わせて文書を更新
- 未実装機能は「将来対応」表記にするか、実装するかを明確化（曖昧禁止）

**変更差分:**

**docs/requirement_gap_report.md:**
```markdown
# docs/requirement_gap_report.md (行24-25, 29)
- | **FR-009** | ファイル名自動生成 | ❌ 未実装 | `src/core/naming.py:29-79` `generate_filename()` | **問題**: `naming_rule`（テンプレート文字列）を受け取っているが使用していない。固定の命名規則を使用。 |
- | **FR-010** | 命名規則カスタマイズ | ❌ 未実装 | `src/models/config_model.py:159` `naming_rule: str` | 設定には存在するが、`Naming`クラスで使用されていない |
+ | **FR-009** | ファイル名自動生成 | ✅ 実装済み | `src/core/naming.py:29-79` `generate_filename()` | **修正済み**: `naming_rule`（テンプレート文字列）を使用してファイル名を生成 |
+ | **FR-010** | 命名規則カスタマイズ | ✅ 実装済み | `src/models/config_model.py:159` `naming_rule: str` | **修正済み**: `Naming`クラスでテンプレート文字列を使用 |

- | **FR-016** | スケジューリング機能 | ⚠️ 部分実装 | `src/scheduler/scheduler.py:54-105` `_setup_schedule()` | **問題**: `interval="custom"`かつ`cron`形式が未サポート（警告のみ） |
+ | **FR-016** | スケジューリング機能 | ✅ 実装済み | `src/scheduler/scheduler.py:54-105` `_setup_schedule()` | **修正済み**: `interval="custom"`かつ`cron`形式をサポート（croniter を使用） |
```

**README.md:**
```markdown
# README.md (行7, 31)
- ppi.jpのWebサイトを解析し、ユーザーが指定した条件に一致するファイルを自動的にダウンロードして、指定したフォルダ（ローカルまたはBox）に整理して保存します。
+ ppi.jpのWebサイトを解析し、ユーザーが指定した条件に一致するファイルを自動的にダウンロードして、指定したフォルダ（ローカル）に整理して保存します。

- │   ├── storage/          # ストレージ（local, box）
+ │   ├── storage/          # ストレージ（local、Boxは将来対応予定）
```

### どう確認する
```powershell
# 1. requirement_gap_report.md の内容を確認
Get-Content docs\requirement_gap_report.md | Select-String -Pattern "FR-009|FR-010|FR-016"

# 2. README.md の内容を確認
Get-Content README.md | Select-String -Pattern "Box|box"

# 3. 実装状況を確認
# naming_rule
Get-Content src\core\naming.py | Select-String -Pattern "naming_rule|format_map" -Context 2

# custom cron
Get-Content src\scheduler\scheduler.py | Select-String -Pattern "croniter|_schedule_custom" -Context 2
```

## 5. P1: 重複回避とダウンロード履歴の実務強化（任意だが推奨）

### 何を
- 重複判定が「ファイルの存在」中心で、運用で更新/別名増殖に弱い
- ダウンロード履歴（URL/ファイル名/サイズ/ハッシュ/日時/結果）をログとして残す

### なぜ
- 同一URLの再取得や内容更新の検知が可能になる
- 運用時の問題追跡が容易になる

### どう直す
**設計案:**
- ダウンロード履歴を JSONL 形式で保存（`logs/download_history.jsonl`）
- 各ダウンロード試行ごとに1行のJSONを追加
- 重複判定時に履歴を参照

**最小実装差分:**

**src/core/download_history.py (新規作成):**
```python
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

    def find_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """ファイルハッシュで履歴を検索（最新の1件）"""
        if not self.history_file.exists():
            return None
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                for line in reversed(list(f)):
                    record = json.loads(line.strip())
                    if record.get("file_hash") == file_hash:
                        return record
        except Exception as e:
            self.logger.warning(f"ダウンロード履歴の読み込みに失敗: {str(e)}")
        
        return None
```

**src/core/downloader.py (修正):**
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
        else:
            # 失敗理由を記録
            error_msg = f"ダウンロードに失敗しました: {save_path}"
            if not hasattr(file_info, '_last_error'):
                file_info._last_error = error_msg
            self.logger.error(error_msg)
+           # ダウンロード履歴を記録（失敗）
+           self.history.add_record(
+               url=file_info.url,
+               filename=file_info.filename,
+               file_path=save_path,
+               file_size=0,
+               file_hash=None,
+               status="failed",
+               error_message=error_msg,
+           )
```

### どう確認する
```powershell
# 1. ダウンロードを実行
python src\main.py

# 2. ダウンロード履歴を確認
Get-Content logs\download_history.jsonl | ConvertFrom-Json | Format-Table -AutoSize

# 3. 特定のURLの履歴を確認
Get-Content logs\download_history.jsonl | ConvertFrom-Json | Where-Object { $_.url -like "*example.com*" } | Format-Table -AutoSize
```

## 6. P2: 例外処理の改善（bare except の削減）

### 何を
- `src/core/downloader.py` に bare except が複数あり、原因追跡が困難

### なぜ
- bare except はすべての例外を捕捉するため、予期しない例外も握りつぶしてしまう
- 例外の種類が分からないため、デバッグが困難

### どう直す
- `except:` を `except Exception as e:` に変更し、ログに例外情報を残す
- 失敗時の戻り値（結果オブジェクト）が原因を持つようにする

**変更差分:**

**src/core/downloader.py:**
```python
# src/core/downloader.py (行361-391)
-           except:
+           except Exception as e:
+               self.logger.warning(f"ファイル読み込みエラー: {file_path} - {str(e)}")
                return False

-               except:
+               except Exception as e:
+                   self.logger.warning(f"ファイル読み込みエラー: {file_path} - {str(e)}")
                    return False

-               except:
+               except Exception as e:
+                   self.logger.warning(f"ファイル読み込みエラー: {file_path} - {str(e)}")
                    return False

-       except Exception as e:
+       except Exception as e:
+           self.logger.error(f"重複チェックエラー: {file_path} - {str(e)}", exc_info=True)
            return False
```

### どう確認する
```powershell
# 1. コードを確認（bare except が残っていないことを確認）
Get-Content src\core\downloader.py | Select-String -Pattern "except:" -Context 2

# 2. テストを実行
pytest tests/ -v

# 3. ログで例外情報が記録されていることを確認
Get-Content logs\app.log | Select-String -Pattern "例外|Exception|Error" | Select-Object -Last 20
```
