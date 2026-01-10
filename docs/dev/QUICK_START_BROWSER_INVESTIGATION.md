# ブラウザ調査クイックスタート

## 簡単な手順

### ステップ1: ブラウザを開く
1. ChromeまたはEdgeを開く
2. `F12`キーで開発者ツールを開く
3. 「Network」（ネットワーク）タブを開く
4. **「Preserve log」（ログを保持）にチェックを入れる** ⚠️ 重要

### ステップ2: サイトにアクセスしてファイルをダウンロード

1. 以下のURLにアクセス:
   ```
   https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4
   ```

2. 検索条件を設定:
   - 発注機関: 「国の機関」を選択
   - 「検索開始」をクリック

3. 検索結果から1件をクリックして詳細ページを開く

4. 詳細ページで「公告文書」または「経過文書」タブのファイルをクリック

### ステップ3: ネットワークタブでリクエストを確認

1. **PDFファイルのリクエストを探す**
   - `KokaiBunshoServlet`を含むリクエスト
   - Content-Typeが`application/pdf`のリクエスト
   - ファイル名に`.pdf`が含まれるリクエスト

2. **リクエストをクリックして選択**

### ステップ4: リクエスト情報を記録

#### Generalタブ
- Request URL（最終的なURL、リダイレクト後）をコピー
- Status Codeを確認

#### Headersタブ
- **Request Headers**（リクエストヘッダー）をすべてコピー
  - 特に重要なヘッダー:
    - `Referer`
    - `Origin`
    - `Cookie`
    - `Sec-Fetch-*`

- **Response Headers**（レスポンスヘッダー）を確認
  - `Content-Type`
  - `Content-Length`

#### リダイレクトがある場合
- Generalタブの下に「Redirects」が表示される
- すべてのリダイレクトURLを記録

### ステップ5: 調査結果を記録

`docs/dev/browser_request_template.json`を開いて、以下の情報を記入:

```json
{
  "request_info": {
    "url": "ここに実際のURLを貼り付け",
    "method": "GET",
    "request_headers": {
      "Referer": "ここにRefererヘッダーを貼り付け",
      "Cookie": "ここにCookieヘッダーを貼り付け",
      "Origin": "ここにOriginヘッダーを貼り付け",
      "Sec-Fetch-Site": "ここにSec-Fetch-Siteヘッダーを貼り付け"
    },
    "redirects": [
      "最初のURL",
      "最終URL"
    ]
  }
}
```

### ステップ6: 分析

以下のコマンドで分析:

```bash
python scripts/dev/analyze_captured_request.py docs/dev/browser_request_template.json
```

## 重要なポイント

- ✅ **「Preserve log」にチェックを入れる** - リダイレクト後にログが消えないようにする
- ✅ **ファイルダウンロード前にネットワークタブを開く** - リクエストを見逃さないようにする
- ✅ **すべてのヘッダーを記録** - 特に`Referer`、`Cookie`、`Origin`が重要
- ✅ **リダイレクトチェーンを記録** - 中継URLを経由している可能性がある

## トラブルシューティング

### リクエストが見つからない場合
- 「Preserve log」にチェックが入っているか確認
- ネットワークタブのフィルタで`pdf`を検索
- ファイルダウンロードリンクをクリックする前にネットワークタブを開いているか確認

### リダイレクトが見つからない場合
- 「Preserve log」にチェックが入っているか確認
- Generalタブの下に「Redirects」が表示されるか確認

## 次のステップ

調査結果を記録したら:
1. `analyze_captured_request.py`で分析
2. 差異を確認
3. コードを修正
4. 再度テスト

詳細な手順は `docs/dev/BROWSER_MANUAL_INVESTIGATION.md` を参照してください。
