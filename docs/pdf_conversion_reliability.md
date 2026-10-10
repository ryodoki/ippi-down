# 入札調書PDF生成・監視仕様

## 生成順序

HTML形式で公開される入札調書は、通信層で一度だけ取得し、既存の必須項目検証と無害化を完了してからPDFへ変換する。

1. 内蔵生成器が、無害化済みHTMLを実行要素のない帳票モデルへ変換する。
2. 同梱したNoto Sans JapaneseとReportLabでA4縦・余白10 mmのPDFを隔離プロセス内に生成する。
3. pypdfでPDFを再読込し、暗号化なし、1～100ページ、全ページA4縦、案件名・表の全文字列が抽出できることを確認する。
4. 内蔵生成が失敗した場合だけMicrosoft Edgeへ切り替える。
5. Edgeも失敗した場合は、正式な保存ファイルへ置換しない。

フォント、表の行数・列数、行結合・列結合を固定値の機関一覧や特定案件へ依存させない。HTML中のscript、外部リソース、イベント属性は従来の無害化工程で除去し、PDF生成器がネットワーク通信する機能は持たない。

## Edgeフォールバックの監視

EdgeはWindows Job Objectへ停止状態の親プロセスを登録した後に開始する。親プロセスだけでなく、そのJobに属するGPU・renderer等の全子プロセスを監視する。

- 親プロセス終了だけを成功条件にしない。Jobの`ActiveProcesses`が0になった後でPDFを検証する。
- Jobへ登録できない場合は、監視なしでEdgeを起動せず`EDGE_SUPERVISION_UNAVAILABLE`で停止する。
- キャンセルまたは時間超過ではJob全体を終了し、全プロセスの終了を待つ。
- GPUクラッシュ、プロセス異常終了、正常終了したがPDFがない状態を別の理由コードにする。
- 一時障害だけを、試行ごとに独立したEdge profileで最大2回試す。起動禁止、署名不正、入力不正は再試行しない。

## 監査ログ

変換ごとに32桁の`conversion_id`を発行し、手動・定期実行の`run_id`、案件名、文書名、生成方式、生成器版、各試行、Edgeのroot PID、プロセス数変化、5秒間隔heartbeat、終了コード、処理時間、出力サイズ、SHA-256、最終理由コードを`logs/pdf-conversions-YYYY-MM-DD.jsonl`へ記録する。

- 1ファイル10 MiBで同日partへローテーションする。
- 監査ログは90日を超えたものを次回変換開始時に削除する。
- URLのquery値、Cookie、HTTP本文、WebForms hiddenは記録しない。
- メイン画面の「PDF変換履歴」で直近200件を確認できる。完全なイベント列は日別JSONLを正本とする。

## 障害資料

すべての生成方式が失敗した場合、再現に必要な無害化済みHTMLとmanifest、Edge標準エラー末尾、障害記録を`logs/pdf-failures/<conversion_id>/`へ保持する。保存期間は30日で、次回変換開始時に期限切れだけを削除する。

障害資料には案件名や入札結果などの業務情報が含まれる。GUIの「PDF変換履歴」からローカルフォルダーを開けるが、自動送信はしない。外部へ提供する場合は内容と組織の取扱規則を確認する。

## 主な理由コード

- `PDF_INTERNAL_RENDER_FAILED`: 内蔵生成のモデル化、フォント、隔離プロセスまたは検証に失敗
- `PDF_CONTENT_VALIDATION_FAILED`: 生成PDFの必須内容を再確認できない
- `EDGE_SUPERVISION_UNAVAILABLE`: Edgeの全プロセスを安全に監視できない
- `EDGE_PROCESS_CRASH`: Edgeプロセスが異常終了
- `EDGE_GPU_PROCESS_CRASH`: GPUプロセス障害を検出
- `EDGE_OUTPUT_NOT_PRODUCED`: 全プロセス終了後もPDFがない
- `CONVERSION_TIMEOUT`: 制限時間内に終わらない
- `PDF_RECOVERY_ARTIFACT_STORED`: 再変換用の障害資料を保存したことを示す警告

`--self-check`は内蔵生成、同梱フォント、PDF再読込検証、一時ファイル後処理と、WindowsでEdge監視機構を利用できることをオフライン確認する。Edge本体がないことだけでは、内蔵生成の自己診断を失敗にしない。

