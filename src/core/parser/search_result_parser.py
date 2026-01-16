"""Search Result Parser（検索結果→案件一覧抽出）"""

from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from ...utils.logger import Logger
from ...app.exceptions import ScrapingError
from .models import ProjectEntry


class SearchResultParser:
    """検索結果パーサー（検索結果→案件一覧抽出）"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()

    def extract_project_entries(
        self,
        soup: BeautifulSoup,
        base_url: str
    ) -> List[ProjectEntry]:
        """検索結果から案件エントリを抽出"""
        entries = []
        
        try:
            # 検索結果テーブルを探す
            result_table = soup.find("table", id="dgrSearchList")
            if not result_table:
                self.logger.warning("検索結果テーブルが見つかりませんでした")
                return entries

            # ヘッダー行をスキップ
            rows = result_table.find_all("tr")[1:]
            
            for row in rows:
                try:
                    # 詳細リンクを探す
                    detail_link = row.find("a", href=True)
                    if not detail_link:
                        continue
                    
                    # 詳細URLを構築
                    detail_url = urljoin(base_url, detail_link["href"])
                    
                    # 工事名を抽出（リンクテキストまたは他のセルから）
                    koji_name = detail_link.get_text(strip=True)
                    if not koji_name:
                        # 他のセルから工事名を探す
                        cells = row.find_all("td")
                        if len(cells) > 1:
                            koji_name = cells[1].get_text(strip=True)
                    
                    if not koji_name:
                        self.logger.debug("工事名が抽出できなかったため、この行をスキップします")
                        continue
                    
                    # メタデータを抽出（必要に応じて）
                    metadata = {
                        "koji_name": koji_name
                    }
                    
                    entries.append(ProjectEntry(
                        detail_url=detail_url,
                        koji_name=koji_name,
                        metadata=metadata
                    ))
                except Exception as e:
                    self.logger.warning(f"行の解析エラー: {str(e)}")
                    continue
            
            self.logger.info(f"検索結果から{len(entries)}個の案件エントリを抽出しました")
            return entries
            
        except Exception as e:
            self.logger.error(f"検索結果解析エラー: {str(e)}")
            raise ScrapingError(f"検索結果解析エラー: {str(e)}")
