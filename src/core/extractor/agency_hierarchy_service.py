# -*- coding: utf-8 -*-

"""発注機関マスターの遅延取得と案件単位のパス解決。"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from ...models.agency import (
    AgencyCatalogSnapshot,
    AgencyLevel,
    AgencyOption,
    AgencyOptionSource,
    AgencyOptionsError,
    AgencyOptionsErrorCode,
    AgencyOptionsResult,
    AgencyPath,
    AgencyPathKey,
    AgencyPathResolution,
    AgencyResolutionReasonCode,
    AgencyResolutionStatus,
    agency_path_key,
)
from ...utils.http_client import HTTPClient
from ...utils.logger import Logger
from ...utils.outbound_policy import NetworkPurpose
from ..parser.agency_catalog_parser import (
    AgencyCatalogParseError,
    AgencyCatalogParser,
)
from ..parser.agency_hierarchy_parser import AgencyHierarchyParser
from ..parser.aspnet_form_parser import AspNetFormParser


@dataclass(frozen=True)
class _WebFormsState:
    """POSTバックに必要な値だけを保持する軽量ページ状態。"""

    hidden_inputs: Mapping[str, str]
    option_indexes: Mapping[str, Mapping[str, int]]


class AgencyHierarchyService:
    """対象別の発注機関カタログと細分類をメモリ内で共有する。"""

    DEFAULT_MASTER_URL = (
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/"
        "Search.aspx?tab=4"
    )
    DEFAULT_MULTI_URL = (
        "https://www.i-ppi.jp/IPPI/SearchServices/Web/Multi/"
        "SearchHachu.aspx?type=koji&clear_flg=false"
    )
    MAX_PAGE_STATES = 32

    def __init__(
        self,
        http_client: HTTPClient,
        logger: Optional[Logger] = None,
        *,
        master_url: str = DEFAULT_MASTER_URL,
    ):
        self.http_client = http_client
        self.logger = logger or Logger()
        self.master_url = self._as_master_url(master_url)
        self._parser = AgencyHierarchyParser(self.logger)
        self._catalog_parser = AgencyCatalogParser()
        self._form_parser = AspNetFormParser(self.logger)
        self._children_cache: Dict[
            Tuple[str, AgencyPathKey],
            Tuple[AgencyOption, ...],
        ] = {}
        self._children_sources: Dict[
            Tuple[str, AgencyPathKey], AgencyOptionSource
        ] = {}
        self._list_children_cache: Dict[
            Tuple[str, AgencyPathKey], Tuple[AgencyOption, ...]
        ] = {}
        self._list_children_sources: Dict[
            Tuple[str, AgencyPathKey], AgencyOptionSource
        ] = {}
        self._page_states: OrderedDict[
            Tuple[str, AgencyPathKey], _WebFormsState
        ] = OrderedDict()
        self._catalog_snapshots: Dict[str, AgencyCatalogSnapshot] = {}
        self._catalog_generations: Dict[str, int] = {}
        self._catalog_invalid_paths: set[Tuple[str, AgencyPathKey]] = set()
        self._cache_lock = threading.RLock()

    @staticmethod
    def _as_master_url(search_url: str) -> str:
        """実際の入札経過検索と同じ対象tabへ統一する。"""

        parsed = urlparse(search_url or AgencyHierarchyService.DEFAULT_MASTER_URL)
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() != "tab"
        ]
        source_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        tab = "7" if source_query.get("tab") == "7" else "4"
        query.append(("tab", tab))
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query),
                "",
            )
        )

    @staticmethod
    def _cache_master_url(master_url: str) -> str:
        """表示条件に依存しないWebFormsキャッシュキーへ正規化する。"""

        parsed = urlparse(master_url)
        return urlunparse(
            (
                parsed.scheme.casefold(),
                parsed.netloc.casefold(),
                parsed.path,
                "",
                "tab=7" if dict(parse_qsl(parsed.query)).get("tab") == "7" else "tab=4",
                "",
            )
        )

    @staticmethod
    def _cache_path_key(
        path: AgencyPath,
    ) -> AgencyPathKey:
        return agency_path_key(path)

    @staticmethod
    def _as_multi_url(search_url: Optional[str] = None) -> str:
        parsed = urlparse(search_url or AgencyHierarchyService.DEFAULT_MULTI_URL)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        agency_type = (
            "gyomu"
            if query.get("type") == "gyomu" or query.get("tab") == "7"
            else "koji"
        )
        return urlunparse(
            (
                parsed.scheme or "https",
                parsed.netloc or "www.i-ppi.jp",
                "/IPPI/SearchServices/Web/Multi/SearchHachu.aspx",
                "",
                urlencode((('type', agency_type), ('clear_flg', 'false'))),
                "",
            )
        )

    @staticmethod
    def _is_official_https_url(url: str) -> bool:
        parsed = urlparse(str(url or ""))
        hostname = (parsed.hostname or "").casefold()
        return parsed.scheme.casefold() == "https" and (
            hostname == "i-ppi.jp" or hostname.endswith(".i-ppi.jp")
        )

    @classmethod
    def _is_official_multi_url(cls, url: str) -> bool:
        parsed = urlparse(str(url or ""))
        return cls._is_official_https_url(url) and parsed.path.casefold() == (
            "/IPPI/SearchServices/Web/Multi/SearchHachu.aspx".casefold()
        )

    def clear_cache(self) -> None:
        """候補・TreeView・WebForms状態をすべてメモリから破棄する。"""

        with self._cache_lock:
            self._children_cache.clear()
            self._children_sources.clear()
            self._list_children_cache.clear()
            self._list_children_sources.clear()
            self._page_states.clear()
            self._catalog_snapshots.clear()
            self._catalog_generations.clear()
            self._catalog_invalid_paths.clear()

    def bootstrap_catalog(
        self,
        search_url: Optional[str] = None,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        force_refresh: bool = False,
    ) -> AgencyCatalogSnapshot:
        """対象別の公式複数選択画面を取得し、先頭3階層を展開する。"""

        started = time.perf_counter()
        multi_url = self._as_multi_url(search_url)
        master_url = self._as_master_url(search_url or self.master_url)
        with self._cache_lock:
            cached = self._catalog_snapshots.get(multi_url)
            if cached is not None and not force_refresh:
                return cached
            if not self._is_official_multi_url(multi_url):
                return self._failed_snapshot(
                    multi_url,
                    AgencyOptionsErrorCode.INVALID_URL,
                    "発注機関候補の取得先が公式HTTPS URLではありません",
                    0,
                    started,
                )

        request_count = 0
        response = None
        try:
            request_count = 1
            response = self.http_client.get(
                multi_url,
                cancel_check=cancel_check,
                purpose=NetworkPurpose.STARTUP_CATALOG,
            )
            response_url = str(getattr(response, "url", "") or multi_url)
            if not self._is_official_multi_url(response_url):
                return self._failed_snapshot(
                    multi_url,
                    (
                        AgencyOptionsErrorCode.CATALOG_REFRESH_FAILED
                        if force_refresh
                        else AgencyOptionsErrorCode.RESPONSE_URL_INVALID
                    ),
                    "発注機関候補ページが公式URL以外へ遷移しました",
                    request_count,
                    started,
                )
            headers = getattr(response, "headers", {}) or {}
            content_type = str(headers.get("Content-Type", "") or "")
            if "text/html" not in content_type.casefold():
                return self._failed_snapshot(
                    multi_url,
                    (
                        AgencyOptionsErrorCode.CATALOG_REFRESH_FAILED
                        if force_refresh
                        else AgencyOptionsErrorCode.CONTENT_TYPE_INVALID
                    ),
                    "発注機関候補ページがHTMLではありません",
                    request_count,
                    started,
                )
            soup = self._to_soup(response)
            snapshot = self._catalog_parser.parse(
                soup,
                source_url=response_url,
                fetched_at=datetime.now(timezone.utc),
                request_count=request_count,
                elapsed_seconds=time.perf_counter() - started,
            )
        except AgencyCatalogParseError as exc:
            return self._failed_snapshot(
                multi_url,
                (
                    AgencyOptionsErrorCode.CATALOG_REFRESH_FAILED
                    if force_refresh
                    else exc.code
                ),
                str(exc),
                request_count,
                started,
            )
        except Exception as exc:
            code = (
                AgencyOptionsErrorCode.CANCELLED
                if self._cancelled(cancel_check)
                else AgencyOptionsErrorCode.CATALOG_REFRESH_FAILED
                if force_refresh
                else AgencyOptionsErrorCode.FETCH_FAILED
            )
            return self._failed_snapshot(
                multi_url,
                code,
                f"発注機関候補ページを取得できません: {exc}",
                request_count,
                started,
            )
        finally:
            self._close_response(response)

        with self._cache_lock:
            old_snapshot = self._catalog_snapshots.get(multi_url)
            old_options = self._snapshot_option_keys(old_snapshot)
            new_options = self._snapshot_option_keys(snapshot)
            generation = self._catalog_generations.get(multi_url, 0) + 1
            snapshot = replace(
                snapshot,
                generation=generation,
                added_count=len(new_options - old_options),
                removed_count=len(old_options - new_options),
            )
            # 新カタログを完全に解析できた場合だけ、その対象の旧枝・hidden
            # 状態を破棄して一括公開する。工事と業務の状態は別キーである。
            self._discard_target_cache_locked(master_url, multi_url)
            self._catalog_snapshots[multi_url] = snapshot
            self._catalog_generations[multi_url] = generation
            for (list_url, path_key), options in tuple(
                self._list_children_cache.items()
            ):
                if urlparse(list_url).hostname != urlparse(multi_url).hostname:
                    continue
                parent = AgencyPath.from_labels_and_codes(
                    (segment[2] for segment in path_key),
                    (segment[1] for segment in path_key),
                )
                self._publish_list_branch(
                    list_url,
                    multi_url,
                    parent,
                    options,
                    self._list_children_sources[(list_url, path_key)],
                )
            self.logger.info(
                "発注機関カタログ更新結果: "
                f"対象={self._catalog_target(multi_url)} 階層=3 "
                f"候補={snapshot.option_count}件 "
                f"追加={snapshot.added_count}件 削除={snapshot.removed_count}件 "
                "結果=OK"
            )
            return snapshot

    def refresh_catalog(
        self,
        search_url: Optional[str] = None,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgencyCatalogSnapshot:
        """対象カタログを再取得し、成功時だけ新世代へ全置換する。"""

        snapshot = self.bootstrap_catalog(
            search_url,
            cancel_check=cancel_check,
            force_refresh=True,
        )
        if snapshot.error is not None:
            self.logger.warning(
                "発注機関カタログ更新結果: "
                f"対象={self._catalog_target(snapshot.source_url)} 階層=3 "
                f"候補={snapshot.option_count}件 追加=0件 削除=0件 "
                f"結果={snapshot.error.code.value}"
            )
        return snapshot

    @staticmethod
    def _catalog_target(url: str) -> str:
        query = dict(parse_qsl(urlparse(str(url or "")).query))
        return (
            "gyomu_keika"
            if query.get("type") == "gyomu" or query.get("tab") == "7"
            else "koji_keika"
        )

    @staticmethod
    def _snapshot_option_keys(
        snapshot: Optional[AgencyCatalogSnapshot],
    ) -> set[Tuple[AgencyPathKey, str, str]]:
        if snapshot is None or not snapshot.is_valid:
            return set()
        return {
            (parent, option.code, option.label)
            for parent, options in snapshot.children.items()
            for option in options
        }

    def _discard_target_cache_locked(
        self,
        master_url: str,
        multi_url: str,
    ) -> None:
        cache_url = self._cache_master_url(master_url)
        for mapping in (
            self._children_cache,
            self._children_sources,
            self._list_children_cache,
            self._list_children_sources,
            self._page_states,
        ):
            for key in tuple(mapping):
                if key[0] == cache_url:
                    mapping.pop(key, None)
        self._catalog_invalid_paths = {
            key
            for key in self._catalog_invalid_paths
            if key[0] != multi_url
        }

    def prime_search_page(
        self,
        soup: BeautifulSoup,
        search_url: Optional[str] = None,
    ) -> bool:
        """他の検索候補取得で得た初期ページをWebForms状態として共有する。"""

        master_url = self._as_master_url(search_url or self.master_url)
        if not self._is_official_https_url(master_url):
            return False
        with self._cache_lock:
            return self._remember_root_state(master_url, soup)

    def get_children_result(
        self,
        parent_path: Optional[AgencyPath] = None,
        *,
        search_url: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgencyOptionsResult:
        """候補と取得元・通信回数・構造化エラーを返す。"""

        result = self._get_children_result(
            parent_path,
            search_url=search_url,
            cancel_check=cancel_check,
        )
        source = result.source.value if result.source is not None else "NONE"
        outcome = result.error.code.value if result.error is not None else "OK"
        message = (
            "発注機関候補取得結果: "
            f"親階層={len(result.parent_path.segments)} "
            f"候補={len(result.options)}件 取得元={source} "
            f"HTTP要求={result.request_count}回 "
            f"経過={result.elapsed_seconds:.3f}秒 結果={outcome}"
        )
        if result.error is not None:
            self.logger.warning(f"{message} 理由={result.error.message}")
        else:
            self.logger.info(message)
        return result

    def _get_children_result(
        self,
        parent_path: Optional[AgencyPath] = None,
        *,
        search_url: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgencyOptionsResult:
        """候補取得本体。公開入口で診断情報を1行へ集約する。"""

        started = time.perf_counter()
        requested_parent = parent_path or AgencyPath()
        if requested_parent.next_level is None:
            return AgencyOptionsResult(
                (),
                requested_parent,
                AgencyOptionSource.MEMORY,
                elapsed_seconds=time.perf_counter() - started,
            )
        master_url = self._as_master_url(search_url or self.master_url)
        if not self._is_official_https_url(master_url):
            return self._error_result(
                requested_parent,
                AgencyOptionsErrorCode.INVALID_URL,
                "発注機関候補の取得先が公式HTTPS URLではありません",
                0,
                started,
            )

        with self._cache_lock:
            multi_url = self._as_multi_url(search_url or self.master_url)
            snapshot = self._catalog_snapshots.get(multi_url)
            parent = self._canonical_parent(snapshot, requested_parent)
            cache_key = (
                self._cache_master_url(master_url),
                agency_path_key(parent),
            )
            cached = self._children_cache.get(cache_key)
            if cached is not None:
                return AgencyOptionsResult(
                    cached,
                    parent,
                    AgencyOptionSource.MEMORY,
                    elapsed_seconds=time.perf_counter() - started,
                )

            request_count = 0
            catalog_error: Optional[AgencyOptionsError] = None
            # TreeViewは大・中・小分類だけを持つ。細分類取得時は、明示的な
            # bootstrapが済んでいる場合だけカタログをパス解決に利用する。
            if requested_parent.next_level is not AgencyLevel.SAIBUNRUI:
                had_snapshot = snapshot is not None
                snapshot = snapshot or self.bootstrap_catalog(
                    search_url,
                    cancel_check=cancel_check,
                )
                if not had_snapshot:
                    request_count += snapshot.request_count
                if snapshot.error is not None:
                    catalog_error = snapshot.error
                elif snapshot.is_valid:
                    parent = self._canonical_parent(snapshot, requested_parent)
                    invalid_key = (multi_url, agency_path_key(parent))
                    if (
                        snapshot.contains_parent(parent)
                        and invalid_key not in self._catalog_invalid_paths
                    ):
                        options = snapshot.get_children(parent)
                        self._store_children(
                            master_url,
                            parent,
                            options,
                            AgencyOptionSource.MULTI_TREE,
                        )
                        return AgencyOptionsResult(
                            options,
                            parent,
                            AgencyOptionSource.MULTI_TREE,
                            request_count=request_count,
                            elapsed_seconds=time.perf_counter() - started,
                        )

            list_result = self._get_list_children_result(
                parent,
                master_url,
                multi_url,
                cancel_check,
                request_count,
                started,
            )
            if list_result.error is not None and catalog_error is not None:
                return AgencyOptionsResult(
                    (),
                    list_result.parent_path,
                    list_result.source,
                    list_result.request_count,
                    list_result.elapsed_seconds,
                    AgencyOptionsError(
                        list_result.error.code,
                        f"{list_result.error.message} "
                        f"(高速候補取得: {catalog_error.message})",
                    ),
                )
            if catalog_error is not None:
                self.logger.warning(
                    "発注機関高速カタログからリスト検索へ切り替えました: "
                    f"[{catalog_error.code.value}] {catalog_error.message}"
                )
            return list_result

    def get_children(
        self,
        parent_path: Optional[AgencyPath] = None,
        *,
        search_url: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[AgencyOption]:
        """従来互換。診断が必要な呼出元はget_children_resultを使う。"""

        result = self.get_children_result(
            parent_path,
            search_url=search_url,
            cancel_check=cancel_check,
        )
        return list(result.options)

    def _get_list_children_result(
        self,
        parent: AgencyPath,
        master_url: str,
        multi_url: str,
        cancel_check: Optional[Callable[[], bool]],
        request_count: int,
        started: float,
    ) -> AgencyOptionsResult:
        cache_url = self._cache_master_url(master_url)
        soup, added_requests, error = self._get_or_fetch_root(
            master_url,
            multi_url,
            cancel_check,
        )
        request_count += added_requests
        if error is not None or soup is None:
            return AgencyOptionsResult(
                (),
                parent,
                None,
                request_count,
                time.perf_counter() - started,
                error,
            )

        root = AgencyPath()
        root_options = self._list_children_cache[
            (cache_url, agency_path_key(root))
        ]
        if not parent.segments:
            return AgencyOptionsResult(
                root_options,
                root,
                (
                    AgencyOptionSource.LIST_EMBEDDED
                    if added_requests
                    else AgencyOptionSource.MEMORY
                ),
                request_count,
                time.perf_counter() - started,
            )

        selected_top = self._find_requested_option(
            list(root_options), parent.segments[0]
        )
        if selected_top is None:
            return self._error_result(
                parent,
                AgencyOptionsErrorCode.PARENT_NOT_FOUND,
                "リスト検索に指定された大分類がありません",
                request_count,
                started,
            )
        top_path = root.append(selected_top)
        middle_key = (cache_url, agency_path_key(top_path))
        middle_options = self._list_children_cache.get(middle_key)
        top_soup = self._get_page_state(middle_key)

        if middle_options is None:
            top_soup, post_error = self._post_selected_state(
                soup,
                master_url,
                top_path,
                selected_top,
                cancel_check,
            )
            request_count += 1
            if post_error is not None or top_soup is None:
                return AgencyOptionsResult(
                    (),
                    top_path,
                    AgencyOptionSource.POSTBACK,
                    request_count,
                    time.perf_counter() - started,
                    post_error,
                )
            middle_options, parse_error = self._remember_postback_state(
                master_url,
                multi_url,
                top_path,
                top_soup,
            )
            if parse_error is not None:
                return AgencyOptionsResult(
                    (),
                    top_path,
                    AgencyOptionSource.POSTBACK,
                    request_count,
                    time.perf_counter() - started,
                    parse_error,
                )
            top_soup = self._get_page_state(middle_key)

        if len(parent.segments) == 1:
            return AgencyOptionsResult(
                middle_options or (),
                top_path,
                (
                    self._list_children_sources.get(middle_key)
                    or AgencyOptionSource.MEMORY
                ),
                request_count,
                time.perf_counter() - started,
            )

        selected_middle = self._find_requested_option(
            list(middle_options or ()), parent.segments[1]
        )
        if selected_middle is None:
            return self._error_result(
                parent,
                AgencyOptionsErrorCode.PARENT_NOT_FOUND,
                "リスト検索に指定された中分類がありません",
                request_count,
                started,
            )
        middle_path = top_path.append(selected_middle)
        small_key = (cache_url, agency_path_key(middle_path))
        small_options = self._list_children_cache.get(small_key)
        middle_soup = self._get_page_state(small_key)

        if small_options is None:
            # 初期ページのhidden候補から中分類を特定できれば、大分類の
            # postbackを省き、中分類のpostbackから開始できる。
            source_soup = (
                soup
                if self._list_children_sources.get(middle_key)
                is AgencyOptionSource.LIST_EMBEDDED
                else top_soup
            )
            if source_soup is None:
                source_soup = soup
            middle_soup, post_error = self._post_selected_state(
                source_soup,
                master_url,
                middle_path,
                selected_middle,
                cancel_check,
                sibling_options=middle_options,
            )
            request_count += 1
            if post_error is not None or middle_soup is None:
                return AgencyOptionsResult(
                    (),
                    middle_path,
                    AgencyOptionSource.POSTBACK,
                    request_count,
                    time.perf_counter() - started,
                    post_error,
                )
            small_options, parse_error = self._remember_postback_state(
                master_url,
                multi_url,
                middle_path,
                middle_soup,
            )
            if parse_error is not None:
                return AgencyOptionsResult(
                    (),
                    middle_path,
                    AgencyOptionSource.POSTBACK,
                    request_count,
                    time.perf_counter() - started,
                    parse_error,
                )
            middle_soup = self._get_page_state(small_key)

        if len(parent.segments) == 2:
            return AgencyOptionsResult(
                small_options or (),
                middle_path,
                (
                    self._list_children_sources.get(small_key)
                    or AgencyOptionSource.MEMORY
                ),
                request_count,
                time.perf_counter() - started,
            )

        selected_small = self._find_requested_option(
            list(small_options or ()), parent.segments[2]
        )
        if selected_small is None:
            return self._error_result(
                parent,
                AgencyOptionsErrorCode.PARENT_NOT_FOUND,
                "リスト検索に指定された小分類がありません",
                request_count,
                started,
            )
        small_path = middle_path.append(selected_small)
        fine_key = (cache_url, agency_path_key(small_path))
        fine_options = self._list_children_cache.get(fine_key)
        if fine_options is None:
            if middle_soup is None:
                middle_soup = self._get_page_state(small_key)
            if middle_soup is None:
                return self._error_result(
                    small_path,
                    AgencyOptionsErrorCode.PAGE_INVALID,
                    "小分類を送信するWebForms状態がありません",
                    request_count,
                    started,
                )
            small_soup, post_error = self._post_selected_state(
                middle_soup,
                master_url,
                small_path,
                selected_small,
                cancel_check,
            )
            request_count += 1
            if post_error is not None or small_soup is None:
                return AgencyOptionsResult(
                    (),
                    small_path,
                    AgencyOptionSource.POSTBACK,
                    request_count,
                    time.perf_counter() - started,
                    post_error,
                )
            fine_options, parse_error = self._remember_postback_state(
                master_url,
                multi_url,
                small_path,
                small_soup,
            )
            if parse_error is not None:
                return AgencyOptionsResult(
                    (),
                    small_path,
                    AgencyOptionSource.POSTBACK,
                    request_count,
                    time.perf_counter() - started,
                    parse_error,
                )

        return AgencyOptionsResult(
            fine_options or (),
            small_path,
            (
                self._list_children_sources.get(fine_key)
                or AgencyOptionSource.MEMORY
            ),
            request_count,
            time.perf_counter() - started,
        )

    def _get_or_fetch_root(
        self,
        master_url: str,
        multi_url: str,
        cancel_check: Optional[Callable[[], bool]],
    ) -> tuple[
        Optional[_WebFormsState], int, Optional[AgencyOptionsError]
    ]:
        root_key = (
            self._cache_master_url(master_url),
            agency_path_key(AgencyPath()),
        )
        cached = self._get_page_state(root_key)
        if cached is not None:
            return cached, 0, None
        response = None
        try:
            response = self.http_client.get(
                master_url,
                cancel_check=cancel_check,
                purpose=NetworkPurpose.SEARCH,
            )
            soup = self._to_soup(response)
        except Exception as exc:
            code = (
                AgencyOptionsErrorCode.CANCELLED
                if self._cancelled(cancel_check)
                else AgencyOptionsErrorCode.FETCH_FAILED
            )
            return None, 1, AgencyOptionsError(
                code, f"発注機関リスト検索ページを取得できません: {exc}"
            )
        finally:
            self._close_response(response)
        if not self._remember_root_state(master_url, soup, multi_url):
            return None, 1, AgencyOptionsError(
                AgencyOptionsErrorCode.DROPDOWN_MISSING,
                "発注機関リスト検索の大分類が見つかりません",
            )
        return self._get_page_state(root_key), 1, None

    def _remember_root_state(
        self,
        master_url: str,
        soup: BeautifulSoup,
        multi_url: Optional[str] = None,
    ) -> bool:
        root = AgencyPath()
        if not self._parser.has_options_container(
            soup, AgencyLevel.DAIBUNRUI
        ):
            return False
        root_options = tuple(
            self._parser.extract_options(
                soup, AgencyLevel.DAIBUNRUI, root
            )
        )
        root_key = (
            self._cache_master_url(master_url),
            agency_path_key(root),
        )
        self._store_page_state(root_key, self._compact_page_state(soup))
        self._store_list_children(
            master_url,
            root,
            root_options,
            AgencyOptionSource.LIST_EMBEDDED,
        )
        target_multi_url = multi_url or self._as_multi_url(master_url)
        self._publish_list_branch(
            master_url,
            target_multi_url,
            root,
            root_options,
            AgencyOptionSource.LIST_EMBEDDED,
        )

        for top in root_options:
            top_path = root.append(top)
            try:
                embedded = self._parser.extract_embedded_middle_options(
                    soup, top_path
                )
            except ValueError as exc:
                self.logger.warning(
                    f"発注機関の埋め込み中分類を解析できません: {exc}"
                )
                continue
            if embedded is None:
                continue
            self._store_list_children(
                master_url,
                top_path,
                embedded,
                AgencyOptionSource.LIST_EMBEDDED,
            )
            self._publish_list_branch(
                master_url,
                target_multi_url,
                top_path,
                tuple(embedded),
                AgencyOptionSource.LIST_EMBEDDED,
            )
        return True

    def _post_selected_state(
        self,
        state: _WebFormsState,
        master_url: str,
        selected_path: AgencyPath,
        event_option: AgencyOption,
        cancel_check: Optional[Callable[[], bool]],
        *,
        sibling_options: Optional[Tuple[AgencyOption, ...]] = None,
    ) -> tuple[Optional[BeautifulSoup], Optional[AgencyOptionsError]]:
        form_data = dict(state.hidden_inputs)
        for segment in selected_path.segments:
            form_data[self._parser.dropdown_name(segment.level)] = segment.code
        dropdown_name = self._parser.dropdown_name(event_option.level)
        form_data["__EVENTTARGET"] = dropdown_name
        form_data["__EVENTARGUMENT"] = ""
        if (
            event_option.level is AgencyLevel.CHUBUNRUI
            and sibling_options
        ):
            for index, option in enumerate(sibling_options, start=1):
                if option.code == event_option.code:
                    form_data["txtLgKikanInf2SelIndex_h"] = str(index)
                    break
        self._add_webforms_compatibility_fields(
            state,
            form_data,
            event_option,
            event_option,
        )
        response = None
        try:
            response = self.http_client.post(
                master_url,
                data=form_data,
                cancel_check=cancel_check,
                purpose=NetworkPurpose.SEARCH,
            )
            return self._to_soup(response), None
        except Exception as exc:
            code = (
                AgencyOptionsErrorCode.CANCELLED
                if self._cancelled(cancel_check)
                else AgencyOptionsErrorCode.FETCH_FAILED
            )
            return None, AgencyOptionsError(
                code, f"発注機関の下位候補を取得できません: {exc}"
            )
        finally:
            self._close_response(response)

    def _remember_postback_state(
        self,
        master_url: str,
        multi_url: str,
        selected_path: AgencyPath,
        soup: BeautifulSoup,
    ) -> tuple[
        Tuple[AgencyOption, ...], Optional[AgencyOptionsError]
    ]:
        child_level = selected_path.next_level
        if child_level is None:
            return (), None
        if not self._parser.has_options_container(soup, child_level):
            return (), AgencyOptionsError(
                AgencyOptionsErrorCode.DROPDOWN_MISSING,
                f"発注機関の{child_level.value}候補欄が見つかりません",
            )
        options = tuple(
            self._parser.extract_options(soup, child_level, selected_path)
        )
        key = (
            self._cache_master_url(master_url),
            agency_path_key(selected_path),
        )
        self._store_page_state(key, self._compact_page_state(soup))
        self._store_list_children(
            master_url,
            selected_path,
            options,
            AgencyOptionSource.POSTBACK,
        )
        self._publish_list_branch(
            master_url,
            multi_url,
            selected_path,
            options,
            AgencyOptionSource.POSTBACK,
        )
        return options, None

    def _store_children(
        self,
        master_url: str,
        parent: AgencyPath,
        options,
        source: AgencyOptionSource,
    ) -> None:
        key = (
            self._cache_master_url(master_url),
            agency_path_key(parent),
        )
        self._children_cache[key] = tuple(options)
        self._children_sources[key] = source

    def _store_list_children(
        self,
        master_url: str,
        parent: AgencyPath,
        options,
        source: AgencyOptionSource,
    ) -> None:
        key = (
            self._cache_master_url(master_url),
            agency_path_key(parent),
        )
        self._list_children_cache[key] = tuple(options)
        self._list_children_sources[key] = source

    def _publish_list_branch(
        self,
        master_url: str,
        multi_url: str,
        parent: AgencyPath,
        list_options: Tuple[AgencyOption, ...],
        list_source: AgencyOptionSource,
    ) -> None:
        mismatch = self._compare_catalog_branch(
            multi_url, parent, list_options
        )
        snapshot = self._catalog_snapshots.get(multi_url)
        canonical = self._canonical_parent(snapshot, parent)
        if (
            not mismatch
            and snapshot is not None
            and snapshot.is_valid
            and snapshot.contains_parent(canonical)
        ):
            self._store_children(
                master_url,
                canonical,
                snapshot.get_children(canonical),
                AgencyOptionSource.MULTI_TREE,
            )
            return
        self._store_children(
            master_url,
            parent,
            list_options,
            list_source,
        )

    def _compare_catalog_branch(
        self,
        multi_url: str,
        parent: AgencyPath,
        list_options: Tuple[AgencyOption, ...],
    ) -> bool:
        snapshot = self._catalog_snapshots.get(multi_url)
        if snapshot is None or not snapshot.is_valid:
            return False
        canonical = self._canonical_parent(snapshot, parent)
        if not snapshot.contains_parent(canonical):
            return False
        catalog_by_code = {
            option.code: option.label
            for option in snapshot.get_children(canonical)
        }
        list_by_code = {option.code: option.label for option in list_options}
        mismatches = [
            code
            for code in catalog_by_code.keys() & list_by_code.keys()
            if self._normalize_text(catalog_by_code[code])
            != self._normalize_text(list_by_code[code])
        ]
        if not mismatches:
            return False
        invalid_key = (multi_url, agency_path_key(canonical))
        self._catalog_invalid_paths.add(invalid_key)
        self.logger.warning(
            "発注機関カタログとリスト検索の表示名が一致しないため、"
            "リスト検索へフォールバックします: "
            f"対象={self._catalog_target(multi_url)} "
            f"階層={len(canonical.segments)} 不一致={len(mismatches)}件"
        )
        return True

    @staticmethod
    def _canonical_parent(
        snapshot: Optional[AgencyCatalogSnapshot],
        parent: AgencyPath,
    ) -> AgencyPath:
        if snapshot is None or not snapshot.is_valid or not parent.segments:
            return parent
        return snapshot.resolve_path(parent.labels, parent.codes) or parent

    @staticmethod
    def _cancelled(
        cancel_check: Optional[Callable[[], bool]],
    ) -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception:
            return False

    @staticmethod
    def _failed_snapshot(
        source_url: str,
        code: AgencyOptionsErrorCode,
        message: str,
        request_count: int,
        started: float,
    ) -> AgencyCatalogSnapshot:
        return AgencyCatalogSnapshot(
            source_url=source_url,
            children={},
            request_count=request_count,
            elapsed_seconds=time.perf_counter() - started,
            error=AgencyOptionsError(code, message),
        )

    @staticmethod
    def _error_result(
        parent: AgencyPath,
        code: AgencyOptionsErrorCode,
        message: str,
        request_count: int,
        started: float,
    ) -> AgencyOptionsResult:
        return AgencyOptionsResult(
            (),
            parent,
            None,
            request_count,
            time.perf_counter() - started,
            AgencyOptionsError(code, message),
        )

    def resolve_project_agency(
        self,
        project_metadata: Mapping[str, object],
        selected_path: Optional[AgencyPath],
        *,
        search_url: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgencyPathResolution:
        """詳細ページの表示値を使い、選択済みの枝を細分類まで補完する。"""

        path = selected_path or AgencyPath()
        office_name = str(project_metadata.get("office_name", "") or "").strip()
        agency_id = str(project_metadata.get("agency_id", "") or "").strip()
        agency_name = str(
            project_metadata.get("hachu_kikan", "") or ""
        ).strip()

        if path.is_complete:
            small = path.get(AgencyLevel.SAIBUNRUI)
            if not office_name:
                legacy_id_match = bool(
                    agency_id
                    and small is not None
                    and small.code
                    and agency_id == small.code
                )
                return AgencyPathResolution(
                    path=path,
                    status=(
                        AgencyResolutionStatus.DETAIL_MATCHED
                        if legacy_id_match
                        else AgencyResolutionStatus.UNRESOLVED
                    ),
                    method=("legacy_exact_id" if legacy_id_match else "detail"),
                    reason=(
                        ""
                        if legacy_id_match
                        else (
                            "案件詳細に担当部・事務所名がなく、"
                            "HachushaIdでも細分類を確認できません"
                        )
                    ),
                    office_name=office_name,
                    agency_id=agency_id,
                    reason_code=(
                        AgencyResolutionReasonCode.LEGACY_ID_MATCH.value
                        if legacy_id_match
                        else AgencyResolutionReasonCode.AGENCY_DETAIL_MISSING.value
                    ),
                )
            conflict_code, conflict = self._complete_path_conflict(path, office_name)
            return AgencyPathResolution(
                path=path,
                status=(
                    AgencyResolutionStatus.UNRESOLVED
                    if conflict
                    else AgencyResolutionStatus.DETAIL_MATCHED
                ),
                method="detail_label",
                reason=conflict,
                office_name=office_name,
                agency_id=agency_id,
                reason_code=(
                    conflict_code
                    or AgencyResolutionReasonCode.OFFICE_LABEL_MATCH.value
                ),
            )

        if not path.segments:
            return AgencyPathResolution(
                path=path,
                status=AgencyResolutionStatus.UNRESOLVED,
                method="detail",
                reason="検索条件に発注機関の選択パスがありません",
                office_name=office_name,
                agency_id=agency_id,
                reason_code=AgencyResolutionReasonCode.NOT_SELECTED.value,
            )

        if not (agency_name or office_name or agency_id):
            return AgencyPathResolution(
                path=path,
                status=AgencyResolutionStatus.UNRESOLVED,
                method="detail",
                reason="案件詳細に発注機関の照合情報がありません",
                office_name=office_name,
                agency_id=agency_id,
                reason_code=(
                    AgencyResolutionReasonCode.DETAIL_METADATA_MISSING.value
                ),
            )

        method = "detail_label"
        while not path.is_complete:
            try:
                options_result = self.get_children_result(
                    path,
                    search_url=search_url,
                    cancel_check=cancel_check,
                )
            except Exception as exc:
                self.logger.warning(
                    f"発注機関パスの補完に失敗しました: {exc}"
                )
                return AgencyPathResolution(
                    path=path,
                    status=AgencyResolutionStatus.UNRESOLVED,
                    method="detail",
                    reason=f"発注機関マスターを取得できません: {exc}",
                    office_name=office_name,
                    agency_id=agency_id,
                    reason_code=(
                        AgencyResolutionReasonCode.OPTIONS_UNAVAILABLE.value
                    ),
                )
            if options_result.error is not None:
                error = options_result.error
                return AgencyPathResolution(
                    path=path,
                    status=AgencyResolutionStatus.UNRESOLVED,
                    method="detail",
                    reason=(
                        "発注機関マスターを取得できません: "
                        f"[{error.code.value}] {error.message}"
                    ),
                    office_name=office_name,
                    agency_id=agency_id,
                    reason_code=(
                        AgencyResolutionReasonCode.OPTIONS_UNAVAILABLE.value
                    ),
                )
            children = list(options_result.options)
            matches, match_method = self._matching_children(
                children,
                agency_name=agency_name,
                office_name=office_name,
                agency_id=agency_id,
            )
            if len(matches) != 1:
                match_count = len(matches)
                reason_code = (
                    AgencyResolutionReasonCode.MATCH_NOT_FOUND.value
                    if match_count == 0
                    else AgencyResolutionReasonCode.MATCH_AMBIGUOUS.value
                )
                reason = (
                    "発注機関候補を一意に照合できません"
                    f" (level={path.next_level.value if path.next_level else ''}, "
                    f"matches={match_count})"
                )
                return AgencyPathResolution(
                    path=path,
                    status=AgencyResolutionStatus.UNRESOLVED,
                    method="detail",
                    reason=reason,
                    office_name=office_name,
                    agency_id=agency_id,
                    reason_code=reason_code,
                )
            path = path.append(matches[0])
            if match_method:
                method = match_method

        conflict_code, conflict = self._complete_path_conflict(path, office_name)
        return AgencyPathResolution(
            path=path,
            status=(
                AgencyResolutionStatus.UNRESOLVED
                if conflict
                else AgencyResolutionStatus.DETAIL_MATCHED
            ),
            method=method,
            reason=conflict,
            office_name=office_name,
            agency_id=agency_id,
            reason_code=(
                conflict_code
                or (
                    AgencyResolutionReasonCode.LEGACY_EXACT_ID_MATCHED.value
                    if method == "legacy_exact_id"
                    else AgencyResolutionReasonCode.DETAIL_LABEL_MATCHED.value
                )
            ),
        )

    @staticmethod
    def _find_requested_option(
        options: List[AgencyOption], requested: AgencyOption
    ) -> Optional[AgencyOption]:
        if requested.code:
            code_matches = [
                option for option in options if option.code == requested.code
            ]
            if len(code_matches) == 1:
                return code_matches[0]
        label_matches = [
            option for option in options if option.label == requested.label
        ]
        return label_matches[0] if len(label_matches) == 1 else None

    @classmethod
    def _matching_children(
        cls,
        children: List[AgencyOption],
        *,
        agency_name: str,
        office_name: str,
        agency_id: str,
    ) -> tuple[List[AgencyOption], str]:
        if not children:
            return [], ""
        next_level = children[0].level
        if next_level is AgencyLevel.SAIBUNRUI:
            # 現行サイトではdrpSmallKikanInfの細分類コード（例: 128）と
            # 詳細ページのHachushaId（例: 02105000）は別名前空間である。
            # 担当部・事務所名が得られた場合は表示名を正本として照合する。
            if office_name:
                return [
                    option
                    for option in children
                    if cls._text_matches(option.label, office_name)
                ], "detail_label"

            # 旧HTMLでは両者が同一だったため、担当事務所名がない場合だけ
            # 完全一致を後方互換フォールバックとして使用する。
            if agency_id:
                id_matches = [
                    option for option in children if option.code == agency_id
                ]
                if id_matches:
                    return id_matches, "legacy_exact_id"

        targets = (
            (agency_name,)
            if next_level is AgencyLevel.SAIBUNRUI
            else (agency_name, office_name)
        )
        matches = [
            option
            for option in children
            if any(
                cls._text_matches(option.label, target)
                for target in targets
                if target
            )
        ]
        return matches, "detail_label"

    @classmethod
    def _complete_path_conflict(
        cls,
        path: AgencyPath,
        office_name: str,
    ) -> tuple[str, str]:
        small = path.get(AgencyLevel.SAIBUNRUI)
        if small is None:
            return (
                AgencyResolutionReasonCode.PATH_INCOMPLETE.value,
                "細分類まで解決されていません",
            )
        if (
            office_name
            and not cls._text_matches(small.label, office_name)
        ):
            return (
                AgencyResolutionReasonCode.OFFICE_MISMATCH.value,
                "選択済み細分類と案件の担当部・事務所が一致しません",
            )
        return "", ""

    @staticmethod
    def _text_matches(label: str, target: str) -> bool:
        normalized_label = AgencyHierarchyService._normalize_text(label)
        normalized_target = AgencyHierarchyService._normalize_text(target)
        return bool(
            normalized_label
            and normalized_target
            and (
                normalized_label == normalized_target
                or normalized_label in normalized_target
                or normalized_target in normalized_label
            )
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(value or ""))
        return re.sub(r"[\s\u3000・･／/()（）]+", "", normalized).casefold()

    @staticmethod
    def _to_soup(response) -> BeautifulSoup:
        encoding = (
            getattr(response, "apparent_encoding", None)
            or getattr(response, "encoding", None)
            or "utf-8"
        )
        response.encoding = encoding
        return BeautifulSoup(
            response.content,
            "lxml",
            from_encoding=encoding,
        )

    @staticmethod
    def _close_response(response: object) -> None:
        """実Responseとcloseを持たないfixtureの双方を安全に扱う。"""

        close = getattr(response, "close", None)
        if callable(close):
            close()

    def _compact_page_state(self, soup: BeautifulSoup) -> _WebFormsState:
        """DOMを保持せず、次回POSTに必要な値だけを抽出する。"""

        indexes: Dict[str, Dict[str, int]] = {}
        for dropdown_name in self._parser.DROPDOWN_NAMES.values():
            dropdown = soup.find("select", id=dropdown_name) or soup.find(
                "select", attrs={"name": dropdown_name}
            )
            if dropdown is None:
                continue
            indexes[dropdown_name] = {
                str(option.get("value", "")): index
                for index, option in enumerate(dropdown.find_all("option"))
            }
        return _WebFormsState(
            hidden_inputs=dict(self._form_parser.get_all_hidden_inputs(soup)),
            option_indexes=indexes,
        )

    def _get_page_state(
        self,
        key: Tuple[str, AgencyPathKey],
    ) -> Optional[_WebFormsState]:
        state = self._page_states.get(key)
        if state is not None:
            self._page_states.move_to_end(key)
        return state

    def _store_page_state(
        self,
        key: Tuple[str, AgencyPathKey],
        state: _WebFormsState,
    ) -> None:
        self._page_states[key] = state
        self._page_states.move_to_end(key)
        while len(self._page_states) > self.MAX_PAGE_STATES:
            self._page_states.popitem(last=False)

    def _add_webforms_compatibility_fields(
        self,
        state: _WebFormsState,
        form_data: Dict[str, str],
        requested: AgencyOption,
        selected: AgencyOption,
    ) -> None:
        """対象別の連動selectが参照する既存hidden値を補う。"""

        level = requested.level
        if level is AgencyLevel.DAIBUNRUI:
            form_data.setdefault("drpLargeKikanInf2", "-1")
            form_data.setdefault("drpMiddleKikanInf", "-1")
            form_data.setdefault("drpSmallKikanInf", "-1")
            form_data["txt_ChangeTopKikan"] = "true"
        elif level is AgencyLevel.CHUBUNRUI:
            form_data.setdefault("drpMiddleKikanInf", "-1")
            form_data.setdefault("drpSmallKikanInf", "-1")
            form_data["txtLgKikanInfSelValue_h"] = (
                f"{selected.label},{selected.code}"
            )
            form_data["txt_ChangeLargeKikan"] = "true"
            dropdown_name = self._parser.dropdown_name(level)
            selected_index = state.option_indexes.get(
                dropdown_name, {}
            ).get(selected.code)
            if selected_index is not None:
                form_data["txtLgKikanInf2SelIndex_h"] = str(selected_index)
        elif level is AgencyLevel.SHOUBUNRUI:
            form_data.setdefault("drpSmallKikanInf", "-1")


__all__ = ["AgencyHierarchyService"]
