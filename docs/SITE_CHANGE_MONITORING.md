# サイト変更監視・調査ツールの使い方

i-ppi サイトの構造変更を検知し、差分レポートと影響範囲（Scraper/Parser の修正ポイント）を把握するための手順です。

## 概要

- **snapshot**: 指定 URL の HTML を「構造だけ」取り出して JSON で保存する
- **probe**: 工事(tab=3)・業務(tab=6) 等の検索画面でドロップダウンと POSTBACK が動くか検証する
- **diff**: 2 つのスナップショットを比較し、重要度付き（HIGH/MED/LOW）で差分レポートを出す
- **impact**: 差分レポート（JSON）と実装マッピングを突合し、修正すべき `src/` の箇所を列挙する

## 前提

- プロジェクトルートで実行する（`scripts/investigate/investigate_i_ppi.py` を実行）
- スナップショット取得・probe はネットワーク接続が必要

## 実行例（PowerShell・コピペ可）

```powershell
# プロジェクトルートへ移動・venv 有効化
cd C:\Users\ryout\Workspaces\ippi-down
.\.venv\Scripts\Activate.ps1
```

### 1. スナップショットを取る（定期実行推奨）

```powershell
# 検索画面（工事 tab=4）と Index を保存
python scripts/investigate/investigate_i_ppi.py snapshot `
  "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4" `
  "https://www.i-ppi.jp/IPPI/SearchServices/Web/Index.htm" `
  --out-dir scripts/snapshots
```

保存先は `scripts/snapshots/YYYYMMDD_HHMMSS/` です。`manifest.json` と URL ごとの JSON ができます。

### 2. ドロップダウン・POSTBACK の検証（probe）

```powershell
# tab=3, 4, 6 を取得し、1 回 POSTBACK して中分類の変化を確認
python scripts/investigate/investigate_i_ppi.py probe --tabs 3 4 6

# POSTBACK なし（GET のみ）
python scripts/investigate/investigate_i_ppi.py probe --tabs 4 --no-postback

# 結果を指定ディレクトリに保存
python scripts/investigate/investigate_i_ppi.py probe --tabs 3 4 6 --out scripts/snapshots/probe
```

### 3. 差分レポートを出す（サイト変更後の比較）

```powershell
# 以前のスナップショットと新しいスナップショットを比較
python scripts/investigate/investigate_i_ppi.py diff `
  scripts/snapshots/20260201_120000 `
  scripts/snapshots/20260215_120000 `
  --output docs/site_diff_report.md

# JSON で出力（impact に渡す用）
python scripts/investigate/investigate_i_ppi.py diff `
  scripts/snapshots/20260201_120000 `
  scripts/snapshots/20260215_120000 `
  --output docs/site_diff_report.json --format json
```

### 4. 影響する実装箇所を列挙（impact）

```powershell
# diff で --format json したファイルを渡す
python scripts/investigate/investigate_i_ppi.py impact docs/site_diff_report.json --output docs/impact.json
```

差分メッセージに含まれるフィールド名（例: `drpTopKikanInf`, `dgrSearchList`）と `scripts/investigate/i_ppi_inspector/mapping.py` を突き合わせ、該当する `src/` のファイル・説明を表示します。

## 重要度の意味

| 重要度 | 内容例 |
|--------|--------|
| HIGH | name/id 変更、select の value 体系変更、form action 変更、重要 DOM（dgrSearchList 等）の消失 |
| MED | DOM 階層変更（id は残っている）、label 変更、input/select の追加・削除 |
| LOW | __VIEWSTATE 等の値の変化、テキストの微差、DOM id の追加 |

## 運用の目安

1. **定期的に snapshot を取得**し、`scripts/snapshots/` に日付付きで保存する
2. サイト側のリニューアルや障害対応後に **新しい snapshot を取得**し、前回分と **diff** する
3. 差分が出たら **impact** で `src/` の修正候補を確認し、Scraper/Parser を修正する
4. **probe** は、ドロップダウンや POSTBACK の挙動を確認したいときに手動で実行する

## マッピングの追加

`scripts/investigate/i_ppi_inspector/mapping.py` の `FIELD_TO_SRC` に、新しいフィールド名や DOM id と `src/` の実装箇所を追加すると、**impact** でその変更の影響先が出ます。

---

**作成日**: 2026年2月
