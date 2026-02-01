# コード全体分析レポート

## 1. エントリポイントの特定

### GUIモード（デフォルト）
```
src/main.py::main()
  → ConfigManager.load_config()
  → AppConfig（YAMLから読み込み）
  → MainWindow（GUI起動）
  → ApplicationService.run()
```

### バックグラウンドモード
```
src/main.py::main() (--background または PPI_BACKGROUND_MODE=true)
  → ConfigManager.load_config()
  → AppConfig（YAMLから読み込み）
  → Scheduler.start()（スケジュール有効時）
  → ApplicationService.run()
```

### CLI（未実装）
- 要件定義では「開発・デバッグ用」として定義されているが、未実装
- `src/main.py` は GUI/バックグラウンドモードのみ

## 2. 設定読み込み経路

```
ConfigManager.load_config()
  → config/config.yaml を読み込み（YAML形式）
  → yaml.safe_load() で辞書に変換
  → ConfigManager._dict_to_config() で AppConfig に変換
  → ConfigValidator.validate_config() で検証
  → AppConfig を返す
    ↓
各コンポーネントに渡される:
  - ApplicationService._initialize_components()
    → Naming(config.naming_rule, ...)
    → Filter(config.download_conditions, ...)
    → Scheduler(config.schedule, ...)
```

## 3. 設定項目の使用状況

### ✅ 使用されている設定項目

| 設定項目 | 使用箇所 | 状態 |
|---------|---------|------|
| `target_urls` | `ApplicationService._extract_files()` | ✅ 使用中 |
| `download_conditions.file_types` | `Filter.match_file_type()` | ✅ 使用中 |
| `download_conditions.keywords` | `Filter.match_keywords()` | ✅ 使用中 |
| `download_conditions.date_range` | `Filter.match_date_range()` | ✅ **実装済み（今回修正）** |
| `save_paths.local` | `ApplicationService.run()` | ✅ 使用中 |
| `naming_rule` | `Naming.generate_filename()` | ✅ **実装済み（今回修正）** |
| `schedule.enabled` | `Scheduler.start()` | ✅ 使用中 |
| `schedule.interval` | `Scheduler._setup_schedule()` | ✅ 使用中 |
| `schedule.time` | `Scheduler._schedule_daily/weekly/monthly()` | ✅ 使用中 |
| `schedule.cron` | `Scheduler._schedule_custom()` | ✅ **実装済み（今回修正）** |
| `logging.level` | `Logger.__init__()` | ✅ 使用中 |
| `logging.file` | `Logger.setup_file_handler()` | ✅ 使用中 |
| `logging.max_bytes` | `Logger.setup_file_handler()` | ✅ 使用中 |
| `logging.backup_count` | `Logger.setup_file_handler()` | ✅ 使用中 |
| `search_conditions.*` | `Scraper`, `Naming` | ✅ 使用中 |

### ⚠️ 設定に存在するが使用されていない項目

| 設定項目 | 状態 | 影響範囲 |
|---------|------|---------|
| `tqdm` (requirements.txt) | コメントアウト済み | 進捗表示ライブラリ（現在未使用） |

### 📝 実装済み（今回修正で対応）

| 設定項目 | 実装状況 | 備考 |
|---------|---------|------|
| `naming_rule` | ✅ 実装済み | テンプレート文字列を使用 |
| `date_range` | ✅ 実装済み | メタデータから日付を取得してフィルタ |
| `schedule.cron` | ✅ 実装済み | croniter を使用 |

## 4. 設定項目の影響範囲

### naming_rule
- **影響範囲**: `src/core/naming.py::Naming.generate_filename()`
- **使用箇所**: `src/app/service.py::ApplicationService._initialize_components()`
- **状態**: ✅ 実装済み（テンプレート文字列を使用）

### date_range
- **影響範囲**: `src/core/filter.py::Filter.match_date_range()`
- **使用箇所**: `src/core/filter.py::Filter._matches_all_conditions()`
- **状態**: ✅ 実装済み（メタデータから日付を取得してフィルタ）

### schedule.cron
- **影響範囲**: `src/scheduler/scheduler.py::Scheduler._schedule_custom()`
- **使用箇所**: `src/scheduler/scheduler.py::Scheduler._setup_schedule()`
- **状態**: ✅ 実装済み（croniter を使用）
