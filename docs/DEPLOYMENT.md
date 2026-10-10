# デプロイ・配布手順

正式な対象はWindows 10/11 x64、Python 3.11、ローカル保存です。HTML形式の入札調書は同梱フォントを使う内蔵生成器でPDF化し、失敗時だけMicrosoft Edgeを監視付きで使用します。Box、custom cron、複数発注機関、PCログオン時の自動登録はこの手順の対象外です。

## 開発環境の準備

Conda／Minicondaは使用しません。次のスクリプトは自身の配置場所を基準にプロジェクトルートを解決し、Windows x64版Python 3.11からプロジェクト専用`.venv`を作成します。壊れた既存`.venv`は一時フォルダーへ退避します。

```powershell
.\scripts\setup.ps1 -WithTest -WithBuild
```

親フォルダーから`.\.venv\Scripts\python.exe`を実行すると、別プロジェクトの仮想環境を選ぶ可能性があります。必ずプロジェクト内の`setup.ps1`、`start_gui.ps1`、またはビルドスクリプトを入口にしてください。

設定例をコピーする場合は、実値や秘密情報を配布物へ含めないでください。

```powershell
Copy-Item config\config.example.yaml config\config.yaml
```

## 受入チェック

構文、静的解析、保存済みfixtureを使う標準テストを実行します。

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\ruff.exe check src tests scripts --select E9,F63,F7,F82
.\.venv\Scripts\python.exe -m pytest tests -v
```

Windows CI／正式ビルドの依存導入は、`requirements/windows-ci-py311.lock`を
`--require-hashes --only-binary=:all:`で使用します。lock更新時はWindows x64の
CPython 3.11 wheelを取得し、版とSHA-256を同時にレビューしてください。
CIは`pip check`と`scripts/security/generate_sbom.py`も実行し、
`artifacts/sbom.cdx.json`を生成します。

GUI、integration、networkテストは標準実行から分離されています。実行方法は[README](../README.md#テスト)を参照してください。

## exeビルド

必要環境、通常ビルドと依存更新時の再ビルド、`build.spec`の内容、成果物の検証、トラブル対処の正本は[PyInstallerビルド・検証手順](pyinstaller_build.md)です。どの作業ディレクトリからでも、スクリプト自身の場所を基準にプロジェクトルートを解決します。

```powershell
.\scripts\setup.ps1 -WithBuild
.\scripts\build\build_exe.ps1
```

コマンドプロンプトの場合:

```bat
scripts\build\build_exe.bat
```

生成物は`dist/ippi-down.exe`です。ビルド後は自己診断を実行します。この診断は内蔵PDF生成、同梱日本語フォント、生成PDFの再読込検証、Edge用Job Object監視機構、PDF署名・終端・サイズ・SHA-256・A4縦MediaBox、後処理を確認します。変換用の一時HTML、PDF、Edgeプロファイルは後処理で削除し、consoleなしのexeでは診断結果だけをexeと同じ場所の`self-check-result.txt`へ更新します。Windows CIでは`scripts/security/run_offline_self_check.ps1`によりexeとEdgeだけを対象とする一時的な外向き通信拒否ruleを作成し、`finally`でruleを削除してから終了します。

```powershell
$selfCheck = Start-Process `
  -FilePath .\dist\ippi-down.exe `
  -ArgumentList --self-check `
  -WindowStyle Hidden `
  -Wait `
  -PassThru
if ($selfCheck.ExitCode -ne 0) { throw "exe self-check failed" }
```

## 配布zip

ソース配布とexe配布は別々に作成します。

```powershell
.\scripts\tools\make_source_release.ps1
.\scripts\tools\make_exe_release.ps1
```

既定の出力:

- `release/ippi-down-source.zip`
- `release/ippi-down-windows-x64.zip`

ソースzipはビルド可能な`README.md`、[PyInstallerビルド・検証手順](pyinstaller_build.md)、[ダウンロードフォルダー仕様](download_folder_spec.md)、`scripts/build/build.spec`、`requirements/`、テストfixtureを含みます。exe zipの内容は次の10ファイルに限定します。

- `ippi-down.exe`
- exe利用者向け`README.md`
- 正本と同一内容の`download_folder_spec.md`
- 正本と同一内容の`memory_resource_management.md`
- 正本と同一内容の`network_security.md`
- 正本と同一内容の`pdf_conversion_reliability.md`
- `THIRD_PARTY_NOTICES.txt`
- Noto Sans Japaneseの`OFL-1.1.txt`
- `config/config.example.yaml`
- `SHA256SUMS.txt`

exe利用者向けREADMEの保存仕様リンクは、同じzip内の`download_folder_spec.md`を参照します。配布スクリプトは`docs/download_folder_spec.md`をそのままコピーし、配布検査では正本とのバイト単位の一致とREADME内のローカルリンク解決を確認します。

どちらのzipにも次を含めません。

- `config/config.yaml`、`.env`などの実設定・秘密情報
- `config/install-location.json`、`config/installation-relocation-journal.json`、`config/schedule-instance-id`、定期実行台帳、スナップショットなど配置固有の所有情報
- `logs/`、`downloads/`、取得文書、`.part`
- `debug/`、実行時に生成されたデバッグHTML
- `.venv/`、`build/`、キャッシュ

## 配布先での確認

1. zipのSHA-256を配布元の値と照合します。
2. Windows 10/11 x64のクリーン環境で展開します。
3. `ippi-down.exe --self-check`の終了コードが0であることを確認します。
4. GUIを起動し、設定例からローカル保存先を指定します。
5. 保存済みfixtureとは別に実サイト確認を行う場合は、既定1リクエスト/秒と初回を含む最大3試行を維持します。

GUIの受入では、設定画面の定期実行タブで管理対象を選び、実行中・順番待ち・再試行待機中でも編集が押せること、確認画面の案内と「今すぐ実行」の無効状態を確認します。小さい画面では操作ボタンと保存・キャンセルが見え、登録内容と履歴の右側の列へスクロールで到達できることを確認します。配布先のexeが想定版か調べる場合は、配布元と配布先で`Get-FileHash ippi-down.exe -Algorithm SHA256`の値を照合します。

ユーザーの既存`config/config.yaml`、ログ、ダウンロード済み文書は更新時に削除しません。新しいexeまたはソースへ置き換えた後も、これらは利用者側でバックアップ・管理してください。

自己診断が失敗した場合は`self-check-result.txt`を確認します。`PDF_INTERNAL_RENDER_FAILED`は内蔵生成失敗、`PDF_CONTENT_VALIDATION_FAILED`は内容検証失敗、`EDGE_SUPERVISION_UNAVAILABLE`はEdge用の全プロセス監視不可を示します。Edge本体がないことだけでは自己診断を失敗にしません。実行時の詳細は[入札調書PDF生成・監視仕様](pdf_conversion_reliability.md)を参照してください。
