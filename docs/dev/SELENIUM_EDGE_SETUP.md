# Selenium + Edge設定ガイド

## Seleniumのインストール

Seleniumは既にインストールされていますが、必要に応じて以下のコマンドでインストールできます：

```bash
pip install selenium>=4.15.0
```

または、requirements.txtから：

```bash
pip install -r requirements.txt
```

## Edge WebDriverの設定

### Windowsの場合

Edgeブラウザがインストールされていれば、Selenium 4.6以降では自動的にEdgeDriverを管理します。

**手動でEdgeDriverを設定する場合**:

1. Edgeブラウザのバージョンを確認
   - Edgeを開く → `edge://settings/help` でバージョンを確認

2. EdgeDriverをダウンロード
   - https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/
   - Edgeのバージョンに合ったWebDriverをダウンロード

3. EdgeDriverを配置
   - `PATH`に追加するか
   - プロジェクトの`scripts/dev/`フォルダに配置

### 自動インストール（推奨）

Selenium 4.6以降では、`webdriver-manager`を使用して自動的にWebDriverを管理できます：

```bash
pip install webdriver-manager
```

その後、コードで使用：

```python
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager

service = Service(EdgeChromiumDriverManager().install())
driver = webdriver.Edge(service=service)
```

## スクリプトの使用方法

### 自動記録スクリプト

```bash
python scripts/dev/capture_browser_network_requests.py
```

このスクリプトは：
1. Edgeブラウザを優先して起動（Chromeはフォールバック）
2. 検索ページにアクセス
3. 検索を実行
4. 詳細ページを開く
5. ファイルダウンロードリンクをクリック
6. ネットワークリクエストを記録

### 手動操作モード

スクリプトが自動操作に失敗した場合、手動で操作できます：
- 各ステップでEnterキーを押すと、手動操作モードになります
- ブラウザを開いたまま、手動で操作してください

## トラブルシューティング

### EdgeDriverが見つからない

**エラー**: `selenium.common.exceptions.WebDriverException: Message: 'MicrosoftWebDriver.exe' executable needs to be in PATH`

**解決方法**:
1. Edgeブラウザがインストールされているか確認
2. Selenium 4.6以降を使用（自動でEdgeDriverを管理）
3. 手動でEdgeDriverをインストールする場合は、上記の手順を参照

### ブラウザが起動しない

**エラー**: `selenium.common.exceptions.SessionNotCreatedException`

**解決方法**:
1. EdgeブラウザのバージョンとEdgeDriverのバージョンが一致しているか確認
2. Edgeブラウザが最新版か確認
3. Seleniumを最新版に更新: `pip install --upgrade selenium`

### ログが取得できない

**エラー**: パフォーマンスログを取得できない

**解決方法**:
- Edgeの場合、ログの取得方法がChromeと異なる可能性があります
- ブラウザの開発者ツール（F12）から手動で情報を取得してください
- 詳細手順: `docs/dev/BROWSER_MANUAL_INVESTIGATION.md`

## Edgeを優先する理由

- Windows標準のブラウザで、多くの環境で利用可能
- Chromeと同様の機能を持ちながら、Microsoftのサポートがある
- 開発・テスト環境でEdgeを使用することで、実際のユーザー環境に近い動作を確認できる

## 関連ドキュメント

- 手動調査手順書: `docs/dev/BROWSER_MANUAL_INVESTIGATION.md`
- クイックスタート: `docs/dev/QUICK_START_BROWSER_INVESTIGATION.md`
- 調査結果分析: `scripts/dev/analyze_captured_request.py`
