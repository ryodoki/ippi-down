# -*- coding: utf-8 -*-

"""工事・業務のWebForms差分を集約した不変プロファイル。"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Tuple

from ..models.search_target import SearchTarget


KOJI_SEARCH_URL = (
    "https://www.i-ppi.jp/"
    "IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"
)
GYOMU_SEARCH_URL = (
    "https://www.i-ppi.jp/"
    "IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=7"
)

KOJI_CONTRACT_TYPES = (
    "一般競争入札",
    "公募型指名競争入札",
    "指名競争入札",
    "随意契約",
    "その他方式",
)
GYOMU_CONTRACT_TYPES = (
    "一般競争入札",
    "指名競争入札",
    "公募型競争入札",
    "随意契約",
    "公募型プロポーザル",
    "標準プロポーザル",
    "コンペ方式",
    "その他",
)


@dataclass(frozen=True)
class SearchProfile:
    target: SearchTarget
    display_label: str
    search_url: str
    tab: str
    agency_type: str
    project_label: str
    place_label: str
    project_name_field: str
    place_radio_field: str
    place_district_field: str
    place_prefecture_field: str
    place_city_field: str
    place_text_field: str
    place_prefecture_info_field: str
    place_prefecture_index_field: str
    contract_fields: Tuple[Tuple[str, str], ...]
    category_fields: Tuple[Tuple[str, str], ...]
    result_project_headers: Tuple[str, ...]
    unknown_project_label: str
    project_list_path: str
    result_table_id: str = "dgrSearchList"
    detail_table_ids: Tuple[str, ...] = ("dgrKokoku", "dgrKeika")

    @property
    def default_contract_types(self) -> Tuple[str, ...]:
        return tuple(label for label, _ in self.contract_fields)

    @property
    def multi_agency_url(self) -> str:
        return (
            "https://www.i-ppi.jp/IPPI/SearchServices/Web/Multi/"
            f"SearchHachu.aspx?type={self.agency_type}&clear_flg=false"
        )


_PROFILES: Mapping[SearchTarget, SearchProfile] = MappingProxyType(
    {
        SearchTarget.KOJI_KEIKA: SearchProfile(
            target=SearchTarget.KOJI_KEIKA,
            display_label="工事（入札の経過）",
            search_url=KOJI_SEARCH_URL,
            tab="4",
            agency_type="koji",
            project_label="工事名",
            place_label="工事場所",
            project_name_field="tbxKojiNm",
            place_radio_field="KojiRadioGroup",
            place_district_field="drpKojiDistrict",
            place_prefecture_field="drpKojiPrefecture2",
            place_city_field="drpKojiCity",
            place_text_field="tbxKojiPlace",
            place_prefecture_info_field="txtKojiPrefectureInf_h",
            place_prefecture_index_field="txtKojiPrefecture2SelIndex_h",
            contract_fields=tuple(
                (label, f"chkKojiNyusatsu{index}")
                for index, label in enumerate(KOJI_CONTRACT_TYPES, start=1)
            ),
            category_fields=(
                ("koji_shubetsu", "drpKojiKbn"),
                ("koji_gyoushu", "drpKojiGyosyu"),
            ),
            result_project_headers=("工事名",),
            unknown_project_label="工事名不明",
            project_list_path="/IPPI/SearchServices/Web/Koji/Keika/List.aspx",
        ),
        SearchTarget.GYOMU_KEIKA: SearchProfile(
            target=SearchTarget.GYOMU_KEIKA,
            display_label="業務（入札の経過）",
            search_url=GYOMU_SEARCH_URL,
            tab="7",
            agency_type="gyomu",
            project_label="業務名",
            place_label="業務対象地域",
            project_name_field="tbxGyomuNm",
            place_radio_field="GyomuRadioGroup",
            place_district_field="drpGyomuDistrict",
            place_prefecture_field="drpGyomuPrefecture2",
            place_city_field="drpGyomuCity",
            place_text_field="tbxGyomuPlace",
            place_prefecture_info_field="txtGyomuPrefectureInf_h",
            place_prefecture_index_field="txtGyomuPrefecture2SelIndex_h",
            contract_fields=tuple(
                (label, f"chkGyomuNyusatsu{index}")
                for index, label in enumerate(GYOMU_CONTRACT_TYPES, start=1)
            ),
            category_fields=(("gyomu_kubun", "drpGyomuKbn"),),
            result_project_headers=("業務名",),
            unknown_project_label="業務名不明",
            project_list_path="/IPPI/SearchServices/Web/Gyomu/Keika/List.aspx",
        ),
    }
)


def get_search_profile(target: object = SearchTarget.KOJI_KEIKA) -> SearchProfile:
    return _PROFILES[SearchTarget.coerce(target)]


def profile_for_url(url: str) -> SearchProfile:
    for profile in _PROFILES.values():
        if str(url or "") == profile.search_url:
            return profile
    raise ValueError(f"未対応のi-ppi検索URLです: {url}")


def search_profiles() -> Tuple[SearchProfile, ...]:
    return tuple(_PROFILES.values())


__all__ = [
    "GYOMU_CONTRACT_TYPES",
    "GYOMU_SEARCH_URL",
    "KOJI_CONTRACT_TYPES",
    "KOJI_SEARCH_URL",
    "SearchProfile",
    "get_search_profile",
    "profile_for_url",
    "search_profiles",
]
