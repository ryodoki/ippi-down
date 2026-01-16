# Phase 0: 現状把握結果

## 1. ルート直下のファイル分類

### アプリ本体コード（運用対象）
- `src/` - アプリケーション本体コード
  - `main.py` - エントリーポイント（GUI版）
  - `app/` - アプリケーションサービス層
  - `core/` - コアロジック（scraper, downloader, filter, naming）
  - `gui/` - GUI関連
  - `config/` - 設定管理
  - `models/` - データモデル
  - `utils/` - ユーティリティ
  - `storage/` - ストレージ抽象化
  - `scheduler/` - スケジューラー

### 調査物/生成物/ログ/成果物（非運用）
- **HTMLファイル（調査用）**: 20+ファイル
  - `browser_*.html`, `search_results_*.html`, `chubunrui_*.html`, `test_detail_page.html`など
- **JSONファイル（調査用）**: 5ファイル
  - `browser_network_*.json`, `search_form_data.json`, `test_koji_name_params.json`など
- **PNGファイル（スクリーンショット）**: 2ファイル
  - `browser_after_*.png`
- **TXTファイル（出力ログ）**: 25+ファイル
  - `test_*_output.txt`, `download_common_js_output.txt`など
- **HARファイル**: `trace_out/network.har`
- **ログディレクトリ**: `logs/`
- **ダウンロードディレクトリ**: `downloads/`, `test_downloads/`
- **トレース出力**: `trace_out/`

### 開発用スクリプト（非運用）
- **ルート直下のテストスクリプト**: 30+ファイル
  - `test_*.py` - 調査用スクリプト（pytestではない）
  - `download_common_js.py`, `analyze_*.py`など
- **scripts/**: 開発用スクリプト（既存）
- **tools/**: ツールスクリプト（既存）

### 設定ファイル
- `config/` - 設定ファイル（`config.yaml`はGit管理外）
- `pytest.ini` - pytest設定
- `requirements.txt` - 依存関係
- `pyrightconfig.json` - 型チェック設定

### ドキュメント
- `docs/` - ドキュメント
- `README.md`, `DEPLOYMENT.md`

### ビルド生成物（Git管理外）
- `build/`, `dist/` - PyInstaller生成物
- `.venv/` - 仮想環境
- `.pytest_cache/` - pytestキャッシュ

## 2. エントリーポイントと主要import経路

### エントリーポイント
- **GUI版**: `src/main.py` → `main()` → `tk.Tk()` → `MainWindow` → `root.mainloop()`
  - ✅ `if __name__ == "__main__"`でガード済み

### 主要import経路
- **アプリ本体**: `from src.* import *` パターン（138箇所）
- **テスト**: `from src.* import *` パターン
- **スクリプト**: `from src.* import *` パターン

### 潜在的な問題
1. **GUI起動がimport時に実行される可能性**
   - `src/gui/main_window.py`の`__init__`で`load_hachu_daibunrui_options()`が呼ばれる
   - これがHTTPリクエストを送信する可能性
   - `src/utils/notifier.py`で`tk.Tk()`が呼ばれる可能性

2. **テストファイルでGUIが起動**
   - `tests/test_settings.py` - `@pytest.mark.gui`は付いているが、import時にGUI起動の可能性
   - `tests/test_phase_a.py` - GUIテストあり

## 3. 現状のテストコマンドと結果

### テストコマンド
```bash
.venv\Scripts\python.exe -m pytest tests\ -v --tb=short -k "not gui"
```

### 問題点
- **GUI起動がimport時に実行される** - pytest収集時にGUIが起動してハング
- **`test_settings.py`がタイムアウト** - GUIダイアログが待機状態になる

### テスト結果（修正前）
- 46テスト収集
- `test_settings.py::test_settings_dialog`がタイムアウト（30秒）
- その他は正常にパス

## 4. フォルダ構成の現状

```
ippi-down/
├── src/                    # アプリ本体
├── tests/                  # テスト
├── scripts/                # 開発用スクリプト（既存）
├── config/                 # 設定ファイル
├── docs/                   # ドキュメント
├── logs/                   # ログ（生成物）
├── downloads/              # ダウンロード（生成物）
├── trace_out/              # トレース出力（生成物）
├── build/, dist/           # ビルド生成物
├── *.html, *.json, *.txt   # 調査物（ルート直下に散在）
└── test_*.py               # 調査用スクリプト（ルート直下に散在）
```

## 5. 次のステップ

### 優先対応（GUI起動問題の修正）
1. **import時にGUIを起動しない構造にする**
   - `src/gui/main_window.py`の`__init__`でHTTPリクエストを遅延実行
   - `src/utils/notifier.py`の`tk.Tk()`呼び出しを関数内に移動
2. **GUIテストのマーカー確認**
   - すべてのGUIテストに`@pytest.mark.gui`を付与
   - `pytest.ini`でデフォルトskipを確認
3. **手動GUI確認スクリプトの移動**
   - `tests/`から`scripts/`へ移動

### Phase 1の準備
- `artifacts/`ディレクトリの作成
- ルート直下の調査物を`artifacts/`へ移動
- `.gitignore`の更新
