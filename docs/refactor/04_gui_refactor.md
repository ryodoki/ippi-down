# Phase 4: GUI リファクタリング

## 概要

GUI 巨大ファイル（main_window.py / settings_dialog.py）を分割し、
presentation 層から core/scraper への直接依存を排除した。

## 実施内容

### Step 1: レイヤ違反の解消 — LookupService 導入

GUI が `core/scraper.Scraper` を直接呼んで階層ドロップダウンを取得していた問題を修正。

| 変更前 | 変更後 |
|--------|--------|
| `GUI → core/scraper.Scraper` | `GUI → app/lookup_service.LookupService → infrastructure/ppi/dropdowns` |

**新規ファイル**: `src/app/lookup_service.py` (71行)

- `LookupService` クラス: HTTPClient と search_url を保持し、dropdowns 関数を薄くラップ
- `get_hachu_daibunrui()`, `get_hachu_chubunrui()`, `get_hachu_shoubunrui()`, `get_hachu_saibunrui()`
- `get_koji_prefecture()`, `get_koji_city()`

### Step 2: main_window.py の分割

| ファイル | 変更前 | 変更後 |
|----------|--------|--------|
| `src/gui/main_window.py` | 1252行 | **287行** |
| `src/gui/widgets/search_conditions_frame.py` | — | **766行** (新規) |

**SearchConditionsFrame** に移動した責務:
- 全検索条件ウィジェットの構築 (`_build_widgets`)
- 発注機関4階層ドロップダウンのイベントハンドラ・非同期ロード・復元
- 工事場所3階層ドロップダウンのイベントハンドラ・非同期ロード・復元
- `load_from_config(sc)` — config → UI 反映
- `write_to_config(sc)` — UI → config 書き戻し
- `load_daibunrui_options()` — 大分類オプション非同期ロード

**MainWindow** に残った責務:
- レイアウト定義（ツールバー、スクロールキャンバス、進捗バー、ログ）
- ダウンロード開始/キャンセル/スレッド管理
- 設定ダイアログの表示
- ログ/検索条件クリア

### Step 3: settings_dialog.py の分割

| ファイル | 変更前 | 変更後 |
|----------|--------|--------|
| `src/gui/settings_dialog.py` | 1204行 | **520行** |
| `src/gui/widgets/settings_search_tab.py` | — | **592行** (新規) |

**SettingsSearchTab** に移動した責務:
- 検索条件タブ全ウィジェットの構築
- ドロップダウンハンドラ（大分類変更→中分類ロード、地方→都道府県→市町村）
- `load_from_config(sc)` — config → UI 反映
- `write_to_search_conditions(existing_sc)` — UI → SearchConditions 変換
- `load_daibunrui_options()` — 大分類オプション非同期ロード

**SettingsDialog** に残った責務:
- ダイアログ構造（Notebook 3タブ）
- 基本設定タブ（URL、保存先、命名規則、スケジュール）
- 詳細設定タブ（ログ設定）
- 保存/キャンセル/リセット

## ファイル構成

```
src/
├── app/
│   └── lookup_service.py          ← NEW (Phase 4)
├── gui/
│   ├── main_window.py             ← 1252行→287行
│   ├── settings_dialog.py         ← 1204行→520行
│   ├── event_handler.py           ← 変更なし
│   └── widgets/
│       ├── __init__.py            ← NEW
│       ├── search_conditions_frame.py  ← NEW (766行)
│       └── settings_search_tab.py      ← NEW (592行)
```

## import ルール確認

| 方向 | 許可 |
|------|------|
| `gui/main_window` → `gui/widgets/*` | ✅ |
| `gui/main_window` → `app/lookup_service` | ✅ |
| `gui/widgets/*` → `app/lookup_service` | ✅（コールバック経由） |
| `gui/*` → `core/scraper` | ❌ **排除済み** |
| `gui/*` → `infrastructure/*` | ❌（LookupService 経由） |

## テスト結果

- `python -m pytest`: 98 passed, 3 deselected ✅
- GUI 起動: 確認待ち
