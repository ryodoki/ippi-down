# -*- coding: utf-8 -*-

"""発注機関階層を使う保存レイアウトv3のテスト。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.downloader import Downloader
from src.core.naming import Naming
from src.models.config_model import SearchConditions
from src.models.file_info import FileInfo
from src.models.search_target import SearchTarget
from src.storage.layout import RunKind, resolve_run_root
from src.utils.file_utils import FileUtils
from src.utils.http_client import DownloadFileResult, DownloadStatus


PDF = b"%PDF-1.7\nlayout-v3\n%%EOF\n"


def _agency_path(resolution: object = None) -> dict:
    return {
        "version": 2,
        "segments": [
            {"level": "daibunrui", "label": "国の機関", "code": "1"},
            {"level": "chubunrui", "label": "国土交通省", "code": "10"},
            {
                "level": "shoubunrui",
                "label": "東北地方整備局",
                "code": "100",
            },
            {
                "level": "saibunrui",
                "label": "山形河川国道事務所",
                "code": "1001",
            },
        ],
        "resolution": resolution
        or {
            "status": "detail_matched",
            "method": "office_name",
            "reason": "",
            "reason_code": "OFFICE_LABEL_MATCH",
        },
    }


def _file(*, agency_path: object = None) -> FileInfo:
    metadata = {
        "koji_name": "国道１３号 金山第二トンネル工事",
        "document_name": "入札公告",
        "document_updated_at": "2026年07月30日 12時00分",
        "document_section": "入札公告等",
        "document_id": "41",
    }
    if agency_path is not None:
        metadata["agency_path"] = agency_path
    return FileInfo(
        "https://example.test/document.pdf?BunshoKanriId=41",
        "document.pdf",
        ".pdf",
        metadata=metadata,
    )


class RecordingHTTPClient:
    def __init__(self):
        self.calls = []

    def download_file(self, url, save_path, *args, **kwargs):
        del args, kwargs
        self.calls.append(save_path)
        Path(save_path).write_bytes(PDF)
        return DownloadFileResult(
            DownloadStatus.SUCCESS,
            url,
            save_path,
            bytes_written=len(PDF),
            sha256=hashlib.sha256(PDF).hexdigest(),
            attempts=1,
            final_url=url,
        )


class LegacyOnlyNaming:
    """generate_folder_partsのない既存モック相当。"""

    def generate_folder_name(self, _file_info):
        return "legacy-folder"

    def generate_filename(self, file_info, _metadata, _index):
        return file_info.filename

    @staticmethod
    def ensure_unique(path):
        return path


def test_resolve_run_root_separates_manual_and_scheduled_layout_v3(tmp_path):
    save_paths = SimpleNamespace(
        local=str(tmp_path),
        layout_version=3,
        normal_folder="01_通常ダウンロード",
        scheduled_folder="02_定期実行",
        schedule_storage_folder="S001_東北トンネル",
    )

    assert resolve_run_root(
        save_paths, RunKind.MANUAL, SearchTarget.KOJI_KEIKA
    ) == (
        tmp_path / "01_通常ダウンロード"
    )
    assert resolve_run_root(
        save_paths, "scheduled", SearchTarget.KOJI_KEIKA
    ) == (
        tmp_path / "02_定期実行" / "S001_東北トンネル"
    )


@pytest.mark.parametrize(
    ("search_target", "target_folder"),
    [
        (SearchTarget.KOJI_KEIKA, "工事の検索（入札の経過）"),
        (SearchTarget.GYOMU_KEIKA, "業務の検索（入札の経過）"),
    ],
)
def test_resolve_run_root_separates_search_targets_in_layout_v4(
    tmp_path,
    search_target,
    target_folder,
):
    save_paths = SimpleNamespace(
        local=str(tmp_path),
        layout_version=4,
        normal_folder="01_通常ダウンロード",
        scheduled_folder="02_定期実行",
        schedule_storage_folder="S001_資材単価",
    )

    assert resolve_run_root(
        save_paths, RunKind.MANUAL, search_target
    ) == tmp_path / target_folder / "01_通常ダウンロード"
    assert resolve_run_root(
        save_paths, RunKind.SCHEDULED, search_target
    ) == (
        tmp_path
        / target_folder
        / "02_定期実行"
        / "S001_資材単価"
    )


def test_resolve_run_root_preserves_legacy_layout_and_rejects_missing_schedule():
    legacy = SimpleNamespace(local="./downloads", layout_version=2)
    assert resolve_run_root(
        legacy, RunKind.SCHEDULED, SearchTarget.KOJI_KEIKA
    ) == Path("./downloads")

    incomplete = SimpleNamespace(
        local="./downloads",
        layout_version=3,
        scheduled_folder="02_定期実行",
        schedule_storage_folder="",
    )
    with pytest.raises(ValueError, match="schedule_storage_folder"):
        resolve_run_root(
            incomplete, RunKind.SCHEDULED, SearchTarget.KOJI_KEIKA
        )


def test_generate_folder_parts_matches_agency_tree_and_document_section():
    naming = Naming(
        "{document_name}_{document_updated_at}",
        logger=MagicMock(),
    )

    assert naming.generate_folder_parts(_file(agency_path=_agency_path())) == [
        "国の機関",
        "国土交通省",
        "東北地方整備局",
        "山形河川国道事務所",
        "国道１３号_金山第二トンネル工事",
        "01_入札公告等",
    ]


def test_generate_folder_parts_accepts_string_resolution_and_search_fallback():
    path = _agency_path("selected")
    naming = Naming("{filename}", logger=MagicMock())
    assert naming.generate_folder_parts(_file(agency_path=path))[0] == "国の機関"

    fallback = Naming(
        "{filename}",
        logger=MagicMock(),
        search_conditions=SearchConditions(
            hachu_daibunrui="国の機関",
            hachu_chubunrui="国土交通省",
        ),
    )
    assert fallback.generate_folder_parts(_file())[:2] == [
        "国の機関",
        "国土交通省",
    ]


def test_generate_folder_parts_isolates_unresolved_agency_and_unknown_section():
    file_info = _file()
    file_info.metadata.update(
        {
            "hachu_kikan": "国土交通省/不明部局",
            "office_name": "CON",
            "document_section": "その他資料",
        }
    )
    naming = Naming("{filename}", logger=MagicMock())

    parts = naming.generate_folder_parts(file_info)

    assert parts[:3] == ["99_分類未解決", "国土交通省_不明部局", "_CON"]
    assert parts[-1] == "99_区分不明"


def test_partial_unresolved_path_keeps_detail_office_in_saved_hierarchy():
    path = _agency_path({
        "status": "unresolved",
        "method": "detail",
        "reason": "細分類候補なし",
        "reason_code": "AGENCY_FINE_NOT_FOUND",
    })
    path["version"] = 2
    path["segments"] = path["segments"][:3]
    file_info = _file(agency_path=path)
    file_info.metadata["office_name"] = "飯田国道事務所"

    parts = Naming("{filename}", logger=MagicMock()).generate_folder_parts(
        file_info
    )

    assert parts[:5] == [
        "99_分類未解決",
        "国の機関",
        "国土交通省",
        "東北地方整備局",
        "飯田国道事務所",
    ]


def test_multilevel_safe_path_is_contained_stable_and_within_240(tmp_path):
    parts = ["..", "CON", "案件" * 100, "資料" * 100]
    first = FileUtils.build_safe_download_path_parts(
        tmp_path,
        parts,
        "公告" * 100 + ".pdf",
    )
    second = FileUtils.build_safe_download_path_parts(
        tmp_path,
        parts,
        "公告" * 99 + "別.pdf",
    )

    assert first.resolve().is_relative_to(tmp_path.resolve())
    assert first.parts[-5] == "untitled"
    assert first.parts[-4] == "_CON"
    assert len(str(first)) <= 240
    assert first.suffix == ".pdf"
    assert first != second


def test_downloader_v3_uses_parts_and_writes_agency_history(tmp_path):
    file_info = _file(agency_path=_agency_path())
    file_info.metadata.update(
        {
            "run_kind": "MANUAL",
            "agency_id": "office-1001",
            "office_name": "山形河川国道事務所",
        }
    )
    naming = Naming(
        "{document_name}_{document_updated_at}",
        logger=MagicMock(),
    )
    http = RecordingHTTPClient()

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        naming,
        layout_version=3,
    )

    destination = Path(result.tasks[0].local_path)
    assert destination.relative_to(tmp_path).parts == (
        "国の機関",
        "国土交通省",
        "東北地方整備局",
        "山形河川国道事務所",
        "国道１３号_金山第二トンネル工事",
        "01_入札公告等",
        "入札公告_20260730_1200.pdf",
    )
    record = json.loads(
        (tmp_path / ".ippi-download-history.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["schema_version"] == 2
    assert record["layout_version"] == 3
    assert record["agency_path"]["segments"][-1] == {
        "level": "saibunrui",
        "label": "山形河川国道事務所",
        "code": "1001",
    }
    assert record["agency_path"]["resolution"]["status"] == "detail_matched"
    assert record["run_kind"] == "MANUAL"
    assert record["agency_id"] == "office-1001"
    assert record["agency_path"]["version"] == 2
    assert record["agency_path"]["resolution"]["reason_code"] == (
        "OFFICE_LABEL_MATCH"
    )


def test_layout_v3_does_not_reuse_flat_v2_alias_and_preserves_old_file(tmp_path):
    file_info = _file(agency_path=_agency_path())
    old_relative = Path("old-flat-folder") / "old-name.pdf"
    old_path = tmp_path / old_relative
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(PDF)
    old_record = {
        "schema_version": 2,
        "url": file_info.url,
        "path": old_relative.as_posix(),
        "target_path": old_relative.as_posix(),
        "expected_format": ".pdf",
        "status": "SUCCESS",
        "size": len(PDF),
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "completed_at": "2026-08-01T00:00:00+09:00",
    }
    (tmp_path / ".ippi-download-history.jsonl").write_text(
        json.dumps(old_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    http = RecordingHTTPClient()
    naming = Naming(
        "{document_name}_{document_updated_at}",
        logger=MagicMock(),
    )

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        naming,
        layout_version=3,
    )

    assert len(http.calls) == 1
    assert result.success == 1
    assert result.reused == 0
    assert old_path.read_bytes() == PDF
    assert Path(result.tasks[0].local_path) != old_path


def test_layout_v3_falls_back_to_legacy_naming_mock(tmp_path):
    http = RecordingHTTPClient()

    result = Downloader(http, MagicMock()).download_files(
        [_file()],
        str(tmp_path),
        LegacyOnlyNaming(),
        layout_version=3,
    )

    assert Path(result.tasks[0].local_path) == (
        tmp_path / "legacy-folder" / "document.pdf"
    )


def test_layout_v3_does_not_reuse_v2_record_even_when_target_is_same(tmp_path):
    file_info = _file()
    relative = Path("legacy-folder") / "document.pdf"
    existing = tmp_path / relative
    existing.parent.mkdir(parents=True)
    existing.write_bytes(PDF)
    record = {
        "schema_version": 2,
        "url": file_info.url,
        "path": relative.as_posix(),
        "target_path": relative.as_posix(),
        "expected_format": ".pdf",
        "status": "SUCCESS",
        "size": len(PDF),
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "completed_at": "2026-08-01T00:00:00+09:00",
    }
    (tmp_path / ".ippi-download-history.jsonl").write_text(
        json.dumps(record) + "\n",
        encoding="utf-8",
    )
    http = RecordingHTTPClient()

    result = Downloader(http, MagicMock()).download_files(
        [file_info],
        str(tmp_path),
        LegacyOnlyNaming(),
        layout_version=3,
    )

    assert len(http.calls) == 1
    assert result.reused == 0
    assert existing.read_bytes() == PDF
    assert Path(result.tasks[0].local_path) != existing
