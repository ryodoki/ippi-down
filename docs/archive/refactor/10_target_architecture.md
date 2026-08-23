# 10 目標アーキテクチャ

---

## 1. レイヤ構成

```
presentation/          ← UI (tkinter) / CLI
  gui/
    widgets/           ← 分割した UI 部品
    viewmodel.py       ← tk.StringVar 束ね + Config 相互変換
    main_window.py     ← 薄いウィンドウシェル
    settings_dialog.py ← 薄いダイアログシェル
    event_handler.py
  cli/
    main.py

application/           ← ユースケース・オーケストレーション
  service.py           ← run() のフロー制御
  lookup_service.py    ← GUI 用ドロップダウン取得（HTTP を隠蔽）
  events.py
  exceptions.py
  run_result.py

domain/                ← 純粋ロジック（副作用なし）
  models/
    config_model.py    ← AppConfig, SearchConditions, SavePaths 等
    file_info.py
    download_task.py
    download_result.py
    search_result.py   ← NEW: 検索結果の型付き返却値
  naming.py
  filter.py
  path_builder.py

infrastructure/        ← 外部 I/O
  http/
    client.py          ← requests Session ラッパー
    error_types.py     ← NEW: エラー分類 dataclass
  ppi/                 ← i-ppi.jp 固有
    forms.py           ← hidden input 収集, POSTBACK データ構築
    html.py            ← encoding 判定, BeautifulSoup 生成
    search.py          ← 検索フォーム送信, 結果一覧抽出
    detail.py          ← 詳細ページ解析, 添付ファイル抽出
    dropdowns.py       ← 階層ドロップダウン取得
  download/
    downloader.py      ← ファイル DL + リトライ
    history.py         ← download_history.jsonl 管理
  storage/
    base.py
    local_storage.py

config/
  config_manager.py
  config_validator.py

scheduler/
  scheduler.py

utils/
  logger.py
  logger_factory.py
  file_utils.py
  path_utils.py
  notifier.py
  startup_manager.py
  secret_provider.py
```

## 2. import ルール（必ず守る）

```
presentation → application → domain ← infrastructure
                    ↓                    ↑
               infrastructure ───────────┘
```

| 呼び出し元 | 呼び出し可能 | 禁止 |
|-----------|------------|------|
| presentation (gui/cli) | application, domain/models | core 直接, infrastructure 直接 |
| application | domain, infrastructure | presentation |
| domain | 同レイヤ内のみ | infrastructure, presentation |
| infrastructure | domain/models | presentation, application |

## 3. 既存 → 新構造の対応表

| 既存パス | 移行先 | 備考 |
|---------|-------|------|
| `src/core/scraper.py` | `infrastructure/ppi/{forms,html,search,detail,dropdowns}.py` | 最大の分割対象 |
| `src/core/downloader.py` | `infrastructure/download/downloader.py` | |
| `src/core/download_history.py` | `infrastructure/download/history.py` | |
| `src/core/filter.py` | `domain/filter.py` | |
| `src/core/naming.py` | `domain/naming.py` | |
| `src/core/path_builder.py` | `domain/path_builder.py` | |
| `src/core/ppi_dropdowns.py` | `infrastructure/ppi/dropdowns.py` | 定数は domain に移すか検討 |
| `src/core/parser/*` | Phase 2 で ppi/* に統合 or 削除 | 現在未使用 |
| `src/core/fetcher/*` | Phase 2 で ppi/* に統合 or 削除 | 現在未使用 |
| `src/core/extractor/*` | Phase 2 で ppi/* に統合 or 削除 | 現在未使用 |
| `src/gui/main_window.py` | `presentation/gui/main_window.py` + `widgets/*` | |
| `src/gui/settings_dialog.py` | `presentation/gui/settings_dialog.py` + `widgets/*` | |
| `src/utils/http_client.py` | `infrastructure/http/client.py` | |
| `src/app/service.py` | `application/service.py` | |
| `src/models/*` | `domain/models/*` | |

## 4. 移行戦略

**段階的移行方針**: 新パスにファイルを作成 → 旧パスから re-export (`from new import *`) → 安定後に旧を削除。  
これにより import が壊れるリスクを最小化する。

> Phase 2 では `src/core/scraper.py` → `src/infrastructure/ppi/*` を最優先で実施。  
> ただし既存 `src/core/scraper.py` のパスは当面残し、re-export ブリッジを置く。
