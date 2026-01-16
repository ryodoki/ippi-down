"""中分類選択後のPOSTレスポンスを詳しく確認するテストスクリプト"""

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
        logger.info("=" * 60)
        logger.info("ステップ1: 初回GET")
        logger.info("=" * 60)
        initial_soup = scraper.fetch_page(normalized_url)
        if not initial_soup:
            logger.error("初回GETに失敗しました")
            return
        
        # 2. 大分類を選択（国の機関 = value="0"）
        logger.info("")
        logger.info("=" * 60)
        logger.info("ステップ2: 大分類「国の機関」を選択")
        logger.info("=" * 60)
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
        logger.info("✓ 大分類選択後のPOST完了")
        
        # 3. 中分類を選択（内閣府沖縄総合事務局 = value="02"）
        logger.info("")
        logger.info("=" * 60)
        logger.info("ステップ3: 中分類「内閣府沖縄総合事務局」を選択")
        logger.info("=" * 60)
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
        with open("test_chubunrui_post_response.html", "w", encoding="utf-8") as f:
            f.write(response_text2)
        logger.info("✓ POSTレスポンスを保存: test_chubunrui_post_response.html")
        
        # 4. hidden inputを確認
        logger.info("")
        logger.info("=" * 60)
        logger.info("ステップ4: hidden inputの確認")
        logger.info("=" * 60)
        hidden_inputs = scraper._get_all_hidden_inputs(soup2)
        for key, value in hidden_inputs.items():
            if "Kikan" in key or "Lg" in key:
                logger.info(f"{key}: {value[:300] if len(value) > 300 else value}")
        
        # 5. 小分類のドロップダウンを確認
        logger.info("")
        logger.info("=" * 60)
        logger.info("ステップ5: 小分類ドロップダウンの確認")
        logger.info("=" * 60)
        dropdown = soup2.find("select", {"name": "drpMiddleKikanInf"})
        if dropdown:
            options = dropdown.find_all("option")
            logger.info(f"HTMLから小分類のオプション数: {len(options)}")
            for i, option in enumerate(options[:10]):
                text = option.get_text().strip()
                value = option.get("value", "")
                logger.info(f"  {i+1}: value={value}, text={text}")
        
        # 6. JavaScriptコードを確認
        logger.info("")
        logger.info("=" * 60)
        logger.info("ステップ6: JavaScriptコードの確認")
        logger.info("=" * 60)
        
        # setListItemSubの呼び出しを探す
        if "setListItemSub" in response_text2:
            logger.info("✓ setListItemSubが含まれています")
            
            # パターン1: setListItemSub('ID', VAR)
            pattern1 = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
            matches1 = re.findall(pattern1, response_text2)
            logger.info(f"setListItemSub呼び出し（変数形式）: {len(matches1)}件")
            for i, (id_val, var_name) in enumerate(matches1[:10]):
                logger.info(f"  {i+1}: ID={id_val}, VAR={var_name}")
                # 変数定義を探す
                var_pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\];"
                var_matches = re.findall(var_pattern, response_text2, re.DOTALL)
                if var_matches:
                    logger.info(f"    ✓ 変数定義が見つかりました: {var_name}")
                    content = var_matches[0]
                    logger.info(f"    内容の長さ: {len(content)}文字")
                    logger.info(f"    内容（最初の500文字）: {content[:500]}")
                    # value:text形式のエントリを抽出
                    items = re.findall(r"['\"]([^'\"]+)['\"]", content)
                    logger.info(f"    抽出されたアイテム数: {len(items)}")
                    for j, item in enumerate(items[:10]):
                        logger.info(f"      {j+1}: {item}")
            
            # パターン2: setListItemSub('ID', [...])
            pattern2 = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*\[(.*?)\]\s*\)"
            matches2 = re.findall(pattern2, response_text2, re.DOTALL)
            logger.info(f"setListItemSub呼び出し（配列形式）: {len(matches2)}件")
            for i, (id_val, list_content) in enumerate(matches2[:10]):
                logger.info(f"  {i+1}: ID={id_val}")
                logger.info(f"    内容の長さ: {len(list_content)}文字")
                logger.info(f"    内容（最初の500文字）: {list_content[:500]}")
        
        # 7. createListItem2の呼び出しを確認
        logger.info("")
        logger.info("=" * 60)
        logger.info("ステップ7: createListItem2の呼び出し確認")
        logger.info("=" * 60)
        if "createListItem2" in response_text2:
            logger.info("✓ createListItem2が含まれています")
            pattern = r"createListItem2\s*\([^)]+\)"
            matches = re.findall(pattern, response_text2)
            logger.info(f"createListItem2呼び出し数: {len(matches)}")
            for i, match in enumerate(matches[:5]):
                logger.info(f"  {i+1}: {match}")
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("テスト完了")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"テストエラー: {str(e)}", exc_info=True)
    finally:
        http_client.close()

if __name__ == "__main__":
    main()

