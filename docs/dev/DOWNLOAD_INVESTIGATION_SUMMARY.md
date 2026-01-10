# ダウンロード機能調査サマリー

## 調査結果

### 1. 詳細ページのHTML確認

詳細ページのHTMLを保存し、実際のリンク構造を確認しました。

**保存ファイル**: `tests/fixtures/html/detail_page_actual.html`

**発見事項**:
- ✅ ダウンロードリンクは`href`属性に直接設定されている
- ✅ URLは正しく抽出されている（例: `https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?...`）
- ✅ JavaScriptの`onclick`属性は不要（少なくとも最初の行では）

**結論**: **URLの抽出は正しく動作している**

### 2. ダウンロード時の問題

**エラー**: 接続タイムアウト
- URL: `https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?...`
- タイムアウト設定: 接続10秒、読み取り300秒
- リトライ: 3回試行（すべて失敗）

**原因候補**:
1. **別ドメインへの直接アクセスが拒否されている**
   - `www.i-ppi.jp` → `e2ppiw01.e-bisc.go.jp`（別ドメイン）
   - サーバー側で`Referer`チェック等により拒否されている可能性

2. **Cookieが別ドメインに送信されていない**
   - 現在のCookie: `www.i-ppi.jp`ドメイン
   - `e-bisc.go.jp`ドメインには送信されない（Same-Origin Policy）

3. **実際のブラウザでは中継ページを経由している可能性**
   - 詳細ページから直接`e-bisc.go.jp`にアクセスするのではなく
   - 中継ページ（`www.i-ppi.jp`ドメイン）を経由している可能性

## 次のステップ

### ⚠️ 最重要: ブラウザでの実際の動作を確認

**手順**:
1. ブラウザを開く
2. `F12`キーで開発者ツールを開く
3. ネットワークタブを開く
4. 実際にファイルをダウンロード
5. PDFファイルのリクエストを探す
6. リクエストを右クリック → 「Copy」→ 「Copy as cURL」または「Copy request headers」

**確認すべき情報**:
- **リクエストURL**（最終的なURL、リダイレクト後）
- **リダイレクトチェーン**（最初のURL → 中間URL → 最終URL）
- **リクエストヘッダー**（すべて、特に`Referer`、`Origin`、`Cookie`）
- **レスポンスヘッダー**（すべて）

### 調査結果の記録

`docs/dev/browser_request_template.json`に情報を記入するか、以下の形式で記録：

```json
{
  "actual_request": {
    "url": "実際のダウンロードURL（リダイレクト後）",
    "method": "GET",
    "headers": {
      "User-Agent": "...",
      "Accept": "...",
      "Referer": "...",
      "Cookie": "...",
      "Origin": "...",
      "Sec-Fetch-Site": "...",
      "Sec-Fetch-Mode": "...",
      "Sec-Fetch-Dest": "...",
      "その他のヘッダー": "..."
    },
    "redirects": [
      "最初のURL",
      "中間URL（もしあれば）",
      "最終URL"
    ]
  },
  "code_request": {
    "url": "コードで生成しているURL",
    "headers": {
      "現在送信しているヘッダー": "..."
    }
  },
  "differences": [
    "差異1",
    "差異2"
  ]
}
```

## 修正提案

調査結果に基づいて、以下の修正を検討してください：

### 修正案1: ブラウザと同じヘッダーを送信

実際のブラウザが送信しているすべてのヘッダーを送信します。

**特に重要なヘッダー**:
- `Origin`: `https://www.i-ppi.jp`
- `Sec-Fetch-Site`: `same-site` または `cross-site`
- `Sec-Fetch-Mode`: `navigate`
- `Sec-Fetch-Dest`: `document`
- `Sec-Fetch-User`: `?1`

### 修正案2: 中継URL経由のダウンロード

詳細ページから中継URL（`www.i-ppi.jp`ドメイン）を取得し、そのURLを経由してダウンロードします。

### 修正案3: Cookieを手動で設定

別ドメインのCookieが必要な場合、Cookieを手動で設定します。

## まとめ

### 現在の状況
- ✅ **URLの抽出**: 正常動作（詳細ページから正しく抽出されている）
- ❌ **ダウンロード**: 接続タイムアウト（別ドメインへの直接アクセスが失敗）

### 次のアクション
1. **ブラウザで実際の動作を確認**（今すぐ実施）
   - 開発者ツールでリクエスト情報を取得
   - 調査結果を記録

2. **調査結果に基づいてコードを修正**
   - ブラウザと同じヘッダーを送信
   - 中継URL経由のダウンロード（もし中継URLが見つかった場合）
   - Cookieの設定（もし別ドメインのCookieが必要な場合）

3. **修正後に再度テスト**
   - テストを実施
   - 成功するまで繰り返す

## 関連ファイル

- **詳細ページHTML**: `tests/fixtures/html/detail_page_actual.html`
- **調査手順書**: `docs/dev/BROWSER_DOWNLOAD_INVESTIGATION.md`
- **修正提案**: `docs/dev/DOWNLOAD_FIX_PROPOSAL.md`
- **修正分析**: `docs/dev/DOWNLOAD_FIX_ANALYSIS.md`
- **修正推奨事項**: `docs/dev/DOWNLOAD_FIX_RECOMMENDATIONS.md`
- **ブラウザリクエストテンプレート**: `docs/dev/browser_request_template.json`
- **分析スクリプト**: `scripts/dev/analyze_browser_download.py`
- **比較スクリプト**: `scripts/dev/compare_browser_request.py`
- **ブラウザシミュレーションテスト**: `scripts/dev/test_download_with_browser_simulation.py`
- **詳細ページHTML保存スクリプト**: `scripts/dev/save_detail_page_html.py`
