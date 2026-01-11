# Playwright実装レポート

## 実装完了状況

### ✅ 完了項目

1. **PlaywrightClientクラスの作成**
   - **ファイル**: `src/utils/playwright_client.py`
   - **機能**: 
     - GET/POSTリクエストの送信
     - ページコンテンツの取得
     - BeautifulSoupオブジェクトの取得
     - ファイルダウンロード（基本実装）
     - セッション管理
     - リトライ機能
   - **動作確認**: ✅ 成功

2. **ScraperPlaywrightクラスの基本実装**
   - **ファイル**: `src/core/scraper_playwright.py`
   - **機能**: 
     - ページ取得
     - BeautifulSoupとの統合
     - メタデータ抽出（基本）
     - ファイルリンク抽出（基本）

3. **環境確認**
   - Playwrightパッケージ: ✅ インストール済み (version: 1.57.0)
   - Chromiumブラウザ: ✅ インストール済み
   - 基本的な動作確認: ✅ 成功

---

## 発見された問題点と修正案

### ⚠️ 問題1: POSTリクエストの実装が不完全

**問題点**:
- `page.request.post()`を使用しているが、フォーム送信後のページ遷移が正しく処理されていない可能性
- ASP.NET WebFormsの`__doPostBack`のような動的なフォーム送信に対応できていない

**修正案1: フォーム要素を使用した送信（推奨）**
```python
def post_form(self, url: str, form_data: Dict, max_retries: int = 3):
    """フォームを送信"""
    page = self.get(url)  # フォームページを取得
    # フォーム要素を取得
    form = page.query_selector("form")
    if form:
        # フォームフィールドを埋める
        for name, value in form_data.items():
            input_field = form.query_selector(f'input[name="{name}"]')
            if input_field:
                input_field.fill(str(value))
        # 送信ボタンをクリック
        submit_button = form.query_selector('input[type="submit"]')
        if submit_button:
            submit_button.click()
            page.wait_for_load_state("networkidle")
    return page
```

**修正案2: JavaScriptを使用した送信**
```python
def post_via_javascript(self, url: str, form_data: Dict):
    """JavaScriptを使用してフォームを送信"""
    page = self.get(url)
    # JavaScriptでフォームを送信
    page.evaluate(f"""
        const form = document.querySelector('form');
        if (form) {{
            Object.keys({form_data}).forEach(key => {{
                const input = form.querySelector(`input[name="${{key}}"]`);
                if (input) input.value = {form_data}[key];
            }});
            form.submit();
        }}
    """)
    page.wait_for_load_state("networkidle")
    return page
```

**修正案3: リクエストAPIを使用（現在の実装を改善）**
```python
def post(self, url: str, data: Optional[Dict] = None, ...):
    """POSTリクエストを送信（改善版）"""
    response = self.page.request.post(url, form=data, ...)
    # レスポンスがHTMLの場合、ページを再読み込み
    if response.headers.get('content-type', '').startswith('text/html'):
        self.page.goto(url, wait_until="networkidle")
    return self.page
```

**推奨**: 修正案1（フォーム要素を使用）が最も確実

---

### ⚠️ 問題2: ダウンロード機能の実装が不完全

**問題点**:
- `expect_download()`の使用方法が正しいか確認が必要
- 進捗コールバックがファイルサイズ取得後にしか呼ばれない
- ダウンロードが開始されない場合のエラーハンドリングが不十分

**修正案1: ダウンロードイベントの監視を改善**
```python
def download_file(self, url: str, save_path: str, ...):
    """ファイルをダウンロード（改善版）"""
    # ダウンロードイベントを監視
    download_promise = self.page.wait_for_event("download", timeout=self.download_timeout)
    
    # リファラーを設定
    if referer:
        self.page.set_extra_http_headers({"Referer": referer})
    
    # ダウンロードリンクにアクセス
    self.page.goto(url, wait_until="domcontentloaded")
    
    # ダウンロードイベントを待機
    download = download_promise
    
    # ファイルを保存
    download.save_as(save_path)
    
    # 進捗コールバック（ファイルサイズ取得後）
    file_size = Path(save_path).stat().st_size
    if progress_callback:
        progress_callback(file_size, file_size)
    
    return True
```

**修正案2: リクエストAPIを使用したダウンロード**
```python
def download_file_via_request(self, url: str, save_path: str, ...):
    """リクエストAPIを使用してファイルをダウンロード"""
    response = self.page.request.get(url, timeout=self.download_timeout)
    
    if response.status == 200:
        # ファイルを保存
        with open(save_path, "wb") as f:
            f.write(response.body())
        
        file_size = Path(save_path).stat().st_size
        if progress_callback:
            progress_callback(file_size, file_size)
        
        return True
    return False
```

**推奨**: 修正案2（リクエストAPIを使用）がシンプルで確実

---

### ⚠️ 問題3: ScraperPlaywrightの実装が不完全

**問題点**:
- 既存の`Scraper`クラスの機能がすべて実装されていない
- 検索フォーム送信（`submit_search_form`）が未実装
- 検索結果からのファイル抽出（`extract_file_links_from_search_results`）が未実装
- `__doPostBack`の処理が未実装

**修正案: 既存のScraperクラスを参考に実装**
```python
class ScraperPlaywright:
    """Playwrightを使用したHTML解析・スクレイピングクラス"""
    
    def submit_search_form(self, url: str, search_conditions: SearchConditions) -> Optional[BeautifulSoup]:
        """検索フォームを送信"""
        # 1. 検索ページを取得
        page = self.playwright_client.get(url)
        if not page:
            return None
        
        # 2. フォームフィールドを埋める
        # 3. 送信ボタンをクリック
        # 4. 結果ページを取得
        # 5. BeautifulSoupオブジェクトを返す
        pass
    
    def extract_file_links_from_search_results(self, soup: BeautifulSoup, base_url: str, file_types: List[str]) -> List[FileInfo]:
        """検索結果からファイルリンクを抽出"""
        # 既存のScraperクラスの実装を参考に
        pass
```

**推奨**: 既存の`Scraper`クラスの実装を参考に、Playwright版を実装

---

### ⚠️ 問題4: 既存コードとの統合が未実装

**問題点**:
- `main.py`では`HTTPClient`を使用しており、`PlaywrightClient`に切り替える方法がない
- 設定で切り替え可能にする機能が未実装

**修正案1: 設定で切り替え可能にする**
```python
# config_model.pyに追加
@dataclass
class AppConfig:
    # ...
    http_client_type: str = "requests"  # "requests" or "playwright"
```

```python
# main.pyで切り替え
if config.http_client_type == "playwright":
    from src.utils.playwright_client import PlaywrightClient
    http_client = PlaywrightClient(logger)
else:
    from src.utils.http_client import HTTPClient
    http_client = HTTPClient(logger)
```

**修正案2: インターフェースを統一**
```python
# 共通インターフェースを定義
class HTTPClientInterface:
    def get(self, url: str, **kwargs): pass
    def post(self, url: str, data: Optional[Dict] = None, **kwargs): pass
    def download_file(self, url: str, save_path: str, ...): pass
    def close(self): pass

# HTTPClientとPlaywrightClientの両方がこのインターフェースを実装
```

**推奨**: 修正案1（設定で切り替え）がシンプル

---

## 実装優先順位

### 優先度1（高）: すぐに実装すべき項目
1. **ScraperPlaywrightの完全実装**
   - `submit_search_form`の実装
   - `extract_file_links_from_search_results`の実装
   - 既存の`Scraper`クラスの機能をすべて実装

2. **ダウンロード機能の改善**
   - リクエストAPIを使用したダウンロード実装
   - 進捗コールバックの改善

### 優先度2（中）: 次に実装すべき項目
3. **既存コードとの統合**
   - 設定での切り替え機能
   - `main.py`での使用

4. **POSTリクエストの改善**
   - フォーム要素を使用した送信実装

### 優先度3（低）: 後で実装すべき項目
5. **テストの実装**
   - 実際のページでのテスト
   - エラーケースのテスト

6. **パフォーマンス最適化**
   - ブラウザの再利用
   - 並列処理の検討

---

## 次のステップ

1. **ScraperPlaywrightの完全実装**
   - 既存の`Scraper`クラスを参考に、すべての機能を実装
   - 特に`submit_search_form`と`extract_file_links_from_search_results`を優先

2. **ダウンロード機能の改善**
   - リクエストAPIを使用した実装に変更
   - 進捗コールバックの改善

3. **既存コードとの統合**
   - 設定で切り替え可能にする
   - `main.py`で使用できるようにする

4. **テストの実行**
   - 実際のページでのテスト
   - 問題があれば修正

---

**作成日**: 2026年1月12日  
**ステータス**: 基本実装完了、改善が必要
