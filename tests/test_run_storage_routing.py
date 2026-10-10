"""通常実行と定期実行の保存ルート振り分けテスト。"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.app.service import ApplicationService, _ExtractionResult
from src.models.config_model import AppConfig, SavePaths, SearchConditions
from src.models.download_result import DownloadResult
from src.models.file_info import FileInfo
from src.models.search_summary import SearchExtractionSummary
from src.models.search_target import SearchTarget
from src.storage.layout import RunKind


@pytest.mark.parametrize(
    ("run_kind", "relative_parts"),
    [
        (RunKind.MANUAL, ("01_通常ダウンロード",)),
        (
            RunKind.SCHEDULED,
            ("02_定期実行", "S001_東北トンネル"),
        ),
    ],
)
def test_application_service_routes_download_to_run_specific_root(
    tmp_path,
    run_kind,
    relative_parts,
):
    config = AppConfig(
        save_paths=SavePaths(
            local=str(tmp_path),
            layout_version=3,
            normal_folder="01_通常ダウンロード",
            scheduled_folder="02_定期実行",
            schedule_storage_key="S001",
            schedule_storage_folder="S001_東北トンネル",
        )
    )
    file_info = FileInfo(
        url="https://example.test/document.pdf",
        filename="document.pdf",
        file_type=".pdf",
    )
    extraction = _ExtractionResult(
        files=[file_info],
        attempted=1,
        search_summary=SearchExtractionSummary(),
    )
    service = ApplicationService(Mock())
    service._initialize_components = Mock()
    service._extract_files = Mock(return_value=extraction)
    service._filter_files = Mock(return_value=[file_info])
    service._apply_filter_decisions = Mock()
    service._emit_search_summary = Mock()
    service._apply_download_results = Mock()
    service._download_files = Mock(
        return_value=DownloadResult(total=1, success=1)
    )

    service.run(config, run_kind=run_kind)

    expected = Path(tmp_path, *relative_parts).resolve()
    assert service._download_files.call_args.kwargs["save_dir"] == expected
    assert service._download_files.call_args.kwargs["run_kind"] is run_kind
    assert expected.is_dir()


@pytest.mark.parametrize(
    ("target", "target_folder"),
    [
        (SearchTarget.KOJI_KEIKA, "工事の検索（入札の経過）"),
        (SearchTarget.GYOMU_KEIKA, "業務の検索（入札の経過）"),
    ],
)
def test_application_service_routes_v4_to_target_first_root(
    tmp_path,
    target,
    target_folder,
):
    config = AppConfig(
        search_conditions=SearchConditions.for_target(target),
        save_paths=SavePaths(
            local=str(tmp_path),
            layout_version=4,
            normal_folder="01_通常ダウンロード",
            scheduled_folder="02_定期実行",
        ),
    )
    file_info = FileInfo(
        url="https://example.test/document.pdf",
        filename="document.pdf",
        file_type=".pdf",
    )
    service = ApplicationService(Mock())
    service._initialize_components = Mock()
    service._extract_files = Mock(
        return_value=_ExtractionResult(
            files=[file_info],
            attempted=1,
            search_summary=SearchExtractionSummary(),
        )
    )
    service._filter_files = Mock(return_value=[file_info])
    service._apply_filter_decisions = Mock()
    service._emit_search_summary = Mock()
    service._apply_download_results = Mock()
    service._download_files = Mock(
        return_value=DownloadResult(total=1, success=1)
    )

    service.run(config, run_kind=RunKind.MANUAL)

    expected = (tmp_path / target_folder / "01_通常ダウンロード").resolve()
    assert service._download_files.call_args.kwargs["save_dir"] == expected
    assert expected.is_dir()


def test_legacy_layout_keeps_exact_configured_root(tmp_path):
    config = AppConfig(
        save_paths=SavePaths(local=str(tmp_path), layout_version=2)
    )
    file_info = FileInfo(
        url="https://example.test/document.pdf",
        filename="document.pdf",
        file_type=".pdf",
    )
    service = ApplicationService(Mock())
    service._initialize_components = Mock()
    service._extract_files = Mock(
        return_value=_ExtractionResult(files=[file_info], attempted=1)
    )
    service._filter_files = Mock(return_value=[file_info])
    service._apply_filter_decisions = Mock()
    service._emit_search_summary = Mock()
    service._apply_download_results = Mock()
    service._download_files = Mock(
        return_value=DownloadResult(total=1, success=1)
    )

    service.run(config, run_kind=RunKind.SCHEDULED)

    assert (
        service._download_files.call_args.kwargs["save_dir"]
        == tmp_path.resolve()
    )


def test_scheduled_download_records_run_kind_and_fixed_storage_key(tmp_path):
    config = AppConfig(
        save_paths=SavePaths(
            local=str(tmp_path),
            layout_version=3,
            schedule_storage_key="S012",
            schedule_storage_folder="S012_橋梁案件",
        )
    )
    file_info = FileInfo(
        url="https://example.test/document.pdf",
        filename="document.pdf",
        file_type=".pdf",
    )
    service = ApplicationService(Mock())
    service._downloader = Mock()
    service._downloader.download_files.return_value = DownloadResult()
    service._naming = Mock()

    service._download_files(
        [file_info],
        config,
        progress_callback=None,
        cancel_flag=None,
        save_dir=tmp_path / "02_定期実行" / "S012_橋梁案件",
        run_kind=RunKind.SCHEDULED,
    )

    assert file_info.metadata["run_kind"] == "SCHEDULED"
    assert file_info.metadata["storage_key"] == "S012"
    assert (
        service._downloader.download_files.call_args.kwargs["layout_version"]
        == 3
    )
