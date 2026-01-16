# GUI地方初期値問題修正完了報告

**修正日**: 2026年1月14日

---

## 問題の原因

GUI起動時に「工事場所（リスト検索）」の「地方」ドロップダウンに「北海道」が選択されている問題が発生していました。

### 原因の特定

`ttk.Combobox`の`state="readonly"`の場合、`StringVar`に空文字列を設定しても、Comboboxが空文字列を選択できない可能性があります。`readonly`のComboboxは、`values`リストに含まれていない値を設定しようとすると、最初の有効な値（この場合は「北海道」）が選択される可能性があります。

### 解決方法

`Combobox`の`current()`メソッドを使用して、明示的にインデックス0（空文字列）を選択するようにしました。

---

## 修正内容

### 1. `setup_ui()`の修正

- `place_chihou_combobox`の参照を`self.place_chihou_combobox`として保持
- 初期値が空文字列の場合、`current(0)`を呼び出して明示的に空文字列を選択
- 初期値が設定されている場合、その値のインデックスを探して`current(index)`を呼び出し

```python
self.place_chihou_combobox = ttk.Combobox(
    place_frame,
    textvariable=self.place_chihou_var,
    values=place_chihou_options,
    state="readonly",
    width=30,
)
self.place_chihou_combobox.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
# readonlyのComboboxで空文字列を選択するには、current(0)を使用する必要がある
if not initial_place_chihou:
    self.place_chihou_combobox.current(0)  # 最初の要素（空文字列）を選択
else:
    # 検索条件に値が設定されている場合、その値のインデックスを探す
    try:
        index = place_chihou_options.index(initial_place_chihou)
        self.place_chihou_combobox.current(index)
    except ValueError:
        # 値が見つからない場合は空文字列を選択
        self.place_chihou_combobox.current(0)
```

### 2. `load_config_to_ui()`の修正

- `place_chihou_combobox`の参照を使用して、設定を読み込む際にも`current()`メソッドを使用
- 空文字列の場合は`current(0)`を呼び出し
- 値が設定されている場合、その値のインデックスを探して`current(index)`を呼び出し

```python
# 工事場所（空文字列の場合は明示的に空文字列を設定）
place_chihou_value = search_conditions.place_chihou if search_conditions.place_chihou else ""
# readonlyのComboboxで空文字列を選択するには、current(0)を使用する必要がある
if not place_chihou_value:
    # 空文字列の場合は、Comboboxのcurrent(0)を使用
    self.place_chihou_var.set("")
    if hasattr(self, 'place_chihou_combobox'):
        self.place_chihou_combobox.current(0)
else:
    self.place_chihou_var.set(place_chihou_value)
    # 値が設定されている場合、その値のインデックスを探す
    place_chihou_options = ["", "北海道", "東北", "関東", "北陸", "中部", "近畿", "中国", "四国", "九州・沖縄"]
    try:
        index = place_chihou_options.index(place_chihou_value)
        if hasattr(self, 'place_chihou_combobox'):
            self.place_chihou_combobox.current(index)
    except ValueError:
        # 値が見つからない場合は空文字列を選択
        if hasattr(self, 'place_chihou_combobox'):
            self.place_chihou_combobox.current(0)
```

---

## 修正ファイル

- `src/gui/main_window.py`

---

## テスト項目

1. **GUI起動時の初期値**
   - GUIを起動し、「工事場所（リスト検索）」の「地方」ドロップダウンが空（未選択）になっているか確認

2. **設定ファイルからの読み込み**
   - 設定ファイルに`place_chihou: "北海道"`が設定されている場合、その値が選択されるか確認
   - 設定ファイルに`place_chihou: ""`が設定されている場合、空（未選択）になるか確認

3. **設定の保存と読み込み**
   - GUIで「地方」を選択して設定を保存
   - GUIを再起動して、保存した設定が正しく読み込まれるか確認

---

## 注意事項

- `ttk.Combobox`の`state="readonly"`の場合、`StringVar`に値を設定するだけでは不十分で、`current()`メソッドを使用して明示的にインデックスを指定する必要があります
- 空文字列を選択するには、`current(0)`を使用します（`values`リストの最初の要素が空文字列であることを前提としています）

---

**最終更新**: 2026年1月14日
