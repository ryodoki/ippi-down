# 調査用スクリプト棚卸し表（debug/ および scripts/）

統合前の debug/ 配下21本と scripts/debug_extract_files.py を機能カテゴリで分類し、重複度を判定した一覧です。  
**debug/ 配下の debug_*.py は削除済みです。** 同等の調査は **scripts/investigate/investigate_i_ppi.py** のサブコマンドで行えます。

## カテゴリ凡例

- **dropdown**: 階層ドロップダウン（大→中→小→細）の value 解決・POSTBACK
- **search**: 検索フォーム送信～1ページ目結果取得
- **form**: フォームフィールド名・hidden/select/text 一覧
- **html**: HTML構造分析・dgrSearchList 等の存在確認
- **pagination**: 次ページ取得・全ページ件数集計
- **verify**: 検索条件と結果の妥当性（機関名一致・工事名ヒット）
- **scraper**: src.core.scraper 経由で同じ検索・件数確認
- **download**: ダウンロードURL・セッション・失敗原因の調査
- **count**: 工事件数・ファイル数カウント

## debug/ 配下 21 本

| スクリプト | カテゴリ | 重複度 | 入力 | 出力 | 共通処理 | ユニーク処理 |
|------------|----------|--------|------|------|----------|--------------|
| debug_cascading_dropdown.py | dropdown | 高 | 固定URL | 各段階の value/選択肢 | get_hidden, get_dropdown_value, POST | 階層ごとの追加フィールド（txtLgKikanInf2SelIndex_h 等） |
| debug_search_request.py | search | 高 | 固定URL・固定条件 | 送信データ・レスポンス概要 | 同上 | 検索ボタン送信まで全手順 |
| debug_pagination.py | pagination | 高 | 固定URL・固定条件 | 1/2ページ目テーブル行数・次ページ有無 | Session, hidden, 固定 form_data | 次ページボタン名で POST |
| debug_html_structure.py | html | 中 | 固定URL | 保存HTML・hidden/select/text/checkbox/radio/button 一覧 | Session, get | フォーム構造の分類出力 |
| debug_field_names.py | form | 中 | 固定URL | フィールド名一覧 | Session, get | フィールド名のみ |
| debug_form_fields.py | form | 中 | 固定URL | フォームフィールド詳細 | Session, get | GUI との差分検証 |
| debug_verify_results.py | verify | 高 | 固定条件 | 結果行の機関名・工事名一致確認 | get_hidden, get_dropdown, 検索送信 | 東北地方整備局件数・他機関リスト |
| debug_search_verification.py | verify | 高 | 固定条件 | 工事名フィルタ検証・結果件数 | Session, 固定 form_data（tbxKojiNm 等） | 検索実行と結果テーブル確認 |
| debug_search_results.py | search | 高 | 固定条件 | 結果1ページ目の工事名一覧 | SimpleHTTPClient, 固定 form_data | 結果行のテキスト表示 |
| debug_count_koji.py | count | 高 | 固定条件 | 全ページ工事件数 | get_hidden, get_dropdown, get_all_form_inputs | 次ページループで累計 |
| debug_full_search.py | pagination | 高 | 固定条件 | 全ページ取得・件数 | Session, 固定 form_data, 次ページ POST | 全ページループ |
| debug_scraper_direct.py | scraper | 中 | 固定条件 | Scraper.submit_search_form 結果・結果表サマリー | src Scraper, SearchConditions | GUI 同経路の再現 |
| debug_scraper_counts.py | scraper/count | 中 | 固定条件 | 工事件数（Scraper 経由） | 同上 | 件数カウント |
| debug_scraper_full.py | scraper | 中 | 固定条件 | 全ページ Scraper 経由 | 同上 + _get_next_page | 全ページ取得 |
| debug_dropdown_issue.py | dropdown | 高 | 固定URL | ドロップダウン選択肢・value | get_hidden, get_dropdown, POST | 問題調査用の詳細出力 |
| debug_comprehensive.py | 複合 | 中 | 固定URL | 総合調査（ブラウザと requests の差） | DebugHTTPClient, 各種取得 | 複数観点の比較 |
| debug_js_response.py | dropdown | 中 | 固定URL | JS で動的追加される選択肢 | Session, get | setListItemSub 等の確認 |
| debug_download_failure.py | download | 低 | URL | ダウンロード失敗原因（HTML返却等） | Session, get | Content-Type/Content-Disposition 確認 |
| debug_download_session.py | download | 低 | 固定 | GUI 同経路でダウンロード可否 | src 経由 | セッション状態 |
| debug_download_url.py | download | 低 | URL | ダウンロード URL 問題 | Session, BeautifulSoup | URL 解決・リダイレクト |
| debug_file_count.py | count | 中 | 固定 | ファイル数重複問題 | src 経由 | ファイル数集計 |

## scripts/ の調査系

| スクリプト | カテゴリ | 入力 | 出力 | 備考 |
|------------|----------|------|------|------|
| scripts/investigate/debug_extract_files.py | extract-files | --url（詳細ページURL）, --out | JSON（ファイル一覧） | investigate_i_ppi.py extract-files のラッパー。 |

## 共通処理の重複（統合対象）

- **get_all_hidden_inputs(soup)** … 全 debug_*.py の多くで同一実装が重複
- **get_dropdown_value_from_text(soup, name, text)** … 検索条件送信系で重複
- **POSTBACK 送信** … form_data = hidden + __EVENTTARGET + 追加フィールドで POST
- **固定検索条件** … 国の機関→国土交通省→東北地方整備局、工事名=トンネル が多数でハードコード

## 統合後の対応

| 旧スクリプト群 | investigate_i_ppi.py サブコマンド |
|----------------|-----------------------------------|
| debug_search_request, debug_search_results, debug_scraper_direct | **search**, **scraper** |
| debug_pagination, debug_full_search, debug_count_koji, debug_scraper_full | **paginate** |
| debug_verify_results, debug_search_verification | **verify** |
| debug_html_structure, debug_field_names, debug_form_fields | **html** |
| debug_cascading_dropdown, debug_dropdown_issue, debug_js_response | **search**（引数で階層指定）＋ **html** |
| scripts/debug_extract_files.py | **extract-files** |

download 系（debug_download_*）は調査ツールでは再現範囲が限られるため、必要時は Playwright 用の scripts/dev/test_download_with_playwright.py を利用する方針とする。

---

**作成日**: 2026年2月  
**参照**: scripts/investigate/investigate_i_ppi.py, docs/INVESTIGATION_TOOL.md
