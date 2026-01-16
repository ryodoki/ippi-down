"""堅牢なダウンロードテストスクリプト

ネットワーク問題やタイムアウトに対応した、より堅牢なテストスクリプト。
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from src.core.downloader import Downloader  # type: ignore
from src.core.naming import Naming  # type: ignore


def test_download_robust():
    """堅牢なダウンロードテスト"""
    print("=" * 80)
    print("堅牢なダウンロードテスト")
    print("=" * 80)
    print("\nこのテストは:")
    print("  - タイムアウト設定: 接続10秒、読み取り300秒（5分）")
    print("  - リトライ回数: 3回（指数バックオフ: 1, 2, 4秒）")
    print("  - GET(stream=True)を使用（HEADの代わりに）")
    print("  - ネットワーク問題に対してより寛容")
    print()
    
    logger = Logger(LoggingConfig(level="INFO"))
    
    # タイムアウトを長めに設定
    http_client = HTTPClient(logger, timeout=30, download_timeout=300)  # 5分
    scraper = Scraper(http_client, logger)
    
    search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    save_path = Path("./downloads/test_robust")
    save_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # ステップ1: 検索を実行
        print("\n[ステップ1] 検索を実行してファイルを取得")
        print("-" * 80)
        
        search_conditions = SearchConditions(
            hachu_daibunrui="国の機関"
        )
        
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        if not result_soup:
            print("[ERROR] 検索に失敗しました")
            return False
        
        files = scraper.extract_file_links_from_search_results(
            result_soup, search_url, [".pdf"]
        )
        
        if not files:
            print("[ERROR] ファイルが見つかりませんでした")
            return False
        
        print(f"[SUCCESS] {len(files)}件のファイルが見つかりました")
        
        # ステップ2: 最初のファイルでダウンロードを試行
        test_file = files[0]
        print(f"\n[ステップ2] ダウンロード実行: {test_file.filename}")
        print("-" * 80)
        print(f"URL: {test_file.url[:100]}...")
        print(f"Page URL: {test_file.page_url}")
        
        naming = Naming("{filename}", logger)
        downloader = Downloader(http_client, logger)
        
        def progress_callback(current, total, filename):
            if total > 0:
                percent = (current / total) * 100
                print(f"  進捗: {percent:.1f}% ({current:,}/{total:,} bytes)")
            else:
                print(f"  進捗: {current:,} bytes (サイズ不明)")
        
        # ダウンロード実行（HTTPClientのリトライ機能に任せる）
        result = downloader.download_files(
            [test_file],
            str(save_path),
            naming,
            progress_callback
        )
        
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
                    else:
                        print(f"  [WARN] ファイルが見つかりません: {task.local_path}")
            return True
        else:
            print("\n[ERROR] ダウンロードに失敗しました")
            for task in result.tasks:
                if task.status == "failed":
                    print(f"  - {task.file_info.filename}")
                    print(f"    エラー: {task.error_message}")
            return False
            
    except KeyboardInterrupt:
        print("\n\n[INFO] ユーザーによって中断されました")
        return False
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()


if __name__ == "__main__":
    success = test_download_robust()
    sys.exit(0 if success else 1)
