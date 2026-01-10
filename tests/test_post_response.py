"""POSTレスポンスを確認するテストスクリプト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.http_client import HTTPClient  # type: ignore
from src.utils.logger import Logger  # type: ignore
from src.models.config_model import LoggingConfig  # type: ignore
from bs4 import BeautifulSoup

def main():
    logger = Logger(LoggingConfig(level="DEBUG"))
    http_client = HTTPClient(logger)
    
    url = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
    
    try:
        # 初回GET
        logger.info(f"初回GET: {url}")
        response = http_client.get(url)
        
        if response.encoding:
            response.encoding = response.apparent_encoding or 'utf-8'
        else:
            response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
        
        # hidden inputを取得
        hidden_inputs = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                hidden_inputs[name] = value
        
        # 大分類を選択（国の機関 = value="0"）
        form_data = hidden_inputs.copy()
        form_data["__EVENTTARGET"] = "drpTopKikanInf"
        form_data["__EVENTARGUMENT"] = ""
        form_data["drpTopKikanInf"] = "0"
        
        logger.info("大分類を選択してPOST送信")
        response2 = http_client.post(url, data=form_data)
        
        if response2.encoding:
            response2.encoding = response2.apparent_encoding or 'utf-8'
        else:
            response2.encoding = 'utf-8'
        
        response_text = response2.text
        
        # POSTレスポンスをファイルに保存
        with open("test_post_response_1.html", "w", encoding="utf-8") as f:
            f.write(response_text)
        logger.info("POSTレスポンスを保存しました: test_post_response_1.html")
        
        # setListItemSubの呼び出しを探す
        import re
        
        # パターン1: setListItemSub('ID', LIST変数)
        pattern1 = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
        matches1 = re.findall(pattern1, response_text)
        logger.info(f"パターン1 (setListItemSub('ID', VAR)): {len(matches1)}件")
        for i, (id_val, var_name) in enumerate(matches1[:5]):
            logger.info(f"  {i+1}: ID={id_val}, VAR={var_name}")
            # 変数定義を探す
            var_pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\];"
            var_matches = re.findall(var_pattern, response_text, re.DOTALL)
            if var_matches:
                logger.info(f"    変数定義が見つかりました: {var_name}")
                logger.info(f"    内容（最初の200文字）: {var_matches[0][:200]}")
        
        # パターン2: setListItemSub('ID', ['value:text', ...])
        pattern2 = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*\[(.*?)\]\s*\)"
        matches2 = re.findall(pattern2, response_text, re.DOTALL)
        logger.info(f"パターン2 (setListItemSub('ID', [...])): {len(matches2)}件")
        for i, (id_val, list_content) in enumerate(matches2[:5]):
            logger.info(f"  {i+1}: ID={id_val}")
            logger.info(f"    内容（最初の200文字）: {list_content[:200]}")
        
        # 中分類のドロップダウンを確認
        soup2 = BeautifulSoup(response_text, "lxml", from_encoding=response2.encoding)
        dropdown = soup2.find("select", {"name": "drpLargeKikanInf2"})
        if dropdown:
            options = dropdown.find_all("option")
            logger.info(f"中分類のオプション数: {len(options)}")
            for i, option in enumerate(options[:10]):
                text = option.get_text().strip()
                value = option.get("value", "")
                logger.info(f"  オプション{i+1}: value={value}, text={text}")
        
        # 小分類のドロップダウンを確認
        dropdown2 = soup2.find("select", {"name": "drpMiddleKikanInf"})
        if dropdown2:
            options2 = dropdown2.find_all("option")
            logger.info(f"小分類のオプション数: {len(options2)}")
            for i, option in enumerate(options2[:10]):
                text = option.get_text().strip()
                value = option.get("value", "")
                logger.info(f"  オプション{i+1}: value={value}, text={text}")
        
        # 中分類を選択してPOST（内閣府沖縄総合事務局 = value="02"）
        form_data2 = {}
        for hidden in soup2.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                form_data2[name] = value
        
        form_data2["__EVENTTARGET"] = "drpLargeKikanInf2"
        form_data2["__EVENTARGUMENT"] = ""
        form_data2["drpTopKikanInf"] = "0"
        form_data2["drpLargeKikanInf2"] = "02"
        
        logger.info("中分類を選択してPOST送信")
        response3 = http_client.post(url, data=form_data2)
        
        if response3.encoding:
            response3.encoding = response3.apparent_encoding or 'utf-8'
        else:
            response3.encoding = 'utf-8'
        
        response_text3 = response3.text
        
        # POSTレスポンスをファイルに保存
        with open("test_post_response_2.html", "w", encoding="utf-8") as f:
            f.write(response_text3)
        logger.info("POSTレスポンス（中分類選択後）を保存しました: test_post_response_2.html")
        
        # 小分類のドロップダウンを確認
        soup3 = BeautifulSoup(response_text3, "lxml", from_encoding=response3.encoding)
        dropdown3 = soup3.find("select", {"name": "drpMiddleKikanInf"})
        if dropdown3:
            options3 = dropdown3.find_all("option")
            logger.info(f"小分類のオプション数（中分類選択後）: {len(options3)}")
            for i, option in enumerate(options3[:10]):
                text = option.get_text().strip()
                value = option.get("value", "")
                logger.info(f"  オプション{i+1}: value={value}, text={text}")
        
        # setListItemSubの呼び出しを探す（中分類選択後のレスポンス）
        pattern1 = r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
        matches1 = re.findall(pattern1, response_text3)
        logger.info(f"setListItemSub呼び出し（中分類選択後）: {len(matches1)}件")
        for i, (id_val, var_name) in enumerate(matches1[:5]):
            logger.info(f"  {i+1}: ID={id_val}, VAR={var_name}")
            # 変数定義を探す
            var_pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\];"
            var_matches = re.findall(var_pattern, response_text3, re.DOTALL)
            if var_matches:
                logger.info(f"    変数定義が見つかりました: {var_name}")
                logger.info(f"    内容（最初の500文字）: {var_matches[0][:500]}")
        
    except Exception as e:
        logger.error(f"エラー: {str(e)}", exc_info=True)
    finally:
        http_client.close()

if __name__ == "__main__":
    main()

