"""ダウンロード機能のテストスクリプト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig, SearchConditions  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from src.core.filter import Filter  # type: ignore
from src.core.downloader import Downloader  # type: ignore
from src.core.naming import Naming  # type: ignore
from src.models.config_model import DownloadConditions  # type: ignore

def main():
    """ダウンロード機能のテスト"""
    logger = Logger(LoggingConfig(level="INFO"))
    logger.info("=" * 60)
    logger.info("ダウンロード機能のテスト")
    logger.info("=" * 60)
    
    # テスト用の検索条件を設定
    search_conditions = SearchConditions(
        hachu_daibunrui="国の機関",  # 大分類
        hachu_chubunrui="",  # 中分類（空の場合はすべて）
        hachu_shoubunrui="",  # 小分類（空の場合はすべて）
        hachu_saibunrui="",  # 細分類（空の場合はすべて）
    )
    
    # ダウンロード条件
    download_conditions = DownloadConditions(
        file_types=[".pdf", ".xlsx", ".docx", ".doc"],
        keywords=[],
        date_range={"start": None, "end": None}
    )
    
    # 保存先
    save_path = Path("./downloads/test")
    save_path.mkdir(parents=True, exist_ok=True)
    
    # 初期化
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    filter_obj = Filter(download_conditions, logger)
    naming = Naming("{category}_{title}_{date}_{index}", logger)
    
    try:
        # 検索URL
        search_url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
        
        logger.info(f"検索URL: {search_url}")
        logger.info(f"検索条件: 大分類={search_conditions.hachu_daibunrui}")
        
        # 検索フォームを送信
        logger.info("検索フォームを送信中...")
        soup = scraper.submit_search_form(search_url, search_conditions)
        
        if not soup:
            logger.error("検索フォームの送信に失敗しました")
            return
        
        logger.info("✓ 検索フォームの送信に成功しました")
        
        # 検索結果ページのHTMLを保存
        output_file = Path("test_search_result_after_submit.html")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(str(soup))
        logger.info(f"✓ 検索結果HTMLを保存: {output_file}")
        
        # 検索結果ページからファイルリンクを抽出
        logger.info("検索結果ページからファイルリンクを抽出中...")
        files = scraper.extract_file_links_from_search_results(
            soup, search_url, download_conditions.file_types
        )
        
        logger.info(f"✓ {len(files)}個のファイルリンクを発見しました")
        
        if len(files) == 0:
            logger.warning("ファイルリンクが見つかりませんでした")
            logger.info("検索条件を変更して再試行してください")
            return
        
        # 最初の5件のファイル情報を表示
        logger.info("\n発見されたファイル（最初の5件）:")
        for i, file_info in enumerate(files[:5], 1):
            logger.info(f"  {i}. {file_info.filename}")
            logger.info(f"     URL: {file_info.url}")
            logger.info(f"     タイプ: {file_info.file_type}")
            if file_info.metadata:
                logger.info(f"     メタデータ: {file_info.metadata}")
        
        # フィルタリング
        logger.info("\nフィルタリング中...")
        filtered_files = filter_obj.filter_files(files)
        logger.info(f"✓ フィルタリング後: {len(filtered_files)}件")
        
        if len(filtered_files) == 0:
            logger.warning("フィルタリング後、ダウンロード対象のファイルがありませんでした")
            return
        
        # ダウンロード（最初の3件のみテスト）
        test_files = filtered_files[:3]
        logger.info(f"\nテスト用に最初の{len(test_files)}件をダウンロードします")
        
        downloader = Downloader(http_client, logger)
        
        def progress_callback(current, total, filename):
            logger.info(f"進捗: {current}/{total} - {filename}")
        
        result = downloader.download_files(
            test_files,
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
        
        if result.success > 0:
            logger.info(f"\n✓ ダウンロードに成功しました！")
            logger.info(f"保存先: {save_path.absolute()}")
        
        # 失敗したファイルの詳細を表示
        if result.failed > 0:
            logger.warning("\n失敗したファイル:")
            for task in result.tasks:
                if task.status == "failed":
                    logger.warning(f"  - {task.file_info.filename}: {task.error_message}")
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
    finally:
        http_client.close()
        logger.info("\nテスト完了")

if __name__ == "__main__":
    main()

