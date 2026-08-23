# -*- coding: utf-8 -*-

"""ApplicationService（GUI/CLI共通サービス）"""

from typing import Optional, Callable
from pathlib import Path
from ..models.config_model import AppConfig
from ..models.download_result import DownloadResult
from ..models.file_info import FileInfo
from ..utils.logger import Logger
from ..utils.http_client import HTTPClient
from ..utils.rate_limiter import reset_shared_limiter
from ..utils.notifier import Notifier
from ..core.scraper import Scraper
from ..core.filter import Filter
from ..core.downloader import Downloader
from ..core.naming import Naming
from ..core.path_builder import build_save_dir as path_builder_build_save_dir
from ..utils.path_utils import resolve_save_path
from .run_result import RunResult
from .events import ProgressEvent, EventType
from .extract_result import ExtractResult


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
            # 保存先を絶対パスに解決（相対の場合は exe/プロジェクトルート基準）
            save_dir = resolve_save_path(config.save_paths.local)
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
            extract_result = self._extract_files(config, progress_callback, cancel_flag)
            all_files = extract_result.files
            
            if cancel_flag and cancel_flag():
                return RunResult(
                    success=False,
                    message="ダウンロードがキャンセルされました"
                )

            if not all_files:
                message = self._build_no_files_message(extract_result)
                # 接続/検索の失敗は赤いエラー表示、それ以外（案件はヒットしたが
                # 添付が公開終了・存在しない等）は警告扱いにして誤解を避ける
                is_connection_failure = extract_result.had_connection_failure
                if progress_callback:
                    progress_callback(ProgressEvent(
                        type=EventType.FAIL if is_connection_failure else EventType.MESSAGE,
                        message=message,
                        metadata=None if is_connection_failure else {"type": "warning"},
                    ))
                return RunResult(
                    success=False,
                    message=message
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

            # ダウンロード実行（save_dir は絶対パス解決済み）
            result = self._download_files(
                filtered_files,
                config,
                progress_callback,
                cancel_flag,
                save_dir=str(save_dir),
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
            save_dirs = result.get_save_directories()
            if save_dirs:
                if len(save_dirs) == 1:
                    result_message += f"\n保存先: {save_dirs[0]}"
                else:
                    result_message += f"\n保存先（{len(save_dirs)}フォルダ）:\n"
                    result_message += "\n".join(f"  - {d}" for d in save_dirs[:5])
                    if len(save_dirs) > 5:
                        result_message += f"\n  ... 他 {len(save_dirs) - 5} 件"
            elif save_dir:
                result_message += f"\n保存先: {save_dir}"

            skip_summary = result.summarize_skips()
            if skip_summary:
                skip_text = ", ".join(f"{k}={v}" for k, v in sorted(skip_summary.items()))
                result_message += f"\nスキップ内訳: {skip_text}"

            completed_paths = result.get_completed_paths(limit=5)
            if completed_paths:
                result_message += "\n新規保存:"
                for p in completed_paths:
                    result_message += f"\n  - {Path(p).name} ({Path(p).parent})"

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
        # max_requests_per_run は「1回の実行」単位なので、実行開始時に数え直す
        reset_shared_limiter()
        self._http_client = HTTPClient(
            self.logger, network_config=getattr(config, "network", None)
        )
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
    ) -> ExtractResult:
        """ファイルを抽出"""
        result = ExtractResult()
        
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

            # Search.aspx の場合は条件の有無にかかわらず検索フォーム送信が必要（条件空だと fetch_page のみだと0件になりやすい）
            is_search_aspx = "Search.aspx" in url
            has_search_conditions = self._has_search_conditions(config.search_conditions)
            if is_search_aspx and not has_search_conditions:
                self.logger.info("検索条件は空ですが Search.aspx のため検索フォームを送信します")

            if is_search_aspx or has_search_conditions:
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
                    result.files.extend(files)
                    # 工事件数（スクレイパーから取得）とファイル数を表示
                    koji_count = getattr(self._scraper, 'last_search_total_koji_count', None)
                    if isinstance(koji_count, int):
                        result.total_koji_count += koji_count
                    if koji_count is None:
                        # フォールバック: ファイルから取得したユニークな工事名の数
                        koji_names = set()
                        for f in files:
                            if f.metadata and f.metadata.get("koji_name"):
                                koji_names.add(f.metadata["koji_name"])
                        koji_count = len(koji_names) if koji_names else "不明"
                    result.unavailable_document_count += getattr(
                        self._scraper, 'last_search_unavailable_document_count', 0
                    ) or 0
                    self.logger.info(f"検索結果: 工事件数={koji_count}件, ファイル数={len(files)}件")
                    if progress_callback:
                        progress_callback(ProgressEvent(
                            type=EventType.MESSAGE,
                            message=f"検索結果: 工事件数={koji_count}件, ファイル数={len(files)}件",
                            metadata={"type": "info"}
                        ))
                else:
                    self.logger.error(f"検索の実行に失敗しました: {url}")
                    result.search_failed_urls.append(url)
            else:
                # 通常のページ解析（Search.aspx 以外で条件なしの場合）
                soup = self._scraper.fetch_page(url)
                if soup:
                    files = self._scraper.extract_file_links(
                        soup, url, config.download_conditions.file_types
                    )
                    result.files.extend(files)
                    self.logger.info(f"{len(files)}個のファイルリンクを発見")
                else:
                    self.logger.error(f"ページの取得に失敗しました: {url}")
                    result.fetch_failed_urls.append(url)

        return result

    def _build_no_files_message(self, extract_result: ExtractResult) -> str:
        """ファイル0件時のユーザー向けメッセージを生成"""
        if extract_result.search_failed_urls:
            return (
                "サイトへの接続または検索の実行に失敗しました。"
                "ネットワーク接続と SSL 証明書設定を確認してください。"
            )
        if extract_result.fetch_failed_urls:
            return (
                "対象ページの取得に失敗しました。"
                "ネットワーク接続と SSL 証明書設定を確認してください。"
            )

        koji_count = extract_result.total_koji_count
        unavailable = extract_result.unavailable_document_count

        if koji_count and koji_count > 0:
            # 案件はヒットしている＝検索・接続は成功。添付が無い/公開終了が原因。
            if unavailable and unavailable > 0:
                return (
                    f"検索で{koji_count}件ヒットしましたが、公開文書が{unavailable}件すべて"
                    "「公開終了」のためダウンロードできるファイルがありませんでした。"
                    "検索条件（発注機関の細分類・期間など）を見直すか、公開中の案件を対象にしてください。"
                )
            return (
                f"検索で{koji_count}件ヒットしましたが、ダウンロード可能な添付ファイルが"
                "ありませんでした（添付なし、または公開終了の可能性）。"
                "検索条件を見直してください。"
            )
        return (
            "検索条件に一致する案件が見つかりませんでした。"
            "検索条件（発注機関・工事名・期間など）を見直してください。"
        )

    def _has_search_conditions(self, search_conditions) -> bool:
        """検索条件が設定されているかチェック"""
        if not search_conditions:
            return False
        return not search_conditions.is_effectively_empty()

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
        cancel_flag: Optional[Callable[[], bool]],
        save_dir: Optional[str] = None,
    ) -> DownloadResult:
        """ファイルをダウンロード。save_dir は run() で絶対パス解決済みを渡す。"""
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

        base_save_dir = save_dir if save_dir else config.save_paths.local
        folder_name = self._compute_run_folder_name(config) if getattr(
            config.save_paths, "run_subfolder_mode", "none"
        ) != "none" else None

        build_save_dir_fn = None
        if getattr(config.save_paths, "enable_agency_root_folders", False):
            def _build_fn(base: Path, file_info: FileInfo):
                return path_builder_build_save_dir(base, file_info, config, self.logger)
            build_save_dir_fn = _build_fn

        return self._downloader.download_files(
            files,
            base_save_dir,
            self._naming,
            progress_wrapper,
            folder_name=folder_name,
            cancel_flag=cancel_flag,
            use_subfolders=config.save_paths.use_subfolders,
            enable_hash_check=config.save_paths.enable_hash_check,
            keep_part_on_cancel=config.save_paths.keep_part_on_cancel,
            build_save_dir_fn=build_save_dir_fn,
        )

    def _compute_run_folder_name(self, config: AppConfig) -> Optional[str]:
        """実行単位のルートフォルダ名を生成（run_subfolder_mode に従う）"""
        mode = getattr(config.save_paths, "run_subfolder_mode", "none")
        if not mode or mode == "none":
            return None
        if mode == "datetime":
            from datetime import datetime
            return datetime.now().strftime("%Y%m%d_%H%M%S")
        if mode == "search":
            sc = config.search_conditions
            parts = []
            if sc.hachu_daibunrui:
                parts.append(sc.hachu_daibunrui)
            if sc.hachu_chubunrui:
                parts.append(sc.hachu_chubunrui)
            if sc.koji_name:
                parts.append(sc.koji_name)
            if not parts:
                from datetime import datetime
                return datetime.now().strftime("%Y%m%d_%H%M%S")
            from ..utils.file_utils import FileUtils
            raw = "_".join(parts).strip()
            return FileUtils.sanitize_filename(raw) or "run"
        return None

    def _cleanup(self):
        """リソースをクリーンアップ"""
        if self._http_client:
            self._http_client.close()
