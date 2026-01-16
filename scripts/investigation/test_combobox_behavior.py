"""Comboboxの動作をテストするスクリプト"""

import tkinter as tk
from tkinter import ttk

def test_combobox():
    root = tk.Tk()
    root.title("Combobox Test")
    
    # テスト1: readonly + 空文字列
    frame1 = ttk.Frame(root, padding="10")
    frame1.pack(fill=tk.X)
    ttk.Label(frame1, text="Test 1 (readonly + empty string):").pack(side=tk.LEFT, padx=5)
    var1 = tk.StringVar(value="")
    cb1 = ttk.Combobox(frame1, textvariable=var1, values=["", "北海道", "東北"], state="readonly", width=20)
    cb1.pack(side=tk.LEFT, padx=5)
    ttk.Label(frame1, text=f"Value: {var1.get()}").pack(side=tk.LEFT, padx=5)
    
    # テスト2: normal + 空文字列
    frame2 = ttk.Frame(root, padding="10")
    frame2.pack(fill=tk.X)
    ttk.Label(frame2, text="Test 2 (normal + empty string):").pack(side=tk.LEFT, padx=5)
    var2 = tk.StringVar(value="")
    cb2 = ttk.Combobox(frame2, textvariable=var2, values=["", "北海道", "東北"], state="normal", width=20)
    cb2.pack(side=tk.LEFT, padx=5)
    ttk.Label(frame2, text=f"Value: {var2.get()}").pack(side=tk.LEFT, padx=5)
    
    # テスト3: readonly + 空文字列（明示的に設定）
    frame3 = ttk.Frame(root, padding="10")
    frame3.pack(fill=tk.X)
    ttk.Label(frame3, text="Test 3 (readonly + set empty):").pack(side=tk.LEFT, padx=5)
    var3 = tk.StringVar()
    cb3 = ttk.Combobox(frame3, textvariable=var3, values=["", "北海道", "東北"], state="readonly", width=20)
    cb3.pack(side=tk.LEFT, padx=5)
    var3.set("")
    ttk.Label(frame3, text=f"Value: {var3.get()}").pack(side=tk.LEFT, padx=5)
    
    # テスト4: readonly + 空文字列（current()を使用）
    frame4 = ttk.Frame(root, padding="10")
    frame4.pack(fill=tk.X)
    ttk.Label(frame4, text="Test 4 (readonly + current(0)):").pack(side=tk.LEFT, padx=5)
    var4 = tk.StringVar()
    cb4 = ttk.Combobox(frame4, textvariable=var4, values=["", "北海道", "東北"], state="readonly", width=20)
    cb4.pack(side=tk.LEFT, padx=5)
    cb4.current(0)  # 最初の要素（空文字列）を選択
    ttk.Label(frame4, text=f"Value: {var4.get()}").pack(side=tk.LEFT, padx=5)
    
    def check_values():
        print(f"Test 1 value: '{var1.get()}'")
        print(f"Test 2 value: '{var2.get()}'")
        print(f"Test 3 value: '{var3.get()}'")
        print(f"Test 4 value: '{var4.get()}'")
        root.after(1000, check_values)
    
    root.after(100, check_values)
    root.mainloop()

if __name__ == "__main__":
    test_combobox()
