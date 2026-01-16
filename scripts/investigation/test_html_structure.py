"""実際のHTML構造を確認するテストスクリプト"""

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
    
    # 複数のURLを試す
    urls = [
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx",
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4",
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search.aspx",
    ]
    
    for url in urls:
        try:
            logger.info(f"ページを取得中: {url}")
            response = http_client.get(url)
            
            # エンコーディング処理
            if response.encoding:
                response.encoding = response.apparent_encoding or 'utf-8'
            else:
                response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            
            # HTMLをファイルに保存
            html_file = project_root / f"test_search_page_{urls.index(url)}.html"
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            logger.info(f"HTMLを保存しました: {html_file}")
            
            # hidden inputを確認
            hidden_inputs = {}
            for hidden in soup.find_all("input", type="hidden"):
                name = hidden.get("name", "")
                value = hidden.get("value", "")
                if name:
                    hidden_inputs[name] = value[:100] if len(value) > 100 else value  # 最初の100文字のみ
            
            logger.info(f"hidden inputを{len(hidden_inputs)}個発見")
            logger.info(f"hidden inputの名前: {list(hidden_inputs.keys())}")
            
            # __VIEWSTATE関連を確認
            viewstate_keys = [k for k in hidden_inputs.keys() if "VIEWSTATE" in k.upper()]
            logger.info(f"VIEWSTATE関連のキー: {viewstate_keys}")
            
            # __EVENTVALIDATION関連を確認
            eventvalidation_keys = [k for k in hidden_inputs.keys() if "EVENTVALIDATION" in k.upper()]
            logger.info(f"EVENTVALIDATION関連のキー: {eventvalidation_keys}")
            
            # 大分類のドロップダウンを確認
            dropdown_name = "ctl00$ContentPlaceHolder1$ddlHachuDaibunrui"
            dropdown = soup.find("select", {"name": dropdown_name})
            if dropdown:
                logger.info(f"大分類ドロップダウンを発見: {dropdown_name}")
                options = dropdown.find_all("option")
                logger.info(f"オプション数: {len(options)}")
                for i, option in enumerate(options[:5]):  # 最初の5個
                    text = option.get_text().strip()
                    value = option.get("value", "")
                    logger.info(f"  オプション{i+1}: value={value}, text={text}")
            else:
                logger.warning(f"大分類ドロップダウンが見つかりません: {dropdown_name}")
                # すべてのselect要素を確認
                all_selects = soup.find_all("select")
                logger.info(f"ページ内のselect要素数: {len(all_selects)}")
                for i, select in enumerate(all_selects[:10]):  # 最初の10個
                    name = select.get("name", "なし")
                    id_attr = select.get("id", "なし")
                    logger.info(f"  select要素{i+1}: name={name}, id={id_attr}")
            
            # setListItemSubが含まれているか確認
            if "setListItemSub" in response.text:
                logger.info("レスポンスにsetListItemSubが含まれています")
                # setListItemSubの呼び出しを探す
                import re
                pattern = r"setListItemSub\s*\([^)]+\)"
                matches = re.findall(pattern, response.text)
                logger.info(f"setListItemSubの呼び出し数: {len(matches)}")
                for i, match in enumerate(matches[:3]):  # 最初の3個
                    logger.info(f"  setListItemSub呼び出し{i+1}: {match[:200]}")  # 最初の200文字
            
        except Exception as e:
            logger.error(f"エラー ({url}): {str(e)}", exc_info=True)
            continue
    
    http_client.close()

if __name__ == "__main__":
    main()
