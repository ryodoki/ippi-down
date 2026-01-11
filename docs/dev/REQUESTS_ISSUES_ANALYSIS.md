# requests実装の問題点分析と修正計画

## driver_probe.pyの結果

### 結果サマリー
- **requests**: NG, score=35
- **エラー**: "サンプルDLが失敗（HTTP 429/403/リダイレクト/タイムアウト等）"
- **実際の状況**:
  - 検索結果から24個のファイルリンクを抽出できている ✅
  - ダウンロード時に接続タイムアウトが発生 ❌
  - `UserEntry_Download.aspxから0個のファイルリンクを抽出しました`が大量 ❌

### 結論
**requests路線はまだ死んでいない**。問題は以下の2点：
1. リンク抽出方法が不完全（UserEntry_Download.aspxで0件）
2. ダウンロード時のタイムアウト（接続タイムアウト）

---

## 問題点の個別切り分け

### 問題1: UserEntry_Download.aspxで0個のファイルリンク抽出

**現状**:
- `extract_file_links()`は拡張子で終わるリンクしか拾わない
- UserEntry_Download.aspxページには`dgrKokoku`/`dgrKeika`テーブルがある
- 詳細ページ用のロジック（`_extract_files_from_detail_page_via_postback`）は存在するが、UserEntry_Download.aspxでは使われていない

**原因**:
```python
# 現在の実装（scraper.py 1263行目）
files = self.extract_file_links(download_soup, download_url, file_types)
```
この`extract_file_links()`は拡張子チェックのみで、`dgrKokoku`/`dgrKeika`テーブルを走査しない。

**修正方針**:
- UserEntry_Download.aspxでも`dgrKokoku`/`dgrKeika`テーブル走査ロジックを使用
- `_extract_files_from_detail_page_via_postback`のロジックを再利用可能にする

---

### 問題2: ダウンロード時の接続タイムアウト

**現状**:
- 接続タイムアウトが発生（300秒設定でもタイムアウト）
- `e2ppiw01.e-bisc.go.jp`への接続が失敗

**原因**:
- ネットワーク/サーバー側の問題の可能性が高い
- ただし、Content-Typeや先頭バイトのチェックが不十分な可能性もある

**修正方針**:
- Content-Typeと先頭数バイトでHTML判定を追加
- Accept-Encoding: brをやめる（またはbrotli対応を入れる）

---

### 問題3: __EVENTVALIDATIONが見つかりませんでした

**現状**: 警告が出ているが、検索結果ページは取得できている

**結論**: **主犯ではない**。この警告は無視して良い。

---

## 修正計画（ステップバイステップ）

### ステップ1: UserEntry_Download.aspxでのリンク抽出を改善

**問題**: `extract_file_links()`が拡張子チェックのみ

**修正案1（推奨）**: `dgrKokoku`/`dgrKeika`テーブル走査ロジックを再利用

```python
def _extract_files_from_tables(self, soup: BeautifulSoup, base_url: str, file_types: List[str]) -> List[FileInfo]:
    """dgrKokoku/dgrKeikaテーブルからファイルリンクを抽出（再利用可能なメソッド）"""
    files = []
    
    for table_id in ["dgrKokoku", "dgrKeika"]:
        table = soup.find("table", id=table_id)
        if not table:
            continue
        
        rows = table.find_all("tr")[1:]  # ヘッダー行をスキップ
        
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            
            document_name = cells[0].get_text(strip=True)
            status_cell = cells[1]
            link = status_cell.find("a", href=True)
            
            if link:
                href = link.get("href")
                if href:
                    absolute_url = urljoin(base_url, href)
                    
                    # ファイルタイプをチェック
                    is_file_link = False
                    if any(href.lower().endswith(ext) for ext in file_types):
                        is_file_link = True
                    elif "KokaiBunshoServlet" in href or "Publish" in href or "Download" in href:
                        is_file_link = True
                    
                    if is_file_link:
                        # ファイル情報を作成
                        filename = absolute_url.split("/")[-1].split("?")[0]
                        if not filename or "." not in filename:
                            filename = document_name
                        
                        file_type = ""
                        url_path = absolute_url.split("?")[0]
                        path_parts = url_path.split("/")
                        if path_parts:
                            last_part = path_parts[-1]
                            if "." in last_part:
                                ext = "." + last_part.split(".")[-1].lower()
                                if len(ext) <= 6:
                                    file_type = ext
                        
                        if not file_type:
                            file_type = ".pdf"
                        
                        file_info = FileInfo(
                            url=absolute_url,
                            filename=filename,
                            file_type=file_type,
                            page_url=base_url,
                            metadata={"title": document_name} if document_name else {}
                        )
                        files.append(file_info)
    
    return files
```

**修正箇所**: `scraper.py`の`_extract_files_from_detail_page_via_postback`内（1263行目付近）

```python
# 修正前
files = self.extract_file_links(download_soup, download_url, file_types)

# 修正後
files = self._extract_files_from_tables(download_soup, download_url, file_types)
if not files:
    # フォールバック: 通常のextract_file_linksも試す
    files = self.extract_file_links(download_soup, download_url, file_types)
```

---

### ステップ2: Content-Typeと先頭バイトでHTML判定を追加

**問題**: ダウンロードしたファイルがHTMLの場合、成功扱いになっている可能性

**修正案**: `HTTPClient.download_file()`にHTML判定を追加

```python
def download_file(self, url: str, save_path: str, ...):
    """ファイルをダウンロード（HTML判定追加）"""
    response = self.session.get(url, stream=True, timeout=timeout_tuple, ...)
    
    # Content-Typeをチェック
    content_type = response.headers.get("Content-Type", "").lower()
    if "text/html" in content_type:
        self.logger.warning(f"ダウンロードしたファイルがHTMLです: {url}")
        return False
    
    # 先頭数バイトをチェック
    first_chunk = next(response.iter_content(chunk_size=16), b"")
    if first_chunk.startswith(b"<html") or first_chunk.startswith(b"<!DOCTYPE"):
        self.logger.warning(f"ダウンロードしたファイルがHTMLです（先頭バイト判定）: {url}")
        return False
    
    # 通常のダウンロード処理を続行
    ...
```

---

### ステップ3: Accept-Encoding: brをやめる

**問題**: brotli圧縮を宣言しているが、解凍できない可能性

**修正案**: `HTTPClient.__init__()`でAccept-Encodingからbrを削除

```python
self.session.headers.update({
    # ...
    "Accept-Encoding": "gzip, deflate",  # brを削除
    # ...
})
```

---

## 実装順序

1. **ステップ1**: UserEntry_Download.aspxでのリンク抽出改善（最優先）
2. **ステップ2**: Content-Typeと先頭バイトでHTML判定（安全装置）
3. **ステップ3**: Accept-Encoding: brをやめる（環境依存の問題回避）

---

**作成日**: 2026年1月12日  
**ステータス**: 問題分析完了、修正計画作成
