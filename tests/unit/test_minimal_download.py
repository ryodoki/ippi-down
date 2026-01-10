"""最小限のダウンロード機能テスト

このスクリプトは、現在のコードで最小限のダウンロードが動作するかを確認します。
要件定義書に基づいた修正を進める前に、基本的な機能が動作することを確認します。
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, DownloadConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from src.core.filter import Filter  # type: ignore
from src.core.downloader import Downloader  # type: ignore
from src.core.naming import Naming  # type: ignore


def test_minimal_download():
    """最小限のダウンロード機能をテスト"""
    print("=" * 60)
    print("最小限ダウンロード機能のテスト")
    print("=" * 60)
    
    # ロガー初期化
    logger = Logger(LoggingConfig(level="INFO"))
    logger.info("テストを開始します")
    
    # 保存先
    save_path = Path("./downloads/test_minimal")
    save_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"保存先: {save_path.absolute()}")
    
    # 初期化
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    download_conditions = DownloadConditions(
        file_types=[".pdf"],  # PDFのみに限定してテスト
        keywords=[],
        date_range=None
    )
    filter_obj = Filter(download_conditions, logger)
    naming = Naming("{filename}", logger)  # シンプルな命名規則
    downloader = Downloader(http_client, logger)
    
    try:
        # テスト1: ページ取得ができるか
        logger.info("\n[テスト1] ページ取得の確認")
        search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        logger.info(f"URL: {search_url}")
        
        soup = scraper.fetch_page(search_url)
        if not soup:
            logger.error("❌ ページ取得に失敗しました")
            return False
        logger.info("✓ ページ取得に成功しました")
        
        # テスト2: ファイルリンクの抽出ができるか
        logger.info("\n[テスト2] ファイルリンク抽出の確認")
        
        # 方法1: 直接抽出を試す
        logger.info("方法1: ページから直接ファイルリンクを抽出...")
        files = scraper.extract_file_links(soup, search_url, download_conditions.file_types)
        logger.info(f"  直接抽出: {len(files)}件")
        
        # 方法2: 検索結果ページからの抽出を試す（詳細ページ経由）
        if len(files) == 0:
            logger.info("方法2: 検索結果ページから詳細ページ経由で抽出...")
            files = scraper.extract_file_links_from_search_results(soup, search_url, download_conditions.file_types)
            logger.info(f"  検索結果経由: {len(files)}件")
        
        logger.info(f"発見されたファイル数（合計）: {len(files)}")
        
        if len(files) == 0:
            logger.error("❌ ファイルリンクが見つかりませんでした")
            logger.info("検索条件を指定して検索フォームを送信する必要があるかもしれません")
            return False
        
        # 最初の3件のファイル情報を表示
        logger.info("\n発見されたファイル（最初の3件）:")
        for i, file_info in enumerate(files[:3], 1):
            logger.info(f"  {i}. {file_info.filename}")
            logger.info(f"     URL: {file_info.url[:80]}...")
            logger.info(f"     タイプ: {file_info.file_type}")
        
        # テスト3: フィルタリングが動作するか
        logger.info("\n[テスト3] フィルタリングの確認")
        filtered_files = filter_obj.filter_files(files)
        logger.info(f"フィルタリング後: {len(filtered_files)}件")
        
        if len(filtered_files) == 0:
            logger.warning("⚠ フィルタリング後、ダウンロード対象のファイルがありませんでした")
            return False
        
        # テスト4: ダウンロードが実行できるか（最初の1件のみ）
        logger.info("\n[テスト4] ダウンロード実行の確認")
        test_file = filtered_files[0]
        logger.info(f"テストファイル: {test_file.filename}")
        logger.info(f"URL: {test_file.url[:80]}...")
        
        def progress_callback(current, total, filename):
            if total > 0:
                percent = (current / total) * 100
                logger.info(f"  進捗: {percent:.1f}% ({current}/{total} bytes)")
            else:
                logger.info(f"  進捗: {current} bytes (サイズ不明)")
        
        result = downloader.download_files(
            [test_file],  # 1件のみテスト
            str(save_path),
            naming,
            progress_callback
        )
        
        # 結果を表示
        logger.info("\n" + "=" * 60)
        logger.info("ダウンロード結果")
        logger.info("=" * 60)
        logger.info(f"総数: {result.total}")
        logger.info(f"成功: {result.success}")
        logger.info(f"失敗: {result.failed}")
        logger.info(f"スキップ: {result.skipped}")
        
        # 成功したファイルの確認
        if result.success > 0:
            logger.info("\n✓ ダウンロードに成功しました！")
            for task in result.tasks:
                if task.status == "completed":
                    file_path = Path(task.local_path)
                    if file_path.exists():
                        size = file_path.stat().st_size
                        logger.info(f"  保存先: {file_path}")
                        logger.info(f"  ファイルサイズ: {size:,} bytes")
                    else:
                        logger.warning(f"  ⚠ ファイルが見つかりません: {task.local_path}")
        
        # 失敗したファイルの詳細
        if result.failed > 0:
            logger.warning("\n失敗したファイル:")
            for task in result.tasks:
                if task.status == "failed":
                    logger.warning(f"  - {task.file_info.filename}")
                    logger.warning(f"    エラー: {task.error_message}")
        
        # 最終判定
        if result.success > 0:
            logger.info("\n" + "=" * 60)
            logger.info("✓ 最小限のダウンロード機能は動作しています")
            logger.info("=" * 60)
            return True
        else:
            logger.error("\n" + "=" * 60)
            logger.error("❌ ダウンロードに失敗しました")
            logger.error("=" * 60)
            return False
            
    except Exception as e:
        logger.error(f"\n❌ エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()
        logger.info("\nテスト完了")


if __name__ == "__main__":
    success = test_minimal_download()
    sys.exit(0 if success else 1)

