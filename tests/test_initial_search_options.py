# -*- coding: utf-8 -*-

from unittest.mock import Mock

from bs4 import BeautifulSoup

from src.core.scraper import Scraper


def test_initial_search_options_are_parsed_from_one_page_fetch():
    soup = BeautifulSoup(
        """
        <form>
          <select id="drpKojiDistrict" name="drpKojiDistrict">
            <option value="-1">▽地方</option>
            <option value="2">東北</option>
          </select>
          <select id="drpKojiKbn" name="drpKojiKbn">
            <option value="">▽以下から選択</option>
            <option value="01">一般土木工事</option>
          </select>
          <select id="drpKojiGyosyu" name="drpKojiGyosyu">
            <option value="-1">▽以下から選択</option>
            <option value="010">土木一式工事</option>
          </select>
        </form>
        """,
        "lxml",
    )
    scraper = Scraper(Mock(), Mock())
    scraper.fetch_page = Mock(return_value=soup)
    scraper._agency_hierarchy_service.prime_search_page = Mock()

    search_url = "https://example.invalid/search"
    options = scraper.get_initial_search_options(search_url)
    cached = scraper.get_search_dropdown_options(search_url, "drpKojiKbn")
    structured = scraper.get_initial_search_option_pairs(search_url)

    assert options == {
        "place_chihou": ["東北"],
        "koji_shubetsu": ["一般土木工事"],
        "koji_gyoushu": ["土木一式工事"],
    }
    assert cached == ["一般土木工事"]
    assert structured["koji_shubetsu"] == [("01", "一般土木工事")]
    assert structured["koji_gyoushu"] == [("010", "土木一式工事")]
    scraper.fetch_page.assert_called_once_with(
        "https://example.invalid/search?tab=4"
    )
    scraper._agency_hierarchy_service.prime_search_page.assert_called_once_with(
        soup,
        "https://example.invalid/search?tab=4",
    )


def test_initial_search_options_return_stable_empty_shape_on_fetch_failure():
    scraper = Scraper(Mock(), Mock())
    scraper.fetch_page = Mock(return_value=None)

    assert scraper.get_initial_search_options("https://example.invalid/search") == {
        "place_chihou": [],
        "koji_shubetsu": [],
        "koji_gyoushu": [],
    }
