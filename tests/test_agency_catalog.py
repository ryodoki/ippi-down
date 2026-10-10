from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup

from src.core.extractor.agency_hierarchy_service import (
    AgencyHierarchyService,
)
from src.core.parser.agency_catalog_parser import (
    AgencyCatalogParseError,
    AgencyCatalogParser,
)
from src.models.agency import (
    AgencyOptionSource,
    AgencyOptionsErrorCode,
)


FIXTURES = Path(__file__).parent / "fixtures"
MULTI_URL = (
    "https://www.i-ppi.jp/IPPI/SearchServices/Web/Multi/"
    "SearchHachu.aspx?type=koji&clear_flg=false"
)
LIST_URL = (
    "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/"
    "Search.aspx?tab=4"
)


class _Response:
    status_code = 200
    encoding = "utf-8"
    apparent_encoding = "utf-8"

    def __init__(
        self,
        fixture_name: str,
        *,
        url: str,
        content_type: str = "text/html; charset=utf-8",
    ):
        self.content = (FIXTURES / fixture_name).read_bytes()
        self.text = self.content.decode("utf-8")
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.close_count = 0

    def close(self):
        self.close_count += 1


class _CatalogHTTPClient:
    def __init__(self, get_responses, post_responses=()):
        self.get_responses = list(get_responses)
        self.post_responses = list(post_responses)
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)

    def post(self, url, data=None, **kwargs):
        self.post_calls.append((url, data, kwargs))
        return self.post_responses.pop(0)


def _fixture_soup(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_bytes(), "lxml")


def test_multi_tree_parser_builds_three_level_catalog_and_resolves_codes():
    snapshot = AgencyCatalogParser().parse(
        _fixture_soup("agency_multi_tree.html"),
        source_url=MULTI_URL,
        request_count=1,
    )

    assert snapshot.is_valid
    assert snapshot.option_count == 10
    assert [option.label for option in snapshot.get_children()] == [
        "国の機関",
        "地方公共団体（都道府県）",
    ]
    path = snapshot.resolve_path(
        ("国の機関", "国土交通省", "東北地方整備局")
    )
    assert path is not None
    assert path.codes == ("0", "21", "02")
    assert snapshot.get_children(path) == ()
    assert not snapshot.contains_parent(path)

    empty_parent = snapshot.resolve_path(
        ("国の機関", "国土交通省北海道開発局")
    )
    assert empty_parent is not None
    assert snapshot.contains_parent(empty_parent)
    assert snapshot.get_children(empty_parent) == ()


def test_multi_tree_parser_rejects_bad_title_missing_tree_and_duplicate_path():
    parser = AgencyCatalogParser()
    bad_title = _fixture_soup("agency_multi_tree.html")
    bad_title.title.string = "エラー"
    try:
        parser.parse(bad_title, source_url=MULTI_URL)
    except AgencyCatalogParseError as exc:
        assert exc.code is AgencyOptionsErrorCode.PAGE_INVALID
    else:
        raise AssertionError("不正タイトルを受理しました")

    missing_tree = BeautifulSoup(
        "<html><title>発注機関指定 複数選択</title></html>", "lxml"
    )
    try:
        parser.parse(missing_tree, source_url=MULTI_URL)
    except AgencyCatalogParseError as exc:
        assert exc.code is AgencyOptionsErrorCode.TREE_MISSING
    else:
        raise AssertionError("tv_Hachu欠落を受理しました")

    duplicate = _fixture_soup("agency_multi_tree.html")
    node = duplicate.find(id="tv_Hachut2")
    assert node is not None
    node.insert_after(BeautifulSoup(str(node), "lxml").find("a"))
    try:
        parser.parse(duplicate, source_url=MULTI_URL)
    except AgencyCatalogParseError as exc:
        assert exc.code is AgencyOptionsErrorCode.DUPLICATE_PATH
    else:
        raise AssertionError("重複パスを受理しました")


def test_catalog_keeps_three_levels_in_memory_and_fine_branch_uses_two_posts():
    client = _CatalogHTTPClient(
        (
            _Response("agency_multi_tree.html", url=MULTI_URL),
            _Response("agency_list_root_embedded.html", url=LIST_URL),
        ),
        (
            _Response("agency_list_after_middle.html", url=LIST_URL),
            _Response("agency_list_after_small.html", url=LIST_URL),
            _Response("agency_list_after_kanto.html", url=LIST_URL),
        ),
    )
    service = AgencyHierarchyService(client, Mock())

    snapshot = service.bootstrap_catalog(LIST_URL)
    assert snapshot.is_valid
    assert len(client.get_calls) == 1

    root_result = service.get_children_result(search_url=LIST_URL)
    top = snapshot.resolve_path(("国の機関",))
    middle = snapshot.resolve_path(("国の機関", "国土交通省"))
    tohoku = snapshot.resolve_path(
        ("国の機関", "国土交通省", "東北地方整備局")
    )
    assert top is not None and middle is not None and tohoku is not None
    assert root_result.source is AgencyOptionSource.MULTI_TREE
    assert service.get_children_result(top, search_url=LIST_URL).request_count == 0
    assert (
        service.get_children_result(middle, search_url=LIST_URL).request_count
        == 0
    )
    assert len(client.get_calls) == 1

    fine = service.get_children_result(tohoku, search_url=LIST_URL)

    assert fine.ok
    assert fine.request_count == 3
    assert [option.label for option in fine.options] == [
        "能代河川国道事務所",
        "山形河川国道事務所",
    ]
    assert len(client.get_calls) == 2
    assert [call[1]["__EVENTTARGET"] for call in client.post_calls] == [
        "drpLargeKikanInf2",
        "drpMiddleKikanInf",
    ]
    assert client.post_calls[0][1]["drpTopKikanInf"] == "0"
    assert client.post_calls[0][1]["drpLargeKikanInf2"] == "21"
    assert client.post_calls[0][1]["txtLgKikanInf2SelIndex_h"] == "1"

    cached = service.get_children_result(tohoku, search_url=LIST_URL)
    assert cached.source is AgencyOptionSource.MEMORY
    assert cached.request_count == 0
    assert cached.options == fine.options
    assert len(client.post_calls) == 2

    kanto = snapshot.resolve_path(
        ("国の機関", "国土交通省", "関東地方整備局")
    )
    assert kanto is not None
    another_branch = service.get_children_result(kanto, search_url=LIST_URL)
    assert another_branch.request_count == 1
    assert [option.label for option in another_branch.options] == ["本局"]
    assert len(client.post_calls) == 3


def test_primed_initial_search_page_makes_fine_prefetch_two_posts_only():
    client = _CatalogHTTPClient(
        (_Response("agency_multi_tree.html", url=MULTI_URL),),
        (
            _Response("agency_list_after_middle.html", url=LIST_URL),
            _Response("agency_list_after_small.html", url=LIST_URL),
        ),
    )
    service = AgencyHierarchyService(client, Mock())
    snapshot = service.bootstrap_catalog(LIST_URL)
    assert service.prime_search_page(
        _fixture_soup("agency_list_root_embedded.html"), LIST_URL
    )
    tohoku = snapshot.resolve_path(
        ("国の機関", "国土交通省", "東北地方整備局")
    )
    assert tohoku is not None

    result = service.get_children_result(tohoku, search_url=LIST_URL)

    assert result.ok
    assert result.request_count == 2
    assert len(client.get_calls) == 1  # 複数選択ツリーだけ
    assert [call[1]["__EVENTTARGET"] for call in client.post_calls] == [
        "drpLargeKikanInf2",
        "drpMiddleKikanInf",
    ]


def test_catalog_failure_is_not_cached_and_empty_branch_is_successful():
    invalid = _Response(
        "agency_multi_tree.html",
        url=MULTI_URL,
        content_type="application/pdf",
    )
    client = _CatalogHTTPClient((invalid, invalid))
    service = AgencyHierarchyService(client, Mock())

    first = service.bootstrap_catalog(LIST_URL)
    second = service.bootstrap_catalog(LIST_URL)

    assert not first.is_valid
    assert first.error is not None
    assert first.error.code is AgencyOptionsErrorCode.CONTENT_TYPE_INVALID
    assert second.error == first.error
    assert len(client.get_calls) == 2

    valid_client = _CatalogHTTPClient(
        (_Response("agency_multi_tree.html", url=MULTI_URL),)
    )
    valid_service = AgencyHierarchyService(valid_client, Mock())
    snapshot = valid_service.bootstrap_catalog(LIST_URL)
    empty_parent = snapshot.resolve_path(
        ("国の機関", "国土交通省北海道開発局")
    )
    assert empty_parent is not None
    result = valid_service.get_children_result(empty_parent, search_url=LIST_URL)
    assert result.ok
    assert result.error is None
    assert result.options == ()


def test_list_overlap_mismatch_falls_back_but_one_sided_entry_is_allowed():
    client = _CatalogHTTPClient(
        (_Response("agency_multi_tree.html", url=MULTI_URL),)
    )
    service = AgencyHierarchyService(client, Mock())
    snapshot = service.bootstrap_catalog(LIST_URL)
    top = snapshot.resolve_path(("国の機関",))
    assert top is not None

    mismatched = _fixture_soup("agency_list_root_embedded.html")
    hidden = mismatched.find("input", attrs={"name": "txtLargeKikanInf_h"})
    assert hidden is not None
    hidden["value"] = "0,国土交通省（変更）,21"
    assert service.prime_search_page(mismatched, LIST_URL)
    result = service.get_children_result(top, search_url=LIST_URL)
    assert [option.label for option in result.options] == [
        "国土交通省（変更）"
    ]

    service.clear_cache()
    client.get_responses.append(_Response("agency_multi_tree.html", url=MULTI_URL))
    snapshot = service.bootstrap_catalog(LIST_URL)
    top = snapshot.resolve_path(("国の機関",))
    assert top is not None
    one_sided = _fixture_soup("agency_list_root_embedded.html")
    hidden = one_sided.find("input", attrs={"name": "txtLargeKikanInf_h"})
    assert hidden is not None
    hidden["value"] = "0,国土交通省,21"
    assert service.prime_search_page(one_sided, LIST_URL)
    allowed = service.get_children_result(top, search_url=LIST_URL)
    assert [option.label for option in allowed.options] == [
        "国土交通省",
        "農林水産省",
        "国土交通省北海道開発局",
    ]


def test_catalog_rejects_non_official_source_without_network():
    client = _CatalogHTTPClient(())
    service = AgencyHierarchyService(client, Mock())

    snapshot = service.bootstrap_catalog("https://example.invalid/Search.aspx")

    assert snapshot.error is not None
    assert snapshot.error.code is AgencyOptionsErrorCode.INVALID_URL
    assert client.get_calls == []


def test_catalog_releases_responses_and_keeps_only_compact_lru_page_states():
    responses = (
        _Response("agency_multi_tree.html", url=MULTI_URL),
        _Response("agency_list_root_embedded.html", url=LIST_URL),
    )
    posts = (
        _Response("agency_list_after_middle.html", url=LIST_URL),
        _Response("agency_list_after_small.html", url=LIST_URL),
    )
    client = _CatalogHTTPClient(responses, posts)
    service = AgencyHierarchyService(client, Mock())
    snapshot = service.bootstrap_catalog(LIST_URL)
    tohoku = snapshot.resolve_path(
        ("国の機関", "国土交通省", "東北地方整備局")
    )
    assert tohoku is not None

    result = service.get_children_result(tohoku, search_url=LIST_URL)

    assert result.ok
    assert all(response.close_count == 1 for response in (*responses, *posts))
    assert len(service._page_states) <= service.MAX_PAGE_STATES  # noqa: SLF001
    assert all(  # noqa: SLF001 - DOMを長期保持しない契約
        not isinstance(state, BeautifulSoup)
        for state in service._page_states.values()
    )


def test_agency_page_state_cache_key_ignores_fragment_and_unrelated_query():
    first = AgencyHierarchyService._cache_master_url(  # noqa: SLF001
        f"{LIST_URL}&cache=one#first"
    )
    second = AgencyHierarchyService._cache_master_url(  # noqa: SLF001
        f"{LIST_URL}&cache=two#second"
    )

    assert first == second
