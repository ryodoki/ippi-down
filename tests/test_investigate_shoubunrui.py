"""小分類と細分類の取得方法を詳しく調査するスクリプト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from bs4 import BeautifulSoup
import re

def main():
    logger = Logger(LoggingConfig(level="DEBUG"))
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    normalized_url = scraper._normalize_search_url(url)
    
    try:
        # 1. 初回GET
        logger.info("=" * 80)
        logger.info("ステップ1: 初回GET - txtLargeKikanInf_hのデータ形式を確認")
        logger.info("=" * 80)
        initial_soup = scraper.fetch_page(normalized_url)
        if not initial_soup:
            logger.error("初回GETに失敗しました")
            return
        
        hidden_inputs = scraper._get_all_hidden_inputs(initial_soup)
        txtLargeKikanInf_h_initial = hidden_inputs.get("txtLargeKikanInf_h", "")
        logger.info(f"初回GET時のtxtLargeKikanInf_h: {txtLargeKikanInf_h_initial[:500]}")
        
        # データ形式を解析
        if txtLargeKikanInf_h_initial:
            entries = txtLargeKikanInf_h_initial.split(":")
            logger.info(f"エントリ数: {len(entries)}")
            for i, entry in enumerate(entries[:5]):
                parts = entry.split(",")
                logger.info(f"  エントリ{i+1}: {len(parts)}個のパーツ")
                logger.info(f"    パーツ: {parts}")
                if len(parts) >= 3:
                    logger.info(f"    大分類value: {parts[0]}, 中分類名: {parts[1]}, 中分類value: {parts[2]}")
                    if len(parts) > 3:
                        logger.info(f"    追加データ: {parts[3:]}")
        
        # 2. 大分類を選択（国の機関 = value="0"）
        logger.info("")
        logger.info("=" * 80)
        logger.info("ステップ2: 大分類「国の機関」を選択")
        logger.info("=" * 80)
        form_data = scraper._get_all_hidden_inputs(initial_soup)
        form_data["__EVENTTARGET"] = "drpTopKikanInf"
        form_data["__EVENTARGUMENT"] = ""
        form_data["drpTopKikanInf"] = "0"
        
        response1 = http_client.post(normalized_url, data=form_data)
        if response1.encoding:
            response1.encoding = response1.apparent_encoding or 'utf-8'
        else:
            response1.encoding = 'utf-8'
        
        soup1 = BeautifulSoup(response1.content, "lxml", from_encoding=response1.encoding)
        hidden_inputs1 = scraper._get_all_hidden_inputs(soup1)
        txtLargeKikanInf_h_1 = hidden_inputs1.get("txtLargeKikanInf_h", "")
        logger.info(f"大分類選択後のtxtLargeKikanInf_h: {txtLargeKikanInf_h_1[:500]}")
        
        # 3. 中分類を選択（内閣府沖縄総合事務局 = value="02"）
        logger.info("")
        logger.info("=" * 80)
        logger.info("ステップ3: 中分類「内閣府沖縄総合事務局」を選択")
        logger.info("=" * 80)
        form_data2 = scraper._get_all_hidden_inputs(soup1)
        form_data2["__EVENTTARGET"] = "drpLargeKikanInf2"
        form_data2["__EVENTARGUMENT"] = ""
        form_data2["drpTopKikanInf"] = "0"
        form_data2["drpLargeKikanInf2"] = "02"
        
        response2 = http_client.post(normalized_url, data=form_data2)
        if response2.encoding:
            response2.encoding = response2.apparent_encoding or 'utf-8'
        else:
            response2.encoding = 'utf-8'
        
        response_text2 = response2.text
        soup2 = BeautifulSoup(response_text2, "lxml", from_encoding=response2.encoding)
        
        # POSTレスポンスを保存
        with open("test_investigate_response.html", "w", encoding="utf-8") as f:
            f.write(response_text2)
        logger.info("✓ POSTレスポンスを保存: test_investigate_response.html")
        
        # hidden inputを確認
        hidden_inputs2 = scraper._get_all_hidden_inputs(soup2)
        logger.info("")
        logger.info("中分類選択後のhidden input（Kikan関連）:")
        for key, value in hidden_inputs2.items():
            if "Kikan" in key or "Lg" in key:
                logger.info(f"  {key}: {value[:300] if len(value) > 300 else value}")
        
        # txtLargeKikanInf_hのデータ形式を詳しく解析
        txtLargeKikanInf_h_2 = hidden_inputs2.get("txtLargeKikanInf_h", "")
        if txtLargeKikanInf_h_2:
            logger.info("")
            logger.info("txtLargeKikanInf_hのデータ形式を解析:")
            entries = txtLargeKikanInf_h_2.split(":")
            logger.info(f"  エントリ数: {len(entries)}")
            for i, entry in enumerate(entries):
                parts = entry.split(",")
                logger.info(f"  エントリ{i+1}: {len(parts)}個のパーツ")
                logger.info(f"    内容: {entry[:200]}")
                if len(parts) >= 3:
                    logger.info(f"    大分類value: {parts[0]}, 中分類名: {parts[1]}, 中分類value: {parts[2]}")
                    if len(parts) > 3:
                        logger.info(f"    追加データ（小分類？）: {parts[3:]}")
                        # 小分類のデータがあるか確認
                        if len(parts) >= 5:
                            logger.info(f"    → 小分類の可能性: 名前={parts[3]}, value={parts[4]}")
        
        # 4. 小分類のドロップダウンを確認
        logger.info("")
        logger.info("=" * 80)
        logger.info("ステップ4: 小分類ドロップダウンの確認")
        logger.info("=" * 80)
        dropdown = soup2.find("select", {"name": "drpMiddleKikanInf"})
        if dropdown:
            options = dropdown.find_all("option")
            logger.info(f"HTMLから小分類のオプション数: {len(options)}")
            for i, option in enumerate(options[:10]):
                text = option.get_text().strip()
                value = option.get("value", "")
                logger.info(f"  {i+1}: value={value}, text={text}")
        else:
            logger.warning("小分類のドロップダウンが見つかりません")
        
        # 5. JavaScriptコードを詳しく確認
        logger.info("")
        logger.info("=" * 80)
        logger.info("ステップ5: JavaScriptコードの詳細確認")
        logger.info("=" * 80)
        
        # setListItemSubの呼び出しを探す
        if "setListItemSub" in response_text2:
            logger.info("✓ setListItemSubが含まれています")
            
            # すべてのsetListItemSub呼び出しを探す
            pattern_all = r"setListItemSub\s*\([^)]+\)"
            matches_all = re.findall(pattern_all, response_text2)
            logger.info(f"setListItemSub呼び出し総数: {len(matches_all)}")
            for i, match in enumerate(matches_all[:10]):
                logger.info(f"  {i+1}: {match[:200]}")
            
            # drpMiddleKikanInfに関連するsetListItemSubを探す
            pattern_middle = r"setListItemSub\s*\(\s*['\"]drpMiddleKikanInf['\"][^)]+\)"
            matches_middle = re.findall(pattern_middle, response_text2)
            logger.info(f"drpMiddleKikanInf関連のsetListItemSub: {len(matches_middle)}件")
            for i, match in enumerate(matches_middle):
                logger.info(f"  {i+1}: {match}")
        
        # createListItem2の呼び出しを確認
        if "createListItem2" in response_text2:
            logger.info("")
            logger.info("✓ createListItem2が含まれています")
            pattern = r"createListItem2\s*\([^)]+\)"
            matches = re.findall(pattern, response_text2)
            logger.info(f"createListItem2呼び出し数: {len(matches)}")
            for i, match in enumerate(matches):
                logger.info(f"  {i+1}: {match}")
        
        # 6. 実際のブラウザの動作をシミュレート: txtLargeKikanInf_hから中分類value="02"に基づいて小分類を抽出
        logger.info("")
        logger.info("=" * 80)
        logger.info("ステップ6: Common.jsのgetListItemStrロジックをシミュレート")
        logger.info("=" * 80)
        if txtLargeKikanInf_h_2:
            # getListItemStr(targetListItemStr, targetListKey)のロジック
            # targetListItemStrを:で分割し、各エントリを,で分割して、targetListKey（中分類のvalue）と一致するエントリを抽出
            target_key = "02"  # 内閣府沖縄総合事務局のvalue
            entries = txtLargeKikanInf_h_2.split(":")
            options = []
            for entry in entries:
                parts = entry.split(",")
                if len(parts) >= 3 and parts[2] == target_key:  # 中分類のvalueと一致
                    # 小分類のデータがある場合
                    if len(parts) >= 5:
                        # 小分類名と小分類valueのペアを抽出
                        for i in range(3, len(parts) - 1, 2):
                            if i + 1 < len(parts):
                                shoubunrui_name = parts[i]
                                shoubunrui_value = parts[i + 1]
                                options.append((shoubunrui_value, shoubunrui_name))
                                logger.info(f"  小分類を発見: value={shoubunrui_value}, name={shoubunrui_name}")
            
            if options:
                logger.info(f"✓ getListItemStrロジックで{len(options)}個の小分類を抽出しました")
            else:
                logger.warning("getListItemStrロジックで小分類を抽出できませんでした")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("調査完了")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"調査エラー: {str(e)}", exc_info=True)
    finally:
        http_client.close()

if __name__ == "__main__":
    main()

