"""ブラウザでの実際のダウンロードリクエストをキャプチャする手順書

このスクリプトは、ブラウザの開発者ツールで取得したリクエスト情報を
JSON形式で保存するためのテンプレートを提供します。
"""

import json
from pathlib import Path
from datetime import datetime

# このファイルを実行すると、ブラウザで取得した情報を入力するテンプレートが表示されます

def create_browser_request_template():
    """ブラウザリクエスト情報のテンプレートを作成"""
    template = {
        "timestamp": datetime.now().isoformat(),
        "investigator": "ブラウザの開発者ツールを使用",
        "steps": [
            "1. ブラウザで https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4 にアクセス",
            "2. 検索条件を設定（発注機関 = '国の機関'）",
            "3. 「検索開始」をクリック",
            "4. 検索結果から1件をクリックして詳細ページを開く",
            "5. 詳細ページで「公告文書」または「経過文書」タブのファイルをクリック",
            "6. 開発者ツール（F12）→ ネットワークタブを開く",
            "7. PDFファイルのリクエストを探す",
            "8. リクエストを右クリック → 「Copy」→ 「Copy as cURL」または「Copy request headers」",
        ],
        "request_info": {
            "url": "最終的なダウンロードURL（リダイレクト後）をここに貼り付け",
            "method": "GET",
            "request_headers": {
                "User-Agent": "ブラウザのUser-Agentをここに貼り付け",
                "Accept": "ブラウザのAcceptヘッダーをここに貼り付け",
                "Accept-Language": "ブラウザのAccept-Languageヘッダーをここに貼り付け",
                "Accept-Encoding": "ブラウザのAccept-Encodingヘッダーをここに貼り付け",
                "Referer": "ブラウザのRefererヘッダーをここに貼り付け（重要）",
                "Cookie": "ブラウザのCookieヘッダーをここに貼り付け（すべて）",
                "Origin": "ブラウザのOriginヘッダーをここに貼り付け（もしあれば）",
                "Sec-Fetch-Site": "ブラウザのSec-Fetch-Siteヘッダーをここに貼り付け（もしあれば）",
                "Sec-Fetch-Mode": "ブラウザのSec-Fetch-Modeヘッダーをここに貼り付け（もしあれば）",
                "Sec-Fetch-Dest": "ブラウザのSec-Fetch-Destヘッダーをここに貼り付け（もしあれば）",
                "その他のヘッダー": "その他の重要なヘッダーがあれば追加"
            },
            "query_parameters": {
                "AnkenKanriNo": "クエリパラメータの値をここに貼り付け",
                "BunshoKanriId": "クエリパラメータの値をここに貼り付け",
                "その他のパラメータ": "その他のパラメータがあれば追加"
            },
            "cookies": [
                {
                    "name": "Cookie名",
                    "value": "Cookie値",
                    "domain": "Cookieのドメイン",
                    "path": "Cookieのパス",
                    "secure": True or False,
                    "httpOnly": True or False
                }
            ],
            "redirects": [
                "最初のURL（リダイレクト前）",
                "中間URL（もしあれば）",
                "最終URL（リダイレクト後）"
            ],
            "response_headers": {
                "Content-Type": "レスポンスのContent-Typeをここに貼り付け",
                "Content-Length": "レスポンスのContent-Lengthをここに貼り付け",
                "Location": "レスポンスのLocationヘッダーをここに貼り付け（リダイレクトの場合）",
                "その他のヘッダー": "その他の重要なヘッダーがあれば追加"
            }
        },
        "findings": {
            "download_url_source": "ダウンロードURLの生成元（HTMLのリンク、JavaScript、リダイレクト等）",
            "session_management": "セッション管理の方法（Cookie、URLパラメータ、ヘッダー等）",
            "required_headers": ["必須のヘッダーリスト"],
            "required_cookies": ["必須のCookieリスト"],
            "redirect_flow": "リダイレクトの流れ（詳細）"
        },
        "code_comparison": {
            "differences": [
                "コードとの差異1",
                "コードとの差異2"
            ],
            "missing_elements": [
                "不足している要素1",
                "不足している要素2"
            ]
        }
    }
    
    output_file = Path(__file__).parent.parent.parent / "docs" / "dev" / "browser_request_template.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    
    print("=" * 80)
    print("ブラウザリクエスト情報テンプレートを作成しました")
    print("=" * 80)
    print(f"\nファイル: {output_file}")
    print("\n以下の手順で情報を記入してください：")
    print("  1. ブラウザで実際にファイルをダウンロード")
    print("  2. 開発者ツール（F12）でネットワークタブを開く")
    print("  3. PDFファイルのリクエストを探す")
    print("  4. リクエストを右クリック → 「Copy」→ 必要な情報をコピー")
    print("  5. テンプレートファイルに情報を記入")
    print("  6. compare_browser_request.py で比較")
    print()
    print("重要な確認項目：")
    print("  - リクエストURL（最終的なURL、リダイレクト後）")
    print("  - Refererヘッダー（どのページからアクセスしているか）")
    print("  - Cookie（すべてのCookie、特にセッションID）")
    print("  - リダイレクトの流れ（もしあれば）")
    print("  - Origin、Sec-Fetch-*ヘッダー（もしあれば）")


if __name__ == "__main__":
    create_browser_request_template()
