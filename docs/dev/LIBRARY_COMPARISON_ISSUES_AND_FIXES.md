# ライブラリ比較スクリプトの問題点と修正方針

## 実行結果の確認

### ✅ 成功した点
- すべてのライブラリ（requests、Selenium、Playwright）でテストが実行された
- 各ライブラリでページへのアクセスに成功
- JSONレポートが正常に生成された

### ❌ 発見された問題点

#### 1. UnicodeEncodeError（Windowsコンソール出力）
**問題**: Windowsコンソール（cp932）でUnicode文字（✓、✗）を出力しようとしてエラーが発生

**現状**: 部分的に修正済みだが、出力が文字化けしている

#### 2. ダウンロード可能性の判定が不正確
**問題**: 
- SeleniumとPlaywrightで`download_possible: false`になっている
- 検索ページには直接PDFリンクがないため、判定ロジックが適切でない可能性

**現状**: 
- requests: `download_possible: true`（Content-Typeで判定）
- Selenium: `download_possible: false`（リンク検出で判定）
- Playwright: `download_possible: false`（リンク検出で判定）

#### 3. スコアリングロジックの改善余地
**問題**: 
- 動的コンテンツがある場合、JavaScript実行能力が重要だが、スコアリングがそれを十分に反映していない可能性
- 実際のダウンロードページ（詳細ページ）でのテストが必要

**現状**: 
- requests: 8点
- Selenium: 8点
- Playwright: 7点

## 修正方針

### 修正方針1: Unicode出力の問題を完全に解決（推奨）

**方法A: ASCII文字のみを使用**
```python
# Unicode文字の代わりにASCII文字を使用
status = "[OK] 成功" if result.success else "[NG] 失敗"
```

**方法B: UTF-8出力を強制**
```python
# スクリプト冒頭でエンコーディングを設定
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
```

**方法C: 環境変数でUTF-8を設定**
```python
# PowerShellで実行前に設定
$env:PYTHONIOENCODING = "utf-8"
python scripts/dev/compare_libraries.py
```

**推奨**: 方法A（ASCII文字のみ）が最も確実で、環境に依存しない

---

### 修正方針2: ダウンロード可能性の判定を改善

**方法A: より詳細なリンク検出**
```python
# Selenium/Playwrightで、より広範囲なリンクパターンを検出
# - PDFリンク（.pdf）
# - Excelリンク（.xlsx, .xls）
# - Wordリンク（.docx, .doc）
# - JavaScriptリンク（__doPostBack）
# - ダウンロード関連のボタン/リンク
download_elements = driver.find_elements(By.XPATH, 
    "//a[contains(@href, '.pdf') or contains(@href, '.xlsx') or "
    "contains(@href, '.docx') or contains(@onclick, 'download') or "
    "contains(@href, 'download')]")
```

**方法B: 実際のダウンロードページでテスト**
```python
# 検索ページではなく、実際のファイルダウンロードページでテスト
# 例: 詳細ページや直接ダウンロードURL
target_url = "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?..."
```

**方法C: 複数ページでテスト**
```python
# 検索ページと詳細ページの両方でテスト
# 検索ページ: リンクの存在を確認
# 詳細ページ: 実際のダウンロードを試行
```

**推奨**: 方法A + 方法B（詳細ページでのテストを追加）

---

### 修正方針3: スコアリングロジックの改善

**方法A: 動的コンテンツの重要性を反映**
```python
# 動的コンテンツがある場合、JavaScript実行能力により高いスコアを付与
if result.dynamic_content:
    if result.has_javascript:
        score += 3  # JavaScript実行可能な場合、高評価
    else:
        score -= 1  # JavaScript実行不可な場合、減点
```

**方法B: 応答時間の重みを調整**
```python
# 応答時間の重みを下げ、機能性を重視
if result.response_time < 2:
    score += 2  # 3から2に減らす
elif result.response_time < 5:
    score += 1  # 2から1に減らす
else:
    score += 0  # 1から0に減らす
```

**方法C: 実装の容易さの重みを調整**
```python
# 実装の容易さの重みを下げ、機能性を重視
if result.implementation_complexity == "low":
    score += 2  # 3から2に減らす
elif result.implementation_complexity == "medium":
    score += 2  # 2のまま
else:
    score += 1  # 1のまま
```

**推奨**: 方法A（動的コンテンツがある場合のJavaScript実行能力を重視）

---

### 修正方針4: 実際のダウンロードフローをテスト

**方法A: エンドツーエンドテストを追加**
```python
# 1. 検索ページにアクセス
# 2. 検索条件を設定
# 3. 検索結果から詳細ページへのリンクを取得
# 4. 詳細ページにアクセス
# 5. ダウンロードリンクを取得
# 6. ダウンロードを試行
```

**方法B: 既知のダウンロードURLでテスト**
```python
# 実際に動作することが確認されているダウンロードURLを使用
# 例: 過去に成功したダウンロードURL
known_download_urls = [
    "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?...",
    # ...
]
```

**推奨**: 方法A（エンドツーエンドテスト）が最も実用的

---

### 修正方針5: エラーハンドリングの改善

**方法A: より詳細なエラーメッセージ**
```python
# エラーの種類に応じて詳細なメッセージを表示
except TimeoutException as e:
    result.error_message = f"タイムアウト（{self.timeout}秒）: {str(e)}"
except ConnectionError as e:
    result.error_message = f"接続エラー: {str(e)}"
except Exception as e:
    result.error_message = f"予期しないエラー: {type(e).__name__}: {str(e)}"
```

**方法B: リトライ機能の追加**
```python
# 失敗した場合に自動的にリトライ
max_retries = 3
for attempt in range(max_retries):
    try:
        # テスト実行
        break
    except Exception as e:
        if attempt < max_retries - 1:
            time.sleep(2)
            continue
        raise
```

**推奨**: 方法A（詳細なエラーメッセージ）がデバッグに有効

---

## 推奨される修正の優先順位

### 優先度1（必須）
1. **Unicode出力の問題を完全に解決**（修正方針1-方法A）
   - すべてのUnicode文字をASCII文字に置き換え
   - 環境に依存しない確実な修正

### 優先度2（重要）
2. **ダウンロード可能性の判定を改善**（修正方針2-方法A + 方法B）
   - より詳細なリンク検出ロジック
   - 実際のダウンロードページでのテストを追加

3. **スコアリングロジックの改善**（修正方針3-方法A）
   - 動的コンテンツがある場合のJavaScript実行能力を重視

### 優先度3（推奨）
4. **エンドツーエンドテストの追加**（修正方針4-方法A）
   - 実際のダウンロードフロー全体をテスト

5. **エラーハンドリングの改善**（修正方針5-方法A）
   - より詳細なエラーメッセージ

---

## 実装例

### 修正例1: Unicode文字をASCII文字に置き換え

```python
# 修正前
status = "✓ 成功" if result.success else "✗ 失敗"

# 修正後
status = "[OK] 成功" if result.success else "[NG] 失敗"
```

### 修正例2: ダウンロード可能性の判定改善

```python
# Selenium
download_elements = driver.find_elements(By.XPATH, 
    "//a[contains(@href, '.pdf') or contains(@href, '.xlsx') or "
    "contains(@href, '.docx') or contains(@href, 'download') or "
    "contains(@onclick, '__doPostBack')]")
result.download_possible = len(download_elements) > 0

# または、ページソースから検出
page_source = driver.page_source.lower()
result.download_possible = any([
    '.pdf' in page_source,
    '.xlsx' in page_source,
    '.docx' in page_source,
    'download' in page_source,
    '__dopostback' in page_source
])
```

### 修正例3: スコアリングロジックの改善

```python
# 動的コンテンツがある場合の処理
if result.dynamic_content:
    if result.has_javascript:
        score += 3  # JavaScript実行可能な場合、高評価
    else:
        score -= 1  # JavaScript実行不可な場合、減点
        # ただし、requestsでも動的コンテンツを検出できる場合は減点しない
        if result.library_name == "requests" and result.dynamic_content:
            score += 0  # 減点しない
```

---

**作成日**: 2026年1月11日  
**ステータス**: 問題点を特定、修正方針を提示
