# 小分類・細分類取得の調査手順書

## 目的
「国の機関」の大分類で、中分類→小分類→細分類が実際に存在するにもかかわらず、現在の実装では取得できていない原因を特定する。

## 必要な情報

### 1. ブラウザでの実際の動作確認

#### 手順
1. **ブラウザで実際のサイトにアクセス**
   - URL: `https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4`
   - ブラウザ: Chrome または Edge（開発者ツールが使いやすい）

2. **発注機関（リスト検索）の階層を確認**
   - 大分類: 「国の機関」を選択
   - 中分類: 任意の中分類（例：「内閣府沖縄総合事務局」）を選択
   - 小分類: 選択可能なオプションが表示されるか確認
   - 細分類: 小分類を選択した後、選択可能なオプションが表示されるか確認

### 2. 開発者ツールでの確認項目

#### 2.1 ネットワークタブ（Network Tab）

**確認手順:**
1. ブラウザの開発者ツールを開く（F12キー）
2. 「Network」タブを開く
3. 「XHR」または「Fetch」フィルタを選択
4. 大分類「国の機関」を選択
5. 中分類「内閣府沖縄総合事務局」を選択
6. 小分類が表示されるまで、すべてのネットワークリクエストを記録

**確認すべき情報:**
- **POSTリクエストのURL**: どのURLにPOSTしているか
- **POSTリクエストのパラメータ**: 
  - `__EVENTTARGET`の値
  - `__VIEWSTATE`の値
  - `__EVENTVALIDATION`の値（存在する場合）
  - `drpTopKikanInf`の値
  - `drpLargeKikanInf2`の値
  - その他のhidden inputの値
- **POSTレスポンスの内容**:
  - HTMLの内容
  - JavaScriptコード（`setListItemSub`の呼び出しがあるか）
  - hidden inputの値（特に`txtLargeKikanInf_h`の値が変化しているか）

**具体的な確認方法:**
```
1. 中分類を選択したPOSTリクエストをクリック
2. 「Headers」タブで「Request Payload」または「Form Data」を確認
3. 「Response」タブでレスポンスのHTMLを確認
4. 「Preview」タブでレンダリングされたHTMLを確認
```

#### 2.2 コンソールタブ（Console Tab）

**確認手順:**
1. 「Console」タブを開く
2. 中分類を選択
3. コンソールに出力されるエラーや警告を確認
4. `setListItemSub`や`createListItem2`などの関数が呼び出されているか確認

**確認すべき情報:**
- JavaScriptエラーがないか
- `setListItemSub`の呼び出しと引数
- `createListItem2`の呼び出しと引数
- 変数の値（特に`txtLargeKikanInf_h`の値）

**具体的な確認方法:**
```javascript
// コンソールで実行して確認
console.log(document.getElementById('txtLargeKikanInf_h').value);
console.log(document.getElementById('drpMiddleKikanInf').options.length);
console.log(document.getElementById('drpSmallKikanInf').options.length);
```

#### 2.3 Elementsタブ（DOM確認）

**確認手順:**
1. 「Elements」タブを開く
2. 中分類を選択した後、小分類のドロップダウン（`drpMiddleKikanInf`）を検索
3. `<select>`要素とその`<option>`要素を確認

**確認すべき情報:**
- `<select name="drpMiddleKikanInf">`の`<option>`要素の数
- 各`<option>`の`value`属性とテキスト内容
- `onchange`属性の値（どのJavaScript関数が呼ばれるか）

**具体的な確認方法:**
```
1. Elementsタブで「drpMiddleKikanInf」を検索（Ctrl+F）
2. <select>要素を展開して<option>要素を確認
3. 各<option>のvalue属性とテキストを記録
```

### 3. 実際のPOSTリクエスト/レスポンスの取得

#### 3.1 ネットワークタブからリクエストをコピー

**手順:**
1. 中分類を選択したPOSTリクエストを右クリック
2. 「Copy」→「Copy as cURL」を選択
3. または「Copy」→「Copy request headers」と「Copy request body」を選択

#### 3.2 レスポンスの保存

**手順:**
1. POSTリクエストをクリック
2. 「Response」タブを開く
3. レスポンスのHTMLをコピーしてファイルに保存
4. ファイル名: `response_after_chubunrui_selection.html`

### 4. JavaScriptコードの実行状況確認

#### 4.1 ブレークポイントの設定

**手順:**
1. 「Sources」タブを開く
2. `Common.js`ファイルを開く
3. `getListItemStr`関数にブレークポイントを設定
4. `createListItem1_3`関数にブレークポイントを設定
5. `createListItem2`関数にブレークポイントを設定
6. 中分類を選択して、どの関数が呼ばれるか確認

#### 4.2 変数の値を確認

**確認すべき変数:**
- `txtLargeKikanInf_h`の値（中分類選択前後で変化するか）
- `drpMiddleKikanInf`の`options`配列
- `drpSmallKikanInf`の`options`配列

### 5. 実際のサイトでの動作フロー確認

#### 5.1 大分類選択時の動作

**確認項目:**
- `createListItem1_3`が呼ばれるか
- `txtLargeKikanInf_h`の値が更新されるか
- 中分類のドロップダウンが更新されるか

#### 5.2 中分類選択時の動作

**確認項目:**
- `createListItem2`が呼ばれるか
- `__doPostBack('drpLargeKikanInf2', '')`が実行されるか
- POSTリクエストが送信されるか
- レスポンスで小分類のドロップダウンが更新されるか
- `setListItemSub`が呼ばれるか（呼ばれる場合、引数は何か）

#### 5.3 小分類選択時の動作

**確認項目:**
- `__doPostBack('drpMiddleKikanInf', '')`が実行されるか
- POSTリクエストが送信されるか
- レスポンスで細分類のドロップダウンが更新されるか
- `setListItemSub`が呼ばれるか（呼ばれる場合、引数は何か）

### 6. 必要な情報のリスト

調査結果として、以下の情報を提供してください：

#### 6.1 ネットワークリクエスト情報
- [ ] 中分類選択時のPOSTリクエストのURL
- [ ] POSTリクエストのすべてのパラメータ（Form Data）
- [ ] POSTレスポンスのHTML（完全な内容）
- [ ] 小分類選択時のPOSTリクエストのURL
- [ ] 小分類選択時のPOSTリクエストのすべてのパラメータ
- [ ] 小分類選択時のPOSTレスポンスのHTML

#### 6.2 JavaScript実行情報
- [ ] 中分類選択時に呼ばれるJavaScript関数のリスト
- [ ] `setListItemSub`が呼ばれる場合、その引数（IDと配列の内容）
- [ ] `txtLargeKikanInf_h`の値（中分類選択前後）
- [ ] 小分類のドロップダウンの`<option>`要素の数と内容

#### 6.3 DOM情報
- [ ] 中分類選択後の`drpMiddleKikanInf`の`<option>`要素の完全なリスト
- [ ] 小分類選択後の`drpSmallKikanInf`の`<option>`要素の完全なリスト

### 7. 調査用スクリプト

以下の情報を取得するためのスクリプトを用意します：

```python
# 調査用スクリプト: test_browser_simulation.py
# 実際のブラウザの動作を再現して、不足している情報を特定
```

### 8. 確認すべきポイント

1. **`__EVENTVALIDATION`の有無**
   - 現在の実装では`__EVENTVALIDATION`が見つからないと警告が出ている
   - 実際のブラウザでは`__EVENTVALIDATION`が存在するか確認

2. **POSTリクエストのタイミング**
   - 中分類選択時に、即座にPOSTリクエストが送信されるか
   - それとも、JavaScriptで処理された後にPOSTリクエストが送信されるか

3. **小分類データの取得方法**
   - `txtLargeKikanInf_h`から取得できるか
   - 別のhidden inputから取得する必要があるか
   - POSTレスポンスのHTMLに直接含まれているか
   - JavaScriptの`setListItemSub`で動的に生成されるか

4. **細分類データの取得方法**
   - 小分類選択後のPOSTレスポンスに含まれているか
   - 別の方法で取得する必要があるか

## 調査結果の報告形式

以下の形式で調査結果を報告してください：

```
### 調査結果

#### 1. ネットワークリクエスト
- 中分類選択時のPOST URL: [URL]
- POSTパラメータ: [パラメータのリスト]
- レスポンスのHTML: [ファイルパスまたは内容の一部]

#### 2. JavaScript実行
- 呼ばれる関数: [関数名のリスト]
- setListItemSubの呼び出し: [有無と引数]

#### 3. DOM状態
- 小分類のオプション数: [数]
- 小分類のオプション: [オプションのリスト]

#### 4. 不足している情報
- [不足している情報のリスト]
```

## 次のステップ

調査結果に基づいて、不足している情報を特定し、実装を修正します。

