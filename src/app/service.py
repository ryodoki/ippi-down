# -*- coding: utf-8 -*-

"""ApplicationService（GUI/CLI共通サービス）"""

from typing import Optional, Callable
from pathlib import Path
from ..models.config_model import AppConfig
from ..models.download_result import DownloadResult
from ..utils.logger import Logger
from ..utils.http_client import HTTPClient
from ..utils.notifier import Notifier
from ..core.scraper import Scraper
from ..core.filter import Filter
from ..core.downloader import Downloader
from ..core.naming import Naming
from .run_result import RunResult
from .events import ProgressEvent, EventType


class ApplicationService:
    """アプリケーションサービス（GUI/CLI共通）"""

    def __init__(self, logger: Logger):
        """初期化"""
        self.logger = logger
        self._http_client: Optional[HTTPClient] = None
        self._scraper: Optional[Scraper] = None
        self._filter: Optional[Filter] = None
        self._naming: Optional[Naming] = None
        self._downloader: Optional[Downloader] = None

    def run(
        self,
        config: AppConfig,
        progress_callback: Optional[Callable[[ProgressEvent], None]] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> RunResult:
        """ダウンロード処理を実行"""
        try:
            # 保存先ディレクトリの作成
            save_dir = Path(config.save_paths.local)
            save_dir.mkdir(parents=True, exist_ok=True)

            # コンポーネントの初期化
            self._initialize_components(config)

            # イベント発行: 開始
            if progress_callback:
                progress_callback(ProgressEvent(
                    type=EventType.START,
                    message="ダウンロードを開始します",
                    total=0
                ))

            # ファイル抽出
            all_files = self._extract_files(config, progress_callback, cancel_flag)
            
            if cancel_flag and cancel_flag():
                return RunResult(
                    success=False,
                    message="ダウンロードがキャンセルされました"
                )

            if not all_files:
                return RunResult(
                    success=False,
                    message="ファイルが見つかりませんでした"
                )

            # フィルタリング
            filtered_files = self._filter_files(all_files, progress_callback)
            
            if cancel_flag and cancel_flag():
                return RunResult(
                    success=False,
                    message="ダウンロードがキャンセルされました"
                )

            if not filtered_files:
                return RunResult(
                    success=False,
                    message="ダウンロード対象のファイルが見つかりませんでした"
                )

            # ダウンロード実行
            result = self._download_files(
                filtered_files,
                config,
                progress_callback,
                cancel_flag
            )

            if cancel_flag and cancel_flag():
                return RunResult(
                    success=False,
                    message="ダウンロードがキャンセルされました"
                )

            # 失敗理由別サマリーを取得（FR-005）
            failure_summary = result.summarize_failures()
            failure_summary_text = ", ".join([
                f"{k}={v}" for k, v in failure_summary.items() if v > 0
            ])
            
            # 結果メッセージ
            result_message = (
                f"ダウンロード完了: 成功={result.success}, "
                f"失敗={result.failed}, スキップ={result.skipped}"
            )
            if failure_summary_text:
                result_message += f" (失敗理由: {failure_summary_text})"
            
            # ログに失敗理由別サマリーを出力（FR-005）
            if result.failed > 0:
                self.logger.info(f"失敗理由別サマリー: {failure_summary_text}")

            # イベント発行: 完了
            if progress_callback:
                progress_callback(ProgressEvent(
                    type=EventType.COMPLETE,
                    message=result_message,
                    current=result.total,
                    total=result.total,
                    metadata={"result": result}  # CLIで使用
                ))

            return RunResult(
                success=True,
                result=result,
                message=result_message
            )

        except Exception as e:
            error_message = f"ダウンロード処理エラー: {str(e)}"
            self.logger.error(error_message)
            
            # イベント発行: エラー
            if progress_callback:
                progress_callback(ProgressEvent(
                    type=EventType.FAIL,
                    message=error_message,
                    error=str(e)
                ))

            return RunResult(
                success=False,
                error=str(e),
                message=error_message
            )
        finally:
            self._cleanup()

    def _initialize_components(self, config: AppConfig):
        """コンポーネントを初期化"""
        self._http_client = HTTPClient(self.logger)
        self._scraper = Scraper(self._http_client, self.logger)
        self._filter = Filter(config.download_conditions, self.logger)
        self._naming = Naming(
            config.naming_rule,
            self.logger,
            config.search_conditions
        )
        self._downloader = Downloader(self._http_client, self.logger)

    def _extract_files(
        self,
        config: AppConfig,
        progress_callback: Optional[Callable[[ProgressEvent], None]],
        cancel_flag: Optional[Callable[[], bool]]
    ):
        """ファイルを抽出"""
        all_files = []
        
        for url in config.target_urls:
            if cancel_flag and cancel_flag():
                break

            self.logger.info(f"ページを解析中: {url}")
            if progress_callback:
                progress_callback(ProgressEvent(
                    type=EventType.MESSAGE,
                    message=f"ページを解析中: {url}",
                    metadata={"type": "info"}
                ))

            # 検索条件のチェック
            has_search_conditions = self._has_search_conditions(config.search_conditions)

            if has_search_conditions:
                # 検索フォームを送信
                if progress_callback:
                    progress_callback(ProgressEvent(
                        type=EventType.MESSAGE,
                        message="検索条件で検索を実行中...",
                        metadata={"type": "info"}
                    ))
                
                soup = self._scraper.submit_search_form(url, config.search_conditions)
                if soup:
                    files = self._scraper.extract_file_links_from_search_results(
                        soup, url, config.download_conditions.file_types, config.search_conditions
                    )
                    all_files.extend(files)
                    # 工事件数（スクレイパーから取得）とファイル数を表示
                    koji_count = getattr(self._scraper, 'last_search_total_koji_count', None)
                    if koji_count is None:
                        # フォールバック: ファイルから取得したユニークな工事名の数
                        koji_names = set()
                        for f in files:
                            if f.metadata and f.metadata.get("koji_name"):
                                koji_names.add(f.metadata["koji_name"])
                        koji_count = len(koji_names) if koji_names else "不明"
                    self.logger.info(f"検索結果: 工事件数={koji_count}件, ファイル数={len(files)}件")
                    if progress_callback:
                        progress_callback(ProgressEvent(
                            type=EventType.MESSAGE,
                            message=f"検索結果: 工事件数={koji_count}件, ファイル数={len(files)}件",
                            metadata={"type": "info"}
                        ))
                else:
                    self.logger.error(f"検索の実行に失敗しました: {url}")
            else:
                # 通常のページ解析
                soup = self._scraper.fetch_page(url)
                if soup:
                    files = self._scraper.extract_file_links(
                        soup, url, config.download_conditions.file_types
                    )
                    all_files.extend(files)
                    self.logger.info(f"{len(files)}個のファイルリンクを発見")
                else:
                    self.logger.error(f"ページの取得に失敗しました: {url}")

        return all_files

    def _has_search_conditions(self, search_conditions) -> bool:
        """検索条件が設定されているかチェック"""
        if not search_conditions:
            return False
        
        sc = search_conditions
        # contract_typesはデフォルトで全選択されているため、空でない場合のみチェック
        # ただし、デフォルト値（全選択）の場合は検索条件として扱わない
        has_contract_types = bool(
            sc.contract_types and 
            len(sc.contract_types) > 0 and
            len(sc.contract_types) < 5  # デフォルトは5つ全て選択されている
        )
        
        return bool(
            (sc.hachu_daibunrui and sc.hachu_daibunrui.strip()) or 
            (sc.hachu_chubunrui and sc.hachu_chubunrui.strip()) or 
            (sc.hachu_shoubunrui and sc.hachu_shoubunrui.strip()) or 
            (sc.hachu_saibunrui and sc.hachu_saibunrui.strip()) or
            (sc.hachu_multi and len(sc.hachu_multi) > 0) or
            (sc.koji_name and sc.koji_name.strip()) or
            (sc.place_search_type == "list" and (sc.place_chihou or sc.place_todofuken or sc.place_shichouson)) or
            (sc.place_search_type == "text" and sc.place_text and sc.place_text.strip()) or
            has_contract_types or
            sc.update_date_type == "past" or
            sc.koukoku_date_type == "range" or
            sc.kaisatsu_date_type == "range" or
            sc.keiyaku_date_type == "range" or
            (sc.koji_shubetsu and sc.koji_shubetsu.strip()) or
            (sc.koji_gyoushu and sc.koji_gyoushu.strip()) or
            sc.yotei_price_min is not None or sc.yotei_price_max is not None or
            sc.rakusatsu_price_min is not None or sc.rakusatsu_price_max is not None or
            (sc.rakusatsu_name and sc.rakusatsu_name.strip()) or
            sc.denshi or
            sc.koukai
        )

    def _filter_files(
        self,
        files,
        progress_callback: Optional[Callable[[ProgressEvent], None]]
    ):
        """ファイルをフィルタリング"""
        filtered = self._filter.filter_files(files)
        
        # 工事件数（ユニークな工事名の数）とファイル数を表示
        koji_names = set()
        for f in filtered:
            if f.metadata and f.metadata.get("koji_name"):
                koji_names.add(f.metadata["koji_name"])
        koji_count = len(koji_names) if koji_names else "不明"
        
        self.logger.info(f"フィルタリング後: 工事件数={koji_count}件, ファイル数={len(filtered)}件")
        
        if progress_callback:
            progress_callback(ProgressEvent(
                type=EventType.MESSAGE,
                message=f"フィルタリング後: 工事件数={koji_count}件, ファイル数={len(filtered)}件",
                metadata={"type": "info"}
            ))
        
        return filtered

    def _download_files(
        self,
        files,
        config: AppConfig,
        progress_callback: Optional[Callable[[ProgressEvent], None]],
        cancel_flag: Optional[Callable[[], bool]]
    ) -> DownloadResult:
        """ファイルをダウンロード"""
        def progress_wrapper(current: int, total: int, filename: str) -> bool:
            """Downloader用の進捗コールバック（boolを返す）"""
            if cancel_flag and cancel_flag():
                return False
            
            if progress_callback:
                progress_callback(ProgressEvent(
                    type=EventType.PROGRESS,
                    message=f"{filename} をダウンロード中...",
                    current=current,
                    total=total,
                    filename=filename
                ))
            return True

        return self._downloader.download_files(
            files,
            config.save_paths.local,
            self._naming,
            progress_wrapper,
            folder_name=None,
            cancel_flag=cancel_flag,
            use_subfolders=config.save_paths.use_subfolders,
            enable_hash_check=config.save_paths.enable_hash_check,
            keep_part_on_cancel=config.save_paths.keep_part_on_cancel,
        )

    def _cleanup(self):
        """リソースをクリーンアップ"""
        if self._http_client:
            self._http_client.close()
