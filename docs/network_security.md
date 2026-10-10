# 外向き通信・ローカル実行セキュリティ仕様

**仕様版**: 1.0  
**更新日**: 2026-08-17  
**対象**: Windows 10/11 x64、Python 3.11、ローカル保存版

## 1. 目的と正本

本書は、ippi-downが実行中に開始できる外向き通信、ローカルプロセス、
保存先および監査方法を定める正本仕様です。READMEや他の設計書と内容が
異なる場合、通信許可範囲については本書を優先します。

通信先は利用者入力やWeb応答から自由に拡張しません。公式サイトの変更で
新しい通信先が必要になった場合は、コード、保存済みfixture、自動テスト、
本書を同じリリースで更新するまで既定拒否とします。

## 2. HTTP許可リスト

すべてのHTTP送信は共通の通信境界を通り、次の組み合わせだけを許可します。
ホスト名とpathは完全一致、schemeはHTTPS、portは443だけです。

| Endpoint ID | 用途 | Method | Host / path | 許可するquery |
|---|---|---|---|---|
| `IPPI_SEARCH` | 検索画面、検索送信 | GET / POST | `www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx` | `tab=4` |
| `IPPI_GYOMU_SEARCH` | 業務検索画面、検索送信 | GET / POST | `www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx` | `tab=7` |
| `IPPI_AGENCY_CATALOG` | 発注機関カタログ | GET | `www.i-ppi.jp/IPPI/SearchServices/Web/Multi/SearchHachu.aspx` | `type=koji&clear_flg=false` |
| `IPPI_GYOMU_AGENCY_CATALOG` | 業務の発注機関カタログ | GET | `www.i-ppi.jp/IPPI/SearchServices/Web/Multi/SearchHachu.aspx` | `type=gyomu&clear_flg=false` |
| `IPPI_PROJECT_DETAIL` | 検索結果のページ送り、工事詳細 | GET / POST | `www.i-ppi.jp/IPPI/SearchServices/Web/Koji/Keika/List.aspx` | `tab=4` |
| `IPPI_GYOMU_PROJECT_DETAIL` | 検索結果のページ送り、業務詳細 | GET / POST | `www.i-ppi.jp/IPPI/SearchServices/Web/Gyomu/Keika/List.aspx` | `tab=7` |
| `IPPI_DOCUMENT_LIST` | 工事の公開文書一覧 | GET | `www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx` | `data1`、`data2`（数字のみ） |
| `EBISC_DOCUMENT` | 公開文書取得 | GET | `e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet` | `AnkenKanriNo`、`BunshoKanriId`（数字のみ） |
| `IPPI_TERMINAL_ERROR` | 公式エラー画面 | GET | `www.i-ppi.jp/information/error.htm` | なし。許可済み通信の同一originリダイレクト終端だけ |

URL内のuserinfo、fragment、制御文字、未知のquery、重複query、別port、
用途と一致しないendpointは送信前に拒否します。リダイレクトは最大5回、
元のorigin内だけとし、各hopを送信直前に再検証します。公式hostであっても
表にないpathへは接続しません。

## 3. 直接接続とTLS

- OS環境変数、`.netrc`、システム／利用者設定の暗黙proxyを利用しません。
- 呼出元が明示したproxy、client certificate、Authorization header、
  TLS検証無効化、URLと異なるHost headerも送信前に拒否します。
- TLSサーバー証明書の検証は常に有効です。独自CA bundleへ実行時に
  切り替える機能は提供しません。
- 通信間隔、タイムアウト、最大3回の再試行、`Retry-After`の扱いは従来仕様を
  維持します。通信ポリシー違反は決定的エラーであり再試行しません。

この直接接続方針により、組織で外部接続に認証proxyが必須の場合は接続に
失敗します。その環境でproxyを許可する変更は、通信先の検証方法と監査範囲を
別途設計したうえで行います。

## 4. 起動・検索・定期実行時の通信

- GUI起動時は、公式の発注機関カタログと検索候補を準備するため、許可リスト
  内のGETをバックグラウンドで行うことがあります。広告、解析、更新確認、
  telemetryは送信しません。
- ダウンロード開始後は、検索POST、同一サイト内のページ送り・詳細・文書一覧、
  選択対象文書のGETだけを行います。
- 定期実行は登録時の不変スナップショットを使用し、GUIを閉じた後も同じ
  許可リストを適用します。スナップショットに非公式URLがあれば実行しません。
- HTML形式の入札調書は一度だけ共通HTTP境界で取得します。内蔵PDF生成器は
  ネットワーク機能を持たず、無害化済みHTMLから帳票モデルだけを生成します。
  Edgeフォールバックには安全化したローカルHTMLを`file://`で渡し、QUIC、
  proxy、名前解決を無効化して再通信を抑止します。

## 5. ローカルプロセスとファイル

- HTMLからPDFへの通常変換は同梱フォント、ReportLab、pypdfを隔離プロセスで
  使用します。失敗時だけ、MicrosoftのAuthenticode署名をオフライン検証できた
  `msedge.exe`をWindows Job Objectへ登録して非表示で起動します。署名検証の
  ための証明書取得通信は行いません。
- Windowsタスク操作は`GetSystemDirectoryW`から解決したSystem32配下の
  `schtasks.exe`とWindows PowerShellを絶対パスで起動します。PATH上の同名
  プログラムは本番で使用しません。
- 設定、ログ、通常／定期実行の保存先はローカルの固定またはリムーバブル
  ドライブだけです。UNC、Windowsデバイスpath、割当済みネットワークドライブは
  設定保存時と実行前に拒否します。
- Box、メール、クラウドストレージ、任意コマンド、任意URLを使う機能は
  現行版にありません。

## 6. ログと機密情報

- `logs/app.log`は共通formatterでURLのquery値、URL userinfo、Cookie、
  Authorization、Bearer tokenをマスクします。例外tracebackにも同じ処理を
  適用します。
- `logs/network-audit.jsonl`には許可／拒否、時刻、PID、用途、Method、
  Endpoint ID、host、path、query名、redirect有無、HTTP状態だけを記録します。
  query値、HTTP本文、Cookie、全header、検索条件、保存文書は記録しません。
- 通信監査ログは5 MiB、5世代を既定上限とします。監査ログの書込障害は
  `app.log`へ警告しますが、許可判定や正常なダウンロード結果を変更しません。
- PDF変換のプロセス数・heartbeat・終了コード・理由コードは、query値やCookieを
  含めず`logs/pdf-conversions-*.jsonl`へ90日保持します。全方式失敗時の無害化済み
  HTML等は`logs/pdf-failures/<conversion_id>/`へ30日保持し、自動送信しません。
- 設定、通常ログ、監査ログ、取得文書には業務情報が含まれる可能性があります。
  公開リポジトリや配布物へ含めません。

## 7. 検証方法

標準pytestはDNS解決とsocket接続をfail-closedで遮断します。HTTP正常系、
リダイレクト、再試行、拒否は保存済みfixtureと記録transportで検証します。
また、実行コードが共通HTTP境界以外の通信ライブラリをimportしていないことを
AST検査します。

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

実サイトの疎通試験は標準テストから分離し、明示した場合だけ許可リスト内の
読み取りGETを実行します。ダウンロードや検索POSTは行いません。

```powershell
$env:RUN_NETWORK_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_live_network_policy.py -v -m network
```

OSレベルのpacket capture、EDR、Windows Filtering Platformでの観測は、Python
外部で行われるOS／Edge動作を含めた実機受入試験です。自動テストはアプリが
意図しない送信を開始しないことを保証しますが、侵害済みOSやセキュリティ製品、
DNS／TLS基盤そのものの動作までは保証しません。

## 8. 主な拒否理由

通信境界は`OUTBOUND_POLICY_BLOCKED`、リダイレクトは
`REDIRECT_POLICY_BLOCKED`として処理し、詳細を固定理由コードで残します。
例は`HOST_NOT_ALLOWED`、`ENDPOINT_NOT_ALLOWED`、`QUERY_NOT_ALLOWED`、
`PURPOSE_MISMATCH`、`PROXY_NOT_ALLOWED`、`TLS_VERIFY_REQUIRED`、
`AUTH_NOT_ALLOWED`、`HOST_HEADER_MISMATCH`です。拒否時はHTTP送信を開始せず、
既存の正常ファイルを変更しません。
