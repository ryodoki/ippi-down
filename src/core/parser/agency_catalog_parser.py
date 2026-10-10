# -*- coding: utf-8 -*-

"""発注機関複数選択TreeViewのメモリ内カタログ解析。"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import DefaultDict, List, Optional, Tuple

from bs4 import BeautifulSoup

from ...models.agency import (
    AgencyCatalogSnapshot,
    AgencyLevel,
    AgencyOption,
    AgencyOptionsErrorCode,
    AgencyPath,
    AgencyPathKey,
    agency_path_key,
)


class AgencyCatalogParseError(ValueError):
    """TreeViewの契約違反を固定コード付きで表す。"""

    def __init__(self, code: AgencyOptionsErrorCode, message: str):
        super().__init__(message)
        self.code = AgencyOptionsErrorCode(code)


class AgencyCatalogParser:
    """ASP.NET TreeView ``tv_Hachu`` の先頭3階層を解析する。"""

    _NODE_ID = re.compile(r"^tv_Hachut\d+$", re.IGNORECASE)
    _POSTBACK = re.compile(
        r"__doPostBack\(\s*['\"]tv_Hachu['\"]\s*,\s*"
        r"['\"]s(?P<path>[0-9A-Za-z_-]+(?:\\+[0-9A-Za-z_-]+)*)['\"]",
        re.IGNORECASE,
    )
    _LEVELS = (
        AgencyLevel.DAIBUNRUI,
        AgencyLevel.CHUBUNRUI,
        AgencyLevel.SHOUBUNRUI,
    )

    def parse(
        self,
        soup: BeautifulSoup,
        *,
        source_url: str,
        fetched_at: Optional[datetime] = None,
        request_count: int = 0,
        elapsed_seconds: float = 0.0,
    ) -> AgencyCatalogSnapshot:
        """検証済みTreeViewを親パス別の候補表へ変換する。"""

        title = " ".join(
            str(soup.title.get_text(" ", strip=True) if soup.title else "").split()
        )
        if "発注機関指定" not in title or "複数選択" not in title:
            raise AgencyCatalogParseError(
                AgencyOptionsErrorCode.PAGE_INVALID,
                "発注機関複数選択ページのタイトルを確認できません",
            )

        tree = soup.find(id="tv_Hachu")
        if tree is None:
            raise AgencyCatalogParseError(
                AgencyOptionsErrorCode.TREE_MISSING,
                "発注機関TreeView(tv_Hachu)が見つかりません",
            )

        records: List[Tuple[int, Tuple[str, ...], str]] = []
        seen_paths: set[Tuple[str, ...]] = set()
        for order, anchor in enumerate(tree.find_all("a", href=True)):
            anchor_id = str(anchor.get("id", "") or "")
            if not self._NODE_ID.match(anchor_id):
                continue
            href = html.unescape(str(anchor.get("href", "") or ""))
            match = self._POSTBACK.search(href)
            if match is None:
                continue
            parts = tuple(
                part for part in re.split(r"\\+", match.group("path")) if part
            )
            if not 1 <= len(parts) <= len(self._LEVELS):
                raise AgencyCatalogParseError(
                    AgencyOptionsErrorCode.TREE_INVALID,
                    "発注機関TreeViewに想定外の階層があります",
                )
            label = anchor.get_text(" ", strip=True)
            if not label or not all(parts):
                raise AgencyCatalogParseError(
                    AgencyOptionsErrorCode.TREE_INVALID,
                    "発注機関TreeViewに空のコードまたは表示名があります",
                )
            if parts in seen_paths:
                raise AgencyCatalogParseError(
                    AgencyOptionsErrorCode.DUPLICATE_PATH,
                    "発注機関TreeViewに重複したパスがあります: "
                    + "/".join(parts),
                )
            seen_paths.add(parts)
            records.append((order, parts, label))

        if not records or max(len(parts) for _, parts, _ in records) < 3:
            raise AgencyCatalogParseError(
                AgencyOptionsErrorCode.TREE_INVALID,
                "発注機関TreeViewの3階層を確認できません",
            )

        children: DefaultDict[AgencyPathKey, List[AgencyOption]] = defaultdict(list)
        paths: dict[Tuple[str, ...], AgencyPath] = {}
        for _, parts, label in sorted(records, key=lambda item: (len(item[1]), item[0])):
            parent_codes = parts[:-1]
            if parent_codes:
                parent_path = paths.get(parent_codes)
                if parent_path is None:
                    raise AgencyCatalogParseError(
                        AgencyOptionsErrorCode.TREE_INVALID,
                        "発注機関TreeViewに親のないノードがあります: "
                        + "/".join(parts),
                    )
            else:
                parent_path = AgencyPath()
            option = AgencyOption(
                level=self._LEVELS[len(parts) - 1],
                code=parts[-1],
                label=label,
                parent_path=parent_path,
            )
            path = parent_path.append(option)
            paths[parts] = path
            children[agency_path_key(parent_path)].append(option)
            # 3階層目の直下は細分類であり、このTreeViewには含まれない。
            if len(parts) < len(self._LEVELS):
                children.setdefault(agency_path_key(path), [])

        return AgencyCatalogSnapshot(
            source_url=source_url,
            children={key: tuple(value) for key, value in children.items()},
            fetched_at=fetched_at or datetime.now(timezone.utc),
            request_count=request_count,
            elapsed_seconds=elapsed_seconds,
        )


__all__ = ["AgencyCatalogParseError", "AgencyCatalogParser"]
