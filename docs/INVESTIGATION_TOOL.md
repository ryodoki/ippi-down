# 調査ツール（investigate_i_ppi.py）の使い方

i-ppi サイトの検索・HTML 構造・ファイル抽出をコマンドラインから確認するための統合ツールです。  
旧 `debug/*.py` および `scripts/debug_extract_files.py` の機能を 1 本にまとめています。

**サイト変更監視**（スナップショット・差分・影響範囲）については [サイト変更監視の使い方](./SITE_CHANGE_MONITORING.md) を参照してください。

## 前提

- プロジェクトルートで実行するか、`python scripts/investigate/investigate_i_ppi.py` で実行してください。
- 検索系コマンドはネットワーク接続が必要です（https://www.i-ppi.jp へアクセス）。

## 実行例（PowerShell・コピペ可）

```powershell
# プロジェクトルートへ移動
cd C:\Users\ryout\Workspaces\ippi-down

# 仮想環境を有効化
.\.venv\Scripts\Activate.ps1
```

### 検索結果 1 ページ目の概要

```powershell
python scripts/investigate/investigate_i_ppi.py search
```

既定の検索条件（国の機関 → 国土交通省 → 東北地方整備局、工事名「トンネル」）で検索し、結果テーブル（dgrSearchList）の 1 ページ目件数と先頭 10 件を表示します。

### 検索条件を変える

```powershell
python scripts/investigate/investigate_i_ppi.py search --daibunrui "国の機関" --chubunrui "国土交通省" --shoubunrui "東北地方整備局" --koji-name "橋梁"
```

### 全ページの件数集計（ページネーション）

```powershell
python scripts/investigate/investigate_i_ppi.py paginate
python scripts/investigate/investigate_i_ppi.py paginate --output-json
```

### 結果の妥当性確認（機関名一致など）

```powershell
python scripts/investigate/investigate_i_ppi.py verify
```

### HTML 構造の確認（hidden / select / text / dgrSearchList）

```powershell
python scripts/investigate/investigate_i_ppi.py html
python scripts/investigate/investigate_i_ppi.py html --save-html debug_page.html --output-json
```

### Scraper 経由で検索（GUI と同じ経路）

```powershell
python scripts/investigate/investigate_i_ppi.py scraper
```

### 詳細ページから添付ファイル一覧を抽出（JSON 出力）

```powershell
python scripts/investigate/investigate_i_ppi.py extract-files --url "https://www.i-ppi.jp/.../Detail.aspx?..." --out result.json
python scripts/investigate/investigate_i_ppi.py extract-files --url "https://..." --out result.json --file-types .pdf .xlsx
```

## 共通オプション

| オプション | 説明 | 既定値 |
|------------|------|--------|
| --base-url | 検索画面 URL | Search.aspx?tab=4 |
| --daibunrui | 大分類 | 国の機関 |
| --chubunrui | 中分類 | 国土交通省 |
| --shoubunrui | 小分類 | 東北地方整備局 |
| --saibunrui | 細分類 | （空） |
| --koji-name | 工事名 | トンネル |
| --timeout | HTTP タイムアウト（秒） | 30 |
| --output-json | 結果を JSON で標準出力にも出す | オフ |
| --debug-log | DEBUG ログを有効化 | オフ |

## 旧スクリプトとの対応

| 旧スクリプト（参考） | 対応するサブコマンド |
|---------------------|----------------------|
| debug_search_request.py, debug_search_results.py | search, scraper |
| debug_pagination.py, debug_full_search.py, debug_count_koji.py | paginate |
| debug_verify_results.py, debug_search_verification.py | verify |
| debug_html_structure.py, debug_field_names.py, debug_form_fields.py | html |
| scripts/investigate/debug_extract_files.py | extract-files |

詳細な棚卸しは [docs/dev-notes/DEBUG_SCRIPTS_INVENTORY.md](dev-notes/DEBUG_SCRIPTS_INVENTORY.md) を参照してください。

---

**作成日**: 2026年2月
