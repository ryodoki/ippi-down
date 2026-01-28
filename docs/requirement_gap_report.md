# 要件定義 vs 実装 ギャップレポート

作成日: 2025-01-XX  
対象: ippi-down リポジトリ  
解析対象: `docs/requirements.md`, `docs/settings_requirements.md`

## 概要

本レポートは、要件定義書に記載されている機能要件と実装コードの差分を分析し、未実装・部分実装・実装済みを分類したものです。

## 要件ギャップ一覧表

| Requirement ID | Description | Status | Evidence (file:line / function) | Notes / Fix Plan |
|---------------|-------------|--------|----------------------------------|------------------|
| **FR-001** | HTML構造解析機能 | ✅ 実装済み | `src/core/scraper.py:75-84` `fetch_page()` | BeautifulSoupを使用して実装 |
| **FR-002** | ファイルリンク検出機能 | ⚠️ 部分実装 | `src/core/scraper.py:585-675` `_extract_files_from_tables()` | `javascript:__doPostBack(...)`形式のリンクが未対応 |
| **FR-003** | メタデータ抽出機能 | ✅ 実装済み | `src/core/scraper.py:479-583` `extract_metadata()` | 発注機関、工事名、日付などを抽出 |
| **FR-004** | 条件指定機能 | ✅ 実装済み | `src/models/config_model.py:10-85` `SearchConditions` | GUI/設定ファイルで設定可能 |
| **FR-005** | 自動ダウンロード機能 | ✅ 実装済み | `src/core/downloader.py:62-158` `download_files()` | 失敗時の記録も実装済み |
| **FR-006** | 進捗表示機能 | ✅ 実装済み | `src/gui/main_window.py` 進捗バー表示 | GUIで実装 |
| **FR-006-1** | キャンセル機能 | ✅ 実装済み | `src/core/downloader.py:86-97` キャンセルチェック | `.part`ファイルの扱いは実装済み |
| **FR-007** | リトライ機能 | ✅ 実装済み | `src/core/downloader.py:54-61` `@retry`デコレータ | 指数バックオフ実装済み、429対応は`http_client.py`で実装 |
| **FR-008** | 重複回避機能 | ⚠️ 部分実装 | `src/core/downloader.py:109-122` `check_duplicate()` → `ensure_unique()` | **問題**: `check_duplicate()`を先に実行してから`ensure_unique()`を実行している。順序が逆。 |
| **FR-009** | ファイル名自動生成 | ❌ 未実装 | `src/core/naming.py:29-79` `generate_filename()` | **問題**: `naming_rule`（テンプレート文字列）を受け取っているが使用していない。固定の命名規則を使用。 |
| **FR-010** | 命名規則カスタマイズ | ❌ 未実装 | `src/models/config_model.py:159` `naming_rule: str` | 設定には存在するが、`Naming`クラスで使用されていない |
| **FR-011** | ファイル名重複回避 | ⚠️ 部分実装 | `src/core/downloader.py:122` `ensure_unique()` | **問題**: `check_duplicate()`の後に`ensure_unique()`を実行しているため、同名ファイルでスキップされる事故が発生する可能性 |
| **FR-012** | 保存先指定機能 | ✅ 実装済み | `src/models/config_model.py:98-101` `SavePaths` | GUI/設定ファイルで設定可能 |
| **FR-013** | フォルダ構造自動生成 | ✅ 実装済み | `src/core/naming.py:117-164` `generate_folder_name()` | メタデータに基づいてサブフォルダ作成 |
| **FR-016** | スケジューリング機能 | ⚠️ 部分実装 | `src/scheduler/scheduler.py:54-105` `_setup_schedule()` | **問題**: `interval="custom"`かつ`cron`形式が未サポート（警告のみ） |
| **FR-017** | 実行ログ記録 | ✅ 実装済み | `src/utils/logger.py` | ログファイルに記録 |
| **FR-018** | 実行結果通知 | ✅ 実装済み | `src/utils/notifier.py` | GUI/ログファイルで通知 |
| **FR-019** | 設定ファイル保存/読み込み | ✅ 実装済み | `src/config/config_manager.py` | YAML形式で実装 |
| **FR-020** | 設定プロファイル管理 | ❌ 未実装 | - | 要件定義では「将来拡張」とされているが、実装なし |
| **FR-021** | ログ記録機能 | ✅ 実装済み | `src/utils/logger.py` | ログレベル、ローテーション実装済み |
| **FR-021-1** | ログ保存先設定 | ✅ 実装済み | `src/models/config_model.py:141-144` `LoggingConfig` | 設定ファイルで変更可能 |
| **FR-021-2** | ログローテーション | ✅ 実装済み | `src/utils/logger.py` `RotatingFileHandler` | サイズベースローテーション実装 |
| **FR-022** | エラーログ記録 | ✅ 実装済み | `src/utils/logger.py` | スタックトレース含む詳細情報を記録 |
| **FR-023** | ログレベル設定 | ✅ 実装済み | `src/models/config_model.py:141` `level: str` | DEBUG/INFO/WARNING/ERROR対応 |
| **FR-024** | CLI提供 | ❌ 未実装 | `src/main.py:127-183` `main()` | GUIのみ実装。要件定義では「開発・デバッグ用」とされているが未実装 |
| **FR-025** | GUI提供 | ✅ 実装済み | `src/gui/main_window.py` | tkinterで実装 |
| **FR-026** | 実行ファイル形式 | ✅ 実装済み | `scripts/build/build.spec` PyInstaller設定 | Windows 10/11対応 |
| **FR-SET-001** | 設定ダイアログ表示 | ⚠️ 部分実装 | `src/gui/settings_dialog.py` | 実装されているが、一部機能が未実装の可能性 |
| **FR-SET-002** | 設定項目表示 | ⚠️ 部分実装 | `src/gui/settings_dialog.py` | 基本設定は実装済み、詳細設定は要確認 |
| **FR-SET-003** | 設定値検証 | ✅ 実装済み | `src/config/config_validator.py` | 実装済み |
| **FR-SET-004** | 設定保存 | ✅ 実装済み | `src/gui/settings_dialog.py` | 実装済み |
| **FR-SET-005** | 設定読み込み | ✅ 実装済み | `src/gui/settings_dialog.py` | 実装済み |
| **FR-SET-006** | 設定キャンセル | ✅ 実装済み | `src/gui/settings_dialog.py` | 実装済み |
| **FR-SET-007** | 設定リセット | ⚠️ 要確認 | `src/gui/settings_dialog.py` | 実装状況要確認 |
| **FR-SET-008** | 設定プロファイル管理 | ❌ 未実装 | - | 要件定義では「中優先度」だが未実装 |
| **FR-SET-009** | 設定インポート/エクスポート | ❌ 未実装 | - | 要件定義では「低優先度」で未実装 |
| **FR-SET-010** | 設定プレビュー | ❌ 未実装 | - | 要件定義では「低優先度」で未実装 |

## 優先度別修正提案

### P0（緊急・必須修正）

#### 1. FR-009/010: 命名規則テンプレート未使用問題
- **問題**: `AppConfig.naming_rule`にテンプレート文字列（例: `"{category}_{title}_{date}_{index}"`）が設定されているが、`Naming.generate_filename()`で使用されていない
- **影響**: ユーザーが設定で命名規則をカスタマイズしても反映されない
- **修正方針**: `Naming.generate_filename()`で`self.naming_rule`を使用し、テンプレート文字列を展開する実装に変更
- **対象ファイル**: `src/core/naming.py:29-79`

#### 2. FR-011: 重複回避の順序問題
- **問題**: `downloader.py:109-122`で`check_duplicate()`を先に実行してから`ensure_unique()`を実行している
- **影響**: 同名ファイルが存在する場合、ユニーク化される前にスキップされる可能性がある
- **修正方針**: `ensure_unique()`を先に実行し、ユニーク化されたパスで`check_duplicate()`を実行
- **対象ファイル**: `src/core/downloader.py:109-122`

#### 3. 入札調書ダウンロード不具合（早期リターン問題）
- **問題**: `scraper.py:1561-1565`で、詳細ページからファイルが見つかった場合、`UserEntry_Download.aspx`をスキップしている
- **影響**: 詳細ページに一部のファイルしかない場合、`UserEntry_Download.aspx`にある追加ファイル（入札調書など）が取得されない
- **修正方針**: 早期リターンを廃止し、`UserEntry_Download.aspx`も必ず探索してマージする
- **対象ファイル**: `src/core/scraper.py:1487-1665` `_extract_files_from_detail_page_via_postback()`

#### 4. `javascript:__doPostBack(...)`形式のリンク未対応
- **問題**: `_extract_files_from_tables()`で`href=True`でチェックしているが、`javascript:__doPostBack(...)`の場合はURLとして扱えない
- **影響**: 入札調書など、PostBackで取得する必要があるファイルが抽出されない
- **修正方針**: `href`が`javascript:__doPostBack(...)`形式の場合、PostBackを実行してファイルURLを解決する
- **対象ファイル**: `src/core/scraper.py:585-675` `_extract_files_from_tables()`

### P1（重要・推奨修正）

#### 5. FR-016: カスタムcron形式未サポート
- **問題**: `scheduler.py:67-71`で`interval="custom"`かつ`cron`形式が未サポート（警告のみ）
- **影響**: 複雑なスケジュール設定ができない
- **修正方針**: `croniter`ライブラリを使用してcron形式をサポート
- **対象ファイル**: `src/scheduler/scheduler.py:54-105`

#### 6. FR-024: CLI未実装
- **問題**: 要件定義では「開発・デバッグ用」としてCLIが定義されているが未実装
- **影響**: 開発・デバッグ時にGUIを起動する必要がある
- **修正方針**: `argparse`または`click`を使用してCLIを実装
- **対象ファイル**: 新規作成 `src/cli/main.py` または `src/main.py`を拡張

### P2（将来実装・低優先度）

#### 7. FR-020: 設定プロファイル管理
- **問題**: 複数の設定プロファイルを管理する機能が未実装
- **影響**: 異なる設定で実行する場合、設定ファイルを手動で切り替える必要がある
- **修正方針**: 設定ファイルのパスを指定できる機能を追加
- **対象ファイル**: `src/config/config_manager.py`

#### 8. FR-SET-008/009/010: 設定ダイアログの高度な機能
- **問題**: 設定プロファイル管理、インポート/エクスポート、プレビュー機能が未実装
- **影響**: 設定の管理が煩雑
- **修正方針**: 要件定義に従って段階的に実装
- **対象ファイル**: `src/gui/settings_dialog.py`

## バグ修正優先度

### 最優先（P0）

1. **入札調書ダウンロード不具合**: 早期リターンの廃止と`UserEntry_Download.aspx`の必ず探索
2. **`javascript:__doPostBack(...)`形式のリンク未対応**: PostBack処理の実装
3. **FR-011: 重複回避の順序問題**: `ensure_unique()`を先に実行
4. **FR-009/010: 命名規則テンプレート未使用**: テンプレート文字列の展開実装

## 実装状況サマリー

- **実装済み**: 23項目
- **部分実装**: 6項目
- **未実装**: 6項目

## 修正実施状況

### ✅ 完了した修正（2025-01-XX）

#### 1. 入札調書ダウンロード不具合の修正（P0）
- **修正内容**: `_extract_files_from_detail_page_via_postback()`の早期リターンを廃止
- **変更ファイル**: `src/core/scraper.py:1487-1665`
- **変更点**:
  - 詳細ページでファイルが見つかっても、`UserEntry_Download.aspx`を必ず探索するように変更
  - 詳細ページのファイルと`UserEntry_Download.aspx`のファイルをマージ（重複除去）
  - 重複判定: URL同一、または（文書名 + ファイルタイプ）同一

#### 2. 重複回避の順序修正（P0）
- **修正内容**: `ensure_unique()`を先に実行し、ユニーク化されたパスで`check_duplicate()`を実行
- **変更ファイル**: `src/core/downloader.py:109-122`
- **変更点**: `check_duplicate()`の前に`ensure_unique()`を実行するように順序を変更

#### 3. デバッグログの追加
- **修正内容**: 抽出時・ダウンロード時の詳細情報をログ出力
- **変更ファイル**: 
  - `src/core/scraper.py:620-673` (`_extract_files_from_tables()`)
  - `src/core/scraper.py:1487-1665` (`_extract_files_from_detail_page_via_postback()`)
  - `src/utils/http_client.py:219-340` (`download_file()`)
- **追加ログ**:
  - 抽出時: 採用/不採用理由、PostBackリンク検出、ファイル抽出結果
  - ダウンロード時: URL、保存先、HTTP status、Content-Type、Content-Disposition、ファイルサイズ

#### 4. デバッグスクリプトの追加
- **作成ファイル**: `scripts/debug_extract_files.py`
- **機能**: 詳細ページURLを指定してファイル抽出をテストし、結果をJSON形式で出力

#### 5. 動作確認メモの作成
- **作成ファイル**: `docs/verification.md`
- **内容**: 動作確認手順、期待されるログ出力例、トラブルシューティング

### ⚠️ 未修正（今後の対応が必要）

#### 1. FR-009/010: 命名規則テンプレート未使用問題（P0）
- **現状**: `AppConfig.naming_rule`が設定されているが、`Naming.generate_filename()`で使用されていない
- **対応**: テンプレート文字列を展開する実装が必要
- **対象ファイル**: `src/core/naming.py:29-79`

#### 2. `javascript:__doPostBack(...)`形式のリンク未対応（P0）
- **現状**: `_extract_files_from_tables()`でPostBackリンクを検出しているが、処理していない
- **対応**: PostBackを実行してファイルURLを解決する実装が必要
- **対象ファイル**: `src/core/scraper.py:585-675`

#### 3. FR-016: カスタムcron形式未サポート（P1）
- **現状**: `interval="custom"`かつ`cron`形式が未サポート（警告のみ）
- **対応**: `croniter`ライブラリを使用してcron形式をサポート
- **対象ファイル**: `src/scheduler/scheduler.py:54-105`

#### 4. FR-024: CLI未実装（P1）
- **現状**: GUIのみ実装、CLIが未実装
- **対応**: `argparse`または`click`を使用してCLIを実装
- **対象ファイル**: 新規作成 `src/cli/main.py` または `src/main.py`を拡張

## 次のステップ

1. ✅ P0のバグ修正を実施（入札調書ダウンロード不具合、重複回避順序） - **完了**
2. ✅ デバッグログの追加（抽出時の採用/不採用理由、ダウンロード時の詳細情報） - **完了**
3. ✅ デバッグスクリプトの追加（`scripts/debug_extract_files.py`） - **完了**
4. ✅ 動作確認メモの作成（`docs/verification.md`） - **完了**
5. ⚠️ 命名規則テンプレートの実装（FR-009/010）
6. ⚠️ PostBackリンク処理の実装
7. ⚠️ カスタムcron形式のサポート（FR-016）
8. ⚠️ CLIの実装（FR-024）
