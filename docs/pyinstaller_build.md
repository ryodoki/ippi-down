# PyInstallerビルド・検証手順

この文書は、ippi-downのWindows実行ファイルをPyInstallerで作成し、検証して配布可能な状態にするための正本です。短い実行例は[README](../README.md#ビルド)、受入試験から配布までの全体手順は[デプロイ・配布手順](DEPLOYMENT.md)を参照してください。

## 1. 対象と前提

正式なビルド対象は次の環境です。

- Windows 10/11 x64
- python.orgから導入したWindows x64版Python 3.11
- Pythonに同梱されたTcl/Tk
- プロジェクト内の`.venv`
- Microsoft Edge（実運用のフォールバック。`--self-check`は未導入だけでは失敗しない）

Conda、Miniconda、AnacondaのPythonは使用しません。セットアップスクリプトとビルドスクリプトは、Pythonの実行ファイルと`base_prefix`を検査し、Conda系の環境を拒否します。グローバル環境の`pyinstaller`コマンドや、別プロジェクトの仮想環境も使用しないでください。

ビルド依存は`requirements/build.txt`、通常実行依存を含む固定バージョンは`requirements/constraints.txt`で管理します。Windows CIではさらに`requirements/windows-ci-py311.lock`にwheelのSHA-256を固定します。

## 2. 初回ビルド

プロジェクトルートをPowerShellで開き、ビルド依存を含む専用環境を準備します。

```powershell
.\scripts\setup.ps1 -WithBuild
.\scripts\build\build_exe.ps1
```

コマンドプロンプトでは次を使用します。

```bat
scripts\setup.bat -WithBuild
scripts\build\build_exe.bat
```

スクリプトは自身の配置場所からプロジェクトルートを解決するため、絶対パスで呼び出す場合は現在の作業フォルダーがプロジェクト外でも構いません。相対パスで実行する場合はプロジェクトルートから実行してください。

正常に完了すると、次のファイルを生成します。

```text
dist\ippi-down.exe
```

## 3. セットアップとビルドスクリプトの動作

`scripts/setup.ps1 -WithBuild`は次の処理を行います。

1. Python 3.11、64bit、Tcl/Tk、非Condaであることを確認する。
2. プロジェクト内に`.venv`を作成または再利用する。
3. runtime依存とbuild依存をconstraints付きで導入する。
4. 実際に使用したPythonのパスとバージョンを表示する。

`scripts/build/build_exe.ps1`は次の処理を行います。

1. `.venv\Scripts\python.exe`とTcl/Tkを再検証する。
2. `.venv`にPyInstallerが導入済みであることを確認する。
3. 使い捨ての中間物である`build\`だけを削除する。
4. `.venv`から`scripts/build/build.spec`を実行し、`build\staged-dist\ippi-down.exe`へ一時出力する。
5. 一時出力が正サイズで、Windows exeの`MZ`署名を持つことを検証する。
6. 検証済みexeだけを`dist\ippi-down.exe`へ原子的に置換する。

`dist\`はexeの実行場所にもなり、`config\`、`downloads\`、`logs\`、`self-check-result.txt`、ダウンロード履歴などの利用者データを含む場合があります。このためビルドスクリプトは`dist\`自体も、`dist\ippi-down.exe`以外の項目も削除しません。

PyInstaller、出力検証、正式exeへの置換のいずれかが失敗した場合は、従来の`dist\ippi-down.exe`を保持します。Windowsで旧exeが実行中なら原子的置換がファイルロックで安全に失敗するため、アプリを終了して再実行してください。置換を通すために`dist\`、取得文書、設定、履歴、ログを削除してはいけません。

## 4. 通常ビルド、依存更新、環境再作成

用途に応じて次の入口を使い分けます。

| 目的 | コマンド | 動作 |
|---|---|---|
| ソース変更後の通常ビルド | `.\scripts\build\build_exe.ps1` | 現在の`.venv`を使い、`build\`だけをクリーンしてexeだけを安全に更新 |
| 依存定義を変更した後の再ビルド | `.\scripts\build\rebuild_exe.ps1` | constraints付きで依存を再度`pip install`し、同じ安全なビルド処理を呼び出す |
| `.venv`を作り直して受入試験も準備する | `.\scripts\setup.ps1 -Recreate -WithTest -WithBuild` | 既存`.venv`を一時フォルダーへ退避し、テスト・ビルド依存を含む環境を新規作成 |

`rebuild_exe.ps1`は`.venv`を削除せず、`--force-reinstall`も使用しません。Python本体、Tcl/Tk、仮想環境が壊れている場合は`setup.ps1 -Recreate`を使用します。

コマンドプロンプトでは対応する`.bat`を使用できます。

```bat
scripts\build\rebuild_exe.bat
```

## 5. PyInstallerを直接実行する場合

通常はビルドスクリプトを入口にしてください。PyInstallerの詳細ログを調査するときだけ、プロジェクトルートで次を実行します。

```powershell
.\.venv\Scripts\python.exe -m PyInstaller `
  --noconfirm `
  --workpath build\pyinstaller-work `
  --distpath build\staged-dist `
  scripts\build\build.spec
```

この直接実行は、ビルドスクリプトが行うPython／Tk／Conda検証、`build\`の事前削除、出力検証、`dist\ippi-down.exe`への原子的置換を省略します。診断用の一時exeは`build\staged-dist\ippi-down.exe`に残り、正式exeを更新しません。正式な成果物を作り直す場合は`build_exe.ps1`を使用してください。`--distpath dist`や出力先指定のない直接実行は、実行用`dist\`へ書き込むため避けてください。

次のような単純な`--onefile`コマンドへ置き換えてはいけません。

```text
pyinstaller --onefile --windowed src/main.py
```

このプロジェクトは、設定例、自己診断用fixture、動的import、除外対象を`build.spec`で明示しています。`.spec`を迂回すると、ビルド自体が成功しても起動時や`--self-check`で失敗する可能性があります。

## 6. build.specの現行契約

`scripts/build/build.spec`は次を定義しています。

- entry point：`src/main.py`
- import探索ルート：プロジェクトルート
- 同梱データ：`config/config.example.yaml`
- 同梱データ：`src/resources/self_check_bid_sheet.html`
- 主なhidden import：PyYAML、requests、urllib3、Beautiful Soup、lxml、schedule
- 除外対象：pytestなどのテスト依存とPyInstaller自身
- 出力名：`ippi-down.exe`
- 形式：one-file、GUI用のconsoleなし
- 現在の設定：アイコンなし、アプリのコード署名なし、UPXは利用可能な場合のみ対象

`console=False`のため、exeをダブルクリックしてもコンソールは表示されません。診断結果はGUI、ログ、終了コード、または`self-check-result.txt`で確認します。

新しい非Pythonファイルを実行時に読む場合は`datas`への追加を検討します。文字列からimportするプラグインや、PyInstallerが静的に検出できないモジュールを追加した場合は`hiddenimports`を見直します。テスト専用または開発専用の大きな依存は、実行時に不要であることを確認して`excludes`を更新します。

## 7. ビルド後の検証

### 7.1 生成物とSHA-256

```powershell
Get-Item .\dist\ippi-down.exe | Select-Object FullName, Length, LastWriteTime
Get-FileHash .\dist\ippi-down.exe -Algorithm SHA256
```

現在のビルドはexe自体へAuthenticodeコード署名を付与しません。配布時は`make_exe_release.ps1`が生成する`SHA256SUMS.txt`で整合性を確認します。組織でコード署名が必須の場合は、証明書管理と署名工程を別途設計し、署名前後のハッシュを混同しないでください。

### 7.2 exe自己診断

GUIなしで終了コードを確実に取得するには、PowerShellから次を実行します。

```powershell
$selfCheck = Start-Process `
  -FilePath .\dist\ippi-down.exe `
  -ArgumentList --self-check `
  -WindowStyle Hidden `
  -Wait `
  -PassThru
$selfCheck.ExitCode
Get-Content .\dist\self-check-result.txt
```

終了コード0が合格です。自己診断では次を確認します。

- Python/Tkを含むexeの起動
- 一意な診断用Windowsタスクの登録、照会、削除
- 内蔵PDF生成器、同梱日本語フォント、pypdf再読込検証
- Edgeフォールバック用Windows Job Object監視機構
- 同梱fixtureを使ったオフラインHTML→PDF生成
- PDF署名、終端、サイズ、SHA-256、A4縦MediaBox
- 一時HTML、PDF、Edgeプロファイルの後処理

診断用タスクは通常の定期実行タスクや検索条件を変更しません。`self-check-result.txt`は診断結果であり、配布zipには含めません。

### 7.3 配布zip

自己診断に合格したexeから、開発・監査用のソースzipと利用者向けexe zipを別々に生成します。

```powershell
.\scripts\tools\make_source_release.ps1
.\scripts\tools\make_exe_release.ps1
```

出力は`release\ippi-down-source.zip`と`release\ippi-down-windows-x64.zip`です。exe zipはexe、利用者向けREADME、設定例、正本仕様書、`SHA256SUMS.txt`だけを含み、実設定、ログ、取得文書、仮想環境、ビルド中間物は含めません。

## 8. CIと再現可能な依存導入

GitHub ActionsのWindows CIは、Python 3.11環境へ次の考え方で依存を導入します。

```powershell
python -m pip install `
  --disable-pip-version-check `
  --only-binary=:all: `
  --require-hashes `
  -r requirements\windows-ci-py311.lock
python -m pip check
python scripts\security\generate_sbom.py --output artifacts\sbom.cdx.json
python -m compileall -q src tests scripts
ruff check src tests scripts --select E9,F63,F7,F82
pytest tests -v
python -m PyInstaller scripts\build\build.spec
& scripts\security\run_offline_self_check.ps1 -ExePath dist\ippi-down.exe
& scripts\tools\make_source_release.ps1 -OutputDir release
& scripts\tools\make_exe_release.ps1 -OutputDir release
```

CIは構文検査、Ruff、実通信を遮断したpytest、SBOM生成、exeビルド、外向き通信を一時的にFirewallで拒否した自己診断、配布zip検査まで行います。`run_offline_self_check.ps1`は管理されたCI環境で一時的なFirewallルールを作成して必ず後処理するためのスクリプトです。通常の開発PCでは安易に実行せず、通常の`--self-check`を使用してください。lockを更新するときは、Windows x64／CPython 3.11用wheelの版とSHA-256を同時にレビューしてください。

開発PCの通常セットアップでは`constraints.txt`を使用し、CIと正式な依存監査ではハッシュ付きlockを使用します。両者でPyInstallerやhookの版がずれた場合は、constraintsとlockを同じ変更として更新します。

## 9. トラブルシューティング

### Python 3.11 x64が見つからない

python.org版Python 3.11をTcl/Tk付きで導入し、Python Launcherを有効にします。自動検出できない場合は、非Condaの実行ファイルを明示します。

```powershell
.\scripts\setup.ps1 `
  -PythonExe "C:\Users\<ユーザー名>\AppData\Local\Programs\Python\Python311\python.exe" `
  -WithBuild
```

### Miniconda／CondaのPythonを参照する

既存`.venv`が過去のConda環境を参照している場合は再作成します。

```powershell
.\scripts\setup.ps1 -WithBuild -Recreate
```

`.venv\pyvenv.cfg`を手作業で書き換えたり、別環境の`python.exe`だけをコピーしたりしないでください。

### Tcl/Tkまたは`init.tcl`のエラー

Python本体をTcl/Tk付きで修復または再インストールし、`.venv`を再作成します。ビルドスクリプトがTk検査で停止する状態のままPyInstallerを直接実行しないでください。

### PyInstallerがない

```powershell
.\scripts\setup.ps1 -WithBuild
```

グローバルへ`pip install pyinstaller`するのではなく、プロジェクトの`.venv`へconstraints付きで導入します。

### PowerShellのExecutionPolicyでスクリプトを実行できない

まず組織の実行ポリシーを確認してください。一時的な回避を独断で設定せず、許可されている場合に限り、コマンドプロンプト用の`.bat`入口または組織指定のPowerShell起動方法を使用します。署名されていないスクリプトの実行を恒久的に全許可する設定は、このビルドの前提にしません。

### プロジェクトパスに空白がある

同梱スクリプトは`$PSScriptRoot`とリテラルパスを使用するため、通常は空白を含むパスでも実行できます。手入力でPythonのパスを指定するときは、PowerShellの呼び出し演算子と引用符を使用してください。

```powershell
& '.\.venv\Scripts\python.exe' -m PyInstaller 'scripts\build\build.spec'
```

### `build`を削除できない

別のPyInstaller処理、エクスプローラーのプレビュー、ウイルス対策ソフトによるスキャンが`build\`内の中間物を保持していないか確認します。ビルドスクリプトは`dist\`を削除しないため、このエラーへの対処として`dist\`や利用者の`downloads`、`logs`を削除してはいけません。

### `dist\ippi-down.exe`を置換できない

起動中の`ippi-down.exe`を終了し、タスクマネージャーでもプロセスが残っていないことを確認してから再実行します。ウイルス対策ソフトが検査中の場合は完了を待ちます。置換失敗時は旧exeが維持され、一時出力は`build\staged-dist\ippi-down.exe`に残ります。旧exeを削除したり、別名へ退避したり、`dist\`内の設定・ログ・取得文書を移動したりする必要はありません。

### ビルド成功後にmoduleまたはデータファイルが見つからない

PyInstallerの警告と`build.spec`の`hiddenimports`、`datas`を確認します。単純な`--onefile`コマンドへ切り替えず、`.spec`を修正して回帰テストと`--self-check`を実行します。

### ウイルス対策ソフトやSmartScreenが警告する

one-file形式や未署名exeは警告対象になる場合があります。配布元の`SHA256SUMS.txt`と照合し、組織のセキュリティ手順に従って確認します。警告回避のためにウイルス対策機能を無効化しないでください。

### 自己診断でPDF生成・監視関連の失敗になる

`self-check-result.txt`の日本語理由と理由コードを確認します。`PDF_INTERNAL_RENDER_FAILED`は内蔵生成失敗、`PDF_CONTENT_VALIDATION_FAILED`は生成PDFの内容検証失敗、`EDGE_SUPERVISION_UNAVAILABLE`はEdge用の全プロセス監視不可を示します。Edge本体がないことだけでは自己診断を失敗にしません。詳細は[入札調書PDF生成・監視仕様](pdf_conversion_reliability.md)を確認してください。

## 10. 変更時のチェックリスト

PyInstallerや実行時依存を変更するときは、次を同じ変更として確認します。

- `requirements/build.txt`、`constraints.txt`、Windows用hash lockの整合
- `build.spec`のentry point、datas、hidden imports、excludes
- `build_exe.ps1`と`build_exe.bat`の同等性
- 4つのbuild/rebuildスクリプトが`dist\`を再帰削除せず、一時出力を検証してexeだけを置換すること
- `dist\ippi-down.exe --self-check`の終了コード0
- 標準pytestとRuff
- ソースzipとexe zipの内容検査
- exeのSHA-256とSBOMの更新

利用者の実設定、ログ、取得文書をビルドや配布物へ混入させないことも必ず確認してください。
