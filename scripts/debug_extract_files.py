# -*- coding: utf-8 -*-

"""ファイル抽出のデバッグスクリプト

使用方法:
    python scripts/debug_extract_files.py --url <詳細ページURL> --out <出力JSONパス> [--debug-log]

例:
    python scripts/debug_extract_files.py --url "https://www.i-ppi.jp/..." --out debug_output.json --debug-log
"""

import sys
import json
import argparse
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.scraper import Scraper
from src.utils.http_client import HTTPClient
from src.utils.logger import Logger, LoggingConfig


def main():
    parser = argparse.ArgumentParser(description="ファイル抽出のデバッグスクリプト")
    parser.add_argument("--url", required=True, help="詳細ページURLまたはPostBackリンク")
    parser.add_argument("--out", required=True, help="出力JSONファイルパス")
    parser.add_argument("--debug-log", action="store_true", help="DEBUGログを有効化")
    parser.add_argument("--file-types", nargs="+", default=[".pdf", ".xlsx", ".docx"], help="対象ファイルタイプ")
    
    args = parser.parse_args()
    
    # ログ設定
    log_config = LoggingConfig(level="DEBUG" if args.debug_log else "INFO")
    logger = Logger(log_config)
    
    # HTTPClientとScraperを初期化
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    logger.info(f"ファイル抽出を開始: URL={args.url}")
    logger.info(f"対象ファイルタイプ: {args.file_types}")
    
    try:
        # PostBackリンクか通常のURLかを判定
        if args.url.startswith("javascript:") and "__doPostBack" in args.url:
            # PostBackリンクの場合
            logger.info("PostBackリンクとして処理します")
            # 注意: PostBackリンクの処理には検索結果ページのsoupが必要
            # このスクリプトでは簡易的に処理できないため、警告を出す
            logger.warning("PostBackリンクの処理には検索結果ページが必要です。通常のURLを指定してください。")
            return 1
        else:
            # 通常のURLの場合
            logger.info("通常のURLとして処理します")
            files = scraper._extract_files_from_detail_page(args.url, args.file_types)
        
        # 結果をJSON形式で出力
        output_data = {
            "url": args.url,
            "file_types": args.file_types,
            "files_count": len(files),
            "files": []
        }
        
        for idx, file_info in enumerate(files, 1):
            file_data = {
                "index": idx,
                "url": file_info.url,
                "filename": file_info.filename,
                "file_type": file_info.file_type,
                "page_url": file_info.page_url,
                "metadata": file_info.metadata or {}
            }
            output_data["files"].append(file_data)
            logger.info(
                f"ファイル[{idx}]: 文書名='{file_info.metadata.get('title', 'N/A') if file_info.metadata else 'N/A'}', "
                f"URL='{file_info.url[:80]}...', type={file_info.file_type}"
            )
        
        # JSONファイルに保存
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"結果を保存しました: {output_path}")
        logger.info(f"抽出されたファイル数: {len(files)}")
        
        return 0
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {str(e)}", exc_info=True)
        return 1
    finally:
        http_client.close()


if __name__ == "__main__":
    sys.exit(main())
