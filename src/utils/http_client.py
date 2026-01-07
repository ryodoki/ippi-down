"""HTTP通信を行うクラス（セッション管理含む）"""

import requests
import time
from typing import Dict, Optional, Callable
from pathlib import Path
from .logger import Logger


class HTTPClient:
    """HTTP通信を行うクラス（セッション管理含む）"""

    def __init__(self, logger: Optional[Logger] = None, timeout: int = 30, download_timeout: int = 60):
        """初期化
        
        Args:
            logger: ロガーインスタンス
            timeout: 通常のリクエストのタイムアウト（秒）
            download_timeout: ダウンロードのタイムアウト（秒）
        """
        self.logger = logger or Logger()
        self.timeout = timeout
        self.download_timeout = download_timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )

    def get(self, url: str, max_retries: int = 3, **kwargs) -> requests.Response:
        """GETリクエストを送信
        
        Args:
            url: リクエストURL
            max_retries: 最大リトライ回数
            **kwargs: requests.get()に渡す追加引数
        """
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=self.timeout, **kwargs)
                
                # HTTPステータス429（レート制限）の処理
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        retry_after = int(response.headers.get('Retry-After', retry_delay * (attempt + 1)))
                        self.logger.warning(f"レート制限に達しました。{retry_after}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                        time.sleep(retry_after)
                        continue
                    else:
                        response.raise_for_status()
                else:
                    response.raise_for_status()
                
                return response
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"GETリクエストエラー: {url} - {str(e)}")
                    raise
                # リトライ前に待機
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(f"リクエストエラー。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
        
        # ここには到達しないはずだが、念のため
        raise requests.exceptions.RequestException("最大リトライ回数に達しました")

    def post(self, url: str, data: Optional[Dict] = None, max_retries: int = 3, **kwargs) -> requests.Response:
        """POSTリクエストを送信
        
        Args:
            url: リクエストURL
            data: POSTデータ
            max_retries: 最大リトライ回数
            **kwargs: requests.post()に渡す追加引数
        """
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, data=data, timeout=self.timeout, **kwargs)
                
                # HTTPステータス429（レート制限）の処理
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        retry_after = int(response.headers.get('Retry-After', retry_delay * (attempt + 1)))
                        self.logger.warning(f"レート制限に達しました。{retry_after}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                        time.sleep(retry_after)
                        continue
                    else:
                        response.raise_for_status()
                else:
                    response.raise_for_status()
                
                return response
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"POSTリクエストエラー: {url} - {str(e)}")
                    raise
                # リトライ前に待機
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(f"リクエストエラー。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
        
        # ここには到達しないはずだが、念のため
        raise requests.exceptions.RequestException("最大リトライ回数に達しました")

    def download_file(
        self,
        url: str,
        save_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_retries: int = 3,
    ) -> bool:
        """ファイルをダウンロード
        
        Args:
            url: ダウンロードURL
            save_path: 保存先パス
            progress_callback: 進捗コールバック関数
            max_retries: 最大リトライ回数
        """
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, stream=True, timeout=self.download_timeout)
                
                # HTTPステータス429（レート制限）の処理
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        retry_after = int(response.headers.get('Retry-After', retry_delay * (attempt + 1)))
                        self.logger.warning(f"レート制限に達しました。{retry_after}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                        time.sleep(retry_after)
                        continue
                    else:
                        response.raise_for_status()
                else:
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
                if attempt == max_retries - 1:
                    self.logger.error(f"ファイルダウンロードエラー: {url} - {str(e)}")
                    return False
                # リトライ前に待機
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(f"ダウンロードエラー。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                self.logger.error(f"ファイル保存エラー: {save_path} - {str(e)}")
                return False
        
        return False

    def get_session(self) -> requests.Session:
        """セッションを取得"""
        return self.session

    def close(self):
        """セッションをクローズ"""
        self.session.close()

