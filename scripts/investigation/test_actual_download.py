"""実際のダウンロードを試行するスクリプト

接続タイムアウトの問題を解決するため、より詳細な情報を取得します。
"""

import sys
from pathlib import Path
import json

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions, DownloadConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from src.core.filter import Filter  # type: ignore
from src.core.downloader import Downloader  # type: ignore
from src.core.naming import Naming  # type: ignore
import requests
from urllib.parse import urlparse


def test_actual_download():
    """実際のダウンロードを試行"""
    print("=" * 80)
    print("実際のダウンロードテスト")
    print("=" * 80)
    
    logger = Logger(LoggingConfig(level="INFO"))
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    save_path = Path("./downloads/test_actual")
    save_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # ステップ1: 検索を実行してファイルを取得
        print("\n[ステップ1] 検索を実行してファイルを取得")
        print("-" * 80)
        
        search_conditions = SearchConditions(
            hachu_daibunrui="国の機関"
        )
        
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        if not result_soup:
            print("検索に失敗しました")
            return False
        
        files = scraper.extract_file_links_from_search_results(
            result_soup, search_url, [".pdf"]
        )
        
        if not files:
            print("ファイルが見つかりませんでした")
            return False
        
        print(f"発見されたファイル数: {len(files)}")
        
        # ステップ2: 最初のファイルで詳細な接続テスト
        test_file = files[0]
        print(f"\n[ステップ2] 接続テスト: {test_file.filename}")
        print("-" * 80)
        print(f"URL: {test_file.url}")
        print(f"Page URL: {test_file.page_url}")
        
        # URLを解析
        parsed_url = urlparse(test_file.url)
        print(f"\nURL解析:")
        print(f"  Scheme: {parsed_url.scheme}")
        print(f"  Netloc: {parsed_url.netloc}")
        print(f"  Path: {parsed_url.path}")
        print(f"  Query: {parsed_url.query}")
        
        # セッション情報を確認
        print(f"\nセッション情報:")
        print(f"  Cookies数: {len(http_client.session.cookies)}")
        for cookie in http_client.session.cookies:
            print(f"    {cookie.name}: {cookie.domain} ({cookie.path})")
        
        # ステップ3: 接続テスト（GET(stream=True)で）
        print(f"\n[ステップ3] 接続テスト（GET + stream=True, 接続10秒/読み取り60秒タイムアウト）")
        print("-" * 80)
        
        try:
            # GETリクエスト（stream=True）で接続をテスト
            # HEADはサーバーによって雑に扱われることがあるため、GETを使用
            test_headers = {
                "Referer": test_file.page_url if test_file.page_url else search_url,
                "Accept": "application/pdf,application/octet-stream,*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            }
            
            print(f"送信するヘッダー:")
            for key, value in test_headers.items():
                print(f"  {key}: {value}")
            
            # GET(stream=True)で接続をテスト
            # 接続タイムアウト: 10秒、読み取りタイムアウト: 60秒
            response = http_client.session.get(
                test_file.url,
                headers=test_headers,
                stream=True,
                timeout=(10, 60),  # 接続10秒、読み取り60秒
                allow_redirects=True
            )
            
            print(f"\n接続成功!")
            print(f"  Status Code: {response.status_code}")
            print(f"  Headers:")
            for key, value in response.headers.items():
                if key.lower() in ['content-type', 'content-length', 'location', 'server']:
                    print(f"    {key}: {value}")
            
            # リダイレクトの確認
            if response.history:
                print(f"  リダイレクト数: {len(response.history)}")
                for i, hist in enumerate(response.history, 1):
                    print(f"    {i}. {hist.status_code} -> {hist.url[:80]}...")
            
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                print(f"\n[SUCCESS] 接続に成功しました！")
                print(f"  Content-Type: {content_type}")
                if 'pdf' in content_type.lower() or 'application/octet-stream' in content_type.lower():
                    print("  ダウンロード可能です")
                    # 実際のダウンロードを試行
                    return try_download(test_file, save_path, http_client, logger)
                else:
                    print(f"  [WARN] 期待されるContent-Typeではありません: {content_type}")
                    # それでもダウンロードを試行（ファイルの内容で判定）
                    return try_download(test_file, save_path, http_client, logger)
            elif response.status_code in [301, 302, 303, 307, 308]:
                location = response.headers.get('Location', '')
                print(f"\n[INFO] リダイレクト検出: Status {response.status_code}")
                print(f"  Location: {location[:100]}...")
                # リダイレクト先にアクセス可能か確認
                if location:
                    print("  リダイレクト先へのアクセスを試行...")
                    return try_download(test_file, save_path, http_client, logger)
                else:
                    return False
            else:
                print(f"\n[WARN] Status Code: {response.status_code}")
                # それでもダウンロードを試行（サーバーによっては正常な応答を返すこともある）
                print("  ダウンロードを試行します...")
                return try_download(test_file, save_path, http_client, logger)
                
        except requests.exceptions.Timeout as e:
            print(f"\n[ERROR] タイムアウト: {str(e)}")
            error_str = str(e).lower()
            if "connect" in error_str:
                print("接続タイムアウトが発生しました（サーバーへの接続が確立できません）。")
            else:
                print("読み取りタイムアウトが発生しました（サーバーからの応答が遅いです）。")
            print("\n考えられる原因:")
            print("  1. サーバーが応答していない、または過負荷")
            print("  2. ネットワーク環境の問題（ファイアウォール、プロキシ、回線速度など）")
            print("  3. 別ドメイン（e-bisc.go.jp）へのアクセスがブロックまたは遅延している")
            print("  4. セッションCookieが別ドメインに送信されていない")
            print("  5. 必要な認証情報やトークンが不足している")
            print("\n[INFO] ネットワーク問題の可能性が高いです。")
            print("  PowerShellで以下を実行して接続を確認してください:")
            print(f'  $u="{test_file.url}"; Invoke-WebRequest -Uri $u -Method Get -TimeoutSec 120 -MaximumRedirection 5')
            # それでも実際のダウンロードを試行（HTTPClientのリトライ機能に任せる）
            print("\n[INFO] HTTPClientのリトライ機能を使ってダウンロードを試行します...")
            return try_download(test_file, save_path, http_client, logger)
        except requests.exceptions.ConnectionError as e:
            print(f"\n[ERROR] 接続エラー: {str(e)}")
            print("接続エラーが発生しました。")
            return False
        except Exception as e:
            print(f"\n[ERROR] 予期しないエラー: {type(e).__name__}: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()


def try_download(file_info, save_path, http_client, logger):
    """実際のダウンロードを試行"""
    print(f"\n[ステップ4] 実際のダウンロードを試行")
    print("-" * 80)
    
    filename = file_info.filename
    if not filename.endswith('.pdf'):
        filename += '.pdf'
    
    save_file = save_path / filename
    
    print(f"保存先: {save_file}")
    print(f"URL: {file_info.url}")
    
    # ダウンロードを実行
    referer = file_info.page_url if file_info.page_url else None
    
    def progress_callback(downloaded, total):
        if total > 0:
            percent = (downloaded / total) * 100
            print(f"  進捗: {percent:.1f}% ({downloaded:,}/{total:,} bytes)")
        else:
            print(f"  進捗: {downloaded:,} bytes (サイズ不明)")
    
    success = http_client.download_file(
        file_info.url,
        str(save_file),
        progress_callback,
        referer=referer
    )
    
    if success:
        if save_file.exists():
            size = save_file.stat().st_size
            print(f"\n[SUCCESS] ダウンロード成功!")
            print(f"  ファイル: {save_file}")
            print(f"  サイズ: {size:,} bytes ({size / 1024:.2f} KB)")
            return True
        else:
            print(f"\n[ERROR] ダウンロードは成功したが、ファイルが見つかりません")
            return False
    else:
        print(f"\n[ERROR] ダウンロードに失敗しました")
        return False


if __name__ == "__main__":
    success = test_actual_download()
    sys.exit(0 if success else 1)

