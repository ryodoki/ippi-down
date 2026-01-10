"""設定の読み込み・保存テスト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig, SearchConditions

def test_config():
    """設定の読み込み・保存テスト"""
    print("=== 設定テスト開始 ===")
    
    # 設定を読み込み
    print("1. 設定ファイルを読み込み中...")
    config_manager = ConfigManager()
    config = config_manager.load_config()
    print("   [OK] 設定読み込み成功")
    print(f"   - 対象URL数: {len(config.target_urls)}")
    
    # 検索条件の確認
    if hasattr(config, "search_conditions"):
        sc = config.search_conditions
        print("   [OK] 検索条件が存在します")
        print(f"   - 工事名: {sc.koji_name}")
        print(f"   - 入札契約方式数: {len(sc.contract_types)}")
    else:
        print("   [WARN] 検索条件が存在しません")
        config.search_conditions = SearchConditions()
    
    # 設定を保存
    print("2. 設定ファイルを保存中...")
    if config_manager.save_config(config):
        print("   [OK] 設定保存成功")
    else:
        print("   [ERROR] 設定保存失敗")
    
    # 再度読み込んで確認
    print("3. 設定ファイルを再読み込み中...")
    config2 = config_manager.load_config()
    if hasattr(config2, "search_conditions"):
        print("   [OK] 検索条件が保存・読み込みできました")
    else:
        print("   [ERROR] 検索条件の保存・読み込みに失敗")
    
    print("=== テスト完了 ===")

if __name__ == "__main__":
    test_config()

