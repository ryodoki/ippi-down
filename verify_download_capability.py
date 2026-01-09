"""実際のダウンロードをするための確認手法を実行するスクリプト

様々な方法でダウンロード可能性を確認します。
"""

import sys
from pathlib import Path
import json
import time

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup


def verify_download_capability():
    """ダウンロード可能性を様々な方法で確認"""
    print("=" * 80)
    print("ダウンロード可能性の確認")
    print("=" * 80)
    
    logger = Logger(LoggingConfig(level="INFO"))
    results = {}
    
    # ステップ1: 検索を実行してファイルURLを取得
    print("\n[ステップ1] 検索を実行してファイルURLを取得")
    print("-" * 80)
    
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    search_conditions = SearchConditions(hachu_daibunrui="国の機関")
    
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
    
    test_file = files[0]
    print(f"テストファイル: {test_file.filename}")
    print(f"URL: {test_file.url}")
    print(f"Page URL: {test_file.page_url}")
    
    results["file_url"] = test_file.url
    results["page_url"] = test_file.page_url
    results["filename"] = test_file.filename
    
    # ステップ2: URL解析
    print("\n[ステップ2] URL解析")
    print("-" * 80)
    
    parsed_url = urlparse(test_file.url)
    print(f"Scheme: {parsed_url.scheme}")
    print(f"Netloc: {parsed_url.netloc}")
    print(f"Path: {parsed_url.path}")
    print(f"Query: {parsed_url.query}")
    
    results["url_parsed"] = {
        "scheme": parsed_url.scheme,
        "netloc": parsed_url.netloc,
        "path": parsed_url.path,
        "query": parsed_url.query
    }
    
    # ステップ3: セッション情報の確認
    print("\n[ステップ3] セッション情報の確認")
    print("-" * 80)
    
    cookies = []
    for cookie in http_client.session.cookies:
        cookie_info = {
            "name": cookie.name,
            "value": cookie.value[:50] + "..." if len(cookie.value) > 50 else cookie.value,
            "domain": cookie.domain,
            "path": cookie.path
        }
        cookies.append(cookie_info)
        print(f"  {cookie.name}: {cookie.domain} ({cookie.path})")
    
    results["cookies"] = cookies
    
    # ステップ4: 様々な方法で接続テスト
    print("\n[ステップ4] 接続テスト（様々な方法）")
    print("-" * 80)
    
    test_methods = []
    
    # 方法1: HEADリクエスト（短いタイムアウト）
    print("\n[方法1] HEADリクエスト（5秒タイムアウト）")
    result1 = test_head_request(http_client, test_file, timeout=5)
    test_methods.append({"method": "HEAD (5s)", "result": result1})
    
    # 方法2: HEADリクエスト（長いタイムアウト）
    print("\n[方法2] HEADリクエスト（30秒タイムアウト）")
    result2 = test_head_request(http_client, test_file, timeout=30)
    test_methods.append({"method": "HEAD (30s)", "result": result2})
    
    # 方法3: GETリクエスト（短いタイムアウト、ストリーミングなし）
    print("\n[方法3] GETリクエスト（5秒タイムアウト、ストリーミングなし）")
    result3 = test_get_request(http_client, test_file, timeout=5, stream=False)
    test_methods.append({"method": "GET (5s, no stream)", "result": result3})
    
    # 方法4: GETリクエスト（長いタイムアウト、ストリーミングあり）
    print("\n[方法4] GETリクエスト（30秒タイムアウト、ストリーミングあり）")
    result4 = test_get_request(http_client, test_file, timeout=30, stream=True)
    test_methods.append({"method": "GET (30s, stream)", "result": result4})
    
    # 方法5: 異なるヘッダーでのテスト
    print("\n[方法5] 異なるヘッダーでのテスト")
    result5 = test_with_different_headers(http_client, test_file)
    test_methods.append({"method": "Different headers", "result": result5})
    
    # 方法6: リダイレクトの確認
    print("\n[方法6] リダイレクトの確認")
    result6 = test_redirects(http_client, test_file)
    test_methods.append({"method": "Redirects", "result": result6})
    
    results["test_methods"] = test_methods
    
    # ステップ5: 結果のサマリー
    print("\n[ステップ5] 結果のサマリー")
    print("-" * 80)
    
    success_count = sum(1 for m in test_methods if m["result"].get("success", False))
    total_count = len(test_methods)
    
    print(f"成功: {success_count}/{total_count}")
    
    for method in test_methods:
        status = "✓" if method["result"].get("success", False) else "✗"
        print(f"  {status} {method['method']}: {method['result'].get('message', 'N/A')}")
    
    # ステップ6: 結果をJSONファイルに保存
    output_file = Path("verify_download_results.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n結果を保存: {output_file}")
    
    # ステップ7: 推奨事項
    print("\n[ステップ7] 推奨事項")
    print("-" * 80)
    
    if success_count == 0:
        print("すべての接続テストが失敗しました。")
        print("\n推奨される対応:")
        print("  1. ブラウザで直接URLにアクセスしてダウンロード可能か確認")
        print("  2. プロキシ設定が必要か確認")
        print("  3. ファイアウォールの設定を確認")
        print("  4. ネットワーク環境の問題を確認")
    elif success_count < total_count:
        print("一部の接続テストが成功しました。")
        print("成功した方法を使用してダウンロードを試行してください。")
    else:
        print("すべての接続テストが成功しました！")
        print("ダウンロードを実行できます。")
    
    http_client.close()
    return success_count > 0


def test_head_request(http_client, file_info, timeout=5):
    """HEADリクエストで接続をテスト"""
    try:
        headers = {
            "Referer": file_info.page_url if file_info.page_url else "",
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        }
        
        response = http_client.session.head(
            file_info.url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True
        )
        
        return {
            "success": True,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "message": f"Status {response.status_code}"
        }
    except requests.exceptions.Timeout as e:
        return {
            "success": False,
            "error": "Timeout",
            "message": f"タイムアウト ({timeout}秒)"
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "error": "ConnectionError",
            "message": f"接続エラー: {str(e)[:100]}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": type(e).__name__,
            "message": f"エラー: {str(e)[:100]}"
        }


def test_get_request(http_client, file_info, timeout=5, stream=False):
    """GETリクエストで接続をテスト"""
    try:
        headers = {
            "Referer": file_info.page_url if file_info.page_url else "",
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        }
        
        response = http_client.session.get(
            file_info.url,
            headers=headers,
            timeout=timeout,
            stream=stream,
            allow_redirects=True
        )
        
        content_length = response.headers.get("content-length", "不明")
        content_type = response.headers.get("content-type", "不明")
        
        # ストリーミングの場合は最初のチャンクを読み取る
        if stream:
            try:
                first_chunk = next(response.iter_content(chunk_size=1024))
                chunk_size = len(first_chunk)
                response.close()
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "content_length": content_length,
                    "content_type": content_type,
                    "first_chunk_size": chunk_size,
                    "message": f"Status {response.status_code}, Content-Length: {content_length}, First chunk: {chunk_size} bytes"
                }
            except StopIteration:
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "content_length": content_length,
                    "content_type": content_type,
                    "message": f"Status {response.status_code}, Content-Length: {content_length} (empty stream)"
                }
        else:
            content_size = len(response.content)
            return {
                "success": True,
                "status_code": response.status_code,
                "content_length": content_length,
                "content_type": content_type,
                "content_size": content_size,
                "message": f"Status {response.status_code}, Content-Length: {content_length}, Downloaded: {content_size} bytes"
            }
    except requests.exceptions.Timeout as e:
        return {
            "success": False,
            "error": "Timeout",
            "message": f"タイムアウト ({timeout}秒)"
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "error": "ConnectionError",
            "message": f"接続エラー: {str(e)[:100]}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": type(e).__name__,
            "message": f"エラー: {str(e)[:100]}"
        }


def test_with_different_headers(http_client, file_info):
    """異なるヘッダーでのテスト"""
    test_headers = [
        {
            "name": "Minimal headers",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        },
        {
            "name": "With Referer",
            "headers": {
                "Referer": file_info.page_url if file_info.page_url else "",
                "Accept": "application/pdf,*/*"
            }
        },
        {
            "name": "Full browser headers",
            "headers": {
                "Referer": file_info.page_url if file_info.page_url else "",
                "Accept": "application/pdf,application/octet-stream,*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        }
    ]
    
    results = []
    for test_header in test_headers:
        try:
            response = http_client.session.head(
                file_info.url,
                headers=test_header["headers"],
                timeout=10,
                allow_redirects=True
            )
            results.append({
                "name": test_header["name"],
                "success": True,
                "status_code": response.status_code,
                "message": f"Status {response.status_code}"
            })
        except Exception as e:
            results.append({
                "name": test_header["name"],
                "success": False,
                "error": type(e).__name__,
                "message": f"エラー: {str(e)[:50]}"
            })
    
    success_count = sum(1 for r in results if r.get("success", False))
    return {
        "success": success_count > 0,
        "results": results,
        "message": f"{success_count}/{len(results)} 成功"
    }


def test_redirects(http_client, file_info):
    """リダイレクトの確認"""
    try:
        # allow_redirects=Falseでリダイレクトを追跡しない
        response = http_client.session.head(
            file_info.url,
            headers={
                "Referer": file_info.page_url if file_info.page_url else "",
            },
            timeout=10,
            allow_redirects=False
        )
        
        if response.status_code in [301, 302, 303, 307, 308]:
            location = response.headers.get("Location", "")
            return {
                "success": True,
                "status_code": response.status_code,
                "redirect": True,
                "location": location,
                "message": f"リダイレクト: {response.status_code} -> {location}"
            }
        else:
            return {
                "success": True,
                "status_code": response.status_code,
                "redirect": False,
                "message": f"リダイレクトなし: {response.status_code}"
            }
    except Exception as e:
        return {
            "success": False,
            "error": type(e).__name__,
            "message": f"エラー: {str(e)[:100]}"
        }


if __name__ == "__main__":
    success = verify_download_capability()
    sys.exit(0 if success else 1)
