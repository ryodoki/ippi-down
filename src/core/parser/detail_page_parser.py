"""Detail Page Parser（詳細ページ→ファイル一覧抽出）"""

from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from ...utils.logger import Logger
from ...app.exceptions import ScrapingError
from .models import FileCandidate


class DetailPageParser:
    """詳細ページパーサー（詳細ページ→ファイル一覧抽出）"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()

    def extract_file_candidates(
        self,
        soup: BeautifulSoup,
        base_url: str,
        file_types: List[str],
        koji_name: Optional[str] = None
    ) -> List[FileCandidate]:
        """詳細ページからファイル候補を抽出"""
        candidates = []
        
        try:
            # ファイルリンクを含むテーブルを探す
            # "入札公告等" または "入札経過・その他" のテーブル
            tables = soup.find_all("table")
            
            for table in tables:
                # テーブルの前にあるdivまたはspanを確認
                prev_elements = table.find_all_previous(["div", "span"], limit=5)
                is_target_table = False
                
                for elem in prev_elements:
                    text = elem.get_text(strip=True)
                    if "入札公告等" in text or "入札経過・その他" in text:
                        is_target_table = True
                        break
                
                if not is_target_table:
                    continue
                
                # テーブル内のリンクを探す
                links = table.find_all("a", href=True)
                
                for link in links:
                    href = link.get("href", "")
                    link_text = link.get_text(strip=True)
                    
                    # "公開中" リンクを探す
                    if "公開中" not in link_text:
                        continue
                    
                    # ファイルURLを構築
                    file_url = urljoin(base_url, href)
                    
                    # ファイルタイプをチェック
                    file_type = self._infer_file_type(file_url, file_types)
                    if not file_type:
                        continue
                    
                    # 文書名称を抽出（同じ行または前の行から）
                    document_name = self._extract_document_name(link)
                    
                    # メタデータ
                    metadata = {
                        "koji_name": koji_name or "",
                        "document_name": document_name
                    }
                    
                    # ファイル名を生成
                    filename = self._generate_filename(file_url, document_name)
                    
                    candidates.append(FileCandidate(
                        url=file_url,
                        filename=filename,
                        file_type=file_type,
                        document_name=document_name,
                        metadata=metadata
                    ))
            
            self.logger.info(f"詳細ページから{len(candidates)}個のファイル候補を抽出しました")
            return candidates
            
        except Exception as e:
            self.logger.error(f"詳細ページ解析エラー: {str(e)}")
            raise ScrapingError(f"詳細ページ解析エラー: {str(e)}")

    def _infer_file_type(self, url: str, file_types: List[str]) -> Optional[str]:
        """URLからファイルタイプを推測"""
        url_lower = url.lower()
        for file_type in file_types:
            if file_type.lower() in url_lower:
                return file_type
        return None

    def _extract_document_name(self, link) -> Optional[str]:
        """文書名称を抽出"""
        # 同じ行の他のセルから文書名称を探す
        row = link.find_parent("tr")
        if row:
            cells = row.find_all("td")
            for cell in cells:
                text = cell.get_text(strip=True)
                if text and text != "公開中":
                    return text
        return None

    def _generate_filename(self, url: str, document_name: Optional[str]) -> str:
        """ファイル名を生成"""
        if document_name:
            # 文書名称から拡張子を推測
            from pathlib import Path
            ext = Path(url).suffix or ".pdf"
            return f"{document_name}{ext}"
        else:
            # URLからファイル名を抽出
            from pathlib import Path
            return Path(url).name or "file.pdf"
