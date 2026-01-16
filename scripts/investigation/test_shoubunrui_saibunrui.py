"""小分類と細分類の取得テストスクリプト"""

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
    logger = Logger(LoggingConfig(level="DEBUG"))
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    
    try:
        # 1. 大分類のオプションを取得
        logger.info("=" * 60)
        logger.info("テスト1: 大分類のオプション取得")
        logger.info("=" * 60)
        daibunrui_options = scraper.get_hachu_daibunrui_options(url)
        logger.info(f"大分類オプション数: {len(daibunrui_options)}")
        for i, opt in enumerate(daibunrui_options[:10]):
            logger.info(f"  {i+1}: {opt}")
        
        if not daibunrui_options:
            logger.error("大分類のオプションが取得できませんでした")
            return
        
        # 2. 大分類を選択して中分類を取得
        logger.info("")
        logger.info("=" * 60)
        logger.info("テスト2: 大分類「国の機関」を選択して中分類を取得")
        logger.info("=" * 60)
        daibunrui_value = "国の機関"
        chubunrui_options = scraper.get_hachu_chubunrui_options(url, daibunrui_value)
        logger.info(f"中分類オプション数: {len(chubunrui_options)}")
        for i, opt in enumerate(chubunrui_options[:10]):
            logger.info(f"  {i+1}: {opt}")
        
        if not chubunrui_options:
            logger.error("中分類のオプションが取得できませんでした")
            return
        
        # 3. 中分類を選択して小分類を取得
        logger.info("")
        logger.info("=" * 60)
        logger.info("テスト3: 中分類を選択して小分類を取得")
        logger.info("=" * 60)
        
        # 最初の中分類を選択（「▽中分類」を除く）
        chubunrui_value = None
        for opt in chubunrui_options:
            if opt != "▽中分類" and opt:
                chubunrui_value = opt
                break
        
        if not chubunrui_value:
            logger.error("有効な中分類が見つかりませんでした")
            return
        
        logger.info(f"選択した中分類: {chubunrui_value}")
        shoubunrui_options = scraper.get_hachu_shoubunrui_options(url, daibunrui_value, chubunrui_value)
        logger.info(f"小分類オプション数: {len(shoubunrui_options)}")
        for i, opt in enumerate(shoubunrui_options[:20]):
            logger.info(f"  {i+1}: {opt}")
        
        if not shoubunrui_options or len(shoubunrui_options) <= 1:
            logger.warning("小分類のオプションが取得できませんでした（▽小分類のみ）")
            logger.info("POSTレスポンスの詳細を確認します...")
            
            # POSTレスポンスを確認
            normalized_url = scraper._normalize_search_url(url)
            initial_soup = scraper.fetch_page(normalized_url)
            if initial_soup:
                # 大分類のvalueを取得
                parent_value1 = scraper._get_dropdown_value_from_text(initial_soup, "drpTopKikanInf", daibunrui_value)
                if parent_value1:
                    # 大分類を選択してPOST
                    form_data = scraper._get_all_hidden_inputs(initial_soup)
                    form_data["__EVENTTARGET"] = "drpTopKikanInf"
                    form_data["__EVENTARGUMENT"] = ""
                    form_data["drpTopKikanInf"] = parent_value1
                    
                    response = http_client.post(normalized_url, data=form_data)
                    if response.encoding:
                        response.encoding = response.apparent_encoding or 'utf-8'
                    else:
                        response.encoding = 'utf-8'
                    
                    soup_after_daibunrui = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
                    
                    # 中分類のvalueを取得
                    parent_value2 = scraper._get_dropdown_value_from_text(soup_after_daibunrui, "drpLargeKikanInf2", chubunrui_value)
                    if parent_value2:
                        # 中分類を選択してPOST
                        form_data2 = scraper._get_all_hidden_inputs(soup_after_daibunrui)
                        form_data2["__EVENTTARGET"] = "drpLargeKikanInf2"
                        form_data2["__EVENTARGUMENT"] = ""
                        form_data2["drpTopKikanInf"] = parent_value1
                        form_data2["drpLargeKikanInf2"] = parent_value2
                        
                        response2 = http_client.post(normalized_url, data=form_data2)
                        if response2.encoding:
                            response2.encoding = response2.apparent_encoding or 'utf-8'
                        else:
                            response2.encoding = 'utf-8'
                        
                        response_text2 = response2.text
                        
                        # POSTレスポンスを保存
                        with open("test_shoubunrui_response.html", "w", encoding="utf-8") as f:
                            f.write(response_text2)
                        logger.info("POSTレスポンスを保存しました: test_shoubunrui_response.html")
                        
                        # hidden inputを確認
                        soup_after_chubunrui = BeautifulSoup(response_text2, "lxml", from_encoding=response2.encoding)
                        hidden_inputs = scraper._get_all_hidden_inputs(soup_after_chubunrui)
                        
                        # txtLargeKikanInf_hなどのhidden inputを確認
                        for key, value in hidden_inputs.items():
                            if "KikanInf" in key or "Kikan" in key:
                                logger.info(f"hidden input: {key} = {value[:200] if len(value) > 200 else value}")
                        
                        # 小分類のドロップダウンを確認
                        dropdown = soup_after_chubunrui.find("select", {"name": "drpMiddleKikanInf"})
                        if dropdown:
                            options = dropdown.find_all("option")
                            logger.info(f"HTMLから小分類のオプション数: {len(options)}")
                            for i, option in enumerate(options[:10]):
                                text = option.get_text().strip()
                                value = option.get("value", "")
                                logger.info(f"  {i+1}: value={value}, text={text}")
                        
                        # setListItemSubの呼び出しを探す
                        import re
                        if "setListItemSub" in response_text2:
                            logger.info("レスポンスにsetListItemSubが含まれています")
                            # パターン1: setListItemSub('ID', VAR)
                            pattern1 = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
                            matches1 = re.findall(pattern1, response_text2)
                            logger.info(f"setListItemSub呼び出し（変数形式）: {len(matches1)}件")
                            for i, (id_val, var_name) in enumerate(matches1[:5]):
                                logger.info(f"  {i+1}: ID={id_val}, VAR={var_name}")
                                # 変数定義を探す
                                var_pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\];"
                                var_matches = re.findall(var_pattern, response_text2, re.DOTALL)
                                if var_matches:
                                    logger.info(f"    変数定義が見つかりました: {var_name}")
                                    logger.info(f"    内容（最初の500文字）: {var_matches[0][:500]}")
                            
                            # パターン2: setListItemSub('ID', [...])
                            pattern2 = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*\[(.*?)\]\s*\)"
                            matches2 = re.findall(pattern2, response_text2, re.DOTALL)
                            logger.info(f"setListItemSub呼び出し（配列形式）: {len(matches2)}件")
                            for i, (id_val, list_content) in enumerate(matches2[:5]):
                                logger.info(f"  {i+1}: ID={id_val}")
                                logger.info(f"    内容（最初の500文字）: {list_content[:500]}")
        else:
            logger.info("✓ 小分類のオプションが正常に取得できました")
        
        # 4. 小分類を選択して細分類を取得
        if shoubunrui_options and len(shoubunrui_options) > 1:
            logger.info("")
            logger.info("=" * 60)
            logger.info("テスト4: 小分類を選択して細分類を取得")
            logger.info("=" * 60)
            
            # 最初の小分類を選択（「▽小分類」を除く）
            shoubunrui_value = None
            for opt in shoubunrui_options:
                if opt != "▽小分類" and opt:
                    shoubunrui_value = opt
                    break
            
            if shoubunrui_value:
                logger.info(f"選択した小分類: {shoubunrui_value}")
                saibunrui_options = scraper.get_hachu_saibunrui_options(url, daibunrui_value, chubunrui_value, shoubunrui_value)
                logger.info(f"細分類オプション数: {len(saibunrui_options)}")
                for i, opt in enumerate(saibunrui_options[:20]):
                    logger.info(f"  {i+1}: {opt}")
                
                if not saibunrui_options or len(saibunrui_options) <= 1:
                    logger.warning("細分類のオプションが取得できませんでした（▽細分類のみ）")
                else:
                    logger.info("✓ 細分類のオプションが正常に取得できました")
        
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

