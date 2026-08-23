# ダウンロード仕様 乖離調査レポート

生成日時: 2026-06-18T00:10:13.222280
設定: `C:\Users\ryout\Workspaces\ippi-down\config\config.yaml`

## 現行設定サマリー

| 項目 | 値 |
|------|-----|
| save_paths.local | `C:/Users/ryout/Downloads` |
| enable_agency_root_folders | `False` |
| use_subfolders | `True` |
| run_subfolder_mode | `none` |
| naming_rule | `{category}_{title}_{date}_{index}` |
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

- **桂巣トンネル外照明設備工事** → `C:\Users\ryout\Downloads\国の機関_国土交通省_東北地方整備局_桂巣トンネル外照明設備工事\入札公告_入札公告_20260201_0.pdf`
- **猪ノ鼻トンネル外照明設備工事** → `C:\Users\ryout\Downloads\国の機関_国土交通省_東北地方整備局_猪ノ鼻トンネル外照明設備工事\設計書_設計書_20260618_1.pdf`

## 乖離一覧

### GAP-004 [P0] 保存先がユーザー想定と乖離（深い階層・単一フォルダ） (FR-012)
- **期待**: 指定フォルダ直下または分かりやすいサブフォルダ
- **実態**: 親ディレクトリ数=1, 例=['C:\\Users\\ryout\\Downloads\\発注機関\\国の機関\\国土交通省\\東北地方整備局\\unknown\\工事_入札公告等']
- **根拠**: logs/app.log 保存先行

### GAP-005 [P1] 重複スキップが多く、新規取得件数が少ない (FR-008)
- **期待**: 初回は全件保存、再実行時のみスキップ
- **実態**: スキップ=12, 新規完了=2, 理由={'url': 8, 'file_exists': 4}
- **根拠**: index ベース命名 + URL 履歴により同一パスに既存ファイル


## 改善方針（実装前）

1. **保存戦略の統一**: 発注機関フォルダ ON 時も `koji_name`（工事名）サブフォルダを維持する。`path_builder` に `koji_name` 階層を追加し、`use_subfolders` と排他にしない。
2. **命名規則のデフォルト修正**: `naming_rule` デフォルトを `{category}_{title}_{date}_{index}{ext}` に戻し、設定画面にプレビューを表示（FR-SET-010）。
3. **設定の明示化**: `config.example.yaml` / GUI 保存時に `enable_agency_root_folders` を必ず書き出し、README のデフォルト記述とコードデフォルトを一致させる（OFF 推奨）。
4. **完了 UX**: 完了メッセージに保存先ルート＋新規保存ファイル一覧（最大5件）を表示。スキップ理由別件数を GUI ログに出力。
5. **重複判定の見直し**: 同一フォルダ内の index 衝突を避けるため、パスに `koji_name` または `AnkenKanriNo` を含める。URL スキップ時は『既存ファイルのパス』をログに出す。
6. **メタデータ日付**: `{date}` は公告日等の HTML メタデータを優先し、無い場合のみ実行日。
7. **ドキュメント更新**: requirement_gap_report / TRACEABILITY を再監査し、本レポートを正とする。
8. **回帰テスト**: 発注機関 ON/OFF × naming_rule 組み合わせの統合テストを追加。