"""HTTP通信を行うクラス（セッション管理含む）"""

import requests
from typing import Dict, Optional, Callable
from pathlib import Path
from ..utils.logger import Logger


class HTTPClient:
    """HTTP通信を行うクラス（セッション管理含む）"""

    def __init__(self, logger: Optional[Logger] = None):
        """初期化"""
        self.logger = logger or Logger()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    def get(self, url: str, **kwargs) -> requests.Response:
        """GETリクエストを送信"""
        try:
            response = self.session.get(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            self.logger.error(f"GETリクエストエラー: {url} - {str(e)}")
            raise

    def post(self, url: str, data: Optional[Dict] = None, **kwargs) -> requests.Response:
        """POSTリクエストを送信"""
        try:
            response = self.session.post(url, data=data, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            self.logger.error(f"POSTリクエストエラー: {url} - {str(e)}")
            raise

    def download_file(
        self,
        url: str,
        save_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """ファイルをダウンロード"""
        try:
            response = self.session.get(url, stream=True, timeout=60)
            response.raise_for_status()

            # 保存先ディレクトリを作成
            save_path_obj = Path(save_path)
            save_path_obj.parent.mkdir(parents=True, exist_ok=True)

            total_size = int(response.headers.get("content-length", 0))
            downloaded_size = 0

            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(downloaded_size, total_size)

            self.logger.info(f"ファイルダウンロード完了: {save_path}")
            return True

        except requests.exceptions.RequestException as e:
            self.logger.error(f"ファイルダウンロードエラー: {url} - {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"ファイル保存エラー: {save_path} - {str(e)}")
            return False

    def get_session(self) -> requests.Session:
        """セッションを取得"""
        return self.session

    def close(self):
        """セッションをクローズ"""
        self.session.close()

