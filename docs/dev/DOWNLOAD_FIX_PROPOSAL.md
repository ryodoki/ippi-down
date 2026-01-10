# ダウンロード機能修正提案

## 現状の問題

### エラー内容
- **接続タイムアウト**: `e2ppiw01.e-bisc.go.jp`への接続が確立できない
- **タイムアウト設定**: 接続10秒、読み取り300秒でもタイムアウト

### 現在のコードの問題点

1. **Cookieのドメイン不一致**
   ```python
   # 現在のCookie: www.i-ppi.jp
   # ダウンロード先: e2ppiw01.e-bisc.go.jp
   # → Cookieが別ドメインに送信されない
   ```

2. **直接アクセスの試行**
   - `e2ppiw01.e-bisc.go.jp`に直接接続しようとしている
   - ブラウザでは、詳細ページからリンクをクリックした際の処理が異なる可能性

3. **リダイレクトの追従不足**
   - ブラウザでは、詳細ページ→中継ページ→ダウンロードの流れがある可能性
   - コードではリダイレクトを追従しているが、中間処理が不足している可能性

## 調査が必要な事項

### 1. ブラウザでの実際の動作を確認

以下の手順でブラウザの開発者ツールを使用して、実際のリクエスト情報を取得してください：

1. **ブラウザでサイトにアクセス**
   - `https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4`

2. **検索を実行**
   - 発注機関 = "国の機関" で検索

3. **詳細ページを開く**
   - 検索結果から1件をクリック

4. **ファイルをダウンロード**
   - 詳細ページで「公告文書」または「経過文書」タブのファイルをクリック

5. **開発者ツール（F12）で確認**
   - Networkタブを開く
   - PDFファイルのリクエストを探す
   - 以下の情報を記録：
     - リクエストURL（最終的なURL、リダイレクト後）
     - リクエストヘッダー（すべて）
     - レスポンスヘッダー（すべて）
     - Cookie（すべて）
     - リダイレクトの流れ

### 2. 調査結果の記録

以下のテンプレートを使用して調査結果を記録してください：

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
    "中間URL",
    "最終URL"
  ]
}
```

### 3. 調査結果を比較

`scripts/dev/compare_browser_request.py`を使用して、ブラウザのリクエストとコードのリクエストを比較してください。

## 修正案

調査結果に基づいて、以下の修正を検討してください：

### 修正案1: 詳細ページから直接ダウンロードURLを取得

現在、詳細ページのHTMLから直接`KokaiBunshoServlet`のURLを抽出していますが、実際のブラウザではJavaScriptで動的に生成されている可能性があります。

**修正案**:
```python
def extract_download_url_from_detail_page(self, detail_soup, base_url):
    """詳細ページからダウンロードURLを取得（JavaScript実行後の状態を想定）"""
    # JavaScript変数からAnkenkanriNoとBunshoKanriIdを取得
    # その後、正しいURLを構築
    pass
```

### 修正案2: Cookieを手動で設定

別ドメインにCookieを送信する必要がある場合、Cookieを手動で設定します。

**修正案**:
```python
# e-bisc.go.jpにも送信されるCookieを設定
cookie = Cookie(
    version=0,
    name='セッション名',
    value='セッション値',
    domain='.e-bisc.go.jp',  # サブドメインにも送信
    path='/',
    secure=True
)
http_client.session.cookies.set_cookie(cookie)
```

### 修正案3: 中継URLを経由

詳細ページから直接ダウンロードできない場合、中継URLを経由します。

**修正案**:
```python
# 詳細ページ → 中継URL → ダウンロード
# 中継URLは、詳細ページのHTMLまたはJavaScriptから取得
intermediate_url = extract_intermediate_url(detail_soup)
response = http_client.get(intermediate_url)
# レスポンスから実際のダウンロードURLを取得
download_url = extract_download_url_from_response(response)
```

### 修正案4: Seleniumを使用（最後の手段）

JavaScriptの実行が必要な場合、Seleniumを使用します。

**修正案**:
```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = webdriver.Chrome()
driver.get(detail_url)
# ダウンロードリンクをクリック
download_link = WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'KokaiBunshoServlet')]"))
)
actual_download_url = download_link.get_attribute('href')
```

## 推奨される手順

1. **まずブラウザで調査**（最重要）
   - 開発者ツールで実際のリクエストを確認
   - 調査結果を記録

2. **調査結果を分析**
   - ブラウザとコードの差異を特定
   - 不足しているヘッダー、Cookie、パラメータを特定

3. **修正を実装**
   - 調査結果に基づいてコードを修正
   - 修正案1-3を順番に試す
   - それでも解決しない場合は修正案4を検討

4. **テスト**
   - 修正後に再度ダウンロードテストを実行
   - 成功するまで繰り返し

## 注意事項

- **ネットワーク問題の可能性**: タイムアウトが発生している場合、コードの問題だけでなく、ネットワーク環境（ファイアウォール、プロキシ）の問題も考えられます
- **サーバー側の制限**: サーバー側で特定の条件（リファラー、Cookie等）を満たさないと接続を拒否する可能性があります
- **セキュリティ**: 実際のブラウザでの動作を正確に再現する必要があります
