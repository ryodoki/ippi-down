"""改善されたヘッダーでダウンロードをテストするスクリプト

ブラウザと同じヘッダーを使用してダウンロードを試行します。
"""

import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from src.core.downloader import Downloader  # type: ignore
from src.core.naming import Naming  # type: ignore
import requests
from urllib.parse import urlparse as url_parse


def test_download_with_improved_headers():
    """改善されたヘッダーでダウンロードをテスト"""
    print("=" * 80)
    print("改善されたヘッダーでのダウンロードテスト")
    print("=" * 80)
    print("\nこのテストは以下を確認します：")
    print("  1. ブラウザと同じヘッダー（Origin、Sec-Fetch-*等）を使用")
    print("  2. リダイレクトの追従")
    print("  3. 詳細なログ出力")
    print()
    
    logger = Logger(LoggingConfig(level="DEBUG"))  # DEBUGレベルで詳細ログ
    http_client = HTTPClient(logger, timeout=30, download_timeout=300)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    save_path = Path("./downloads/test_improved_headers")
    save_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # ステップ1: 検索を実行してファイルを取得
        print("\n[ステップ1] 検索を実行してファイルを取得")
        print("-" * 80)
        
        search_conditions = SearchConditions(hachu_daibunrui="国の機関")
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        
        if not result_soup:
            print("[ERROR] 検索に失敗しました")
            return False
        
        files = scraper.extract_file_links_from_search_results(
            result_soup, search_url, [".pdf"]
        )
        
        if not files or len(files) == 0:
            print("[ERROR] ファイルが見つかりませんでした")
            return False
        
        test_file = files[0]
        print(f"[INFO] テストファイル: {test_file.filename}")
        print(f"  URL: {test_file.url}")
        print(f"  Page URL: {test_file.page_url}")
        
        # ステップ2: リクエスト情報を詳細に記録
        print("\n[ステップ2] リクエスト情報の詳細")
        print("-" * 80)
        
        parsed_url = url_parse(test_file.url)
        print(f"  ダウンロードURLの詳細:")
        print(f"    スキーム: {parsed_url.scheme}")
        print(f"    ホスト: {parsed_url.netloc}")
        print(f"    パス: {parsed_url.path}")
        print(f"    クエリ: {parsed_url.query}")
        
        print(f"\n  セッション情報:")
        print(f"    Cookies数: {len(http_client.session.cookies)}")
        for cookie in http_client.session.cookies:
            print(f"      - {cookie.name}: {cookie.domain} ({cookie.path})")
        
        # ステップ3: 実際のダウンロードを試行
        print(f"\n[ステップ3] 実際のダウンロードを試行")
        print("-" * 80)
        
        # まず、HEADリクエストで接続をテスト
        print(f"  [試行1] HEADリクエストで接続テスト")
        try:
            referer = test_file.page_url
            parsed_referer = url_parse(referer)
            origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
            
            test_headers = {
                "Accept": "application/pdf,application/octet-stream,*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Referer": referer,
                "Origin": origin,
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-User": "?1",
            }
            
            print(f"    送信するヘッダー:")
            for key, value in test_headers.items():
                print(f"      {key}: {value}")
            
            head_response = http_client.session.head(
                test_file.url,
                headers=test_headers,
                timeout=(10, 30),
                allow_redirects=True
            )
            
            print(f"\n    [SUCCESS] HEADリクエスト成功")
            print(f"      Status Code: {head_response.status_code}")
            print(f"      Final URL: {head_response.url}")
            print(f"      Redirects: {len(head_response.history)}")
            
            if head_response.history:
                print(f"      リダイレクトチェーン:")
                for i, resp in enumerate(head_response.history, 1):
                    print(f"        {i}. {resp.status_code} -> {resp.url[:80]}...")
            
            print(f"      Response Headers:")
            for key, value in head_response.headers.items():
                if key.lower() in ['content-type', 'content-length', 'location', 'server', 'date']:
                    print(f"        {key}: {value}")
                    
        except requests.exceptions.Timeout as e:
            print(f"    [ERROR] HEADリクエストタイムアウト: {type(e).__name__}")
            print(f"      詳細: {str(e)}")
            print(f"    → GETリクエスト（stream=True）で試行します")
        except Exception as e:
            print(f"    [ERROR] HEADリクエストエラー: {type(e).__name__}: {str(e)}")
            print(f"    → GETリクエスト（stream=True）で試行します")
        
        # ダウンロードを実行
        print(f"\n  [試行2] 実際のダウンロードを実行")
        
        naming = Naming("{filename}", logger)
        downloader = Downloader(http_client, logger)
        
        def progress_callback(current, total, filename):
            if total > 0:
                percent = (current / total) * 100
                print(f"    進捗: {percent:.1f}% ({current:,}/{total:,} bytes)", end="\r")
            else:
                print(f"    進捗: {current:,} bytes (サイズ不明)", end="\r")
        
        result = downloader.download_files(
            [test_file],
            str(save_path),
            naming,
            progress_callback
        )
        
        print()  # 改行
        
        # 結果を表示
        print("\n" + "=" * 80)
        print("ダウンロード結果")
        print("=" * 80)
        print(f"総数: {result.total}")
        print(f"成功: {result.success}")
        print(f"失敗: {result.failed}")
        print(f"スキップ: {result.skipped}")
        
        if result.success > 0:
            print("\n[SUCCESS] ダウンロードに成功しました！")
            for task in result.tasks:
                if task.status == "completed":
                    file_path = Path(task.local_path)
                    if file_path.exists():
                        size = file_path.stat().st_size
                        print(f"  ファイル: {file_path}")
                        print(f"  サイズ: {size:,} bytes ({size / 1024:.2f} KB)")
                        
                        # ファイルの最初の数バイトを確認（PDFのマジックナンバー）
                        with open(file_path, "rb") as f:
                            first_bytes = f.read(4)
                            if first_bytes == b'%PDF':
                                print(f"  [確認] PDFファイルとして認識されました")
                            else:
                                print(f"  [警告] PDFのマジックナンバーが見つかりませんでした")
                                print(f"    最初の4バイト: {first_bytes}")
            return True
        else:
            print("\n[ERROR] ダウンロードに失敗しました")
            for task in result.tasks:
                if task.status == "failed":
                    print(f"  - {task.file_info.filename}")
                    print(f"    URL: {task.file_info.url}")
                    print(f"    エラー: {task.error_message}")
            
            # 詳細な分析結果を保存
            save_analysis_result(test_file, http_client, logger)
            return False
            
    except KeyboardInterrupt:
        print("\n\n[INFO] ユーザーによって中断されました")
        return False
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()


def save_analysis_result(file_info, http_client, logger):
    """分析結果を保存"""
    import json
    
    analysis = {
        "timestamp": datetime.now().isoformat(),
        "file_info": {
            "filename": file_info.filename,
            "url": file_info.url,
            "page_url": file_info.page_url,
            "metadata": file_info.metadata
        },
        "session_info": {
            "cookies": [
                {
                    "name": cookie.name,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "secure": cookie.secure
                }
                for cookie in http_client.session.cookies
            ]
        },
        "recommendation": "ブラウザの開発者ツールで実際のリクエストを確認してください"
    }
    
    output_file = Path("./docs/dev/improved_headers_test_analysis.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    
    logger.info(f"分析結果を保存: {output_file}")


if __name__ == "__main__":
    success = test_download_with_improved_headers()
    sys.exit(0 if success else 1)
