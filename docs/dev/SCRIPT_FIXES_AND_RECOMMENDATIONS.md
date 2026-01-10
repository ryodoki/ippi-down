# 自動スクリプトの修正と推奨事項

## 実行結果の分析

### ✅ 成功した部分
1. **Edgeブラウザの起動**: 成功
2. **検索ページへのアクセス**: 成功
3. **検索条件の設定**: 成功
4. **検索の実行**: 成功
5. **詳細ページを開く**: 成功（修正後）
6. **パフォーマンスログの取得**: 成功（199件のログを取得）

### ❌ 発見した問題

#### 問題1: ElementClickInterceptedException
**状況**: 詳細ページへのリンクをクリックしようとした際、ソートリンクが邪魔をしてクリックできない

**原因**: 
- XPathで`__doPostBack`を含むリンクを検索した際、ソートリンク（`Sort$`を含む）も含まれていた
- ソートリンクが最初に見つかり、他の要素がクリックを妨害

**修正内容**:
- ✅ ソートリンクを除外する条件を追加
- ✅ 複数の方法でリンクを検索
- ✅ JavaScriptクリックを使用（より確実）

**コード変更**:
```python
# ソートリンクを除外
links = driver.find_elements(By.XPATH, "//table[@id='dgrSearchList']//a[contains(@href, '__doPostBack')]")
for link in links:
    href = link.get_attribute("href") or ""
    if "__doPostBack" in href and "Sort$" not in href:
        first_link = link
        break

# JavaScriptクリックを使用
driver.execute_script("arguments[0].click();", first_link)
```

#### 問題2: EOFError（非対話的環境）
**状況**: 非対話的環境で`input()`を呼び出すとEOFErrorが発生

**原因**: 自動実行時に標準入力が利用できない

**修正内容**:
- ✅ `input()`を`try-except`で囲む
- ✅ 非対話的環境では自動的に次のステップに進む
- ✅ 待機時間を追加して手動操作の時間を確保

**コード変更**:
```python
try:
    _ = input("  検索条件を設定したら、Enterキーを押してください...")
except EOFError:
    print("  [INFO] 非対話的環境のため、自動的に次のステップに進みます...")
    time.sleep(5)
```

#### 問題3: PDFリクエストが見つからない（0件）
**状況**: パフォーマンスログからPDFファイル関連のリクエストを抽出できていない

**考えられる原因**:
1. **ダウンロードリンクがまだクリックされていない**
   - 自動操作が失敗している可能性
   - 手動操作が必要な可能性

2. **ログの解析方法が適切でない**
   - Edgeのログ形式がChromeと異なる可能性
   - ログの検索条件が狭すぎる可能性

3. **ログが記録される前に取得している**
   - ダウンロードリンクをクリックした直後にログを取得している
   - リクエストが記録されるまで十分な時間を確保できていない

**修正内容**:
- ✅ より広範囲な検索条件を追加（`e-bisc.go.jp`, `e2ppiw01`, `servlet`など）
- ✅ 待機時間を15秒に延長
- ✅ すべてのネットワークリクエストを記録してデバッグ情報を出力
- ✅ 新しいタブが開かれた場合の処理を追加

**コード変更**:
```python
# より広範囲な検索条件
pdf_keywords = [
    'kokaiBunshoServlet',
    'publish',
    'download',
    '.pdf',
    'e-bisc.go.jp',
    'e2ppiw01',
    'servlet'
]

# 待機時間を15秒に延長
time.sleep(15)

# 新しいタブのチェック
if len(driver.window_handles) > 1:
    # すべてのタブを確認
    ...
```

## 修正提案

### 修正提案1: ログの取得タイミングを改善（優先度: 高）

**問題**: ダウンロードリンクをクリックした直後にログを取得しているため、リクエストが記録される前に取得している可能性

**修正案**:
```python
# ダウンロードリンクをクリック
download_link.click()

# ログを取得する前に、リクエストが記録されるまで待機
print("  リクエストが記録されるまで待機...")
for i in range(30):  # 30秒間、1秒ごとにチェック
    time.sleep(1)
    # ログを取得して、PDFリクエストが含まれているか確認
    logs = driver.get_log('performance')
    # PDFリクエストを探す
    if find_pdf_request_in_logs(logs):
        print(f"  PDFリクエストを発見（{i+1}秒後）")
        break
else:
    print("  30秒待機してもPDFリクエストが見つかりませんでした")
```

### 修正提案2: CDPを使用したネットワークログの取得（優先度: 高）

**問題**: パフォーマンスログからPDFリクエストを抽出できていない

**修正案**:
- Chrome DevTools Protocol (CDP) を使用してネットワークログを取得
- `Network.enable`でネットワークログを有効化
- `Network.requestWillBeSent`と`Network.responseReceived`イベントをリスニング

**実装**: `scripts/dev/capture_browser_cdp.py`を作成済み

### 修正提案3: 手動操作モードの改善（優先度: 中）

**問題**: 自動操作が失敗した場合、ユーザーが手動で操作する必要があるが、ログの記録タイミングが適切でない

**修正案**:
```python
print("  手動でファイルダウンロードリンクをクリックしてください")
print("  クリックしたら、Enterキーを押してください...")
try:
    _ = input()
except EOFError:
    print("  [INFO] 非対話的環境のため、30秒待機します...")
    time.sleep(30)

# クリック後にログを取得
logs = driver.get_log('performance')
```

### 修正提案4: スクリーンショットの自動保存（優先度: 中）

**問題**: どの段階で問題が発生しているか特定しにくい

**修正案**:
```python
# 各ステップでスクリーンショットを保存
screenshot_dir = Path("screenshots")
screenshot_dir.mkdir(parents=True, exist_ok=True)

# ステップ1後
driver.save_screenshot(str(screenshot_dir / "step1_search_page.png"))

# ステップ2後
driver.save_screenshot(str(screenshot_dir / "step2_search_results.png"))

# ステップ3後
driver.save_screenshot(str(screenshot_dir / "step3_detail_page.png"))

# ステップ4後
driver.save_screenshot(str(screenshot_dir / "step4_after_click.png"))
```

### 修正提案5: より詳細なログ出力（優先度: 低）

**問題**: デバッグが困難

**修正案**:
```python
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('capture_browser_debug.log'),
        logging.StreamHandler()
    ]
)
```

## 実装済みの修正

### ✅ 修正1: 詳細ページへのリンクのクリック改善
- ソートリンクを除外
- 複数の方法でリンクを検索
- JavaScriptクリックを使用
- スクロールして要素を表示

### ✅ 修正2: 非対話的環境でのinput()処理
- `try-except`で囲む
- 非対話的環境では自動的に次のステップに進む

### ✅ 修正3: PDFリクエストの検出改善
- より広範囲な検索条件を追加
- すべてのネットワークリクエストを記録
- デバッグ情報を出力

### ✅ 修正4: 待機時間の延長
- ダウンロードリンクのクリック後、15秒待機
- 新しいタブが開かれた場合の処理を追加

## 次のステップ

### 最優先: 手動操作での確認

**推奨される方法**:
1. スクリプトを実行してブラウザを開く
2. 手動で操作する（検索、詳細ページを開く、ファイルをダウンロード）
3. 操作完了後にEnterキーを押す
4. ログを取得して分析

**手動操作モードの改善スクリプト**: `scripts/dev/capture_browser_cdp.py`

### 次に優先: CDPを使用したネットワークログの取得

**推奨される方法**:
1. CDPを使用してネットワークログを有効化
2. `Network.requestWillBeSent`と`Network.responseReceived`イベントをリスニング
3. PDF関連のリクエストを自動的に記録

**実装済みスクリプト**: `scripts/dev/capture_browser_cdp.py`

### その他: スクリーンショットの自動保存

**推奨される方法**:
- 各ステップでスクリーンショットを保存
- 問題の特定を容易にする

## まとめ

### 修正完了項目
- ✅ ElementClickInterceptedExceptionの対処
- ✅ 非対話的環境でのinput()処理
- ✅ PDFリクエストの検出条件の拡張
- ✅ 待機時間の延長
- ✅ 新しいタブの処理

### 残っている課題
- ❌ PDFリクエストの抽出（0件）
- ⚠️ ログの取得タイミング（改善が必要）
- ⚠️ ダウンロードリンクの自動クリック（手動操作が必要な可能性）

### 推奨される次のアクション
1. **手動操作モードで確認**（最重要）
   - スクリプトを実行してブラウザを開く
   - 手動で操作する
   - 操作完了後にログを取得

2. **CDPを使用したネットワークログの取得を試す**
   - `capture_browser_cdp.py`を実行
   - より確実にリクエストを記録できる可能性

3. **スクリーンショットの自動保存を実装**
   - 問題の特定を容易にする
