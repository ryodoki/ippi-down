"""エントリーポイント（GUI版）"""

import tkinter as tk
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig
from src.gui.main_window import MainWindow
from src.utils.logger import Logger
from src.utils.http_client import HTTPClient
from src.utils.notifier import Notifier
from src.utils.startup_manager import StartupManager
from src.core.scraper import Scraper
from src.core.filter import Filter
from src.core.downloader import Downloader
from src.core.naming import Naming
from src.storage.box_client import BoxClient
from src.scheduler.scheduler import Scheduler


def download_files(main_window: MainWindow):
    """ファイルをダウンロード"""
    logger = main_window.logger
    logger.info("ダウンロードを開始します")

    # 設定を取得
    config = main_window.get_config_from_ui()
    
    # 保存先ディレクトリが存在しない場合は作成
    from pathlib import Path
    save_dir = Path(config.save_paths.local)
    save_dir.mkdir(parents=True, exist_ok=True)

    # 初期化
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    filter_obj = Filter(config.download_conditions, logger)
    naming = Naming(config.naming_rule, logger)
    downloader = Downloader(http_client, logger)

    # Boxクライアント（オプション）
    box_client = None
    if config.save_paths.box.get("enabled", False):
        box_client = BoxClient(
            config.box.client_id,
            config.box.client_secret,
            config.box.access_token,
            config.box.refresh_token,
            logger,
        )

    try:
        # 各URLからファイルを取得
        all_files = []
        for url in config.target_urls:
            # キャンセルチェック
            if main_window.cancel_flag.is_set():
                logger.info("ダウンロードがキャンセルされました")
                main_window.show_message("ダウンロードがキャンセルされました", "warning")
                return
            
            logger.info(f"ページを解析中: {url}")
            main_window.show_message(f"ページを解析中: {url}", "info")
            
            # 検索条件が設定されている場合は検索フォームを送信
            # すべての検索条件をチェック
            has_search_conditions = False
            if config.search_conditions:
                sc = config.search_conditions
                has_search_conditions = (
                    sc.hachu_daibunrui or sc.hachu_chubunrui or sc.hachu_shoubunrui or sc.hachu_saibunrui or
                    (sc.hachu_multi and len(sc.hachu_multi) > 0) or
                    sc.koji_name or
                    (sc.place_search_type == "list" and (sc.place_chihou or sc.place_todofuken or sc.place_shichouson)) or
                    (sc.place_search_type == "text" and sc.place_text) or
                    (sc.contract_types and len(sc.contract_types) > 0) or
                    sc.update_date_type == "past" or
                    sc.koukoku_date_type == "range" or
                    sc.kaisatsu_date_type == "range" or
                    sc.keiyaku_date_type == "range" or
                    sc.koji_shubetsu or
                    sc.koji_gyoushu or
                    sc.yotei_price_min is not None or sc.yotei_price_max is not None or
                    sc.rakusatsu_price_min is not None or sc.rakusatsu_price_max is not None or
                    sc.rakusatsu_name or
                    sc.denshi or
                    sc.koukai
                )
            
            if has_search_conditions:
                # 検索フォームを送信
                main_window.show_message("検索条件で検索を実行中...", "info")
                soup = scraper.submit_search_form(url, config.search_conditions)
                if soup:
                    # 検索結果ページからファイルを抽出
                    files = scraper.extract_file_links_from_search_results(
                        soup, url, config.download_conditions.file_types
                    )
                    all_files.extend(files)
                    main_window.show_message(f"検索結果から{len(files)}個のファイルリンクを発見", "info")
                else:
                    main_window.show_message(f"検索の実行に失敗しました: {url}", "error")
            else:
                # 検索条件がない場合は通常のページ解析
                soup = scraper.fetch_page(url)
                if soup:
                    files = scraper.extract_file_links(soup, url, config.download_conditions.file_types)
                    all_files.extend(files)
                    main_window.show_message(f"{len(files)}個のファイルリンクを発見", "info")
                else:
                    main_window.show_message(f"ページの取得に失敗しました: {url}", "error")

        # キャンセルチェック
        if main_window.cancel_flag.is_set():
            logger.info("ダウンロードがキャンセルされました")
            main_window.show_message("ダウンロードがキャンセルされました", "warning")
            return

        # フィルタリング
        filtered_files = filter_obj.filter_files(all_files)
        logger.info(f"フィルタリング後: {len(filtered_files)}件")
        main_window.show_message(f"フィルタリング後: {len(filtered_files)}件", "info")

        if not filtered_files:
            main_window.show_message("ダウンロード対象のファイルが見つかりませんでした", "warning")
            return
        
        # キャンセルチェック
        if main_window.cancel_flag.is_set():
            logger.info("ダウンロードがキャンセルされました")
            main_window.show_message("ダウンロードがキャンセルされました", "warning")
            return

        # ダウンロード実行
        def progress_callback(current, total, filename):
            # キャンセルチェック
            if main_window.cancel_flag.is_set():
                return False  # Falseを返すことでダウンロードを中断
            main_window.root.after(0, lambda: main_window.update_progress(current, total, filename))
            main_window.root.after(0, lambda: main_window.show_message(f"{filename} をダウンロード中..."))
            return True  # 続行

        result = downloader.download_files(
            filtered_files,
            config.save_paths.local,
            naming,
            progress_callback,
        )
        
        # キャンセルチェック
        if main_window.cancel_flag.is_set():
            logger.info("ダウンロードがキャンセルされました")
            main_window.show_message("ダウンロードがキャンセルされました", "warning")
            return

        # Boxにアップロード（オプション）
        if box_client and config.save_paths.box.get("enabled", False):
            box_client.authenticate()
            box_folder_id = config.save_paths.box.get("folder_id")
            if box_folder_id:
                for task in result.tasks:
                    if task.status == "completed":
                        box_client.upload_file(task.local_path, box_folder_id)

        # 結果を表示
        result_message = f"ダウンロード完了: 成功={result.success}, 失敗={result.failed}, スキップ={result.skipped}"
        main_window.show_message(result_message, "info")
        main_window.update_progress(result.total, result.total, "完了")

        # 通知を表示（バックグラウンド実行時）
        if not main_window.root.winfo_viewable():  # ウィンドウが表示されていない場合
            notifier = Notifier(logger)
            notifier.notify(
                "ppi-file-downloader",
                result_message,
                duration=10,
            )

    except Exception as e:
        logger.error(f"ダウンロード処理エラー: {str(e)}")
        main_window.show_message(f"エラー: {str(e)}", "error")
    finally:
        http_client.close()


def run_scheduled_download(config: AppConfig, logger: Logger):
    """スケジュール実行用のダウンロード関数（GUIなし）"""
    logger.info("スケジュールに従ってダウンロードを開始します")

    # 保存先ディレクトリが存在しない場合は作成
    from pathlib import Path
    save_dir = Path(config.save_paths.local)
    save_dir.mkdir(parents=True, exist_ok=True)

    # 初期化
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    filter_obj = Filter(config.download_conditions, logger)
    naming = Naming(config.naming_rule, logger)
    downloader = Downloader(http_client, logger)

    # Boxクライアント（オプション）
    box_client = None
    if config.save_paths.box.get("enabled", False):
        box_client = BoxClient(
            config.box.client_id,
            config.box.client_secret,
            config.box.access_token,
            config.box.refresh_token,
            logger,
        )

    notifier = Notifier(logger)

    try:
        # 各URLからファイルを取得
        all_files = []
        for url in config.target_urls:
            logger.info(f"ページを解析中: {url}")
            
            # 検索条件が設定されている場合は検索フォームを送信
            # すべての検索条件をチェック
            has_search_conditions = False
            if config.search_conditions:
                sc = config.search_conditions
                has_search_conditions = (
                    sc.hachu_daibunrui or sc.hachu_chubunrui or sc.hachu_shoubunrui or sc.hachu_saibunrui or
                    (sc.hachu_multi and len(sc.hachu_multi) > 0) or
                    sc.koji_name or
                    (sc.place_search_type == "list" and (sc.place_chihou or sc.place_todofuken or sc.place_shichouson)) or
                    (sc.place_search_type == "text" and sc.place_text) or
                    (sc.contract_types and len(sc.contract_types) > 0) or
                    sc.update_date_type == "past" or
                    sc.koukoku_date_type == "range" or
                    sc.kaisatsu_date_type == "range" or
                    sc.keiyaku_date_type == "range" or
                    sc.koji_shubetsu or
                    sc.koji_gyoushu or
                    sc.yotei_price_min is not None or sc.yotei_price_max is not None or
                    sc.rakusatsu_price_min is not None or sc.rakusatsu_price_max is not None or
                    sc.rakusatsu_name or
                    sc.denshi or
                    sc.koukai
                )
            
            if has_search_conditions:
                # 検索フォームを送信
                logger.info("検索条件で検索を実行中...")
                soup = scraper.submit_search_form(url, config.search_conditions)
                if soup:
                    # 検索結果ページからファイルを抽出
                    files = scraper.extract_file_links_from_search_results(
                        soup, url, config.download_conditions.file_types
                    )
                    all_files.extend(files)
                    logger.info(f"検索結果から{len(files)}個のファイルリンクを発見")
                else:
                    logger.error(f"検索の実行に失敗しました: {url}")
            else:
                # 検索条件がない場合は通常のページ解析
                soup = scraper.fetch_page(url)
                if soup:
                    files = scraper.extract_file_links(soup, url, config.download_conditions.file_types)
                    all_files.extend(files)
                    logger.info(f"{len(files)}個のファイルリンクを発見")
                else:
                    logger.error(f"ページの取得に失敗しました: {url}")

        # フィルタリング
        filtered_files = filter_obj.filter_files(all_files)
        logger.info(f"フィルタリング後: {len(filtered_files)}件")

        if not filtered_files:
            notifier.notify("ppi-file-downloader", "ダウンロード対象のファイルが見つかりませんでした")
            return

        # ダウンロード実行
        result = downloader.download_files(filtered_files, config.save_paths.local, naming)

        # Boxにアップロード（オプション）
        if box_client and config.save_paths.box.get("enabled", False):
            box_client.authenticate()
            box_folder_id = config.save_paths.box.get("folder_id")
            if box_folder_id:
                for task in result.tasks:
                    if task.status == "completed":
                        box_client.upload_file(task.local_path, box_folder_id)

        # 結果を通知
        result_message = f"ダウンロード完了: 成功={result.success}, 失敗={result.failed}, スキップ={result.skipped}"
        logger.info(result_message)
        notifier.notify("ppi-file-downloader", result_message, duration=10)

    except Exception as e:
        error_message = f"ダウンロード処理エラー: {str(e)}"
        logger.error(error_message)
        notifier.notify("ppi-file-downloader", error_message, duration=10)
    finally:
        http_client.close()


def main():
    """メイン関数"""
    import os

    # 設定を読み込み
    config_manager = ConfigManager()
    config = config_manager.load_config()
    logger = Logger(config.logging)

    # バックグラウンド実行モードかチェック（環境変数またはコマンドライン引数）
    background_mode = os.getenv("PPI_BACKGROUND_MODE", "").lower() == "true"
    if len(sys.argv) > 1 and sys.argv[1] == "--background":
        background_mode = True

    # バックグラウンドモードの場合
    if background_mode:
        logger.info("バックグラウンドモードで実行します")
        # スケジュールが有効な場合はスケジューラーを起動
        if config.schedule.enabled:
            scheduler = Scheduler(config.schedule, logger)
            scheduler.set_download_callback(lambda: run_scheduled_download(config, logger))
            scheduler.start()

            # スケジューラーを実行し続ける
            import time
            try:
                while True:
                    time.sleep(60)  # 1分ごとにチェック
            except KeyboardInterrupt:
                scheduler.stop()
        else:
            # スケジュールが無効な場合は1回だけ実行
            run_scheduled_download(config, logger)
        return

    # GUIモード
    root = tk.Tk()
    config_manager = ConfigManager()
    main_window = MainWindow(root, config, config_manager, logger)
    main_window.set_download_callback(lambda: download_files(main_window))

    # スケジューラーを設定（GUIモードでもバックグラウンドで動作）
    if config.schedule.enabled:
        scheduler = Scheduler(config.schedule, logger)
        scheduler.set_download_callback(lambda: run_scheduled_download(config, logger))
        scheduler.start()
        logger.info("スケジューラーを開始しました")

    root.mainloop()


if __name__ == "__main__":
    main()

