# ダウンロード機能修正実装レポート

## 実装日時
2026年1月10日

## 実装した修正

### 1. ブラウザと同じヘッダーの追加

**ファイル**: `src/utils/http_client.py`

**修正内容**:
- `download_file`メソッドで、ブラウザと同じヘッダーを送信するように修正
- 追加したヘッダー:
  - `Accept-Encoding: gzip, deflate, br`
  - `Connection: keep-alive`
  - `Upgrade-Insecure-Requests: 1`
  - `Cache-Control: no-cache`
  - `Pragma: no-cache`
  - `Origin: https://www.i-ppi.jp` (Refererから自動生成)
  - `Sec-Fetch-Site: same-site` または `cross-site`
  - `Sec-Fetch-Mode: navigate`
  - `Sec-Fetch-Dest: document`
  - `Sec-Fetch-User: ?1`

**コード変更**:
```python
# 修正前
download_headers = {
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
if referer:
    download_headers["Referer"] = referer

# 修正後
download_headers = {
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
if referer:
    download_headers["Referer"] = referer
    parsed_referer = urlparse(referer)
    origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
    download_headers["Origin"] = origin
    download_headers["Sec-Fetch-Site"] = "same-site" if parsed_referer.netloc.endswith(".i-ppi.jp") else "cross-site"
    download_headers["Sec-Fetch-Mode"] = "navigate"
    download_headers["Sec-Fetch-Dest"] = "document"
    download_headers["Sec-Fetch-User"] = "?1"
```

### 2. リダイレクトの確実な追従

**ファイル**: `src/utils/http_client.py`

**修正内容**:
- `session.get()`に`allow_redirects=True`を明示的に指定
- リダイレクトチェーンを確実に追従

**コード変更**:
```python
# 修正前
response = self.session.get(
    url,
    stream=True,
    timeout=timeout_tuple,
    headers=download_headers
)

# 修正後
response = self.session.get(
    url,
    stream=True,
    timeout=timeout_tuple,
    headers=download_headers,
    allow_redirects=True  # リダイレクトを確実に追従
)
```

## 調査結果

### 詳細ページのHTML確認

**保存ファイル**: `tests/fixtures/html/detail_page_actual.html`

**発見事項**:
- ✅ ダウンロードリンクは`href`属性に直接設定されている
- ✅ URLは正しく抽出されている（例: `https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?...`）
- ✅ JavaScriptの`onclick`属性は不要（少なくとも最初の行では）
- ✅ 中継ページ（`UserEntry_Download.aspx`）の存在を確認

**結論**: **URLの抽出は正しく動作している**

### ダウンロード時の問題

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

## 作成したスクリプト

### 1. 詳細ページHTML保存スクリプト

**ファイル**: `scripts/dev/save_detail_page_html.py`

**機能**:
- 詳細ページのHTMLを保存
- ダウンロードリンクの構造を分析

### 2. 改善されたヘッダーでダウンロードテスト

**ファイル**: `scripts/dev/test_download_with_improved_headers.py`

**機能**:
- ブラウザと同じヘッダーを使用してダウンロードをテスト
- 詳細なログ出力
- HEADリクエストで接続テスト

### 3. ブラウザ動作分析スクリプト

**ファイル**: `scripts/dev/analyze_browser_download.py`

**機能**:
- ブラウザでのダウンロード動作を分析
- セッション情報、Cookie、ヘッダーを確認

### 4. ブラウザリクエスト比較スクリプト

**ファイル**: `scripts/dev/compare_browser_request.py`

**機能**:
- ブラウザのリクエストとコードのリクエストを比較
- 差異を特定

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
      "すべてのヘッダー": "..."
    },
    "redirects": [
      "最初のURL",
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

## 追加で検討すべき修正

### 修正案1: 中継URL経由のダウンロード

詳細ページから中継URL（`www.i-ppi.jp`ドメイン）を取得し、そのURLを経由してダウンロードします。

**実装例**:
```python
def _get_download_url_via_intermediate(self, detail_soup, base_url):
    """中継URLを経由してダウンロードURLを取得"""
    # 詳細ページから中継URLを探す
    intermediate_link = detail_soup.find("a", href=lambda x: x and "UserEntry_Download.aspx" in x)
    if intermediate_link:
        intermediate_url = urljoin(base_url, intermediate_link.get("href"))
        # 中継URLにアクセス（リダイレクトを追従）
        response = self.http_client.get(intermediate_url, allow_redirects=True)
        # 最終的なダウンロードURLを取得
        return response.url
    return None
```

### 修正案2: Cookieを手動で設定

別ドメインのCookieが必要な場合、Cookieを手動で設定します。

**実装例**:
```python
def _set_cookie_for_download(self, http_client, cookie_info):
    """ダウンロード用のCookieを設定"""
    from http.cookiejar import Cookie
    cookie = Cookie(
        version=0,
        name=cookie_info["name"],
        value=cookie_info["value"],
        domain=cookie_info["domain"],  # .e-bisc.go.jp などのサブドメインにも送信
        path=cookie_info.get("path", "/"),
        secure=cookie_info.get("secure", False)
    )
    http_client.session.cookies.set_cookie(cookie)
```

## まとめ

### 実装した修正
- ✅ ブラウザと同じヘッダーの追加（Origin、Sec-Fetch-*等）
- ✅ リダイレクトの確実な追従
- ✅ 詳細なログ出力の改善

### 調査結果
- ✅ URLの抽出は正しく動作している
- ❌ ダウンロード時の接続タイムアウトが発生

### 次のアクション
1. **ブラウザで実際の動作を確認**（最重要）
   - 開発者ツールでリクエスト情報を取得
   - 調査結果を記録

2. **調査結果に基づいて追加修正を実装**
   - 中継URL経由のダウンロード（もし中継URLが見つかった場合）
   - Cookieの設定（もし別ドメインのCookieが必要な場合）

3. **修正後に再度テスト**
   - テストを実施
   - 成功するまで繰り返す

## 関連ファイル

- **修正したファイル**:
  - `src/utils/http_client.py`

- **作成したスクリプト**:
  - `scripts/dev/save_detail_page_html.py`
  - `scripts/dev/test_download_with_improved_headers.py`
  - `scripts/dev/analyze_browser_download.py`
  - `scripts/dev/compare_browser_request.py`

- **調査結果ファイル**:
  - `tests/fixtures/html/detail_page_actual.html`
  - `docs/dev/browser_download_analysis.json`
  - `docs/dev/browser_simulation_analysis.json`

- **ドキュメント**:
  - `docs/dev/BROWSER_DOWNLOAD_INVESTIGATION.md`
  - `docs/dev/DOWNLOAD_FIX_PROPOSAL.md`
  - `docs/dev/DOWNLOAD_FIX_ANALYSIS.md`
  - `docs/dev/DOWNLOAD_FIX_RECOMMENDATIONS.md`
  - `docs/dev/DOWNLOAD_INVESTIGATION_SUMMARY.md`
  - `docs/dev/DOWNLOAD_FIX_IMPLEMENTATION.md`（このファイル）
