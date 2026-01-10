# リポジトリクリーンアップ手順

## 目的

リポジトリから「環境・生成物・実行結果・ローカル設定」を排除し、差分が汚れない構成にする。  
Git追跡状態をクリーンにし、配布やレビューが成立する状態にする。

## 注意事項

以下のディレクトリ・ファイルは **Git で追跡されていません**（`.gitignore` で除外されています）:
- `.venv/` - 仮想環境
- `__pycache__/` - Pythonキャッシュ
- `.pytest_cache/` - pytestキャッシュ
- `build/` - PyInstallerビルド作業ディレクトリ
- `dist/` - PyInstaller生成物（.exeファイル）
- `logs/` - ログファイル
- `downloads/` - ダウンロード結果ファイル
- `config/config.yaml` - ローカル設定ファイル（機密情報を含む可能性）

**これらのファイル・ディレクトリはローカルに残すことができます**（追跡されないだけです）。

## 既にGitで追跡されている場合の対処

過去に誤ってこれらのファイルがGitに追加されてしまった場合、以下のコマンドで **追跡を解除** してください。

**重要**: これらのコマンドはローカルファイルを削除しません。Gitの追跡から外すだけです。

### 追跡解除コマンド

```bash
# 仮想環境の追跡解除
git rm -r --cached .venv

# ビルド生成物の追跡解除
git rm -r --cached build
git rm -r --cached dist

# ログ・ダウンロード・キャッシュの追跡解除
git rm -r --cached logs
git rm -r --cached downloads
git rm -r --cached .pytest_cache

# 設定ファイルの追跡解除（ローカル設定のみ）
git rm --cached config/config.yaml

# Pythonキャッシュの追跡解除（すべての__pycache__）
git rm -r --cached **/__pycache__
# または、特定のディレクトリのみ
git rm -r --cached src/__pycache__
git rm -r --cached tests/__pycache__
```

### 一括で実行する場合（PowerShell）

```powershell
# PowerShellで実行
git rm -r --cached .venv, build, dist, logs, downloads, .pytest_cache -ErrorAction SilentlyContinue
git rm --cached config/config.yaml -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | ForEach-Object { git rm -r --cached $_.FullName -ErrorAction SilentlyContinue }
```

### 変更をコミット

追跡解除後、変更をコミットしてください：

```bash
git add .gitignore
git commit -m "chore: remove tracked files that should be ignored"
```

## 現在の追跡状態を確認

以下のコマンドで、不要なファイルが追跡されていないことを確認できます：

```bash
# 追跡されている不要なファイルを検索
git ls-files | grep -E "\.venv|__pycache__|\.pytest_cache|^build/|^dist/|^downloads/|^logs/|config/config\.yaml|\.pyc$"

# PowerShellの場合
git ls-files | Select-String -Pattern "\.venv|__pycache__|\.pytest_cache|^build/|^dist/|^downloads/|^logs/|config/config\.yaml|\.pyc$"
```

**結果が空**なら、適切に除外されています。

## クリーンな状態を確認する

以下のコマンドで、リポジトリがクリーンな状態であることを確認できます：

```bash
# Gitステータスを確認
git status

# 追跡されているファイル数を確認（軽量なリポジトリであることを確認）
git ls-files | wc -l

# 追跡されているファイルの主な構成を確認
git ls-files | cut -d'/' -f1 | sort | uniq -c | sort -rn
```

**期待される結果**:
- `git status` が clean であること
- `src/`, `tests/`, `docs/`, `config/config.example.yaml` が中心の軽量なリポジトリであること
- `.venv`, `build`, `dist`, `logs`, `downloads`, `config/config.yaml` が含まれていないこと

---

## クリーンなzip配布用パッケージの作成

配布用のzipファイルを作成する際は、不要なファイルを除外してください。

### PowerShell（Windows）での例

```powershell
# 現在のディレクトリに移動
cd C:\Users\ryout\Workspaces\ippi-down

# 除外するディレクトリ・ファイルを指定
$excludeItems = @(
    ".venv",
    "build",
    "dist",
    "logs",
    "downloads",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "*.pyc",
    "*.log",
    "config/config.yaml"
)

# 一時的なexcludeリストファイルを作成（7-Zipを使用する場合）
$excludeList = Join-Path $env:TEMP "zip-exclude.txt"
$excludeItems | ForEach-Object { Write-Output $_ } | Out-File -FilePath $excludeList -Encoding UTF8

# 7-Zipを使用してクリーンなzipファイルを作成
# 7-Zipがインストールされている必要があります
$zipPath = "ippi-down-clean.zip"
$sourceDir = "."
& "C:\Program Files\7-Zip\7z.exe" a -tzip $zipPath $sourceDir -x@"$excludeList"

Write-Host "クリーンなzipファイルを作成しました: $zipPath"
```

### PowerShell Compress-Archiveを使用する場合

`Compress-Archive` には除外オプションがないため、一時ディレクトリに必要なファイルのみをコピーしてからzip化します。

```powershell
# 現在のディレクトリに移動
cd C:\Users\ryout\Workspaces\ippi-down

# 除外するディレクトリ・ファイルを指定
$excludeItems = @(
    ".venv",
    "build",
    "dist",
    "logs",
    "downloads",
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".pyc",
    ".log"
)

# 一時ディレクトリを作成
$tempDir = Join-Path $env:TEMP "ippi-down-clean"
if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
New-Item -ItemType Directory -Path $tempDir | Out-Null

# 必要なファイルのみをコピー
Get-ChildItem -Path . -Recurse -Force | Where-Object {
    $item = $_
    $relativePath = $item.FullName.Substring((Get-Location).Path.Length + 1)
    $shouldExclude = $false
    
    # config/config.yamlを除外
    if ($relativePath -eq "config\config.yaml" -or $relativePath -eq "config/config.yaml") {
        $shouldExclude = $true
    }
    
    # 除外リストに一致するかチェック
    foreach ($exclude in $excludeItems) {
        if ($relativePath -like "*$exclude*") {
            $shouldExclude = $true
            break
        }
    }
    
    # 隠しファイル・ディレクトリを除外（.git, .venvなど）
    if ($item.Name -match "^\.") {
        $shouldExclude = $true
    }
    
    -not $shouldExclude
} | ForEach-Object {
    $destPath = $_.FullName.Replace((Get-Location).Path, $tempDir)
    $destDir = Split-Path $destPath -Parent
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Copy-Item $_.FullName -Destination $destPath -Force
}

# zipファイルを作成
$zipPath = "ippi-down-clean.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$tempDir\*" -DestinationPath $zipPath -Force

# 一時ディレクトリを削除
Remove-Item $tempDir -Recurse -Force

Write-Host "クリーンなzipファイルを作成しました: $zipPath"
```

### 確認事項

zipファイルを作成後、以下の点を確認してください：

1. zipファイルサイズが適切であること（`.venv/` が含まれていない場合、大幅に軽量になる）
2. `config/config.yaml` が含まれていないこと
3. `.git/` ディレクトリが含まれていないこと（配布物としては不要）
4. `src/`, `tests/`, `docs/`, `config/config.example.yaml` が含まれていること

---

**作成日**: 2026年1月10日  
**最終更新**: 2026年1月10日
