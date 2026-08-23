# ネットワークポリシー（ippi-down）

このツールは公開情報サイトから資料を取得します。相手のサーバーは共有資源なので、
**「許可した宛先だけ」「相手の指示（robots.txt）に従う」「負荷をかけない」「身元を明かす」**
の4点を機械的に守るようにしてあります。

## 許可している通信

| 項目 | 既定値 |
|---|---|
| 許可ホスト | `www.i-ppi.jp` |
| 許可スキーム | `https` のみ |
| 許可ポート | 443 |
| 内部ネットワーク宛（プライベート IP） | 遮断（SSRF 対策） |
| 同一ホストへの最小間隔 | 1.0 秒（robots の `Crawl-delay` が長ければそちらを採用） |
| 同時接続数 | 1 |
| 1回の実行のリクエスト上限 | 500 |
| 稼働時間帯 | 制限なし（`allowed_hours` で設定可能） |

設定は `config/config.yaml` の `network` セクションです（`config/config.example.yaml` を参照）。
`target_urls` のホストが `allowed_hosts` に無い場合、**起動時にエラーで停止**します。

## どう強制しているか

1. **エグレスガード**（`src/utils/netguard.py`）: `socket.getaddrinfo` を差し替え、許可外ホストは
   名前解決の時点で `BlockedConnectionError`。`connect` / `connect_ex` / `sendto` も差し替え、
   IP 直打ちとプライベート IP 宛を遮断します。`src/main.py` と `src/cli/main.py` の冒頭で有効化します。
2. **URL 検査**（`HTTPClient._check_url`）: `get` / `post` / `download_file` の入口でスキームと
   ホストを照合します。HTML から抽出した動的リンク（添付ファイル等）も必ずここを通ります。
3. **robots.txt**（`src/utils/robots.py`）: ホストごとに1回取得してキャッシュ（既定 24 時間）。
   `Disallow` の URL は取得しません。`Crawl-delay` / `Request-rate` は最小間隔の下限として採用します。
   取得できなかったときの既定は**ブロック**（`network.robots.on_error: allow` で緩められます）。
   404（robots.txt が無い）は制限なし、401/403 は全面禁止として扱います（RFC 9309）。
4. **レート制限**（`src/utils/rate_limiter.py`）: ホスト単位の最小間隔（±20% のジッタ）、
   同時接続数、実行あたりのリクエスト上限、稼働時間帯。429 を受けたら以後の最小間隔を倍にします。
5. **身元の明示**: UA の末尾に `ippi-down/<version> (+連絡先)` を付加します。
   robots.txt の `User-agent` 行との照合には製品トークン（`ippi-down`）を使います。
   `network.user_agent` を指定すると UA を完全に置き換えられます（ブラウザ表記をやめる場合）。
6. **静的検査**: `requests` で送信するのは `http_client.py` のみ、`socket` は `netguard.py` のみ、
   `selenium` / `playwright` / `urllib.request` は使用禁止。テストで機械的に検証します。

### UA を偽装のままにしている理由

既定は「現行のブラウザ UA に識別子を付加する」形です。サイト側が UA でレスポンスを
変えるため、完全に正直な UA へ切り替えると取得できなくなる可能性があります。
運用として望ましいのは `network.user_agent` に自分の名前と連絡先だけを設定することで、
接続性を確認できたらそちらへ移行してください。

## 監査ログの見方

`network.audit_log`（既定 `./logs/network.log`）に、判定ごとに TSV で1行記録します。

列: `時刻 / 判定 / メソッド / 宛先 / ステータス / バイト数 / 所要ms / 詳細`

判定は次の4種です。

| 判定 | 意味 |
|---|---|
| `allow` | 送信した（相手からの応答も記録） |
| `blocked` | ポリシー違反（許可外ホスト・スキーム）で送信を中止した |
| `robots_denied` | robots.txt により取得しなかった |
| `rate_limited` | 相手から 429 を受けた（以後の間隔を倍にした） |

エグレスガードの記録はメソッド列が `GUARD` になります。

## ポリシーを変更する手順

1. 対象サイトの利用規約と robots.txt を確認し、許諾が必要なら取得する
2. `config.yaml` の `network.allowed_hosts` を変更する（`target_urls` との整合は起動時に検証されます）
3. 間隔を短くする場合は相手の規模と時間帯を考慮する。既定より短くする変更はレビュー必須
4. `tests/test_url_policy.py` / `tests/test_config_network.py` を更新する

## やらないこと

- 認証・アクセス制限の回避、CAPTCHA の回避
- robots.txt で `Disallow` された領域の取得
- 取得したデータの再配布（利用規約に反する二次利用）
- 短い間隔・多数の並列接続による過負荷
- 個人情報の収集を目的とした取得

robots.txt の `Disallow` が必要なページを含んでいた場合、機能は停止します。
それは「取得してよいか」を判断する材料そのものなので、ログとエラーメッセージで理由を示し、
運用側でサイト管理者へ許諾を取るかどうかを判断してください。

## 検証方法

```powershell
# ガードレール関連のテストだけを実行
.\scripts\check_guardrails.ps1

# 全テスト（実通信テストは既定でスキップ）
python -m pytest
```

テスト実行中は `tests/conftest.py` がソケットを遮断します。実通信が必要なテストには
`@pytest.mark.network` を付け、`RUN_NETWORK_TESTS=1` で明示的に有効化してください。
