# -*- coding: utf-8 -*-

"""発注機関（リスト検索）の階層候補パーサー。"""

from __future__ import annotations

import html
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from ...models.agency import AgencyLevel, AgencyOption, AgencyPath
from ...utils.logger import Logger


class AgencyHierarchyParser:
    """HTML/JavaScriptに含まれる1階層分のoptionを読み取る。"""

    DROPDOWN_NAMES = {
        AgencyLevel.DAIBUNRUI: "drpTopKikanInf",
        AgencyLevel.CHUBUNRUI: "drpLargeKikanInf2",
        AgencyLevel.SHOUBUNRUI: "drpMiddleKikanInf",
        AgencyLevel.SAIBUNRUI: "drpSmallKikanInf",
    }

    def __init__(self, logger: Optional[Logger] = None):
        self.logger = logger or Logger()

    @classmethod
    def dropdown_name(cls, level: AgencyLevel) -> str:
        return cls.DROPDOWN_NAMES[AgencyLevel(level)]

    def extract_options(
        self,
        soup: BeautifulSoup,
        level: AgencyLevel,
        parent_path: AgencyPath,
    ) -> List[AgencyOption]:
        """指定階層の候補を、コードと親パス付きで返す。"""

        requested_level = AgencyLevel(level)
        dropdown_name = self.dropdown_name(requested_level)
        select = self._find_dropdown(soup, dropdown_name)

        pairs: List[tuple[str, str]] = []
        if select is not None:
            pairs.extend(
                (
                    str(option.get("value", "") or "").strip(),
                    option.get_text(" ", strip=True),
                )
                for option in select.find_all("option")
            )
        if not pairs:
            pairs.extend(
                self._extract_script_pairs(str(soup), dropdown_name)
            )

        results: List[AgencyOption] = []
        seen: set[tuple[str, str]] = set()
        for code, label in pairs:
            if self._is_placeholder(code, label):
                continue
            key = (code, label)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                AgencyOption(
                    level=requested_level,
                    code=code,
                    label=label,
                    parent_path=parent_path,
                )
            )
        return results

    def has_options_container(
        self,
        soup: BeautifulSoup,
        level: AgencyLevel,
    ) -> bool:
        """候補0件を要素欠落と区別する。"""

        dropdown_name = self.dropdown_name(level)
        if self._find_dropdown(soup, dropdown_name) is not None:
            return True
        return any(
            call_id.endswith(dropdown_name)
            for call_id, _ in self._iter_script_calls(str(soup))
        )

    def extract_embedded_middle_options(
        self,
        soup: BeautifulSoup,
        parent_path: AgencyPath,
    ) -> Optional[List[AgencyOption]]:
        """初期ページのhidden値から中分類候補を読む。

        hidden自体がない場合は``None``、存在して候補がない場合は空listを
        返すため、取得失敗と正常な0件を区別できる。
        """

        if len(parent_path.segments) != 1:
            raise ValueError("中分類の埋め込み候補には大分類パスが必要です")
        hidden = soup.find("input", id="txtLargeKikanInf_h") or soup.find(
            "input", attrs={"name": "txtLargeKikanInf_h"}
        )
        if hidden is None:
            return None
        source = html.unescape(str(hidden.get("value", "") or "")).strip()
        if not source:
            return []

        top = parent_path.segments[0]
        options: List[AgencyOption] = []
        seen: set[tuple[str, str]] = set()
        for raw_entry in source.split(":"):
            parts = [part.strip() for part in raw_entry.split(",", 2)]
            if len(parts) != 3:
                raise ValueError("txtLargeKikanInf_hの形式が不正です")
            top_code, label, code = parts
            if top_code != top.code or self._is_placeholder(code, label):
                continue
            key = (code, label)
            if key in seen:
                continue
            seen.add(key)
            options.append(
                AgencyOption(
                    level=AgencyLevel.CHUBUNRUI,
                    code=code,
                    label=label,
                    parent_path=parent_path,
                )
            )
        return options

    @staticmethod
    def _find_dropdown(soup: BeautifulSoup, dropdown_name: str):
        select = soup.find("select", id=dropdown_name)
        if select is None:
            select = soup.find("select", attrs={"name": dropdown_name})
        if select is None:
            select = soup.find(
                "select",
                id=lambda value: bool(value)
                and str(value).endswith(dropdown_name),
            )
        if select is None:
            select = soup.find(
                "select",
                attrs={
                    "name": lambda value: bool(value)
                    and str(value).endswith(dropdown_name)
                },
            )
        return select

    @staticmethod
    def _is_placeholder(code: str, label: str) -> bool:
        normalized_code = str(code or "").strip()
        normalized_label = str(label or "").strip()
        return (
            normalized_code in {"", "-1"}
            or not normalized_label
            or normalized_label.startswith("▽")
            or normalized_label in {"選択してください", "未選択"}
        )

    @staticmethod
    def _extract_script_pairs(
        source: str,
        dropdown_name: str,
    ) -> List[tuple[str, str]]:
        """WebFormsがselectでなくsetListItemSubを返す場合を扱う。"""

        pairs: List[tuple[str, str]] = []
        for call_id, values_source in AgencyHierarchyParser._iter_script_calls(
            source
        ):
            if not call_id.endswith(dropdown_name):
                continue
            for raw_value in re.findall(
                r"['\"]((?:\\.|[^'\"])*)['\"]",
                values_source,
            ):
                decoded = html.unescape(raw_value)
                if ":" not in decoded:
                    continue
                code, label = decoded.split(":", 1)
                pairs.append((code.strip(), label.strip()))
        return pairs

    @staticmethod
    def _iter_script_calls(source: str):
        calls = re.finditer(
            r"setListItemSub\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*"
            r"(?:\[([^\]]*)\]|new\s+Array\s*\((.*?)\))\s*\)",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for call in calls:
            yield call.group(1), call.group(2) or call.group(3) or ""


__all__ = ["AgencyHierarchyParser"]
