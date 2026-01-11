"""Playwrightを使用したHTTP通信クラス"""

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeoutError
from typing import Dict, Optional, Callable
from pathlib import Path
import time
from bs4 import BeautifulSoup
from .logger import Logger


class PlaywrightClient:
    """Playwrightを使用したHTTP通信クラス（セッション管理含む）"""

    def __init__(self, logger: Optional[Logger] = None, timeout: int = 30000, download_timeout: int = 300000, headless: bool = True):
        """初期化
        
        Args:
            logger: ロガーインスタンス
            timeout: 通常のリクエストのタイムアウト（ミリ秒、デフォルト30000ms=30秒）
            download_timeout: ダウンロードのタイムアウト（ミリ秒、デフォルト300000ms=5分）
            headless: ヘッドレスモードで実行するか（デフォルトTrue）
        """
        self.logger = logger or Logger()
        self.timeout = timeout
        self.download_timeout = download_timeout
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._initialize_browser()

    def _initialize_browser(self):
        """ブラウザを初期化"""
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
            )
            self.page = self.context.new_page()
            
            # デフォルトのタイムアウトを設定
            self.page.set_default_timeout(self.timeout)
            
            self.logger.info("Playwrightブラウザを初期化しました")
        except Exception as e:
            self.logger.error(f"Playwrightブラウザの初期化に失敗しました: {str(e)}")
            raise

    def get(self, url: str, max_retries: int = 3, wait_until: str = "networkidle", **kwargs) -> Optional[Page]:
        """GETリクエストを送信（Pageオブジェクトを返す）
        
        Args:
            url: リクエストURL
            max_retries: 最大リトライ回数
            wait_until: ページ読み込み完了の待機条件（"load", "domcontentloaded", "networkidle"）
            **kwargs: 追加のオプション
        """
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                self.logger.debug(f"GETリクエスト送信: {url} (試行 {attempt + 1}/{max_retries})")
                
                response = self.page.goto(
                    url,
                    timeout=self.timeout,
                    wait_until=wait_until,
                    **kwargs
                )
                
                if response:
                    status = response.status
                    if status == 429:
                        # レート制限
                        if attempt < max_retries - 1:
                            retry_after = int(response.headers.get('retry-after', retry_delay * (attempt + 1)))
                            self.logger.warning(f"レート制限に達しました。{retry_after}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                            time.sleep(retry_after)
                            continue
                        else:
                            self.logger.error(f"レート制限エラー: {url} (status: {status})")
                            raise Exception(f"レート制限エラー: status {status}")
                    elif status >= 400:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (attempt + 1)
                            self.logger.warning(f"HTTPエラー (status: {status})。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                        else:
                            self.logger.error(f"HTTPエラー: {url} (status: {status})")
                            raise Exception(f"HTTPエラー: status {status}")
                
                return self.page
                
            except PlaywrightTimeoutError as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"GETリクエストタイムアウト: {url} - {str(e)}")
                    raise
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(f"タイムアウトエラー。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"GETリクエストエラー: {url} - {str(e)}")
                    raise
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(f"リクエストエラー。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
        
        return None

    def post(self, url: str, data: Optional[Dict] = None, max_retries: int = 3, wait_until: str = "networkidle", **kwargs) -> Optional[Page]:
        """POSTリクエストを送信（Pageオブジェクトを返す）
        
        Args:
            url: リクエストURL
            data: POSTデータ
            max_retries: 最大リトライ回数
            wait_until: ページ読み込み完了の待機条件
            **kwargs: 追加のオプション
        """
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                self.logger.debug(f"POSTリクエスト送信: {url} (試行 {attempt + 1}/{max_retries})")
                
                # PlaywrightでPOSTリクエストを送信
                # フォーム送信の場合は、フォームを埋めて送信ボタンをクリックする方法も可能
                # ここでは、request.post()を使用して直接POSTリクエストを送信
                if data:
                    # フォームデータとして送信
                    response = self.page.request.post(
                        url,
                        form=data,
                        timeout=self.timeout,
                        **kwargs
                    )
                else:
                    response = self.page.request.post(
                        url,
                        timeout=self.timeout,
                        **kwargs
                    )
                
                if response:
                    status = response.status
                    if status == 429:
                        if attempt < max_retries - 1:
                            retry_after = int(response.headers.get('retry-after', retry_delay * (attempt + 1)))
                            self.logger.warning(f"レート制限に達しました。{retry_after}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                            time.sleep(retry_after)
                            continue
                        else:
                            self.logger.error(f"レート制限エラー: {url} (status: {status})")
                            raise Exception(f"レート制限エラー: status {status}")
                    elif status >= 400:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (attempt + 1)
                            self.logger.warning(f"HTTPエラー (status: {status})。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                        else:
                            self.logger.error(f"HTTPエラー: {url} (status: {status})")
                            raise Exception(f"HTTPエラー: status {status}")
                    
                    # POSTリクエスト後、ページを再読み込み（レスポンスがHTMLの場合）
                    # リダイレクトがある場合は自動的に追従される
                    if wait_until and status < 400:
                        # ページに移動して待機
                        self.page.goto(url, timeout=self.timeout, wait_until=wait_until)
                
                return self.page
                
            except PlaywrightTimeoutError as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"POSTリクエストタイムアウト: {url} - {str(e)}")
                    raise
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(f"タイムアウトエラー。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"POSTリクエストエラー: {url} - {str(e)}")
                    raise
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(f"リクエストエラー。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
        
        return None

    def get_page_content(self, url: str, **kwargs) -> Optional[str]:
        """ページのHTMLコンテンツを取得
        
        Args:
            url: リクエストURL
            **kwargs: get()に渡す追加引数
        """
        page = self.get(url, **kwargs)
        if page:
            return page.content()
        return None

    def get_page_soup(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        """ページのBeautifulSoupオブジェクトを取得
        
        Args:
            url: リクエストURL
            **kwargs: get()に渡す追加引数
        """
        content = self.get_page_content(url, **kwargs)
        if content:
            try:
                return BeautifulSoup(content, "lxml")
            except Exception as e:
                self.logger.error(f"BeautifulSoupの作成に失敗: {str(e)}")
                return None
        return None

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
        
        # 保存先ディレクトリを作成
        save_path_obj = Path(save_path)
        save_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        for attempt in range(max_retries):
            try:
                self.logger.debug(f"ファイルダウンロード開始: {url} -> {save_path} (試行 {attempt + 1}/{max_retries})")
                
                # リファラーを設定
                if referer:
                    self.page.set_extra_http_headers({"Referer": referer})
                
                # ダウンロードを開始
                # expect_download()を使用してダウンロードイベントを待機
                with self.page.expect_download(timeout=self.download_timeout) as download_info:
                    # ダウンロードリンクにアクセス
                    self.page.goto(url, timeout=self.download_timeout, wait_until="domcontentloaded")
                
                download = download_info.value
                
                # ファイルを保存
                download.save_as(save_path)
                
                # ファイルサイズを取得
                file_size = save_path_obj.stat().st_size if save_path_obj.exists() else 0
                
                if progress_callback and file_size > 0:
                    progress_callback(file_size, file_size)
                
                self.logger.info(f"ファイルダウンロード完了: {save_path} ({file_size:,} bytes)")
                return True
                
            except PlaywrightTimeoutError as e:
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"ファイルダウンロードタイムアウト: {url} - {str(e)} "
                        f"(タイムアウト設定: {self.download_timeout}ms)"
                    )
                    return False
                wait_time = retry_delay * (2 ** attempt)
                self.logger.warning(
                    f"ダウンロードタイムアウト。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries}, タイムアウト設定: {self.download_timeout}ms)"
                )
                time.sleep(wait_time)
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"ファイルダウンロードエラー: {url} - {str(e)} "
                        f"(エラータイプ: {type(e).__name__})"
                    )
                    return False
                wait_time = retry_delay * (2 ** attempt)
                self.logger.warning(
                    f"ダウンロードエラー。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries}, エラー: {type(e).__name__})"
                )
                time.sleep(wait_time)
        
        return False

    def get_current_page(self) -> Optional[Page]:
        """現在のPageオブジェクトを取得"""
        return self.page

    def close(self):
        """ブラウザをクローズ"""
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            self.logger.info("Playwrightブラウザをクローズしました")
        except Exception as e:
            self.logger.error(f"Playwrightブラウザのクローズに失敗: {str(e)}")

    def __enter__(self):
        """コンテキストマネージャーのエントリ"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャーのエグジット"""
        self.close()
