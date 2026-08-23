# -*- coding: utf-8 -*-

"""HTTP通信を行うクラス（セッション管理含む）"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from typing import Dict, Optional, Callable, Any, Tuple
from pathlib import Path
from urllib.parse import urlparse
from .logger import Logger
from .ssl_config import configure_ssl, ssl_error_hint
from .network_audit import (
    EVENT_ALLOW,
    EVENT_BLOCKED,
    EVENT_RATE_LIMITED,
    EVENT_ROBOTS_DENIED,
    NetworkAuditLog,
)
from .rate_limiter import RateLimiter, get_shared_limiter
from .robots import RobotsPolicy
from ..models.config_model import NetworkConfig
from ..app.exceptions import BlockedRequestError, NetworkError, RateLimitError

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class HTTPClient:
    """HTTP通信を行うクラス（セッション管理含む）"""

    def __init__(
        self,
        logger: Optional[Logger] = None,
        timeout: int = 30,
        download_timeout: int = 300,
        network_config: Optional[NetworkConfig] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """初期化
        
        Args:
            logger: ロガーインスタンス
            timeout: 通常のリクエストのタイムアウト（秒、デフォルト30秒）
            download_timeout: ダウンロードの読み取りタイムアウト（秒、デフォルト300秒=5分）
            network_config: 通信ポリシー（許可先・レート制限・robots・監査ログ）
            rate_limiter: レート制限。省略時はプロセス共有のものを使う
        """
        self.logger = logger or Logger()
        self.timeout = timeout
        self.download_timeout = download_timeout
        self.network_config = network_config or NetworkConfig()
        self.audit = NetworkAuditLog(self.network_config.audit_log, logger=self.logger)
        # 共有インスタンスにすることで、GUI のスレッドと本処理が同一ホストへ同時に出ない
        self.rate_limiter = rate_limiter or get_shared_limiter(
            self.network_config, logger=self.logger
        )
        self.robots = RobotsPolicy.from_config(
            self.network_config, fetcher=self._fetch_robots, logger=self.logger
        )
        configure_ssl()
        self.session = requests.Session()
        # デフォルトヘッダーを設定（身元を明示したUAを使用）
        self.session.headers.update(
            {
                "User-Agent": self._build_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",  # brを削除（brotli解凍の問題回避）
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

    # ------------------------------------------------------------ 通信の作法

    def _build_user_agent(self) -> str:
        """身元を明示したUAを組み立てる

        既定は現行UAへ識別子を付加する形。完全に置き換えたい場合は
        network.user_agent を指定する。
        """
        if self.network_config.user_agent:
            return self.network_config.user_agent
        suffix = (self.network_config.user_agent_suffix or "").strip()
        return f"{BROWSER_USER_AGENT} {suffix}".strip()

    @property
    def user_agent(self) -> str:
        return self.session.headers.get("User-Agent", "")

    @property
    def robots_user_agent(self) -> str:
        """robots.txt の照合に使う製品トークン

        UA 全体は互換性のためブラウザ表記を含むため、robots.txt の
        User-agent 行とは自分の名前（例 ippi-down）で照合する。
        """
        source = self.network_config.user_agent or self.network_config.user_agent_suffix or ""
        token = source.strip().split(" ")[0].split("/")[0].strip()
        return token or self.user_agent

    def _check_url(self, url: str, method: str = "GET") -> str:
        """スキームとホストを許可リストと照合し、違反なら送信前に中止する"""
        parsed = urlparse(url or "")
        scheme = (parsed.scheme or "").casefold()
        host = (parsed.hostname or "").casefold()
        allowed_schemes = {str(s).casefold() for s in self.network_config.allowed_schemes}

        reason = ""
        if not scheme or not host:
            reason = "URLの形式が不正です"
        elif scheme not in allowed_schemes:
            reason = f"許可されていないスキームです（許可: {', '.join(sorted(allowed_schemes))}）"
        elif not self._host_allowed(host):
            reason = (
                "許可リストにないホストです"
                f"（許可: {', '.join(self.network_config.allowed_hosts)}）"
            )
        if reason:
            self.logger.warning(f"通信を中止しました: {url} - {reason}")
            self.audit.write(EVENT_BLOCKED, url, method=method, detail=reason)
            raise BlockedRequestError(f"通信ポリシー違反: {url} - {reason}", reason=reason)
        return host

    def _host_allowed(self, host: str) -> bool:
        for pattern in self.network_config.allowed_hosts:
            allowed = str(pattern).strip().rstrip(".").casefold()
            if not allowed:
                continue
            if allowed.startswith("*."):
                if host == allowed[2:] or host.endswith(allowed[1:]):
                    return True
            elif host == allowed:
                return True
        return False

    def _fetch_robots(self, robots_url: str) -> Tuple[Optional[int], str]:
        """robots.txt を取得する（robots 判定自体は行わない）"""
        self._check_url(robots_url, method="GET")
        response = self.session.get(robots_url, timeout=self.timeout)
        return response.status_code, response.text

    def _check_robots(self, url: str, method: str) -> None:
        """robots.txt の Disallow を確認し、Crawl-delay を最小間隔へ反映する"""
        if not self.network_config.robots.enabled:
            return
        host = urlparse(url).hostname or ""
        agent = self.robots_user_agent
        delay = self.robots.crawl_delay(agent, url)
        if delay:
            self.rate_limiter.set_min_interval(host, delay)
        if self.robots.can_fetch(agent, url):
            return
        reason = "robots.txt により取得が禁止されています"
        self.logger.warning(f"{reason}: {url}")
        self.audit.write(EVENT_ROBOTS_DENIED, url, method=method, detail=reason)
        raise BlockedRequestError(f"{reason}: {url}", reason="robots_denied")

    def _before_request(self, method: str, url: str) -> str:
        """URL検査 → robots 判定 → レート制限。戻り値はホスト名。"""
        host = self._check_url(url, method=method)
        self._check_robots(url, method)
        self.rate_limiter.acquire(host)
        return host

    def _after_response(
        self,
        method: str,
        url: str,
        host: str,
        response: Optional[requests.Response],
        started: float,
    ) -> None:
        """送信結果を監査ログへ記録し、429 なら以後の間隔を延ばす"""
        elapsed_ms = (time.time() - started) * 1000
        status = response.status_code if response is not None else None
        size = None
        if response is not None:
            length = response.headers.get("Content-Length")
            if length and str(length).isdigit():
                size = int(length)
        event = EVENT_RATE_LIMITED if status == 429 else EVENT_ALLOW
        if status == 429:
            self.rate_limiter.note_rate_limited(host)
        self.audit.write(
            event, url, method=method, status=status, size=size, elapsed_ms=elapsed_ms
        )

    def get(self, url: str, max_retries: int = 3, **kwargs) -> requests.Response:
        """GETリクエストを送信"""
        return self._request_with_retry(
            "GET", url, max_retries=max_retries, **kwargs
        )

    def post(self, url: str, data: Optional[Dict] = None, max_retries: int = 3, **kwargs) -> requests.Response:
        """POSTリクエストを送信"""
        return self._request_with_retry(
            "POST", url, max_retries=max_retries, data=data, **kwargs
        )

    def _request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> requests.Response:
        """GET/POST 共通のリトライ付きリクエスト"""
        retry_delay = 1

        for attempt in range(max_retries):
            host = self._before_request(method, url)
            started = time.time()
            try:
                if method == "GET":
                    response = self.session.get(url, timeout=self.timeout, **kwargs)
                else:
                    response = self.session.post(url, timeout=self.timeout, **kwargs)
                self._after_response(method, url, host, response, started)

                if response.status_code == 429:
                    retry_after = int(
                        response.headers.get("Retry-After", retry_delay * (attempt + 1))
                    )
                    if attempt < max_retries - 1:
                        self.logger.warning(
                            f"レート制限に達しました。{retry_after}秒後にリトライします... "
                            f"(試行 {attempt + 1}/{max_retries})"
                        )
                        time.sleep(retry_after)
                        continue
                    raise RateLimitError(
                        f"レート制限に達しました: {url}",
                        retry_after=retry_after,
                    )

                response.raise_for_status()
                return response

            except RateLimitError:
                raise
            except requests.exceptions.Timeout as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"{method}リクエストタイムアウト: {url} - {str(e)}")
                    raise NetworkError(f"リクエストタイムアウト: {url} - {str(e)}")
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(
                    f"リクエストタイムアウト。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            except requests.exceptions.ConnectionError as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"{method}リクエスト接続エラー: {url} - {str(e)}")
                    raise NetworkError(self._format_network_error(url, e))
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(
                    f"リクエスト接続エラー。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"{method}リクエストエラー: {url} - {str(e)}")
                    raise NetworkError(self._format_network_error(url, e))
                wait_time = retry_delay * (attempt + 1)
                self.logger.warning(
                    f"リクエストエラー。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            finally:
                self.rate_limiter.release(host)

        raise requests.exceptions.RequestException("最大リトライ回数に達しました")

    def _format_network_error(self, url: str, error: Exception) -> str:
        """接続エラーメッセージを整形（SSL ヒント付き）"""
        message = f"接続エラー: {url} - {str(error)}"
        hint = ssl_error_hint(str(error))
        if hint:
            message = f"{message} {hint}"
        return message

    def download_file(
        self,
        url: str,
        save_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_retries: int = 3,
        referer: Optional[str] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> tuple[bool, dict]:
        """ファイルをダウンロード
        
        Args:
            url: ダウンロードURL
            save_path: 保存先パス（.part拡張子は自動付与、成功時にリネーム）
            progress_callback: 進捗コールバック関数
            max_retries: 最大リトライ回数
            referer: リファラーヘッダー（元のページURL）
            cancel_flag: キャンセルチェック関数（Trueを返すと中断）
        
        Returns:
            (success: bool, error_info: dict)
            - success: ダウンロード成功時True
            - error_info: 失敗時のエラー情報（成功時は空辞書）
                - http_status: HTTPステータスコード
                - error_type: エラー種別（network, rate_limit, http_4xx, http_5xx, filesystem, other）
                - exception_type: 例外クラス名
                - retry_attempts: 実際に試行した回数
        """
        retry_delay = 1
        
        # ダウンロード用のヘッダーを準備（ブラウザと同じヘッダーを設定）
        from urllib.parse import urlparse
        download_headers = {
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",  # br を削除（Brotli 対応なし）
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        
        # RefererとOriginが指定されている場合は追加
        if referer:
            download_headers["Referer"] = referer
            parsed_referer = urlparse(referer)
            origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
            download_headers["Origin"] = origin
            # Sec-Fetch-*ヘッダー（モダンブラウザで使用）
            download_headers["Sec-Fetch-Site"] = "same-site" if parsed_referer.netloc.endswith(".i-ppi.jp") else "cross-site"
            download_headers["Sec-Fetch-Mode"] = "navigate"
            download_headers["Sec-Fetch-Dest"] = "document"
            download_headers["Sec-Fetch-User"] = "?1"
        
        for attempt in range(max_retries):
            # 通信ポリシー（許可先・robots・レート制限）を通す
            host = self._before_request("GET", url)
            started = time.time()
            try:
                # DEBUG: ダウンロード開始情報をログ出力
                self.logger.debug(
                    f"ダウンロード開始: URL='{url[:100]}...', "
                    f"保存先='{save_path}', "
                    f"試行={attempt + 1}/{max_retries}, "
                    f"Referer='{referer[:80] if referer else 'N/A'}...'"
                )
                
                # 接続タイムアウトと読み取りタイムアウトを分離
                # 接続タイムアウト: 10秒、読み取りタイムアウト: download_timeout秒
                timeout_tuple = (10, self.download_timeout)
                
                response = self.session.get(
                    url,
                    stream=True,
                    timeout=timeout_tuple,
                    headers=download_headers,
                    allow_redirects=True  # リダイレクトを確実に追従
                )
                self._after_response("GET", url, host, response, started)

                # DEBUG: レスポンス情報をログ出力
                self.logger.debug(
                    f"ダウンロードレスポンス: status={response.status_code}, "
                    f"Content-Type={response.headers.get('Content-Type', 'N/A')}, "
                    f"Content-Disposition={response.headers.get('Content-Disposition', 'N/A')}, "
                    f"Content-Length={response.headers.get('Content-Length', 'N/A')}"
                )
                
                # HTTPステータス429（レート制限）の処理
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', retry_delay * (attempt + 1)))
                    if attempt < max_retries - 1:
                        self.logger.warning(f"レート制限に達しました。{retry_after}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                        time.sleep(retry_after)
                        continue
                    else:
                        raise RateLimitError(
                            f"レート制限に達しました: {url}",
                            retry_after=retry_after
                        )
                else:
                    response.raise_for_status()

                # Content-Typeをチェック（HTMLの場合は失敗扱い）
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" in content_type:
                    self.logger.warning(
                        f"ダウンロードしたファイルがHTMLです: URL='{url[:100]}...', "
                        f"Content-Type={content_type}, "
                        f"保存先='{save_path}'"
                    )
                    if attempt == max_retries - 1:
                        # HTMLレスポンスの診断情報を保存
                        try:
                            html_body = response.text[:2000]
                            diag_dir = Path("logs/html_diagnostics")
                            diag_dir.mkdir(parents=True, exist_ok=True)
                            from urllib.parse import urlparse, parse_qs
                            parsed = urlparse(url)
                            qs = parse_qs(parsed.query)
                            suffix = qs.get("BunshoKanriId", ["unknown"])[0]
                            anken = qs.get("AnkenKanriNo", ["unknown"])[0][-8:]
                            diag_file = diag_dir / f"failed_{anken}_{suffix}.html"
                            with open(diag_file, "w", encoding="utf-8") as df:
                                df.write(response.text)
                            self.logger.error(
                                f"ダウンロード失敗（HTMLレスポンス）: URL='{url[:100]}...'\n"
                                f"  診断HTML保存先: {diag_file}\n"
                                f"  HTML先頭: {html_body[:200]}..."
                            )
                        except Exception:
                            self.logger.error(f"ダウンロード失敗（HTMLレスポンス）: URL='{url[:100]}...'")
                        return (False, {
                            "http_status": response.status_code,
                            "error_type": "other",
                            "exception_type": "HTMLResponse",
                            "retry_attempts": attempt + 1,
                        })
                    wait_time = retry_delay * (2 ** attempt)
                    self.logger.warning(f"HTMLレスポンス。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue

                # 保存先ディレクトリを作成
                save_path_obj = Path(save_path)
                save_path_obj.parent.mkdir(parents=True, exist_ok=True)
                
                # .partファイルとして保存（FR-006-1）
                part_path = str(save_path_obj) + ".part"
                part_path_obj = Path(part_path)

                total_size = int(response.headers.get("content-length", 0))
                downloaded_size = 0
                start_time = time.time()
                last_progress_time = start_time
                last_progress_size = 0

                # 先頭数バイトをチェック（HTMLの場合は失敗扱い）
                first_chunk_received = False
                html_detected = False
                cancelled = False
                with open(part_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        # キャンセルチェック（FR-006-1）
                        if cancel_flag and cancel_flag():
                            self.logger.info(f"ダウンロードがキャンセルされました: {url}")
                            cancelled = True
                            break
                        
                        if chunk:
                            # 最初のチャンクでHTML判定
                            if not first_chunk_received:
                                first_chunk_received = True
                                if chunk.startswith(b"<html") or chunk.startswith(b"<!DOCTYPE") or chunk.startswith(b"<HTML"):
                                    self.logger.warning(f"ダウンロードしたファイルがHTMLです（先頭バイト判定）: {url}")
                                    f.close()
                                    part_path_obj.unlink(missing_ok=True)  # ファイルを削除
                                    html_detected = True
                                    break  # リトライループに戻る
                            
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
                
                # キャンセルされた場合（.partファイルの扱いは呼び出し側で制御、FR-006-1）
                if cancelled:
                    # .partファイルは残す（呼び出し側でkeep_part_on_cancelに従って削除）
                    return (False, {
                        "http_status": response.status_code,
                        "error_type": "other",
                        "exception_type": "Cancelled",
                        "retry_attempts": attempt + 1,
                    })
                
                # HTML判定で中断された場合はリトライループに戻る
                if html_detected:
                    if attempt == max_retries - 1:
                        return (False, {
                            "http_status": response.status_code,
                            "error_type": "other",
                            "exception_type": "HTMLResponse",
                            "retry_attempts": attempt + 1,
                        })
                    wait_time = retry_delay * (2 ** attempt)
                    self.logger.warning(f"HTMLレスポンス（先頭バイト）。{wait_time}秒後にリトライします... (試行 {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue

                # 成功時: .partファイルをリネーム（FR-006-1）
                try:
                    if part_path_obj.exists():
                        part_path_obj.rename(save_path_obj)
                except Exception as e:
                    self.logger.error(f".partファイルのリネームに失敗: {part_path} -> {save_path} - {str(e)}")
                    return (False, {
                        "http_status": response.status_code,
                        "error_type": "filesystem",
                        "exception_type": type(e).__name__,
                        "retry_attempts": attempt + 1,
                    })

                # DEBUG: ダウンロード完了情報をログ出力
                file_size = save_path_obj.stat().st_size if save_path_obj.exists() else 0
                self.logger.debug(
                    f"ダウンロード完了: URL='{url[:100]}...', "
                    f"保存先='{save_path}', "
                    f"ファイルサイズ={file_size:,} bytes, "
                    f"Content-Type={content_type}"
                )
                self.logger.info(f"ファイルダウンロード完了: {save_path}")
                return (True, {})

            except RateLimitError as e:
                # 429エラーは既に処理済み（上記でreturnしている）
                raise
            except requests.exceptions.Timeout as e:
                # タイムアウトエラーの詳細な処理
                error_type = "接続タイムアウト" if "connect" in str(e).lower() else "読み取りタイムアウト"
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"ファイルダウンロードタイムアウト: {url} - {error_type} "
                        f"(タイムアウト設定: {self.download_timeout}秒)"
                    )
                    return (False, {
                        "http_status": None,
                        "error_type": "network",
                        "exception_type": type(e).__name__,
                        "retry_attempts": attempt + 1,
                    })
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
                    return (False, {
                        "http_status": None,
                        "error_type": "network",
                        "exception_type": type(e).__name__,
                        "retry_attempts": attempt + 1,
                    })
                wait_time = retry_delay * (2 ** attempt)
                self.logger.warning(
                    f"ダウンロード接続エラー。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            except requests.exceptions.HTTPError as e:
                # HTTPエラー（4xx, 5xx）
                status_code = e.response.status_code if e.response else None
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"ファイルダウンロードHTTPエラー: {url} - {status_code} - {str(e)}"
                    )
                    error_type = "rate_limit" if status_code == 429 else \
                                "http_5xx" if status_code and 500 <= status_code < 600 else \
                                "http_4xx" if status_code and 400 <= status_code < 500 else \
                                "other"
                    return (False, {
                        "http_status": status_code,
                        "error_type": error_type,
                        "exception_type": type(e).__name__,
                        "retry_attempts": attempt + 1,
                    })
                wait_time = retry_delay * (2 ** attempt)
                self.logger.warning(
                    f"ダウンロードHTTPエラー ({status_code})。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"ファイルダウンロードエラー: {url} - {str(e)} "
                        f"(エラータイプ: {type(e).__name__})"
                    )
                    return (False, {
                        "http_status": None,
                        "error_type": "network",
                        "exception_type": type(e).__name__,
                        "retry_attempts": attempt + 1,
                    })
                # リトライ前に待機（指数バックオフ）
                wait_time = retry_delay * (2 ** attempt)
                self.logger.warning(
                    f"ダウンロードエラー。{wait_time}秒後にリトライします... "
                    f"(試行 {attempt + 1}/{max_retries}, エラー: {type(e).__name__})"
                )
                time.sleep(wait_time)
            except Exception as e:
                from ..app.exceptions import FilesystemError
                self.logger.error(
                    f"ファイル保存エラー: {save_path} - {str(e)} "
                    f"(エラータイプ: {type(e).__name__})"
                )
                # FilesystemErrorとして再発生させる（呼び出し側で処理可能）
                if attempt == max_retries - 1:
                    return (False, {
                        "http_status": None,
                        "error_type": "filesystem",
                        "exception_type": type(e).__name__,
                        "retry_attempts": attempt + 1,
                    })
                return (False, {
                    "http_status": None,
                    "error_type": "filesystem",
                    "exception_type": type(e).__name__,
                    "retry_attempts": attempt + 1,
                })
            finally:
                self.rate_limiter.release(host)

        return (False, {
            "http_status": None,
            "error_type": "other",
            "exception_type": "",
            "retry_attempts": max_retries,
        })

    def get_session(self) -> requests.Session:
        """セッションを取得"""
        return self.session

    def close(self):
        """セッションをクローズ"""
        self.session.close()

