# コードレビュー・検査結果

## 1. Gitリポジトリの状態

### 現在の状態
- ✅ Gitリポジトリは正常に初期化されています
- ✅ 初期コミット（be0be94）が存在します
- ⚠️ リモートリポジトリが設定されていません
- ⚠️ 以下のファイルが変更されています：
  - `pyrightconfig.json` (修正済み)
  - `src/utils/http_client.py` (修正済み)
- ⚠️ 以下のファイルが未追跡状態です：
  - `docs/テスト結果比較.md`
  - `docs/動作確認手順.md`
  - `docs/動作確認結果サマリー.md`
  - `docs/実装タスクリスト.md`

### 推奨事項
1. **リモートリポジトリの設定**
   ```bash
   git remote add origin <リポジトリURL>
   ```

2. **未追跡ファイルの追加**
   ```bash
   git add docs/
   git commit -m "docs: ドキュメントファイルを追加"
   ```

3. **変更のコミット**
   ```bash
   git add pyrightconfig.json src/utils/http_client.py
   git commit -m "fix: インポートエラーとリンター設定を修正"
   ```

## 2. コードベースの問題点と推奨修正

### 2.1 HTTPClient (`src/utils/http_client.py`)

#### 問題点
1. **HTTPステータス429（レート制限）の処理が不足**
   - 現在は`raise_for_status()`で例外を発生させるのみ
   - レート制限時のリトライ処理がない

2. **タイムアウト設定が固定**
   - GET/POST: 30秒固定
   - ダウンロード: 60秒固定
   - 設定可能にするべき

3. **User-Agentが不完全**
   - 現在: `"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"`
   - 完全なUser-Agent文字列にすべき

#### 推奨修正
```python
# HTTPステータス429の処理を追加
def get(self, url: str, **kwargs) -> requests.Response:
    """GETリクエストを送信"""
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            response = self.session.get(url, timeout=30, **kwargs)
            
            # 429エラーの場合はリトライ
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    retry_after = int(response.headers.get('Retry-After', retry_delay))
                    self.logger.warning(f"レート制限に達しました。{retry_after}秒後にリトライします...")
                    time.sleep(retry_after)
                    continue
                else:
                    response.raise_for_status()
            else:
                response.raise_for_status()
            
            return response
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                self.logger.error(f"GETリクエストエラー: {url} - {str(e)}")
                raise
            time.sleep(retry_delay * (attempt + 1))
```

### 2.2 Scraper (`src/core/scraper.py`)

#### 問題点
1. **メタデータ抽出が不完全**
   - `extract_metadata()`はタイトルのみ抽出
   - 発注機関、工事名、日付などの情報が抽出されていない

#### 推奨修正
```python
def extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
    """ページからメタデータを抽出"""
    metadata = {}
    
    # タイトル
    title_tag = soup.find("title")
    if title_tag:
        metadata["title"] = title_tag.get_text().strip()
    
    # 発注機関の抽出（ページ構造に応じて調整）
    hachu_kikan = soup.find("td", string=re.compile("発注機関"))
    if hachu_kikan:
        next_td = hachu_kikan.find_next_sibling("td")
        if next_td:
            metadata["hachu_kikan"] = next_td.get_text().strip()
    
    # 工事名の抽出
    koji_name = soup.find("td", string=re.compile("工事名"))
    if koji_name:
        next_td = koji_name.find_next_sibling("td")
        if next_td:
            metadata["koji_name"] = next_td.get_text().strip()
    
    # 日付の抽出
    date_patterns = [
        r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})[日]?",
        r"(\d{4})-(\d{2})-(\d{2})"
    ]
    for pattern in date_patterns:
        date_match = re.search(pattern, soup.get_text())
        if date_match:
            metadata["date"] = date_match.group(0)
            break
    
    return metadata
```

### 2.3 Downloader (`src/core/downloader.py`)

#### 問題点
1. **リトライ処理が不完全**
   - `retry_download()`メソッドは存在するが、`download_files()`で使用されていない
   - デコレータ`@retry`は使用されているが、429エラーなどの特定のエラーに対する処理がない

#### 推奨修正
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        requests.exceptions.RequestException,
        requests.exceptions.HTTPError,
    )),
)
def download_file(
    self, file_info: FileInfo, save_path: str, progress_callback: Optional[Callable] = None
) -> bool:
    """ファイルをダウンロード"""
    try:
        # 既存のコード...
        # HTTPステータス429の処理を追加
        response = self.http_client.session.get(file_info.url, stream=True, timeout=60)
        
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 5))
            self.logger.warning(f"レート制限に達しました。{retry_after}秒後にリトライします...")
            time.sleep(retry_after)
            # リトライ（デコレータが処理）
            raise requests.exceptions.HTTPError("429 Too Many Requests")
        
        response.raise_for_status()
        # ... 残りのコード
```

### 2.4 FileUtils (`src/utils/file_utils.py`)

#### 問題点
1. **Windowsパス長制限（260文字）の処理がない**
   - `sanitize_filename()`は無効文字の削除のみ
   - パス長が260文字を超える場合の処理がない

#### 推奨修正
```python
@staticmethod
def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """ファイル名から無効な文字を削除し、長さを制限"""
    # 既存の処理...
    
    # Windowsパス長制限を考慮（拡張子を除いて200文字以内）
    if len(filename) > max_length:
        # 拡張子を取得
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            ext = '.' + ext
        else:
            name = filename
            ext = ''
        
        # ファイル名を切り詰め
        max_name_length = max_length - len(ext)
        filename = name[:max_name_length] + ext
    
    return filename
```

### 2.5 ConfigModel (`src/models/config_model.py`)

#### 問題点
1. **スケジュール設定の検証が不足**
   - `ScheduleConfig`の`interval`と`time`の排他的条件チェックがない
   - `interval`が`custom`の場合、`cron`が必須だが検証されていない

#### 推奨修正
```python
@dataclass
class ScheduleConfig:
    """スケジュール設定"""
    
    enabled: bool = False
    interval: str = "daily"  # daily, weekly, monthly, custom
    time: str = "09:00"  # HH:MM形式
    cron: Optional[str] = None  # cron形式（intervalがcustomの場合）
    
    def __post_init__(self):
        """初期化後の検証"""
        if self.enabled:
            if self.interval == "custom":
                if not self.cron:
                    raise ValueError("intervalがcustomの場合、cron形式を指定してください")
            elif not self.time:
                raise ValueError("intervalがcustom以外の場合、timeを指定してください")
```

### 2.6 Logger (`src/utils/logger.py`)

#### 問題点
1. **JSONL形式のログ出力がない**
   - 現在は標準のログ形式のみ
   - 要件定義書にはJSONL形式のログ出力が記載されている可能性がある

#### 推奨修正
```python
def setup_file_handler(self):
    """ファイルハンドラーを設定"""
    log_file = Path(self.config.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # JSONL形式のログも出力（オプション）
    if self.config.jsonl_enabled:
        jsonl_file = log_file.with_suffix('.jsonl')
        jsonl_handler = logging.FileHandler(jsonl_file, encoding='utf-8')
        jsonl_handler.setFormatter(JsonFormatter())
        self.logger.addHandler(jsonl_handler)
    
    # 既存のRotatingFileHandler...
```

### 2.7 GUI (`src/gui/main_window.py`)

#### 問題点
1. **キャンセル機能がない**
   - ダウンロード中のキャンセルボタンがない
   - 長時間実行される処理を中断できない

#### 推奨修正
```python
def __init__(self, ...):
    # ...
    self.cancel_flag = threading.Event()
    
def on_download_cancel(self):
    """ダウンロードをキャンセル"""
    self.cancel_flag.set()
    self.logger.info("ダウンロードをキャンセルしました")
    self.show_message("ダウンロードをキャンセルしました", "warning")

def download_files(self, ...):
    """ファイルをダウンロード"""
    # ...
    for file_info in file_list:
        if self.cancel_flag.is_set():
            logger.info("ダウンロードがキャンセルされました")
            break
        # ダウンロード処理...
```

## 3. プロジェクト構造の問題点

### 3.1 `.gitignore`の確認
- ✅ `.venv/`、`build/`、`dist/`は適切に除外されている
- ⚠️ テストファイル（`test_*.py`、`test_*.html`）が除外されているが、一部のテストファイルはリポジトリに含まれている可能性がある

### 3.2 ビルド成果物
- ⚠️ `.venv/`、`build/`、`dist/`がzipファイルに含まれていた
- これらは`.gitignore`で除外されているため、Gitリポジトリには含まれていないはず
- zipファイル作成時に`.gitignore`を無視した可能性がある

## 4. 推奨される次のステップ

1. **変更のコミット**
   ```bash
   git add pyrightconfig.json src/utils/http_client.py
   git commit -m "fix: インポートエラーとリンター設定を修正"
   ```

2. **ドキュメントの追加**
   ```bash
   git add docs/
   git commit -m "docs: ドキュメントファイルを追加"
   ```

3. **リモートリポジトリの設定**（必要に応じて）
   ```bash
   git remote add origin <リポジトリURL>
   git push -u origin main
   ```

4. **コードの改善**
   - 上記の問題点を順次修正
   - 各修正後にテストを実行して動作確認

5. **テストの追加**
   - 単体テストの追加
   - 統合テストの追加

## 5. その他の注意事項

1. **文字エンコーディング**
   - 一部のファイル名が文字化けしている可能性がある
   - Windows環境では問題なく表示されるが、クロスプラットフォーム対応を考慮する場合はUTF-8に統一

2. **依存関係**
   - `requirements.txt`の文字化けを修正（UTF-8で保存）

3. **セキュリティ**
   - `config/config.yaml`は`.gitignore`で除外されているが、機密情報が含まれないよう注意

