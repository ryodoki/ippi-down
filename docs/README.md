# ドキュメント索引（ippi-down）

このフォルダの文書は次の2種類に分かれます。

## 現行（実装と揃えて保守する）

| 文書 | 内容 |
|---|---|
| [../README.md](../README.md) | 概要・セットアップ・使い方（入口） |
| [network-policy.md](network-policy.md) | 通信許可リスト・robots・レート制限・監査ログ |
| [batch-operation.md](batch-operation.md) | タスクスケジューラによる定期実行 |
| [../config/config.example.yaml](../config/config.example.yaml) | 設定の雛形 |
| [requirements.md](requirements.md) | 機能要件 |
| [REQUIREMENTS_TRACEABILITY.md](REQUIREMENTS_TRACEABILITY.md) | 要件トレーサビリティ |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 配布・配置 |
| [RELEASE_AND_PACK.md](RELEASE_AND_PACK.md) | リリースと梱包 |
| [SITE_CHANGE_MONITORING.md](SITE_CHANGE_MONITORING.md) | サイト変更の監視 |
| [EXECUTION_AND_REGRESSION.md](EXECUTION_AND_REGRESSION.md) | 実行・回帰手順 |
| [acceptance_checklist.md](acceptance_checklist.md) | 受け入れチェックリスト |
| [verification.md](verification.md) | 検証手順 |

## アーカイブ（歴史文書）

`archive/` 配下は調査・リファクタ途中のメモや古い要件草案です。
**現行の実装や設定と一致しない可能性があります。** 運用の判断材料には使わないでください。

| 場所 | 内容 |
|---|---|
| [archive/refactor/](archive/refactor/) | リファクタ設計メモ |
| [archive/investigation/](archive/investigation/) | サイト調査・差分監査 |
| [archive/reports/](archive/reports/) | 実装報告・ギャップ分析・旧設定要件など |
| [archive/dev-notes/](archive/dev-notes/) | 開発メモ |

Azure VM での定期実行は Workspaces 直下の兄弟フォルダ
[../../azure-batch-vm/docs/runbook.md](../../azure-batch-vm/docs/runbook.md) を参照してください。
