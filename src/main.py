<<<<<<< HEAD
"""エントリーポイント（GUI版 - CustomTkinter）"""
=======
# -*- coding: utf-8 -*-

"""エントリーポイント（GUI版）"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

import customtkinter as ctk
import tkinter as tk
import sys
import os
import time
from pathlib import Path

# プロジェクトルートをパスに追加（開発時のみ必要、exe配布時は不要）
if not getattr(sys, 'frozen', False):
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig
from src.gui.main_window import MainWindow
from src.utils.logger import Logger
from src.utils import netguard
from src.utils.ssl_config import configure_ssl
from src.utils.notifier import Notifier
from src.app.service import ApplicationService
from src.app.events import ProgressEvent
from src.scheduler.scheduler import Scheduler


def download_files(main_window: MainWindow):
    """ファイルをダウンロード（GUI用）"""
    logger = main_window.logger
    logger.info("ダウンロードを開始します")

    # 設定を取得
    config = main_window.get_config_from_ui()
    
    # デバッグ: 検索条件を確認
    if config.search_conditions:
        sc = config.search_conditions
        logger.info(
            f"検索条件 - 大分類: '{sc.hachu_daibunrui}', "
            f"中分類: '{sc.hachu_chubunrui}', "
            f"小分類: '{sc.hachu_shoubunrui}', "
            f"細分類: '{sc.hachu_saibunrui}', "
            f"工事名: '{sc.koji_name}'"
        )
    else:
        logger.warning("検索条件が設定されていません")

    # ApplicationServiceを使用
    service = ApplicationService(logger)
    
    # 進捗コールバック（EventHandler経由）
    def progress_callback(event: ProgressEvent):
        main_window.event_handler.emit(event)
    
    # キャンセルフラグ
    def cancel_check() -> bool:
        return main_window.cancel_flag.is_set()

    # 実行
    run_result = service.run(config, progress_callback, cancel_check)

    # 結果の処理
    if not run_result.success:
        if run_result.message:
            main_window.show_message(run_result.message, "warning" if "キャンセル" in run_result.message else "error")
        return

    # 結果を表示
    if run_result.result:
        result = run_result.result
        result_message = (
            f"ダウンロード完了: 成功={result.success}, "
            f"失敗={result.failed}, スキップ={result.skipped}"
        )
        main_window.show_message(result_message, "info")
        main_window.update_progress(result.total, result.total, "完了")

        # 通知を表示（バックグラウンド実行時）
        if not main_window.root.winfo_viewable():
            notifier = Notifier(logger)
            notifier.notify("ppi-file-downloader", result_message, duration=10)


def run_scheduled_download(config: AppConfig, logger: Logger):
    """スケジュール実行用のダウンロード関数（GUIなし）"""
    logger.info("スケジュールに従ってダウンロードを開始します")

    # デバッグ: 検索条件を確認
    if config.search_conditions:
        sc = config.search_conditions
        logger.info(
            f"検索条件 - 大分類: '{sc.hachu_daibunrui}', "
            f"中分類: '{sc.hachu_chubunrui}', "
            f"小分類: '{sc.hachu_shoubunrui}', "
            f"細分類: '{sc.hachu_saibunrui}', "
            f"工事名: '{sc.koji_name}'"
        )
    else:
        logger.warning("検索条件が設定されていません")

    # ApplicationServiceを使用
    service = ApplicationService(logger)
    notifier = Notifier(logger)

    # 進捗コールバック（ログのみ）
    def progress_callback(event: ProgressEvent):
        if event.message:
            logger.info(event.message)

    # 実行
    run_result = service.run(config, progress_callback, cancel_flag=None)

    # 結果の処理
    if not run_result.success:
        error_message = run_result.message or run_result.error or "ダウンロードに失敗しました"
        logger.error(error_message)
        notifier.notify("ppi-file-downloader", error_message, duration=10)
        return

    # 結果を通知
    if run_result.result:
        result_message = run_result.message
        logger.info(result_message)
        notifier.notify("ppi-file-downloader", result_message, duration=10)


def main():
    """メイン関数"""
    # 設定より前に許可リストを有効化する（起動直後の通信も対象にする）
    netguard.install_guard()
    configure_ssl()

    # 設定を読み込み
    config_manager = ConfigManager()
    config = config_manager.load_config()
    logger = Logger(config.logging)
    policy = netguard.install_from_config(config.network, logger=logger)
    logger.info(f"通信の許可先: {', '.join(policy.allowed_hosts) or 'なし（全遮断）'}")

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
            # NOTE: moved to top-level imports (keep for reference during refactor)
            # import time

            try:
                while True:
                    time.sleep(60)  # 1分ごとにチェック
            except KeyboardInterrupt:
                scheduler.stop()
        else:
            # スケジュールが無効な場合は1回だけ実行
            run_scheduled_download(config, logger)
        return

    # GUIモード（CustomTkinter）
    root = ctk.CTk()
    config_manager = ConfigManager()
    main_window = MainWindow(root, config, config_manager, logger)
    # ダウンロードコールバックを設定（_download_threadからselfが渡される）
    main_window.set_download_callback(lambda mw: download_files(mw))

    # スケジューラーを設定（GUIモードでもバックグラウンドで動作）
    if config.schedule.enabled:
        scheduler = Scheduler(config.schedule, logger)
        scheduler.set_download_callback(lambda: run_scheduled_download(config, logger))
        scheduler.start()
        logger.info("スケジューラーを開始しました")

    root.mainloop()


if __name__ == "__main__":
    main()

