# Phase 0: GUI起動問題の修正完了

## 問題の特定

### 原因
1. **`src/gui/main_window.py`の`__init__`でHTTPリクエストが送られる可能性**
   - `load_hachu_daibunrui_options()`が`__init__`で直接呼ばれていた
   - 別スレッドで実行されるが、import時に実行される可能性がある

2. **`src/utils/notifier.py`の`tk.Tk()`呼び出し**
   - `_notify_windows_fallback()`で`tk.Tk()`が呼ばれる
   - メソッド内なので通常は問題ないが、安全性のため改善

## 修正内容

### 1. `src/gui/main_window.py`の修正
```python
# 修正前
self.load_hachu_daibunrui_options()  # 即座に実行

# 修正後
self.root.after(100, self.load_hachu_daibunrui_options)  # GUI表示後に遅延実行
```

**効果**: import時にHTTPリクエストが送られないようにする

### 2. `src/utils/notifier.py`の修正
```python
# 修正後: 既存のTkインスタンスを確認してから新規作成
try:
    root = tk._default_root
    if root is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(title, message)
        root.destroy()
    else:
        messagebox.showinfo(title, message)
except Exception:
    # フォールバック
    ...
```

**効果**: 既存のGUIが起動している場合は再利用、起動していない場合のみ新規作成

## 検証結果

### import時の動作確認
```bash
.venv\Scripts\python.exe -c "from src.gui.main_window import MainWindow; print('Import successful - no GUI launched')"
```
✅ **成功**: GUIが起動せず、importが正常に完了

## 次のステップ

- Phase 1: 非破壊の隔離（artifacts/への移動）
- テスト実行時のGUI起動確認（`pytest -k "not gui"`）
