# ライブラリ比較ガイド

## 概要

このドキュメントは、Playwright、Selenium、requestsの3つのライブラリのうち、どれがダウンロード対象のWebページに最も適しているかを調査する方法を説明します。

## 比較スクリプトの使用方法

### 1. 必要なライブラリのインストール

```bash
# 基本ライブラリ
pip install requests selenium playwright

# Playwrightのブラウザをインストール
playwright install chromium
```

### 2. スクリプトの実行

```bash
# デフォルトURL（i-ppi.jpの検索ページ）で実行
python scripts/dev/compare_libraries.py

# カスタムURLを指定
python scripts/dev/compare_libraries.py "https://example.com/target-page"

# タイムアウトを変更（デフォルト: 30秒）
python scripts/dev/compare_libraries.py -t 60

# レポート出力先を指定
python scripts/dev/compare_libraries.py -o docs/dev/my_comparison_report.json
```

### 3. 出力レポートの確認

レポートはJSON形式で保存され、以下の情報が含まれます：

- 各ライブラリのテスト結果
- 応答時間
- JavaScript実行能力
- 動的コンテンツ対応
- ダウンロード可能性
- 実装の複雑度
- 推奨ライブラリとその理由

## 比較項目

### 1. requests
- **JavaScript実行**: 不可
- **動的コンテンツ**: 対応不可（静的HTMLのみ）
- **実装複雑度**: 低
- **パフォーマンス**: 高速
- **用途**: シンプルなHTTPリクエスト、API呼び出し

### 2. Selenium
- **JavaScript実行**: 可能
- **動的コンテンツ**: 対応可能（ブラウザを制御）
- **実装複雑度**: 中
- **パフォーマンス**: 中（ブラウザ起動が必要）
- **用途**: ブラウザ自動化、JavaScriptが必要なページ

### 3. Playwright
- **JavaScript実行**: 可能
- **動的コンテンツ**: 対応可能（モダンなブラウザ自動化）
- **実装複雑度**: 中
- **パフォーマンス**: 中〜高（最適化されたブラウザ制御）
- **用途**: モダンなWebアプリケーション、E2Eテスト

## 評価基準

スクリプトは以下の基準で各ライブラリを評価します：

1. **応答時間**: 短いほど高評価
2. **JavaScript実行能力**: 必要に応じて高評価
3. **動的コンテンツ対応**: 必要に応じて高評価
4. **ダウンロード可能性**: 可能な場合に高評価
5. **実装の容易さ**: 簡単なほど高評価

## 推奨の判定ロジック

スクリプトは以下のロジックで推奨ライブラリを判定します：

1. すべてのライブラリでテストを実行
2. 成功したライブラリを評価
3. 各評価項目にスコアを付与
4. 最高スコアのライブラリを推奨

## 使用例

### 例1: 基本的な使用

```bash
python scripts/dev/compare_libraries.py
```

### 例2: 特定のページをテスト

```bash
python scripts/dev/compare_libraries.py "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
```

### 例3: タイムアウトを延長

```bash
python scripts/dev/compare_libraries.py -t 60
```

## 注意事項

1. **Selenium**: EdgeDriverが必要です。インストールされていない場合はエラーになります。
2. **Playwright**: 初回実行時にブラウザをダウンロードするため、時間がかかります。
3. **ネットワーク**: 対象ページにアクセスできる必要があります。
4. **タイムアウト**: 遅いページの場合はタイムアウトを延長してください。

## トラブルシューティング

### Seleniumでエラーが発生する場合

```bash
# EdgeDriverを確認
# EdgeDriverは自動的にダウンロードされますが、手動でインストールする場合：
# https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/
```

### Playwrightでエラーが発生する場合

```bash
# ブラウザを再インストール
playwright install chromium
```

### requestsでタイムアウトが発生する場合

- タイムアウト時間を延長: `-t 60`
- ネットワーク接続を確認
- プロキシ設定を確認

## レポートの解釈

### 成功した場合

- `success: true`: テストが成功
- `response_time`: 応答時間（秒）
- `status_code`: HTTPステータスコード
- `has_javascript`: JavaScript実行能力
- `dynamic_content`: 動的コンテンツの有無
- `download_possible`: ダウンロード可能性

### 失敗した場合

- `success: false`: テストが失敗
- `error_message`: エラーメッセージ
- エラーの内容を確認して、適切な対処を行う

## 次のステップ

1. スクリプトを実行してレポートを確認
2. 推奨ライブラリを確認
3. 推奨ライブラリで実装を試行
4. 必要に応じて他のライブラリも検討

---

**作成日**: 2026年1月10日  
**最終更新**: 2026年1月10日
