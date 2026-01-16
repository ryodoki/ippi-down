"""小分類が存在する中分類を探すスクリプト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from bs4 import BeautifulSoup

def main():
    logger = Logger(LoggingConfig(level="INFO"))
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    normalized_url = scraper._normalize_search_url(url)
    
    try:
        # 1. 初回GET
        initial_soup = scraper.fetch_page(normalized_url)
        if not initial_soup:
            logger.error("初回GETに失敗しました")
            return
        
        # 2. すべての大分類を試す
        daibunrui_dropdown = initial_soup.find("select", {"name": "drpTopKikanInf"})
        if not daibunrui_dropdown:
            logger.error("大分類のドロップダウンが見つかりません")
            return
        
        daibunrui_options = []
        for option in daibunrui_dropdown.find_all("option"):
            text = option.get_text().strip()
            value = option.get("value", "")
            if text and value != "-1":
                daibunrui_options.append((value, text))
        
        logger.info(f"大分類の数: {len(daibunrui_options)}")
        
        # 各大分類を試す
        for daibunrui_value, daibunrui_text in daibunrui_options:
            logger.info("")
            logger.info("=" * 80)
            logger.info(f"大分類: {daibunrui_text} (value={daibunrui_value})")
            logger.info("=" * 80)
            
            # 大分類を選択
            form_data = scraper._get_all_hidden_inputs(initial_soup)
            form_data["__EVENTTARGET"] = "drpTopKikanInf"
            form_data["__EVENTARGUMENT"] = ""
            form_data["drpTopKikanInf"] = daibunrui_value
        
        response1 = http_client.post(normalized_url, data=form_data)
        if response1.encoding:
            response1.encoding = response1.apparent_encoding or 'utf-8'
        else:
            response1.encoding = 'utf-8'
        
        soup1 = BeautifulSoup(response1.content, "lxml", from_encoding=response1.encoding)
        
        # 3. すべての中分類を取得
        dropdown = soup1.find("select", {"name": "drpLargeKikanInf2"})
        if not dropdown:
            logger.error("中分類のドロップダウンが見つかりません")
            return
        
        chubunrui_options = []
        for option in dropdown.find_all("option"):
            text = option.get_text().strip()
            value = option.get("value", "")
            if text and value != "-1":
                chubunrui_options.append((value, text))
        
        logger.info(f"中分類の数: {len(chubunrui_options)}")
        
        # 4. 各中分類を選択して、小分類が存在するか確認
        for i, (chubunrui_value, chubunrui_text) in enumerate(chubunrui_options[:5]):  # 最初の5件をテスト
            logger.info("")
            logger.info(f"中分類{i+1}: {chubunrui_text} (value={chubunrui_value})")
            
            form_data2 = scraper._get_all_hidden_inputs(soup1)
            form_data2["__EVENTTARGET"] = "drpLargeKikanInf2"
            form_data2["__EVENTARGUMENT"] = ""
            form_data2["drpTopKikanInf"] = daibunrui_value
            form_data2["drpLargeKikanInf2"] = chubunrui_value
            
            response2 = http_client.post(normalized_url, data=form_data2)
            if response2.encoding:
                response2.encoding = response2.apparent_encoding or 'utf-8'
            else:
                response2.encoding = 'utf-8'
            
            soup2 = BeautifulSoup(response2.content, "lxml", from_encoding=response2.encoding)
            
            # 小分類のドロップダウンを確認
            dropdown_shoubunrui = soup2.find("select", {"name": "drpMiddleKikanInf"})
            if dropdown_shoubunrui:
                options = dropdown_shoubunrui.find_all("option")
                valid_options = [opt for opt in options if opt.get("value", "") != "-1"]
                if len(valid_options) > 0:
                    logger.info(f"  ✓ 小分類が存在します: {len(valid_options)}件")
                    for j, opt in enumerate(valid_options[:5]):
                        logger.info(f"    {j+1}: {opt.get_text().strip()} (value={opt.get('value', '')})")
                    
                    # 最初の小分類を選択して細分類を確認
                    if valid_options:
                        first_shoubunrui_value = valid_options[0].get("value", "")
                        first_shoubunrui_text = valid_options[0].get_text().strip()
                        logger.info(f"  小分類「{first_shoubunrui_text}」を選択して細分類を確認...")
                        
                        form_data3 = scraper._get_all_hidden_inputs(soup2)
                        form_data3["__EVENTTARGET"] = "drpMiddleKikanInf"
                        form_data3["__EVENTARGUMENT"] = ""
                        form_data3["drpTopKikanInf"] = daibunrui_value
                        form_data3["drpLargeKikanInf2"] = chubunrui_value
                        form_data3["drpMiddleKikanInf"] = first_shoubunrui_value
                        
                        response3 = http_client.post(normalized_url, data=form_data3)
                        if response3.encoding:
                            response3.encoding = response3.apparent_encoding or 'utf-8'
                        else:
                            response3.encoding = 'utf-8'
                        
                        soup3 = BeautifulSoup(response3.content, "lxml", from_encoding=response3.encoding)
                        
                        # 細分類のドロップダウンを確認
                        dropdown_saibunrui = soup3.find("select", {"name": "drpSmallKikanInf"})
                        if dropdown_saibunrui:
                            options_saibunrui = dropdown_saibunrui.find_all("option")
                            valid_saibunrui = [opt for opt in options_saibunrui if opt.get("value", "") != "-1"]
                            if len(valid_saibunrui) > 0:
                                logger.info(f"    ✓ 細分類が存在します: {len(valid_saibunrui)}件")
                                for k, opt in enumerate(valid_saibunrui[:5]):
                                    logger.info(f"      {k+1}: {opt.get_text().strip()} (value={opt.get('value', '')})")
                            else:
                                logger.info(f"    ✗ 細分類は存在しません")
                else:
                    logger.info(f"  ✗ 小分類は存在しません")
        
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

