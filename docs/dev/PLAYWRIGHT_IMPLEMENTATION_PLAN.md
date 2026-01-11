# Playwright実装計画（ステップバイステップ）

## 実装方針

既存の`Scraper`クラスの機能を`ScraperPlaywright`に段階的に実装します。
各ステップで問題があれば個別に切り分けて修正します。

---

## ステップ1: 基本機能の完全実装

### 1.1 `extract_metadata()`の完全実装

**現状**: 基本実装のみ（タイトルのみ）

**必要な機能**:
- タイトル
- 発注機関
- 工事名
- 日付（公告日、開札日、契約日など）
- カテゴリ
- 予定価格
- 落札価格

**実装方法**: 既存の`Scraper.extract_metadata()`をそのまま移植

**問題点**: なし（既存実装をそのまま使用可能）

---

### 1.2 `extract_file_links()`の完全実装

**現状**: 基本実装のみ（拡張子チェックのみ）

**必要な機能**:
- ファイルタイプのフィルタリング
- メタデータの抽出（`_extract_link_metadata`）
- 絶対URLへの変換
- `page_url`の設定

**実装方法**: 既存の`Scraper.extract_file_links()`をそのまま移植

**問題点**: なし（既存実装をそのまま使用可能）

---

## ステップ2: 検索フォーム送信の実装

### 2.1 `_build_search_form_data()`の実装

**現状**: 未実装

**必要な機能**:
- 検索条件からフォームデータを構築
- ドロップダウンの値の設定
- テキスト入力フィールドの設定
- 日付範囲の設定
- チェックボックスの設定

**実装方法**: 既存の`Scraper._build_search_form_data()`を参考に実装

**問題点**: 
- Playwrightでフォーム要素を操作する必要がある
- 既存の実装は`requests`のPOSTデータ形式

**修正案**:
- 方法1: フォームデータを辞書形式で構築し、`PlaywrightClient.post()`で送信
- 方法2: フォーム要素を直接操作（`fill()`, `select_option()`, `click()`）

**推奨**: 方法1（既存実装との互換性を保つ）

---

### 2.2 `submit_search_form()`の実装

**現状**: 未実装

**必要な機能**:
- 検索ページを取得
- hidden inputを取得
- 検索フォームデータを構築
- POSTリクエストで検索を実行
- 検索結果ページを取得

**実装方法**: 既存の`Scraper.submit_search_form()`を参考に実装

**問題点**:
- PlaywrightのPOSTリクエストが正しく動作するか確認が必要
- フォーム送信後のページ遷移が正しく処理されるか確認が必要

**修正案**:
- ステップ2.1で構築したフォームデータを使用
- `PlaywrightClient.post()`でPOSTリクエストを送信
- レスポンスからBeautifulSoupオブジェクトを取得

---

## ステップ3: 検索結果からのファイル抽出

### 3.1 `extract_file_links_from_search_results()`の実装

**現状**: 未実装

**必要な機能**:
- 検索結果テーブルからファイルリンクを抽出
- 詳細ページへのリンクを抽出
- `__doPostBack`の処理
- 詳細ページからのファイル抽出

**実装方法**: 既存の`Scraper.extract_file_links_from_search_results()`を参考に実装

**問題点**:
- `__doPostBack`の処理が複雑
- 詳細ページへの遷移が必要

**修正案**:
- 方法1: BeautifulSoupでHTMLを解析してリンクを抽出
- 方法2: PlaywrightでJavaScriptを実行してリンクを取得

**推奨**: 方法1（既存実装との互換性を保つ）

---

## ステップ4: ダウンロード機能の改善

### 4.1 リクエストAPIを使用したダウンロード実装

**現状**: `expect_download()`を使用（動作確認が必要）

**問題点**:
- `expect_download()`が正しく動作するか確認が必要
- 進捗コールバックがファイルサイズ取得後にしか呼ばれない

**修正案1: リクエストAPIを使用（推奨）**
```python
def download_file(self, url: str, save_path: str, ...):
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

**修正案2: 進捗コールバックの改善**
```python
def download_file(self, url: str, save_path: str, ...):
    """進捗コールバックを改善したダウンロード"""
    response = self.page.request.get(url, timeout=self.download_timeout, stream=True)
    
    if response.status == 200:
        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0
        
        with open(save_path, "wb") as f:
            for chunk in response.iter_bytes(chunk_size=8192):
                f.write(chunk)
                downloaded_size += len(chunk)
                if progress_callback and total_size > 0:
                    progress_callback(downloaded_size, total_size)
        
        return True
    return False
```

**推奨**: 修正案1（シンプルで確実）

---

## 実装順序

1. **ステップ1**: 基本機能の完全実装（問題なし）
2. **ステップ2**: 検索フォーム送信の実装（POSTリクエストの確認が必要）
3. **ステップ3**: 検索結果からのファイル抽出（`__doPostBack`の処理が必要）
4. **ステップ4**: ダウンロード機能の改善（リクエストAPIへの変更）

---

## 各ステップでの確認事項

### ステップ1完了後
- [ ] `extract_metadata()`が正しく動作するか
- [ ] `extract_file_links()`が正しく動作するか

### ステップ2完了後
- [ ] `submit_search_form()`が正しく動作するか
- [ ] 検索結果ページが正しく取得できるか
- [ ] POSTリクエストが正しく送信されるか

### ステップ3完了後
- [ ] 検索結果からファイルリンクが正しく抽出できるか
- [ ] `__doPostBack`が正しく処理されるか
- [ ] 詳細ページからのファイル抽出が正しく動作するか

### ステップ4完了後
- [ ] ダウンロードが正しく動作するか
- [ ] 進捗コールバックが正しく呼ばれるか
- [ ] エラーハンドリングが正しく動作するか

---

**作成日**: 2026年1月12日  
**ステータス**: 実装計画作成完了
