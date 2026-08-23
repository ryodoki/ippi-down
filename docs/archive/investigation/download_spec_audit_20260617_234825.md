# ダウンロード仕様 乖離調査レポート

生成日時: 2026-06-17T23:48:25.679583
設定: `C:\Users\ryout\Workspaces\ippi-down\config\config.yaml`

## 現行設定サマリー

| 項目 | 値 |
|------|-----|
| save_paths.local | `C:/Users/ryout/Downloads` |
| enable_agency_root_folders | `True` |
| use_subfolders | `True` |
| run_subfolder_mode | `none` |
| naming_rule | `{index}` |
| date_partition | `none` |

## ログ・履歴からの観測

- 直近ログ: {
  "summary_line": "ppi_file_downloader - INFO - ダウンロード完了: 成功=2, 失敗=0, スキップ=12",
  "save_path_samples": [
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\0.pdf",
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\1.pdf",
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\2.pdf",
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\3.pdf",
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\4.pdf"
  ],
  "save_path_count": 14,
  "unique_parent_dirs": [
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等"
  ],
  "unique_parent_dir_count": 1,
  "completed_files": 2,
  "skip_count": 12,
  "skip_reasons": {
    "url": 8,
    "file_exists": 4
  },
  "filename_samples": [
    "0.pdf",
    "1.pdf",
    "2.pdf",
    "3.pdf",
    "4.pdf",
    "5.pdf",
    "6.pdf",
    "7.pdf"
  ]
}
- 履歴: {
  "total_records": 396,
  "recent_analyzed": 200,
  "naming_style_counts": {
    "index_only": 200
  },
  "sample_paths": [
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\62.pdf",
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\63.pdf",
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\64.pdf",
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\1.pdf",
    "C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等\\5.pdf"
  ],
  "top_parent_folder_names": [
    [
      "工事_入札公告等",
      145
    ],
    [
      "国の機関_国土交通省_宮崎２１８号_越次トンネル新設工事",
      5
    ],
    [
      "国の機関_国土交通省_熊本５７号網津長浜トンネル（長浜工区）新設工事",
      5
    ],
    [
      "国の機関_国土交通省_令和７年度_三遠南信１号トンネル工事",
      5
    ],
    [
      "国の機関_国土交通省_関東地方整備局_横浜湘南道路トンネルその４工事",
      4
    ],
    [
      "国の機関_国土交通省_令和７年度_１号藤枝ＢＰ原トンネル工事",
      4
    ],
    [
      "国の機関_国土交通省_関東地方整備局_Ｒ５国道２０号新笹子トンネル関連改良工事",
      3
    ],
    [
      "国の機関_国土交通省_関東地方整備局_Ｒ６国道２４６号新善波トンネル厚木坑口復旧（その３）工事",
      3
    ]
  ]
}

## パスシミュレーション

- **桂巣トンネル外照明設備工事** → `C:\Users\ryout\Downloads\発注機関\国の機関\国土交通省\東北地方整備局\unknown\工事_入札公告等\0.pdf`
- **猪ノ鼻トンネル外照明設備工事** → `C:\Users\ryout\Downloads\発注機関\国の機関\国土交通省\東北地方整備局\unknown\工事_入札公告等\1.pdf`

## 乖離一覧

### GAP-001 [P0] 発注機関フォルダON時に工事件ごとのサブフォルダが消える (FR-013)
- **期待**: メタデータ（工事名等）に基づき分類保存（README: トンネル/工事名フォルダ）
- **実態**: 全工事のファイルが同一フォルダ（…/工事_入札公告等/）にフラット配置
- **根拠**: downloader.py: build_save_dir_fn 使用時 use_subfolders/generate_folder_name をスキップ

### GAP-002 [P0] 命名規則が連番のみで文書種別・工事名が失われる (FR-009)
- **期待**: テンプレ例: {category}_{title}_{date}_{index} で識別可能なファイル名
- **実態**: naming_rule='{index}' → 0.pdf, 1.pdf 等
- **根拠**: config.naming_rule, history naming styles: {'index_only': 200}

### GAP-003 [P1] 発注機関フォルダのデフォルトが README とコードで不一致 (FR-012/FR-SET)
- **期待**: README: デフォルト OFF
- **実態**: SavePaths.enable_agency_root_folders コードデフォルト=True, 現設定=True
- **根拠**: config_model.py vs README.md

### GAP-004 [P0] 保存先がユーザー想定と乖離（深い階層・単一フォルダ） (FR-012)
- **期待**: 指定フォルダ直下または分かりやすいサブフォルダ
- **実態**: 親ディレクトリ数=1, 例=['C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等']
- **根拠**: logs/app.log 保存先行

### GAP-005 [P1] 重複スキップが多く、新規取得件数が少ない (FR-008)
- **期待**: 初回は全件保存、再実行時のみスキップ
- **実態**: スキップ=12, 新規完了=2, 理由={'url': 8, 'file_exists': 4}
- **根拠**: index ベース命名 + URL 履歴により同一パスに既存ファイル

### GAP-006 [P2] 命名の {date} が HTML メタデータではなく実行日 (FR-009)
- **期待**: 公告日等のメタデータ日付を優先
- **実態**: naming.py _build_context_from_search_conditions で datetime.now() を使用
- **根拠**: src/core/naming.py

### GAP-007 [P1] config.yaml に save_paths 拡張項目が未記載 (FR-019)
- **期待**: 有効な設定が YAML に明示され GUI と一致
- **実態**: enable_agency_root_folders 等が未記載のためコードデフォルト(True)が暗黙適用
- **根拠**: config/config.yaml

### GAP-008 [P2] 完了サマリーが保存先・スキップ内訳を十分に示さない (FR-005)
- **期待**: 成功件数と実保存ファイル数の一致、保存先フォルダの明示
- **実態**: サマリー例: ppi_file_downloader - INFO - ダウンロード完了: 成功=2, 失敗=0, スキップ=12
- **根拠**: service.py 完了メッセージ（改善一部済み）

### GAP-009 [P2] 要件トレーサビリティ文書が実態と乖離 (—)
- **期待**: requirement_gap_report.md が現状を反映
- **実態**: FR-013/FR-009 を OK と記載しているが、発注機関モード+index命名で仕様未達
- **根拠**: docs/requirement_gap_report.md


## 改善方針（実装前）

1. **保存戦略の統一**: 発注機関フォルダ ON 時も `koji_name`（工事名）サブフォルダを維持する。`path_builder` に `koji_name` 階層を追加し、`use_subfolders` と排他にしない。
2. **命名規則のデフォルト修正**: `naming_rule` デフォルトを `{category}_{title}_{date}_{index}{ext}` に戻し、設定画面にプレビューを表示（FR-SET-010）。
3. **設定の明示化**: `config.example.yaml` / GUI 保存時に `enable_agency_root_folders` を必ず書き出し、README のデフォルト記述とコードデフォルトを一致させる（OFF 推奨）。
4. **完了 UX**: 完了メッセージに保存先ルート＋新規保存ファイル一覧（最大5件）を表示。スキップ理由別件数を GUI ログに出力。
5. **重複判定の見直し**: 同一フォルダ内の index 衝突を避けるため、パスに `koji_name` または `AnkenKanriNo` を含める。URL スキップ時は『既存ファイルのパス』をログに出す。
6. **メタデータ日付**: `{date}` は公告日等の HTML メタデータを優先し、無い場合のみ実行日。
7. **ドキュメント更新**: requirement_gap_report / TRACEABILITY を再監査し、本レポートを正とする。
8. **回帰テスト**: 発注機関 ON/OFF × naming_rule 組み合わせの統合テストを追加。