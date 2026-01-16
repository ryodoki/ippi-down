"""統合テスト: 実際のダウンロード機能の確認

このスクリプトは、実際のWebサイトにアクセスしてダウンロード機能が動作するかを確認します。
検索条件を指定してファイルを検索し、実際にダウンロードを試みます。
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions, DownloadConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from src.core.filter import Filter  # type: ignore
from src.core.downloader import Downloader  # type: ignore
from src.core.naming import Naming  # type: ignore


def test_integration_download():
    """統合テスト: 実際のダウンロード機能の確認"""
    print("=" * 80)
    print("統合テスト: 実際のダウンロード機能の確認")
    print("=" * 80)
    
    # ロガー初期化
    logger = Logger(LoggingConfig(level="INFO"))
    logger.info("統合テストを開始します")
    
    # 保存先
    save_path = Path("./downloads/test_integration")
    save_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"保存先: {save_path.absolute()}")
    
    # 初期化
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    # 検索条件を設定（実際にファイルが見つかる可能性が高い条件）
    search_conditions = SearchConditions(
        hachu_daibunrui="国の機関",  # 大分類
        hachu_chubunrui="",  # 中分類（空の場合はすべて）
        hachu_shoubunrui="",  # 小分類（空の場合はすべて）
        hachu_saibunrui="",  # 細分類（空の場合はすべて）
    )
    
    # ダウンロード条件
    download_conditions = DownloadConditions(
        file_types=[".pdf"],  # PDFのみに限定
        keywords=[],
        date_range=None
    )
    
    filter_obj = Filter(download_conditions, logger)
    naming = Naming("{filename}", logger)  # シンプルな命名規則
    downloader = Downloader(http_client, logger)
    
    try:
        # ステップ1: 検索ページを取得
        logger.info("\n[ステップ1] 検索ページの取得")
        search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
        logger.info(f"URL: {search_url}")
        
        soup = scraper.fetch_page(search_url)
        if not soup:
            logger.error("❌ 検索ページの取得に失敗しました")
            return False
        logger.info("✓ 検索ページの取得に成功しました")
        
        # ステップ2: 検索フォームを送信
        logger.info("\n[ステップ2] 検索フォームの送信")
        logger.info(f"検索条件: 大分類={search_conditions.hachu_daibunrui}")
        
        result_soup = scraper.submit_search_form(search_url, search_conditions)
        if not result_soup:
            logger.error("❌ 検索フォームの送信に失敗しました")
            return False
        logger.info("✓ 検索フォームの送信に成功しました")
        
        # ステップ3: ファイルリンクの抽出
        logger.info("\n[ステップ3] ファイルリンクの抽出")
        files = scraper.extract_file_links_from_search_results(
            result_soup, search_url, download_conditions.file_types
        )
        logger.info(f"発見されたファイル数: {len(files)}")
        
        if len(files) == 0:
            logger.warning("⚠ ファイルリンクが見つかりませんでした")
            logger.info("検索結果ページの構造を確認する必要があるかもしれません")
            return False
        
        # 最初の3件のファイル情報を表示
        logger.info("\n発見されたファイル（最初の3件）:")
        for i, file_info in enumerate(files[:3], 1):
            logger.info(f"  {i}. {file_info.filename}")
            logger.info(f"     URL: {file_info.url[:100]}...")
            logger.info(f"     タイプ: {file_info.file_type}")
            if file_info.metadata:
                logger.info(f"     メタデータ: {file_info.metadata}")
        
        # ステップ4: フィルタリング
        logger.info("\n[ステップ4] フィルタリング")
        filtered_files = filter_obj.filter_files(files)
        logger.info(f"フィルタリング後: {len(filtered_files)}件")
        
        if len(filtered_files) == 0:
            logger.warning("⚠ フィルタリング後、ダウンロード対象のファイルがありませんでした")
            return False
        
        # ステップ5: ダウンロード実行（最初の1件のみ）
        logger.info("\n[ステップ5] ダウンロード実行（最初の1件のみ）")
        test_file = filtered_files[0]
        logger.info(f"テストファイル: {test_file.filename}")
        logger.info(f"URL: {test_file.url[:100]}...")
        
        def progress_callback(current, total, filename):
            if total > 0:
                percent = (current / total) * 100
                logger.info(f"  進捗: {percent:.1f}% ({current:,}/{total:,} bytes)")
            else:
                logger.info(f"  進捗: {current:,} bytes (サイズ不明)")
        
        result = downloader.download_files(
            [test_file],  # 1件のみテスト
            str(save_path),
            naming,
            progress_callback
        )
        
        # 結果を表示
        logger.info("\n" + "=" * 80)
        logger.info("ダウンロード結果")
        logger.info("=" * 80)
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
                        logger.info(f"  ファイルサイズ: {size:,} bytes ({size / 1024:.2f} KB)")
                        logger.info(f"  ファイル名: {file_path.name}")
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
            logger.info("\n" + "=" * 80)
            logger.info("✓ 統合テスト: ダウンロード機能は正常に動作しています")
            logger.info("=" * 80)
            return True
        else:
            logger.error("\n" + "=" * 80)
            logger.error("❌ 統合テスト: ダウンロードに失敗しました")
            logger.error("=" * 80)
            return False
            
    except Exception as e:
        logger.error(f"\n❌ エラーが発生しました: {str(e)}", exc_info=True)
        return False
    finally:
        http_client.close()
        logger.info("\n統合テスト完了")


if __name__ == "__main__":
    success = test_integration_download()
    sys.exit(0 if success else 1)

