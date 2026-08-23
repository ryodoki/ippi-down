# 要件ギャップレポート（FR-001〜FR-026）

docs/requirements.md に基づく機能要件と実装・テストの突合結果。状態は OK/Partial/NG。

| FR-ID | 要件 | 実装ファイル/関数 | テスト | 状態 | コメント（根拠） |
|-------|------|-------------------|--------|------|------------------|
| FR-001 | HTML構造解析 | src/core/scraper.py (fetch_page, BeautifulSoup) | 統合 | OK | 検索・詳細ページの解析 |
| FR-002 | ファイルリンク検出 | scraper (_extract_files_from_tables, extract_file_links) | 統合 | OK | PDF/Excel/Word/PostBack対応 |
| FR-003 | メタデータ抽出 | scraper.extract_metadata, metadata_extractor | 統合 | OK | 発注機関・工事名・日付 |
| FR-004 | 条件指定・YAML保存 | config_manager, settings_dialog | test_config_model, test_settings | OK | GUI/設定ファイル対応 |
| FR-005 | 自動ダウンロード・失敗記録・サマリー | downloader, service, download_result.summarize_failures | test_application_service | OK | 失敗理由別件数出力 |
| FR-006 | 進捗表示 | gui/main_window, event_handler, ProgressEvent | GUI | OK | 進捗バー・成功/失敗/スキップ |
| FR-006-1 | キャンセル・.part扱い | downloader (keep_part_on_cancel) | 手動 | OK | 設定で keep/delete |
| FR-007 | リトライ（回数・指数バックオフ・429） | utils/http_client (tenacity, Retry-After) | test_http_client | OK | 3回・対象外4xx |
| FR-008 | 重複スキップ（URL/同名+サイズ/ハッシュ） | downloader.check_duplicate, download_history | test_downloader | OK | スキップ理由をタスクに記録するよう整備済み |
| FR-009 | テンプレート文字列でファイル名生成 | core/naming.py (generate_filename, format_map) | test_naming | OK | 欠損値は "unknown"、ext 対応 |
| FR-010 | 命名規則カスタマイズ・保存 | settings_dialog, config_manager, naming_rule | test_settings | OK | YAML に保存 |
| FR-011 | ファイル名重複回避（連番） | file_utils.ensure_unique, naming.ensure_unique | test_file_utils | OK | _1, _2 付与 |
| FR-012 | 指定フォルダに保存 | downloader (save_dir, folder_name), service | test_downloader | OK | folder_name をベース下に反映 |
| FR-013 | サブフォルダ自動生成 | downloader (use_subfolders), naming.generate_folder_name | test_downloader | OK | メタデータに基づくフォルダ名 |
| FR-016 | 定期実行（間隔/時刻/cron） | scheduler/, ScheduleConfig, croniter | test_config_model, test_schedule_cron | OK | 起動中のみ・croniter で cron 対応 |
| FR-017 | 実行ログ記録 | utils/logger.py, LoggingConfig | - | OK | 開始/終了/件数 |
| FR-018 | 実行結果通知（ログ・GUI） | logger, event_handler, Notifier | - | OK | ログ＋GUI表示 |
| FR-019 | 設定YAML保存・読み込み | config_manager.load_config/save_config | - | OK | 起動時自動読み込み |
| FR-020 | 複数プロファイル | - | - | Partial | 将来拡張。単一 config.yaml |
| FR-021 | ログ保存先・ローテーション | LoggingConfig (max_bytes, backup_count) | - | OK | 10MB・5世代 |
| FR-022 | エラーログ（スタックトレース） | logger.error(exc_info=True) | - | OK | |
| FR-023 | ログレベル設定 | LoggingConfig.level | - | OK | DEBUG/INFO/WARNING/ERROR |
| FR-024 | CLI（設定・1回実行） | src/cli/main.py (--config, --once, --dry-run) | 手動 | OK | 開発・検証用 |
| FR-025 | GUI必須 | src/main.py, gui/main_window, settings_dialog | GUI手動 | OK | 設定・進捗・ログ表示 |
| FR-026 | 実行ファイル（.exe）配布 | scripts/build/build.spec, PyInstaller | 手動ビルド | OK | Windows 10/11 64bit |

## 修正済み・対応方針

- **FR-009/FR-010**: テンプレートの欠損キーを空文字ではなく "unknown" に統一。プレースホルダ {ext} をコンテキストに追加。
- **FR-008**: check_duplicate の戻り値を (bool, Optional[str]) とし、スキップ時に "url" / "filename_size" / "hash" を DownloadTask に記録。
- **FR-016**: cron は croniter で実装済み。次回実行時刻の算出と不正 cron 検出のテストを追加。

## Partial の扱い

- FR-020（複数プロファイル）: 要件上「将来拡張」のため Partial のまま。README に現状を明記。

---

**作成日**: 2026年2月  
**参照**: docs/requirements.md, docs/REQUIREMENTS_TRACEABILITY.md
