# 02 scraper 分割設計 (Phase 2)

> 実施日: 2026-02-27

---

## 概要

`src/core/scraper.py`（2,034行）をファサードパターンで分割。
ロジックを `src/infrastructure/ppi/` 配下の5モジュールに委譲。

## 新モジュール構成

| モジュール | 責務 | 行数 |
|-----------|------|------|
| `infrastructure/ppi/html.py` | encoding判定, BeautifulSoup生成, URL正規化 | ~40行 |
| `infrastructure/ppi/forms.py` | hidden input収集, 全フォーム入力取得, POSTBACK実行 | ~120行 |
| `infrastructure/ppi/dropdowns.py` | 階層ドロップダウン取得（大/中/小/細分類, 地区/都道府県/市町村） | ~400行 |
| `infrastructure/ppi/detail.py` | 詳細ページ解析, テーブルファイル抽出, UserEntry_Download.aspx対応 | ~350行 |
| `infrastructure/ppi/search.py` | 検索フォーム送信, ページネーション, 検索結果からのファイルリンク抽出 | ~400行 |

## 旧→新 対応表

| 旧メソッド | 新モジュール.関数 |
|-----------|-----------------|
| `_set_response_encoding` | `html.set_response_encoding` |
| `_parse_response_to_soup` | `html.parse_response_to_soup` |
| `_normalize_search_url` | `html.normalize_search_url` |
| `_get_all_hidden_inputs` | `forms.get_all_hidden_inputs` |
| `_get_all_form_inputs` | `forms.get_all_form_inputs` |
| `_do_postback` | `forms.do_postback` |
| `_set_chubunrui_select_index` | `forms.set_chubunrui_select_index` |
| `get_dropdown_options` | `dropdowns.fetch_dropdown_options` |
| `get_hachu_daibunrui_options` | `dropdowns.fetch_hachu_daibunrui` |
| `get_hachu_chubunrui_options` | `dropdowns.fetch_hachu_chubunrui` |
| `get_hachu_shoubunrui_options` | `dropdowns.fetch_hachu_shoubunrui` |
| `get_hachu_saibunrui_options` | `dropdowns.fetch_hachu_saibunrui` |
| `get_koji_prefecture_options` | `dropdowns.fetch_koji_prefecture` |
| `get_koji_city_options` | `dropdowns.fetch_koji_city` |
| `extract_file_links` | `detail.extract_file_links` |
| `extract_metadata` | `detail.extract_metadata` |
| `_extract_files_from_tables` | `detail.extract_files_from_tables` |
| `submit_search_form` | `search.submit_search_form` |
| `_build_search_form_data` | `search.build_search_form_data` |
| `extract_file_links_from_search_results` | `search.extract_file_links_from_search_results` |

## scraper.py ファサード

`Scraper` クラスは約200行の薄いラッパーとして残し、全メソッドを新モジュールに委譲。
外部コード（`service.py`, `main_window.py`）からの `import` パスは変更なし。

## テスト結果

```
89 passed, 1 skipped, 3 deselected
```
