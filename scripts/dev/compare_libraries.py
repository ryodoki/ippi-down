"""
ライブラリ比較スクリプト: Playwright、Selenium、requestsの適性を調査

対象ページに各ライブラリでアクセスし、以下の観点で比較：
- JavaScriptの実行が必要か
- 動的コンテンツの読み込みが必要か
- 認証/セッション管理の複雑さ
- パフォーマンス
- 実装の容易さ
- ファイルダウンロードの可否
"""

import time
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

# Windowsコンソールのエンコーディング問題を回避
if sys.platform == 'win32':
    try:
        # UTF-8で出力できるように設定
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        # 設定できない場合はASCII文字を使用
        pass

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from selenium import webdriver
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class LibraryTestResult:
    """ライブラリテスト結果"""
    library_name: str
    available: bool
    success: bool
    error_message: Optional[str] = None
    response_time: Optional[float] = None
    status_code: Optional[int] = None
    content_length: Optional[int] = None
    has_javascript: Optional[bool] = None
    dynamic_content: Optional[bool] = None
    cookies_count: Optional[int] = None
    headers_count: Optional[int] = None
    download_possible: Optional[bool] = None
    implementation_complexity: Optional[str] = None  # "low", "medium", "high"
    notes: Optional[str] = None


class LibraryComparator:
    """ライブラリ比較クラス"""
    
    def __init__(self, target_url: str, timeout: int = 30):
        self.target_url = target_url
        self.timeout = timeout
        self.results: List[LibraryTestResult] = []
    
    def test_requests(self) -> LibraryTestResult:
        """requestsライブラリでテスト"""
        result = LibraryTestResult(
            library_name="requests",
            available=REQUESTS_AVAILABLE,
            success=False
        )
        
        if not REQUESTS_AVAILABLE:
            result.error_message = "requestsライブラリがインストールされていません"
            return result
        
        try:
            start_time = time.time()
            
            # セッションを作成
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            # リクエスト送信
            response = session.get(self.target_url, timeout=self.timeout, allow_redirects=True)
            
            response_time = time.time() - start_time
            
            result.success = True
            result.response_time = response_time
            result.status_code = response.status_code
            result.content_length = len(response.content)
            result.cookies_count = len(session.cookies)
            result.headers_count = len(response.headers)
            
            # JavaScriptの実行は不可
            result.has_javascript = False
            
            # 動的コンテンツの判定（HTMLに特定のパターンがあるか）
            content = response.text.lower()
            result.dynamic_content = any([
                "__dopostback" in content,
                "javascript:" in content,
                "onclick=" in content,
                "document.write" in content,
                "settimeout" in content,
                "setinterval" in content
            ])
            
            # ダウンロード可能性の判定
            content_type = response.headers.get("Content-Type", "").lower()
            result.download_possible = any([
                "application/pdf" in content_type,
                "application/vnd.ms-excel" in content_type,
                "application/vnd.openxmlformats" in content_type,
                "application/octet-stream" in content_type,
                response.status_code == 200 and result.content_length > 0
            ])
            
            result.implementation_complexity = "low"
            result.notes = "シンプルなHTTPリクエスト。JavaScriptは実行不可。"
            
        except requests.exceptions.Timeout:
            result.error_message = f"タイムアウト（{self.timeout}秒）"
        except requests.exceptions.ConnectionError as e:
            result.error_message = f"接続エラー: {str(e)}"
        except Exception as e:
            result.error_message = f"エラー: {str(e)}"
        
        return result
    
    def test_selenium(self) -> LibraryTestResult:
        """Seleniumライブラリでテスト"""
        result = LibraryTestResult(
            library_name="selenium",
            available=SELENIUM_AVAILABLE,
            success=False
        )
        
        if not SELENIUM_AVAILABLE:
            result.error_message = "Seleniumライブラリがインストールされていません"
            return result
        
        driver = None
        try:
            start_time = time.time()
            
            # Edgeブラウザのオプション設定
            options = EdgeOptions()
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            
            # EdgeDriverを起動
            driver = webdriver.Edge(options=options)
            driver.set_page_load_timeout(self.timeout)
            
            # ページにアクセス
            driver.get(self.target_url)
            
            # ページが完全に読み込まれるまで待機
            WebDriverWait(driver, self.timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            response_time = time.time() - start_time
            
            # ページ情報を取得
            page_source = driver.page_source
            cookies = driver.get_cookies()
            
            result.success = True
            result.response_time = response_time
            result.status_code = 200  # Seleniumは常に200を返す
            result.content_length = len(page_source.encode('utf-8'))
            result.cookies_count = len(cookies)
            result.has_javascript = True
            result.dynamic_content = True  # SeleniumはJavaScriptを実行する
            
            # 動的コンテンツの判定
            content = page_source.lower()
            result.dynamic_content = any([
                "__dopostback" in content,
                "javascript:" in content,
                "onclick=" in content
            ])
            
            # ダウンロード可能性の判定（より詳細な検出）
            # 1. 直接リンクの検出
            download_elements = driver.find_elements(By.XPATH, 
                "//a[contains(@href, '.pdf') or contains(@href, '.xlsx') or "
                "contains(@href, '.docx') or contains(@href, '.doc') or "
                "contains(@href, '.xls')]")
            
            # 2. JavaScriptリンク（__doPostBack）の検出
            js_links = driver.find_elements(By.XPATH, 
                "//a[contains(@onclick, '__doPostBack') or contains(@href, 'javascript:')]")
            
            # 3. ページソースからダウンロード関連のキーワードを検出
            page_source_lower = page_source.lower()
            has_download_keywords = any([
                '.pdf' in page_source_lower,
                '.xlsx' in page_source_lower,
                '.docx' in page_source_lower,
                'download' in page_source_lower,
                '__dopostback' in page_source_lower,
                'servlet' in page_source_lower
            ])
            
            result.download_possible = len(download_elements) > 0 or len(js_links) > 0 or has_download_keywords
            
            result.implementation_complexity = "medium"
            result.notes = "ブラウザを制御。JavaScript実行可能。実装は中程度の複雑さ。"
            
        except TimeoutException:
            result.error_message = f"タイムアウト（{self.timeout}秒）"
        except WebDriverException as e:
            result.error_message = f"WebDriverエラー: {str(e)}"
        except Exception as e:
            result.error_message = f"エラー: {str(e)}"
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        return result
    
    def test_playwright(self) -> LibraryTestResult:
        """Playwrightライブラリでテスト"""
        result = LibraryTestResult(
            library_name="playwright",
            available=PLAYWRIGHT_AVAILABLE,
            success=False
        )
        
        if not PLAYWRIGHT_AVAILABLE:
            result.error_message = "Playwrightライブラリがインストールされていません"
            return result
        
        try:
            start_time = time.time()
            
            with sync_playwright() as p:
                # ブラウザを起動（Chromiumを使用）
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                
                # ページにアクセス
                response = page.goto(self.target_url, timeout=self.timeout * 1000, wait_until="networkidle")
                
                # ページが完全に読み込まれるまで待機
                page.wait_for_load_state("networkidle")
                
                response_time = time.time() - start_time
                
                # ページ情報を取得
                page_content = page.content()
                cookies = context.cookies()
                headers = response.headers if response else {}
                
                result.success = True
                result.response_time = response_time
                result.status_code = response.status if response else None
                result.content_length = len(page_content.encode('utf-8'))
                result.cookies_count = len(cookies)
                result.headers_count = len(headers)
                result.has_javascript = True
                result.dynamic_content = True  # PlaywrightはJavaScriptを実行する
                
                # 動的コンテンツの判定
                content = page_content.lower()
                result.dynamic_content = any([
                    "__dopostback" in content,
                    "javascript:" in content,
                    "onclick=" in content
                ])
                
                # ダウンロード可能性の判定（より詳細な検出）
                # 1. 直接リンクの検出
                download_links = page.query_selector_all(
                    "a[href*='.pdf'], a[href*='.xlsx'], a[href*='.docx'], "
                    "a[href*='.doc'], a[href*='.xls']"
                )
                
                # 2. JavaScriptリンクの検出
                js_links = page.query_selector_all(
                    "a[onclick*='__doPostBack'], a[href^='javascript:']"
                )
                
                # 3. ページソースからダウンロード関連のキーワードを検出
                page_content_lower = page_content.lower()
                has_download_keywords = any([
                    '.pdf' in page_content_lower,
                    '.xlsx' in page_content_lower,
                    '.docx' in page_content_lower,
                    'download' in page_content_lower,
                    '__dopostback' in page_content_lower,
                    'servlet' in page_content_lower
                ])
                
                result.download_possible = len(download_links) > 0 or len(js_links) > 0 or has_download_keywords
                
                result.implementation_complexity = "medium"
                result.notes = "モダンなブラウザ自動化。JavaScript実行可能。APIが直感的。"
                
                browser.close()
                
        except PlaywrightTimeoutError:
            result.error_message = f"タイムアウト（{self.timeout}秒）"
        except Exception as e:
            result.error_message = f"エラー: {str(e)}"
        
        return result
    
    def run_comparison(self) -> List[LibraryTestResult]:
        """すべてのライブラリでテストを実行"""
        print(f"=== ライブラリ比較テスト ===")
        print(f"対象URL: {self.target_url}")
        print(f"タイムアウト: {self.timeout}秒")
        print()
        
        # requestsでテスト
        print("1. requests でテスト中...")
        result_requests = self.test_requests()
        self.results.append(result_requests)
        self._print_result(result_requests)
        print()
        
        # Seleniumでテスト
        print("2. Selenium でテスト中...")
        result_selenium = self.test_selenium()
        self.results.append(result_selenium)
        self._print_result(result_selenium)
        print()
        
        # Playwrightでテスト
        print("3. Playwright でテスト中...")
        result_playwright = self.test_playwright()
        self.results.append(result_playwright)
        self._print_result(result_playwright)
        print()
        
        return self.results
    
    def _print_result(self, result: LibraryTestResult):
        """結果を表示"""
        # Windowsコンソール対応: ASCII文字のみを使用（環境に依存しない）
        status = "[OK] 成功" if result.success else "[NG] 失敗"
        print(f"  結果: {status}")
        
        if result.error_message:
            print(f"  エラー: {result.error_message}")
        
        if result.success:
            print(f"  応答時間: {result.response_time:.2f}秒")
            print(f"  ステータスコード: {result.status_code}")
            print(f"  コンテンツサイズ: {result.content_length:,} bytes")
            print(f"  JavaScript実行: {'可能' if result.has_javascript else '不可'}")
            print(f"  動的コンテンツ: {'あり' if result.dynamic_content else 'なし'}")
            print(f"  ダウンロード可能: {'はい' if result.download_possible else '不明'}")
            print(f"  実装複雑度: {result.implementation_complexity}")
            if result.notes:
                print(f"  備考: {result.notes}")
    
    def generate_report(self, output_file: Optional[str] = None) -> Dict:
        """比較レポートを生成"""
        report = {
            "target_url": self.target_url,
            "test_date": datetime.now().isoformat(),
            "timeout": self.timeout,
            "results": [asdict(result) for result in self.results],
            "recommendation": self._generate_recommendation()
        }
        
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"\nレポートを保存しました: {output_file}")
        
        return report
    
    def _generate_recommendation(self) -> Dict:
        """推奨ライブラリを判定"""
        available_results = [r for r in self.results if r.available]
        successful_results = [r for r in available_results if r.success]
        
        if not successful_results:
            return {
                "recommended": None,
                "reason": "すべてのライブラリでテストが失敗しました"
            }
        
        # 成功したライブラリを評価
        scores = {}
        for result in successful_results:
            score = 0
            
            # 応答時間（短いほど良い）
            if result.response_time:
                if result.response_time < 2:
                    score += 3
                elif result.response_time < 5:
                    score += 2
                else:
                    score += 1
            
            # JavaScript実行能力
            if result.has_javascript:
                score += 2
            
            # 動的コンテンツ対応（動的コンテンツがある場合、JavaScript実行能力を重視）
            if result.dynamic_content:
                if result.has_javascript:
                    score += 3  # JavaScript実行可能な場合、高評価
                else:
                    # JavaScript実行不可な場合、減点（ただしrequestsでも検出できる場合は減点しない）
                    if result.library_name == "requests":
                        score += 1  # requestsでも動的コンテンツを検出できる場合は加点
                    else:
                        score += 0  # その他の場合は加点なし
            
            # ダウンロード可能性
            if result.download_possible:
                score += 2
            
            # 実装の容易さ
            if result.implementation_complexity == "low":
                score += 3
            elif result.implementation_complexity == "medium":
                score += 2
            else:
                score += 1
            
            scores[result.library_name] = {
                "score": score,
                "result": result
            }
        
        # 最高スコアのライブラリを推奨
        if scores:
            # 最高スコアを取得
            max_score = max(v["score"] for v in scores.values())
            
            # 最高スコアのライブラリをすべて取得（同点の場合）
            best_libraries = [(k, v) for k, v in scores.items() if v["score"] == max_score]
            
            # 同点の場合、応答時間が短いものを優先
            if len(best_libraries) > 1:
                best = min(best_libraries, key=lambda x: x[1]["result"].response_time or float('inf'))
            else:
                best = best_libraries[0]
            
            recommended = best[0]
            score = best[1]["score"]
            
            reasons = []
            result = best[1]["result"]
            
            if result.has_javascript:
                reasons.append("JavaScript実行が必要")
            if result.dynamic_content:
                reasons.append("動的コンテンツに対応")
            if result.download_possible:
                reasons.append("ファイルダウンロードが可能")
            if result.implementation_complexity == "low":
                reasons.append("実装が容易")
            
            # 同点の場合の情報を追加
            if len(best_libraries) > 1:
                tied_libraries = [lib[0] for lib in best_libraries]
                reasons.append(f"同点ライブラリ: {', '.join(tied_libraries)}（応答時間で選択）")
            
            return {
                "recommended": recommended,
                "score": score,
                "reasons": reasons,
                "all_scores": {k: v["score"] for k, v in scores.items()}
            }
        
        return {
            "recommended": None,
            "reason": "評価できませんでした"
        }


def main():
    """メイン関数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="ライブラリ比較スクリプト")
    parser.add_argument(
        "url",
        nargs="?",
        default="https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4",
        help="テスト対象のURL（デフォルト: i-ppi.jpの検索ページ）"
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=30,
        help="タイムアウト時間（秒、デフォルト: 30）"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="docs/dev/library_comparison_report.json",
        help="レポート出力ファイル（デフォルト: docs/dev/library_comparison_report.json）"
    )
    
    args = parser.parse_args()
    
    # 比較を実行
    comparator = LibraryComparator(args.url, timeout=args.timeout)
    results = comparator.run_comparison()
    
    # レポートを生成
    report = comparator.generate_report(args.output)
    
    # 推奨を表示
    print("\n=== 推奨ライブラリ ===")
    recommendation = report["recommendation"]
    if recommendation.get("recommended"):
        print(f"推奨: {recommendation['recommended']}")
        print(f"スコア: {recommendation['score']}")
        print("理由:")
        for reason in recommendation.get("reasons", []):
            print(f"  - {reason}")
        print("\n全ライブラリのスコア:")
        for lib, score in recommendation.get("all_scores", {}).items():
            print(f"  - {lib}: {score}")
    else:
        print(f"推奨なし: {recommendation.get('reason', '不明')}")


if __name__ == "__main__":
    main()
