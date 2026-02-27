# 03 ApplicationService 整理 (Phase 3)

> 実施日: 2026-02-27

---

## 実施内容

### 1. SearchConditions.is_effectively_empty() の追加

`service.py` にあった 30 行の条件判定ロジックを
`SearchConditions` dataclass にメソッドとして移植。

**変更前**: `service.py:_has_search_conditions()` が 30 行のロジックを保持
**変更後**: `SearchConditions.is_effectively_empty()` に移動、
`_has_search_conditions()` は 2 行の委譲に縮小

### 2. テスト追加

`test_config_model.py` に 7 件のテストを追加:

- デフォルト状態 → 空
- 大分類あり → 空でない
- 工事名あり → 空でない
- 入札方式5つ全選択 → デフォルト扱い（空）
- 入札方式一部選択 → 空でない
- 予定価格あり → 空でない

## テスト結果

```
14 passed (config_model), 15 passed (application_service)
全体: 89 passed, 1 skipped, 3 deselected
```
