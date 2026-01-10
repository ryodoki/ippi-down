# ダウンロード機能修正分析

## 現状の問題

### エラー内容
- **接続タイムアウト**: `e2ppiw01.e-bisc.go.jp`への接続が確立できない
- **タイムアウト設定**: 接続10秒、読み取り300秒でもタイムアウト
- **リトライ**: 3回試行（1秒、2秒、4秒の指数バックオフ）→ すべて失敗

### コードの現在の動作

1. **ファイルリンクの抽出**
   - 検索結果ページ → 詳細ページ（`__doPostBack`経由）
   - 詳細ページから`dgrKokoku`、`dgrKeika`テーブル内のリンクを抽出
   - リンクが`KokaiBunshoServlet`を含む場合、それをダウンロードURLとして扱う

2. **ダウンロードの実行**
   - 抽出したURL（例: `https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?...`）に直接アクセス
   - `Referer`ヘッダーに`page_url`（詳細ページのURL）を設定
   - Cookieは`www.i-ppi.jp`ドメインのもののみ

## 仮説：コードの問題点

### 仮説1: ダウンロードURLの生成方法が間違っている

**問題点**:
- 詳細ページのHTMLから直接`KokaiBunshoServlet`のURLを抽出している
- しかし、実際のブラウザでは、JavaScriptで動的に生成されている可能性がある
- または、中継ページ（`UserEntry_Download.aspx`等）を経由する必要がある

**検証方法**:
- 詳細ページのHTMLを確認し、`KokaiBunshoServlet`のURLが実際に存在するか確認
- JavaScriptコードを確認し、URLの生成方法を特定

### 仮説2: Cookieが別ドメインに送信されていない

**問題点**:
- 現在のCookie: `www.i-ppi.jp`ドメイン
- ダウンロード先: `e2ppiw01.e-bisc.go.jp`（別ドメイン）
- **Cookieが別ドメインに送信されない**（Same-Origin Policy）

**検証方法**:
- ブラウザの開発者ツールで、実際のダウンロードリクエストのCookieを確認
- `e-bisc.go.jp`ドメインのCookieが存在するか確認

**考えられる解決策**:
1. Cookieが不要な場合: URLパラメータだけで認証されている可能性
2. Cookieが必要な場合: 中継ページ（`www.i-ppi.jp`ドメイン）を経由してCookieを設定する必要がある

### 仮説3: リダイレクトの追従が不足している

**問題点**:
- 詳細ページから直接`e-bisc.go.jp`にアクセスしようとしている
- しかし、実際のブラウザでは、中継ページ（`www.i-ppi.jp`ドメイン）を経由している可能性がある

**検証方法**:
- ブラウザの開発者ツールで、リダイレクトチェーンを確認
- 中間URLが存在するか確認

**考えられる解決策**:
1. 中継URLを取得: 詳細ページのHTMLから中継URLを抽出
2. 中継URLにアクセス: 中継URLにアクセスして、リダイレクトを追従
3. 最終URLを取得: リダイレクト後のURLをダウンロードURLとして使用

### 仮説4: 必要なヘッダーが不足している

**問題点**:
- 現在送信しているヘッダー: `User-Agent`, `Accept`, `Accept-Language`, `Referer`
- ブラウザが送信している追加ヘッダー: `Origin`, `Sec-Fetch-*`等が不足している可能性

**検証方法**:
- ブラウザの開発者ツールで、実際のリクエストヘッダーを確認
- コードで送信しているヘッダーと比較

**考えられる解決策**:
1. ブラウザと同じヘッダーを送信
2. 特に`Origin`ヘッダーは重要（CSRF保護のため）

### 仮説5: 詳細ページのリンクが相対URLで、絶対URLへの変換が間違っている

**問題点**:
- 詳細ページのHTMLからリンクを抽出する際、相対URLを絶対URLに変換している
- しかし、`base_url`が間違っている可能性がある

**検証方法**:
- 詳細ページのHTMLを保存して確認
- リンクの`href`属性の実際の値を確認
- `urljoin`の結果が正しいか確認

## 推奨される調査手順

### ステップ1: ブラウザで実際の動作を確認（最重要）

1. **ブラウザを開く**
   - ChromeまたはEdge

2. **開発者ツールを開く**
   - `F12`キー
   - ネットワークタブを開く
   - 「Preserve log」（ログを保持）にチェック

3. **実際にファイルをダウンロード**
   ```
   1. https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4 にアクセス
   2. 検索条件を設定（発注機関 = "国の機関"）
   3. 「検索開始」をクリック
   4. 検索結果から1件をクリックして詳細ページを開く
   5. 詳細ページで「公告文書」タブのファイルをクリック
   6. ダウンロードを実行
   ```

4. **ネットワークタブで確認**
   - PDFファイルのリクエストを探す
   - リクエストを右クリック → 「Copy」→ 「Copy as cURL」または「Copy request headers」
   - 以下の情報を記録：
     - **リクエストURL**（最終的なURL、リダイレクト後）
     - **リクエストヘッダー**（すべて）
     - **レスポンスヘッダー**（すべて）
     - **Cookie**（すべて）
     - **リダイレクトの流れ**（もしあれば）

### ステップ2: 調査結果を記録

`docs/dev/browser_request_template.json`に情報を記入するか、以下の形式で記録：

```json
{
  "url": "実際のダウンロードURL（リダイレクト後）",
  "method": "GET",
  "headers": {
    "User-Agent": "...",
    "Accept": "...",
    "Referer": "...",
    "Cookie": "...",
    "その他のヘッダー": "..."
  },
  "cookies": [
    {
      "name": "Cookie名",
      "value": "Cookie値",
      "domain": "ドメイン",
      "path": "パス"
    }
  ],
  "redirects": [
    "最初のURL",
    "最終URL"
  ]
}
```

### ステップ3: コードとの差異を特定

`scripts/dev/compare_browser_request.py`を使用して、ブラウザのリクエストとコードのリクエストを比較：

```bash
python scripts/dev/compare_browser_request.py
# 調査結果のJSONファイルのパスを入力
```

### ステップ4: 修正を実装

調査結果に基づいて、以下の修正を検討：

#### 修正案A: 中継URLを経由する

```python
def _get_download_url_via_intermediate(self, detail_soup, base_url):
    """中継URLを経由してダウンロードURLを取得"""
    # 詳細ページから中継URLを抽出
    intermediate_link = detail_soup.find("a", href=lambda x: x and "KokaiBunshoServlet" in x)
    if intermediate_link:
        intermediate_url = urljoin(base_url, intermediate_link.get("href"))
        # 中継URLにアクセス（リダイレクトを追従）
        response = self.http_client.get(intermediate_url, allow_redirects=True)
        # 最終的なダウンロードURLを取得
        return response.url
    return None
```

#### 修正案B: Cookieを手動で設定

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

#### 修正案C: ブラウザと同じヘッダーを送信

```python
def _get_browser_like_headers(self, referer=None):
    """ブラウザと同じヘッダーを生成"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "same-site",  # または "cross-site"
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    if referer:
        headers["Referer"] = referer
        headers["Origin"] = urlparse(referer).scheme + "://" + urlparse(referer).netloc
    return headers
```

#### 修正案D: 詳細ページのリンクを正確に抽出

```python
def _extract_download_link_from_detail_page(self, detail_soup, base_url):
    """詳細ページからダウンロードリンクを正確に抽出"""
    # dgrKokokuとdgrKeikaテーブルからリンクを抽出
    for table_id in ["dgrKokoku", "dgrKeika"]:
        table = detail_soup.find("table", id=table_id)
        if not table:
            continue
        
        rows = table.find_all("tr")[1:]  # ヘッダー行をスキップ
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            
            status_cell = cells[1]
            link = status_cell.find("a", href=True)
            
            if link:
                href = link.get("href")
                if href:
                    # 絶対URLへの変換を正確に行う
                    # base_urlは詳細ページのURL（post_url）を使用
                    absolute_url = urljoin(base_url, href)
                    
                    # リンクが実際にクリック可能か確認
                    # JavaScriptイベントハンドラがある場合は、実際のURLを生成
                    onclick = link.get("onclick", "")
                    if onclick and "KokaiBunshoServlet" in onclick:
                        # JavaScriptからURLを抽出
                        # 例: onclick="window.open('URL', ...)"
                        import re
                        url_match = re.search(r"['\"]([^'\"]*KokaiBunshoServlet[^'\"]*)['\"]", onclick)
                        if url_match:
                            absolute_url = url_match.group(1)
                            # 相対URLの場合は絶対URLに変換
                            if not absolute_url.startswith("http"):
                                absolute_url = urljoin(base_url, absolute_url)
                    
                    return absolute_url
    return None
```

## 修正実装の優先順位

### 最優先: ブラウザでの調査

1. **ブラウザの開発者ツールで実際のリクエストを確認**
   - これが最も重要
   - 実際のリクエスト情報がないと、修正の方向性が定まらない

2. **調査結果を記録**
   - `browser_request_template.json`に記入
   - または、手動でメモ

3. **コードとの差異を特定**
   - `compare_browser_request.py`で比較

### 次に実施: コードの修正

調査結果に基づいて、以下の順序で修正を試す：

1. **ヘッダーの修正**（簡単、影響が大きい）
   - ブラウザと同じヘッダーを送信
   - 特に`Origin`、`Sec-Fetch-*`ヘッダー

2. **中継URLの経由**（中程度の難易度）
   - 詳細ページから中継URLを抽出
   - 中継URLを経由してダウンロード

3. **Cookieの設定**（やや複雑）
   - 別ドメインのCookieを手動で設定
   - または、中継ページでCookieを取得

4. **Seleniumの使用**（最後の手段）
   - JavaScriptの実行が必要な場合のみ
   - パフォーマンスと依存関係のコストが高い

## まとめ

### 現在の状況
- ✅ ファイルリンクの抽出: 正常動作（55件抽出）
- ❌ ファイルダウンロード: 接続タイムアウト

### 次のステップ
1. **ブラウザで実際の動作を確認**（最重要）
   - 開発者ツールでリクエスト情報を取得
   - 調査結果を記録

2. **コードとの差異を特定**
   - 調査結果とコードを比較
   - 不足している要素を特定

3. **修正を実装**
   - 調査結果に基づいてコードを修正
   - テストを実施

### 推奨事項
- **まずはブラウザでの調査を実施してください**
- 調査結果がないと、修正の方向性が定まらないため
- 調査結果に基づいて、適切な修正を実装します
