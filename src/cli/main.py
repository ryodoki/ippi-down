# -*- coding: utf-8 -*-

"""CLIエントリーポイント（FR-024）"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# プロジェクトルートをパスに追加
if not getattr(sys, 'frozen', False):
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig
from src.utils.logger import Logger
from src.utils import netguard
from src.utils.ssl_config import configure_ssl
from src.app.service import ApplicationService
from src.app.events import ProgressEvent, EventType


def _write_report(path: str, payload: dict[str, Any], logger=None) -> None:
    """実行サマリーを JSON で書き出す（タスクスケジューラ等からの監視用）"""
    try:
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if logger:
            logger.info(f"実行レポートを出力しました: {report_path}")
    except OSError as e:
        if logger:
            logger.error(f"実行レポートの出力に失敗しました: {e}")


def _build_report_payload(
    *,
    started_at: datetime,
    success: bool,
    dry_run: bool,
    message: str = "",
    counts: Optional[dict[str, int]] = None,
    failure_summary: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    ended_at = datetime.now()
    return {
        "tool": "ippi-down",
        "started_at": started_at.isoformat(timespec="seconds"),
        "ended_at": ended_at.isoformat(timespec="seconds"),
        "duration_seconds": round((ended_at - started_at).total_seconds(), 1),
        "dry_run": dry_run,
        "success": success,
        "message": message,
        "counts": counts or {},
        "failure_summary": {k: v for k, v in (failure_summary or {}).items() if v > 0},
    }


def main():
    """CLIメイン関数"""
    # 設定より前に許可リストを有効化する（起動直後の通信も対象にする）
    netguard.install_guard()
    configure_ssl()

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

    parser.add_argument(
        "--report",
        type=str,
        default=None,
        help="実行サマリーを JSON で出力するパス（定期実行の監視用）"
    )

    args = parser.parse_args()
    started_at = datetime.now()
    
    # 設定を読み込み
    config_manager = ConfigManager(config_path=args.config)
    config = config_manager.load_config()
    logger = Logger(config.logging)
    policy = netguard.install_from_config(config.network, logger=logger)

    logger.info("CLIモードで実行します")
    logger.info(f"通信の許可先: {', '.join(policy.allowed_hosts) or 'なし（全遮断）'}")
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
    
    def finish(
        exit_code: int,
        message: str = "",
        counts: Optional[dict[str, int]] = None,
        failure_summary: Optional[dict[str, int]] = None,
    ) -> int:
        if args.report:
            payload = _build_report_payload(
                started_at=started_at,
                success=(exit_code == 0),
                dry_run=args.dry_run,
                message=message,
                counts=counts,
                failure_summary=failure_summary,
            )
            _write_report(args.report, payload, logger)
        return exit_code

    # ドライランモード
    if args.dry_run:
        logger.info("ドライランモード: ファイル抽出のみ実行します")
        # ファイル抽出のみ実行（_extract_files は ExtractResult を返す）
        extract_result = service._extract_files(config, progress_callback, cancel_flag)
        all_files = extract_result.files
        if not all_files:
            message = service._build_no_files_message(extract_result)
            logger.warning(message)
            return finish(1, message)

        # フィルタリング
        filtered_files = service._filter_files(all_files, progress_callback)
        if not filtered_files:
            message = "ダウンロード対象のファイルが見つかりませんでした"
            logger.warning(message)
            return finish(1, message)

        logger.info(f"ドライラン結果: 対象ファイル数={len(filtered_files)}件")
        for i, file_info in enumerate(filtered_files[:10], 1):  # 最初の10件だけ表示
            logger.info(f"  {i}. {file_info.filename} ({file_info.url[:80]}...)")
        if len(filtered_files) > 10:
            logger.info(f"  ... 他 {len(filtered_files) - 10}件")

        return finish(
            0,
            f"ドライラン結果: 対象ファイル数={len(filtered_files)}件",
            counts={"target": len(filtered_files)},
        )

    # 通常実行
    run_result = service.run(config, progress_callback, cancel_flag)

    if not run_result.success:
        message = run_result.message or run_result.error or "ダウンロードに失敗しました"
        logger.error(message)
        failure_summary = (
            run_result.result.summarize_failures() if run_result.result else None
        )
        return finish(1, message, failure_summary=failure_summary)

    # 結果を表示
    counts: Optional[dict[str, int]] = None
    failure_summary: Optional[dict[str, int]] = None
    message = ""
    if run_result.result:
        result = run_result.result
        message = (
            f"ダウンロード完了: 成功={result.success}, "
            f"失敗={result.failed}, スキップ={result.skipped}"
        )
        logger.info(message)
        counts = {
            "total": result.total,
            "success": result.success,
            "failed": result.failed,
            "skipped": result.skipped,
        }

        # 失敗理由別サマリーを出力（FR-005）
        failure_summary = result.summarize_failures()
        failure_summary_text = ", ".join([
            f"{k}={v}" for k, v in failure_summary.items() if v > 0
        ])
        if failure_summary_text:
            logger.info(f"失敗理由別サマリー: {failure_summary_text}")

    return finish(0, message, counts=counts, failure_summary=failure_summary)


if __name__ == "__main__":
    sys.exit(main())
