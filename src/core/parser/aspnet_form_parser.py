# -*- coding: utf-8 -*-

"""ASP.NET Form Parser（__VIEWSTATE等hidden解析 + postback組み立て）"""

from typing import Dict, Optional
from bs4 import BeautifulSoup
from ...utils.logger import Logger
from ...app.exceptions import ScrapingError


class AspNetFormParser:
    """ASP.NET Form Parser（hidden解析 + postback組み立て）"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()

    def get_all_hidden_inputs(self, soup: BeautifulSoup) -> Dict[str, str]:
        """すべてのhidden inputを取得"""
        hidden_inputs = {}
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                hidden_inputs[name] = value
        
        self.logger.debug(f"hidden inputを{len(hidden_inputs)}個取得しました")
        
        # 重要なhidden inputの存在を確認
        if "__VIEWSTATE" in hidden_inputs:
            self.logger.debug(f"__VIEWSTATE: 取得済み (長さ: {len(hidden_inputs['__VIEWSTATE'])})")
        else:
            self.logger.warning("__VIEWSTATEが見つかりませんでした")
        
        if "__EVENTVALIDATION" in hidden_inputs:
            self.logger.debug(f"__EVENTVALIDATION: 取得済み (長さ: {len(hidden_inputs['__EVENTVALIDATION'])})")
        else:
            self.logger.warning("__EVENTVALIDATIONが見つかりませんでした")
        
        return hidden_inputs

    def build_postback_data(
        self,
        soup: BeautifulSoup,
        event_target: str,
        event_argument: str = "",
        additional_data: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """POSTバックデータを組み立て"""
        hidden_inputs = self.get_all_hidden_inputs(soup)
        
        # POSTバックデータを構築
        post_data = {
            "__EVENTTARGET": event_target,
            "__EVENTARGUMENT": event_argument,
            **hidden_inputs
        }
        
        # 追加データをマージ
        if additional_data:
            post_data.update(additional_data)
        
        return post_data
