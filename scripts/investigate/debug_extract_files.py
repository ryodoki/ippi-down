# -*- coding: utf-8 -*-
"""
ファイル抽出のデバッグスクリプト（後方互換用スタブ）

本スクリプトは scripts/investigate/investigate_i_ppi.py の extract-files サブコマンドを呼び出します。
新規利用では以下を推奨します:

  python scripts/investigate/investigate_i_ppi.py extract-files --url <詳細ページURL> --out <出力JSONパス>

使用方法（従来通り）:
  python scripts/investigate/debug_extract_files.py --url <詳細ページURL> --out <出力JSONパス> [--debug-log]
"""

import subprocess
import sys
from pathlib import Path

def main():
    script_dir = Path(__file__).resolve().parent
    investigate = script_dir / "investigate_i_ppi.py"
    if not investigate.exists():
        print("エラー: investigate_i_ppi.py が見つかりません", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(investigate), "extract-files"]
    # argparse で解析せず、sys.argv をそのまま渡す（--url, --out, --debug-log, --file-types）
    cmd.extend(sys.argv[1:])
    return subprocess.call(cmd)

if __name__ == "__main__":
    sys.exit(main())
