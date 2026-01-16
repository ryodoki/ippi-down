"""ファイルダウンロードを行うクラス"""

from typing import List, Optional, Callable
from pathlib import Path
from ..models.file_info import FileInfo
from ..models.download_task import DownloadTask
from ..models.download_result import DownloadResult
from ..utils.http_client import HTTPClient
from ..utils.logger import Logger
from ..utils.file_utils import FileUtils
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests


class Downloader:
    """ファイルダウンロードを行うクラス"""

    def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None):
        """初期化"""
        self.http_client = http_client
        self.logger = logger or Logger()
        self.file_utils = FileUtils()

    def download_file(
        self, file_info: FileInfo, save_path: str, progress_callback: Optional[Callable] = None
    ) -> bool:
        """ファイルをダウンロード"""
        try:
            # ディレクトリを作成
            save_path_obj = Path(save_path)
            save_path_obj.parent.mkdir(parents=True, exist_ok=True)

            # リファラーを設定（元のページURLから）
            referer = file_info.page_url if file_info.page_url else None

            # ダウンロード実行
            success = self.http_client.download_file(
                file_info.url, save_path, progress_callback, referer=referer
            )

            if success:
                self.logger.info(f"ダウンロード完了: {save_path}")
            else:
                self.logger.error(f"ダウンロード失敗: {save_path}")

            return success

        except Exception as e:
            self.logger.error(f"ダウンロードエラー: {save_path} - {str(e)}")
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
            requests.exceptions.RequestException,
            requests.exceptions.HTTPError,
        )),
    )
    def download_files(
        self,
        file_list: List[FileInfo],
        save_dir: str,
        naming,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        folder_name: Optional[str] = None,
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
                # 各ファイルごとにフォルダ名を生成
                file_folder_name = naming.generate_folder_name(file_info)
                file_save_dir = save_dir_path / file_folder_name
                file_save_dir.mkdir(parents=True, exist_ok=True)
                
                # ファイル名を生成
                filename = naming.generate_filename(file_info, file_info.metadata, index)
                save_path = str(file_save_dir / filename)

                # 重複チェック
                if self.check_duplicate(save_path):
                    self.logger.info(f"スキップ（既に存在）: {save_path}")
                    task = DownloadTask(
                        file_info=file_info,
                        local_path=save_path,
                        status="skipped",
                    )
                    result.add_task(task)
                    result.update_status(task)
                    continue

                # 一意なパスを確保
                save_path = naming.ensure_unique(save_path)

                # 進捗コールバック
                def progress_wrapper(downloaded, total):
                    if progress_callback:
                        progress_callback(index + 1, len(file_list), file_info.filename)

                # ダウンロードタスクを作成
                task = DownloadTask(file_info=file_info, local_path=save_path)
                task.mark_downloading()

                # ダウンロード実行
                success = self.download_file(file_info, save_path, progress_wrapper)

                if success:
                    task.mark_completed()
                else:
                    task.mark_failed("ダウンロードに失敗しました")

                result.add_task(task)
                result.update_status(task)

            except Exception as e:
                self.logger.error(f"ファイルダウンロードエラー: {file_info.url} - {str(e)}")
                task = DownloadTask(
                    file_info=file_info,
                    local_path="",
                    status="failed",
                    error_message=str(e),
                )
                result.add_task(task)
                result.update_status(task)

        self.logger.info(
            f"ダウンロード完了: 成功={result.success}, 失敗={result.failed}, スキップ={result.skipped}"
        )
        return result

    def retry_download(self, file_info: FileInfo, save_path: str, max_retries: int = 3) -> bool:
        """ダウンロードをリトライ"""
        for attempt in range(max_retries):
            self.logger.info(f"リトライ {attempt + 1}/{max_retries}: {save_path}")
            if self.download_file(file_info, save_path):
                return True
        return False

    def check_duplicate(self, file_path: str) -> bool:
        """ファイルが既に存在するかチェック"""
        return Path(file_path).exists()

