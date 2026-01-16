"""txtLargeKikanInf_hの解析をテストするスクリプト"""

txt = "0,内閣府沖縄総合事務局,02:0,防衛省,05:0,農林水産省,16:0,国土交通省,21:3,岐阜県,21:0,国土交通省北海道開発局,22:5,岐阜県市町村共同,98:9,テスト用発注機関,99"

print("="*80)
print("txtLargeKikanInf_hの解析テスト")
print("="*80)

print(f"\n元の値: {txt}")

# :で分割
entries = txt.split(":")
print(f"\n:で分割したエントリ数: {len(entries)}")
for i, entry in enumerate(entries):
    print(f"  {i+1}. {entry}")

# 中分類「国土交通省」(value='21')の小分類を抽出
print("\n--- 中分類「国土交通省」(value='21')の小分類を抽出 ---")

target_key = "21"
options = []

for entry in entries:
    # ,で分割
    parts = entry.split(",")
    print(f"\nエントリ: {entry}")
    print(f"  パーツ数: {len(parts)}")
    print(f"  パーツ: {parts}")
    
    if len(parts) >= 3:
        # 形式: 大分類value,中分類名,中分類value,小分類名,小分類value,...
        daibunrui_value = parts[0]
        chubunrui_name = parts[1]
        chubunrui_value = parts[2]
        
        print(f"  大分類値: {daibunrui_value}")
        print(f"  中分類名: {chubunrui_name}")
        print(f"  中分類値: {chubunrui_value}")
        
        # 中分類のvalueと一致する場合
        if chubunrui_value == target_key:
            print(f"  ★ 中分類値 '{target_key}' と一致！")
            
            # 小分類のデータがある場合（parts[3]以降）
            if len(parts) >= 5:
                print(f"  小分類のデータを抽出（parts[3]以降）...")
                # 小分類名と小分類valueのペアを抽出
                for i in range(3, len(parts) - 1, 2):
                    if i + 1 < len(parts):
                        shoubunrui_name = parts[i]
                        shoubunrui_value = parts[i + 1]
                        options.append((shoubunrui_value, shoubunrui_name))
                        print(f"    小分類: '{shoubunrui_name}' -> '{shoubunrui_value}'")
            else:
                print(f"  小分類のデータがありません（parts数: {len(parts)}）")

print(f"\n抽出された小分類: {len(options)}個")
for value, text in options:
    print(f"  '{text}' -> '{value}'")
    if "東北" in text:
        print(f"      ★「東北地方整備局」を発見！")
