# -*- coding: utf-8 -*-

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from bs4 import BeautifulSoup

from src.app.service import ApplicationService
from src.core.extractor.agency_hierarchy_service import AgencyHierarchyService
from src.core.parser.agency_catalog_parser import AgencyCatalogParser
from src.core.parser.agency_hierarchy_parser import AgencyHierarchyParser
from src.core.parser.detail_page_parser import DetailPageParser
from src.core.parser.search_result_parser import SearchResultParser
from src.core.scraper import Scraper
from src.core.search_profiles import (
    GYOMU_SEARCH_URL,
    KOJI_SEARCH_URL,
    get_search_profile,
)
from src.models.agency import AgencyLevel, AgencyPath
from src.models.config_model import SearchConditions
from src.models.file_info import FileInfo
from src.models.search_target import SearchTarget
from src.utils.outbound_policy import NetworkPurpose


FIXTURES = Path(__file__).parent / "fixtures"


def _soup(value: str) -> BeautifulSoup:
    return BeautifulSoup(value, "lxml")


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _catalog(*labels: str) -> bytes:
    nodes = "".join(
        (
            f'<a id="tv_Hachut{index}" '
            f'href="javascript:__doPostBack(\'tv_Hachu\',\'s{code}\')">'
            f"{label}</a>"
        )
        for index, (code, label) in enumerate(
            (
                ("A", labels[0]),
                (r"A\B", labels[1]),
                (r"A\B\C", labels[2]),
            )
        )
    )
    return (
        "<html><head><title>発注機関指定（複数選択）</title></head>"
        f'<body><div id="tv_Hachu">{nodes}</div></body></html>'
    ).encode("utf-8")


def _response(content: bytes, url: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        url=url,
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        encoding="utf-8",
        apparent_encoding="utf-8",
        close=lambda: None,
    )


def test_gyomu_profile_builds_confirmed_webforms_fields() -> None:
    scraper = Scraper(Mock())
    conditions = SearchConditions.for_target(SearchTarget.GYOMU_KEIKA)
    conditions.project_name = "橋梁点検業務"
    conditions.place_search_type = "text"
    conditions.place_text = "東京都"
    conditions.gyomu_kubun = "土木関係建設コンサルタント業務"
    html = _fixture("gyomu_keika_search_form.html")

    form = scraper._build_search_form_data(conditions, _soup(html))

    assert form["tbxGyomuNm"] == "橋梁点検業務"
    assert form["GyomuRadioGroup"] == "1"
    assert form["tbxGyomuPlace"] == "東京都"
    assert form["drpGyomuKbn"] == "01"
    assert set(form) >= {
        f"chkGyomuNyusatsu{index}" for index in range(1, 9)
    }
    assert not any(key.startswith("chkKoji") for key in form)


def test_gyomu_result_parser_uses_business_name_and_category() -> None:
    html = _fixture("gyomu_keika_results_page1.html")

    entries = SearchResultParser().extract_project_entries(
        _soup(html),
        GYOMU_SEARCH_URL,
        search_target=SearchTarget.GYOMU_KEIKA,
    )

    assert len(entries) == 1
    assert entries[0].project_name == "橋梁点検業務"
    assert entries[0].koji_name == "橋梁点検業務"
    assert entries[0].search_target == "gyomu_keika"
    assert entries[0].metadata["gyomu_kubun"] == "測量"


def test_gyomu_duplicate_names_keep_all_eight_result_rows() -> None:
    """案件名が同じでもpostback単位で8件を別案件として集計する。"""

    soup = _soup(_fixture("gyomu_keika_results_duplicate_names.html"))
    scraper = Scraper(Mock())
    conditions = SearchConditions.for_target(SearchTarget.GYOMU_KEIKA)
    conditions.project_name = "資材単価"
    captured: list[tuple[str, int]] = []

    def detail_side_effect(
        _base_url,
        _postback_href,
        _file_types,
        _current_soup,
        *,
        koji_name,
        project_entry,
        event_target,
        event_argument,
        **_kwargs,
    ):
        captured.append((event_argument, project_entry.row_no))
        if project_entry.row_no <= 4:
            rows = []
            files = []
            for document_no in range(1, 6):
                url = (
                    "https://example.test/document?AnkenKanriNo="
                    f"PROJECT-{project_entry.row_no}&BunshoKanriId={document_no}"
                )
                rows.append(
                    SimpleNamespace(
                        status="PUBLIC",
                        document_name=f"公開文書{document_no}",
                        href=url,
                    )
                )
                files.append(
                    FileInfo(url, f"document-{document_no}.pdf", ".pdf")
                )
        else:
            rows = [
                SimpleNamespace(
                    status="EXPIRED",
                    document_name="公開終了文書",
                    href="",
                )
            ]
            files = []
        scraper._record_project_document_summary(
            project_entry=project_entry,
            koji_name=koji_name,
            document_rows=rows,
            candidates=files,
        )
        return files

    scraper._extract_files_from_detail_page_via_postback = Mock(
        side_effect=detail_side_effect
    )

    files = scraper.extract_file_links_from_search_results(
        soup,
        GYOMU_SEARCH_URL,
        [".pdf"],
        conditions,
    )

    assert captured == [(f"${index}", index + 1) for index in range(8)]
    assert len(files) == 20
    assert scraper.last_search_summary.projects_scanned == 8
    assert scraper.last_search_summary.projects_matched == 8
    assert scraper.last_search_total_project_count == 8
    assert scraper.last_search_summary.public_documents == 20
    assert scraper.last_search_summary.expired_only_projects == 4
    assert len({item.project_id for item in scraper.last_search_summary.projects}) == 8


def test_business_target_alone_uses_search_submission_flow() -> None:
    service = ApplicationService.__new__(ApplicationService)
    conditions = SearchConditions.for_target(SearchTarget.GYOMU_KEIKA)

    assert service._has_search_conditions(conditions)
    assert len(get_search_profile(conditions.target).default_contract_types) == 8


def test_agency_refresh_replaces_snapshot_and_preserves_old_on_failure() -> None:
    profile = get_search_profile(SearchTarget.GYOMU_KEIKA)
    client = Mock()
    client.get.side_effect = [
        _response(_catalog("大", "中", "旧事務所"), profile.multi_agency_url),
        _response(_catalog("大", "中", "新事務所"), profile.multi_agency_url),
        RuntimeError("temporary failure"),
    ]
    service = AgencyHierarchyService(client)

    first = service.bootstrap_catalog(profile.search_url)
    second = service.refresh_catalog(profile.search_url)
    failed = service.refresh_catalog(profile.search_url)
    retained = service.bootstrap_catalog(profile.search_url)

    assert first.generation == 1
    assert second.generation == 2
    assert second.added_count == 1
    assert second.removed_count == 1
    assert failed.error is not None
    assert failed.error.code.value == "AGENCY_CATALOG_REFRESH_FAILED"
    assert retained is second


def test_agency_catalog_generations_replace_added_and_removed_options() -> None:
    parser = AgencyCatalogParser()
    names = (
        "agency_koji_generation_1.html",
        "agency_koji_generation_2_added.html",
        "agency_koji_generation_3_removed.html",
    )
    snapshots = [
        parser.parse(_soup(_fixture(name)), source_url=KOJI_SEARCH_URL)
        for name in names
    ]

    root = AgencyPath()
    first_top = snapshots[0].get_children(root)[0]
    first_middle = snapshots[0].get_children(root.append(first_top))[0]
    first_small = snapshots[0].get_children(
        root.append(first_top).append(first_middle)
    )
    assert [option.label for option in first_small] == ["既存事務所"]

    second_top = snapshots[1].get_children(root)[0]
    second_middle = snapshots[1].get_children(root.append(second_top))[0]
    assert [
        option.label
        for option in snapshots[1].get_children(
            root.append(second_top).append(second_middle)
        )
    ] == ["復興事務所", "既存事務所"]

    third_top = snapshots[2].get_children(root)[0]
    third_middle = snapshots[2].get_children(root.append(third_top))[0]
    assert [
        option.label
        for option in snapshots[2].get_children(
            root.append(third_top).append(third_middle)
        )
    ] == ["復興事務所"]


def test_empty_agency_branch_is_a_successful_empty_option_list() -> None:
    parser = AgencyHierarchyParser()
    soup = _soup(_fixture("agency_empty_branch.html"))

    assert parser.has_options_container(soup, AgencyLevel.SAIBUNRUI)
    assert parser.extract_options(
        soup, AgencyLevel.SAIBUNRUI, AgencyPath.from_labels_and_codes(
            ("大", "中", "小"), ("1", "2", "3")
        )
    ) == []


def test_koji_and_gyomu_catalogs_keep_separate_snapshots() -> None:
    koji_profile = get_search_profile(SearchTarget.KOJI_KEIKA)
    gyomu_profile = get_search_profile(SearchTarget.GYOMU_KEIKA)
    client = Mock()
    client.get.side_effect = [
        _response(
            _fixture("agency_koji_generation_1.html").encode(),
            koji_profile.multi_agency_url,
        ),
        _response(
            _fixture("agency_gyomu_generation_1.html").encode(),
            gyomu_profile.multi_agency_url,
        ),
    ]
    service = AgencyHierarchyService(client)

    koji = service.bootstrap_catalog(koji_profile.search_url)
    gyomu = service.bootstrap_catalog(gyomu_profile.search_url)

    assert koji.source_url == koji_profile.multi_agency_url
    assert gyomu.source_url == gyomu_profile.multi_agency_url
    assert koji.get_children()[0].code == "K01"
    assert gyomu.get_children()[0].code == "G01"
    assert client.get.call_count == 2


def test_gyomu_pagination_resolves_confirmed_form_action() -> None:
    list_url = (
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/"
        "Gyomu/Keika/List.aspx?tab=7"
    )
    client = Mock()
    client.post.return_value = _response(
        _fixture("gyomu_keika_results_page2.html").encode(), list_url
    )
    scraper = Scraper(client)
    scraper._last_search_result_url = list_url

    next_page = scraper._get_next_page(
        _soup(_fixture("gyomu_keika_results_page1.html")),
        GYOMU_SEARCH_URL,
    )

    assert next_page is not None
    assert "河川調査業務" in next_page.get_text(" ", strip=True)
    assert client.post.call_args.args[0] == list_url
    assert client.post.call_args.kwargs["purpose"] is NetworkPurpose.PAGINATION


def test_gyomu_detail_uses_common_document_tables() -> None:
    result = DetailPageParser(Mock()).extract_detail_result(
        _soup(_fixture("gyomu_keika_detail.html")),
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Gyomu/Keika/List.aspx?tab=7",
        [".pdf"],
        koji_name="橋梁点検業務",
    )

    assert [row.document_name for row in result.document_rows] == [
        "入札公告",
        "入札調書",
    ]
    assert result.project_metadata == {
        "hachu_kikan": "業務発注局",
        "office_name": "業務担当部",
        "agency_id": "700100",
    }
    assert len(result.candidates) == 2
