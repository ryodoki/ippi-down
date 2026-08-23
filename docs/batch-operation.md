# 定期バッチ運用ガイド

ippi-down を Windows タスクスケジューラで定期実行するための手順です。
ローカル PC でも Azure VM でも同じスクリプトを使います（Azure VM の構築は
[../../azure-batch-vm/docs/runbook.md](../../azure-batch-vm/docs/runbook.md) を参照。
Workspaces 直下の兄弟フォルダです）。

GUI 内蔵のスケジューラ（`schedule.enabled` / `--background`）は GUI を開いたまま使う用途向けで、
無人運用ではプロセスの死活管理ができるタスクスケジューラ方式を推奨します。

## 仕組み

```
タスクスケジューラ
  └─ scripts\schedule\run_batch.ps1（ランナー）
       └─ python src\cli\main.py --once --report logs\reports\batch_<日時>.json
```

- 既定のタスク名は `ippi-down-daily`（`register_task.ps1` / `status_task.ps1` / `unregister_task.ps1` の既定）
- `register_task.ps1` はランナー起動時に `-TaskName` を渡すため、履歴・イベントログのソース名は登録したタスク名と一致します
- ランナーは CLI の終了コードをそのまま返すため、タスクスケジューラの「前回の実行結果」で成否が分かります（0 が成功）
- 実行ごとに `logs\batch-history.log` へ 1 行（開始/終了/exit/タスク名/レポートパス）追記します
- レポート JSON には成功/失敗/スキップ件数・失敗理由別サマリー・所要時間が入ります
- 失敗時は Windows イベントログ（Application、ソース=タスク名）にも書き込みます（ソース登録済みの場合）

## スケジュール登録

```powershell
cd scripts\schedule

# 毎日 9:30 に実行
.\register_task.ps1 -Time "09:30" -Interval Daily

# 設定ファイルを指定 / 毎週月曜
.\register_task.ps1 -Time "09:30" -ConfigPath ..\..\config\config.yaml
.\register_task.ps1 -Interval Weekly -DayOfWeek Monday -Time "10:00"
```

- 同名タスクは上書き更新されます
- 管理者 PowerShell で実行すると、失敗通知用のイベントログソースも登録されます（推奨・初回のみ）

### allowed_hours との整合

設定の `network.allowed_hours`（例 `"08:00-22:00"`）が実行時刻を含まないと、
アプリ側のネットワークポリシーで実行が停止します。`register_task.ps1` は登録時に
整合を検査して範囲外なら警告します。スケジュールを深夜に変える場合は
`allowed_hours` も合わせて見直してください。

また `network.max_requests_per_run`（既定 500）は 1 回の実行あたりの上限です。
定期実行の頻度を上げても、この上限とレート制限（最小間隔 1 秒）はそのまま適用されます。

## 状態確認・手動実行・削除

```powershell
.\status_task.ps1                              # 前回結果・次回予定・履歴の表示
Start-ScheduledTask -TaskName ippi-down-daily  # 即時実行
.\unregister_task.ps1                          # 削除
```

## 失敗時の切り分け

1. `.\status_task.ps1` で「前回の実行結果」を確認（0 以外なら失敗）
2. `logs\reports\batch_*.json` の `message` / `failure_summary` を確認
   - `network` が多い → サイト側または回線の問題。時間を置いて再実行
   - `rate_limit` がある → 実行間隔が近すぎる。頻度を下げる
3. `logs\network.log`（監査ログ）にブロック記録がないか確認
   - `robots_denied` → 対象ページが robots.txt で拒否されている。取得可否の再確認が必要
   - `blocked` → 許可リスト外への接続試行。設定の `target_urls` を確認
4. exit 99 → ランナー自体のエラー。`batch-history.log` の `runner-error` 行を確認

## 手動でランナーを試す

```powershell
# ドライランで動作確認（ダウンロードは行わない）
.\run_batch.ps1 -DryRun
```
