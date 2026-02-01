# 動作確認メモ

作成日: 2025-01-XX  
対象: ippi-down リポジトリ  
目的: バグ修正後の動作確認手順

## 修正内容サマリー

### 1. 入札調書ダウンロード不具合の修正
- **問題**: 詳細ページからファイルが見つかった場合、`UserEntry_Download.aspx`をスキップしていた
- **修正**: 早期リターンを廃止し、`UserEntry_Download.aspx`も必ず探索してマージするように変更
- **対象ファイル**: `src/core/scraper.py:1487-1665` `_extract_files_from_detail_page_via_postback()`

### 2. 重複回避の順序修正
- **問題**: `check_duplicate()`を先に実行してから`ensure_unique()`を実行していた
- **修正**: `ensure_unique()`を先に実行し、ユニーク化されたパスで`check_duplicate()`を実行
- **対象ファイル**: `src/core/downloader.py:109-122`

### 3. デバッグログの追加
- **抽出時**: 採用/不採用理由、PostBackリンク検出をログ出力
- **ダウンロード時**: URL、保存先、HTTP status、Content-Type、Content-Dispositionをログ出力
- **対象ファイル**: `src/core/scraper.py`, `src/utils/http_client.py`

## 動作確認手順

### 前提条件

- Windows 10/11 (64bit)
- Python 3.11.x がインストールされていること
- 仮想環境（venv）を使用する場合:
  ```powershell
  cd C:\Users\ryout\Workspaces\ippi-down
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  ```

### 1. デバッグログの確認

#### 1.1 ログレベルをDEBUGに設定

`config/config.yaml`を編集:
```yaml
logging:
  level: DEBUG  # INFOからDEBUGに変更
  file: ./logs/app.log
  max_bytes: 10485760
  backup_count: 5
```

#### 1.2 アプリケーションを実行

```powershell
# 仮想環境を使用する場合
.\venv\Scripts\Activate.ps1

# アプリケーションを起動
python src/main.py
```

#### 1.3 ログファイルを確認

```powershell
# ログファイルを開く（PowerShell）
Get-Content .\logs\app.log -Tail 100 -Wait

# または、テキストエディタで開く
notepad .\logs\app.log
```

#### 1.4 期待されるログ出力例

**ファイル抽出時:**
```
[DEBUG] テーブルを発見: dgrKokoku
[DEBUG] ファイルリンクを採用: 文書名='入札調書', 理由=servlet/Download/Publish文字列検出
[DEBUG] PostBackリンクを検出（未対応）: 文書名='入札調書', href='javascript:__doPostBack(...)'
[INFO] 詳細ページから3個のファイルリンクを抽出しました
[DEBUG] UserEntry_Download.aspxにアクセス（詳細ページに3件のファイルがある場合でも実行）: https://www.i-ppi.jp/...
[INFO] UserEntry_Download.aspxから2個のファイルリンクを抽出しました
[INFO] ファイル抽出完了: 詳細ページ=3件, UserEntry_Download.aspx=2件, マージ後=5件（重複除去済み）
```

**ダウンロード時:**
```
[DEBUG] ダウンロード開始: URL='https://www.i-ppi.jp/...', 保存先='./downloads/...', 試行=1/3, Referer='https://www.i-ppi.jp/...'
[DEBUG] ダウンロードレスポンス: status=200, Content-Type=application/pdf, Content-Disposition=attachment; filename="入札調書.pdf", Content-Length=123456
[DEBUG] ダウンロード完了: URL='https://www.i-ppi.jp/...', 保存先='./downloads/...', ファイルサイズ=123,456 bytes, Content-Type=application/pdf
```

### 2. デバッグスクリプトの使用

#### 2.1 詳細ページURLを指定してファイル抽出をテスト

```powershell
# 仮想環境を使用する場合
.\venv\Scripts\Activate.ps1

# デバッグスクリプトを実行
python scripts\debug_extract_files.py --url "https://www.i-ppi.jp/IPPI/SearchServices/Web/..." --out debug_output.json --debug-log
```

#### 2.2 出力JSONを確認

```powershell
# JSONファイルを開く
Get-Content .\debug_output.json | ConvertFrom-Json | Format-List

# または、テキストエディタで開く
notepad .\debug_output.json
```

#### 2.3 期待される出力例

**通常のURLの場合:**
```json
{
  "url": "https://www.i-ppi.jp/...",
  "file_types": [".pdf", ".xlsx", ".docx"],
  "postback_detected": false,
  "postback_reason": null,
  "files_count": 5,
  "files": [
    {
      "index": 1,
      "url": "https://www.i-ppi.jp/.../KokaiBunshoServlet?...",
      "filename": "入札調書.pdf",
      "file_type": ".pdf",
      "page_url": "https://www.i-ppi.jp/...",
      "metadata": {
        "title": "入札調書"
      }
    },
    ...
  ]
}
```

**PostBackリンクが検出された場合:**
```json
{
  "url": "https://www.i-ppi.jp/...",
  "file_types": [".pdf", ".xlsx", ".docx"],
  "postback_detected": true,
  "postback_reason": "抽出されたファイルにPostBackリンクが含まれています: javascript:__doPostBack(...)",
  "files_count": 3,
  "files": [
    ...
  ]
}
```

**注意**: `postback_detected: true`の場合、PostBackリンクのファイルは抽出されていません。P0-1の実装（PostBackリンク対応）が必要です。

### 3. 入札調書ダウンロードの確認

#### 3.1 検索条件を設定

GUIで以下を設定:
- 発注機関: 適切な分類を選択
- 工事名: （任意）
- ファイルタイプ: PDFを選択

#### 3.2 ダウンロードを実行

1. 「ダウンロード開始」ボタンをクリック
2. 進捗バーで進捗を確認
3. ログ画面で詳細を確認

#### 3.3 期待される動作

- 詳細ページからファイルが抽出される
- **重要**: 詳細ページにファイルがあっても、`UserEntry_Download.aspx`も探索される
- 両方のソースから取得したファイルがマージされる（重複除去済み）
- **PostBackリンク対応**: PostBackリンク（`javascript:__doPostBack(...)`）形式のリンクは検出され、`FileInfo.metadata`にpostback情報が保持されます。ダウンロード時に`Downloader._download_postback_file()`でPostBackを実行してファイルを取得します。
- 通常のURL形式の入札調書が含まれている場合、ダウンロードされる
- PostBackリンクの入札調書もダウンロードされる（P0-1の実装完了）

#### 3.4 確認ポイント

- ログに「UserEntry_Download.aspxにアクセス（詳細ページにX件のファイルがある場合でも実行）」が表示されること
- ログに「ファイル抽出完了: 詳細ページ=X件, UserEntry_Download.aspx=Y件, マージ後=Z件（重複除去済み）」が表示されること
- 保存先フォルダに「入札調書」などのファイルが保存されること

### 4. 重複回避の確認

#### 4.1 同名ファイルが存在する場合の動作確認

1. 既にダウンロード済みのファイルと同じ名前のファイルをダウンロードしようとする
2. ログを確認

#### 4.2 期待される動作

- `ensure_unique()`が先に実行され、連番が付与される（例: `file_1.pdf`, `file_2.pdf`）
- ユニーク化されたパスで`check_duplicate()`が実行される
- 既に存在する場合はスキップされる

#### 4.3 確認ポイント

- ログに「一意なパスを確保」が表示されること
- 同名ファイルが存在する場合、連番が付与されること
- 連番が付与されたファイルが既に存在する場合、スキップされること

## トラブルシューティング

### 問題1: ログが出力されない

**原因**: ログレベルがINFO以上に設定されている

**解決策**: `config/config.yaml`で`logging.level`を`DEBUG`に設定

### 問題2: UserEntry_Download.aspxが実行されない

**原因**: `AnkenkanriNo`または`HachushaId`が抽出できていない

**確認方法**: ログに「AnkenkanriNoを抽出: ...」が表示されるか確認

**解決策**: 詳細ページのHTML構造が変更されている可能性がある。ログで確認。

### 問題3: 重複ファイルがスキップされない

**原因**: `ensure_unique()`が正しく実行されていない

**確認方法**: ログに「一意なパスを確保」が表示されるか確認

**解決策**: `src/core/downloader.py:109-122`の順序を確認

## 検証完了チェックリスト

- [ ] ログレベルをDEBUGに設定して実行
- [ ] 詳細ページからファイルが抽出されることを確認
- [ ] UserEntry_Download.aspxも探索されることを確認（ログで確認）
- [ ] ファイルがマージされることを確認（重複除去済み）
- [ ] 入札調書がダウンロードされることを確認
- [ ] 重複回避が正しく動作することを確認（連番が付与される）
- [ ] デバッグスクリプトが正常に動作することを確認

## 注意事項

- 本修正は段階的に実装されているため、各修正を個別に検証することが推奨されます
- ログレベルをDEBUGに設定すると、ログファイルが大きくなる可能性があります
- **PostBackリンク対応**: PostBackリンク（`javascript:__doPostBack(...)`）形式のリンクは検出され、`FileInfo.metadata`にpostback情報が保持されます。ダウンロード時に`Downloader._download_postback_file()`でPostBackを実行してファイルを取得します（P0-1の実装完了）。
- デバッグスクリプト（`scripts/debug_extract_files.py`）はPostBackリンクを検出してJSONに`postback_detected: true`と`postback_reason`を出力します。

## スモーク実行コマンド

### ファイル抽出のみ（デバッグスクリプト）

```powershell
# 仮想環境を使用する場合
.\venv\Scripts\Activate.ps1

# デバッグスクリプトを実行（PostBackリンク検出情報を含む）
python scripts\debug_extract_files.py --url "https://www.i-ppi.jp/IPPI/SearchServices/Web/..." --out debug_output.json --debug-log

# 結果を確認
Get-Content .\debug_output.json | ConvertFrom-Json | Select-Object postback_detected, postback_reason, files_count | Format-List
```

### ダウンロードまで含むスモーク実行（GUI経由）

```powershell
# 仮想環境を使用する場合
.\venv\Scripts\Activate.ps1

# 1. 設定ファイルを準備（config/config.yaml）
#    - 検索条件を設定（発注機関、工事名など）
#    - ファイルタイプを設定（.pdfなど）
#    - 保存先を設定

# 2. GUIを起動
python src\main.py

# 3. GUI上で以下を実行:
#    - 検索条件を設定（必要に応じて）
#    - 「ダウンロード開始」ボタンをクリック
#    - 進捗バーとログで結果を確認

# 4. ログを確認（PostBackリンク検出・ダウンロードを確認）
Get-Content .\logs\app.log -Tail 100 | Select-String -Pattern "PostBack|入札調書|UserEntry_Download|PostBackでダウンロード"

# 5. 保存先フォルダを確認
Get-ChildItem .\downloads -Recurse -File | Select-Object FullName, Length, LastWriteTime | Format-Table -AutoSize
```

### 期待されるログ出力（PostBackリンクダウンロード時）

```
[DEBUG] PostBackリンクを検出（FileInfo作成）: 文書名='入札調書', event_target='dgrKokoku', event_argument='$0'
[INFO] PostBackでダウンロード開始: 文書名='入札調書', event_target='dgrKokoku', event_argument='$0'
[DEBUG] PostBackを実行: URL='https://www.i-ppi.jp/...', event_target='dgrKokoku'
[DEBUG] PostBackレスポンス: status=200, Content-Type=application/pdf, Content-Disposition=attachment; filename="入札調書.pdf"
[INFO] PostBackでダウンロード完了: 保存先='./downloads/...', ファイルサイズ=123,456 bytes, Content-Type=application/pdf
```

### 期待されるログ出力（PostBackリンク検出・ダウンロード時）

**検出時:**
```
[DEBUG] PostBackリンクを検出（FileInfo作成）: 文書名='入札調書', event_target='dgrKokoku', event_argument='$0'
```

**ダウンロード時:**
```
[INFO] PostBackでダウンロード開始: 文書名='入札調書', event_target='dgrKokoku', event_argument='$0'
[DEBUG] PostBackを実行: URL='https://www.i-ppi.jp/...', event_target='dgrKokoku'
[DEBUG] PostBackレスポンス: status=200, Content-Type=application/pdf, Content-Disposition=attachment; filename="入札調書.pdf"
[INFO] PostBackでダウンロード完了: 保存先='./downloads/...', ファイルサイズ=123,456 bytes, Content-Type=application/pdf
```
