# 中分類POSTバック後のレスポンス分析結果

**分析日**: 2026年1月13日

---

## 重要な発見

### 1. JavaScript関数の定義

レスポンスのHTMLには以下のJavaScript関数が定義されています：

- **`setListItemSub(SEL, LIST)`** (行22-38)
  - ドロップダウンに選択肢を動的に追加する関数
  - `LIST`は`['value:text', 'value:text', ...]`の形式
  - しかし、実際の呼び出し（`setListItemSub('drpMiddleKikanInf', [...])`）はレスポンスに含まれていない

### 2. select要素のonchange属性

中分類のselect要素には以下のonchange属性が設定されています：

```html
<select id="drpLargeKikanInf2" onchange="createListItem2('drpLargeKikanInf2','txtLgKikanInfSelValue_h','txtLgKikanInf2SelIndex_h');setTimeout('__doPostBack(\'drpLargeKikanInf2\',\'\')', 0)">
```

- **`createListItem2()`** が呼び出されている
- この関数は`Common.js`から読み込まれる
- `txtLgKikanInf2SelIndex_h`というhiddenフィールドが使用されている

### 3. 小分類のselect要素

小分類のselect要素には選択肢が1個（デフォルト値のみ）しかありません：

```html
<select id="drpMiddleKikanInf" onchange="javascript:setTimeout('__doPostBack(\'drpMiddleKikanInf\',\'\')', 0)">
  <option selected="selected" value="-1">▽小分類</option>
</select>
```

### 4. hiddenフィールドの状態

中分類のPOSTバック後のhiddenフィールド：

- `txtLargeKikanInf_h`: 初期ページと同じ値（小分類のデータが含まれていない）
- `txtLgKikanInf2SelIndex_h`: 空文字列
- `txt_ChangeLargeKikan`: 'true'

---

## 問題の原因

小分類の選択肢がHTMLに含まれていない理由：

1. **JavaScriptで動的に読み込まれる**
   - `createListItem2()`関数が`Common.js`から読み込まれ、`txtLargeKikanInf_h`から小分類の選択肢を取得している可能性
   - しかし、実際の呼び出しはブラウザ側で実行されるため、レスポンスには含まれない

2. **別のhiddenフィールドが必要**
   - `txtLgKikanInf2SelIndex_h`が正しく設定されていない可能性
   - HARファイルでは`txtLgKikanInf2SelIndex_h: '4'`が設定されている

3. **POSTバックのパラメータが不足**
   - 中分類のPOSTバック時に、すべての必要なパラメータが送信されていない可能性

---

## 次のステップ

1. **`Common.js`を確認**
   - `createListItem2()`関数の実装を確認
   - どのように小分類の選択肢を取得しているかを特定

2. **`txtLgKikanInf2SelIndex_h`の設定**
   - 中分類のPOSTバック時に、このフィールドを正しく設定する必要がある
   - HARファイルでは`'4'`が設定されている

3. **代替アプローチ: 検索結果ページでフィルタリング**
   - 検索条件に一致しない案件を除外する
   - これは確実に動作する方法

---

## 結論

中分類のPOSTバック後のレスポンスには、小分類の選択肢がHTMLに含まれていません。これは、小分類の選択肢がJavaScriptで動的に読み込まれることを示しています。

`createListItem2()`関数が`Common.js`から読み込まれ、`txtLargeKikanInf_h`から小分類の選択肢を取得している可能性が高いです。しかし、この関数の実装を確認する必要があります。

---

**最終更新**: 2026年1月13日
