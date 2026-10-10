# -*- coding: utf-8 -*-

from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from src.core.extractor.agency_hierarchy_service import (
    AgencyHierarchyService,
)
from src.core.extractor.metadata_extractor import MetadataExtractor
from src.core.parser.detail_page_parser import DetailPageParser
from src.core.parser.agency_hierarchy_parser import AgencyHierarchyParser
from src.core.parser.models import FileCandidate, ProjectEntry
from src.core.scraper import Scraper
from src.models.agency import (
    AgencyLevel,
    AgencyOption,
    AgencyOptionSource,
    AgencyOptionsError,
    AgencyOptionsErrorCode,
    AgencyOptionsResult,
    AgencyPath,
    AgencyPathResolution,
    AgencyResolutionReasonCode,
    AgencyResolutionStatus,
)


FIXTURES = Path(__file__).parent / "fixtures"


class _Response:
    status_code = 200
    encoding = "utf-8"
    apparent_encoding = "utf-8"

    def __init__(self, fixture_name: str):
        self.content = (FIXTURES / fixture_name).read_bytes()
        self.text = self.content.decode("utf-8")
        self.url = "https://www.i-ppi.jp/Search.aspx?tab=4"


class _BranchHTTPClient:
    def __init__(self):
        self.get_calls = []
        self.post_calls = []
        self._post_responses = [
            _Response("agency_tab2_after_top.html"),
            _Response("agency_tab2_after_large.html"),
            _Response("agency_tab2_after_middle.html"),
        ]

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return _Response("agency_tab2_root.html")

    def post(self, url, data=None, **kwargs):
        self.post_calls.append((url, data, kwargs))
        return self._post_responses.pop(0)


def _selected_middle_path() -> AgencyPath:
    return AgencyPath.from_labels_and_codes(
        ("国の機関", "国土交通省", "東北地方整備局"),
        ("01", "0101", "0210"),
    )


def _selected_chubu_path() -> AgencyPath:
    return AgencyPath.from_labels_and_codes(
        ("国の機関", "国土交通省", "中部地方整備局"),
        ("0", "21", "05"),
    )


def test_agency_path_mapping_has_stable_segment_contract_and_round_trips():
    path = _selected_middle_path()
    resolution = AgencyPathResolution(
        path=path,
        status=AgencyResolutionStatus.SELECTED,
        method="search_selection",
        reason_code="AGENCY_SELECTED",
    )

    payload = resolution.to_mapping()

    assert payload["version"] == 2
    assert [segment["level"] for segment in payload["segments"]] == [
        "daibunrui",
        "chubunrui",
        "shoubunrui",
    ]
    assert payload["segments"][1] == {
        "level": "chubunrui",
        "code": "0101",
        "label": "国土交通省",
    }
    assert payload["resolution"] == {
        "status": "selected",
        "method": "search_selection",
        "reason": "",
        "reason_code": "AGENCY_SELECTED",
    }
    restored = AgencyPathResolution.from_mapping(payload)
    assert restored.path == path
    assert restored.reason_code == "AGENCY_SELECTED"


def test_agency_option_keeps_parent_path_and_rejects_duplicate_level():
    path = _selected_middle_path()
    child = AgencyOption(
        level=AgencyLevel.SAIBUNRUI,
        code="02102000",
        label="能代河川国道事務所",
        parent_path=path,
    )

    completed = path.append(child)

    assert child.parent_path == path
    assert completed.append(child) == completed


def test_list_service_fetches_only_selected_branch_and_caches_children():
    http_client = _BranchHTTPClient()
    service = AgencyHierarchyService(http_client, Mock())
    path = _selected_middle_path()

    children = service.get_children(
        path,
        search_url="https://www.i-ppi.jp/Search.aspx?tab=4&foo=bar",
    )
    cached = service.get_children(
        path,
        search_url="https://www.i-ppi.jp/Search.aspx?tab=4&foo=bar",
    )

    assert [child.label for child in children] == [
        "能代河川国道事務所",
        "山形河川国道事務所",
    ]
    assert all(child.parent_path == path for child in children)
    assert cached == children
    assert len(http_client.get_calls) == 1
    assert len(http_client.post_calls) == 3
    requested_urls = [http_client.get_calls[0][0]] + [
        call[0] for call in http_client.post_calls
    ]
    assert all(
        parse_qs(urlparse(url).query)["tab"] == ["4"]
        for url in requested_urls
    )
    assert all("foo=bar" in url for url in requested_urls)
    assert [
        call[1]["__EVENTTARGET"] for call in http_client.post_calls
    ] == [
        "drpTopKikanInf",
        "drpLargeKikanInf2",
        "drpMiddleKikanInf",
    ]


def test_detail_metadata_uniquely_completes_small_classification():
    service = AgencyHierarchyService(_BranchHTTPClient(), Mock())

    resolution = service.resolve_project_agency(
        {
            "hachu_kikan": "国土交通省東北地方整備局",
            "office_name": "能代河川国道事務所",
            "agency_id": "02102000",
        },
        _selected_middle_path(),
        search_url="https://www.i-ppi.jp/Search.aspx?tab=4",
    )

    payload = resolution.to_mapping()
    assert resolution.status is AgencyResolutionStatus.DETAIL_MATCHED
    assert resolution.path.is_complete
    assert resolution.path.labels[-1] == "能代河川国道事務所"
    assert resolution.method == "detail_label"
    assert resolution.reason_code == "OFFICE_LABEL_MATCH"
    assert payload["resolution"]["status"] == "detail_matched"
    assert len(payload["segments"]) == 4


def test_conflicting_office_name_does_not_accept_selected_small_path():
    complete = _selected_middle_path().append(
        AgencyOption(
            level=AgencyLevel.SAIBUNRUI,
            code="02102000",
            label="能代河川国道事務所",
            parent_path=_selected_middle_path(),
        )
    )
    service = AgencyHierarchyService(Mock(), Mock())

    resolution = service.resolve_project_agency(
        {
            "office_name": "山形河川国道事務所",
            "agency_id": "02103000",
        },
        complete,
    )

    assert resolution.status is AgencyResolutionStatus.UNRESOLVED
    assert "担当部・事務所" in resolution.reason
    assert resolution.reason_code == "AGENCY_OFFICE_CONFLICT"
    service.http_client.get.assert_not_called()


def test_current_site_fine_code_is_not_compared_with_hachusha_id():
    parent = _selected_chubu_path()
    soup = BeautifulSoup(
        (FIXTURES / "agency_current_fine_options.html").read_text(
            encoding="utf-8"
        ),
        "lxml",
    )
    options = AgencyHierarchyParser(Mock()).extract_options(
        soup,
        AgencyLevel.SAIBUNRUI,
        parent,
    )
    service = AgencyHierarchyService(Mock(), Mock())
    service.get_children_result = Mock(return_value=AgencyOptionsResult(
        tuple(options),
        parent,
        AgencyOptionSource.POSTBACK,
    ))

    resolution = service.resolve_project_agency(
        {
            "hachu_kikan": "国土交通省中部地方整備局",
            "office_name": "飯田国道事務所",
            "agency_id": "02105000",
        },
        parent,
    )

    assert resolution.status is AgencyResolutionStatus.DETAIL_MATCHED
    assert resolution.path.leaf is not None
    assert resolution.path.leaf.code == "128"
    assert resolution.agency_id == "02105000"
    assert resolution.method == "detail_label"
    assert (
        resolution.reason_code
        == AgencyResolutionReasonCode.OFFICE_LABEL_MATCH.value
    )

    already_complete = service.resolve_project_agency(
        {
            "office_name": "飯田国道事務所",
            "agency_id": "02105000",
        },
        resolution.path,
    )
    assert already_complete.status is AgencyResolutionStatus.DETAIL_MATCHED
    assert already_complete.reason_code == "OFFICE_LABEL_MATCH"


def test_legacy_exact_hachusha_id_is_used_only_without_office_label():
    service = AgencyHierarchyService(_BranchHTTPClient(), Mock())

    resolution = service.resolve_project_agency(
        {
            "hachu_kikan": "",
            "office_name": "",
            "agency_id": "02102000",
        },
        _selected_middle_path(),
        search_url="https://www.i-ppi.jp/Search.aspx?tab=4",
    )

    assert resolution.status is AgencyResolutionStatus.DETAIL_MATCHED
    assert resolution.method == "legacy_exact_id"
    assert resolution.reason_code == "LEGACY_ID_MATCH"


def test_complete_selection_without_office_requires_legacy_exact_id():
    middle = _selected_middle_path()
    complete = middle.append(AgencyOption(
        AgencyLevel.SAIBUNRUI,
        "02102000",
        "能代河川国道事務所",
        middle,
    ))
    service = AgencyHierarchyService(Mock(), Mock())

    accepted = service.resolve_project_agency(
        {"agency_id": "02102000"},
        complete,
    )
    rejected = service.resolve_project_agency(
        {"agency_id": "02105000"},
        complete,
    )

    assert accepted.status is AgencyResolutionStatus.DETAIL_MATCHED
    assert accepted.method == "legacy_exact_id"
    assert accepted.reason_code == "LEGACY_ID_MATCH"
    assert rejected.status is AgencyResolutionStatus.UNRESOLVED
    assert rejected.reason_code == "AGENCY_DETAIL_MISSING"
    service.http_client.get.assert_not_called()


def test_fine_zero_and_multiple_matches_have_distinct_reason_codes():
    parent = _selected_chubu_path()
    service = AgencyHierarchyService(Mock(), Mock())
    no_match_options = (
        AgencyOption(
            AgencyLevel.SAIBUNRUI,
            "120",
            "高山国道事務所",
            parent,
        ),
    )
    service.get_children_result = Mock(return_value=AgencyOptionsResult(
        no_match_options,
        parent,
        AgencyOptionSource.POSTBACK,
    ))

    missing = service.resolve_project_agency(
        {"office_name": "飯田国道事務所"},
        parent,
    )

    assert missing.status is AgencyResolutionStatus.UNRESOLVED
    assert missing.reason_code == "AGENCY_FINE_NOT_FOUND"

    ambiguous_options = (
        AgencyOption(
            AgencyLevel.SAIBUNRUI,
            "128",
            "飯田国道事務所",
            parent,
        ),
        AgencyOption(
            AgencyLevel.SAIBUNRUI,
            "129",
            "飯田国道事務所 管理課",
            parent,
        ),
    )
    service.get_children_result.return_value = AgencyOptionsResult(
        ambiguous_options,
        parent,
        AgencyOptionSource.POSTBACK,
    )

    ambiguous = service.resolve_project_agency(
        {"office_name": "飯田国道事務所"},
        parent,
    )

    assert ambiguous.status is AgencyResolutionStatus.UNRESOLVED
    assert ambiguous.reason_code == "AGENCY_FINE_AMBIGUOUS"


def test_catalog_failure_is_not_reported_as_normal_zero_match():
    parent = _selected_chubu_path()
    service = AgencyHierarchyService(Mock(), Mock())
    service.get_children_result = Mock(return_value=AgencyOptionsResult(
        (),
        parent,
        AgencyOptionSource.POSTBACK,
        error=AgencyOptionsError(
            AgencyOptionsErrorCode.FETCH_FAILED,
            "timeout",
        ),
    ))

    resolution = service.resolve_project_agency(
        {"office_name": "飯田国道事務所"},
        parent,
    )

    assert resolution.status is AgencyResolutionStatus.UNRESOLVED
    assert resolution.reason_code == "AGENCY_CATALOG_FETCH_FAILED"
    assert "AGENCY_OPTIONS_FETCH_FAILED" in resolution.reason


def test_v1_agency_path_without_reason_code_remains_readable():
    legacy = {
        "version": 1,
        "segments": [
            {
                "level": "daibunrui",
                "code": "0",
                "label": "国の機関",
            }
        ],
        "resolution": {
            "status": "unresolved",
            "method": "detail",
            "reason": "旧形式",
        },
    }

    resolution = AgencyPathResolution.from_mapping(legacy)

    assert resolution.path.labels == ("国の機関",)
    assert resolution.reason_code == ""


def test_saved_detail_fixture_extracts_office_and_hachusha_id():
    soup = BeautifulSoup(
        (FIXTURES / "test_detail_page.html").read_text(encoding="utf-8"),
        "lxml",
    )

    metadata = DetailPageParser(Mock()).extract_project_metadata(soup)

    assert metadata == {
        "hachu_kikan": "国土交通省東北地方整備局",
        "office_name": "能代河川国道事務所",
        "agency_id": "02102000",
    }


def test_project_entry_agency_resolution_propagates_to_file_metadata():
    path = _selected_middle_path()
    resolution = AgencyPathResolution(
        path=path,
        status=AgencyResolutionStatus.UNRESOLVED,
        method="detail",
        reason="細分類候補なし",
        office_name="能代河川国道事務所",
        agency_id="02102000",
        reason_code="AGENCY_FINE_NOT_FOUND",
    )
    project = ProjectEntry(
        detail_url="https://example.invalid/detail",
        koji_name="テスト工事",
        metadata={"hachu_kikan": "国土交通省東北地方整備局"},
        agency_path=path,
        agency_resolution=resolution,
        office_name=resolution.office_name,
        agency_id=resolution.agency_id,
    )
    candidate = FileCandidate(
        url="https://example.invalid/doc.pdf",
        filename="doc.pdf",
        file_type=".pdf",
        document_name="入札公告",
    )

    file_info = MetadataExtractor(Mock()).to_file_info(candidate, project)

    assert file_info.metadata["office_name"] == "能代河川国道事務所"
    assert file_info.metadata["agency_id"] == "02102000"
    assert file_info.metadata["agency_resolution_status"] == "unresolved"
    assert file_info.metadata["agency_resolution_reason_code"] == (
        "AGENCY_FINE_NOT_FOUND"
    )
    assert file_info.metadata["agency_path"]["segments"][2]["label"] == (
        "東北地方整備局"
    )


def test_detail_postback_propagates_selected_path_office_and_agency_id():
    middle = _selected_middle_path()
    complete = middle.append(
        AgencyOption(
            level=AgencyLevel.SAIBUNRUI,
            code="02102000",
            label="能代河川国道事務所",
            parent_path=middle,
        )
    )
    selected = AgencyPathResolution(
        path=complete,
        status=AgencyResolutionStatus.SELECTED,
        method="search_selection",
    )
    project = ProjectEntry(
        detail_url="https://example.invalid/detail",
        koji_name="摩当山トンネル換気設備製作据付工事",
        metadata={"koji_name": "摩当山トンネル換気設備製作据付工事"},
        agency_path=complete,
        agency_resolution=selected,
    )
    http_client = Mock()
    http_client.post.return_value = _Response("test_detail_page.html")
    scraper = Scraper(http_client, Mock())
    current_soup = BeautifulSoup(
        '<form action="/detail">'
        '<input type="hidden" name="__VIEWSTATE" value="x">'
        "</form>",
        "lxml",
    )

    files = scraper._extract_files_from_detail_page_via_postback(
        "https://www.i-ppi.jp/Search.aspx?tab=4",
        "javascript:__doPostBack('dgrSearchList','$0')",
        [".pdf"],
        current_soup,
        koji_name=project.koji_name,
        project_entry=project,
    )

    assert files
    assert all(
        file_info.metadata["office_name"] == "能代河川国道事務所"
        for file_info in files
    )
    assert all(
        file_info.metadata["agency_id"] == "02102000"
        for file_info in files
    )
    assert all(
        len(file_info.metadata["agency_path"]["segments"]) == 4
        for file_info in files
    )
    assert all(
        file_info.metadata["agency_path"]["resolution"]["status"]
        == "detail_matched"
        for file_info in files
    )
    # 完全な選択パスは詳細値との整合確認だけで確定でき、候補通信は不要。
    http_client.get.assert_not_called()
