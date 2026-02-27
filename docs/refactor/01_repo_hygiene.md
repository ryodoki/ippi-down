# 01 リポジトリ衛生 (Phase 1)

> 実施日: 2026-02-27

---

## 実施内容

### 1. 未使用モジュールの削除

| 削除対象 | 行数 | 理由 |
|---------|------|------|
| `src/core/parser/` (4ファイル) | 295行 | scraper.py に同等機能が統合済み。テストのみ参照。 |
| `src/core/fetcher/` (1ファイル) | 60行 | 同上 |
| `src/core/extractor/` (1ファイル) | 49行 | 同上 |

**合計 404行の死コード削除**

### 2. テスト更新

| テストファイル | 変更 |
|-------------|------|
| `tests/test_phase_b.py` | parser/fetcher/extractor の5テストを削除、プレースホルダに置換 |
| `tests/test_integration.py` | `test_page_fetcher_integration`, `test_parser_integration` を削除 |
| `tests/test_downloader.py` | `check_duplicate` の物理ファイル存在チェック追加に伴いテスト更新 |
| `tests/test_schedule_cron.py` | `pytest.importorskip("croniter")` 追加で未インストール時スキップ |

### 3. Git 追跡から生成物を除去

| ファイル | 対応 |
|---------|------|
| `debug/debug_html_fields.json` | `git rm --cached` （ファイルは残る、.gitignore でカバー済み） |
| `debug/debug_search_page.html` | 同上 |

### 4. テスト結果

```
89 passed, 1 skipped (croniter), 3 deselected (network marker)
```
