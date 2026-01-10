"""実際のブラウザの動作をシミュレートして、不足している情報を特定するスクリプト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig  # type: ignore
from src.core.scraper import Scraper  # type: ignore
from bs4 import BeautifulSoup
import json

def save_response_html(filename: str, content: str):
    """レスポンスのHTMLをファイルに保存"""
    filepath = project_root / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath

def save_form_data(filename: str, form_data: dict):
    """フォームデータをJSONファイルに保存"""
    filepath = project_root / filename
    # 長い値を切り詰める
    truncated_data = {}
    for key, value in form_data.items():
        if isinstance(value, str) and len(value) > 500:
            truncated_data[key] = value[:500] + f"... (長さ: {len(value)})"
        else:
            truncated_data[key] = value
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(truncated_data, f, ensure_ascii=False, indent=2)
    return filepath

def main():
    logger = Logger(LoggingConfig(level="INFO"))
    http_client = HTTPClient(logger)
    scraper = Scraper(http_client, logger)
    
    url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx"
    normalized_url = scraper._normalize_search_url(url)
    
    try:
        logger.info("=" * 80)
        logger.info("実際のブラウザの動作をシミュレート")
        logger.info("=" * 80)
        
        # ステップ1: 初回GET
        logger.info("")
        logger.info("ステップ1: 初回GET")
        logger.info("-" * 80)
        initial_soup = scraper.fetch_page(normalized_url)
        if not initial_soup:
            logger.error("初回GETに失敗しました")
            return
        
        initial_hidden = scraper._get_all_hidden_inputs(initial_soup)
        save_form_data("step1_initial_hidden.json", initial_hidden)
        logger.info("✓ 初回GETのhidden inputを保存: step1_initial_hidden.json")
        
        # ステップ2: 大分類を選択（国の機関 = value="0"）
        logger.info("")
        logger.info("ステップ2: 大分類「国の機関」を選択")
        logger.info("-" * 80)
        form_data1 = scraper._get_all_hidden_inputs(initial_soup)
        form_data1["__EVENTTARGET"] = "drpTopKikanInf"
        form_data1["__EVENTARGUMENT"] = ""
        form_data1["drpTopKikanInf"] = "0"
        
        save_form_data("step2_daibunrui_post.json", form_data1)
        logger.info("✓ POSTリクエストのフォームデータを保存: step2_daibunrui_post.json")
        
        response1 = http_client.post(normalized_url, data=form_data1)
        if response1.encoding:
            response1.encoding = response1.apparent_encoding or 'utf-8'
        else:
            response1.encoding = 'utf-8'
        
        response1_text = response1.text
        save_response_html("step2_daibunrui_response.html", response1_text)
        logger.info("✓ POSTレスポンスを保存: step2_daibunrui_response.html")
        
        soup1 = BeautifulSoup(response1_text, "lxml", from_encoding=response1.encoding)
        hidden1 = scraper._get_all_hidden_inputs(soup1)
        save_form_data("step2_daibunrui_hidden.json", hidden1)
        logger.info("✓ 大分類選択後のhidden inputを保存: step2_daibunrui_hidden.json")
        
        # 中分類のオプションを確認
        dropdown1 = soup1.find("select", {"name": "drpLargeKikanInf2"})
        if dropdown1:
            options1 = dropdown1.find_all("option")
            logger.info(f"中分類のオプション数: {len(options1)}")
            for i, opt in enumerate(options1[:5]):
                logger.info(f"  {i+1}: {opt.get_text().strip()} (value={opt.get('value', '')})")
        
        # ステップ3: 中分類を選択（内閣府沖縄総合事務局 = value="02"）
        logger.info("")
        logger.info("ステップ3: 中分類「内閣府沖縄総合事務局」を選択")
        logger.info("-" * 80)
        form_data2 = scraper._get_all_hidden_inputs(soup1)
        form_data2["__EVENTTARGET"] = "drpLargeKikanInf2"
        form_data2["__EVENTARGUMENT"] = ""
        form_data2["drpTopKikanInf"] = "0"
        form_data2["drpLargeKikanInf2"] = "02"
        
        save_form_data("step3_chubunrui_post.json", form_data2)
        logger.info("✓ POSTリクエストのフォームデータを保存: step3_chubunrui_post.json")
        
        response2 = http_client.post(normalized_url, data=form_data2)
        if response2.encoding:
            response2.encoding = response2.apparent_encoding or 'utf-8'
        else:
            response2.encoding = 'utf-8'
        
        response2_text = response2.text
        save_response_html("step3_chubunrui_response.html", response2_text)
        logger.info("✓ POSTレスポンスを保存: step3_chubunrui_response.html")
        
        soup2 = BeautifulSoup(response2_text, "lxml", from_encoding=response2.encoding)
        hidden2 = scraper._get_all_hidden_inputs(soup2)
        save_form_data("step3_chubunrui_hidden.json", hidden2)
        logger.info("✓ 中分類選択後のhidden inputを保存: step3_chubunrui_hidden.json")
        
        # 小分類のドロップダウンを確認
        dropdown2 = soup2.find("select", {"name": "drpMiddleKikanInf"})
        if dropdown2:
            options2 = dropdown2.find_all("option")
            logger.info(f"小分類のオプション数: {len(options2)}")
            for i, opt in enumerate(options2):
                text = opt.get_text().strip()
                value = opt.get("value", "")
                logger.info(f"  {i+1}: {text} (value={value})")
            
            # 小分類のオプションをJSONに保存
            shoubunrui_options = []
            for opt in options2:
                shoubunrui_options.append({
                    "value": opt.get("value", ""),
                    "text": opt.get_text().strip()
                })
            with open("step3_shoubunrui_options.json", "w", encoding="utf-8") as f:
                json.dump(shoubunrui_options, f, ensure_ascii=False, indent=2)
            logger.info("✓ 小分類のオプションを保存: step3_shoubunrui_options.json")
            
            # 最初の小分類を選択（細分類取得のため）
            valid_options = [opt for opt in options2 if opt.get("value", "") != "-1"]
            if valid_options:
                first_shoubunrui_value = valid_options[0].get("value", "")
                first_shoubunrui_text = valid_options[0].get_text().strip()
                logger.info("")
                logger.info(f"ステップ4: 小分類「{first_shoubunrui_text}」を選択")
                logger.info("-" * 80)
                
                form_data3 = scraper._get_all_hidden_inputs(soup2)
                form_data3["__EVENTTARGET"] = "drpMiddleKikanInf"
                form_data3["__EVENTARGUMENT"] = ""
                form_data3["drpTopKikanInf"] = "0"
                form_data3["drpLargeKikanInf2"] = "02"
                form_data3["drpMiddleKikanInf"] = first_shoubunrui_value
                
                save_form_data("step4_shoubunrui_post.json", form_data3)
                logger.info("✓ POSTリクエストのフォームデータを保存: step4_shoubunrui_post.json")
                
                response3 = http_client.post(normalized_url, data=form_data3)
                if response3.encoding:
                    response3.encoding = response3.apparent_encoding or 'utf-8'
                else:
                    response3.encoding = 'utf-8'
                
                response3_text = response3.text
                save_response_html("step4_shoubunrui_response.html", response3_text)
                logger.info("✓ POSTレスポンスを保存: step4_shoubunrui_response.html")
                
                soup3 = BeautifulSoup(response3_text, "lxml", from_encoding=response3.encoding)
                hidden3 = scraper._get_all_hidden_inputs(soup3)
                save_form_data("step4_shoubunrui_hidden.json", hidden3)
                logger.info("✓ 小分類選択後のhidden inputを保存: step4_shoubunrui_hidden.json")
                
                # 細分類のドロップダウンを確認
                dropdown3 = soup3.find("select", {"name": "drpSmallKikanInf"})
                if dropdown3:
                    options3 = dropdown3.find_all("option")
                    logger.info(f"細分類のオプション数: {len(options3)}")
                    for i, opt in enumerate(options3):
                        text = opt.get_text().strip()
                        value = opt.get("value", "")
                        logger.info(f"  {i+1}: {text} (value={value})")
                    
                    # 細分類のオプションをJSONに保存
                    saibunrui_options = []
                    for opt in options3:
                        saibunrui_options.append({
                            "value": opt.get("value", ""),
                            "text": opt.get_text().strip()
                        })
                    with open("step4_saibunrui_options.json", "w", encoding="utf-8") as f:
                        json.dump(saibunrui_options, f, ensure_ascii=False, indent=2)
                    logger.info("✓ 細分類のオプションを保存: step4_saibunrui_options.json")
        
        # JavaScriptコードの確認
        logger.info("")
        logger.info("ステップ5: JavaScriptコードの確認")
        logger.info("-" * 80)
        
        # setListItemSubの呼び出しを確認
        import re
        if "setListItemSub" in response2_text:
            logger.info("✓ 中分類選択後のレスポンスにsetListItemSubが含まれています")
            pattern = r"setListItemSub\s*\([^)]+\)"
            matches = re.findall(pattern, response2_text)
            logger.info(f"setListItemSubの呼び出し数: {len(matches)}")
            for i, match in enumerate(matches[:5]):
                logger.info(f"  {i+1}: {match[:200]}")
        else:
            logger.info("✗ 中分類選択後のレスポンスにsetListItemSubが含まれていません")
        
        # 小分類が存在する場合のみ、細分類の確認を行う
        response3_text = None
        if valid_options:
            response3_text = response3_text if 'response3_text' in locals() else None
        
        if response3_text and "setListItemSub" in response3_text:
            logger.info("✓ 小分類選択後のレスポンスにsetListItemSubが含まれています")
            pattern = r"setListItemSub\s*\([^)]+\)"
            matches = re.findall(pattern, response3_text)
            logger.info(f"setListItemSubの呼び出し数: {len(matches)}")
            for i, match in enumerate(matches[:5]):
                logger.info(f"  {i+1}: {match[:200]}")
        else:
            logger.info("✗ 小分類選択後のレスポンスにsetListItemSubが含まれていません")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("調査完了")
        logger.info("=" * 80)
        logger.info("")
        logger.info("保存されたファイル:")
        logger.info("  - step1_initial_hidden.json: 初回GETのhidden input")
        logger.info("  - step2_daibunrui_post.json: 大分類選択時のPOSTデータ")
        logger.info("  - step2_daibunrui_response.html: 大分類選択後のレスポンス")
        logger.info("  - step2_daibunrui_hidden.json: 大分類選択後のhidden input")
        logger.info("  - step3_chubunrui_post.json: 中分類選択時のPOSTデータ")
        logger.info("  - step3_chubunrui_response.html: 中分類選択後のレスポンス")
        logger.info("  - step3_chubunrui_hidden.json: 中分類選択後のhidden input")
        logger.info("  - step3_shoubunrui_options.json: 小分類のオプション")
        if valid_options:
            logger.info("  - step4_shoubunrui_post.json: 小分類選択時のPOSTデータ")
            logger.info("  - step4_shoubunrui_response.html: 小分類選択後のレスポンス")
            logger.info("  - step4_shoubunrui_hidden.json: 小分類選択後のhidden input")
            logger.info("  - step4_saibunrui_options.json: 細分類のオプション")
        
    except Exception as e:
        logger.error(f"調査エラー: {str(e)}", exc_info=True)
    finally:
        http_client.close()

if __name__ == "__main__":
    main()

