# -*- coding: utf-8 -*-

"""CLIエントリーポイント（FR-024）"""

import argparse
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
if not getattr(sys, 'frozen', False):
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig
from src.utils.logger import Logger
from src.app.service import ApplicationService
from src.app.events import ProgressEvent, EventType


def main():
    """CLIメイン関数"""
    parser = argparse.ArgumentParser(
        description="ppi-file-downloader CLI版",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  # 設定ファイルを指定して1回実行
  python src/cli/main.py --config config/config.yaml --once
  
  # ドライラン（ダウンロードせず対象件数と予定ファイル名だけ出力）
  python src/cli/main.py --config config/config.yaml --once --dry-run
        """
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="設定ファイルのパス（デフォルト: config/config.yaml）"
    )
    
    parser.add_argument(
        "--once",
        action="store_true",
        help="1回だけ実行して終了"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ダウンロードせず対象件数と予定ファイル名だけ出力"
    )
    
    args = parser.parse_args()
    
    # 設定を読み込み
    config_manager = ConfigManager(config_path=args.config)
    config = config_manager.load_config()
    logger = Logger(config.logging)
    
    logger.info("CLIモードで実行します")
    if args.config:
        logger.info(f"設定ファイル: {args.config}")
    if args.dry_run:
        logger.info("ドライランモード: ダウンロードは実行しません")
    
    # ApplicationServiceを使用
    service = ApplicationService(logger)
    
    # 進捗コールバック（ログ出力のみ）
    def progress_callback(event: ProgressEvent):
        if event.message:
            logger.info(event.message)
        if event.type == EventType.COMPLETE:
            # 完了時に失敗理由別サマリーを出力
            if event.metadata and "result" in event.metadata:
                result = event.metadata["result"]
                failure_summary = result.summarize_failures()
                failure_summary_text = ", ".join([
                    f"{k}={v}" for k, v in failure_summary.items() if v > 0
                ])
                if failure_summary_text:
                    logger.info(f"失敗理由別サマリー: {failure_summary_text}")
    
    # キャンセルフラグ（CLIでは常にNone）
    cancel_flag = None
    
    # ドライランモード
    if args.dry_run:
        logger.info("ドライランモード: ファイル抽出のみ実行します")
        # ファイル抽出のみ実行
        all_files = service._extract_files(config, progress_callback, cancel_flag)
        if not all_files:
            logger.warning("ファイルが見つかりませんでした")
            return 1
        
        # フィルタリング
        filtered_files = service._filter_files(all_files, progress_callback)
        if not filtered_files:
            logger.warning("ダウンロード対象のファイルが見つかりませんでした")
            return 1
        
        logger.info(f"ドライラン結果: 対象ファイル数={len(filtered_files)}件")
        for i, file_info in enumerate(filtered_files[:10], 1):  # 最初の10件だけ表示
            logger.info(f"  {i}. {file_info.filename} ({file_info.url[:80]}...)")
        if len(filtered_files) > 10:
            logger.info(f"  ... 他 {len(filtered_files) - 10}件")
        
        return 0
    
    # 通常実行
    run_result = service.run(config, progress_callback, cancel_flag)
    
    if not run_result.success:
        logger.error(run_result.message or run_result.error or "ダウンロードに失敗しました")
        return 1
    
    # 結果を表示
    if run_result.result:
        result = run_result.result
        logger.info(
            f"ダウンロード完了: 成功={result.success}, "
            f"失敗={result.failed}, スキップ={result.skipped}"
        )
        
        # 失敗理由別サマリーを出力（FR-005）
        failure_summary = result.summarize_failures()
        failure_summary_text = ", ".join([
            f"{k}={v}" for k, v in failure_summary.items() if v > 0
        ])
        if failure_summary_text:
            logger.info(f"失敗理由別サマリー: {failure_summary_text}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
