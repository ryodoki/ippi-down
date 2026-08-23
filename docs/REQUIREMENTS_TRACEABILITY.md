# 要件トレーサビリティ表

本ドキュメントは `docs/requirements.md` および（歴史文書の）`docs/archive/reports/settings_requirements.md` の機能要件（FR）を実装・テストと対応付けたものです。設定 GUI は実装済みです。旧「未実装」記述はアーカイブ側の文書を参照してください。

**凡例**
- **状態**: OK=要件を満たす / Partial=一部未対応 / NG=未対応
- **コメント**: 実装上の注意や将来拡張

---

## 1. コア機能（requirements.md）

| FR-ID | 要件 | 実装ファイル/関数 | テスト | 状態 | コメント |
|-------|------|------------------|--------|------|----------|
| FR-001 | HTML構造解析 | src/core/scraper.py (fetch_page, BeautifulSoup) | 統合テスト | OK | 検索ページ・詳細ページの解析 |
| FR-002 | ファイルリンク検出 | src/core/scraper.py (_extract_files_from_tables, extract_file_links) | 統合 | OK | PDF/Excel/Word/PostBack対応 |
| FR-003 | メタデータ抽出 | src/core/scraper.py (extract_metadata), metadata_extractor.py | 統合 | OK | 発注機関・工事名・日付等 |
| FR-004 | 条件指定・YAML保存 | config_manager, settings_dialog, config.example.yaml | test_config_model, test_settings | OK | GUI/設定ファイル対応 |
| FR-005 | 自動ダウンロード・失敗記録・サマリー | downloader.py, service.py, download_result.summarize_failures | test_application_service | OK | 失敗理由別件数出力 |
| FR-006 | 進捗表示 | gui/main_window, event_handler, ProgressEvent | GUI | OK | 進捗バー・成功/失敗/スキップ件数 |
| FR-006-1 | キャンセル・.part扱い | downloader.download_file, download_files (keep_part_on_cancel) | 手動/GUI | OK | 設定で keep/delete 選択可 |
| FR-007 | リトライ（回数・指数バックオフ・429） | utils/http_client.py (tenacity, Retry-After) | test_http_client | OK | 3回・対象外4xx |
| FR-008 | 重複スキップ（URL/ファイル名+サイズ/ハッシュ） | downloader.check_duplicate, download_history | 統合 | OK | enable_hash_check で MD5 有効化 |
| FR-009 | テンプレート文字列でファイル名生成 | core/naming.py (generate_filename, format_map) | tests/test_naming.py | OK | 空の場合は従来ロジック |
| FR-010 | 命名規則カスタマイズ・保存 | settings_dialog, config_manager, naming_rule | test_settings | OK | YAML に保存 |
| FR-011 | ファイル名重複回避（連番） | utils/file_utils.ensure_unique, naming.ensure_unique | test_file_utils | OK | _1, _2 付与 |
| FR-012 | 指定フォルダに保存 | downloader.download_files (save_dir, folder_name), service | 本表追加テスト | OK | folder_name をベース下に反映 |
| FR-013 | サブフォルダ自動生成 | downloader (use_subfolders), naming.generate_folder_name | 本表追加テスト | OK | メタデータに基づくフォルダ名 |
| FR-016 | 定期実行（間隔/時刻） | scheduler/, ScheduleConfig, croniter | test_config_model (schedule) | OK | 起動中のみ・cron対応 |
| FR-017 | 実行ログ記録 | utils/logger.py, LoggingConfig | - | OK | 開始/終了/件数 |
| FR-018 | 実行結果通知（ログ・GUI） | logger, event_handler, Notifier | - | OK | ログ＋GUI表示 |
| FR-019 | 設定YAML保存・読み込み | config_manager.load_config/save_config | test_config 相当 | OK | 起動時自動読み込み |
| FR-020 | 複数プロファイル | - | - | Partial | 将来拡張。現状は単一 config.yaml |
| FR-021 | ログ保存先・ローテーション | logger, LoggingConfig (max_bytes, backup_count) | - | OK | 10MB・5世代 |
| FR-021-1 | ログ保存先設定可能 | config.logging.file | - | OK | |
| FR-021-2 | ローテーション | RotatingFileHandler | - | OK | |
| FR-022 | エラーログ（スタックトレース） | logger.error(exc_info=True) | - | OK | |
| FR-023 | ログレベル設定 | LoggingConfig.level, config.yaml | - | OK | DEBUG/INFO/WARNING/ERROR |
| FR-024 | CLI（設定読み込み・1回実行） | src/cli/main.py (--config, --once, --dry-run) | 手動 | OK | 開発・検証用 |
| FR-025 | GUI必須 | src/main.py, gui/main_window, settings_dialog | GUI手動 | OK | 設定・進捗・ログ表示 |
| FR-026 | 実行ファイル配布（.exe） | scripts/build/build.spec, PyInstaller | 手動ビルド | OK | Windows 10/11 64bit |

---

## 2. 設定機能（settings_requirements.md）

| FR-ID | 要件 | 実装ファイル/関数 | テスト | 状態 | コメント |
|-------|------|------------------|--------|------|----------|
| FR-SET-001 | 設定ダイアログ表示 | gui/settings_dialog.py (__init__, geometry 800x700) | test_settings | OK | モーダル・中央表示 |
| FR-SET-002 | 全設定項目の表示・編集 | settings_dialog (setup_basic_tab, setup_search_tab, setup_advanced_tab) | test_settings | OK | URL/条件/保存先/命名/スケジュール/ログ |
| FR-SET-003 | 設定値の検証 | config_validator.validate_config, settings_dialog.validate_config | test_config_model | OK | URL・パス・日付・必須項目 |
| FR-SET-004 | 保存ボタンで保存 | settings_dialog.on_save, config_manager.save_config | test_settings | OK | 検証→保存→メイン更新 |
| FR-SET-005 | 開いたときに現在設定を読み込み | settings_dialog.load_config_to_ui | test_settings | OK | load_config から UI 反映 |
| FR-SET-006 | キャンセルで変更破棄 | settings_dialog.on_cancel | test_settings | OK | 未保存時確認あり |
| FR-SET-007 | デフォルトに戻す | settings_dialog.on_reset | test_settings | OK | 確認ダイアログ後リセット |
| FR-SET-008 | 設定プロファイル管理 | - | - | Partial | 将来拡張。現状は単一ファイル |
| FR-SET-009 | インポート/エクスポート | - | - | Partial | 将来拡張。YAML手動で代替可 |
| FR-SET-010 | 設定プレビュー（命名・次回実行） | - | - | Partial | 将来拡張。命名は設定欄の説明で代用 |

---

## 3. 非機能・技術要件（要約）

| ID | 要件 | 実装/状態 |
|----|------|-----------|
| NFR-001 | 大量ファイルで安定動作 | ストリーミング・履歴でメモリ配慮 |
| NFR-002 | 並列ダウンロード | 将来拡張 |
| NFR-003 | 認証情報を平文で保存しない | 対象外（ログインなし範囲） |
| NFR-005 | エラーハンドリング・タイムアウト | http_client (connect/read 設定可能) |
| NFR-006 | 1件失敗でも継続 | downloader のループで継続 |
| TR-001 | Python 3.11.x | requirements.txt, README |
| TR-006 | requirements.txt | あり |
| TR-007 | PyInstaller で exe | scripts/build/build.spec |

---

## 4. 未反映・Partial の扱い

- **FR-020 / FR-SET-008**: 複数プロファイルは未実装。README に「現状は単一設定ファイル」と明記。
- **FR-SET-009**: インポート/エクスポートは未実装。設定は config.yaml を手動コピーで代替可能。
- **FR-SET-010**: プレビューは未実装。命名規則は config.example.yaml のコメントで変数説明を記載。

---

**作成日**: 2026年2月  
**参照**: docs/requirements.md, docs/archive/reports/settings_requirements.md, README.md
