# コードベース確認メモと改善タスク提案

## コードベース概要（確認結果）

- アプリ本体は `src/` 配下にあり、`src/main.py` は GUI/バックグラウンド実行、`src/cli/main.py` は CLI 実行の入口を提供している。
- 主要責務は `src/app/service.py`（処理オーケストレーション）、`src/core/`（スクレイピング・命名・ダウンロード）、`src/config/`（設定読み込みと検証）、`src/utils/`（HTTP/ログ等）で分離されている。
- テストは `tests/` にあり、`pytest.ini` では `pytest-timeout` の利用を前提とした実行オプションが設定されている。

## 提案タスク（4件）

### 1) 入力ミスを修正するタスク

**タスク名**: 命名規則テンプレートの typo 入力支援（候補提示）

- 背景: `ConfigValidator.validate_naming_rule()` は未知キーを検出するが、「どのキーに近いか」の候補を提示しないため、設定入力時の typo 修正コストが高い。
- 対応案:
  - `difflib.get_close_matches` などで `{typo_key}` に近い有効キー候補（例: `{title}` など）をメッセージに含める。
  - 1件目だけでなく、テンプレート中の未知キーをできる限り列挙できる実装に拡張する。
- 完了条件:
  - typo を含む `naming_rule` 入力で「未知キー + 候補」を返す。
  - エラーメッセージ仕様をテストで固定する。

### 2) バグを修正するタスク

**タスク名**: `check_duplicate()` のゼロバイトファイル分岐の死コード修正

- 背景: `Downloader.check_duplicate()` は `if path.exists() and path.stat().st_size > 0:` のブロック内で `if path.stat().st_size == 0:` を判定しており、ゼロバイト分岐が到達不能になっている。
- 影響:
  - 壊れたゼロバイトファイルの再取得フローが期待どおり動かない可能性がある。
- 対応案:
  - 条件分岐を整理して `exists` 判定後にサイズを変数化し、`0` を先に扱う。
  - `path.stat()` の多重呼び出しを削減して副作用/競合の可能性を下げる。
- 完了条件:
  - ゼロバイトファイル検出時に削除して `duplicate=False` を返すことをユニットテストで確認する。

### 3) コメントまたはドキュメントの矛盾を修正するタスク

**タスク名**: CLI 実装状況に関するドキュメント更新

- 背景: `docs/code_analysis.md` では「CLI 未実装」と記載されているが、実際には `src/cli/main.py` が存在して実装されている。
- 対応案:
  - `docs/code_analysis.md` と関連ドキュメントの「CLI 未実装」表現を現状（CLI 実装済み）に更新する。
  - 必要に応じて README の CLI 実行例と整合させる。
- 完了条件:
  - 主要ドキュメント間で CLI 実装状況の記述が一致している。

### 4) テストを改善するタスク

**タスク名**: `check_duplicate()` の分岐網羅テスト追加

- 背景: 重複判定ロジックは URL / filename+size / hash / file_exists / HTML混入など分岐が多いが、分岐単位の回帰テストが十分でない。
- 対応案:
  - `tests/test_downloader.py` に以下のケースを追加:
    - URL一致でスキップ
    - 既存ゼロバイトファイルは削除して再取得
    - 既存HTMLファイルは削除して再取得
    - filename+size 一致でスキップ
    - hash 一致でスキップ（`enable_hash_check=True`）
- 完了条件:
  - 各スキップ理由（`url`, `filename_size`, `hash`, `file_exists`）と再取得（`False, None`）がテストで明示される。

