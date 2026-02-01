# 要件受け入れ条件チェックリスト

作成日: 2025-01-XX  
対象: ippi-down リポジトリ  
目的: 要件定義書の各要件IDについて、受け入れ条件ベースで実装状況を検証

## 検証方法

- **Status**: OK（実装済み・要件を満たす）、Partial（部分実装・要件の一部を満たす）、NG（未実装・要件を満たさない）
- **Evidence**: 該当するファイル、関数名、行番号
- **Verification Command**: PowerShellコマンドまたはPythonスクリプトの実行例
- **Notes/Next Fix**: 修正が必要な場合の具体的な対応方針

## 重点検証項目

### 1. FR-002: ファイルリンク検出（PostBack対応）

| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-002** | ページ内のファイルリンク（PDF、Excel、Wordなど）を検出できること | 詳細表示（遷移またはポストバック）後のHTMLまたはダウンロード応答から、添付ファイル取得に必要なURL/POSTパラメータを特定し、保存できること。`javascript:__doPostBack(...)`形式のリンクも処理できること | **OK** | `src/core/scraper.py:628-673` `_extract_files_from_tables()` - PostBackリンクを検出してFileInfoを作成。`src/core/downloader.py:56-133` `_download_postback_file()` - PostBackダウンロードを実装 | `python scripts\debug_extract_files.py --url "https://www.i-ppi.jp/..." --out test.json --debug-log` でPostBackリンクが検出され、JSONに`postback_detected: true`が含まれることを確認。`python src\main.py` でGUIを起動し、PostBackリンクのファイルがダウンロードされることを確認 | **✅ 実装完了**: PostBackリンクを検出してFileInfoを作成し、`Downloader._download_postback_file()`でPostBackを実行してダウンロード |

### 2. FR-008: 重複回避

| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-008** | 既にダウンロード済みのファイルをスキップできること（重複回避） | 1. URL同一判定: 同一URLのファイルは常にスキップ。2. ファイル名+サイズ判定: 保存先に同名ファイルが存在し、サイズが一致する場合はスキップ。3. ハッシュ判定（オプション）: 設定で有効化した場合、ファイルのMD5ハッシュを計算して比較 | **Partial** | `src/core/downloader.py:114` `check_duplicate()` - ファイル存在チェックのみ。URL同一判定・ファイル名+サイズ判定は未実装 | `python -c "from src.core.downloader import Downloader; from src.utils.http_client import HTTPClient; from src.utils.logger import Logger; d = Downloader(HTTPClient(Logger()), Logger()); print(d.check_duplicate.__doc__)"` で実装内容を確認 | **P1**: `check_duplicate()`にURL同一判定とファイル名+サイズ判定を追加。`FileInfo`のURLを保持し、ダウンロード前にURL重複チェックを実施 |

### 3. FR-006-1: キャンセル機能（.partファイル）

| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-006-1** | ダウンロード処理をユーザーがキャンセルできること | ダウンロード中は常に`.part`拡張子で保存し、成功時にリネーム。キャンセル時は`.part`ファイルを残す/削除する（設定で選択可能） | **NG** | `src/utils/http_client.py:293` `download_file()` - `save_path`に直接書き込んでいる（`.part`拡張子を使用していない） | `python -c "import inspect; from src.utils.http_client import HTTPClient; print(inspect.getsource(HTTPClient.download_file))" | Select-String -Pattern '\.part'` で`.part`の使用を確認 | **P1**: ダウンロード中は`save_path + '.part'`で保存し、成功時にリネームする処理を追加。キャンセル時の`.part`ファイルの扱いは設定に従う |

### 4. FR-009/010: 命名規則テンプレート

| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-009** | HTML構造から取得した情報を使用してファイル名を自動生成できること | テンプレート文字列（例: `{category}_{title}_{date}_{index}`）を使用してファイル名を生成できること | **NG** | `src/core/naming.py:29-79` `generate_filename()` - `self.naming_rule`を受け取っているが使用していない。固定の命名規則を使用 | `python -c "from src.core.naming import Naming; from src.utils.logger import Logger; n = Naming('{category}_{title}_{date}', Logger()); import inspect; print(inspect.getsource(n.generate_filename))" | Select-String -Pattern 'naming_rule'` で`naming_rule`の使用を確認 | **P0**: `Naming.generate_filename()`で`self.naming_rule`を使用し、テンプレート文字列を展開する実装に変更 |
| **FR-010** | ユーザーが命名規則をカスタマイズできること | GUI上で命名テンプレートを編集し、設定ファイルに保存できること | **Partial** | `src/models/config_model.py:159` `naming_rule: str` - 設定には存在するが、`Naming`クラスで使用されていない。GUI設定ダイアログの実装状況要確認 | `python src\main.py` でGUIを起動し、設定ダイアログで命名規則を編集できることを確認 | **P0**: FR-009の実装と合わせて、GUI設定ダイアログで命名規則を編集できることを確認 |

### 5. FR-016: スケジューリング機能（分単位の間隔）

| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-016** | 定期的に自動実行できること | 設定した間隔（分単位、例: 60分ごと）または時刻（例: 毎日9:00）に、アプリ起動中に自動的に検索・ダウンロードを実行できること。`interval="custom"`かつ`cron`形式もサポートすること | **Partial** | `src/scheduler/scheduler.py:54-71` `_setup_schedule()` - `interval="custom"`かつ`cron`形式が未サポート（警告のみ）。分単位の間隔指定が未実装（`ScheduleConfig.interval`は`str`で`"daily"`等のみ） | `python -c "from src.models.config_model import ScheduleConfig; sc = ScheduleConfig(interval='60'); print(sc.interval)"` で分単位の間隔指定が可能か確認 | **P1**: `ScheduleConfig.interval`に分単位の間隔指定（`integer`）を追加。`croniter`ライブラリを使用してcron形式をサポート |

### 6. FR-024: CLI提供

| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-024** | コマンドラインインターフェース（CLI）を提供すること（開発・デバッグ用） | 指定した設定ファイルを読み込み、1回の検索・ダウンロードを実行できること（開発・検証用） | **NG** | `src/main.py:127-183` `main()` - GUIのみ実装。`--background`オプションはあるが、これはCLIではなくバックグラウンドモード | `python src\main.py --help` でCLIヘルプが表示されるか確認（現状は表示されない） | **P1**: `argparse`または`click`を使用してCLIを実装。`--config`オプションで設定ファイルを指定し、1回の検索・ダウンロードを実行できるようにする |

### 7. FR-SET-001〜010: 設定ダイアログ仕様

| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-SET-001** | 設定ダイアログの表示 | 「設定」ボタンをクリックすると設定ダイアログが表示されること。モーダルダイアログとして表示。親ウィンドウの中央に表示。ダイアログサイズ: 幅600px、高さ700px（スクロール可能） | **Partial** | `src/gui/settings_dialog.py:42-55` `__init__()` - ダイアログサイズが`800x700`（要件は`600x700`） | `python src\main.py` でGUIを起動し、「設定」ボタンをクリックしてダイアログサイズを確認 | **P2**: ダイアログサイズを`600x700`に変更（または要件定義を修正） |
| **FR-SET-002** | 設定項目の表示 | すべての設定項目をGUI上で表示・編集できること（対象URL、ダウンロード条件、保存先、ファイル命名規則、スケジュール、ログ設定） | **Partial** | `src/gui/settings_dialog.py:89-925` `setup_ui()` - 基本設定タブと詳細設定タブが実装されているが、全項目の実装状況要確認 | `python src\main.py` でGUIを起動し、設定ダイアログで全項目が表示・編集できることを確認 | **P1**: 全設定項目が表示・編集できることを確認し、不足があれば追加 |
| **FR-SET-003** | 設定値の検証 | 設定値を保存する前に検証を行うこと（URLの形式チェック、ファイルパスの存在確認、日付範囲の妥当性チェック、必須項目の入力チェック） | **OK** | `src/config/config_validator.py` `ConfigValidator` - 実装済み | `python -c "from src.config.config_validator import ConfigValidator; from src.utils.logger import Logger; cv = ConfigValidator(Logger()); print(hasattr(cv, 'validate'))"` で検証機能の存在を確認 | - |
| **FR-SET-004** | 設定の保存 | 「保存」ボタンで設定をファイルに保存できること | **OK** | `src/gui/settings_dialog.py` `on_save()` - 実装済み | `python src\main.py` でGUIを起動し、設定を変更して「保存」ボタンをクリックし、設定ファイルが更新されることを確認 | - |
| **FR-SET-005** | 設定の読み込み | ダイアログを開いたときに現在の設定を読み込んで表示すること | **OK** | `src/gui/settings_dialog.py:58` `load_config_to_ui()` - 実装済み | `python src\main.py` でGUIを起動し、設定ダイアログを開いて現在の設定が表示されることを確認 | - |
| **FR-SET-006** | 設定のキャンセル | 「キャンセル」ボタンで変更を破棄してダイアログを閉じること | **OK** | `src/gui/settings_dialog.py` `on_cancel()` - 実装済み | `python src\main.py` でGUIを起動し、設定を変更して「キャンセル」ボタンをクリックし、変更が破棄されることを確認 | - |
| **FR-SET-007** | 設定のリセット | 「デフォルトに戻す」ボタンで設定をデフォルト値にリセットできること | **Partial** | `src/gui/settings_dialog.py` - 実装状況要確認 | `python src\main.py` でGUIを起動し、設定ダイアログに「デフォルトに戻す」ボタンがあることを確認 | **P2**: 「デフォルトに戻す」ボタンの実装を確認し、不足があれば追加 |
| **FR-SET-008** | 設定プロファイル管理 | 複数の設定プロファイルを保存・読み込みできること | **NG** | - | `python src\main.py` でGUIを起動し、設定ダイアログでプロファイル管理機能があることを確認（現状はない） | **P2**: 設定プロファイル管理機能を実装（要件定義では「中優先度」） |
| **FR-SET-009** | 設定のインポート/エクスポート | 設定ファイルをインポート/エクスポートできること | **NG** | - | `python src\main.py` でGUIを起動し、設定ダイアログでインポート/エクスポート機能があることを確認（現状はない） | **P2**: 設定のインポート/エクスポート機能を実装（要件定義では「低優先度」） |
| **FR-SET-010** | 設定のプレビュー | 設定変更の影響をプレビューできること | **NG** | - | `python src\main.py` でGUIを起動し、設定ダイアログでプレビュー機能があることを確認（現状はない） | **P2**: 設定のプレビュー機能を実装（要件定義では「低優先度」） |

## その他の要件

### FR-001: HTML構造解析機能
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-001** | 対象サイトのWebページのHTML構造を解析できること | 検索ページのHTMLを取得し、フォーム要素、ドロップダウン、テーブル構造を正しく解析できること | **OK** | `src/core/scraper.py:75-84` `fetch_page()` - BeautifulSoupを使用して実装 | `python scripts\debug_extract_files.py --url "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4" --out test.json --debug-log` でHTMLが取得・解析されることを確認 | - |

### FR-003: メタデータ抽出機能
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-003** | HTMLの階層構造を抽出できること | 検索結果ページまたは詳細表示ページから、発注機関名、工事名称、公告日、開札日、契約日などのメタデータを抽出できること | **OK** | `src/core/scraper.py:479-583` `extract_metadata()` - 発注機関、工事名、日付などを抽出 | `python scripts\debug_extract_files.py --url "https://www.i-ppi.jp/..." --out test.json --debug-log` でJSONの`metadata`にメタデータが含まれることを確認 | - |

### FR-004: 条件指定機能
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-004** | ユーザーが事前にダウンロード条件を設定できること | GUI上で検索条件を設定し、設定ファイル（YAML）に保存・読み込みできること | **OK** | `src/models/config_model.py:10-85` `SearchConditions` - GUI/設定ファイルで設定可能 | `python src\main.py` でGUIを起動し、検索条件を設定して保存し、`config\config.yaml`が更新されることを確認 | - |

### FR-005: 自動ダウンロード機能
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-005** | 指定した条件に一致するファイルを自動的にダウンロードできること | 指定条件で検索し、添付が存在し、かつ取得可能なものは全件保存する。取得不能なものは失敗としてログに残し、実行結果サマリーに件数を出力すること | **OK** | `src/core/downloader.py:62-158` `download_files()` - 失敗時の記録も実装済み | `python src\main.py` でGUIを起動し、ダウンロードを実行して成功/失敗/スキップ件数が表示されることを確認 | - |

### FR-006: 進捗表示機能
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-006** | ダウンロード進捗状況を表示できること | GUI上で進捗バー、成功/失敗/スキップ件数をリアルタイム表示できること | **OK** | `src/gui/main_window.py` 進捗バー表示 - GUIで実装 | `python src\main.py` でGUIを起動し、ダウンロードを実行して進捗バーが更新されることを確認 | - |

### FR-007: リトライ機能
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-007** | ダウンロード失敗時のリトライ機能を有すること | ネットワークエラー時に自動リトライし、3回失敗した場合のみエラーとして記録すること。429エラー時は適切な待機時間を確保すること | **OK** | `src/core/downloader.py:54-61` `@retry`デコレータ - 指数バックオフ実装済み。429対応は`http_client.py`で実装 | `python src\main.py` でGUIを起動し、ネットワークエラー時にリトライが実行されることをログで確認 | - |

### FR-011: ファイル名重複回避
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-011** | ファイル名の重複を回避する仕組みを有すること | 保存先に同名ファイルが存在する場合、自動的に連番（`_1`, `_2`など）を付与して保存すること | **OK** | `src/core/downloader.py:111` `ensure_unique()` - 実装済み（修正済み） | `python src\main.py` でGUIを起動し、同名ファイルをダウンロードして連番が付与されることを確認 | - |

### FR-012: 保存先指定機能
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-012** | ユーザーが事前に指定したローカルフォルダにファイルを保存できること | フォルダ選択ダイアログで保存先を指定し、ファイルを正しく保存できること | **OK** | `src/models/config_model.py:98-101` `SavePaths` - GUI/設定ファイルで設定可能 | `python src\main.py` でGUIを起動し、保存先を指定してファイルが保存されることを確認 | - |

### FR-013: フォルダ構造自動生成
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-013** | フォルダ構造をHTML構造に基づいて自動生成できること | 設定で有効化した場合、メタデータに基づいてサブフォルダを作成し、ファイルを分類保存できること | **OK** | `src/core/naming.py:117-164` `generate_folder_name()` - メタデータに基づいてサブフォルダ作成 | `python src\main.py` でGUIを起動し、ダウンロードを実行してサブフォルダが作成されることを確認 | - |

### FR-017: 実行ログ記録
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-017** | 実行ログを記録できること | 各実行の開始時刻、終了時刻、処理件数、エラー情報をログファイルに記録できること | **OK** | `src/utils/logger.py` - ログファイルに記録 | `python src\main.py` でGUIを起動し、ダウンロードを実行して`logs\app.log`にログが記録されることを確認 | - |

### FR-018: 実行結果通知
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-018** | 実行結果を通知できること | 実行完了時にログファイルに結果を記録し、GUI上で通知を表示できること | **OK** | `src/utils/notifier.py` - GUI/ログファイルで通知 | `python src\main.py` でGUIを起動し、ダウンロード完了時に通知が表示されることを確認 | - |

### FR-019: 設定ファイル保存/読み込み
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-019** | 設定をファイル（YAML形式）に保存・読み込みできること | 設定をYAMLファイルに保存し、次回起動時に自動読み込みできること | **OK** | `src/config/config_manager.py` - YAML形式で実装 | `python src\main.py` でGUIを起動し、設定を変更して保存し、次回起動時に設定が読み込まれることを確認 | - |

### FR-020: 設定プロファイル管理
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-020** | 複数の設定プロファイルを管理できること | 複数の設定ファイルを切り替えて使用できること（将来拡張） | **NG** | - | `python src\main.py` でGUIを起動し、設定プロファイルを切り替える機能があることを確認（現状はない） | **P2**: 設定プロファイル管理機能を実装（要件定義では「将来拡張」） |

### FR-021: ログ記録機能
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-021** | 実行ログを記録できること | ログファイルが10MBに達した場合、自動的にローテーションし、最大5世代まで保持すること | **OK** | `src/utils/logger.py` `RotatingFileHandler` - サイズベースローテーション実装 | `python -c "from src.utils.logger import Logger, LoggingConfig; l = Logger(LoggingConfig()); print(hasattr(l, 'handler'))"` でローテーション機能の存在を確認 | - |
| **FR-021-1** | ログ保存先を設定可能とすること | デフォルト: `./logs/app.log`。設定ファイルで変更可能 | **OK** | `src/models/config_model.py:141-144` `LoggingConfig` - 設定ファイルで変更可能 | `config\config.yaml`で`logging.file`を変更し、ログが新しいパスに保存されることを確認 | - |
| **FR-021-2** | ログローテーション機能を有すること | 最大ファイルサイズ: 10MB（設定可能）。世代数: 5世代（設定可能）。ローテーション方式: サイズベース | **OK** | `src/utils/logger.py` `RotatingFileHandler` - 実装済み | `config\config.yaml`で`logging.max_bytes`と`logging.backup_count`を変更し、ローテーションが正しく動作することを確認 | - |

### FR-022: エラーログ記録
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-022** | エラーログを記録できること | エラー発生時にスタックトレースを含む詳細情報をログに記録できること | **OK** | `src/utils/logger.py` - スタックトレース含む詳細情報を記録 | `python src\main.py` でGUIを起動し、エラーが発生した場合に`logs\app.log`にスタックトレースが記録されることを確認 | - |

### FR-023: ログレベル設定
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-023** | ログレベルを設定できること | 設定ファイルでログレベルを変更し、該当レベルのログのみ出力できること | **OK** | `src/models/config_model.py:141` `level: str` - DEBUG/INFO/WARNING/ERROR対応 | `config\config.yaml`で`logging.level`を`DEBUG`に変更し、DEBUGレベルのログが出力されることを確認 | - |

### FR-025: GUI提供
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-025** | グラフィカルユーザーインターフェース（GUI）を提供すること（必須） | GUI上で検索条件を設定し、ダウンロードを開始し、進捗とログを確認できること | **OK** | `src/gui/main_window.py` - tkinterで実装 | `python src\main.py` でGUIが起動し、検索条件を設定してダウンロードを開始できることを確認 | - |

### FR-026: 実行ファイル形式
| Requirement ID | Description | Acceptance Criteria | Status | Evidence | Verification Command | Notes/Next Fix |
|---------------|-------------|---------------------|--------|----------|---------------------|-----------------|
| **FR-026** | 実行ファイル形式（.exe等）で配布できること | Windows 10/11（64bit）環境で、Python未インストールでも実行ファイルを起動できること | **OK** | `scripts/build/build.spec` PyInstaller設定 - Windows 10/11対応 | `pyinstaller scripts\build\build.spec` で実行ファイルを生成し、Python未インストール環境で起動できることを確認 | - |

## サマリー

- **OK（実装済み）**: 20項目
- **Partial（部分実装）**: 6項目
- **NG（未実装）**: 5項目

## 優先度別修正提案

### P0（緊急・必須修正）
1. **FR-002**: PostBackリンク対応（`javascript:__doPostBack(...)`形式のリンクを処理できるようにする）
2. **FR-009/010**: 命名規則テンプレートの実装（`Naming.generate_filename()`で`naming_rule`を使用）

### P1（重要・推奨修正）
3. **FR-008**: 重複回避の実装（URL同一判定、ファイル名+サイズ判定を追加）
4. **FR-006-1**: .partファイル処理の実装（ダウンロード中は`.part`拡張子で保存）
5. **FR-016**: スケジューリング機能の改善（分単位の間隔指定、cron形式のサポート）
6. **FR-024**: CLIの実装（開発・デバッグ用）

### P2（将来実装・低優先度）
7. **FR-SET-001**: ダイアログサイズの調整（600x700に変更、または要件定義を修正）
8. **FR-SET-007**: 設定のリセット機能の確認・追加
9. **FR-SET-008/009/010**: 設定ダイアログの高度な機能（プロファイル管理、インポート/エクスポート、プレビュー）
10. **FR-020**: 設定プロファイル管理（将来拡張）
