# 自動スクリプトの問題と修正提案

## 実行結果の分析

### ✅ 成功した部分
1. **Edgeブラウザの起動**: ✅ 成功
2. **検索ページへのアクセス**: ✅ 成功
3. **検索条件の設定**: ✅ 成功
4. **検索の実行**: ✅ 成功
5. **詳細ページを開く**: ✅ 成功（修正後）
6. **パフォーマンスログの取得**: ✅ 成功（199件のログを取得）

### ❌ 発見した問題

#### 問題1: PDFリクエストが見つからない（0件）

**状況**: パフォーマンスログからPDFファイル関連のリクエストを抽出できていない

**分析**:
- ログには`Network.requestWillBeSent`と`Network.responseReceived`が記録されている
- ただし、検索結果ページまでのリクエストのみが記録されている
- **詳細ページやダウンロードリンクのクリック後のリクエストが記録されていない**

**考えられる原因**:
1. **ダウンロードリンクがまだクリックされていない**
   - 自動操作が失敗している可能性
   - リンクが見つからない、またはクリックできない状態

2. **ログの取得タイミングが早すぎる**
   - ダウンロードリンクをクリックした直後にログを取得している
   - リクエストが記録される前に取得している可能性

3. **ログの解析方法が適切でない**
   - Edgeのログ形式がChromeと異なる可能性
   - ログの検索条件が狭すぎる可能性

#### 問題2: ElementClickInterceptedException（修正済み）

**状況**: 詳細ページへのリンクをクリックしようとした際、ソートリンクが邪魔をしてクリックできない

**修正内容**: ✅ 修正済み
- ソートリンクを除外する条件を追加
- JavaScriptクリックを使用
- スクロールして要素を表示

#### 問題3: EOFError（修正済み）

**状況**: 非対話的環境で`input()`を呼び出すとEOFErrorが発生

**修正内容**: ✅ 修正済み
- `input()`を`try-except`で囲む
- 非対話的環境では自動的に次のステップに進む

## 修正実装済み項目

### ✅ 修正1: 詳細ページへのリンクのクリック改善
- ソートリンク（`Sort$`を含む）を除外
- 複数の方法でリンクを検索
- スクロールして要素を表示
- JavaScriptクリックを使用（より確実）

### ✅ 修正2: 非対話的環境でのinput()処理
- `try-except`で囲む
- 非対話的環境では自動的に次のステップに進む
- 待機時間を追加して手動操作の時間を確保

### ✅ 修正3: PDFリクエストの検出改善
- より広範囲な検索条件を追加（`e-bisc.go.jp`, `e2ppiw01`, `servlet`など）
- すべてのネットワークリクエストを記録（デバッグ用）
- デバッグ情報を出力（最初の30件を表示）

### ✅ 修正4: 待機時間の延長と新しいタブの処理
- ダウンロードリンクのクリック後、15秒待機（10秒から延長）
- 新しいタブが開かれた場合の処理を追加
- すべてのタブを確認してリクエストを記録

## 追加修正提案

### 修正提案1: ログの取得タイミングを改善（優先度: 高）

**問題**: ダウンロードリンクをクリックした直後にログを取得しているため、リクエストが記録される前に取得している可能性

**修正案**:
```python
# ダウンロードリンクをクリック
download_link.click()

# ログを取得する前に、リクエストが記録されるまで待機（ポーリング方式）
print("  リクエストが記録されるまで待機...")
max_wait_time = 30  # 最大30秒
wait_interval = 1  # 1秒ごとにチェック
start_time = time.time()

while time.time() - start_time < max_wait_time:
    time.sleep(wait_interval)
    
    # ログを取得
    current_logs = driver.get_log('performance')
    
    # PDFリクエストを探す
    pdf_found = False
    for log in current_logs:
        try:
            log_message = json.loads(log['message'])
            message = log_message.get('message', {})
            params = message.get('params', {})
            request = params.get('request', {})
            response = params.get('response', {})
            url = request.get('url', '') or response.get('url', '')
            
            if any(keyword in url.lower() for keyword in ['kokaiBunshoServlet', 'e-bisc', 'e2ppiw01']):
                pdf_found = True
                break
        except Exception:
            continue
    
    if pdf_found:
        elapsed = time.time() - start_time
        print(f"  [SUCCESS] PDFリクエストを発見（{elapsed:.1f}秒後）")
        logs = current_logs  # 最新のログを使用
        break
else:
    print(f"  [WARNING] {max_wait_time}秒待機してもPDFリクエストが見つかりませんでした")
    logs = driver.get_log('performance')  # 最後にログを取得
```

### 修正提案2: ダウンロードリンクの検出を改善（優先度: 高）

**問題**: ダウンロードリンクが見つからない、またはクリックできない

**修正案**:
```python
# 複数の方法でダウンロードリンクを探す
download_link = None

# 方法1: KokaiBunshoServletを含むリンクを探す
try:
    download_link = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'KokaiBunshoServlet')]"))
    )
except Exception:
    pass

# 方法2: dgrKokokuまたはdgrKeikaテーブル内のリンクを探す
if not download_link:
    try:
        # まず、テーブルが存在するか確認
        kokoku_table = driver.find_element(By.ID, "dgrKokoku")
        download_link = kokoku_table.find_element(By.XPATH, ".//a[contains(@href, 'KokaiBunshoServlet')]")
    except Exception:
        try:
            keika_table = driver.find_element(By.ID, "dgrKeika")
            download_link = keika_table.find_element(By.XPATH, ".//a[contains(@href, 'KokaiBunshoServlet')]")
        except Exception:
            pass

# 方法3: JavaScript変数からURLを生成
if not download_link:
    try:
        # 詳細ページのJavaScriptからAnkenkanriNoとBunshoKanriIdを抽出
        page_source = driver.page_source
        import re
        anken_match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', page_source)
        bunsho_match = re.search(r'var\s+BunshoKanriId\s*=\s*"([^"]+)"', page_source)
        
        if anken_match and bunsho_match:
            ankenkanri_no = anken_match.group(1)
            bunsho_kanri_id = bunsho_match.group(1)
            download_url = f"https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?AnkenKanriNo={ankenkanri_no}&BunshoKanriId={bunsho_kanri_id}"
            print(f"  JavaScriptからURLを生成: {download_url}")
            # 新しいタブでURLを開く
            driver.execute_script(f"window.open('{download_url}', '_blank');")
            download_link_clicked = True
    except Exception as e:
        print(f"  JavaScriptからのURL生成に失敗: {str(e)}")
```

### 修正提案3: CDPを使用したネットワークログの取得（優先度: 中）

**問題**: パフォーマンスログからPDFリクエストを抽出できていない

**修正案**: CDPを使用して、より確実にネットワークリクエストを記録

**実装済み**: `scripts/dev/capture_browser_cdp.py`

**使用方法**:
```bash
python scripts/dev/capture_browser_cdp.py
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

# ステップ4後（ダウンロードリンククリック後）
driver.save_screenshot(str(screenshot_dir / "step4_after_click.png"))
```

### 修正提案5: より詳細なデバッグ情報の出力（優先度: 低）

**問題**: デバッグが困難

**修正案**:
```python
# すべてのネットワークリクエストを表示（デバッグ用）
print(f"\n[DEBUG] すべてのネットワークリクエスト（{len(all_network_requests)}件）:")
for i, req in enumerate(all_network_requests, 1):
    url_short = req['url'][:100] + "..." if len(req['url']) > 100 else req['url']
    print(f"  {i}. {req['method']}: {url_short}")
    if req['mimeType']:
        print(f"     MimeType: {req['mimeType']}")
    if req['status']:
        print(f"     Status: {req['status']}")
```

## 推奨される次のステップ

### 最優先: 手動操作モードで確認

**推奨される方法**:
1. スクリプトを実行してブラウザを開く
2. 手動で操作する（検索、詳細ページを開く、ファイルをダウンロード）
3. 操作完了後にEnterキーを押す
4. ログを取得して分析

**手動操作モードの改善スクリプト**: `scripts/dev/capture_browser_cdp.py`

### 次に優先: ログの取得タイミングを改善

**推奨される方法**:
- ダウンロードリンクをクリックした後、リクエストが記録されるまでポーリング方式で待機
- 30秒間、1秒ごとにログを確認し、PDFリクエストが含まれているかチェック

### その他: スクリーンショットの自動保存

**推奨される方法**:
- 各ステップでスクリーンショットを保存
- 問題の特定を容易にする

## まとめ

### 修正完了項目
- ✅ ElementClickInterceptedExceptionの対処
- ✅ 非対話的環境でのinput()処理
- ✅ PDFリクエストの検出条件の拡張
- ✅ 待機時間の延長（15秒）
- ✅ 新しいタブの処理

### 残っている課題
- ❌ PDFリクエストの抽出（0件）
  - **原因**: ダウンロードリンクがまだクリックされていない可能性が高い
  - **解決策**: 手動操作モードで確認、またはログの取得タイミングを改善

### 推奨される次のアクション
1. **手動操作モードで確認**（最重要）
   - スクリプトを実行してブラウザを開く
   - 手動で操作する
   - 操作完了後にログを取得

2. **ログの取得タイミングを改善**
   - ポーリング方式でリクエストが記録されるまで待機
   - 30秒間、1秒ごとにチェック

3. **CDPを使用したネットワークログの取得を試す**
   - `capture_browser_cdp.py`を実行
   - より確実にリクエストを記録できる可能性
