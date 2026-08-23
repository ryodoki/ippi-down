# リリース・梱包手順

梱包・レビュー用ZIPは **`scripts/tools/`** で一本化しています。

## 生成物について

- **リポジトリに含めないもの**: `.venv/`, `build/`, `dist/`, `logs/`, `downloads/`, `scripts/snapshots/`, `release/`, `*.zip`, `_review_pack/`, **`config/config.yaml`**
- 設定は **`config.example.yaml` のみ**リポジトリに含め、実運用の `config.yaml` はローカルでコピーして編集する運用です。ZIP には `config.yaml` を同梱しません。

## レビュー用ZIP（PowerShell コピペ）

```powershell
# プロジェクトルートで実行
cd <プロジェクトのパス>
powershell -ExecutionPolicy Bypass -File .\scripts\tools\pack_for_review.ps1
```

- **出力**: ルートに `ippi-down_review.zip`、一時フォルダ `_review_pack/`
- **含まれるもの**: `src/`, `tests/`, `docs/`, `scripts/`, `config/config.example.yaml`, `README.md`, `requirements.txt` 等
- **除外**: 上記「生成物」＋ `config/config.yaml`

## クリーン配布用ZIP

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\tools\make_release_zip.ps1 -OutputName ippi-down-clean.zip
```

- **出力**: `release/ippi-down-clean.zip`

## 実行ファイル（.exe）ビルド

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build\build_exe.ps1
```

- 成果物: `dist/` 配下（Git 管理外）
