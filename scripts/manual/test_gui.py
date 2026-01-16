#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GUIテスト用スクリプト"""

import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from src.gui.main_window import MainWindow
    from src.models.config_model import AppConfig, SearchConditions
    from src.config.config_manager import ConfigManager
    import logging
    
    print("=" * 50)
    print("GUIテスト開始")
    print("=" * 50)
    
    # ロガー設定
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # 設定を読み込み
    config_manager = ConfigManager()
    config = config_manager.load_config()
    
    print(f"設定読み込み成功: {config}")
    print(f"検索条件: {config.search_conditions}")
    
    # GUIを起動
    import tkinter as tk
    root = tk.Tk()
    app = MainWindow(root, config, config_manager, logger)
    
    print("GUI起動成功")
    print("ウィンドウを閉じると終了します")
    
    root.mainloop()
    
except Exception as e:
    print(f"エラーが発生しました: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
