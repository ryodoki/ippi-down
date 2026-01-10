# ダウンロード機能修正推奨事項

## 調査結果サマリー

### 現状の問題
- ✅ ファイルリンクの抽出: **正常動作**（55件抽出）
- ❌ ファイルダウンロード: **接続タイムアウト**（`e2ppiw01.e-bisc.go.jp`への接続が確立できない）

### コードの動作
1. 詳細ページから`KokaiBunshoServlet`のURLを抽出（例: `https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?...`）
2. そのURLに直接アクセスを試行
3. **接続タイムアウト**が発生

## 原因分析

### 問題の可能性が高い点

#### 1. 別ドメインへの直接アクセス

**コードの動作**:
```python
# 詳細ページから直接 e-bisc.go.jp のURLを抽出
url = "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?..."
# そのURLに直接アクセス
response = http_client.get(url)  # → タイムアウト
```

**ブラウザの動作（推測）**:
- 詳細ページからリンクをクリック
- **中継ページ（`www.i-ppi.jp`ドメイン）を経由**
- 中継ページから`e-bisc.go.jp`にリダイレクト
- セッション情報が正しく引き継がれる

#### 2. Cookieのドメイン不一致

**現在のCookie**:
- `ApplicationGatewayAffinity`: `www.i-ppi.jp`ドメイン
- `ASP.NET_SessionId`: `www.i-ppi.jp`ドメイン

**ダウンロード先**:
- `e2ppiw01.e-bisc.go.jp`（別ドメイン）

**問題**: Cookieが別ドメインに送信されない（Same-Origin Policy）

#### 3. 必要なリダイレクト処理の不足

詳細ページのHTMLから直接`KokaiBunshoServlet`のURLを抽出していますが、実際のブラウザでは：
1. 詳細ページのリンクをクリック
2. 中継ページ（`www.i-ppi.jp`）にアクセス
3. 中継ページから`e-bisc.go.jp`にリダイレクト
4. セッション情報が正しく引き継がれる

この流れがコードで再現できていない可能性があります。

## 修正提案

### 提案1: 詳細ページのリンクを正確に取得（優先度: 高）

詳細ページのHTMLを確認し、実際のリンクがどのように生成されているか確認します。

**実装**:
```python
def _extract_download_link_from_table(self, detail_soup, base_url, table_id):
    """テーブルからダウンロードリンクを正確に抽出"""
    table = detail_soup.find("table", id=table_id)
    if not table:
        return None
    
    rows = table.find_all("tr")[1:]  # ヘッダー行をスキップ
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        
        status_cell = cells[1]
        link = status_cell.find("a", href=True)
        
        if link:
            href = link.get("href")
            onclick = link.get("onclick", "")
            
            # JavaScriptのonclick属性を確認
            if onclick:
                # window.open()やlocation.hrefなどのパターンを処理
                url_match = re.search(r"['\"]([^'\"]*KokaiBunshoServlet[^'\"]*)['\"]", onclick)
                if url_match:
                    url = url_match.group(1)
                    if not url.startswith("http"):
                        url = urljoin(base_url, url)
                    return url
            
            # HTMLのhref属性を使用
            if href:
                absolute_url = urljoin(base_url, href)
                return absolute_url
    
    return None
```

### 提案2: 中継URL経由のダウンロード（優先度: 高）

詳細ページから中継URL（`www.i-ppi.jp`ドメイン）を取得し、そのURLを経由してダウンロードします。

**実装**:
```python
def _get_download_url_via_intermediate(self, detail_soup, base_url):
    """中継URLを経由してダウンロードURLを取得"""
    # 詳細ページから中継URL（www.i-ppi.jpドメイン）を探す
    # 例: /IPPI/DownloadServices/Web/Download.aspx?...
    intermediate_link = detail_soup.find("a", href=lambda x: x and (
        "Download.aspx" in x or 
        "Publish.aspx" in x or
        "UserEntry_Download.aspx" in x
    ))
    
    if intermediate_link:
        intermediate_href = intermediate_link.get("href")
        if intermediate_href:
            # 相対URLを絶対URLに変換
            if not intermediate_href.startswith("http"):
                intermediate_url = urljoin(base_url, intermediate_href)
            else:
                intermediate_url = intermediate_href
            
            # 中継URLにアクセス（リダイレクトを追従）
            response = self.http_client.get(intermediate_url, allow_redirects=True)
            
            # 最終的なダウンロードURLを取得
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                if 'pdf' in content_type.lower():
                    # PDFを直接返している場合
                    return response.url
                else:
                    # HTMLページを返している場合、その中からダウンロードリンクを探す
                    intermediate_soup = BeautifulSoup(response.content, 'html.parser')
                    download_link = intermediate_soup.find("a", href=lambda x: x and "KokaiBunshoServlet" in x)
                    if download_link:
                        download_href = download_link.get("href")
                        if download_href:
                            return urljoin(response.url, download_href)
            
            # リダイレクト後のURL
            return response.url
    
    return None
```

### 提案3: ブラウザと同じヘッダーを送信（優先度: 中）

ブラウザが送信しているすべてのヘッダーを送信します。

**実装**:
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
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    
    if referer:
        headers["Referer"] = referer
        parsed_referer = urlparse(referer)
        origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
        headers["Origin"] = origin
        
        # Sec-Fetch-*ヘッダー（モダンブラウザで使用）
        headers["Sec-Fetch-Site"] = "same-site"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-User"] = "?1"
    
    return headers
```

### 提案4: 詳細ページのHTMLを保存して確認（優先度: 高）

詳細ページのHTMLを保存し、実際のリンク構造を確認します。

**実装**:
```python
# 詳細ページのHTMLを保存
detail_html_file = Path("tests/fixtures/html/detail_page_actual.html")
with open(detail_html_file, "w", encoding="utf-8") as f:
    f.write(str(detail_soup))
logger.info(f"詳細ページHTMLを保存: {detail_html_file}")
```

## 即座に実施すべき調査

### ステップ1: ブラウザでの実際の動作を確認（最重要）

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

### ステップ2: 詳細ページのHTMLを確認

詳細ページのHTMLを保存し、実際のリンク構造を確認します。

**確認項目**:
- ダウンロードリンクの`href`属性の値
- `onclick`属性の有無と内容
- JavaScriptで動的に生成されているか
- 中継URL（`www.i-ppi.jp`ドメイン）の存在

### ステップ3: 調査結果を記録

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

## 推奨される修正手順

### フェーズ1: 調査（今すぐ実施）

1. **ブラウザでの実際の動作を確認**
   - 開発者ツールでリクエスト情報を取得
   - 調査結果を記録

2. **詳細ページのHTMLを保存して確認**
   - `test_download_with_browser_simulation.py`でHTMLを保存
   - 実際のリンク構造を確認

### フェーズ2: 修正の実装

調査結果に基づいて、以下の順序で修正を実施：

1. **詳細ページのリンク抽出を修正**（調査結果に基づく）
2. **中継URL経由のダウンロードを実装**（もし中継URLが見つかった場合）
3. **ヘッダーの追加**（ブラウザと同じヘッダーを送信）
4. **Cookieの設定**（もし別ドメインのCookieが必要な場合）

### フェーズ3: テスト

修正後に再度テストを実施し、成功するまで繰り返す。

## 重要な注意事項

- **タイムアウトの原因はコードの問題の可能性が高い**
- ただし、ネットワーク環境（ファイアウォール、プロキシ）の問題も考えられる
- **まずはブラウザでの実際の動作を確認することが最重要**

## 次のアクション

1. **ブラウザで実際の動作を確認**（今すぐ実施）
   - 開発者ツールでリクエスト情報を取得
   - 調査結果を`browser_request_template.json`に記入

2. **調査結果を共有**
   - 取得したリクエスト情報を共有
   - それに基づいてコードを修正

3. **修正を実装**
   - 調査結果に基づいてコードを修正
   - テストを実施
