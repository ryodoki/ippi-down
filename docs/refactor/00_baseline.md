# 00 ベースライン記録

> 記録日: 2026-02-27  
> Python: 3.11.9 / pytest: 9.0.2 / Windows 10

---

## 1. テスト実行結果

```
96 selected, 92 passed, 4 failed, 3 deselected
```

| 状態 | 件数 | 備考 |
|------|------|------|
| passed | 92 | |
| failed | 1 | `test_url_match_returns_skip_url` — 重複チェック修正に伴い更新済み |
| failed | 3 | `test_schedule_cron` — `croniter` 未インストール（既存問題） |
| deselected | 3 | `@pytest.mark.network` 等のマーカーで除外 |

> **対応**: テスト更新後は **96 selected, 93 passed, 3 failed (croniter)**。  
> croniter 系 3 件は Phase 1 で対処方針を決定する。

---

## 2. GUI 起動確認

- `python -m src.main` で tkinter GUI が起動。
- 設定画面の開閉、発注機関ドロップダウンの取得（HTTP通信あり）が動作。

---

## 3. リポジトリ構造サマリー

### 3.1 ファイル行数 Top 10

| # | ファイル | 行数 | 責務 |
|---|---------|------|------|
| 1 | `src/core/scraper.py` | 2,034 | HTTP / HTMLパース / フォーム状態 / 検索 / 詳細 / DLリンク抽出 |
| 2 | `src/gui/main_window.py` | 1,250 | メインウィンドウ全体（UI＋ロジック＋HTTP呼び出し混在） |
| 3 | `src/gui/settings_dialog.py` | 1,203 | 設定ダイアログ全体（同上） |
| 4 | `src/core/downloader.py` | 602 | ファイルDL / 重複チェック / 履歴管理 |
| 5 | `src/utils/http_client.py` | 543 | HTTP GET / POST / ファイルDL / リトライ |
| 6 | `src/app/service.py` | 382 | オーケストレーション |
| 7 | `src/config/config_manager.py` | 284 | YAML ↔ AppConfig |
| 8 | `src/core/naming.py` | 252 | ファイル名テンプレ展開 |
| 9 | `src/core/ppi_dropdowns.py` | 184 | GUI用ドロップダウン定数 |
| 10 | `src/utils/file_utils.py` | 175 | ファイルユーティリティ |

### 3.2 未使用コードディレクトリ

以下はファイルが存在するが、**メインコードから一切 import されていない**：

| ディレクトリ | ファイル | 行数合計 | 状態 |
|------------|---------|---------|------|
| `src/core/parser/` | `search_result_parser.py`, `detail_page_parser.py`, `aspnet_form_parser.py`, `models.py` | 295行 | テストのみ参照 |
| `src/core/fetcher/` | `page_fetcher.py` | 60行 | テストのみ参照 |
| `src/core/extractor/` | `metadata_extractor.py` | 49行 | テストのみ参照 |

> これらは `scraper.py` に同等機能が統合されており、重複状態。

### 3.3 依存関係

- 循環 import: **なし**
- レイヤ違反: **gui → core/scraper, core/http_client を直接呼び出している**（main_window.py, settings_dialog.py）
- `_review_pack/`: `.gitignore` で除外済み、Git 追跡なし
- 生成物の Git 追跡: **なし**（`.gitignore` で適切に管理）

### 3.4 設定ファイル

| ファイル | 用途 |
|---------|------|
| `config/config.yaml` | 実行設定（.gitignore で除外） |
| `config/config.example.yaml` | テンプレ（Git管理） |
| `pytest.ini` | テスト設定 |
| `pyrightconfig.json` | 型チェック |
| `requirements.txt` | 本番依存 |
| `requirements-dev.txt` | 開発依存 |

---

## 4. 既知の問題

1. `croniter` が requirements.txt に含まれているが未インストール → テスト 3 件失敗
2. `scraper.py` 2,034行 — 単一責務の原則に大きく違反
3. GUI → core 直接呼び出し — application 層を介していない
4. `parser/fetcher/extractor` が未使用で死んだコード状態
