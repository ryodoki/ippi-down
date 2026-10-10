# -*- coding: utf-8 -*-

"""エントリーポイント（GUI版）"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Sequence
import uuid

import yaml

# プロジェクトルートをパスに追加（開発時のみ必要、exe配布時は不要）
if not getattr(sys, "frozen", False):
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig
from src.utils.logger import Logger
from src.utils.notifier import Notifier
from src.utils.scheduled_notifier import (
    ScheduleNotificationPolicy,
    ScheduledRunNotifier,
)
from src.app.service import ApplicationService
from src.app.events import ProgressEvent, EventType
from src.app.run_guard import DOWNLOAD_RUN_GUARD
from src.app.run_queue import (
    RunQueueError,
    get_default_run_queue,
    manual_run_slot,
    validate_schedule_id,
)
from src.app.headless import (
    ExecutionRecord,
    HeadlessExitCode,
    RetryPolicy,
    execute_headless,
    make_config_failure_record,
    make_queue_timeout_record,
    make_schedule_record_sink,
)
from src.app.exceptions import ConfigError, FilesystemError
from src.models.download_diagnostics import RedownloadPolicy
from src.models.download_result import RunOutcome
from src.models.agency import AgencyLevel, AgencyOption, AgencyPath
from src.models.search_target import SearchTarget
from src.core.search_profiles import get_search_profile
from src import __version__
from src.utils.path_utils import get_base_path, get_logs_path
from src.storage.layout import RunKind
from src.storage.reclassification import ReclassificationService

if TYPE_CHECKING:
    from src.gui.main_window import MainWindow


class _AlreadyAcquiredGuard:
    """dispatcherが取得済みのglobal実行枠をexecute_headlessへ示す。"""

    @contextmanager
    def try_acquire(self):
        yield True


_ALREADY_ACQUIRED_GUARD = _AlreadyAcquiredGuard()


class _ManualRunSlotGuard:
    """定期実行の待機ticketを追い越さずに再分類枠を取得する。"""

    @contextmanager
    def try_acquire(self):
        with manual_run_slot() as acquired:
            yield acquired


class _GuiReclassificationAgencyResolver:
    """GUIが所有する公式候補Sessionを再分類でも共有する。"""

    def __init__(self, main_window: "MainWindow") -> None:
        self._main_window = main_window

    def resolve_candidates(self, query: object) -> tuple[AgencyOption, ...]:
        parent = AgencyPath()
        for raw_segment in tuple(getattr(query, "parent_segments", ()) or ()):
            raw_level = getattr(raw_segment, "level", "")
            level = AgencyLevel(getattr(raw_level, "value", raw_level))
            option = AgencyOption(
                level=level,
                code=str(getattr(raw_segment, "code", "") or ""),
                label=str(getattr(raw_segment, "label", "") or ""),
                parent_path=parent,
            )
            parent = parent.append(option)

        cancel_check = getattr(query, "cancel_check", None)
        target = SearchTarget.coerce(
            getattr(query, "search_target", SearchTarget.KOJI_KEIKA.value)
        )
        search_url = get_search_profile(target).search_url
        main_window = self._main_window
        with main_window._scraper_request_lock:
            scraper = main_window._get_scraper()
            result = scraper.get_agency_children_result(
                search_url,
                parent_path=parent,
                cancel_check=(cancel_check if callable(cancel_check) else None),
            )
        error = getattr(result, "error", None)
        if error is not None:
            raise RuntimeError(str(error))
        return tuple(getattr(result, "options", ()) or ())


def prepare_runtime_config(config: AppConfig, logger: Logger) -> AppConfig:
    """旧・将来機能の設定値を保持したまま、実行用コピーでは無効化する。"""
    runtime_config = deepcopy(config)
    if runtime_config.search_conditions.hachu_multi:
        logger.warning(
            "複数発注機関の旧設定は現在サポートされないため、今回の実行では無効化します"
        )
        runtime_config.search_conditions.hachu_multi = []
    return runtime_config


def _report_self_check(message: str, *, error: bool = False) -> None:
    """consoleなしexeでもself-checkの診断結果を残す。"""
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        try:
            print(message, file=stream)
        except (OSError, ValueError):
            # windowedビルドでは表示先のない擬似streamになる場合がある。
            pass
    if not getattr(sys, "frozen", False):
        return
    try:
        result_path = Path(sys.executable).resolve().parent / "self-check-result.txt"
        result_path.write_text(message + "\n", encoding="utf-8")
    except OSError:
        # 終了コードは維持し、書込不可を元の診断失敗で上書きしない。
        return


def _show_startup_error(message: str) -> None:
    """GUI生成前の設定エラーを、通信せず利用者へ表示する。"""

    root = None
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "ippi-down - 設定エラー",
            f"{message}\n\n設定を修正してから再度起動してください。",
            parent=root,
        )
    except Exception:
        # Tk自体を利用できない環境でも、直前のfile logと終了コードを維持する。
        return
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def run_self_check() -> int:
    """配布exeと内蔵PDF生成・Edge監視機構をオフライン確認する。"""
    if sys.version_info[:2] != (3, 11):
        message = (
            "ippi-down self-check: FAILED "
            f"(Python {sys.version_info.major}.{sys.version_info.minor}; "
            "Python 3.11 is required)"
        )
        _report_self_check(message, error=True)
        return 1
    try:
        import hashlib
        import re
        import shutil
        import tempfile
        import uuid

        # GUIモジュールもbundleへ含まれていることを確認する。ただしTk rootは
        # 作らないため、画面・設定・ログは生成しない。
        import tkinter  # noqa: F401
        from src.gui.main_window import MainWindow  # noqa: F401
        from src.core.html_to_pdf import HtmlToPdfConverter
        from src.core.pdf_conversion_audit import PdfConversionAudit
        from src.core.windows_process_supervisor import (
            WindowsJobProcessSupervisor,
        )
        from src.models.config_model import ScheduleConfig
        from src.scheduler.service import calculate_next_run
        from src.scheduler.task_scheduler import (
            SchtasksClient,
            build_task_xml,
            task_definitions_match,
            task_definition_signature,
        )
        from src.utils.path_utils import get_resource_path

        if any(
            "conda" in str(value).lower()
            for value in (sys.executable, sys.base_prefix, sys.prefix)
        ):
            raise RuntimeError(
                "[CONDA_ENVIRONMENT_NOT_SUPPORTED] Conda／Miniconda環境は使用できません"
            )
        if os.name == "nt" and shutil.which("schtasks.exe") is None:
            raise RuntimeError("[SCHTASKS_NOT_FOUND] schtasks.exeが見つかりません")

        schedule_check = ScheduleConfig(
            enabled=True,
            interval="monthly",
            time="09:00",
            day_of_month=28,
        )
        task_xml = build_task_xml(
            schedule_check,
            Path(sys.executable).resolve(strict=False),
            [
                "--scheduled-run",
                "--config",
                str(Path("profile.yaml").resolve(strict=False)),
            ],
            working_directory=Path(sys.executable).resolve().parent,
        )
        signature = task_definition_signature(task_xml)
        if (
            "ScheduleByMonth" not in task_xml
            or "--scheduled-run" not in task_xml
            or not signature
            or calculate_next_run(schedule_check) is None
        ):
            raise RuntimeError(
                "[SCHEDULE_SELF_CHECK_FAILED] 定期実行定義を検証できません"
            )

        # exe版ではXMLの生成だけでなく、実際のWindows Task Schedulerへ
        # 一意な診断用タスクを登録・照会・削除する。通常のDownloadタスクや
        # 設定スナップショットには触れない。
        if os.name == "nt" and getattr(sys, "frozen", False):
            task_client = SchtasksClient()
            self_check_task_name = (
                rf"\ippi-down\SelfCheck-{os.getpid()}-{uuid.uuid4().hex[:8]}"
            )
            task_created = False
            try:
                task_client.create_or_update(self_check_task_name, task_xml)
                task_created = True
                task_query = task_client.query(self_check_task_name)
                if (
                    not task_query.exists
                    or not task_query.xml
                    or not task_definitions_match(task_query.xml, task_xml)
                ):
                    raise RuntimeError(
                        "[TASK_SELF_CHECK_MISMATCH] "
                        "診断用Windowsタスクの登録内容が一致しません"
                    )
            finally:
                if task_created:
                    try:
                        task_client.delete(self_check_task_name, missing_ok=True)
                    except Exception as cleanup_exc:
                        raise RuntimeError(
                            "[TASK_SELF_CHECK_CLEANUP_FAILED] "
                            f"診断用Windowsタスクを削除できません: {cleanup_exc}"
                        ) from cleanup_exc

        if os.name == "nt" and not WindowsJobProcessSupervisor.available():
            raise RuntimeError(
                "[EDGE_SUPERVISION_UNAVAILABLE] "
                "EdgeフォールバックのJob Object監視を利用できません"
            )
        # Edgeはフォールバックなので未導入でも内蔵生成の自己診断は行う。
        edge_path = HtmlToPdfConverter.discover_edge()

        project_name = "自己診断用トンネル工事"
        source_url = (
            "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/"
            "KokaiBunshoServlet?AnkenKanriNo=SELF_CHECK&BunshoKanriId=40"
        )
        fixture_path = get_resource_path("src/resources/self_check_bid_sheet.html")
        source_html = fixture_path.read_text(encoding="utf-8")

        temporary_root: Path | None = None
        with tempfile.TemporaryDirectory(prefix="ippi-down-self-check-") as temp_dir:
            temporary_root = Path(temp_dir)
            output_part = temporary_root / "bid-sheet.pdf.part"
            converter = HtmlToPdfConverter(
                edge_path=edge_path,
                audit=PdfConversionAudit(temporary_root / "audit"),
            )
            result = converter.convert(
                source_html,
                output_part,
                source_url=source_url,
                document_name="入札調書",
                project_name=project_name,
            )
            if not result.success:
                issue = result.primary_issue
                if issue is not None:
                    code = getattr(issue.code, "value", str(issue.code))
                    raise RuntimeError(f"[{code}] {issue.message}")
                raise RuntimeError(result.error or "入札調書のPDF生成に失敗しました")

            pdf_bytes = output_part.read_bytes()
            if not pdf_bytes.startswith(b"%PDF-"):
                raise RuntimeError("[OUTPUT_INVALID_PDF] PDF署名を確認できません")
            if b"%%EOF" not in pdf_bytes[-4096:]:
                raise RuntimeError("[OUTPUT_INVALID_PDF] PDF終端を確認できません")
            if result.bytes_written != len(pdf_bytes):
                raise RuntimeError(
                    "[OUTPUT_INVALID_PDF] PDFサイズが変換結果と一致しません"
                )
            digest = hashlib.sha256(pdf_bytes).hexdigest()
            if not result.sha256 or result.sha256 != digest:
                raise RuntimeError("[OUTPUT_INVALID_PDF] PDFのSHA-256が一致しません")
            media_box = re.search(
                rb"/MediaBox\s*\[\s*"
                rb"([-+]?\d+(?:\.\d+)?)\s+"
                rb"([-+]?\d+(?:\.\d+)?)\s+"
                rb"([-+]?\d+(?:\.\d+)?)\s+"
                rb"([-+]?\d+(?:\.\d+)?)\s*\]",
                pdf_bytes,
            )
            if media_box is None:
                raise RuntimeError("[OUTPUT_INVALID_PDF] PDFの用紙寸法を確認できません")
            x1, y1, x2, y2 = (float(value) for value in media_box.groups())
            width_points = x2 - x1
            height_points = y2 - y1
            if (
                abs(width_points - 595.28) > 3
                or abs(height_points - 841.89) > 3
                or width_points >= height_points
            ):
                raise RuntimeError("[OUTPUT_INVALID_PDF] PDFがA4縦ではありません")

            output_part.unlink()
            audit_root = temporary_root / "audit"
            if audit_root.is_dir() and not audit_root.is_symlink():
                shutil.rmtree(audit_root)
            if any(temporary_root.iterdir()):
                raise RuntimeError("[TEMP_CLEANUP_FAILED] 一時ファイルが残っています")

        if temporary_root is None or temporary_root.exists():
            raise RuntimeError("[TEMP_CLEANUP_FAILED] 一時フォルダーを削除できません")
    except Exception as exc:
        _report_self_check(
            f"ippi-down self-check: FAILED ({exc})",
            error=True,
        )
        return 1
    _report_self_check(f"ippi-down {__version__} self-check: OK")
    return 0


def download_files(
    main_window: MainWindow,
    config: AppConfig,
    window_was_visible: bool = True,
    redownload_policy: RedownloadPolicy | None = None,
):
    """ファイルをダウンロード（GUI用）"""
    logger = main_window.logger
    with manual_run_slot() as acquired:
        if not acquired:
            message = (
                "別のダウンロードが実行中、または定期実行が待機中のため、"
                "今回の実行を開始しません"
            )
            logger.warning(message)
            main_window.event_handler.emit(
                ProgressEvent(
                    type=EventType.MESSAGE,
                    message=message,
                    metadata={"type": "warning"},
                )
            )
            return

        logger.info("ダウンロードを開始します")
        service = ApplicationService(logger)

        def progress_callback(event: ProgressEvent):
            main_window.event_handler.emit(event)

        def cancel_check() -> bool:
            return main_window.cancel_flag.is_set()

        if redownload_policy is None:
            # 旧GUIコールバックや直接呼び出しとの互換性を保つ。
            run_result = service.run(config, progress_callback, cancel_check)
        else:
            run_result = service.run(
                config,
                progress_callback,
                cancel_check,
                redownload_policy=redownload_policy,
            )

        if run_result.result and not window_was_visible:
            Notifier(logger).notify("ippi-down", run_result.message, duration=10)


def run_scheduled_download(
    config: AppConfig,
    logger: Logger,
    *,
    acquire_guard: bool = True,
    notify: bool = True,
    cancel_check: Optional[Callable[[], bool]] = None,
    run_kind: RunKind = RunKind.SCHEDULED,
    run_id: str = "",
):
    """GUIなしで1回実行し、終了コード判定に使うRunResultを返す。"""

    def run_once():
        if run_kind is RunKind.SCHEDULED:
            logger.info("スケジュールに従ってダウンロードを開始します")
        else:
            logger.info("画面なしの単発ダウンロードを開始します")
        service = ApplicationService(logger)
        notifier = Notifier(logger) if notify else None

        def progress_callback(event: ProgressEvent):
            if (
                event.type in {EventType.FAIL, EventType.COMPLETE}
                or not event.message
                or (event.metadata and event.metadata.get("already_logged"))
            ):
                return
            level = event.metadata.get("type", "info") if event.metadata else "info"
            if level == "error":
                logger.error(event.message)
            elif level == "warning":
                logger.warning(event.message)
            else:
                logger.info(event.message)

        run_result = service.run(
            config,
            progress_callback,
            cancel_flag=cancel_check,
            run_kind=run_kind,
            run_id=run_id,
        )

        if not run_result.success:
            error_message = (
                run_result.message or run_result.error or "ダウンロードに失敗しました"
            )
            if run_result.outcome in {
                RunOutcome.CANCELLED,
                RunOutcome.NO_MATCH,
            }:
                logger.warning(error_message)
            else:
                logger.error(error_message)
            if notifier is not None:
                notifier.notify("ippi-down", error_message, duration=10)
            return run_result

        if run_result.outcome == RunOutcome.PARTIAL:
            logger.warning(run_result.message)
            if notifier is not None:
                notifier.notify(
                    "ippi-down",
                    run_result.message,
                    duration=10,
                )
            return run_result

        if run_result.result:
            logger.info(run_result.message)
            if notifier is not None:
                notifier.notify("ippi-down", run_result.message, duration=10)
        return run_result

    if not acquire_guard:
        return run_once()

    with DOWNLOAD_RUN_GUARD.try_acquire() as acquired:
        if not acquired:
            logger.warning(
                "別のダウンロードが実行中のため、スケジュール実行をスキップします"
            )
            return None
        return run_once()


class _RuntimeConfigError(ConfigError):
    """CLIで安定した理由コードへ変換する設定読込エラー。"""

    def __init__(
        self,
        message: str,
        reason_code: str,
        *,
        schedule_id: str = "",
        snapshot_id: str = "",
        display_name: str = "",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.schedule_id = schedule_id
        self.snapshot_id = snapshot_id
        self.display_name = display_name


class _RuntimeIdentity(str):
    """旧tuple APIを保ったままv2の2種類のIDを運ぶ文字列。"""

    schedule_id: str
    snapshot_id: str
    display_name: str

    def __new__(
        cls,
        profile_id: str,
        *,
        schedule_id: str = "",
        snapshot_id: str = "",
        display_name: str = "",
    ) -> "_RuntimeIdentity":
        instance = str.__new__(cls, profile_id)
        instance.schedule_id = schedule_id
        instance.snapshot_id = snapshot_id or profile_id
        instance.display_name = display_name
        return instance


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ippi-down")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--scheduled-run",
        action="store_true",
        help="登録済み設定スナップショットで定期実行します",
    )
    modes.add_argument(
        "--run-once",
        action="store_true",
        help="GUIを表示せず1回だけ実行します",
    )
    modes.add_argument(
        "--background",
        action="store_true",
        help="非推奨: --run-onceの互換alias",
    )
    modes.add_argument(
        "--self-check",
        action="store_true",
        help="配布物のオフライン自己診断を実行します",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="実行に使用する設定スナップショットまたは設定ファイル",
    )
    parser.add_argument(
        "--schedule-id",
        type=str,
        help="Windowsタスクへ登録された論理スケジュールID",
    )
    return parser


def _read_explicit_config(
    config_path: str,
    *,
    require_profile: bool = False,
    expected_schedule_id: Optional[str] = None,
) -> tuple[ConfigManager, AppConfig, str]:
    """明示パスは欠落・構文不正・検証不合格を既定値へ丸めない。"""
    import yaml

    path = Path(config_path).expanduser().resolve(strict=False)
    if not path.is_file():
        raise _RuntimeConfigError(
            f"設定ファイルが見つかりません: {path}",
            "CONFIG_NOT_FOUND",
        )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise _RuntimeConfigError(
            f"設定ファイルを読み込めません: {path}: {exc}",
            "CONFIG_READ_FAILED",
        ) from exc
    except yaml.YAMLError as exc:
        raise _RuntimeConfigError(
            f"設定ファイルのYAMLが不正です: {path}: {exc}",
            "CONFIG_PARSE_FAILED",
        ) from exc
    if not isinstance(document, Mapping):
        raise _RuntimeConfigError(
            "設定ファイルの最上位はマッピングである必要があります",
            "CONFIG_PARSE_FAILED",
        )

    metadata = document.get("_schedule_profile")
    raw_metadata_schedule_id = ""
    raw_metadata_snapshot_id = ""
    raw_metadata_display_name = ""
    if isinstance(metadata, Mapping):
        raw_metadata_schedule_id = str(metadata.get("schedule_id", "") or "")
        raw_metadata_snapshot_id = str(
            metadata.get("snapshot_id") or metadata.get("profile_id", "") or ""
        )
        raw_metadata_display_name = str(
            metadata.get("display_name") or metadata.get("name") or ""
        )
    if require_profile or metadata is not None:
        try:
            from src.scheduler.profile import ScheduleProfileStore
        except ImportError as exc:
            raise _RuntimeConfigError(
                "定期実行プロファイルを検証する機能を読み込めません",
                "PROFILE_VALIDATION_UNAVAILABLE",
            ) from exc
        try:
            # 登録後に検索条件だけを書き換えられた場合は実行しない。
            document = ScheduleProfileStore(path.parent).read(path)
        except Exception as exc:
            raise _RuntimeConfigError(
                str(exc),
                str(getattr(exc, "reason_code", "PROFILE_INVALID")),
                schedule_id=raw_metadata_schedule_id,
                snapshot_id=raw_metadata_snapshot_id,
                display_name=raw_metadata_display_name,
            ) from exc

    manager = ConfigManager(str(path))
    try:
        # ConfigManager.load_config()は通常GUI向けに不正設定を既定値へ
        # fallbackするため、タスク実行では変換・検証を明示的に行う。
        config = manager._dict_to_config(dict(document))
        valid, errors = manager.validate_config(config)
    except Exception as exc:
        raise _RuntimeConfigError(
            f"設定ファイルが不正です: {exc}",
            "CONFIG_INVALID",
            schedule_id=raw_metadata_schedule_id,
            snapshot_id=raw_metadata_snapshot_id,
            display_name=raw_metadata_display_name,
        ) from exc
    if not valid:
        raise _RuntimeConfigError(
            "設定ファイルが不正です: " + "、".join(errors),
            "CONFIG_INVALID",
            schedule_id=raw_metadata_schedule_id,
            snapshot_id=raw_metadata_snapshot_id,
            display_name=raw_metadata_display_name,
        )

    metadata = document.get("_schedule_profile", {})
    profile_id = ""
    snapshot_id = ""
    metadata_schedule_id = ""
    metadata_display_name = ""
    schema_version = 0
    if isinstance(metadata, Mapping):
        snapshot_id = str(
            metadata.get("snapshot_id") or metadata.get("profile_id", "") or ""
        )
        profile_id = snapshot_id
        metadata_schedule_id = str(metadata.get("schedule_id", "") or "")
        metadata_display_name = str(
            metadata.get("display_name") or metadata.get("name") or ""
        )
        try:
            schema_version = int(metadata.get("schema_version", 0) or 0)
        except (TypeError, ValueError):
            schema_version = 0
    if not profile_id:
        profile_id = str(getattr(config.schedule, "active_profile_id", "") or path.stem)
        snapshot_id = profile_id

    if schema_version >= 2 and not metadata_schedule_id:
        raise _RuntimeConfigError(
            "定期実行スナップショットにschedule_idがありません",
            "PROFILE_SCHEDULE_ID_MISSING",
            snapshot_id=snapshot_id,
            display_name=metadata_display_name,
        )
    if expected_schedule_id:
        try:
            expected = validate_schedule_id(expected_schedule_id)
        except ValueError as exc:
            raise _RuntimeConfigError(
                f"schedule_idが不正です: {exc}",
                "SCHEDULE_ID_INVALID",
            ) from exc
        if metadata_schedule_id and metadata_schedule_id != expected:
            raise _RuntimeConfigError(
                "Windowsタスクのschedule_idとスナップショットが一致しません",
                "SCHEDULE_ID_MISMATCH",
                schedule_id=metadata_schedule_id,
                snapshot_id=snapshot_id,
                display_name=metadata_display_name,
            )
    if metadata_schedule_id:
        try:
            validate_schedule_id(metadata_schedule_id)
        except ValueError as exc:
            raise _RuntimeConfigError(
                f"スナップショットのschedule_idが不正です: {exc}",
                "SCHEDULE_ID_INVALID",
                schedule_id=metadata_schedule_id,
                snapshot_id=snapshot_id,
                display_name=metadata_display_name,
            ) from exc

    return (
        manager,
        config,
        _RuntimeIdentity(
            profile_id,
            schedule_id=metadata_schedule_id,
            snapshot_id=snapshot_id,
            display_name=(
                metadata_display_name
                or ("既存の定期実行" if schema_version == 1 else "")
            ),
        ),
    )


def _load_runtime_config(
    config_path: Optional[str],
    *,
    require_profile: bool = False,
    expected_schedule_id: Optional[str] = None,
) -> tuple[ConfigManager, AppConfig, str]:
    if config_path:
        return _read_explicit_config(
            config_path,
            require_profile=require_profile,
            expected_schedule_id=expected_schedule_id,
        )
    manager = ConfigManager()
    try:
        config = manager.load_config()
    except (ConfigError, FilesystemError, TypeError, ValueError) as exc:
        raise _RuntimeConfigError(
            f"設定ファイルを読み込めません: {exc}",
            "CONFIG_INVALID",
        ) from exc
    profile_id = str(getattr(config.schedule, "active_profile_id", "") or "manual")
    return (
        manager,
        config,
        _RuntimeIdentity(
            profile_id,
            schedule_id="manual",
            snapshot_id=profile_id,
            display_name="",
        ),
    )


def _scheduled_at_from_environment(logger: Logger) -> datetime:
    jst = timezone(timedelta(hours=9), name="JST")
    fallback = datetime.now(jst)
    value = os.getenv("PPI_SCHEDULED_AT", "").strip()
    if not value:
        # Windows Task Schedulerは元のトリガー日時を子プロセスへ渡さない。
        # そのため実タスク経路では、プロセスの実行要求時刻を安全な代替値にする。
        return fallback
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        logger.warning(
            "PPI_SCHEDULED_ATがISO 8601形式ではないため実行要求時刻を使用します"
        )
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=jst)
    return parsed.astimezone(jst)


def _append_config_failure(
    logger: Logger,
    *,
    profile_id: str,
    reason_code: str,
    schedule_id: str = "default",
    snapshot_id: str = "",
    run_id: str = "",
    display_name: str = "",
    notification_policy: str = ScheduleNotificationPolicy.OFF.value,
    notify: bool = False,
) -> ExecutionRecord:
    record = make_config_failure_record(
        profile_id=profile_id,
        reason_code=reason_code,
        schedule_id=schedule_id,
        snapshot_id=snapshot_id or profile_id,
        run_id=run_id,
        display_name=display_name,
        scheduled_at=_scheduled_at_from_environment(logger),
    )
    try:
        make_schedule_record_sink(get_logs_path("schedule-runs.jsonl"))(record)
    except Exception as exc:
        logger.error(f"定期実行履歴を保存できません: {exc}")
    if notify:
        _notify_scheduled_record(logger, record, notification_policy)
    return record


def _notification_policy(config: AppConfig) -> str:
    value = getattr(
        getattr(config, "schedule", None),
        "notification_policy",
        ScheduleNotificationPolicy.OFF.value,
    )
    try:
        return ScheduleNotificationPolicy(value).value
    except (TypeError, ValueError):
        return ScheduleNotificationPolicy.OFF.value


def _notification_policy_from_path(config_path: str | Path) -> str:
    """壊れたsnapshotでも、通知方針だけを安全側で読み取る。"""

    try:
        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        schedule = raw.get("schedule", {}) if isinstance(raw, Mapping) else {}
        value = (
            schedule.get("notification_policy", ScheduleNotificationPolicy.OFF.value)
            if isinstance(schedule, Mapping)
            else ScheduleNotificationPolicy.OFF.value
        )
        return ScheduleNotificationPolicy(value).value
    except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError):
        return ScheduleNotificationPolicy.OFF.value


def _notify_scheduled_record(
    logger: Logger,
    record: ExecutionRecord,
    policy: str,
) -> float:
    """履歴確定後に通知し、通知障害を実行結果から分離する。"""

    try:
        delivery = ScheduledRunNotifier().notify(record, policy)
    except Exception as exc:
        logger.warning(
            "schedule.notification "
            + json.dumps(
                {
                    "schedule_id": record.schedule_id,
                    "run_id": record.run_id,
                    "reason_code": "NOTIFICATION_FAILED",
                    "error": type(exc).__name__,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0.0

    payload = {
        "schedule_id": record.schedule_id,
        "run_id": record.run_id,
        "status": delivery.status.value,
        "reason_code": delivery.reason_code,
        "elapsed_seconds": round(delivery.elapsed_seconds, 3),
    }
    message = "schedule.notification " + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )
    if delivery.reason_code in {
        "NOTIFICATION_FAILED",
        "NOTIFICATION_UNAVAILABLE",
    }:
        logger.warning(message)
    else:
        logger.info(message)
    return float(delivery.elapsed_seconds)


def _log_scheduled_lifecycle(
    logger: Logger,
    event: str,
    *,
    schedule_id: str,
    run_id: str,
    elapsed_seconds: float = 0.0,
    retry_wait_seconds: float = 0.0,
    notification_seconds: float = 0.0,
    exit_code: Optional[int] = None,
) -> None:
    payload: dict[str, object] = {
        "event": event,
        "pid": os.getpid(),
        "schedule_id": schedule_id,
        "run_id": run_id,
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 3),
        "retry_wait_seconds": round(max(0.0, retry_wait_seconds), 3),
        "notification_seconds": round(max(0.0, notification_seconds), 3),
    }
    if exit_code is not None:
        payload["exit_code"] = int(exit_code)
    logger.info(
        "schedule.lifecycle " + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _execute_cli_mode(
    config: AppConfig,
    logger: Logger,
    *,
    scheduled: bool,
    profile_id: str,
    schedule_id: str = "default",
    snapshot_id: str = "",
    run_id: str = "",
    trigger_kind: str = "manual_cli",
    display_name: str = "",
    scheduled_at: Optional[datetime] = None,
    use_waiting_queue: bool = True,
    initial_queue_wait_seconds: float = 0.0,
    guard_already_acquired: bool = False,
    retry_wait_callback: Optional[Callable[[bool, int, float], None]] = None,
) -> int:
    lifecycle_started = time.monotonic()
    retry_wait_seconds = 0.0
    retry_wait_started: dict[int, float] = {}
    if scheduled:
        _log_scheduled_lifecycle(
            logger,
            "start",
            schedule_id=schedule_id,
            run_id=run_id,
        )
    resolved_scheduled_at = scheduled_at
    if scheduled and resolved_scheduled_at is None:
        resolved_scheduled_at = _scheduled_at_from_environment(logger)
    runtime_config = prepare_runtime_config(config, logger)
    retry_policy = RetryPolicy(
        retry_count=(
            int(getattr(config.schedule, "retry_count", 2)) if scheduled else 0
        ),
        interval_minutes=(
            float(getattr(config.schedule, "retry_interval_minutes", 15))
            if scheduled
            else 0
        ),
    )
    sink = (
        make_schedule_record_sink(get_logs_path("schedule-runs.jsonl"))
        if scheduled
        else None
    )
    scheduled_queue = None
    if scheduled and use_waiting_queue:
        try:
            scheduled_queue = get_default_run_queue()
        except (OSError, RunQueueError) as exc:
            logger.error(f"実行キューを初期化できません: {exc}")
            record = make_queue_timeout_record(
                profile_id=profile_id,
                schedule_id=schedule_id,
                snapshot_id=snapshot_id or profile_id,
                run_id=run_id,
                trigger_kind=trigger_kind,
                display_name=display_name,
                scheduled_at=resolved_scheduled_at,
            )
            if sink is not None:
                try:
                    sink(record)
                except Exception as sink_exc:
                    logger.error(f"定期実行履歴を保存できません: {sink_exc}")
            notification_seconds = _notify_scheduled_record(
                logger, record, _notification_policy(config)
            )
            _log_scheduled_lifecycle(
                logger,
                "finish",
                schedule_id=schedule_id,
                run_id=run_id,
                elapsed_seconds=time.monotonic() - lifecycle_started,
                notification_seconds=notification_seconds,
                exit_code=int(HeadlessExitCode.QUEUE_TIMEOUT),
            )
            return int(HeadlessExitCode.QUEUE_TIMEOUT)
    processing_deadline: Optional[float] = None

    def set_processing_deadline(deadline: float) -> None:
        nonlocal processing_deadline
        processing_deadline = deadline

    def processing_timed_out() -> bool:
        return (
            processing_deadline is not None and time.monotonic() >= processing_deadline
        )

    def observe_retry_wait(
        waiting: bool,
        attempt: int,
        seconds: float,
    ) -> None:
        """実際の再試行待機時間を計測し、dispatcher状態も更新する。"""

        nonlocal retry_wait_seconds
        if waiting:
            retry_wait_started[attempt] = time.monotonic()
        else:
            started = retry_wait_started.pop(attempt, None)
            if started is not None:
                retry_wait_seconds += max(0.0, time.monotonic() - started)
        if retry_wait_callback is not None:
            retry_wait_callback(waiting, attempt, seconds)

    execution = execute_headless(
        lambda: run_scheduled_download(
            runtime_config,
            logger,
            acquire_guard=False,
            notify=False,
            cancel_check=processing_timed_out if scheduled else None,
            run_kind=(RunKind.SCHEDULED if scheduled else RunKind.MANUAL),
            run_id=run_id,
        ),
        logger=logger,
        profile_id=profile_id,
        schedule_id=schedule_id,
        snapshot_id=snapshot_id or profile_id,
        run_id=run_id,
        trigger_kind=trigger_kind,
        display_name=display_name,
        scheduled_at=resolved_scheduled_at if scheduled else None,
        retry_policy=retry_policy,
        guard=(
            _ALREADY_ACQUIRED_GUARD if guard_already_acquired else DOWNLOAD_RUN_GUARD
        ),
        run_queue=scheduled_queue,
        initial_queue_wait_seconds=initial_queue_wait_seconds,
        processing_deadline_callback=(set_processing_deadline if scheduled else None),
        retry_wait_callback=observe_retry_wait,
        record_sink=sink,
    )
    notification_seconds = 0.0
    if scheduled:
        notification_seconds = _notify_scheduled_record(
            logger,
            execution.record,
            _notification_policy(config),
        )
    if scheduled and execution.record.reason_code != "ALREADY_RUNNING":
        _finalize_scheduled_snapshot(
            logger,
            schedule_id=schedule_id,
            snapshot_id=snapshot_id or profile_id,
        )
    if scheduled:
        _log_scheduled_lifecycle(
            logger,
            "finish",
            schedule_id=schedule_id,
            run_id=run_id,
            elapsed_seconds=time.monotonic() - lifecycle_started,
            retry_wait_seconds=retry_wait_seconds,
            notification_seconds=notification_seconds,
            exit_code=int(execution.exit_code),
        )
    return int(execution.exit_code)


def _write_dispatch_control_record(
    logger: Logger,
    *,
    profile_id: str,
    schedule_id: str,
    snapshot_id: str,
    run_id: str,
    display_name: str,
    scheduled_at: Optional[datetime],
    result: str,
    reason_code: str,
    exit_code: int,
    queue_wait_seconds: float = 0.0,
    notification_policy: str = ScheduleNotificationPolicy.OFF.value,
    notify: bool = True,
) -> ExecutionRecord:
    moment = datetime.now().astimezone()
    record = ExecutionRecord(
        profile_id=profile_id,
        schedule_id=schedule_id,
        snapshot_id=snapshot_id or profile_id,
        run_id=run_id,
        trigger_kind="windows_task",
        queue_wait_seconds=max(0.0, queue_wait_seconds),
        display_name=display_name,
        scheduled_at=scheduled_at,
        started_at=moment,
        finished_at=moment,
        result=result,
        reason_code=reason_code,
        exit_code=int(exit_code),
    )
    try:
        make_schedule_record_sink(get_logs_path("schedule-runs.jsonl"))(record)
    except Exception as exc:
        logger.error(f"定期実行履歴を保存できません: {exc}")
    if notify:
        _notify_scheduled_record(logger, record, notification_policy)
    return record


def _run_cli_mode(
    config: AppConfig,
    logger: Logger,
    *,
    scheduled: bool,
    profile_id: str,
    schedule_id: str = "default",
    snapshot_id: str = "",
    run_id: str = "",
    trigger_kind: str = "manual_cli",
    display_name: str = "",
    config_path: str = "",
) -> int:
    """定期実行は軽量enqueue後、単一dispatcherでFIFO処理する。"""

    if not scheduled or not config_path:
        return _execute_cli_mode(
            config,
            logger,
            scheduled=scheduled,
            profile_id=profile_id,
            schedule_id=schedule_id,
            snapshot_id=snapshot_id,
            run_id=run_id,
            trigger_kind=trigger_kind,
            display_name=display_name,
        )

    scheduled_at = _scheduled_at_from_environment(logger)
    try:
        run_queue = get_default_run_queue()
        own_ticket = run_queue.enqueue_dispatch_request(
            schedule_id,
            run_id,
            snapshot_id=snapshot_id or profile_id,
            config_path=config_path,
            scheduled_at=scheduled_at,
        )
    except (OSError, RunQueueError, ValueError) as exc:
        logger.error(f"実行キューへ登録できません: {exc}")
        _write_dispatch_control_record(
            logger,
            profile_id=profile_id,
            schedule_id=schedule_id,
            snapshot_id=snapshot_id or profile_id,
            run_id=run_id,
            display_name=display_name,
            scheduled_at=scheduled_at,
            result="queue_timeout",
            reason_code="QUEUE_TIMEOUT",
            exit_code=int(HeadlessExitCode.QUEUE_TIMEOUT),
            notification_policy=_notification_policy(config),
        )
        return int(HeadlessExitCode.QUEUE_TIMEOUT)

    if own_ticket is None:
        logger.warning(
            "同じ定期実行が実行中または順番待ちのため、今回の要求を開始しません"
        )
        _write_dispatch_control_record(
            logger,
            profile_id=profile_id,
            schedule_id=schedule_id,
            snapshot_id=snapshot_id or profile_id,
            run_id=run_id,
            display_name=display_name,
            scheduled_at=scheduled_at,
            result="busy",
            reason_code="ALREADY_RUNNING",
            exit_code=int(HeadlessExitCode.ALREADY_RUNNING),
            notification_policy=_notification_policy(config),
        )
        return int(HeadlessExitCode.ALREADY_RUNNING)

    own_exit_code = int(HeadlessExitCode.SUCCESS)
    profile_root = Path(config_path).expanduser().resolve(strict=False).parent
    with run_queue.dispatcher_lease(handoff_seconds=0.5) as dispatcher:
        if not dispatcher:
            logger.info(
                "定期実行要求をdispatcherのFIFOキューへ登録しました。"
                "この起動プロセスは待機せず終了します"
            )
            return int(HeadlessExitCode.SUCCESS)

        while True:
            ticket = run_queue.claim_next_dispatch_request()
            if ticket is None:
                break
            ticket_exit_code = int(HeadlessExitCode.QUEUE_TIMEOUT)
            try:
                with run_queue.dispatch_turn(ticket) as turn:
                    if not turn.acquired:
                        control_policy = (
                            _notification_policy(config)
                            if ticket.ticket_id == own_ticket.ticket_id
                            else _notification_policy_from_path(
                                profile_root / f"{ticket.snapshot_id}.yaml"
                            )
                        )
                        _write_dispatch_control_record(
                            logger,
                            profile_id=ticket.snapshot_id,
                            schedule_id=ticket.schedule_id,
                            snapshot_id=ticket.snapshot_id,
                            run_id=ticket.run_id,
                            display_name="",
                            scheduled_at=ticket.scheduled_at,
                            result="queue_timeout",
                            reason_code="QUEUE_TIMEOUT",
                            exit_code=int(HeadlessExitCode.QUEUE_TIMEOUT),
                            queue_wait_seconds=turn.wait_seconds,
                            notification_policy=control_policy,
                        )
                    else:
                        try:
                            if ticket.ticket_id == own_ticket.ticket_id:
                                ticket_config = config
                                ticket_identity = _RuntimeIdentity(
                                    profile_id,
                                    schedule_id=schedule_id,
                                    snapshot_id=snapshot_id or profile_id,
                                    display_name=display_name,
                                )
                                ticket_logger = logger
                            else:
                                from src.scheduler.profile import (
                                    ScheduleProfileStore,
                                )

                                ticket_config_path = ScheduleProfileStore(
                                    profile_root
                                ).path_for(ticket.snapshot_id)
                                _, ticket_config, ticket_identity = (
                                    _load_runtime_config(
                                        str(ticket_config_path),
                                        require_profile=True,
                                        expected_schedule_id=ticket.schedule_id,
                                    )
                                )
                                ticket_logger = Logger(ticket_config.logging)
                        except _RuntimeConfigError as exc:
                            ticket_logger = logger
                            ticket_logger.error(str(exc))
                            _append_config_failure(
                                ticket_logger,
                                profile_id=ticket.snapshot_id,
                                snapshot_id=ticket.snapshot_id,
                                schedule_id=ticket.schedule_id,
                                reason_code=exc.reason_code,
                                run_id=ticket.run_id,
                                notification_policy=_notification_policy_from_path(
                                    profile_root / f"{ticket.snapshot_id}.yaml"
                                ),
                                notify=True,
                            )
                            ticket_exit_code = int(HeadlessExitCode.CONFIG_INVALID)
                        else:
                            with run_queue.schedule_lease(
                                ticket.schedule_id
                            ) as schedule_acquired:
                                if not schedule_acquired:
                                    _write_dispatch_control_record(
                                        ticket_logger,
                                        profile_id=str(ticket_identity),
                                        schedule_id=ticket.schedule_id,
                                        snapshot_id=(
                                            ticket.snapshot_id or str(ticket_identity)
                                        ),
                                        run_id=ticket.run_id,
                                        display_name=str(
                                            getattr(
                                                ticket_identity,
                                                "display_name",
                                                "",
                                            )
                                            or ""
                                        ),
                                        scheduled_at=ticket.scheduled_at,
                                        result="busy",
                                        reason_code="ALREADY_RUNNING",
                                        exit_code=int(HeadlessExitCode.ALREADY_RUNNING),
                                        queue_wait_seconds=turn.wait_seconds,
                                        notification_policy=_notification_policy(
                                            ticket_config
                                        ),
                                    )
                                    ticket_exit_code = int(
                                        HeadlessExitCode.ALREADY_RUNNING
                                    )
                                else:

                                    def update_retry_wait(
                                        waiting: bool,
                                        _attempt: int,
                                        _seconds: float,
                                    ) -> None:
                                        run_queue.set_dispatch_state(
                                            ticket.ticket_id,
                                            ("retry_waiting" if waiting else "running"),
                                        )

                                    ticket_exit_code = _execute_cli_mode(
                                        ticket_config,
                                        ticket_logger,
                                        scheduled=True,
                                        profile_id=str(ticket_identity),
                                        schedule_id=ticket.schedule_id,
                                        snapshot_id=(
                                            ticket.snapshot_id or str(ticket_identity)
                                        ),
                                        run_id=ticket.run_id,
                                        trigger_kind="windows_task",
                                        display_name=str(
                                            getattr(
                                                ticket_identity,
                                                "display_name",
                                                "",
                                            )
                                            or ""
                                        ),
                                        scheduled_at=ticket.scheduled_at,
                                        use_waiting_queue=False,
                                        initial_queue_wait_seconds=(turn.wait_seconds),
                                        guard_already_acquired=True,
                                        retry_wait_callback=update_retry_wait,
                                    )
            finally:
                try:
                    run_queue.complete_dispatch_request(ticket.ticket_id)
                except RunQueueError as exc:
                    logger.warning(f"処理済み定期実行ticketを削除できません: {exc}")
            if ticket.ticket_id == own_ticket.ticket_id:
                own_exit_code = ticket_exit_code
    return own_exit_code


def _create_schedule_service(logger: Logger) -> Optional[Any]:
    """Windows scheduler backendを必要な経路でだけ遅延読込する。"""
    try:
        from src.scheduler.service import ScheduleService
    except ImportError as exc:
        logger.warning(f"Windowsタスク連携を読み込めません: {exc}")
        return None
    try:
        return ScheduleService()
    except Exception as exc:
        logger.error(f"Windowsタスク連携を初期化できません: {exc}")
        return None


def _installation_startup_block_reason(
    *,
    headless: bool,
) -> Optional[tuple[str, str]]:
    """廃止配置と、非GUIで確認できない配置差分を実行前に拒否する。"""

    try:
        from src.scheduler.installation import InstallationLocationStore

        current_root = get_base_path().resolve(strict=False)
        location = InstallationLocationStore(
            current_root / "config" / "install-location.json"
        ).read()
    except Exception as exc:
        return (
            "INSTALLATION_LOCATION_INVALID",
            f"配置場所の管理情報を確認できません: {exc}",
        )
    if location is not None and location.status == "retired":
        return (
            "INSTALLATION_RETIRED",
            "この配置は移行済みのため起動できません。"
            f"現在の配置を使用してください: {location.moved_to or '-'}",
        )
    if headless and location is not None:
        try:
            same_root = os.path.normcase(str(location.app_root)) == os.path.normcase(
                str(current_root)
            )
        except (OSError, RuntimeError, ValueError):
            same_root = False
        if not same_root:
            return (
                "INSTALLATION_PATH_CHANGED",
                "配置フォルダーが変更されています。GUIを起動して現在の配置へ"
                "付け替えてください",
            )
    if headless:
        try:
            from src.scheduler.service import ScheduleService

            service = ScheduleService(
                app_root=current_root,
                config_dir=current_root / "config",
                logs_dir=current_root / "logs",
                executable=(sys.executable if getattr(sys, "frozen", False) else None),
                script_path=current_root / "src" / "main.py",
                queue_ticket_provider=lambda: (),
            )
            preview = service.preview_installation_relocation()
        except Exception as exc:
            return (
                "INSTALLATION_RELOCATION_CHECK_FAILED",
                f"配置変更の有無を確認できません: {exc}",
            )
        if preview.required:
            return (
                preview.reason_code or "INSTALLATION_PATH_CHANGED",
                preview.blocked_reason
                or "配置フォルダーが変更されています。GUIを起動して現在の配置へ"
                "付け替えてください",
            )
    return None


def _finalize_scheduled_snapshot(
    logger: Logger,
    *,
    schedule_id: str,
    snapshot_id: str,
) -> None:
    """完了済み実行が参照していた旧snapshotをbest-effortで回収する。"""

    service = _create_schedule_service(logger)
    if service is None:
        return
    finalizer = getattr(service, "finalize_scheduled_run", None)
    if not callable(finalizer):
        return
    try:
        finalizer(schedule_id, snapshot_id)
    except Exception as exc:
        # 実行結果とTask Schedulerの終了コードは、後処理失敗で変えない。
        logger.warning(f"完了済みの定期実行スナップショットを回収できません: {exc}")


def main(argv: Optional[Sequence[str]] = None):
    """GUIと非GUIの全起動経路を振り分ける。"""
    args = _build_argument_parser().parse_args(
        list(argv) if argv is not None else sys.argv[1:]
    )
    run_id = uuid.uuid4().hex
    if args.self_check:
        return run_self_check()

    environment_background = os.getenv("PPI_BACKGROUND_MODE", "").lower() == "true"
    legacy_background = args.background or (
        environment_background and not args.scheduled_run and not args.run_once
    )
    headless = args.scheduled_run or args.run_once or legacy_background
    requested_schedule_id = str(args.schedule_id or "").strip()
    if args.schedule_id and not args.scheduled_run:
        logger = Logger()
        logger.error("--schedule-idは--scheduled-runと一緒に指定してください")
        return int(HeadlessExitCode.CONFIG_INVALID)
    if requested_schedule_id:
        try:
            validate_schedule_id(requested_schedule_id)
        except ValueError as exc:
            logger = Logger()
            logger.error(f"schedule_idが不正です: {exc}")
            _append_config_failure(
                logger,
                profile_id=Path(args.config or "unknown").stem or "unknown",
                schedule_id="default",
                reason_code="SCHEDULE_ID_INVALID",
                run_id=run_id,
                notification_policy=(
                    _notification_policy_from_path(args.config)
                    if args.scheduled_run and args.config
                    else ScheduleNotificationPolicy.OFF.value
                ),
                notify=bool(args.scheduled_run and args.config),
            )
            return int(HeadlessExitCode.CONFIG_INVALID)
    if args.scheduled_run and not args.config:
        logger = Logger()
        message = "--scheduled-runには--configの指定が必要です"
        logger.error(message)
        _append_config_failure(
            logger,
            profile_id="unknown",
            schedule_id=requested_schedule_id or "default",
            reason_code="CONFIG_PATH_REQUIRED",
            run_id=run_id,
        )
        return int(HeadlessExitCode.CONFIG_INVALID)
    if args.config and not headless:
        logger = Logger()
        logger.error("--configは非GUI実行モードでのみ指定できます")
        return int(HeadlessExitCode.CONFIG_INVALID)

    installation_block = _installation_startup_block_reason(headless=headless)
    if installation_block is not None:
        reason_code, message = installation_block
        logger = Logger()
        logger.error(f"{message} [{reason_code}]")
        if args.scheduled_run:
            _append_config_failure(
                logger,
                profile_id=Path(args.config or "unknown").stem or "unknown",
                schedule_id=requested_schedule_id or "default",
                reason_code=reason_code,
                run_id=run_id,
            )
        elif not headless:
            _show_startup_error(message)
        return int(HeadlessExitCode.CONFIG_INVALID)

    try:
        config_manager, config, profile_id = _load_runtime_config(
            args.config,
            require_profile=args.scheduled_run,
            expected_schedule_id=(
                requested_schedule_id if args.scheduled_run else None
            ),
        )
    except _RuntimeConfigError as exc:
        logger = Logger()
        logger.error(str(exc))
        if args.scheduled_run:
            failed_snapshot_id = str(
                getattr(exc, "snapshot_id", "")
                or Path(args.config or "unknown").stem
                or "unknown"
            )
            failed_schedule_id = str(
                requested_schedule_id or getattr(exc, "schedule_id", "") or "default"
            )
            _append_config_failure(
                logger,
                profile_id=failed_snapshot_id,
                snapshot_id=failed_snapshot_id,
                schedule_id=failed_schedule_id,
                reason_code=exc.reason_code,
                run_id=run_id,
                display_name=str(getattr(exc, "display_name", "") or ""),
                notification_policy=(
                    _notification_policy_from_path(args.config)
                    if args.config
                    else ScheduleNotificationPolicy.OFF.value
                ),
                notify=bool(args.config),
            )
        elif not headless:
            _show_startup_error(str(exc))
        return int(HeadlessExitCode.CONFIG_INVALID)

    metadata_schedule_id = str(getattr(profile_id, "schedule_id", "") or "")
    snapshot_id = str(getattr(profile_id, "snapshot_id", "") or str(profile_id))
    display_name = str(getattr(profile_id, "display_name", "") or "")
    resolved_schedule_id = (
        requested_schedule_id
        or metadata_schedule_id
        or ("default" if args.scheduled_run else "manual")
    )
    if (
        args.scheduled_run
        and requested_schedule_id
        and metadata_schedule_id
        and requested_schedule_id != metadata_schedule_id
    ):
        logger = Logger()
        logger.error("Windowsタスクのschedule_idとスナップショットが一致しません")
        _append_config_failure(
            logger,
            profile_id=str(profile_id),
            snapshot_id=snapshot_id,
            schedule_id=requested_schedule_id,
            reason_code="SCHEDULE_ID_MISMATCH",
            run_id=run_id,
            display_name=display_name,
            notification_policy=_notification_policy(config),
            notify=True,
        )
        return int(HeadlessExitCode.CONFIG_INVALID)

    logger = Logger(config.logging)
    if legacy_background:
        logger.warning(
            "--backgroundおよびPPI_BACKGROUND_MODEは非推奨です。"
            "今回は--run-onceとして1回だけ実行します"
        )
    if headless:
        return _run_cli_mode(
            config,
            logger,
            scheduled=args.scheduled_run,
            profile_id=str(profile_id),
            schedule_id=resolved_schedule_id,
            snapshot_id=snapshot_id,
            run_id=run_id,
            display_name=display_name,
            trigger_kind=(
                "windows_task"
                if args.scheduled_run
                else ("legacy_background" if legacy_background else "manual_cli")
            ),
            config_path=str(args.config or ""),
        )

    # GUIモード
    try:
        import tkinter as tk
        from src.gui.main_window import MainWindow
    except Exception as exc:
        logger.error(f"GUIモジュールを読み込めません: {exc}")
        return 1
    root = tk.Tk()
    main_window = MainWindow(root, config, config_manager, logger)
    main_window.set_download_callback(
        lambda mw, run_config, visible, policy: download_files(
            mw, run_config, visible, policy
        )
    )

    # GUIを閉じても継続するWindowsタスクをサービスとして注入する。
    schedule_service = _create_schedule_service(logger)
    if schedule_service is not None:
        setter = getattr(main_window, "set_schedule_service", None)
        if callable(setter):
            setter(schedule_service)

    # 保存済みファイルの再分類も、通常ダウンロードと同じFIFO実行枠と
    # GUIが所有するHTTP Sessionを使用する。初期化時には通信しない。
    reclassification_service = ReclassificationService(
        logger,
        agency_resolver=_GuiReclassificationAgencyResolver(main_window),
        run_guard=_ManualRunSlotGuard(),
    )
    reclassification_setter = getattr(main_window, "set_reclassification_service", None)
    if callable(reclassification_setter):
        reclassification_setter(reclassification_service)

    root.mainloop()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main() or 0)
