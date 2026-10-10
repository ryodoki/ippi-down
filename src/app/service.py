# -*- coding: utf-8 -*-

"""ApplicationService（GUI/CLI共通サービス）"""

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Callable, List, Optional
import uuid
from ..models.config_model import AppConfig
from ..models.download_diagnostics import (
    DownloadIssueCode,
    IssueSeverity,
    RedownloadPolicy,
)
from ..models.download_result import DownloadResult
from ..models.file_info import FileInfo
from ..models.search_summary import (
    DocumentDecision,
    SearchExtractionSummary,
)
from ..utils.logger import Logger
from ..utils.http_client import HTTPClient
from ..utils.path_utils import resolve_app_path
from ..storage.layout import RunKind, resolve_run_root
from ..core.scraper import (
    RequestFailureDiagnostic,
    Scraper,
    SearchProgress,
    classify_request_failure,
)
from ..core.filter import Filter
from ..core.downloader import Downloader
from ..core.naming import Naming
from ..core.search_profiles import get_search_profile
from ..models.search_target import SearchTarget
from .run_result import RunResult, RunOutcome
from .events import ProgressEvent, EventType


@dataclass
class _ExtractionResult:
    """URL取得・解析の成否と抽出ファイルを区別する内部結果。"""

    files: List[FileInfo] = field(default_factory=list)
    attempted: int = 0
    failed: int = 0
    nested_failed: int = 0
    errors: List[str] = field(default_factory=list)
    search_summary: SearchExtractionSummary = field(
        default_factory=lambda: SearchExtractionSummary(complete=True)
    )

    @staticmethod
    def _format_failure(
        message: str,
        failure: Optional[RequestFailureDiagnostic],
    ) -> str:
        reason_code = (
            failure.reason_code
            if isinstance(failure, RequestFailureDiagnostic)
            else DownloadIssueCode.UNKNOWN.value
        )
        return f"[{reason_code}] {message}"

    def add_failure(
        self,
        message: str,
        failure: Optional[RequestFailureDiagnostic] = None,
    ) -> None:
        self.failed += 1
        self.errors.append(self._format_failure(message, failure))
        self.search_summary.complete = False

    def add_nested_failure(
        self,
        message: str,
        failure: Optional[RequestFailureDiagnostic] = None,
    ) -> None:
        self.nested_failed += 1
        self.errors.append(self._format_failure(message, failure))
        self.search_summary.complete = False

    @property
    def has_failures(self) -> bool:
        return self.failed > 0 or self.nested_failed > 0


def _existing_file_was_preserved(task) -> bool:
    """診断detailsに記録された既存ファイル保持状態を読み取る。"""
    return any(
        bool(issue.details.get("existing_file_preserved")) for issue in task.issues
    )


def _has_invalid_history(task) -> bool:
    """保持された既存ファイルが履歴再検証に不合格だったかを返す。"""
    return any(issue.code == DownloadIssueCode.HISTORY_INVALID for issue in task.issues)


def format_search_conditions(search_conditions) -> str:
    """機密情報を含まない実行用検索条件を一意な表記へ整形する。"""

    profile = get_search_profile(search_conditions.target)
    fields: list[tuple[str, object]] = [
        ("発注機関・大", search_conditions.hachu_daibunrui),
        ("発注機関・中", search_conditions.hachu_chubunrui),
        ("発注機関・小", search_conditions.hachu_shoubunrui),
        ("発注機関・細", search_conditions.hachu_saibunrui),
        (profile.project_label, search_conditions.effective_project_name),
    ]
    if profile.target == SearchTarget.GYOMU_KEIKA:
        fields.insert(0, ("検索対象", profile.display_label))

    if search_conditions.place_search_type == "text":
        fields.append((f"{profile.place_label}・文字", search_conditions.place_text))
    else:
        fields.extend(
            (
                (f"{profile.place_label}・地方", search_conditions.place_chihou),
                (f"{profile.place_label}・都道府県", search_conditions.place_todofuken),
                (
                    f"{profile.place_label}・市区町村",
                    search_conditions.place_shichouson,
                ),
            )
        )

    if profile.target.value == "koji_keika":
        fields.extend(
            (
                ("工事種別", search_conditions.koji_shubetsu),
                ("工事業種", search_conditions.koji_gyoushu),
            )
        )
    else:
        fields.append(("業務区分", search_conditions.gyomu_kubun))
    parts = [
        f"{label}={str(value).strip()}"
        for label, value in fields
        if value is not None and str(value).strip()
    ]
    if search_conditions.contract_types and len(search_conditions.contract_types) < len(
        profile.default_contract_types
    ):
        parts.append("入札方式=" + ",".join(search_conditions.contract_types))

    if (
        search_conditions.update_date_type == "past"
        and search_conditions.update_date_days is not None
    ):
        parts.append(f"最終更新=過去{search_conditions.update_date_days}日")

    for label, mode, start, end in (
        (
            "公告日",
            search_conditions.koukoku_date_type,
            search_conditions.koukoku_date_start,
            search_conditions.koukoku_date_end,
        ),
        (
            "開札日",
            search_conditions.kaisatsu_date_type,
            search_conditions.kaisatsu_date_start,
            search_conditions.kaisatsu_date_end,
        ),
        (
            "契約日",
            search_conditions.keiyaku_date_type,
            search_conditions.keiyaku_date_start,
            search_conditions.keiyaku_date_end,
        ),
    ):
        if mode == "range":
            parts.append(f"{label}={start or '-'}～{end or '-'}")

    for label, minimum, maximum in (
        (
            "予定価格",
            search_conditions.yotei_price_min,
            search_conditions.yotei_price_max,
        ),
        (
            "落札価格",
            search_conditions.rakusatsu_price_min,
            search_conditions.rakusatsu_price_max,
        ),
    ):
        if minimum is not None or maximum is not None:
            parts.append(
                f"{label}={minimum if minimum is not None else '-'}～"
                f"{maximum if maximum is not None else '-'}"
            )

    winner_name = str(search_conditions.rakusatsu_name or "").strip()
    if winner_name:
        parts.append(f"落札者名={winner_name}")
    if search_conditions.denshi:
        parts.append("電子入札=対象案件のみ")
    if search_conditions.koukai:
        parts.append("公開文書=公開中のみ")
    parts.append(f"表示件数={search_conditions.display_count}")
    return " / ".join(parts) if parts else "指定なし"


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
        redownload_policy: RedownloadPolicy = (RedownloadPolicy.REUSE_VERIFIED),
        run_kind: RunKind = RunKind.MANUAL,
        run_id: str = "",
    ) -> RunResult:
        """ダウンロード処理を実行"""
        search_summary = SearchExtractionSummary()
        resolved_run_id = str(run_id or uuid.uuid4().hex)

        def finish(run_result: RunResult) -> RunResult:
            if run_result.search_summary is None:
                run_result.search_summary = search_summary
            self._emit_terminal_event(progress_callback, run_result)
            return run_result

        try:
            if config.search_conditions.hachu_multi:
                message = (
                    "複数発注機関検索は現在サポートされていません。"
                    "発注機関（リスト検索）を使用してください"
                )
                self.logger.error(message)
                return finish(
                    RunResult(
                        success=False,
                        message=message,
                        error=message,
                        outcome=RunOutcome.FAILED,
                    )
                )

            # データルートから実行種別ごとの保存先を解決する。旧設定
            # （layout_version < 3）は従来どおりlocal直下を使用する。
            save_dir = resolve_app_path(
                resolve_run_root(
                    config.save_paths,
                    run_kind,
                    config.search_conditions.target,
                )
            )
            save_dir.mkdir(parents=True, exist_ok=True)
            run_kind_value = (
                run_kind.value
                if isinstance(run_kind, RunKind)
                else str(run_kind).strip().upper()
            )
            self.logger.info(
                "保存先を解決しました: "
                f"実行種別={run_kind_value}, "
                f"レイアウト=v{config.save_paths.layout_version}, "
                f"保存先={save_dir}"
            )

            # コンポーネントの初期化
            self._initialize_components(config)

            # イベント発行: 開始
            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        type=EventType.START,
                        message="ダウンロードを開始します",
                        total=0,
                    )
                )

            # ファイル抽出
            extraction = self._extract_files(config, progress_callback, cancel_flag)
            search_summary = extraction.search_summary
            all_files = extraction.files

            if not all_files and search_summary.projects_matched:
                search_summary.target_documents = 0
                search_summary.download_count = 0
                self._emit_search_summary(
                    progress_callback,
                    search_summary,
                    config.search_conditions.koukai,
                )

            if cancel_flag and cancel_flag():
                return finish(
                    RunResult(
                        success=False,
                        message="ダウンロードがキャンセルされました",
                        outcome=RunOutcome.CANCELLED,
                    )
                )

            if not all_files:
                if extraction.has_failures:
                    message = (
                        "検索ページの取得または解析に失敗しました: "
                        f"取得元={extraction.failed}/{extraction.attempted} URL, "
                        f"検索結果内={extraction.nested_failed}件"
                    )
                    return finish(
                        RunResult(
                            success=False,
                            message=message,
                            error="; ".join(extraction.errors),
                            outcome=RunOutcome.FAILED,
                        )
                    )
                return finish(
                    RunResult(
                        success=False,
                        message=(
                            self._format_search_summary(search_summary)
                            + "\n公開中の取得可能なファイルが見つかりませんでした"
                        ),
                        outcome=RunOutcome.NO_MATCH,
                    )
                )

            # フィルタリング
            filtered_files = self._filter_files(all_files, progress_callback)
            self._apply_filter_decisions(
                search_summary,
                all_files,
                filtered_files,
            )
            self._emit_search_summary(
                progress_callback,
                search_summary,
                config.search_conditions.koukai,
            )

            if cancel_flag and cancel_flag():
                return finish(
                    RunResult(
                        success=False,
                        message="ダウンロードがキャンセルされました",
                        outcome=RunOutcome.CANCELLED,
                    )
                )

            if not filtered_files:
                if extraction.has_failures:
                    message = (
                        "一部の検索結果を取得できず、確認できた範囲にも"
                        "ダウンロード対象がありませんでした: "
                        f"取得元失敗={extraction.failed}/{extraction.attempted} URL, "
                        f"検索結果内失敗={extraction.nested_failed}件"
                    )
                    return finish(
                        RunResult(
                            success=False,
                            message=message,
                            error="; ".join(extraction.errors),
                            outcome=RunOutcome.FAILED,
                        )
                    )
                return finish(
                    RunResult(
                        success=False,
                        message=(
                            self._format_search_summary(search_summary)
                            + "\nダウンロード条件に一致するファイルが"
                            "見つかりませんでした"
                        ),
                        outcome=RunOutcome.NO_MATCH,
                    )
                )

            # ダウンロード実行
            result = self._download_files(
                filtered_files,
                config,
                progress_callback,
                cancel_flag,
                redownload_policy,
                save_dir=save_dir,
                run_kind=run_kind,
                run_id=resolved_run_id,
            )
            self._apply_download_results(search_summary, result)
            self._emit_search_summary(
                progress_callback,
                search_summary,
                config.search_conditions.koukai,
            )

            # 結果メッセージ
            reused = getattr(result, "reused", result.skipped)
            all_reused = (
                result.total > 0
                and reused == result.total
                and result.success == 0
                and result.failed == 0
                and result.cancelled == 0
            )
            if all_reused:
                result_message = (
                    f"完了（{result.total}件すべて保存済み）: "
                    f"新規保存=0, 保存済み確認={reused}, 失敗=0, "
                    "キャンセル=0, HTML→PDF変換=0"
                )
            else:
                result_message = (
                    f"ダウンロード完了: 新規保存={result.success}, "
                    f"失敗={result.failed}, 保存済み確認={reused}, "
                    f"キャンセル={result.cancelled}, "
                    f"HTML→PDF変換={result.converted}"
                )
            download_error = None
            if result.issue_counts:
                diagnostic_counts = ", ".join(
                    f"{code.value}={count}"
                    for code, count in sorted(
                        result.issue_counts.items(),
                        key=lambda item: item[0].value,
                    )
                )
                result_message += f", 診断内訳: {diagnostic_counts}"
            failed_reason_counts = Counter()
            for failed_task in result.failed_tasks:
                primary_issue = next(
                    (
                        item
                        for item in failed_task.issues
                        if item.severity == IssueSeverity.ERROR
                    ),
                    failed_task.issues[0] if failed_task.issues else None,
                )
                if primary_issue:
                    failed_reason_counts[primary_issue.code.value] += 1
            if failed_reason_counts:
                result_message += ", 失敗理由別: " + ", ".join(
                    f"{code}={count}"
                    for code, count in sorted(failed_reason_counts.items())
                )
            if result.failed_tasks:
                first_task = result.failed_tasks[0]
                first_issue = next(
                    (
                        item
                        for item in first_task.issues
                        if item.severity == IssueSeverity.ERROR
                    ),
                    first_task.issues[0] if first_task.issues else None,
                )
                reason = (
                    first_issue.message if first_issue else first_task.error_message
                )
                if _existing_file_was_preserved(first_task) and "保持" not in reason:
                    reason += "（既存の正常ファイルは保持されています）"
                code = f" [{first_issue.code.value}]" if first_issue else ""
                remaining = len(result.failed_tasks) - 1
                download_error = f"{first_task.file_info.filename}: {reason}{code}"
                download_error += (
                    f"（残り{remaining}件。詳細はlogs/app.logを確認してください）"
                )
                result_message += f", 先頭理由: {download_error}"

            outcome = result.outcome
            if extraction.has_failures and outcome == RunOutcome.SUCCESS:
                outcome = RunOutcome.PARTIAL
            if extraction.failed:
                result_message += (
                    f", 検索ページ取得失敗="
                    f"{extraction.failed}/{extraction.attempted} URL"
                )
            if extraction.nested_failed:
                result_message += f", 検索結果内処理失敗={extraction.nested_failed}件"

            result_message = (
                self._format_search_summary(search_summary) + "\n" + result_message
            )

            return finish(
                RunResult(
                    success=outcome in {RunOutcome.SUCCESS, RunOutcome.PARTIAL},
                    result=result,
                    message=result_message,
                    error=(
                        "; ".join(
                            value
                            for value in (
                                (
                                    "; ".join(extraction.errors)
                                    if extraction.has_failures
                                    else ""
                                ),
                                download_error or "",
                            )
                            if value
                        )
                        or None
                    ),
                    outcome=outcome,
                    search_summary=search_summary,
                )
            )

        except Exception as e:
            error_message = f"ダウンロード処理エラー: {str(e)}"
            self.logger.error(error_message)

            return finish(
                RunResult(
                    success=False,
                    error=str(e),
                    message=error_message,
                    outcome=RunOutcome.FAILED,
                )
            )
        finally:
            self._cleanup()

    def _emit_terminal_event(
        self,
        progress_callback: Optional[Callable[[ProgressEvent], None]],
        run_result: RunResult,
    ) -> None:
        """すべての終了経路をRunOutcome付きイベントへ統一する。"""
        if not progress_callback:
            return
        outcome = run_result.outcome or (
            RunOutcome.SUCCESS if run_result.success else RunOutcome.FAILED
        )
        result = run_result.result
        total = result.total if result is not None else 0
        reused = getattr(result, "reused", result.skipped) if result is not None else 0
        all_reused = bool(
            result is not None
            and outcome == RunOutcome.SUCCESS
            and total > 0
            and reused == total
            and result.success == 0
            and result.failed == 0
            and result.cancelled == 0
        )
        level = {
            RunOutcome.SUCCESS: "info",
            RunOutcome.PARTIAL: "warning",
            RunOutcome.FAILED: "error",
            RunOutcome.CANCELLED: "warning",
            RunOutcome.NO_MATCH: "info",
        }[outcome]
        search_summary = run_result.search_summary
        progress_callback(
            ProgressEvent(
                type=(
                    EventType.FAIL
                    if outcome == RunOutcome.FAILED
                    else EventType.COMPLETE
                ),
                message=run_result.message,
                current=total,
                total=total,
                error=run_result.error
                or (run_result.message if outcome == RunOutcome.FAILED else ""),
                metadata={
                    "outcome": outcome.value,
                    "type": level,
                    "all_reused": all_reused,
                    "new_downloads": result.success if result else 0,
                    "reused": reused,
                    "search_summary": (
                        search_summary.to_dict() if search_summary is not None else None
                    ),
                    "projects": (
                        search_summary.project_dicts()
                        if search_summary is not None
                        else []
                    ),
                    "snapshot_kind": "final",
                    "generation": getattr(
                        self._scraper, "_search_progress_generation", 0
                    ),
                },
            )
        )

    def _initialize_components(self, config: AppConfig):
        """コンポーネントを初期化"""
        self._http_client = HTTPClient(self.logger)
        self._scraper = Scraper(self._http_client, self.logger)
        self._filter = Filter(config.download_conditions, self.logger)
        self._naming = Naming(config.naming_rule, self.logger, config.search_conditions)
        self._downloader = Downloader(self._http_client, self.logger)

    def _extract_files(
        self,
        config: AppConfig,
        progress_callback: Optional[Callable[[ProgressEvent], None]],
        cancel_flag: Optional[Callable[[], bool]],
    ) -> _ExtractionResult:
        """ファイルを抽出し、0件と取得・解析失敗を区別する。"""
        result = _ExtractionResult()

        for url in config.target_urls:
            if cancel_flag and cancel_flag():
                break
            result.attempted += 1

            self.logger.info(f"ページを解析中: {url}")
            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        type=EventType.MESSAGE,
                        message=f"ページを解析中: {url}",
                        metadata={"type": "info"},
                    )
                )

            # 検索条件のチェック
            has_search_conditions = self._has_search_conditions(
                config.search_conditions
            )

            try:
                if has_search_conditions:
                    # 検索フォームを送信
                    condition_summary = self._format_search_conditions(
                        config.search_conditions
                    )
                    self.logger.info(f"実行する検索条件: {condition_summary}")
                    if progress_callback:
                        progress_callback(
                            ProgressEvent(
                                type=EventType.MESSAGE,
                                message=(
                                    f"検索条件で検索を実行中: {condition_summary}"
                                ),
                                metadata={"type": "info"},
                            )
                        )

                    soup = self._scraper.submit_search_form(
                        url,
                        config.search_conditions,
                        cancel_check=cancel_flag,
                    )
                    if soup is None:
                        message = f"検索の実行に失敗しました: {url}"
                        self.logger.error(message)
                        failure = getattr(self._scraper, "last_request_failure", None)
                        result.add_failure(
                            message,
                            failure=(
                                failure
                                if isinstance(failure, RequestFailureDiagnostic)
                                else None
                            ),
                        )
                        continue

                    def on_search_progress(progress: SearchProgress) -> None:
                        if not progress_callback:
                            return
                        progress_callback(
                            ProgressEvent(
                                type=EventType.PROGRESS,
                                metadata={
                                    "phase": "search",
                                    "search_phase": progress.phase,
                                    "page": progress.page_number,
                                    "row": progress.row_number,
                                    "rows_on_page": progress.rows_on_page,
                                    "projects_scanned": progress.projects_scanned,
                                    "files_discovered": progress.files_discovered,
                                    "public_documents": progress.public_documents,
                                    "expired_only_projects": (
                                        progress.expired_only_projects
                                    ),
                                    "no_document_projects": (
                                        progress.no_document_projects
                                    ),
                                    "detail_failed_projects": (
                                        progress.detail_failed_projects
                                    ),
                                    "search_summary": progress.search_summary,
                                    "projects": progress.projects,
                                    "project_delta": progress.project_delta,
                                    "snapshot_kind": progress.snapshot_kind,
                                    "generation": progress.generation,
                                },
                            )
                        )

                    files = self._scraper.extract_file_links_from_search_results(
                        soup,
                        url,
                        config.download_conditions.file_types,
                        config.search_conditions,
                        cancel_check=cancel_flag,
                        progress_callback=on_search_progress,
                    )
                    result.files.extend(files)
                    scraper_summary = getattr(
                        self._scraper, "last_search_summary", None
                    )
                    if isinstance(scraper_summary, SearchExtractionSummary):
                        result.search_summary.merge(scraper_summary)
                    diagnostics = getattr(
                        self._scraper, "last_search_diagnostics", None
                    )
                    diagnostic_errors = getattr(diagnostics, "errors", [])
                    diagnostic_failures = getattr(diagnostics, "failures", [])
                    if isinstance(diagnostic_errors, list):
                        for index, diagnostic_error in enumerate(diagnostic_errors):
                            failure = (
                                diagnostic_failures[index]
                                if isinstance(diagnostic_failures, list)
                                and index < len(diagnostic_failures)
                                and isinstance(
                                    diagnostic_failures[index],
                                    RequestFailureDiagnostic,
                                )
                                else None
                            )
                            result.add_nested_failure(
                                f"{url}: {diagnostic_error}",
                                failure=failure,
                            )
                    # 案件数（スクレイパーから取得）とファイル数を表示
                    koji_count = getattr(
                        self._scraper,
                        "last_search_total_project_count",
                        getattr(
                            self._scraper,
                            "last_search_total_koji_count",
                            None,
                        ),
                    )
                    if koji_count is None:
                        # フォールバック: ファイルから取得したユニークな案件名の数
                        koji_names = {
                            file_info.metadata.get("project_name")
                            or file_info.metadata.get("koji_name")
                            for file_info in files
                            if file_info.metadata
                            and (
                                file_info.metadata.get("project_name")
                                or file_info.metadata.get("koji_name")
                            )
                        }
                        koji_count = len(koji_names) if koji_names else "不明"
                    message = (
                        f"検索結果: 案件数={koji_count}件, ファイル数={len(files)}件"
                    )
                    self.logger.info(message)
                    if progress_callback:
                        progress_callback(
                            ProgressEvent(
                                type=EventType.MESSAGE,
                                message=message,
                                metadata={"type": "info"},
                            )
                        )
                else:
                    # 通常のページ解析
                    soup = self._scraper.fetch_page(url)
                    if soup is None:
                        message = f"ページの取得に失敗しました: {url}"
                        self.logger.error(message)
                        failure = getattr(self._scraper, "last_request_failure", None)
                        result.add_failure(
                            message,
                            failure=(
                                failure
                                if isinstance(failure, RequestFailureDiagnostic)
                                else None
                            ),
                        )
                        continue
                    files = self._scraper.extract_file_links(
                        soup, url, config.download_conditions.file_types
                    )
                    result.files.extend(files)
                    self.logger.info(f"{len(files)}個のファイルリンクを発見")
            except Exception as exc:
                message = f"ページの解析に失敗しました: {url} - {exc}"
                self.logger.error(message)
                result.add_failure(
                    message,
                    failure=classify_request_failure(exc),
                )

        result.files = self._deduplicate_files(result.files)
        # ここはファイル種別判定後・ユーザーフィルター前の一意候補数。
        # 複数URLやページで同じ文書が再掲されても二重計上しない。
        result.search_summary.candidate_documents = len(result.files)
        if cancel_flag and cancel_flag():
            result.search_summary.complete = False
        return result

    @staticmethod
    def _format_search_conditions(search_conditions) -> str:
        """機密情報を含まない有効検索条件を一行へ整形する。"""
        return format_search_conditions(search_conditions)

    def _has_search_conditions(self, search_conditions) -> bool:
        """検索条件が設定されているかチェック"""
        if not search_conditions:
            return False

        sc = search_conditions
        profile = get_search_profile(sc.target)
        # contract_typesはデフォルトで全選択されているため、空でない場合のみチェック
        # ただし、デフォルト値（全選択）の場合は検索条件として扱わない
        has_contract_types = bool(
            sc.contract_types
            and len(sc.contract_types) > 0
            and len(sc.contract_types) < len(profile.default_contract_types)
        )

        return bool(
            sc.target != SearchTarget.KOJI_KEIKA
            or (sc.hachu_daibunrui and sc.hachu_daibunrui.strip())
            or (sc.hachu_chubunrui and sc.hachu_chubunrui.strip())
            or (sc.hachu_shoubunrui and sc.hachu_shoubunrui.strip())
            or (sc.hachu_saibunrui and sc.hachu_saibunrui.strip())
            or (sc.hachu_multi and len(sc.hachu_multi) > 0)
            or (sc.effective_project_name and sc.effective_project_name.strip())
            or (
                sc.place_search_type == "list"
                and (sc.place_chihou or sc.place_todofuken or sc.place_shichouson)
            )
            or (
                sc.place_search_type == "text"
                and sc.place_text
                and sc.place_text.strip()
            )
            or has_contract_types
            or sc.update_date_type == "past"
            or sc.koukoku_date_type == "range"
            or sc.kaisatsu_date_type == "range"
            or sc.keiyaku_date_type == "range"
            or (sc.koji_shubetsu and sc.koji_shubetsu.strip())
            or (sc.koji_gyoushu and sc.koji_gyoushu.strip())
            or (sc.gyomu_kubun and sc.gyomu_kubun.strip())
            or sc.yotei_price_min is not None
            or sc.yotei_price_max is not None
            or sc.rakusatsu_price_min is not None
            or sc.rakusatsu_price_max is not None
            or (sc.rakusatsu_name and sc.rakusatsu_name.strip())
            or sc.denshi
            or sc.koukai
        )

    def _filter_files(
        self, files, progress_callback: Optional[Callable[[ProgressEvent], None]]
    ):
        """ファイルをフィルタリング"""
        filtered = self._filter.filter_files(files)

        # 案件数（ユニークな案件名の数）とファイル数を表示
        koji_names = set()
        for f in filtered:
            if f.metadata:
                project_name = f.metadata.get("project_name") or f.metadata.get(
                    "koji_name"
                )
                if project_name:
                    koji_names.add(project_name)
        koji_count = len(koji_names) if koji_names else "不明"

        self.logger.info(
            f"フィルタリング後: 案件数={koji_count}件, ファイル数={len(filtered)}件"
        )

        if progress_callback:
            progress_callback(
                ProgressEvent(
                    type=EventType.MESSAGE,
                    message=f"フィルタリング後: 案件数={koji_count}件, ファイル数={len(filtered)}件",
                    metadata={"type": "info"},
                )
            )

        return filtered

    @staticmethod
    def _deduplicate_files(files: List[FileInfo]) -> List[FileInfo]:
        """複数ページ・取得元で再掲された同一URLを一件へ統合する。"""
        merged: List[FileInfo] = []
        by_url = {}
        for file_info in files:
            if not file_info.url:
                # 不正候補も個別の失敗として診断できるよう、空URL同士は
                # 同一文書とみなさない。
                merged.append(file_info)
                continue
            existing = by_url.get(file_info.url)
            if existing is None:
                by_url[file_info.url] = file_info
                merged.append(file_info)
                continue
            if file_info.metadata:
                if existing.metadata is None:
                    existing.metadata = {}
                existing.metadata.update(file_info.metadata)
            existing.allow_html_to_pdf = (
                existing.allow_html_to_pdf or file_info.allow_html_to_pdf
            )
        return merged

    @staticmethod
    def _apply_filter_decisions(
        summary: SearchExtractionSummary,
        all_files: List[FileInfo],
        filtered_files: List[FileInfo],
    ) -> None:
        """公開文書行へファイル種別・ユーザーフィルター結果を反映する。"""
        candidate_urls = {item.url for item in all_files}
        target_urls = {item.url for item in filtered_files}
        summary.candidate_documents = len(candidate_urls)
        summary.target_documents = len(target_urls)
        summary.download_count = len(target_urls)
        summary.reuse_count = 0
        summary.legacy_reuse_count = 0
        for project in summary.projects:
            for document in project.documents:
                if document.public_status != "PUBLIC":
                    continue
                if document.url in target_urls:
                    document.decision = DocumentDecision.DOWNLOAD_TARGET.value
                    document.decision_reason = "今回のダウンロード対象"
                elif document.url in candidate_urls:
                    document.decision = DocumentDecision.EXCLUDED_FILTER.value
                    document.decision_reason = "キーワードまたは日付条件の対象外"
                elif document.url:
                    document.decision = DocumentDecision.EXCLUDED_FILE_TYPE.value
                    document.decision_reason = "選択したファイル種別の対象外"
                else:
                    document.decision = DocumentDecision.PUBLIC_LINK_MISSING.value
                    document.decision_reason = "公開中ですがリンクがありません"
        summary.refresh_counts()
        # refresh_countsは文書決定からtargetを算出するため、URL単位で
        # 重複排除した実ダウンロード対象を最終値として採用する。
        summary.target_documents = len(target_urls)

    @staticmethod
    def _apply_download_results(
        summary: SearchExtractionSummary,
        result: DownloadResult,
    ) -> None:
        """ファイル単位の確定結果を案件・文書内訳へ反映する。"""
        tasks_by_url = {task.file_info.url: task for task in result.tasks}
        for project in summary.projects:
            for document in project.documents:
                task = tasks_by_url.get(document.url)
                if task is None:
                    continue
                if task.status == "completed":
                    document.decision = DocumentDecision.DOWNLOADED.value
                    document.decision_reason = "新規または更新文書を保存"
                elif task.status == "skipped":
                    if getattr(task, "reuse_kind", "") == "LEGACY_PATH_ALIAS":
                        document.decision = DocumentDecision.REUSED_LEGACY.value
                        document.decision_reason = "旧名称の保存済み文書を再利用"
                    else:
                        document.decision = DocumentDecision.REUSED.value
                        document.decision_reason = "保存済み文書を再利用"
                elif task.status == "failed":
                    document.decision = DocumentDecision.FAILED.value
                    document.decision_reason = task.error_message or "ダウンロード失敗"
                elif task.status == "cancelled":
                    document.decision = DocumentDecision.CANCELLED.value
                    document.decision_reason = "キャンセル"
        summary.download_count = result.success
        summary.reuse_count = result.reused
        summary.legacy_reuse_count = getattr(result, "legacy_reused", 0)
        summary.refresh_counts()
        # フォールバックで取得した文書は案件内訳に対応する行を持たない
        # 場合がある。実行総数を集計の不変条件として最後に採用する。
        summary.target_documents = result.total

    @staticmethod
    def _format_search_summary(summary: SearchExtractionSummary) -> str:
        state = "検索解析完了" if summary.complete else "検索途中集計"
        expired = (
            "集計対象外（公開中のみ）"
            if summary.expired_scope_excluded
            else f"{summary.expired_only_projects}件"
        )
        first = (
            f"{state}: 案件{summary.projects_matched}件 / "
            f"公開中データ{summary.public_documents}件 / "
            f"公開終了のみ{expired}"
        )
        second = f"今回のダウンロード対象{summary.target_documents}件"
        if summary.reuse_count or summary.download_count:
            second += (
                f"（新規・更新{summary.download_count}件 / "
                f"保存済み確認{summary.reuse_count}件"
            )
            if summary.legacy_reuse_count:
                second += f"〈旧命名{summary.legacy_reuse_count}件〉"
            second += "）"
        lines = [first, second]
        if summary.agency_resolution_counts:
            agency_line = (
                "発注機関分類: "
                f"確定{summary.agency_resolved_projects}件 / "
                f"未解決{summary.agency_unresolved_projects}件"
            )
            if summary.agency_issue_counts:
                issue_text = ", ".join(
                    f"{code}={count}"
                    for code, count in sorted(summary.agency_issue_counts.items())
                )
                agency_line += f"（理由別: {issue_text}）"
            lines.append(agency_line)
        return "\n".join(lines)

    def _emit_search_summary(
        self,
        progress_callback: Optional[Callable[[ProgressEvent], None]],
        summary: SearchExtractionSummary,
        public_only: bool,
    ) -> None:
        summary.expired_scope_excluded = bool(public_only)
        message = self._format_search_summary(summary)
        self.logger.info(message.replace("\n", " / "))
        self.logger.info(
            "search.summary "
            + json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True)
        )
        if progress_callback:
            progress_callback(
                ProgressEvent(
                    type=EventType.PROGRESS,
                    message=message,
                    metadata={
                        "phase": "search",
                        "search_phase": "summary",
                        "search_summary": summary.to_dict(),
                        "projects": summary.project_dicts(),
                        "snapshot_kind": "final",
                        "generation": getattr(
                            self._scraper, "_search_progress_generation", 0
                        ),
                        "type": "info",
                    },
                )
            )

    def _download_files(
        self,
        files,
        config: AppConfig,
        progress_callback: Optional[Callable[[ProgressEvent], None]],
        cancel_flag: Optional[Callable[[], bool]],
        redownload_policy: RedownloadPolicy = (RedownloadPolicy.REUSE_VERIFIED),
        save_dir: Optional[str | Path] = None,
        run_kind: RunKind = RunKind.MANUAL,
        run_id: str = "",
    ) -> DownloadResult:
        """ファイルをダウンロード"""

        def progress_wrapper(current: int, total: int, filename: str) -> bool:
            """Downloader用の進捗コールバック（boolを返す）"""
            if cancel_flag and cancel_flag():
                return False

            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        type=EventType.PROGRESS,
                        message=f"{filename} をダウンロード中...",
                        current=current,
                        total=total,
                        filename=filename,
                    )
                )
            return True

        def task_result_callback(current, total, task) -> None:
            """ファイル単位の完了状態をGUIへ渡す。"""
            if not progress_callback:
                return
            if task.status == "skipped":
                progress_callback(
                    ProgressEvent(
                        type=EventType.PROGRESS,
                        message=(
                            f"保存済み確認: {task.file_info.filename}（HTTP通信なし）"
                        ),
                        current=current,
                        total=total,
                        filename=(f"保存済み確認: {task.file_info.filename}"),
                        metadata={
                            "type": "info",
                            "status": "reused",
                            # Downloaderが同じ内容をファイルログへ記録済み。
                            "already_logged": True,
                        },
                    )
                )
                return
            progress_labels = {
                "completed": "新規保存",
                "failed": "失敗",
                "cancelled": "キャンセル",
            }
            progress_label = progress_labels.get(task.status, "処理完了")
            progress_callback(
                ProgressEvent(
                    type=EventType.PROGRESS,
                    current=current,
                    total=total,
                    filename=(f"{progress_label}: {task.file_info.filename}"),
                    metadata={
                        "type": "info",
                        "status": task.status,
                    },
                )
            )
            if task.status == "completed":
                legacy_path_issue = next(
                    (
                        issue
                        for issue in task.issues
                        if getattr(issue.code, "value", issue.code)
                        == "LEGACY_PATH_REDOWNLOAD"
                    ),
                    None,
                )
                if legacy_path_issue is not None:
                    progress_callback(
                        ProgressEvent(
                            type=EventType.MESSAGE,
                            message=(
                                "旧分類場所のファイルを保持して正規保存先へ"
                                "再取得しました: "
                                f"{task.file_info.filename} "
                                "[LEGACY_PATH_REDOWNLOAD]"
                            ),
                            metadata={
                                "type": "warning",
                                "stage": legacy_path_issue.stage.value,
                                "issue_code": "LEGACY_PATH_REDOWNLOAD",
                                "already_logged": True,
                            },
                        )
                    )
                history_issue = next(
                    (
                        issue
                        for issue in task.issues
                        if getattr(issue.code, "value", issue.code) == "HISTORY_INVALID"
                    ),
                    None,
                )
                if history_issue is not None:
                    progress_callback(
                        ProgressEvent(
                            type=EventType.MESSAGE,
                            message=(
                                "保存済みファイル検証失敗→再取得済み: "
                                f"{task.file_info.filename} — "
                                f"{history_issue.message} "
                                "[HISTORY_INVALID]"
                            ),
                            metadata={
                                "type": "warning",
                                "stage": history_issue.stage.value,
                                "issue_code": "HISTORY_INVALID",
                                "already_logged": True,
                            },
                        )
                    )
            if task.status != "failed":
                return
            issue = next(
                (item for item in task.issues if item.severity == IssueSeverity.ERROR),
                task.issues[0] if task.issues else None,
            )
            reason = issue.message if issue else task.error_message
            if _existing_file_was_preserved(task) and "保持" not in reason:
                if _has_invalid_history(task):
                    reason += "（検証不合格の既存ファイルは削除せず保持しています）"
                else:
                    reason += "（既存の正常ファイルは保持されています）"
            code = f" [{issue.code.value}]" if issue else ""
            progress_callback(
                ProgressEvent(
                    type=EventType.MESSAGE,
                    message=(f"失敗: {task.file_info.filename} — {reason}{code}"),
                    metadata={
                        "type": "error",
                        "stage": issue.stage.value if issue else "",
                        "issue_code": issue.code.value if issue else "",
                        "processing_mode": task.processing_mode.value,
                        # Downloaderが同じ内容をファイルログへ記録済み。
                        "already_logged": True,
                    },
                )
            )

        effective_save_dir = (
            resolve_app_path(save_dir)
            if save_dir is not None
            else resolve_app_path(
                resolve_run_root(
                    config.save_paths,
                    RunKind.MANUAL,
                    config.search_conditions.target,
                )
            )
        )
        run_kind_value = (
            run_kind.value
            if isinstance(run_kind, RunKind)
            else str(run_kind).strip().upper()
        )
        storage_key = str(
            getattr(config.save_paths, "schedule_storage_key", "") or ""
        ).strip()
        for file_info in files:
            metadata = file_info.metadata or {}
            file_info.metadata = metadata
            metadata["run_kind"] = run_kind_value
            metadata["run_id"] = str(run_id or "")
            if run_kind_value == RunKind.SCHEDULED.value and storage_key:
                metadata["storage_key"] = storage_key
        return self._downloader.download_files(
            files,
            str(effective_save_dir),
            self._naming,
            progress_wrapper,
            folder_name=None,
            cancel_check=cancel_flag,
            task_result_callback=task_result_callback,
            redownload_policy=redownload_policy,
            layout_version=int(getattr(config.save_paths, "layout_version", 2)),
        )

    def _cleanup(self):
        """リソースをクリーンアップ"""
        http_client = self._http_client
        # Scraper/DownloaderからSessionへ続く参照も実行終了時に切り、
        # ApplicationServiceを再利用・保持する呼出側でも応答やcacheを
        # 次回GCまで抱え続けないようにする。
        self._downloader = None
        self._naming = None
        self._filter = None
        self._scraper = None
        self._http_client = None
        if http_client:
            http_client.close()
