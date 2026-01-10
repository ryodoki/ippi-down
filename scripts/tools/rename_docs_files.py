"""docsディレクトリ内の日本語ファイル名を英数字名にリネームするスクリプト"""

import os
import sys
from pathlib import Path

# ファイル名マッピング（旧名: 新名）
RENAME_MAP = {
    # docs/
    "システム設計書.md": "system_design.md",
    "テスト結果比較.md": "test_results_comparison.md",
    "動作確認手順.md": "operation_check_procedure.md",
    "動作確認結果サマリー.md": "operation_check_summary.md",
    "実装タスクリスト.md": "implementation_task_list.md",
    "実装設計書.md": "implementation_design.md",
    "技術選定.md": "technology_selection.md",
    "要件定義書_レビュー版.md": "requirements_review.md",
    "要件定義書.md": "requirements.md",
    "要件定義見直し.md": "requirements_revision.md",
    "要件整合性チェック結果.md": "requirements_consistency_check.md",
    "設定機能要件定義書.md": "settings_requirements.md",
    # docs/dev/
    "調査手順書.md": "investigation_procedure.md",
}

def rename_files(base_dir: Path):
    """ファイルをリネーム"""
    renamed = []
    
    for old_name, new_name in RENAME_MAP.items():
        # docs/配下を検索
        old_path = base_dir / old_name
        if old_path.exists():
            new_path = base_dir / new_name
            if new_path.exists():
                print(f"  [SKIP] {old_name} -> {new_name} (既に存在)")
                continue
            old_path.rename(new_path)
            renamed.append((old_name, new_name, str(old_path.parent)))
            print(f"  [RENAMED] {old_name} -> {new_name}")
        
        # docs/dev/配下を検索
        old_path = base_dir / "dev" / old_name
        if old_path.exists():
            new_path = base_dir / "dev" / new_name
            if new_path.exists():
                print(f"  [SKIP] dev/{old_name} -> dev/{new_name} (既に存在)")
                continue
            old_path.rename(new_path)
            renamed.append((f"dev/{old_name}", f"dev/{new_name}", str(old_path.parent)))
            print(f"  [RENAMED] dev/{old_name} -> dev/{new_name}")
    
    return renamed

if __name__ == "__main__":
    # プロジェクトルートに移動
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    
    docs_dir = project_root / "docs"
    
    if not docs_dir.exists():
        print(f"エラー: {docs_dir} が見つかりません")
        sys.exit(1)
    
    print(f"docsディレクトリ: {docs_dir}")
    print("ファイルをリネームします...")
    print()
    
    renamed = rename_files(docs_dir)
    
    print()
    print(f"リネーム完了: {len(renamed)} ファイル")
    print()
    print("リネームされたファイル:")
    for old, new, parent in renamed:
        print(f"  {old} -> {new}")
