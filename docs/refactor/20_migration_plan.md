# 20 移行計画

---

## フェーズ一覧

| Phase | 名称 | 優先度 | リスク | 主な成果 |
|-------|------|-------|-------|---------|
| 1 | リポジトリ衛生 | 最優先 | 低 | 死コード削除, .gitignore 整備 |
| 2 | scraper 分割 | 高 | 中 | 2,034行→5モジュール, ユニットテスト追加 |
| 3 | ApplicationService 整理 | 中 | 低 | SearchConditions.is_empty(), typed 返却値 |
| 4 | GUI 分割 | 高 | 中 | widgets 切り出し, viewmodel 導入 |
| 5 | HTTPClient 共通化 | 中 | 低 | リトライ共通化, error dataclass |
| 6 | 命名/パス/保存の純化 | 中 | 低 | Naming/PathBuilder 責務明確化 |

---

## Phase 1: リポジトリ衛生

### 作業内容
1. `src/core/parser/`, `src/core/fetcher/`, `src/core/extractor/` を削除
   - これらは `scraper.py` に同等機能が統合済み
   - テスト (`test_phase_b.py`, `test_integration.py`) で参照しているので、テストも更新
2. `croniter` 依存の整理
   - `requirements.txt` に croniter がある場合は確認
   - テストで `croniter` が無い場合のスキップ処理を追加
3. 不要な生成物・デバッグファイルの確認
   - `debug/` フォルダ, `artifacts/` フォルダの Git 管理状況を確認
4. `docs/refactor/01_repo_hygiene.md` を作成

### テスト方針
- 削除したモジュールを参照するテストを修正
- `python -m pytest` が 93+ passed で安定

### 影響範囲
- `test_phase_b.py`: parser/fetcher/extractor のテストを削除
- `test_integration.py`: 同上
- 本番コード: 影響なし（未使用モジュールの削除のため）

---

## Phase 2: scraper 分割

### 作業内容
1. `src/infrastructure/ppi/` ディレクトリを新規作成
2. `scraper.py` から以下を抽出:
   - `forms.py`: hidden input 収集, フォームデータ構築, POSTBACK 送信
   - `html.py`: encoding 判定, BeautifulSoup 生成, URL 正規化
   - `search.py`: 検索フォーム送信, 検索結果ページング, 件数抽出
   - `detail.py`: 詳細ページ解析, テーブルからのファイルリンク抽出
   - `dropdowns.py`: 発注機関/工事場所ドロップダウン取得
3. `scraper.py` をファサードとして残し、新モジュールに委譲
4. fixtures を使ったユニットテストを追加（ネットワーク不要）

### テスト方針
- 各モジュールに対してユニットテスト作成
- `test_scraper.py` の既存テストが引き続きパスすること
- fixtures: `tests/fixtures/` に HTML サンプルを配置

### 影響範囲
- `src/app/service.py`: Scraper の公開 API が変わらないため影響なし
- `src/gui/main_window.py`: Scraper import が変わらないため影響なし

---

## Phase 3: ApplicationService 整理

### 作業内容
1. `SearchConditions.is_effectively_empty()` メソッドを `config_model.py` に追加
2. `service.py` の `_has_search_conditions()` を上記に委譲
3. `SearchResult` dataclass を `models/` に追加（`last_search_total_koji_count` 副作用廃止）
4. `service.py` の戻り値を型付きに

### 影響範囲
- `src/app/service.py`, `src/models/config_model.py`
- テスト: `test_application_service.py` 更新

---

## Phase 4: GUI 分割

### 作業内容
1. `src/gui/widgets/` ディレクトリを新規作成
2. `main_window.py` から切り出し:
   - `toolbar.py`: ツールバー
   - `search_conditions_frame.py`: 検索条件 UI
   - `log_frame.py`: ログ表示
3. `settings_dialog.py` から切り出し:
   - 各タブの UI をウィジェットとして分離
4. `viewmodel.py`: tk.StringVar 束ね + Config 相互変換
5. `lookup_service.py`: GUI からの HTTP 呼び出しをラップ

### 影響範囲
- `main_window.py`, `settings_dialog.py` の行数削減
- GUI の見た目・操作は変更なし

---

## Phase 5: HTTPClient 共通化

### 作業内容
1. `get()` / `post()` / `download_file()` のリトライロジックを共通関数に統合
2. エラー情報を `DownloadError` dataclass に統一
3. requests モックによるユニットテスト追加

---

## Phase 6: 命名/パス/保存の純化

### 作業内容
1. `Naming`: テンプレ展開のみ（副作用なし）
2. `PathBuilder`: フォルダ階層構築のみ
3. `Downloader`: I/O とリトライのみ
4. 責務境界を docs に固定

---

## 受け入れ基準（全 Phase 共通）

- [ ] `python -m pytest` パス
- [ ] `python -m src.main` で GUI 起動・設定画面開閉・ドロップダウン取得が正常
- [ ] `config/config.yaml` スキーマ互換性維持
- [ ] 各 Phase のドキュメントが `docs/refactor/` に存在
