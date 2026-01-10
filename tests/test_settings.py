"""設定ダイアログのテストスクリプト"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import tkinter as tk
from src.config.config_manager import ConfigManager
from src.gui.settings_dialog import SettingsDialog
from src.models.config_model import AppConfig, SearchConditions

def test_settings_dialog():
    """設定ダイアログのテスト"""
    print("=== 設定ダイアログテスト開始 ===")
    
    # 設定を読み込み
    print("1. 設定ファイルを読み込み中...")
    config_manager = ConfigManager()
    config = config_manager.load_config()
    print(f"   ✓ 設定読み込み成功 (URL数: {len(config.target_urls)})")
    
    # 検索条件の確認
    if hasattr(config, "search_conditions"):
        print(f"   ✓ 検索条件が存在します")
    else:
        print("   ⚠ 検索条件が存在しません（デフォルト値を使用）")
        config.search_conditions = SearchConditions()
    
    # GUIを起動
    print("2. GUIを起動中...")
    root = tk.Tk()
    root.withdraw()  # メインウィンドウは非表示
    
    try:
        print("3. 設定ダイアログを作成中...")
        dialog = SettingsDialog(root, config, config_manager)
        print("   ✓ 設定ダイアログ作成成功")
        
        print("4. 設定ダイアログを表示中...")
        print("   （ダイアログを閉じるとテストが完了します）")
        
        # ダイアログを表示（モーダル）
        result = dialog.show()
        
        if result:
            print("5. 設定が保存されました")
            print(f"   - 対象URL数: {len(result.target_urls)}")
            print(f"   - 保存先: {result.save_paths.local}")
            print(f"   - スケジュール有効: {result.schedule.enabled}")
        else:
            print("5. 設定は保存されませんでした（キャンセル）")
        
        print("=== テスト完了 ===")
        
    except Exception as e:
        print(f"   ✗ エラー: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        root.destroy()

if __name__ == "__main__":
    test_settings_dialog()

