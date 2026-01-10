"""HTTP通信を行うクラス（セッション管理含む）"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from typing import Dict, Optional, Callable
from pathlib import Path
from .logger import Logger


class HTTPClient:
    """HTTP通信を行うクラス（セッション管理含む）"""

    def __init__(self, logger: Optional[Logger] = None, timeout: int = 30, download_timeout: int = 300):
        """初期化
        
        Args:
            logger: ロガーインスタンス
            timeout: 通常のリクエストのタイムアウト（秒、デフォルト30秒）
            download_timeout: ダウンロードの読み取りタイムアウト（秒、デフォルト300秒=5分）
        """
        self.logger = logger or Logger()
        self.timeout = timeout
        self.download_timeout = download_timeout
        self.session = requests.Session()
        # デフォルトヘッダーを設定（ブラウザを模倣）
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        
        # 接続プールとリトライ設定を改善
        # 指数バックオフ: 1秒, 2秒, 4秒
        retry_strategy = Retry(
            total=3,
            backoff_factor=2,  # 指数バックオフ: 2^0, 2^1, 2^2 = 1, 2, 4秒
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False  # ステータスコードエラーでもリトライを続ける
        )
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=retry_strategy
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

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
        referer: Optional[str] = None,
    ) -> bool:
        """ファイルをダウンロード
        
        Args:
            url: ダウンロードURL
            save_path: 保存先パス
            progress_callback: 進捗コールバック関数
            max_retries: 最大リトライ回数
            referer: リファラーヘッダー（元のページURL）
        """
        retry_delay = 1
        
        # ダウンロード用のヘッダーを準備
        download_headers = {
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        }
        
        # Refererが指定されている場合は追加
        if referer:
            download_headers["Referer"] = referer
        
        for attempt in range(max_retries):
            try:
                # 接続タイムアウトと読み取りタイムアウトを分離
                # 接続タイムアウト: 10秒、読み取りタイムアウト: download_timeout秒
                timeout_tuple = (10, self.download_timeout)
                
                response = self.session.get(
                    url,
                    stream=True,
                    timeout=timeout_tuple,
                    headers=download_headers
                )
                
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
                start_time = time.time()
                last_progress_time = start_time
                last_progress_size = 0

                with open(save_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            current_time = time.time()
                            
                            # 進捗コールバック
                            if progress_callback and total_size > 0:
                                progress_callback(downloaded_size, total_size)
                            
                            # タイムアウト前の警告（30秒以上進捗がない場合）
                            if current_time - last_progress_time > 30:
                                elapsed = current_time - start_time
                                remaining_timeout = self.download_timeout - elapsed
                                if remaining_timeout < 60:
                                    self.logger.warning(
                                        f"ダウンロードが遅延しています。残りタイムアウト: {remaining_timeout:.0f}秒 "
                                        f"(進捗: {downloaded_size:,}/{total_size:,} bytes)"
                                    )
                                last_progress_time = current_time
                            
                            # 進捗がある場合は更新
                            if downloaded_size > last_progress_size:
                                last_progress_size = downloaded_size
                                last_progress_time = current_time

                self.logger.info(f"ファイルダウンロード完了: {save_path}")
                return True

            except requests.exceptions.Timeout as e:
                # タイムアウトエラーの詳細な処理
                error_type = "接続タイムアウト" if "connect" in str(e).lower() else "読み取りタイムアウト"
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"ファイルダウンロードタイムアウト: {url} - {error_type} "
                        f"(タイムアウト設定: {self.download_timeout}秒)"
                    )
                    return False
                # リトライ前に待機（指数バックオフ）
                wait_time = retry_delay * (2 ** attempt)
                self.logger.warning(
                    f"ダウンロードタイムアウト ({error_type})。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries}, タイムアウト設定: {self.download_timeout}秒)"
                )
                time.sleep(wait_time)
            except requests.exceptions.ConnectionError as e:
                # 接続エラーの詳細な処理
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"ファイルダウンロード接続エラー: {url} - {str(e)}"
                    )
                    return False
                wait_time = retry_delay * (2 ** attempt)
                self.logger.warning(
                    f"ダウンロード接続エラー。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"ファイルダウンロードエラー: {url} - {str(e)} "
                        f"(エラータイプ: {type(e).__name__})"
                    )
                    return False
                # リトライ前に待機（指数バックオフ）
                wait_time = retry_delay * (2 ** attempt)
                self.logger.warning(
                    f"ダウンロードエラー。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries}, エラー: {type(e).__name__})"
                )
                time.sleep(wait_time)
            except Exception as e:
                self.logger.error(
                    f"ファイル保存エラー: {save_path} - {str(e)} "
                    f"(エラータイプ: {type(e).__name__})"
                )
                return False
        
        return False

    def get_session(self) -> requests.Session:
        """セッションを取得"""
        return self.session

    def close(self):
        """セッションをクローズ"""
        self.session.close()

