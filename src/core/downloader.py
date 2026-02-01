# -*- coding: utf-8 -*-

"""ファイルダウンロードを行うクラス"""

from typing import List, Optional, Callable
from pathlib import Path
import json
from ..models.file_info import FileInfo
from ..models.download_task import DownloadTask
from ..models.download_result import DownloadResult
from ..utils.http_client import HTTPClient
from ..utils.logger import Logger
from ..utils.file_utils import FileUtils
from .download_history import DownloadHistory
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests


class Downloader:
    """ファイルダウンロードを行うクラス"""

    def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None, history_file: Optional[str] = None):
        """初期化
        
        Args:
            http_client: HTTPクライアント
            logger: ロガーインスタンス
            history_file: ダウンロード履歴ファイルのパス（FR-008）
        """
        self.http_client = http_client
        self.logger = logger or Logger()
        self.file_utils = FileUtils()
        self.history = DownloadHistory(history_file or "logs/download_history.jsonl", self.logger)

    def download_file(
        self, file_info: FileInfo, save_path: str, progress_callback: Optional[Callable] = None,
        cancel_flag: Optional[Callable[[], bool]] = None
    ) -> tuple[bool, dict]:
        """ファイルをダウンロード
        
        Returns:
            (success: bool, error_info: dict)
            - success: ダウンロード成功時True
            - error_info: 失敗時のエラー情報（成功時は空辞書）
        """
        try:
            # ディレクトリを作成
            save_path_obj = Path(save_path)
            save_path_obj.parent.mkdir(parents=True, exist_ok=True)

            # PostBackリンクの場合は特別な処理
            if file_info.metadata and file_info.metadata.get("postback"):
                success = self._download_postback_file(file_info, save_path, progress_callback, cancel_flag)
                if success:
                    return (True, {})
                else:
                    # キャンセルされた場合
                    if cancel_flag and cancel_flag():
                        return (False, {
                            "http_status": None,
                            "error_type": "other",
                            "exception_type": "Cancelled",
                            "retry_attempts": 0,
                        })
                    return (False, {
                        "http_status": None,
                        "error_type": "other",
                        "exception_type": "PostBackError",
                        "retry_attempts": 0,
                    })

            # 通常のURLダウンロード
            # リファラーを設定（元のページURLから）
            referer = file_info.page_url if file_info.page_url else None

            # ダウンロード実行（HTTPClient側でリトライ処理済み）
            success, error_info = self.http_client.download_file(
                file_info.url, save_path, progress_callback, referer=referer, cancel_flag=cancel_flag
            )

            if success:
                self.logger.info(f"ダウンロード完了: {save_path}")
            else:
                # 失敗理由を記録
                error_msg = f"ダウンロードに失敗しました: {save_path}"
                if not hasattr(file_info, '_last_error'):
                    file_info._last_error = error_msg
                self.logger.error(error_msg)

            return (success, error_info)

        except requests.exceptions.RequestException as e:
            # ネットワークエラーは再送出（リトライ可能）
            error_msg = f"ネットワークエラー: {save_path} - {str(e)}"
            if not hasattr(file_info, '_last_error'):
                file_info._last_error = error_msg
            self.logger.warning(error_msg)
            raise  # 例外を再送出してリトライ可能にする
        except Exception as e:
            # その他の例外も再送出
            error_msg = f"ダウンロードエラー: {save_path} - {str(e)}"
            if not hasattr(file_info, '_last_error'):
                file_info._last_error = error_msg
            self.logger.error(error_msg, exc_info=True)
            raise  # 例外を再送出

    def _download_postback_file(
        self, file_info: FileInfo, save_path: str, progress_callback: Optional[Callable] = None,
        cancel_flag: Optional[Callable[[], bool]] = None
    ) -> bool:
        """PostBackリンクのファイルをダウンロード
        
        Args:
            file_info: FileInfo（metadataにpostback情報を含む）
            save_path: 保存先パス
            progress_callback: 進捗コールバック関数
        
        Returns:
            ダウンロード成功時True、失敗時False
        """
        try:
            postback_info = file_info.metadata.get("postback_info", {})
            event_target = postback_info.get("event_target")
            event_argument = postback_info.get("event_argument")
            postback_href = postback_info.get("postback_href")
            page_url = file_info.page_url
            
            if not event_target or not page_url:
                self.logger.error(
                    f"PostBackダウンロードに必要な情報が不足しています: "
                    f"event_target={event_target}, page_url={page_url}"
                )
                return False
            
            self.logger.info(
                f"PostBackでダウンロード開始: 文書名='{file_info.metadata.get('title', 'N/A')}', "
                f"event_target='{event_target}', event_argument='{event_argument}'"
            )
            
            # 元のページを取得してhidden inputを取得
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
            
            # ページを取得
            response = self.http_client.get(page_url)
            if response.status_code != 200:
                self.logger.error(f"PostBackダウンロード: 元のページを取得できませんでした: {page_url} (status={response.status_code})")
                return False
            
            # BeautifulSoupでパース
            response.encoding = response.apparent_encoding or 'utf-8'
            try:
                soup = BeautifulSoup(response.content, "lxml", from_encoding=response.encoding)
            except (UnicodeDecodeError, LookupError):
                try:
                    soup = BeautifulSoup(response.content, "lxml", from_encoding='utf-8')
                except UnicodeDecodeError:
                    soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), "lxml")
            
            if not soup:
                self.logger.error(f"PostBackダウンロード: 元のページをパースできませんでした: {page_url}")
                return False
            
            # hidden inputを取得
            form_data = {}
            for hidden in soup.find_all("input", type="hidden"):
                name = hidden.get("name", "")
                value = hidden.get("value", "")
                if name:
                    form_data[name] = value
            form_data["__EVENTTARGET"] = event_target
            form_data["__EVENTARGUMENT"] = event_argument
            
            # formのaction属性を取得
            form = soup.find("form")
            if form and form.get("action"):
                from urllib.parse import urljoin
                post_url = urljoin(page_url, form.get("action"))
            else:
                post_url = page_url
            
            # PostBackを実行してファイルを取得
            self.logger.debug(f"PostBackを実行: URL='{post_url}', event_target='{event_target}'")
            response = self.http_client.post(post_url, data=form_data)
            
            # Content-Typeをチェック
            content_type = response.headers.get("Content-Type", "").lower()
            content_disposition = response.headers.get("Content-Disposition", "")
            
            self.logger.debug(
                f"PostBackレスポンス: status={response.status_code}, "
                f"Content-Type={content_type}, Content-Disposition={content_disposition}"
            )
            
            # ファイル名をContent-Dispositionから取得
            filename_from_disposition = None
            if content_disposition:
                import re
                match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', content_disposition)
                if match:
                    filename_from_disposition = match.group(1).strip('"\'')
            
            # ファイルタイプをContent-Typeから推測
            file_type = file_info.file_type
            if not file_type or file_type == ".pdf":
                if "pdf" in content_type:
                    file_type = ".pdf"
                elif "excel" in content_type or "spreadsheet" in content_type:
                    file_type = ".xlsx"
                elif "word" in content_type or "document" in content_type:
                    file_type = ".docx"
            
            # ファイルを保存（.partファイルとして保存、成功時にリネーム、FR-006-1）
            save_path_obj = Path(save_path)
            if filename_from_disposition and not save_path_obj.suffix:
                # Content-Dispositionから取得したファイル名を使用（拡張子がない場合）
                save_path = str(save_path_obj.parent / filename_from_disposition)
                save_path_obj = Path(save_path)
            
            # キャンセルチェック（FR-006-1）
            if cancel_flag and cancel_flag():
                self.logger.info(f"PostBackダウンロードがキャンセルされました: {save_path}")
                return False
            
            # .partファイルとして保存
            part_path = str(save_path_obj) + ".part"
            part_path_obj = Path(part_path)
            
            with open(part_path, "wb") as f:
                f.write(response.content)
            
            # 成功時: .partファイルをリネーム（FR-006-1）
            try:
                if part_path_obj.exists():
                    part_path_obj.rename(save_path_obj)
            except Exception as e:
                self.logger.error(f".partファイルのリネームに失敗: {part_path} -> {save_path} - {str(e)}")
                return False
            
            file_size = Path(save_path).stat().st_size
            self.logger.info(
                f"PostBackでダウンロード完了: 保存先='{save_path}', "
                f"ファイルサイズ={file_size:,} bytes, Content-Type={content_type}"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"PostBackダウンロードエラー: 文書名='{file_info.metadata.get('title', 'N/A')}' - {str(e)}",
                exc_info=True
            )
            return False

    def download_files(
        self,
        file_list: List[FileInfo],
        save_dir: str,
        naming,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        folder_name: Optional[str] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
        use_subfolders: bool = True,
        enable_hash_check: bool = False,
        keep_part_on_cancel: bool = True,
    ) -> DownloadResult:
        """複数のファイルをダウンロード
        
        Args:
            file_list: ダウンロード対象のファイルリスト
            save_dir: 保存先ディレクトリ
            naming: ファイル名生成オブジェクト
            progress_callback: 進捗コールバック関数
            folder_name: サブフォルダ名（指定された場合はサブフォルダを作成）
        """
        result = DownloadResult(total=len(file_list))
        save_dir_path = Path(save_dir)
        
        # ベースディレクトリを作成
        save_dir_path.mkdir(parents=True, exist_ok=True)

        for index, file_info in enumerate(file_list):
            # キャンセルチェック（progress_callbackがFalseを返した場合）
            if progress_callback:
                try:
                    # キャンセルチェック用にコールバックを呼び出し
                    # コールバックがFalseを返すか、例外が発生した場合は中断
                    callback_result = progress_callback(index, len(file_list), file_info.filename)
                    if callback_result is False:
                        self.logger.info("ダウンロードがキャンセルされました")
                        break
                except Exception:
                    # コールバックで例外が発生した場合は続行
                    pass
            
            try:
                # ファイル名を生成（元の意図したファイル名、FR-008）
                filename = naming.generate_filename(file_info, file_info.metadata, index)
                
                # サブフォルダの生成（FR-013: 設定でON/OFF）
                if use_subfolders:
                    file_folder_name = naming.generate_folder_name(file_info)
                    file_save_dir = save_dir_path / file_folder_name
                else:
                    file_save_dir = save_dir_path
                file_save_dir.mkdir(parents=True, exist_ok=True)
                
                # 元の意図した保存パス（重複チェック用、FR-008）
                intended_save_path = str(file_save_dir / filename)
                
                # 重複チェック（元の意図したパスで実行、FR-008）
                if self.check_duplicate(file_info, intended_save_path, naming, enable_hash_check):
                    self.logger.info(f"スキップ（重複）: {intended_save_path}")
                    task = DownloadTask(
                        file_info=file_info,
                        local_path=intended_save_path,
                        status="skipped",
                        url=file_info.url,
                    )
                    result.add_task(task)
                    result.update_status(task)
                    continue
                
                # 一意なパスを確保（同名ファイルが存在する場合、連番を付与）
                save_path = naming.ensure_unique(intended_save_path)

                # 進捗コールバック
                def progress_wrapper(downloaded, total):
                    if progress_callback:
                        progress_callback(index + 1, len(file_list), file_info.filename)

                # ダウンロードタスクを作成（FR-005）
                task = DownloadTask(
                    file_info=file_info,
                    local_path=save_path,
                    url=file_info.url,
                )
                task.mark_downloading()

                # ダウンロード実行（HTTPClient側でリトライ処理済み、P0-2）
                try:
                    success, error_info = self.download_file(
                        file_info, save_path, progress_wrapper, cancel_flag=cancel_flag
                    )
                    
                    # エラー情報をDownloadTaskに記録（FR-005）
                    if not success and error_info:
                        task.http_status = error_info.get("http_status")
                        task.error_type = error_info.get("error_type", "other")
                        task.exception_type = error_info.get("exception_type", "")
                        task.retry_attempts = error_info.get("retry_attempts", 0)
                except requests.exceptions.RequestException as e:
                    # ネットワークエラー（HTTPClient側でリトライ済みだが、例外が発生した場合）
                    self.logger.warning(f"ダウンロードエラー: {file_info.filename} - {str(e)}")
                    success = False
                    error_info = {
                        "http_status": None,
                        "error_type": "network",
                        "exception_type": type(e).__name__,
                        "retry_attempts": 0,
                    }
                    task.http_status = error_info.get("http_status")
                    task.error_type = error_info.get("error_type")
                    task.exception_type = error_info.get("exception_type")
                    task.retry_attempts = error_info.get("retry_attempts")
                except Exception as e:
                    # その他の例外
                    self.logger.error(f"ダウンロードエラー（リトライ不可）: {file_info.filename} - {str(e)}", exc_info=True)
                    success = False
                    error_info = {
                        "http_status": None,
                        "error_type": "other",
                        "exception_type": type(e).__name__,
                        "retry_attempts": 0,
                    }
                    task.http_status = error_info.get("http_status")
                    task.error_type = error_info.get("error_type")
                    task.exception_type = error_info.get("exception_type")
                    task.retry_attempts = error_info.get("retry_attempts")

                if success:
                    task.mark_completed()
                    # ダウンロード履歴を記録（FR-008）
                    try:
                        file_size = Path(save_path).stat().st_size if Path(save_path).exists() else 0
                        file_hash = None
                        if enable_hash_check:
                            file_hash = self.history.calculate_file_hash(save_path)
                        self.history.add_record(
                            url=file_info.url,
                            filename=file_info.filename,
                            file_path=save_path,
                            file_size=file_size,
                            file_hash=file_hash,
                            status="completed",
                        )
                    except Exception as e:
                        self.logger.warning(f"ダウンロード履歴の記録に失敗: {str(e)}")
                else:
                    # 最終的な失敗理由を取得
                    error_message = "ダウンロードに失敗しました"
                    if hasattr(file_info, '_last_error'):
                        error_message = file_info._last_error
                    task.mark_failed(error_message)
                    
                    # キャンセル時の.partファイルの扱い（FR-006-1）
                    if not keep_part_on_cancel and error_info.get("exception_type") == "Cancelled":
                        part_path = Path(save_path + ".part")
                        if part_path.exists():
                            try:
                                part_path.unlink()
                                self.logger.debug(f"キャンセル時の.partファイルを削除: {part_path}")
                            except Exception as e:
                                self.logger.warning(f"キャンセル時の.partファイル削除に失敗: {part_path} - {str(e)}")
                    
                    # 失敗履歴も記録（FR-008）
                    try:
                        self.history.add_record(
                            url=file_info.url,
                            filename=file_info.filename,
                            file_path=save_path,
                            file_size=0,
                            file_hash=None,
                            status="failed",
                            error_message=error_message,
                        )
                    except Exception as e:
                        self.logger.warning(f"ダウンロード履歴の記録に失敗: {str(e)}")

                result.add_task(task)
                result.update_status(task)

            except Exception as e:
                # 予期しない例外（ファイル名生成エラー等）
                self.logger.error(f"予期しないエラー: {file_info.filename} - {str(e)}", exc_info=True)
                task = DownloadTask(
                    file_info=file_info,
                    local_path=save_path if 'save_path' in locals() else "",
                    status="failed",
                    error_message=f"予期しないエラー: {str(e)}",
                )
                result.add_task(task)
                result.update_status(task)

        self.logger.info(
            f"ダウンロード完了: 成功={result.success}, 失敗={result.failed}, スキップ={result.skipped}"
        )
        return result

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
            requests.exceptions.RequestException,
            requests.exceptions.HTTPError,
        )),
    )
    def retry_download(self, file_info: FileInfo, save_path: str, max_retries: int = 3) -> tuple[bool, dict]:
        """ダウンロードをリトライ（tenacity デコレータ使用）
        
        download_file が例外を再送出するため、tenacity が自動的にリトライする。
        3回リトライしても失敗した場合は (False, error_info) を返す。
        
        Note: 現在はHTTPClient側でリトライ処理済みのため、このメソッドは使用されていない（P0-2）。
        ただし、外部から呼ばれる可能性があるため残している。
        """
        try:
            # download_file が例外を再送出するため、tenacity が自動的にリトライする
            return self.download_file(file_info, save_path)
        except Exception as e:
            # 最終的な失敗（3回リトライ後も失敗）
            error_msg = f"リトライ後もダウンロードに失敗: {save_path} - {str(e)}"
            if not hasattr(file_info, '_last_error'):
                file_info._last_error = error_msg
            self.logger.error(error_msg)
            return (False, {
                "http_status": None,
                "error_type": "other",
                "exception_type": type(e).__name__,
                "retry_attempts": max_retries,
            })

    def check_duplicate(
        self, file_info: FileInfo, intended_save_path: str, naming, enable_hash_check: bool = False
    ) -> bool:
        """重複チェック（FR-008）
        
        優先順位:
        1. URL同一判定: 過去に成功したURLをスキップ
        2. ファイル名+サイズ判定: 同名+同サイズのファイルが存在する場合はスキップ
        3. ハッシュ判定（オプション）: enable_hash_checkがTrueの場合、MD5ハッシュで比較
        
        Args:
            file_info: ファイル情報
            intended_save_path: 元の意図した保存パス（重複チェック用）
            naming: ファイル名生成オブジェクト
            enable_hash_check: ハッシュ判定を有効化するか
        
        Returns:
            重複している場合True、重複していない場合False
        """
        # 1. URL同一判定（FR-008）
        if file_info.url:
            history_record = self.history.find_by_url(file_info.url)
            if history_record:
                self.logger.debug(f"スキップ（URL同一）: {file_info.url}")
                return True
        
        # 2. ファイル名+サイズ判定（FR-008）
        path = Path(intended_save_path)
        if path.exists() and path.stat().st_size > 0:
            # ファイルサイズが0の場合は再ダウンロード
            if path.stat().st_size == 0:
                self.logger.debug(f"空ファイルを検出、再ダウンロードします: {intended_save_path}")
                try:
                    path.unlink()  # 空ファイルを削除
                except Exception as e:
                    self.logger.warning(f"ファイル削除エラー: {intended_save_path} - {str(e)}")
                return False
            
            # ファイルの先頭バイトをチェック（HTMLかどうか）
            try:
                with open(intended_save_path, 'rb') as f:
                    first_bytes = f.read(100)
                
                # HTMLファイルの場合は再ダウンロード
                if first_bytes.startswith(b'<html') or first_bytes.startswith(b'<!DOCTYPE') or first_bytes.startswith(b'<HTML'):
                    self.logger.debug(f"HTMLファイルを検出、再ダウンロードします: {intended_save_path}")
                    try:
                        path.unlink()  # HTMLファイルを削除
                    except Exception as e:
                        self.logger.warning(f"HTMLファイル削除エラー: {intended_save_path} - {str(e)}")
                    return False
            except Exception as e:
                self.logger.warning(f"ファイルチェックエラー: {intended_save_path} - {str(e)}")
                return False
            
            # ファイル名+サイズで履歴を検索
            filename = path.name
            file_size = path.stat().st_size
            history_record = self.history.find_by_filename_and_size(filename, file_size)
            if history_record:
                self.logger.debug(f"スキップ（ファイル名+サイズ同一）: {filename} ({file_size} bytes)")
                return True
            
            # 3. ハッシュ判定（オプション、FR-008）
            if enable_hash_check:
                file_hash = self.history.calculate_file_hash(intended_save_path)
                if file_hash:
                    # 履歴から同じハッシュのファイルを検索
                    # （簡易実装: 履歴ファイル全体を検索）
                    if self.history.history_file.exists():
                        try:
                            with open(self.history.history_file, "r", encoding="utf-8") as f:
                                for line in reversed(list(f)):
                                    if not line.strip():
                                        continue
                                    record = json.loads(line.strip())
                                    if (record.get("file_hash") == file_hash and
                                        record.get("status") == "completed"):
                                        self.logger.debug(f"スキップ（ハッシュ同一）: {filename} (hash={file_hash[:8]}...)")
                                        return True
                        except Exception as e:
                            self.logger.warning(f"ハッシュ履歴の読み込みに失敗: {str(e)}")
            
            # 有効なファイルとして存在（ファイル名+サイズ判定で一致）
            return True
        
        return False

