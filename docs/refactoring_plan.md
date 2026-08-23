# 実務運用品質向上のための修正計画

## 0. 現状把握

### 0.1 リポジトリ構成とエントリポイント

```
ippi-down/
├── src/
│   ├── main.py              # エントリポイント（GUI/バックグラウンドモード）
│   ├── app/
│   │   └── service.py       # ApplicationService（GUI/CLI共通サービス）
│   ├── gui/
│   │   └── main_window.py   # GUIメインウィンドウ
│   ├── core/
│   │   ├── scraper.py      # HTML解析・スクレイピング
│   │   ├── downloader.py   # ファイルダウンロード
│   │   ├── filter.py       # 条件フィルタリング
│   │   └── naming.py       # ファイル命名
│   ├── scheduler/
│   │   └── scheduler.py    # 定期実行管理
│   ├── config/
│   │   └── config_manager.py # 設定ファイル管理
│   └── utils/
│       ├── logger.py       # ログ管理
│       └── http_client.py  # HTTPクライアント
├── config/
│   ├── config.yaml         # 設定ファイル（実運用）
│   └── config.example.yaml # 設定ファイル例
└── scripts/
    └── debug_extract_files.py # デバッグスクリプト
```

### 0.2 エントリポイントと設定読み込み経路

**GUIモード（デフォルト）:**
```
src/main.py::main()
  → ConfigManager.load_config()
  → AppConfig（YAMLから読み込み）
  → MainWindow（GUI起動）
  → ApplicationService.run()
```

**バックグラウンドモード:**
```
src/main.py::main() (--background または PPI_BACKGROUND_MODE=true)
  → ConfigManager.load_config()
  → AppConfig（YAMLから読み込み）
  → Scheduler.start()（スケジュール有効時）
  → ApplicationService.run()
```

**設定読み込み経路:**
```
ConfigManager.load_config()
  → config/config.yaml を読み込み
  → AppConfig に変換
  → 各コンポーネントに渡される
```

### 0.3 存在するが使われていない設定項目

1. **naming_rule** (`AppConfig.naming_rule`)
   - 設定: `"{category}_{title}_{date}_{index}"`
   - 実装: `Naming.generate_filename()` で未使用（固定ロジックを使用）

2. **date_range** (`DownloadConditions.date_range`)
   - 設定: `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`
   - 実装: `Filter.match_date_range()` が `pass` のまま（実装未完了）

3. **custom cron** (`ScheduleConfig.interval="custom"`, `ScheduleConfig.cron`)
   - 設定: cron形式文字列
   - 実装: `Scheduler._setup_schedule()` で警告のみ（未実装）

4. **keywords** (`DownloadConditions.keywords`)
   - 設定: キーワードリスト
   - 実装: `Filter.match_keywords()` で実装済み（使用されている）

## 1. 優先度別修正計画

### P0（最優先・必須修正）

1. **配布/レビューZIP作成スクリプトの不具合修正**
   - `pack_for_review.ps1`: `config.example.yaml` が `IncludeDirs` に含まれている（ファイルなので `IncludeFiles` に移動）
   - `pack_for_review2.ps1`: `$templatePatterns` 未定義エラー（198行目）

2. **naming_rule を実装として反映**
   - `Naming.generate_filename()` でテンプレート文字列を使用

### P1（重要・推奨修正）

3. **date_range と custom cron の扱い**
   - 方針: 実装する（date_range は最低限実装、custom cron は croniter 導入）

4. **Accept-Encoding の矛盾解消**
   - `br` を外す（Brotli 対応なし）

5. **リトライ設計見直し**
   - `@retry` デコレータが機能するように例外を適切に再送出

6. **ログ設計を統一**
   - `handlers.clear()` の副作用排除

### P2（将来実装・低優先度）

7. **テストの安定化**
   - GUIテストを `@pytest.mark.gui` に移す

8. **仕上げ**
   - 不要依存の棚卸し
   - ドキュメント更新
