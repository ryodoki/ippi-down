# -*- coding: utf-8 -*-

"""HTML解析・スクレイピングを行うクラス"""

from bs4 import BeautifulSoup
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs
from dataclasses import dataclass, field
from itertools import count
import json
import re
from ..app.exceptions import NetworkError, RateLimitError
from ..models.file_info import FileInfo
from ..models.agency import (
    AgencyPath,
    AgencyPathResolution,
    AgencyResolutionReasonCode,
    AgencyResolutionStatus,
)
from ..models.download_diagnostics import DownloadIssueCode
from ..models.config_model import SearchConditions
from ..models.search_target import SearchTarget
from ..utils.http_client import HTTPClient
from ..utils.logger import Logger
from ..utils.outbound_policy import NetworkPurpose
from .fetcher.page_fetcher import PageFetcher
from .parser.aspnet_form_parser import AspNetFormParser
from .parser.search_result_parser import SearchResultParser
from .parser.detail_page_parser import DetailPageParser
from .parser.document_classifier import classify_document_candidate
from .parser.models import ProjectEntry
from .extractor.metadata_extractor import MetadataExtractor
from .extractor.agency_hierarchy_service import AgencyHierarchyService
from .naming import Naming
from .search_profiles import get_search_profile, profile_for_url
from ..models.search_summary import (
    DocumentDecision,
    DocumentSummary,
    ProjectClassification,
    ProjectDocumentSummary,
    SearchExtractionSummary,
)


_SEARCH_PROGRESS_GENERATIONS = count(1)


@dataclass
class SearchExtractionDiagnostics:
    """検索結果の部分的な取得失敗を公開戻り値と分離して保持する。"""

    detail_attempted: int = 0
    detail_failed: int = 0
    pagination_failed: int = 0
    validation_failed: int = 0
    errors: List[str] = field(default_factory=list)
    failures: List["RequestFailureDiagnostic"] = field(default_factory=list)

    @property
    def failure_count(self) -> int:
        return (
            self.detail_failed
            + self.pagination_failed
            + self.validation_failed
        )


@dataclass(frozen=True)
class SearchProgress:
    """検索結果走査中にGUIへ通知する累計進捗。"""

    phase: str
    page_number: int
    row_number: int
    rows_on_page: int
    projects_scanned: int
    files_discovered: int
    public_documents: int = 0
    expired_only_projects: int = 0
    no_document_projects: int = 0
    detail_failed_projects: int = 0
    search_summary: Optional[Dict[str, Any]] = None
    projects: Optional[List[Dict[str, Any]]] = None
    project_delta: Optional[Dict[str, Any]] = None
    snapshot_kind: str = "none"
    generation: int = 0


@dataclass(frozen=True)
class RequestFailureDiagnostic:
    """検索HTTP処理の安定した理由コードと再試行可否。"""

    reason_code: str
    message: str
    retryable: bool = False


_HTTP_STATUS_PATTERN = re.compile(r"(?<!\d)([45]\d{2})(?!\d)")


def classify_request_failure(error: Exception) -> RequestFailureDiagnostic:
    """HTTP例外を、ジョブ再試行で使える安全な分類へ変換する。"""
    message = str(error) or error.__class__.__name__
    lowered = message.lower()
    policy_reason = str(getattr(error, "reason_code", "") or "")
    for agency_code in (
        "AGENCY_SELECTION_REMOVED",
        "AGENCY_CATALOG_REFRESH_FAILED",
    ):
        if agency_code in message:
            return RequestFailureDiagnostic(agency_code, message, False)
    if "対象サイトの選択肢へ変換できません" in message:
        return RequestFailureDiagnostic(
            "AGENCY_SELECTION_REMOVED", message, False
        )
    if policy_reason in {
        DownloadIssueCode.OUTBOUND_POLICY_BLOCKED.value,
        DownloadIssueCode.REDIRECT_POLICY_BLOCKED.value,
    }:
        return RequestFailureDiagnostic(
            policy_reason,
            message,
            False,
        )
    if isinstance(error, RateLimitError) or "rate limit" in lowered or "レート制限" in message:
        return RequestFailureDiagnostic(
            DownloadIssueCode.RATE_LIMIT.value,
            message,
            True,
        )

    status_match = _HTTP_STATUS_PATTERN.search(message)
    if status_match is not None:
        status = int(status_match.group(1))
        if status == 429:
            return RequestFailureDiagnostic(
                DownloadIssueCode.RATE_LIMIT.value,
                message,
                True,
            )
        if 500 <= status < 600:
            return RequestFailureDiagnostic(
                DownloadIssueCode.HTTP_5XX.value,
                message,
                True,
            )
        return RequestFailureDiagnostic(
            DownloadIssueCode.HTTP_4XX.value,
            message,
            False,
        )

    if any(token in lowered for token in ("timeout", "timed out")) or "タイムアウト" in message:
        return RequestFailureDiagnostic(
            DownloadIssueCode.NETWORK_TIMEOUT.value,
            message,
            True,
        )
    if any(
        token in lowered
        for token in (
            "invalid url",
            "failed to parse",
            "no connection adapters",
            "invalid schema",
            "too many redirects",
            "exceeded 30 redirects",
        )
    ):
        return RequestFailureDiagnostic(
            DownloadIssueCode.HTTP_STATUS.value,
            message,
            False,
        )
    if "キャンセル" in message or "cancel" in lowered:
        return RequestFailureDiagnostic(
            DownloadIssueCode.CANCELLED.value,
            message,
            False,
        )
    if isinstance(error, NetworkError):
        return RequestFailureDiagnostic(
            DownloadIssueCode.NETWORK_ERROR.value,
            message,
            True,
        )
    return RequestFailureDiagnostic(
        DownloadIssueCode.UNKNOWN.value,
        message,
        False,
    )


class Scraper:
    """HTML解析・スクレイピングを行うクラス"""

    def __init__(self, http_client: HTTPClient, logger: Optional[Logger] = None):
        """初期化"""
        self.http_client = http_client
        self.logger = logger or Logger()
        self._page_fetcher = PageFetcher(http_client, self.logger)
        self._form_parser = AspNetFormParser(self.logger)
        self._search_result_parser = SearchResultParser(self.logger)
        self._detail_page_parser = DetailPageParser(self.logger)
        self._metadata_extractor = MetadataExtractor(self.logger)
        self._agency_hierarchy_service = AgencyHierarchyService(
            http_client, self.logger
        )
        self._initial_search_options_cache: Dict[
            str, Dict[str, Tuple[Tuple[str, str], ...]]
        ] = {}
        self._selected_agency_resolution = AgencyPathResolution(
            path=AgencyPath(),
            status=AgencyResolutionStatus.UNRESOLVED,
            method="search_selection",
            reason="発注機関が選択されていません",
            reason_code=AgencyResolutionReasonCode.NOT_SELECTED.value,
        )
        self.last_search_diagnostics = SearchExtractionDiagnostics()
        self.last_search_summary = SearchExtractionSummary()
        self.last_request_failure: Optional[RequestFailureDiagnostic] = None
        self._search_progress_generation = 0
        self._last_project_delta: Optional[Dict[str, Any]] = None
        self._agency_log_fingerprints: Dict[str, Tuple[str, ...]] = {}

    def _record_search_failure(
        self,
        kind: str,
        message: str,
        *,
        failure: Optional[RequestFailureDiagnostic] = None,
    ) -> None:
        """検索結果内の失敗を記録する（既存のList戻り値は維持）。"""
        if kind == "detail":
            self.last_search_diagnostics.detail_failed += 1
        elif kind == "pagination":
            self.last_search_diagnostics.pagination_failed += 1
        elif kind == "validation":
            self.last_search_diagnostics.validation_failed += 1
        self.last_search_diagnostics.errors.append(message)
        self.last_search_diagnostics.failures.append(
            failure
            or RequestFailureDiagnostic(
                DownloadIssueCode.UNKNOWN.value,
                message,
                False,
            )
        )
        self.logger.warning(message)

    def _set_response_encoding(self, response) -> None:
        """レスポンスのエンコーディングを設定（共通処理）"""
        if response.encoding:
            response.encoding = response.apparent_encoding or 'utf-8'
        else:
            response.encoding = 'utf-8'

    def _parse_response_to_soup(self, response) -> BeautifulSoup:
        """レスポンスからBeautifulSoupを生成（共通処理）"""
        try:
            try:
                self._set_response_encoding(response)
                return BeautifulSoup(
                    response.content,
                    "lxml",
                    from_encoding=response.encoding,
                )
            except (UnicodeDecodeError, LookupError):
                try:
                    return BeautifulSoup(
                        response.content,
                        "lxml",
                        from_encoding='utf-8',
                    )
                except UnicodeDecodeError:
                    return BeautifulSoup(
                        response.content.decode('utf-8', errors='ignore'),
                        "lxml",
                    )
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _set_chubunrui_select_index(self, soup: BeautifulSoup, form_data: Dict[str, str], chubunrui_value: str) -> None:
        """中分類の選択インデックスをform_dataに設定"""
        dropdown = soup.find("select", id="drpLargeKikanInf2")
        if dropdown:
            for idx, opt in enumerate(dropdown.find_all("option")):
                if opt.get("value", "") == chubunrui_value:
                    form_data["txtLgKikanInf2SelIndex_h"] = str(idx)
                    self.logger.debug(f"中分類の選択インデックス: {idx}")
                    break

    def _do_postback(
        self,
        url: str,
        soup: BeautifulSoup,
        event_target: str,
        additional_data: Optional[Dict[str, str]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> BeautifulSoup:
        """POSTバックを実行してBeautifulSoupを返す"""
        form_data = self._get_all_hidden_inputs(soup)
        form_data["__EVENTTARGET"] = event_target
        form_data["__EVENTARGUMENT"] = ""
        if additional_data:
            form_data.update(additional_data)
        response = self.http_client.post(
            url,
            data=form_data,
            cancel_check=cancel_check,
            purpose=NetworkPurpose.SEARCH,
        )
        return self._parse_response_to_soup(response)

    def _normalize_search_url(
        self,
        search_url: str,
        target: object = SearchTarget.KOJI_KEIKA,
    ) -> str:
        """検索URLを選択対象のtabへ正規化する。"""
        parsed = urlparse(search_url)
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        query_params['tab'] = [get_search_profile(target).tab]
        new_query = '&'.join(
            f"{k}={v[0]}" if len(v) == 1 else '&'.join(f"{k}={val}" for val in v)
            for k, v in query_params.items()
        )
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        return normalized

    @staticmethod
    def _profile_from_url(search_url: str):
        try:
            return profile_for_url(search_url)
        except ValueError:
            tab = parse_qs(urlparse(search_url).query).get("tab", ["4"])[0]
            return get_search_profile(
                SearchTarget.GYOMU_KEIKA
                if tab == "7"
                else SearchTarget.KOJI_KEIKA
            )

    def get_agency_children(
        self,
        search_url: str,
        parent_path: Optional[AgencyPath] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        """高速カタログ／tab=4リストから指定した親の直下を取得する。"""

        return self._agency_hierarchy_service.get_children(
            parent_path,
            search_url=search_url,
            cancel_check=cancel_check,
        )

    def bootstrap_agency_catalog(
        self,
        search_url: str,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        """発注機関の先頭3階層を公式ツリーからメモリ展開する。"""

        return self._agency_hierarchy_service.bootstrap_catalog(
            search_url,
            cancel_check=cancel_check,
        )

    def refresh_agency_catalog(
        self,
        search_url: str,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        """再取得に成功した場合だけ発注機関候補を新世代へ切り替える。"""

        snapshot = self._agency_hierarchy_service.refresh_catalog(
            search_url,
            cancel_check=cancel_check,
        )
        if snapshot.is_valid:
            self._initial_search_options_cache.pop(
                self._normalize_search_url(
                    search_url,
                    self._profile_from_url(search_url).target,
                ),
                None,
            )
        return snapshot

    def get_agency_children_result(
        self,
        search_url: str,
        parent_path: Optional[AgencyPath] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        """発注機関候補と取得元・通信回数・構造化エラーを返す。"""

        return self._agency_hierarchy_service.get_children_result(
            parent_path,
            search_url=search_url,
            cancel_check=cancel_check,
        )

    def clear_agency_cache(self) -> None:
        """発注機関のプロセス内候補とWebForms状態だけを破棄する。"""

        self._agency_hierarchy_service.clear_cache()
        self._initial_search_options_cache.clear()

    def resolve_project_agency(
        self,
        project_metadata: Dict[str, Any],
        selected_path: Optional[AgencyPath],
        *,
        search_url: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgencyPathResolution:
        """案件詳細と選択済みの枝から発注機関パスを解決する。"""

        return self._agency_hierarchy_service.resolve_project_agency(
            project_metadata,
            selected_path,
            search_url=search_url,
            cancel_check=cancel_check,
        )

    @staticmethod
    def _build_selected_agency_resolution(
        search_conditions: Optional[SearchConditions],
        codes: Tuple[str, ...] = (),
    ) -> AgencyPathResolution:
        labels = (
            (
                search_conditions.hachu_daibunrui,
                search_conditions.hachu_chubunrui,
                search_conditions.hachu_shoubunrui,
                search_conditions.hachu_saibunrui,
            )
            if search_conditions is not None
            else ()
        )
        path = AgencyPath.from_labels_and_codes(labels, codes)
        return AgencyPathResolution(
            path=path,
            status=(
                AgencyResolutionStatus.SELECTED
                if path.segments
                else AgencyResolutionStatus.UNRESOLVED
            ),
            method="search_selection",
            reason=("" if path.segments else "発注機関が選択されていません"),
            reason_code=(
                AgencyResolutionReasonCode.SELECTED.value
                if path.segments
                else AgencyResolutionReasonCode.NOT_SELECTED.value
            ),
        )

    def _agency_resolution_for_search(
        self,
        search_conditions: Optional[SearchConditions],
    ) -> AgencyPathResolution:
        """現在の検索条件と一致するときだけ解決済みコードを再利用する。"""

        label_only = self._build_selected_agency_resolution(search_conditions)
        current = self._selected_agency_resolution
        if current.path.labels == label_only.path.labels:
            return current
        self._selected_agency_resolution = label_only
        return label_only

    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """ページを取得してBeautifulSoupオブジェクトを返す"""
        self.last_request_failure = None
        try:
            return self._page_fetcher.fetch_page(url)
        except Exception as e:
            self.last_request_failure = classify_request_failure(e)
            self.logger.error(f"ページ取得エラー: {url} - {str(e)}", exc_info=True)
            return None

    def _get_all_hidden_inputs(self, soup: BeautifulSoup) -> Dict[str, str]:
        """すべてのhidden inputを取得"""
        hidden_inputs = self._form_parser.get_all_hidden_inputs(soup)
        
        self.logger.debug(f"hidden inputを{len(hidden_inputs)}個取得しました")
        # 取得したhidden inputの名前をログに出力（最初の10個）
        if hidden_inputs:
            keys_list = list(hidden_inputs.keys())[:10]
            self.logger.debug(f"取得したhidden inputの名前（最初の10個）: {', '.join(keys_list)}")
        
        # 重要なhidden inputの存在を確認
        if "__VIEWSTATE" in hidden_inputs:
            self.logger.debug(f"__VIEWSTATE: 取得済み (長さ: {len(hidden_inputs['__VIEWSTATE'])})")
        else:
            self.logger.warning("__VIEWSTATEが見つかりませんでした")
            # __VIEWSTATEで始まるキーを探す
            viewstate_keys = [k for k in hidden_inputs.keys() if "__VIEWSTATE" in k.upper() or "VIEWSTATE" in k.upper()]
            if viewstate_keys:
                self.logger.debug(f"VIEWSTATE関連のキーが見つかりました: {viewstate_keys}")
        
        if "__EVENTVALIDATION" in hidden_inputs:
            self.logger.debug(f"__EVENTVALIDATION: 取得済み (長さ: {len(hidden_inputs['__EVENTVALIDATION'])})")
        else:
            self.logger.warning("__EVENTVALIDATIONが見つかりませんでした")
            # __EVENTVALIDATIONで始まるキーを探す
            eventvalidation_keys = [k for k in hidden_inputs.keys() if "__EVENTVALIDATION" in k.upper() or "EVENTVALIDATION" in k.upper()]
            if eventvalidation_keys:
                self.logger.debug(f"EVENTVALIDATION関連のキーが見つかりました: {eventvalidation_keys}")
        
        if "__VIEWSTATEGENERATOR" in hidden_inputs:
            self.logger.debug("__VIEWSTATEGENERATOR: 取得済み")
        
        return hidden_inputs

    def _get_all_form_inputs(self, soup: BeautifulSoup) -> Dict[str, str]:
        """すべてのフォームフィールド（hidden, select, text, checkbox）の値を取得
        
        ASP.NET WebFormsのページネーションでは、検索条件を維持するために
        すべてのフォームフィールドを送信する必要があります。
        """
        form_data = {}
        
        # 1. Hidden inputs
        for hidden in soup.find_all("input", type="hidden"):
            name = hidden.get("name", "")
            value = hidden.get("value", "")
            if name:
                form_data[name] = value
        
        # 2. Select elements (ドロップダウン)
        for select in soup.find_all("select"):
            name = select.get("name", "")
            if name:
                # 選択されているオプションの値を取得
                selected_option = select.find("option", selected=True)
                if selected_option:
                    form_data[name] = selected_option.get("value", "")
                else:
                    # 選択されていない場合は最初のオプションの値
                    first_option = select.find("option")
                    if first_option:
                        form_data[name] = first_option.get("value", "")
        
        # 3. Text inputs
        for text_input in soup.find_all("input", type="text"):
            name = text_input.get("name", "")
            value = text_input.get("value", "")
            if name:
                form_data[name] = value
        
        # 4. Checked checkboxes
        for checkbox in soup.find_all("input", type="checkbox"):
            name = checkbox.get("name", "")
            if name and checkbox.get("checked"):
                form_data[name] = checkbox.get("value", "on")
        
        # 5. Checked radio buttons
        for radio in soup.find_all("input", type="radio"):
            name = radio.get("name", "")
            if name and radio.get("checked"):
                form_data[name] = radio.get("value", "")
        
        self.logger.debug(f"全フォームフィールドを{len(form_data)}個取得しました")
        return form_data

    def _get_dropdown_select(self, soup: BeautifulSoup, dropdown_name: str):
        """ドロップダウン要素を取得"""
        dropdown = soup.find("select", {"name": dropdown_name})
        if not dropdown:
            dropdown_id = dropdown_name.replace("$", "_")
            dropdown = soup.find("select", {"id": dropdown_id})
        if not dropdown:
            if "TopKikanInf" in dropdown_name or "HachuDaibunrui" in dropdown_name:
                dropdown = soup.find("select", {"id": lambda x: x and ("TopKikanInf" in str(x) or "HachuDaibunrui" in str(x))})
                if not dropdown:
                    dropdown = soup.find("select", {"name": lambda x: x and ("TopKikanInf" in str(x) or "HachuDaibunrui" in str(x))})
            elif "LargeKikanInf" in dropdown_name or "HachuChubunrui" in dropdown_name:
                dropdown = soup.find("select", {"id": lambda x: x and ("LargeKikanInf" in str(x) or "HachuChubunrui" in str(x))})
                if not dropdown:
                    dropdown = soup.find("select", {"name": lambda x: x and ("LargeKikanInf" in str(x) or "HachuChubunrui" in str(x))})
            elif "MiddleKikanInf" in dropdown_name or "HachuShoubunrui" in dropdown_name:
                dropdown = soup.find("select", {"id": lambda x: x and ("MiddleKikanInf" in str(x) or "HachuShoubunrui" in str(x))})
                if not dropdown:
                    dropdown = soup.find("select", {"name": lambda x: x and ("MiddleKikanInf" in str(x) or "HachuShoubunrui" in str(x))})
            elif "SmallKikanInf" in dropdown_name or "HachuSaibunrui" in dropdown_name:
                dropdown = soup.find("select", {"id": lambda x: x and ("SmallKikanInf" in str(x) or "HachuSaibunrui" in str(x))})
                if not dropdown:
                    dropdown = soup.find("select", {"name": lambda x: x and ("SmallKikanInf" in str(x) or "HachuSaibunrui" in str(x))})
        
        if not dropdown:
            # デバッグ: すべてのselect要素を確認
            all_selects = soup.find_all("select")
            self.logger.debug(f"ドロップダウンが見つかりません: {dropdown_name}")
            self.logger.debug(f"ページ内のselect要素数: {len(all_selects)}")
            if all_selects:
                select_names = [s.get("name", "なし") for s in all_selects[:5]]
                self.logger.debug(f"最初の5個のselect要素のname: {select_names}")
        
        return dropdown

    def _get_dropdown_value_from_text(self, soup: BeautifulSoup, dropdown_name: str, display_text: str) -> Optional[str]:
        """表示テキストまたは既存のvalueに対応するvalueを取得する。"""
        requested = (display_text or "").strip()
        if not requested:
            return None
        dropdown = self._get_dropdown_select(soup, dropdown_name)
        if dropdown:
            for option in dropdown.find_all("option"):
                value = option.get("value", "")
                if option.get_text().strip() == requested or value == requested:
                    return value if value not in ("", "-1") else None
            return None

    def _get_dropdown_text_from_value(
        self,
        soup: BeautifulSoup,
        dropdown_name: str,
        value: str,
    ) -> Optional[str]:
        """valueに対応する正規の表示テキストを取得する。"""
        requested = (value or "").strip()
        if not requested:
            return None
        dropdown = self._get_dropdown_select(soup, dropdown_name)
        if dropdown:
            for option in dropdown.find_all("option"):
                if (option.get("value", "") or "").strip() == requested:
                    text = option.get_text().strip()
                    return text or None
        return None

    @staticmethod
    def _is_placeholder_option(value: str, text: str) -> bool:
        """未選択用optionをGUI候補から除外する。"""
        normalized_value = (value or "").strip()
        normalized_text = (text or "").strip()
        return (
            normalized_value in {"", "-1"}
            or not normalized_text
            or normalized_text.startswith("▽")
            or normalized_text in {"選択してください", "未選択"}
        )

    def _require_dropdown_value(
        self,
        soup: BeautifulSoup,
        dropdown_name: str,
        requested: str,
        label: str,
    ) -> str:
        """指定された表示名/valueを解決し、解決不能なら検索を中止する。"""
        value = self._get_dropdown_value_from_text(
            soup, dropdown_name, requested
        )
        if value is None:
            raise ValueError(
                f"{label}「{requested}」を対象サイトの選択肢へ"
                "変換できません"
            )
        return value

    def get_search_dropdown_options(
        self, search_url: str, dropdown_name: str
    ) -> List[str]:
        """検索ページの初期ドロップダウンから表示名を取得する。"""
        return [
            text
            for _, text in self.get_search_dropdown_option_pairs(
                search_url, dropdown_name
            )
        ]

    def get_search_dropdown_option_pairs(
        self, search_url: str, dropdown_name: str
    ) -> List[Tuple[str, str]]:
        """検索候補を送信コードと表示名のペアで取得する。"""

        profile = self._profile_from_url(search_url)
        shared_dropdowns = {
            profile.place_district_field: "place_chihou",
            **{
                form_field: condition_field
                for condition_field, form_field in profile.category_fields
            },
        }
        shared_field = shared_dropdowns.get(dropdown_name)
        if shared_field is not None:
            return list(
                self.get_initial_search_option_pairs(search_url)[shared_field]
            )
        soup = self.fetch_page(search_url)
        if not soup:
            return []
        return [
            (value, text)
            for value, text in self._parse_html_options(soup, dropdown_name)
            if not self._is_placeholder_option(value, text)
        ]

    def get_initial_search_options(
        self, search_url: str
    ) -> Dict[str, List[str]]:
        """初期検索ページを1回だけ取得し、独立した候補をまとめて返す。

        GUI起動時に地方・工事種別・業種を個別取得すると、共通の
        1リクエスト/秒制限によって発注機関候補の表示まで待たされる。
        同じHTMLに存在するselectはここで一度に解析する。
        """

        pairs = self.get_initial_search_option_pairs(search_url)
        return {
            field: [text for _, text in options]
            for field, options in pairs.items()
        }

    def get_initial_search_option_pairs(
        self, search_url: str
    ) -> Dict[str, List[Tuple[str, str]]]:
        """初期候補を送信コードと表示名のペアで一括取得する。"""

        profile = self._profile_from_url(search_url)
        # 細分類のPOSTバックへ同じVIEWSTATEを安全に渡せるよう、
        # AgencyHierarchyServiceと同じ対象tabを取得する。
        normalized_url = self._agency_hierarchy_service._as_master_url(
            search_url
        )
        cached = self._initial_search_options_cache.get(normalized_url)
        if cached is not None:
            return {
                field: list(options)
                for field, options in cached.items()
            }

        soup = self.fetch_page(normalized_url)
        if not soup:
            return {
                field: []
                for field in (
                    "place_chihou",
                    *(name for name, _ in profile.category_fields),
                )
            }
        self._agency_hierarchy_service.prime_search_page(
            soup,
            normalized_url,
        )

        dropdowns = {
            "place_chihou": profile.place_district_field,
            **dict(profile.category_fields),
        }
        parsed = {
            field: [
                (value, text)
                for value, text in self._parse_html_options(soup, dropdown_name)
                if not self._is_placeholder_option(value, text)
            ]
            for field, dropdown_name in dropdowns.items()
        }
        self._initial_search_options_cache[normalized_url] = {
            field: tuple(options)
            for field, options in parsed.items()
        }
        return parsed

    def _get_place_prefecture_pairs(
        self,
        soup: BeautifulSoup,
        district_value: str,
        target: object = SearchTarget.KOJI_KEIKA,
    ) -> List[Tuple[str, str]]:
        """hiddenフィールドから地方に属する都道府県(value, 表示名)を得る。"""
        profile = get_search_profile(target)
        hidden = soup.find(
            "input", {"name": profile.place_prefecture_info_field}
        )
        raw_value = hidden.get("value", "") if hidden else ""
        pairs: List[Tuple[str, str]] = []
        for entry in raw_value.split(":"):
            parts = [part.strip() for part in entry.split(",")]
            if len(parts) >= 3 and parts[0] == district_value:
                pairs.append((parts[2], parts[1]))
        return pairs

    def _get_place_prefecture_value(
        self,
        soup: BeautifulSoup,
        district_value: str,
        requested: str,
        target: object = SearchTarget.KOJI_KEIKA,
    ) -> Optional[str]:
        """都道府県の表示名またはvalueをvalueへ正規化する。"""
        for value, text in self._get_place_prefecture_pairs(
            soup, district_value, target
        ):
            if requested in (value, text):
                return value
        return None

    def get_place_todofuken_options(
        self, search_url: str, chihou: str
    ) -> List[str]:
        """地方に対応する都道府県の表示名を取得する。"""
        return [
            text
            for _, text in self.get_place_todofuken_option_pairs(
                search_url, chihou
            )
        ]

    def get_place_todofuken_option_pairs(
        self, search_url: str, chihou: str
    ) -> List[Tuple[str, str]]:
        """地方に対応する都道府県をコード付きで取得する。"""

        soup = self.fetch_page(search_url)
        if not soup:
            return []
        profile = self._profile_from_url(search_url)
        district_value = self._get_dropdown_value_from_text(
            soup, profile.place_district_field, chihou
        )
        if not district_value:
            return []
        return self._get_place_prefecture_pairs(
            soup, district_value, profile.target
        )

    def _post_place_prefecture(
        self,
        search_url: str,
        soup: BeautifulSoup,
        chihou: str,
        todofuken: str,
    ) -> Tuple[BeautifulSoup, Optional[str], Optional[str]]:
        """都道府県を選択した状態までASP.NETフォームを進める。"""
        profile = self._profile_from_url(search_url)
        district_value = self._get_dropdown_value_from_text(
            soup, profile.place_district_field, chihou
        )
        if not district_value:
            return soup, None, None
        prefecture_pairs = self._get_place_prefecture_pairs(
            soup, district_value, profile.target
        )
        prefecture_value = next(
            (
                value
                for value, text in prefecture_pairs
                if todofuken in (value, text)
            ),
            None,
        )
        if not prefecture_value:
            return soup, district_value, None
        # hidden mappingにはプレースホルダーがないが、実selectのselectedIndexは
        # 先頭の「▽都道府県」を0として数える。
        prefecture_index = next(
            (
                index + 1
                for index, (value, _) in enumerate(prefecture_pairs)
                if value == prefecture_value
            ),
            1,
        )
        additional_data = {
            profile.place_radio_field: "0",
            profile.place_district_field: district_value,
            profile.place_prefecture_field: prefecture_value,
            profile.place_city_field: "-1",
            (
                "txtGyomuPrefectureSelValue_h"
                if profile.target is SearchTarget.GYOMU_KEIKA
                else "txtKojiPrefectureSelValue_h"
            ): prefecture_value,
            profile.place_prefecture_index_field: str(prefecture_index),
        }
        updated_soup = self._do_postback(
            self._normalize_search_url(search_url, profile.target),
            soup,
            profile.place_prefecture_field,
            additional_data,
        )
        return updated_soup, district_value, prefecture_value

    def get_place_shichouson_options(
        self, search_url: str, chihou: str, todofuken: str
    ) -> List[str]:
        """都道府県に対応する市区町村の表示名を取得する。"""
        return [
            text
            for _, text in self.get_place_shichouson_option_pairs(
                search_url, chihou, todofuken
            )
        ]

    def get_place_shichouson_option_pairs(
        self, search_url: str, chihou: str, todofuken: str
    ) -> List[Tuple[str, str]]:
        """都道府県に対応する市区町村をコード付きで取得する。"""

        soup = self.fetch_page(search_url)
        if not soup:
            return []
        updated_soup, _, prefecture_value = self._post_place_prefecture(
            search_url, soup, chihou, todofuken
        )
        if not prefecture_value:
            return []
        return [
            (value, text)
            for value, text in self._parse_html_options(
                updated_soup,
                self._profile_from_url(search_url).place_city_field,
            )
            if not self._is_placeholder_option(value, text)
        ]

    def _parse_setListItemSub(self, response_text: str, dropdown_name: str) -> List[Tuple[str, str]]:
        """setListItemSub()からオプションを抽出（value, textのタプルのリストを返す）"""
        try:
            dropdown_id = dropdown_name.replace("$", "_")
            dropdown_id_part = dropdown_id.split("_")[-1]
            
            self.logger.debug(f"setListItemSub解析開始: dropdown_name={dropdown_name}, dropdown_id={dropdown_id}")
            
            # setListItemSubの呼び出しパターンを検索
            # パターン: setListItemSub('ID', ['value:text', 'value:text', ...]);
            pattern = rf"setListItemSub\s*\(\s*['\"]([^'\"]*{re.escape(dropdown_id_part)}[^'\"]*)['\"]\s*,\s*\[(.*?)\]\s*\)"
            matches = re.findall(pattern, response_text, re.DOTALL)
            
            self.logger.debug(f"setListItemSubパターンマッチ: {len(matches)}件")
            
            for call_id, list_content in matches:
                # IDが一致するか確認
                if dropdown_id in call_id or dropdown_id_part in call_id:
                    self.logger.debug(f"マッチしたsetListItemSub呼び出し: ID={call_id}")
                    
                    # リストアイテムを抽出（'value:text' または "value:text" の形式）
                    items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
                    options = []
                    
                    for item in items:
                        if ":" in item:
                            # "value:text" 形式を分解
                            parts = item.split(":", 1)
                            if len(parts) == 2:
                                value, text = parts
                                options.append((value, text))
                                self.logger.debug(f"  オプション: value={value}, text={text}")
                            else:
                                # コロンが1つしかない場合は値のみ
                                options.append((item, item))
                        else:
                            # コロンがない場合は値とテキストが同じ
                            options.append((item, item))
                    
                    self.logger.info(f"setListItemSubから{len(options)}個のオプションを抽出しました")
                    return options
            
            # 別のパターン: setListItemSub('ID', LIST変数)の形式も試す
            # パターン: setListItemSub('ID', VAR)
            pattern_var = rf"setListItemSub\s*\(\s*['\"]([^'\"]*{re.escape(dropdown_id_part)}[^'\"]*)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
            matches_var = re.findall(pattern_var, response_text)
            
            self.logger.debug(f"setListItemSub変数形式パターンマッチ: {len(matches_var)}件")
            
            for call_id, var_name in matches_var:
                # IDが一致するか確認
                if dropdown_id in call_id or dropdown_id_part in call_id:
                    self.logger.debug(f"マッチしたsetListItemSub呼び出し（変数形式）: ID={call_id}, VAR={var_name}")
                    
                    # 変数定義を探す
                    var_pattern = rf"var\s+{re.escape(var_name)}\s*=\s*\[(.*?)\];"
                    var_matches = re.findall(var_pattern, response_text, re.DOTALL)
                    
                    if var_matches:
                        self.logger.debug(f"変数定義が見つかりました: {var_name}")
                        list_content = var_matches[0]
                        
                        # リストアイテムを抽出（'value:text' または "value:text" の形式）
                        items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
                        options = []
                        
                        for item in items:
                            if ":" in item:
                                # "value:text" 形式を分解
                                parts = item.split(":", 1)
                                if len(parts) == 2:
                                    value, text = parts
                                    options.append((value, text))
                                    self.logger.debug(f"  オプション: value={value}, text={text}")
                                else:
                                    options.append((item, item))
                            else:
                                options.append((item, item))
                        
                        if options:
                            self.logger.info(f"setListItemSub（変数形式）から{len(options)}個のオプションを抽出しました")
                            return options
            
            return []
            
        except Exception as e:
            self.logger.error(f"setListItemSub解析エラー: {str(e)}", exc_info=True)
            return []

    def _parse_txtLargeKikanInf_h(self, txtLargeKikanInf_h: str, target_key: str) -> List[Tuple[str, str]]:
        """txtLargeKikanInf_hから指定されたkey（中分類のvalue）に一致するエントリを抽出（Common.jsのgetListItemStrと同じロジック）"""
        try:
            options = []
            # :で分割
            entries = txtLargeKikanInf_h.split(":")
            
            # 中分類のエントリを探す
            chubunrui_entry_index = None
            for i, entry in enumerate(entries):
                parts = entry.split(",")
                if len(parts) >= 3:
                    chubunrui_value = parts[2]
                    if chubunrui_value == target_key:
                        chubunrui_entry_index = i
                        break
            
            if chubunrui_entry_index is None:
                self.logger.debug(f"中分類値 '{target_key}' が見つかりませんでした")
                return []
            
            # 中分類のエントリの次のエントリから小分類のデータを探す
            # 小分類の形式: 小分類value,小分類名,親の中分類value
            for i in range(chubunrui_entry_index + 1, len(entries)):
                entry = entries[i]
                parts = entry.split(",")
                if len(parts) >= 3:
                    shoubunrui_value = parts[0]
                    shoubunrui_name = parts[1]
                    parent_chubunrui_value = parts[2]
                    
                    # 親の中分類の値が一致する場合、これは小分類のデータ
                    if parent_chubunrui_value == target_key:
                        options.append((shoubunrui_value, shoubunrui_name))
                        self.logger.debug(f"小分類を発見: '{shoubunrui_name}' -> '{shoubunrui_value}'")
                    else:
                        # 親の値が一致しない場合は、次のエントリに移る
                        break
            
            self.logger.info(f"txtLargeKikanInf_hから中分類値 '{target_key}' の小分類を{len(options)}個抽出しました")
            return options
        except Exception as e:
            self.logger.error(f"txtLargeKikanInf_h解析エラー: {str(e)}", exc_info=True)
            return []
    
    def _parse_html_options(self, soup: BeautifulSoup, dropdown_name: str) -> List[Tuple[str, str]]:
        """HTMLから<select><option>を解析（value, textのタプルのリストを返す）"""
        dropdown = self._get_dropdown_select(soup, dropdown_name)
        if dropdown:
            options = []
            for option in dropdown.find_all("option"):
                text = option.get_text().strip()
                value = option.get("value", "")
                if not self._is_placeholder_option(value, text):
                    options.append((value, text))
            return options
        return []

    def get_dropdown_options(
        self,
        search_url: str,
        dropdown_name: str,
        parent_values: Optional[Dict[str, str]] = None,
        event_target: Optional[str] = None,
    ) -> List[str]:
        """階層ドロップダウンのオプションを取得（表示テキストのリストを返す）"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            self.logger.debug(f"ドロップダウンオプション取得開始: {dropdown_name}, URL={normalized_url}")
            
            # 初回GET: すべてのhidden inputを取得
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                self.logger.warning("検索ページの取得に失敗しました")
                return []
            
            form_data = self._get_all_hidden_inputs(initial_soup)
            
            # WebFormsでは「値を変更した親」をPOSTバック対象にする。
            form_data["__EVENTTARGET"] = event_target or dropdown_name
            form_data["__EVENTARGUMENT"] = ""
            
            # 親ドロップダウンのvalueをform_dataに含める
            if parent_values:
                for key, value in parent_values.items():
                    form_data[key] = value
                    self.logger.debug(f"親ドロップダウンを設定: {key}={value}")
            
            # POSTリクエスト
            self.logger.debug(f"POST送信: form_dataのキー数={len(form_data)}")
            self.logger.debug(f"form_dataのキー: {', '.join(list(form_data.keys())[:20])}")  # 最初の20個
            
            response = self.http_client.post(
                normalized_url,
                data=form_data,
                purpose=NetworkPurpose.SEARCH,
            )
            if response.status_code == 405:
                self.logger.error("405 Method Not Allowed エラーが発生しました")
                close = getattr(response, "close", None)
                if callable(close):
                    close()
                return []
            
            self.logger.debug(f"POSTレスポンス: status_code={response.status_code}")
            self._set_response_encoding(response)
            response_text = response.text
            soup = self._parse_response_to_soup(response)
            
            # ① setListItemSub()をJavaScriptから解析
            self.logger.debug("setListItemSub()の解析を開始")
            if "setListItemSub" in response_text:
                self.logger.debug("レスポンスにsetListItemSubが含まれています")
                options_from_js = self._parse_setListItemSub(response_text, dropdown_name)
                if options_from_js:
                    display_texts = [
                        text
                        for value, text in options_from_js
                        if not self._is_placeholder_option(value, text)
                    ]
                    self.logger.info(f"setListItemSub()から{len(display_texts)}個のオプションを取得しました")
                    return display_texts
                else:
                    self.logger.debug("setListItemSub()からオプションを抽出できませんでした")
            else:
                self.logger.debug("レスポンスにsetListItemSubが含まれていません")
            
            # ② HTMLから<select><option>を解析
            self.logger.debug("HTMLから<select><option>の解析を開始")
            options_from_html = self._parse_html_options(soup, dropdown_name)
            if options_from_html:
                display_texts = [text for _, text in options_from_html]
                self.logger.info(f"HTMLから{len(display_texts)}個のオプションを取得しました")
                return display_texts
            
            self.logger.warning(f"ドロップダウンオプションを取得できませんでした: {dropdown_name}")
            return []
            
        except Exception as e:
            self.logger.error(f"ドロップダウンオプション取得エラー: {dropdown_name} - {str(e)}", exc_info=True)
            return []

    def extract_file_links(
        self, soup: BeautifulSoup, base_url: str, file_types: List[str]
    ) -> List[FileInfo]:
        """ページからファイルリンクを抽出"""
        file_links = []
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if not href:
                continue

            absolute_url = urljoin(base_url, href)

            parsed_url = urlparse(absolute_url)
            path = parsed_url.path.lower()

            matched_type = None
            for file_type in file_types:
                if path.endswith(file_type.lower()):
                    matched_type = file_type
                    break

            if matched_type:
                filename = path.split("/")[-1] or "untitled" + matched_type
                metadata = self._extract_link_metadata(link)

                file_info = FileInfo(
                    url=absolute_url,
                    filename=filename,
                    file_type=matched_type,
                    page_url=base_url,
                    metadata=metadata,
                )

                file_links.append(file_info)
                self.logger.debug(f"ファイルリンクを発見: {absolute_url}")

        self.logger.info(f"{len(file_links)}個のファイルリンクを抽出しました")
        return file_links

    def extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """ページからメタデータを抽出
        
        抽出する情報:
        - title: ページタイトル
        - hachu_kikan: 発注機関
        - koji_name: 工事名
        - date: 日付（公告日、開札日、契約日など）
        - category: カテゴリ
        """
        metadata = {}

        # タイトル
        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text().strip()

        # テーブルから情報を抽出（i-ppi.jpのページ構造に応じて）
        # 発注機関の抽出
        hachu_labels = ["発注機関", "発注者", "発注元"]
        for label in hachu_labels:
            hachu_elem = soup.find("td", string=re.compile(label))
            if hachu_elem:
                next_td = hachu_elem.find_next_sibling("td")
                if next_td:
                    hachu_text = next_td.get_text().strip()
                    if hachu_text:
                        metadata["hachu_kikan"] = hachu_text
                        break

        # 工事名の抽出
        koji_labels = ["工事名", "工事名称", "案件名"]
        for label in koji_labels:
            koji_elem = soup.find("td", string=re.compile(label))
            if koji_elem:
                next_td = koji_elem.find_next_sibling("td")
                if next_td:
                    koji_text = next_td.get_text().strip()
                    if koji_text:
                        metadata["koji_name"] = koji_text
                        break

        # 日付の抽出（公告日、開札日、契約日など）
        date_labels = ["公告日", "開札日", "契約日", "更新日", "最終更新日"]
        for label in date_labels:
            date_elem = next(
                (
                    element
                    for element in soup.find_all(
                        ["td", "th"], string=re.compile(label)
                    )
                    if str(
                        (
                            element.find_parent("table") or {}
                        ).get("id", "")
                    )
                    not in {"dgrKokoku", "dgrKeika"}
                ),
                None,
            )
            if date_elem is not None:
                next_td = date_elem.find_next_sibling("td")
                if next_td:
                    date_text = next_td.get_text().strip()
                    if date_text:
                        # 最初に見つかった日付を優先的に使用
                        if "date" not in metadata:
                            metadata["date"] = date_text
                        # ラベル付きで保存
                        metadata[f"date_{label}"] = date_text

        # 日付パターンでテキスト全体から日付を抽出（上記で見つからなかった場合）
        if "date" not in metadata:
            date_patterns = [
                r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})[日]?",
                r"(\d{4})-(\d{2})-(\d{2})",
                r"(\d{4})\.(\d{2})\.(\d{2})",
            ]
            page_text = soup.get_text()
            for pattern in date_patterns:
                date_match = re.search(pattern, page_text)
                if date_match:
                    # 日付を正規化（YYYY-MM-DD形式）
                    year, month, day = date_match.groups()
                    metadata["date"] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    break

        # カテゴリの抽出（ページ構造に応じて調整）
        category_elem = soup.find("td", string=re.compile("カテゴリ|分類|種別"))
        if category_elem:
            next_td = category_elem.find_next_sibling("td")
            if next_td:
                category_text = next_td.get_text().strip()
                if category_text:
                    metadata["category"] = category_text

        # 予定価格の抽出
        price_elem = soup.find("td", string=re.compile("予定価格|予定金額"))
        if price_elem:
            next_td = price_elem.find_next_sibling("td")
            if next_td:
                price_text = next_td.get_text().strip()
                # 数値を抽出
                price_match = re.search(r"[\d,]+", price_text.replace(",", ""))
                if price_match:
                    metadata["yotei_price"] = int(price_match.group().replace(",", ""))

        # 落札価格の抽出
        rakusatsu_elem = soup.find("td", string=re.compile("落札価格|契約価格|落札金額"))
        if rakusatsu_elem:
            next_td = rakusatsu_elem.find_next_sibling("td")
            if next_td:
                rakusatsu_text = next_td.get_text().strip()
                # 数値を抽出
                rakusatsu_match = re.search(r"[\d,]+", rakusatsu_text.replace(",", ""))
                if rakusatsu_match:
                    metadata["rakusatsu_price"] = int(rakusatsu_match.group().replace(",", ""))

        # 詳細ページ固有のID付き要素とJavaScript変数を、分割パーサーで
        # 一元的に抽出する。こちらを優先して表記ゆれを上書きする。
        metadata.update(
            self._detail_page_parser.extract_project_metadata(soup)
        )

        return metadata

    def _extract_files_from_tables(
        self, soup: BeautifulSoup, base_url: str, file_types: List[str]
    ) -> List[FileInfo]:
        """dgrKokoku/dgrKeikaテーブルからファイルリンクを抽出（再利用可能なメソッド）
        
        Args:
            soup: BeautifulSoupオブジェクト
            base_url: ベースURL（page_urlに設定される）
            file_types: 対象ファイルタイプのリスト
        
        Returns:
            抽出されたFileInfoのリスト
        """
        files = []
        
        # dgrKokokuとdgrKeikaテーブル内のリンクを抽出
        for table_id in ["dgrKokoku", "dgrKeika"]:
            table = soup.find("table", id=table_id)
            if not table:
                self.logger.debug(f"テーブルが見つかりません: {table_id}")
                continue
            
            self.logger.debug(f"テーブルを発見: {table_id}")
            
            # テーブル内のすべての行を取得（ヘッダー行を除く）
            rows = table.find_all("tr")[1:]  # 最初の行はヘッダー
            
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                
                # 文書名称（最初のセル）
                document_name = cells[0].get_text(strip=True)
                
                # 公開状況セル（2番目のセル）内のリンクを探す
                status_cell = cells[1]
                link = status_cell.find("a", href=True)
                
                if link:
                    href = link.get("href")
                    if href:
                        # 相対URLを絶対URLに変換
                        absolute_url = urljoin(base_url, href)
                        
                        # URL、文書名、対象サイトの既知Servletの順に種別を推定する。
                        # 文書名にExcel/Word等が明示されている場合は、拡張子のない
                        # URLを無条件にPDFへ誤分類しない。
                        classification = classify_document_candidate(
                            absolute_url, document_name, file_types
                        )
                        file_type = classification.file_type
                        is_file_link = bool(file_type)
                        
                        if is_file_link:
                            # ファイル名をURLから抽出（拡張子がある場合）
                            filename = absolute_url.split("/")[-1].split("?")[0]
                            if not filename or "." not in filename:
                                # 拡張子がない場合、文書名称から推測
                                filename = f"{document_name}{file_type}"

                            metadata = {}
                            if document_name:
                                metadata = {
                                    "title": document_name,
                                    "document_name": document_name,
                                }
                            
                            file_info = FileInfo(
                                url=absolute_url,
                                filename=filename,
                                file_type=file_type,
                                page_url=base_url,  # ベースURLを設定（Refererヘッダーに使用）
                                metadata=metadata,
                                allow_html_to_pdf=(
                                    classification.allow_html_to_pdf
                                ),
                            )
                            files.append(file_info)
                            self.logger.debug(f"ファイルリンクを抽出: {document_name} -> {absolute_url} (type: {file_type})")
        
        return files

    @staticmethod
    def _infer_download_file_type(
        url: str,
        document_name: str,
        file_types: List[str],
    ) -> str:
        """拡張子のない配信URLも文書名と既知Servletから安全に推定する。"""
        return classify_document_candidate(
            url, document_name, file_types
        ).file_type

    def _extract_files_with_modular_parser(
        self,
        soup: BeautifulSoup,
        base_url: str,
        file_types: List[str],
        koji_name: Optional[str] = None,
    ) -> List[FileInfo]:
        """分割済みparser/extractorで詳細ページを正規化する。"""
        try:
            candidates = self._detail_page_parser.extract_file_candidates(
                soup, base_url, file_types, koji_name
            )
            project_entry = ProjectEntry(
                detail_url=base_url,
                koji_name=koji_name or "",
                metadata={"koji_name": koji_name} if koji_name else {},
            )
            return [
                self._metadata_extractor.to_file_info(
                    candidate, project_entry, base_url
                )
                for candidate in candidates
            ]
        except Exception as exc:
            self._record_search_failure(
                "detail",
                f"分割パーサーによる詳細ページ解析を継続できません: {exc}",
            )
            return []

    @staticmethod
    def _merge_unique_files(*groups: List[FileInfo]) -> List[FileInfo]:
        """URL単位でファイル候補を統合する。"""
        merged: List[FileInfo] = []
        by_url: Dict[str, FileInfo] = {}
        for group in groups:
            for file_info in group:
                existing = by_url.get(file_info.url)
                if existing:
                    if file_info.metadata:
                        if existing.metadata is None:
                            existing.metadata = {}
                        existing.metadata.update(file_info.metadata)
                    existing.allow_html_to_pdf = (
                        existing.allow_html_to_pdf
                        or file_info.allow_html_to_pdf
                    )
                    continue
                by_url[file_info.url] = file_info
                merged.append(file_info)
        return merged

    def get_hachu_daibunrui_options(self, search_url: str) -> List[str]:
        """大分類のオプションを取得"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            
            soup = self.fetch_page(normalized_url)
            if not soup:
                self.logger.warning("検索ページの取得に失敗しました（大分類）")
                return []
            
            dropdown_name = "drpTopKikanInf"
            dropdown = self._get_dropdown_select(soup, dropdown_name)
            
            if dropdown:
                options = []
                for option in dropdown.find_all("option"):
                    text = option.get_text().strip()
                    value = option.get("value", "")
                    if not self._is_placeholder_option(value, text):
                        options.append(text)
                self.logger.info(f"大分類オプション取得成功: {len(options)}件")
                return options
            else:
                self.logger.warning("大分類のドロップダウンが見つかりません")
                return []
            
        except Exception as e:
            self.logger.error(f"大分類オプション取得エラー: {str(e)}", exc_info=True)
            return []

    def get_hachu_chubunrui_options(
        self, search_url: str, daibunrui_value: str
    ) -> List[str]:
        """中分類のオプションを取得（大分類の表示テキストを指定）"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            
            # まず大分類の表示テキストからvalueを取得
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                return []
            
            parent_dropdown_name = "drpTopKikanInf"
            parent_value_actual = self._get_dropdown_value_from_text(initial_soup, parent_dropdown_name, daibunrui_value)
            if not parent_value_actual:
                self.logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
                return []
            
            self.logger.debug(f"大分類のvalueを取得: {daibunrui_value} -> {parent_value_actual}")
            
            parent_values = {
                parent_dropdown_name: parent_value_actual
            }
            
            dropdown_name = "drpLargeKikanInf2"
            return self.get_dropdown_options(
                normalized_url,
                dropdown_name,
                parent_values,
                event_target=parent_dropdown_name,
            )
            
        except Exception as e:
            self.logger.error(f"中分類オプション取得エラー: {str(e)}", exc_info=True)
            return []

    def get_hachu_shoubunrui_options(
        self, search_url: str, daibunrui_value: str, chubunrui_value: str
    ) -> List[str]:
        """小分類のオプションを取得（大分類と中分類の表示テキストを指定）"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            
            # 初回GET: 大分類のvalueを取得
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                return []
            
            parent_dropdown_name1 = "drpTopKikanInf"
            parent_value1 = self._get_dropdown_value_from_text(initial_soup, parent_dropdown_name1, daibunrui_value)
            if not parent_value1:
                self.logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
                return []
            
            # 大分類を選択してPOST: 中分類のvalueを取得
            form_data = self._get_all_hidden_inputs(initial_soup)
            form_data["__EVENTTARGET"] = parent_dropdown_name1
            form_data["__EVENTARGUMENT"] = ""
            form_data[parent_dropdown_name1] = parent_value1
            
            response = self.http_client.post(
                normalized_url,
                data=form_data,
                purpose=NetworkPurpose.SEARCH,
            )
            soup_after_daibunrui = self._parse_response_to_soup(response)
            
            parent_dropdown_name2 = "drpLargeKikanInf2"
            parent_value2 = self._get_dropdown_value_from_text(soup_after_daibunrui, parent_dropdown_name2, chubunrui_value)
            if not parent_value2:
                self.logger.warning(f"中分類のvalueが見つかりませんでした: {chubunrui_value}")
                return []
            
            # 中分類を選択してPOST: 小分類のオプションを取得
            additional_data2 = {
                parent_dropdown_name1: parent_value1,
                parent_dropdown_name2: parent_value2,
                "txtLgKikanInfSelValue_h": f"{chubunrui_value},{parent_value2}"
            }
            self._set_chubunrui_select_index(soup_after_daibunrui, additional_data2, parent_value2)
            
            response2 = self.http_client.post(
                normalized_url,
                data={**self._get_all_hidden_inputs(soup_after_daibunrui), "__EVENTTARGET": parent_dropdown_name2, "__EVENTARGUMENT": "", **additional_data2},
                purpose=NetworkPurpose.SEARCH,
            )
            self._set_response_encoding(response2)
            response_text2 = response2.text
            soup_after_chubunrui = self._parse_response_to_soup(response2)
            
            # 小分類のオプションを取得（中分類選択後のPOSTレスポンスから）
            # ① setListItemSub()をJavaScriptから解析
            if "setListItemSub" in response_text2:
                options_from_js = self._parse_setListItemSub(response_text2, "drpMiddleKikanInf")
                if options_from_js:
                    display_texts = [text for _, text in options_from_js]
                    self.logger.info(f"setListItemSub()から小分類{len(display_texts)}個のオプションを取得しました")
                    return display_texts
            
            # ② HTMLから<select><option>を解析
            dropdown = self._get_dropdown_select(soup_after_chubunrui, "drpMiddleKikanInf")
            
            if dropdown:
                options = []
                all_options = dropdown.find_all("option")
                self.logger.debug(f"小分類のドロップダウンから{len(all_options)}個のoption要素を発見")
                
                for option in all_options:
                    text = option.get_text().strip()
                    value = option.get("value", "")
                    if not self._is_placeholder_option(value, text):
                        options.append(text)
                        self.logger.debug(f"  小分類オプション追加: value={value}, text={text}")
                
                if options:
                    self.logger.info(f"HTMLから小分類{len(options)}個のオプションを取得しました")
                    return options
                else:
                    self.logger.warning(f"小分類のオプションが見つかりませんでした（すべてのoption要素: {len(all_options)}件）")
            else:
                self.logger.warning("小分類のドロップダウンが見つかりませんでした")
                # デバッグ: すべてのselect要素を確認
                all_selects = soup_after_chubunrui.find_all("select")
                self.logger.debug(f"ページ内のselect要素数: {len(all_selects)}")
                for i, sel in enumerate(all_selects[:10]):
                    name = sel.get("name", "なし")
                    id_attr = sel.get("id", "なし")
                    self.logger.debug(f"  select要素{i+1}: name={name}, id={id_attr}")
            
            self.logger.warning("小分類のオプションを取得できませんでした")
            return []
            
        except Exception as e:
            self.logger.error(f"小分類オプション取得エラー: {str(e)}", exc_info=True)
            return []
    
    def get_hachu_saibunrui_options(
        self, search_url: str, daibunrui_value: str, chubunrui_value: str, shoubunrui_value: str
    ) -> List[str]:
        """細分類のオプションを取得（大分類、中分類、小分類の表示テキストを指定）"""
        try:
            normalized_url = self._normalize_search_url(search_url)
            
            # 初回GET: 大分類のvalueを取得
            initial_soup = self.fetch_page(normalized_url)
            if not initial_soup:
                return []
            
            parent_dropdown_name1 = "drpTopKikanInf"
            parent_value1 = self._get_dropdown_value_from_text(initial_soup, parent_dropdown_name1, daibunrui_value)
            if not parent_value1:
                self.logger.warning(f"大分類のvalueが見つかりませんでした: {daibunrui_value}")
                return []
            
            # 大分類を選択してPOST: 中分類のvalueを取得
            form_data = self._get_all_hidden_inputs(initial_soup)
            form_data["__EVENTTARGET"] = parent_dropdown_name1
            form_data["__EVENTARGUMENT"] = ""
            form_data[parent_dropdown_name1] = parent_value1
            
            response = self.http_client.post(
                normalized_url,
                data=form_data,
                purpose=NetworkPurpose.SEARCH,
            )
            soup_after_daibunrui = self._parse_response_to_soup(response)
            
            parent_dropdown_name2 = "drpLargeKikanInf2"
            parent_value2 = self._get_dropdown_value_from_text(soup_after_daibunrui, parent_dropdown_name2, chubunrui_value)
            if not parent_value2:
                self.logger.warning(f"中分類のvalueが見つかりませんでした: {chubunrui_value}")
                return []
            
            # 中分類を選択してPOST: 小分類のvalueを取得
            additional_data2 = {
                parent_dropdown_name1: parent_value1,
                parent_dropdown_name2: parent_value2,
                "txtLgKikanInfSelValue_h": f"{chubunrui_value},{parent_value2}"
            }
            self._set_chubunrui_select_index(soup_after_daibunrui, additional_data2, parent_value2)
            soup_after_chubunrui = self._do_postback(normalized_url, soup_after_daibunrui, parent_dropdown_name2, additional_data2)
            
            parent_dropdown_name3 = "drpMiddleKikanInf"
            parent_value3 = self._get_dropdown_value_from_text(soup_after_chubunrui, parent_dropdown_name3, shoubunrui_value)
            if not parent_value3:
                self.logger.warning(f"小分類のvalueが見つかりませんでした: {shoubunrui_value}")
                return []
            
            # 小分類を選択してPOST: 細分類のオプションを取得
            form_data3 = self._get_all_hidden_inputs(soup_after_chubunrui)
            form_data3["__EVENTTARGET"] = parent_dropdown_name3
            form_data3["__EVENTARGUMENT"] = ""
            form_data3[parent_dropdown_name1] = parent_value1
            form_data3[parent_dropdown_name2] = parent_value2
            form_data3[parent_dropdown_name3] = parent_value3
            
            response3 = self.http_client.post(
                normalized_url,
                data=form_data3,
                purpose=NetworkPurpose.SEARCH,
            )
            self._set_response_encoding(response3)
            response_text3 = response3.text
            soup_after_shoubunrui = self._parse_response_to_soup(response3)
            
            # 細分類のオプションを取得（小分類選択後のPOSTレスポンスから）
            # ① setListItemSub()をJavaScriptから解析
            if "setListItemSub" in response_text3:
                options_from_js = self._parse_setListItemSub(response_text3, "drpSmallKikanInf")
                if options_from_js:
                    display_texts = [text for _, text in options_from_js]
                    self.logger.info(f"setListItemSub()から細分類{len(display_texts)}個のオプションを取得しました")
                    return display_texts
            
            # ② HTMLから<select><option>を解析
            dropdown = self._get_dropdown_select(soup_after_shoubunrui, "drpSmallKikanInf")
            
            if dropdown:
                options = []
                all_options = dropdown.find_all("option")
                self.logger.debug(f"細分類のドロップダウンから{len(all_options)}個のoption要素を発見")
                
                for option in all_options:
                    text = option.get_text().strip()
                    value = option.get("value", "")
                    if not self._is_placeholder_option(value, text):
                        options.append(text)
                        self.logger.debug(f"  細分類オプション追加: value={value}, text={text}")
                
                if options:
                    self.logger.info(f"HTMLから細分類{len(options)}個のオプションを取得しました")
                    return options
                else:
                    self.logger.warning(f"細分類のオプションが見つかりませんでした（すべてのoption要素: {len(all_options)}件）")
            else:
                self.logger.warning("細分類のドロップダウンが見つかりませんでした")
            
            self.logger.warning("細分類のオプションを取得できませんでした")
            return []
            
        except Exception as e:
            self.logger.error(f"細分類オプション取得エラー: {str(e)}", exc_info=True)
            return []

    def _extract_link_metadata(self, link_tag) -> Dict[str, Any]:
        """リンクタグからメタデータを抽出"""
        metadata = {}

        link_text = link_tag.get_text().strip()
        if link_text:
            metadata["link_text"] = link_text

        parent = link_tag.parent
        if parent:
            parent_text = parent.get_text().strip()
            if parent_text:
                metadata["parent_text"] = parent_text

        return metadata

    def submit_search_form(
        self,
        search_url: str,
        search_conditions: SearchConditions,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Optional[BeautifulSoup]:
        """検索フォームを送信して検索結果ページを取得（階層的ドロップダウン対応）"""
        self.last_request_failure = None
        try:
            profile = get_search_profile(search_conditions.search_target)
            self._selected_agency_resolution = (
                self._build_selected_agency_resolution(search_conditions)
            )
            if cancel_check and cancel_check():
                return None
            if search_conditions.hachu_multi:
                self.logger.error(
                    "複数発注機関検索は現在サポートされていません。"
                    "発注機関（リスト検索）を使用してください"
                )
                return None
            self.logger.info(f"検索フォームを送信中: {search_url}")
            
            normalized_url = self._normalize_search_url(
                search_url, profile.target
            )
            
            # 初期ページを取得
            soup = self.fetch_page(normalized_url)
            if not soup:
                return None
            
            # 階層的ドロップダウンのPOSTバックを順次実行
            daibunrui_value = None
            chubunrui_value = None
            shoubunrui_value = None
            saibunrui_value = None
            
            # 1. 大分類を選択してPOSTバック
            if search_conditions.hachu_daibunrui:
                daibunrui_value = self._require_dropdown_value(
                    soup,
                    "drpTopKikanInf",
                    search_conditions.hachu_daibunrui,
                    "発注機関の大分類",
                )
                self.logger.info(f"大分類を選択: '{search_conditions.hachu_daibunrui}' -> '{daibunrui_value}'")
                soup = self._do_postback(
                    normalized_url,
                    soup,
                    "drpTopKikanInf",
                    {"drpTopKikanInf": daibunrui_value},
                    cancel_check=cancel_check,
                )
                self.logger.debug("大分類のPOSTバック完了")
            
            # 2. 中分類を選択してPOSTバック
            if search_conditions.hachu_chubunrui and daibunrui_value:
                chubunrui_value = self._require_dropdown_value(
                    soup,
                    "drpLargeKikanInf2",
                    search_conditions.hachu_chubunrui,
                    "発注機関の中分類",
                )
                self.logger.info(f"中分類を選択: '{search_conditions.hachu_chubunrui}' -> '{chubunrui_value}'")
                additional_data = {
                    "drpTopKikanInf": daibunrui_value,
                    "drpLargeKikanInf2": chubunrui_value,
                    "drpMiddleKikanInf": "-1",
                    "drpSmallKikanInf": "-1",
                    "txtLgKikanInfSelValue_h": f"{search_conditions.hachu_chubunrui},{chubunrui_value}",
                    "txt_ChangeTopKikan": "true" if daibunrui_value else "false",
                    "txt_ChangeLargeKikan": "true"
                }
                self._set_chubunrui_select_index(soup, additional_data, chubunrui_value)
                soup = self._do_postback(
                    normalized_url,
                    soup,
                    "drpLargeKikanInf2",
                    additional_data,
                    cancel_check=cancel_check,
                )
                self.logger.debug("中分類のPOSTバック完了")
            elif search_conditions.hachu_chubunrui:
                raise ValueError(
                    "発注機関の中分類を送信する大分類がありません"
                )
            
            # 3. 小分類の選択肢を取得（POSTバック後のHTMLから）
            if search_conditions.hachu_shoubunrui and chubunrui_value:
                # まず、POSTバック後のHTMLから小分類の選択肢を取得
                dropdown = soup.find("select", id="drpMiddleKikanInf")
                if dropdown:
                    options = dropdown.find_all("option")
                    self.logger.debug(f"POSTバック後のHTMLから小分類の選択肢を{len(options)}個取得しました")
                    
                    # 小分類の値を取得
                    for opt in options:
                        value = opt.get("value", "")
                        text = opt.get_text(strip=True)
                        if value != "-1" and search_conditions.hachu_shoubunrui in (value, text):
                            shoubunrui_value = value
                            self.logger.info(f"小分類を選択: '{text}' -> '{shoubunrui_value}'")
                            break
                
                # HTMLから取得できなかった場合、txtLargeKikanInf_hから取得を試みる
                if not shoubunrui_value:
                    form_data = self._get_all_hidden_inputs(soup)
                    if "txtLargeKikanInf_h" in form_data:
                        shoubunrui_options = self._parse_txtLargeKikanInf_h(form_data["txtLargeKikanInf_h"], chubunrui_value)
                        self.logger.info(f"txtLargeKikanInf_hから小分類の選択肢を{len(shoubunrui_options)}個取得しました")
                        
                        # 小分類の値を取得
                        for value, text in shoubunrui_options:
                            if search_conditions.hachu_shoubunrui in (value, text):
                                shoubunrui_value = value
                                self.logger.info(f"小分類を選択: '{text}' -> '{shoubunrui_value}'")
                                break
                        
                        if not shoubunrui_value:
                            self.logger.debug(f"利用可能な小分類: {[text for _, text in shoubunrui_options]}")
                    else:
                        self.logger.warning("txtLargeKikanInf_hが見つかりませんでした")

                if not shoubunrui_value:
                    raise ValueError(
                        "発注機関の小分類"
                        f"「{search_conditions.hachu_shoubunrui}」を"
                        "対象サイトの選択肢へ変換できません"
                    )
            elif search_conditions.hachu_shoubunrui:
                raise ValueError(
                    "発注機関の小分類を送信する中分類がありません"
                )
            
            # 4. 小分類を選択してPOSTバック（細分類の選択肢を読み込むため）
            if search_conditions.hachu_shoubunrui and shoubunrui_value:
                self.logger.info(f"小分類を選択してPOSTバック: '{shoubunrui_value}'")
                additional_data = {
                    "drpTopKikanInf": daibunrui_value,
                    "drpLargeKikanInf2": chubunrui_value,
                    "drpMiddleKikanInf": shoubunrui_value,
                    "drpSmallKikanInf": "-1"
                }
                if chubunrui_value:
                    self._set_chubunrui_select_index(soup, additional_data, chubunrui_value)
                soup = self._do_postback(
                    normalized_url,
                    soup,
                    "drpMiddleKikanInf",
                    additional_data,
                    cancel_check=cancel_check,
                )
                self.logger.debug("小分類のPOSTバック完了")
            
            # 5. 細分類を選択（必要な場合）
            if search_conditions.hachu_saibunrui and shoubunrui_value:
                # POSTバック後のHTMLから細分類の選択肢を取得
                dropdown = soup.find("select", id="drpSmallKikanInf")
                if dropdown:
                    options = dropdown.find_all("option")
                    self.logger.debug(f"POSTバック後のHTMLから細分類の選択肢を{len(options)}個取得しました")
                    
                    # 細分類の値を取得
                    for opt in options:
                        value = opt.get("value", "")
                        text = opt.get_text(strip=True)
                        if value != "-1" and search_conditions.hachu_saibunrui in (value, text):
                            saibunrui_value = value
                            self.logger.info(f"細分類を選択: '{text}' -> '{saibunrui_value}'")
                            break
                
                if not saibunrui_value:
                    raise ValueError(
                        "発注機関の細分類"
                        f"「{search_conditions.hachu_saibunrui}」を"
                        "対象サイトの選択肢へ変換できません"
                    )
            elif search_conditions.hachu_saibunrui:
                raise ValueError(
                    "発注機関の細分類を送信する小分類がありません"
                )

            # 6. 工事場所の階層選択をフォーム値へ正規化
            place_district_value = None
            place_prefecture_value = None
            place_city_value = None
            if search_conditions.place_search_type == "list":
                place_district_value = self._get_dropdown_value_from_text(
                    soup,
                    profile.place_district_field,
                    search_conditions.place_chihou,
                )
                if search_conditions.place_todofuken and place_district_value:
                    soup, place_district_value, place_prefecture_value = (
                        self._post_place_prefecture(
                            normalized_url,
                            soup,
                            search_conditions.place_chihou,
                            search_conditions.place_todofuken,
                        )
                    )
                if search_conditions.place_shichouson and place_prefecture_value:
                    place_city_value = self._get_dropdown_value_from_text(
                        soup,
                        profile.place_city_field,
                        search_conditions.place_shichouson,
                    )

            # 7. 検索フォームのデータを構築
            if cancel_check and cancel_check():
                return None
            self._selected_agency_resolution = (
                self._build_selected_agency_resolution(
                    search_conditions,
                    (
                        daibunrui_value or "",
                        chubunrui_value or "",
                        shoubunrui_value or "",
                        saibunrui_value or "",
                    ),
                )
            )
            form_data = self._get_all_hidden_inputs(soup)
            resolved_dropdown_values = {
                "drpTopKikanInf": daibunrui_value,
                "drpLargeKikanInf2": chubunrui_value,
                "drpMiddleKikanInf": shoubunrui_value,
                "drpSmallKikanInf": saibunrui_value,
                profile.place_district_field: place_district_value,
                profile.place_prefecture_field: place_prefecture_value,
                profile.place_city_field: place_city_value,
            }
            search_form_data = self._build_search_form_data(
                search_conditions,
                soup,
                resolved_dropdown_values,
            )
            form_data.update(search_form_data)
            
            # 階層的ドロップダウンの値を明示的に設定
            if daibunrui_value:
                form_data["drpTopKikanInf"] = daibunrui_value
            if chubunrui_value:
                form_data["drpLargeKikanInf2"] = chubunrui_value
            if shoubunrui_value:
                form_data["drpMiddleKikanInf"] = shoubunrui_value
                self.logger.info(f"小分類の値を設定: '{shoubunrui_value}'")
            if saibunrui_value:
                form_data["drpSmallKikanInf"] = saibunrui_value
            if place_district_value:
                form_data[profile.place_district_field] = place_district_value
            if place_prefecture_value:
                form_data[profile.place_prefecture_field] = place_prefecture_value
            if place_city_value:
                form_data[profile.place_city_field] = place_city_value
            
            # 中分類の選択インデックスを再設定（検索時に必要）
            if chubunrui_value:
                self._set_chubunrui_select_index(soup, form_data, chubunrui_value)
            
            # POSTリクエストで検索を実行
            if cancel_check and cancel_check():
                return None
            response = self.http_client.post(
                normalized_url,
                data=form_data,
                cancel_check=cancel_check,
                purpose=NetworkPurpose.SEARCH,
            )
            soup = self._parse_response_to_soup(response)
            
            # リダイレクト後の最終URLを保存（次ページ取得時に使用）
            self._last_search_result_url = response.url
            self._last_search_target = profile.target.value
            self.logger.info(f"検索結果ページを取得しました (URL: {response.url})")
            return soup
            
        except Exception as e:
            self.last_request_failure = classify_request_failure(e)
            if (
                any(
                    str(value or "").strip()
                    for value in (
                        search_conditions.hachu_daibunrui,
                        search_conditions.hachu_chubunrui,
                        search_conditions.hachu_shoubunrui,
                        search_conditions.hachu_saibunrui,
                    )
                )
                and self.last_request_failure.reason_code
                in {
                    DownloadIssueCode.NETWORK_ERROR.value,
                    DownloadIssueCode.NETWORK_TIMEOUT.value,
                    DownloadIssueCode.HTTP_5XX.value,
                }
            ):
                self.last_request_failure = RequestFailureDiagnostic(
                    "AGENCY_CATALOG_REFRESH_FAILED",
                    str(e),
                    False,
                )
            self.logger.error(f"検索フォーム送信エラー: {str(e)}", exc_info=True)
            return None

    def _build_search_form_data(
        self,
        search_conditions: SearchConditions,
        initial_soup: BeautifulSoup,
        resolved_values: Optional[Dict[str, Optional[str]]] = None,
    ) -> Dict[str, Any]:
        """検索フォームのデータを構築"""
        resolved_values = resolved_values or {}
        profile = get_search_profile(search_conditions.search_target)

        def resolve(
            field_name: str, requested: str, label: str
        ) -> str:
            known_value = resolved_values.get(field_name)
            if known_value:
                return known_value
            return self._require_dropdown_value(
                initial_soup, field_name, requested, label
            )

        def resolve_search_option(
            field_name: str, requested: str, label: str
        ) -> str:
            """検索用選択肢を解決し、安全な診断情報だけを記録する。"""
            value = resolve(field_name, requested, label)
            display_text = (
                self._get_dropdown_text_from_value(
                    initial_soup, field_name, value
                )
                or requested
            )
            # hiddenフィールドを含むform_data全体は出力しない。reprを使い、
            # 候補名に改行などが含まれてもログ行を壊さないようにする。
            self.logger.info(
                f"検索送信条件を解決しました: {label} "
                f"(表示名={display_text!r}, コード={value!r})"
            )
            return value

        form_data = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
        }
        
        # 発注機関（リスト検索） - 表示テキストからvalueに変換
        if search_conditions.hachu_daibunrui:
            form_data["drpTopKikanInf"] = resolve(
                "drpTopKikanInf",
                search_conditions.hachu_daibunrui,
                "発注機関の大分類",
            )
        if search_conditions.hachu_chubunrui:
            form_data["drpLargeKikanInf2"] = resolve(
                "drpLargeKikanInf2",
                search_conditions.hachu_chubunrui,
                "発注機関の中分類",
            )
        if search_conditions.hachu_shoubunrui:
            form_data["drpMiddleKikanInf"] = resolve(
                "drpMiddleKikanInf",
                search_conditions.hachu_shoubunrui,
                "発注機関の小分類",
            )
        if search_conditions.hachu_saibunrui:
            form_data["drpSmallKikanInf"] = resolve(
                "drpSmallKikanInf",
                search_conditions.hachu_saibunrui,
                "発注機関の細分類",
            )
        
        # 工事名／業務名（文字列検索）
        if search_conditions.effective_project_name:
            form_data[profile.project_name_field] = (
                search_conditions.effective_project_name
            )
        
        # 工事場所（リスト検索、正しいフィールド名: drpKojiDistrict, drpKojiPrefecture2, drpKojiCity）
        if search_conditions.place_search_type == "list":
            # ラジオボタンでリスト検索を選択
            form_data[profile.place_radio_field] = "0"
            if search_conditions.place_chihou:
                form_data[profile.place_district_field] = resolve(
                    profile.place_district_field,
                    search_conditions.place_chihou,
                    f"{profile.place_label}の地方",
                )
            if search_conditions.place_todofuken:
                form_data[profile.place_prefecture_field] = resolve(
                    profile.place_prefecture_field,
                    search_conditions.place_todofuken,
                    f"{profile.place_label}の都道府県",
                )
            if search_conditions.place_shichouson:
                form_data[profile.place_city_field] = resolve(
                    profile.place_city_field,
                    search_conditions.place_shichouson,
                    f"{profile.place_label}の市区町村",
                )
        
        # 工事場所（文字列検索、正しいフィールド名: tbxKojiPlace）
        if search_conditions.place_search_type == "text" and search_conditions.place_text:
            form_data[profile.place_radio_field] = "1"
            form_data[profile.place_text_field] = search_conditions.place_text
        
        # 入札契約方式（チェックボックス形式、正しいフィールド名: chkKojiNyusatsu*）
        contract_type_map = dict(profile.contract_fields)
        for contract_type in search_conditions.contract_types:
            if contract_type in contract_type_map:
                form_data[contract_type_map[contract_type]] = "on"
        
        # 最終更新日（正しいフィールド名: LastUpdate, tbxLastUpdate）
        if search_conditions.update_date_type == "past" and search_conditions.update_date_days:
            form_data["LastUpdate"] = "rbtLastUpdate2"
            form_data["tbxLastUpdate"] = str(search_conditions.update_date_days)
        
        # 公告日（正しいフィールド名: KokokuDateKeika, dateKokokuFromKeika, dateKokokuToKeika）
        if search_conditions.koukoku_date_type == "range":
            form_data["KokokuDateKeika"] = "rbtKokokuDate2Keika"
            if search_conditions.koukoku_date_start:
                form_data["dateKokokuFromKeika"] = search_conditions.koukoku_date_start
            if search_conditions.koukoku_date_end:
                form_data["dateKokokuToKeika"] = search_conditions.koukoku_date_end
        
        # 開札日（正しいフィールド名: KaisatsuDate, dateKaisatsuFrom, dateKaisatsuTo）
        if search_conditions.kaisatsu_date_type == "range":
            form_data["KaisatsuDate"] = "rbtKaisatsuDate2"
            if search_conditions.kaisatsu_date_start:
                form_data["dateKaisatsuFrom"] = search_conditions.kaisatsu_date_start
            if search_conditions.kaisatsu_date_end:
                form_data["dateKaisatsuTo"] = search_conditions.kaisatsu_date_end
        
        # 契約日（正しいフィールド名: KeiyakuDate, dateKeiyakuFrom, dateKeiyakuTo）
        if search_conditions.keiyaku_date_type == "range":
            form_data["KeiyakuDate"] = "rbtKeiyakuDate2"
            if search_conditions.keiyaku_date_start:
                form_data["dateKeiyakuFrom"] = search_conditions.keiyaku_date_start
            if search_conditions.keiyaku_date_end:
                form_data["dateKeiyakuTo"] = search_conditions.keiyaku_date_end
        
        category_labels = {
            "koji_shubetsu": "工事種別",
            "koji_gyoushu": "工事の業種",
            "gyomu_kubun": "業務区分",
        }
        for condition_field, form_field in profile.category_fields:
            requested = str(getattr(search_conditions, condition_field, "") or "")
            if requested:
                form_data[form_field] = resolve_search_option(
                    form_field,
                    requested,
                    category_labels[condition_field],
                )
        
        # 予定価格（正しいフィールド名: tbxYoteiPriceFrom, tbxYoteiPriceTo）
        if search_conditions.yotei_price_min is not None:
            form_data["tbxYoteiPriceFrom"] = str(search_conditions.yotei_price_min)
        if search_conditions.yotei_price_max is not None:
            form_data["tbxYoteiPriceTo"] = str(search_conditions.yotei_price_max)
        
        # 落札価格／契約価格（正しいフィールド名: tbxRakusatsuPriceFrom, tbxRakusatsuPriceTo）
        if search_conditions.rakusatsu_price_min is not None:
            form_data["tbxRakusatsuPriceFrom"] = str(search_conditions.rakusatsu_price_min)
        if search_conditions.rakusatsu_price_max is not None:
            form_data["tbxRakusatsuPriceTo"] = str(search_conditions.rakusatsu_price_max)
        
        # 落札者名／契約者名（正しいフィールド名: tbxRakusatsuNm）
        if search_conditions.rakusatsu_name:
            form_data["tbxRakusatsuNm"] = search_conditions.rakusatsu_name
        
        # 電子入札（正しいフィールド名: chkElectronicNyusatsu）
        if search_conditions.denshi:
            form_data["chkElectronicNyusatsu"] = "on"
        
        # 公開文書（正しいフィールド名: chkKokaiBunsyo）
        if search_conditions.koukai:
            form_data["chkKokaiBunsyo"] = "on"
        
        # 表示件数（正しいフィールド名: drpCount）
        if search_conditions.display_count:
            form_data["drpCount"] = str(search_conditions.display_count)
        
        # 検索ボタンをクリック
        form_data["btnSearch"] = "検索開始"
        
        return form_data

    def extract_file_links_from_search_results(
        self,
        soup: BeautifulSoup,
        base_url: str,
        file_types: List[str],
        search_conditions: SearchConditions = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[SearchProgress], None]] = None,
    ) -> List[FileInfo]:
        """検索結果ページからファイルリンクを抽出（全ページを処理、ページネーション対応）
        
        Args:
            soup: 検索結果ページのBeautifulSoupオブジェクト
            base_url: ベースURL
            file_types: ファイルタイプのリスト
            search_conditions: 検索条件（工事名でフィルタリングする場合に使用）
        
        Note:
            処理後、self.last_search_total_project_count に検索結果の案件数が
            設定されます。旧last_search_total_koji_countも互換維持します。
        """
        # 公開戻り値は従来どおりListのままにし、部分失敗は診断属性で公開する。
        self.last_search_diagnostics = SearchExtractionDiagnostics()
        self._search_progress_generation = next(
            _SEARCH_PROGRESS_GENERATIONS
        )
        self._last_project_delta = None
        self._agency_log_fingerprints.clear()
        self.last_search_summary = SearchExtractionSummary(
            expired_scope_excluded=bool(
                search_conditions and search_conditions.koukai
            )
        )
        search_target = (
            search_conditions.target
            if search_conditions is not None
            else SearchTarget.coerce(
                getattr(
                    self,
                    "_last_search_target",
                    SearchTarget.KOJI_KEIKA.value,
                )
            )
        )
        all_file_links = []
        current_soup = soup
        page_number = 1
        max_pages = 100  # 無限ループ防止
        total_koji_count = 0  # 全ページの案件数をカウント
        agency_resolution = self._agency_resolution_for_search(
            search_conditions
        )
        
        while page_number <= max_pages:
            if cancel_check and cancel_check():
                break
            self.logger.info(f"検索結果ページ {page_number} を処理中...")

            result_table = current_soup.find("table", id="dgrSearchList")
            if result_table is None:
                page_text = self._normalize_condition_text(
                    current_soup.get_text(" ", strip=True)
                )
                no_match_markers = (
                    "該当する案件が見つかりませんでした",
                    "該当する情報がありません",
                    "検索結果は0件",
                    "該当件数0件",
                )
                if not any(
                    self._normalize_condition_text(marker) in page_text
                    for marker in no_match_markers
                ):
                    self._record_search_failure(
                        "validation",
                        "検索POSTの応答が検索結果ページではありません",
                    )
                break
            project_entries = self._search_result_parser.extract_project_entries(
                current_soup,
                base_url,
                page_no=page_number,
                agency_resolution=agency_resolution,
                search_target=search_target,
            )
            page_koji_count = len(project_entries)
            result_rows = result_table.find_all("tr")[1:] if result_table else []
            if result_rows and not project_entries:
                self._record_search_failure(
                    "validation",
                    f"検索結果ページ{page_number}の案件行を解析できませんでした",
                )
                break
            if not self._validate_search_entries(
                project_entries, search_conditions, page_number
            ):
                break

            total_koji_count += page_koji_count
            self.last_search_summary.projects_matched = total_koji_count
            self.logger.info(
                f"ページ {page_number} の案件数: {page_koji_count}件 "
                f"(累計: {total_koji_count}件)"
            )
            self._emit_search_progress(
                progress_callback,
                SearchProgress(
                    phase="page",
                    page_number=page_number,
                    row_number=0,
                    rows_on_page=page_koji_count,
                    projects_scanned=total_koji_count - page_koji_count,
                    files_discovered=len(all_file_links),
                    public_documents=(
                        self.last_search_summary.public_documents
                    ),
                    expired_only_projects=(
                        self.last_search_summary.expired_only_projects
                    ),
                    no_document_projects=(
                        self.last_search_summary.no_document_projects
                    ),
                    detail_failed_projects=(
                        self.last_search_summary.detail_failed_projects
                    ),
                    search_summary=self.last_search_summary.to_dict(),
                    snapshot_kind="page_start",
                    generation=self._search_progress_generation,
                ),
            )
            
            # 現在のページからファイルリンクを抽出
            page_files = self._extract_file_links_from_single_page(
                current_soup,
                base_url,
                file_types,
                search_conditions,
                project_entries=project_entries,
                page_number=page_number,
                projects_before_page=total_koji_count - page_koji_count,
                files_before_page=len(all_file_links),
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
            all_file_links.extend(page_files)
            if not (cancel_check and cancel_check()):
                self._emit_search_progress(
                    progress_callback,
                    SearchProgress(
                        phase="page_complete",
                        page_number=page_number,
                        row_number=page_koji_count,
                        rows_on_page=page_koji_count,
                        projects_scanned=(
                            self.last_search_summary.projects_scanned
                        ),
                        files_discovered=len(all_file_links),
                        public_documents=(
                            self.last_search_summary.public_documents
                        ),
                        expired_only_projects=(
                            self.last_search_summary.expired_only_projects
                        ),
                        no_document_projects=(
                            self.last_search_summary.no_document_projects
                        ),
                        detail_failed_projects=(
                            self.last_search_summary.detail_failed_projects
                        ),
                        search_summary=self.last_search_summary.to_dict(),
                        projects=self.last_search_summary.project_dicts(),
                        snapshot_kind="page",
                        generation=self._search_progress_generation,
                    ),
                )

            if cancel_check and cancel_check():
                break
            
            # 次のページが存在するか確認
            next_page_soup = self._get_next_page(
                current_soup, base_url, cancel_check=cancel_check
            )
            if next_page_soup is None:
                if (
                    not (cancel_check and cancel_check())
                    and self.last_search_diagnostics.pagination_failed == 0
                ):
                    self.logger.info(f"全{page_number}ページの処理が完了しました")
                break

            if page_number >= max_pages:
                self._record_search_failure(
                    "pagination",
                    f"検索結果が処理上限の{max_pages}ページを超えたため"
                    "残りを取得できませんでした",
                )
                break
            
            current_soup = next_page_soup
            page_number += 1
        
        all_file_links = self._merge_unique_files(all_file_links)
        self.last_search_summary.complete = bool(
            not (cancel_check and cancel_check())
            and self.last_search_diagnostics.failure_count == 0
        )
        # 完全走査時は解析済み案件IDを正とし、ページ再掲による重複を
        # 案件数へ加えない。途中終了時だけ未走査分を含む検索行数を残す。
        self.last_search_summary.projects_matched = (
            len(self.last_search_summary.projects)
            if self.last_search_summary.complete
            else total_koji_count
        )
        self.last_search_summary.refresh_counts()
        # 共通案件数を正本とし、旧属性名もservice.py向けに維持する。
        self.last_search_total_project_count = (
            self.last_search_summary.projects_matched
        )
        self.last_search_total_koji_count = (
            self.last_search_summary.projects_matched
        )
        
        self.logger.info(
            f"検索結果から合計{len(all_file_links)}個のファイルリンクを"
            f"抽出しました（案件数: {total_koji_count}件）"
        )
        return all_file_links

    @staticmethod
    def _emit_search_progress(
        callback: Optional[Callable[[SearchProgress], None]],
        progress: SearchProgress,
    ) -> None:
        if callback is not None:
            callback(progress)

    @staticmethod
    def _document_status_value(document_row: Any) -> str:
        status = getattr(document_row, "status", "UNKNOWN")
        return str(getattr(status, "value", status) or "UNKNOWN").upper()

    @staticmethod
    def _looks_like_detail_page(
        soup: BeautifulSoup,
        document_rows: List[Any],
    ) -> bool:
        """文書0件と、検索・エラーページの誤返却を区別する。"""
        if document_rows:
            return True
        if any(
            soup.find("table", id=table_id) is not None
            for table_id in ("dgrKokoku", "dgrKeika")
        ):
            return True
        title = soup.find("title")
        title_text = title.get_text(" ", strip=True) if title else ""
        return "案件概要" in title_text or "案件詳細" in title_text

    @staticmethod
    def _project_summary_id(
        project_entry: Optional[ProjectEntry],
        koji_name: str,
        document_rows: List[Any],
    ) -> str:
        """案件番号を優先し、名称衝突しない安定した案件IDを作る。"""
        target = (
            project_entry.search_target
            if project_entry is not None
            else SearchTarget.KOJI_KEIKA.value
        )
        base_id = ""
        for row in document_rows:
            href = str(getattr(row, "href", "") or "")
            values = parse_qs(urlparse(href).query)
            anken = next(
                (
                    value
                    for key, candidates in values.items()
                    if key.casefold() == "ankenkanrino".casefold()
                    for value in candidates
                    if value
                ),
                "",
            )
            if anken:
                base_id = anken
                break
        if not base_id and project_entry is not None:
            base_id = "|".join(
                (
                    project_entry.source_url,
                    str(project_entry.page_no),
                    str(project_entry.row_no),
                    project_entry.event_target,
                    project_entry.event_argument,
                )
            )
        return f"{target}|{base_id or koji_name}"

    def _record_project_document_summary(
        self,
        *,
        project_entry: Optional[ProjectEntry],
        koji_name: str,
        document_rows: List[Any],
        candidates: List[FileInfo],
        detail_error: str = "",
    ) -> ProjectDocumentSummary:
        """詳細ページ1件をGUI・ログ用の案件内訳へ正規化する。"""
        candidate_urls = {item.url for item in candidates}
        documents: List[DocumentSummary] = []
        for row in document_rows:
            status = self._document_status_value(row)
            href = str(getattr(row, "href", "") or "")
            if status == "PUBLIC" and href in candidate_urls:
                decision = DocumentDecision.NOT_EVALUATED.value
                reason = "ダウンロード条件を確認中"
            elif status == "PUBLIC":
                decision = DocumentDecision.PUBLIC_LINK_MISSING.value
                reason = (
                    "公開中ですがリンクがないか、選択した形式に対応しません"
                )
            elif status == "EXPIRED":
                decision = DocumentDecision.EXCLUDED_EXPIRED.value
                reason = "公開終了のため対象外"
            else:
                decision = DocumentDecision.UNAVAILABLE.value
                reason = "公開状態を確認できないため対象外"
            documents.append(DocumentSummary(
                document_name=str(
                    getattr(row, "document_name", "") or ""
                ),
                public_status=status,
                document_updated_at=str(
                    getattr(row, "document_updated_at", "") or ""
                ),
                listing_end_at=str(
                    getattr(row, "listing_end_at", "")
                    or getattr(row, "document_expires_at", "")
                    or ""
                ),
                decision=decision,
                decision_reason=reason,
                url=href,
                document_id=str(
                    getattr(row, "document_id", "") or ""
                ),
                section=str(getattr(row, "section", "") or ""),
            ))

        if detail_error:
            classification = ProjectClassification.DETAIL_FAILED.value
        elif not documents:
            classification = ProjectClassification.NO_DOCUMENTS.value
        elif any(item.public_status == "PUBLIC" for item in documents):
            classification = ProjectClassification.PUBLIC_AVAILABLE.value
        elif all(item.public_status == "EXPIRED" for item in documents):
            classification = ProjectClassification.EXPIRED_ONLY.value
        else:
            classification = ProjectClassification.UNKNOWN.value

        project_id = self._project_summary_id(
            project_entry, koji_name, document_rows
        )
        agency_fields = self._project_agency_summary_fields(project_entry)
        project = ProjectDocumentSummary(
            project_id=project_id,
            project_name=koji_name,
            documents=documents,
            classification=classification,
            detail_error=detail_error,
            **agency_fields,
        )
        # 同一案件が複数URLやページで再掲されても、案件ID索引と状態差分で
        # 一定時間に追加・置換する。進捗イベントはこの1案件だけを渡せる。
        adopted = self.last_search_summary.upsert_project(project)
        self._log_agency_classification(adopted)
        self._last_project_delta = adopted.to_dict()
        return adopted

    @staticmethod
    def _project_agency_summary_fields(
        project_entry: Optional[ProjectEntry],
    ) -> Dict[str, Any]:
        if project_entry is None:
            return {}
        resolution = project_entry.agency_resolution
        if resolution is None:
            raw_path = (project_entry.metadata or {}).get("agency_path")
            if isinstance(raw_path, Mapping):
                try:
                    resolution = AgencyPathResolution.from_mapping(
                        raw_path,
                        office_name=project_entry.office_name,
                        agency_id=project_entry.agency_id,
                    )
                except (TypeError, ValueError):
                    resolution = None
        if resolution is None:
            return {
                "office_name": project_entry.office_name,
                "agency_id": project_entry.agency_id,
                "planned_agency_folder": Naming.generate_agency_folder_parts(
                    {},
                    office_name=project_entry.office_name,
                ),
            }
        agency_path = resolution.to_mapping()
        return {
            "agency_path": agency_path,
            "agency_resolution_status": resolution.status.value,
            "agency_resolution_method": resolution.method,
            "agency_resolution_reason_code": resolution.reason_code,
            "agency_resolution_reason": resolution.reason,
            "office_name": resolution.office_name,
            "agency_id": resolution.agency_id,
            "planned_agency_folder": Naming.generate_agency_folder_parts(
                agency_path,
                office_name=resolution.office_name,
            ),
        }

    def _log_agency_classification(
        self,
        project: ProjectDocumentSummary,
    ) -> None:
        path = project.agency_path
        raw_segments = path.get("segments", []) if isinstance(path, Mapping) else []
        segments = [
            segment
            for segment in raw_segments
            if isinstance(segment, Mapping)
        ]
        labels = [str(segment.get("label") or "") for segment in segments]
        codes = [str(segment.get("code") or "") for segment in segments]
        fingerprint = (
            project.agency_resolution_status,
            project.agency_resolution_method,
            project.agency_resolution_reason_code,
            project.agency_resolution_reason,
            *labels,
            *codes,
            *project.planned_agency_folder,
        )
        if self._agency_log_fingerprints.get(project.project_id) == fingerprint:
            return
        self._agency_log_fingerprints[project.project_id] = fingerprint
        fine_code = ""
        for segment in segments:
            if str(segment.get("level") or "") == "saibunrui":
                fine_code = str(segment.get("code") or "")
                break
        payload = {
            "project_id": project.project_id,
            "project_name": project.project_name,
            "status": project.agency_resolution_status,
            "method": project.agency_resolution_method,
            "reason_code": project.agency_resolution_reason_code,
            "reason": project.agency_resolution_reason,
            "path_labels": labels,
            "path_codes": codes,
            "office_name": project.office_name,
            "hachusha_id": project.agency_id,
            "fine_code": fine_code,
            "planned_agency_folder": list(project.planned_agency_folder),
        }
        message = "agency.classification " + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        if project.agency_resolution_status == "unresolved":
            self.logger.warning(message)
        else:
            self.logger.info(message)

    @staticmethod
    def _normalize_condition_text(value: str) -> str:
        import unicodedata

        normalized = unicodedata.normalize("NFKC", value or "")
        return re.sub(r"[\s\u3000／/]+", "", normalized).casefold()

    def _validate_search_entries(
        self,
        entries: List[ProjectEntry],
        search_conditions: Optional[SearchConditions],
        page_number: int,
    ) -> bool:
        """検索結果表が送信条件と矛盾していないことを確認する。"""
        if not search_conditions or not entries:
            return True

        expected_organization = next(
            (
                value
                for value in (
                    search_conditions.hachu_saibunrui,
                    search_conditions.hachu_shoubunrui,
                    search_conditions.hachu_chubunrui,
                )
                if value
            ),
            "",
        )
        profile = get_search_profile(search_conditions.target)
        selected_contracts = search_conditions.contract_types or []
        validate_contract = (
            0 < len(selected_contracts)
            < len(profile.default_contract_types)
        )
        is_koji = profile.target == SearchTarget.KOJI_KEIKA
        expected_industry = (
            search_conditions.koji_gyoushu if is_koji else ""
        )
        industry_is_observable = any(
            bool(
                str(
                    (entry.metadata or {}).get("koji_gyoushu", "")
                    or ""
                ).strip()
            )
            for entry in entries
        )
        if expected_industry and not industry_is_observable:
            self.logger.info(
                "検索結果に工事業種の確認可能な項目がないため、"
                "工事業種の照合は未実施です"
            )

        for entry in entries:
            metadata = entry.metadata or {}
            comparisons = [
                (
                    "発注機関",
                    expected_organization,
                    metadata.get("hachu_kikan", ""),
                    "contains",
                ),
                (
                    profile.project_label,
                    search_conditions.effective_project_name,
                    entry.project_name,
                    "contains",
                ),
            ]
            if is_koji:
                comparisons.append((
                    "工事種別",
                    search_conditions.koji_shubetsu,
                    metadata.get("koji_shubetsu", ""),
                    "equals",
                ))
            else:
                comparisons.append((
                    "業務区分",
                    search_conditions.gyomu_kubun,
                    metadata.get("gyomu_kubun", ""),
                    "equals",
                ))
            for label, expected, actual, match_type in comparisons:
                if not expected:
                    continue
                expected_value = self._normalize_condition_text(expected)
                actual_value = self._normalize_condition_text(actual)
                matches = (
                    expected_value in actual_value
                    if match_type == "contains"
                    else expected_value == actual_value
                )
                if not matches:
                    self._record_search_failure(
                        "validation",
                        f"検索条件が結果へ反映されていません "
                        f"(ページ={page_number}, 行={entry.row_no}, "
                        f"条件={label}, 期待値={expected}, 実際={actual})",
                    )
                    return False

            # 検索結果に業種が明示されている場合だけ照合する。サイトが
            # 業種列を返さない画面を、確認済みとして扱ったり失敗扱いに
            # したりしない。
            actual_industry = str(
                metadata.get("koji_gyoushu", "") or ""
            ).strip()
            if expected_industry and actual_industry:
                if self._normalize_condition_text(
                    expected_industry
                ) != self._normalize_condition_text(actual_industry):
                    self._record_search_failure(
                        "validation",
                        "検索条件が結果へ反映されていません "
                        f"(ページ={page_number}, 行={entry.row_no}, "
                        "条件=工事業種, "
                        f"期待値={expected_industry}, "
                        f"実際={actual_industry})",
                    )
                    return False

            if validate_contract:
                actual_contract = self._normalize_condition_text(
                    metadata.get("contract_type", "")
                )
                if not any(
                    self._normalize_condition_text(value) in actual_contract
                    for value in selected_contracts
                ):
                    self._record_search_failure(
                        "validation",
                        f"入札契約方式が検索条件と一致しません "
                        f"(ページ={page_number}, 行={entry.row_no})",
                    )
                    return False
        return True
    
    def _count_koji_in_page(self, soup: BeautifulSoup, search_conditions: SearchConditions = None) -> int:
        """現在のページの案件数をカウント"""
        result_table = soup.find("table", id="dgrSearchList")
        if not result_table:
            return 0
        
        rows = result_table.find_all("tr")[1:]  # ヘッダー行を除く
        count = 0
        
        for row in rows:
            # 工事名のリンクを探す
            detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
            if not detail_link:
                continue
            
            # 工事名を取得
            koji_name = detail_link.get_text(strip=True)
            if not koji_name:
                cells = row.find_all("td")
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if text:
                        koji_name = text
                        break
            
            if not koji_name:
                continue
            
            # 検索条件で工事名が指定されている場合、フィルタリング
            if search_conditions and search_conditions.effective_project_name:
                if search_conditions.effective_project_name not in koji_name:
                    continue
            
            count += 1
        
        return count
    
    def _get_next_page(
        self,
        current_soup: BeautifulSoup,
        base_url: str,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Optional[BeautifulSoup]:
        """次のページを取得（存在しない場合はNoneを返す）"""
        if cancel_check and cancel_check():
            return None
        # 「次ページ」ボタンを探す（inputタイプのsubmit）
        next_button = current_soup.find("input", {"type": "submit", "value": "次ページ"})
        
        # IDで探す（btnNext1, btnNext2）
        if not next_button:
            next_button = current_soup.find("input", {"id": "btnNext1"})
        if not next_button:
            next_button = current_soup.find("input", {"id": "btnNext2"})
        
        # buttonタイプも確認
        if not next_button:
            next_button = current_soup.find("button", string=lambda x: x and "次ページ" in x)
        
        # inputタイプのbutton（id="btnNext"など）も確認
        if not next_button:
            next_button = current_soup.find("input", {"id": lambda x: x and "Next" in str(x)})
        
        if not next_button:
            self.logger.debug("次ページボタンが見つかりません（検索結果に全件表示済みの可能性）")
            return None
        
        # ボタンがdisabledの場合は次のページがない
        if next_button.get("disabled"):
            self.logger.debug("次ページボタンが無効化されています（最終ページです）")
            return None
        
        # ボタンの名前を取得
        button_name = next_button.get("name", "")
        if not button_name:
            self._record_search_failure(
                "pagination",
                f"次ページボタンの名前が取得できません: {next_button}",
            )
            return None
        
        self.logger.info(f"次ページに移動中... (ボタン名: {button_name})")
        
        # POSTバックで次のページを取得（全フォームフィールドの値を送信）
        form_data = self._get_all_form_inputs(current_soup)
        self.logger.debug(f"Form inputs: __VIEWSTATE={len(form_data.get('__VIEWSTATE', ''))}, __EVENTVALIDATION={len(form_data.get('__EVENTVALIDATION', ''))}, total_fields={len(form_data)}")
        form_data[button_name] = next_button.get("value", "次ページ")
        
        # フォームのaction属性からPOST先URLを取得（これが最も重要！）
        form = current_soup.find("form")
        if form and form.get("action"):
            form_action = form.get("action")
            # 相対URLを絶対URLに変換
            # 重要: 基準URLは「最後にアクセスしたページのURL」を使用する
            # （元の検索条件ページのURLではない）
            from urllib.parse import urljoin
            current_page_url = getattr(self, '_last_search_result_url', base_url)
            actual_url = urljoin(current_page_url, form_action)
            self.logger.info(f"フォームaction属性から取得したURL: {actual_url} (基準URL: {current_page_url})")
        else:
            # フォームaction属性がない場合は、保存されたURLを使用
            actual_url = getattr(self, '_last_search_result_url', base_url)
            self.logger.debug(f"フォームaction属性なし、保存されたURLを使用: {actual_url}")
        
        try:
            if cancel_check and cancel_check():
                return None
            response = self.http_client.post(
                actual_url,
                data=form_data,
                cancel_check=cancel_check,
                purpose=NetworkPurpose.PAGINATION,
            )
            self.logger.debug(f"次ページ応答: status={response.status_code}, content_length={len(response.content)}")
            next_soup = self._parse_response_to_soup(response)
            
            # 次ページのURLも更新
            self._last_search_result_url = response.url
            
            if not next_soup:
                self._record_search_failure(
                    "pagination", "次ページの解析に失敗しました"
                )
                return None
            
            # 検索結果テーブルが存在するか確認
            result_table = next_soup.find("table", id="dgrSearchList")
            if result_table:
                rows = result_table.find_all("tr")[1:]  # ヘッダー以外
                self.logger.debug(f"次ページで検索結果テーブルを発見: {len(rows)}行")
                return next_soup
            else:
                # ページタイトルを確認
                title = next_soup.find("title")
                title_text = title.get_text() if title else "不明"
                self._record_search_failure(
                    "pagination",
                    "次ページに検索結果テーブルがありません "
                    f"(ページタイトル: {title_text})",
                )
                return None
        except Exception as e:
            failure = classify_request_failure(e)
            self._record_search_failure(
                "pagination",
                f"次ページの取得に失敗: {str(e)}",
                failure=failure,
            )
            self.logger.debug("次ページ取得例外", exc_info=True)
            return None
    
    def _extract_file_links_from_single_page(
        self,
        soup: BeautifulSoup,
        base_url: str,
        file_types: List[str],
        search_conditions: SearchConditions = None,
        project_entries: Optional[List[ProjectEntry]] = None,
        page_number: int = 0,
        projects_before_page: int = 0,
        files_before_page: int = 0,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[SearchProgress], None]] = None,
    ) -> List[FileInfo]:
        """単一の検索結果ページからファイルリンクを抽出"""
        file_links = []
        
        # dgrSearchListテーブルを探す
        result_table = soup.find("table", id="dgrSearchList")
        project_entries = (
            project_entries
            if project_entries is not None
            else (
                self._search_result_parser.extract_project_entries(
                    soup,
                    base_url,
                    page_no=page_number,
                    agency_resolution=self._agency_resolution_for_search(
                        search_conditions
                    ),
                    search_target=(
                        search_conditions.target
                        if search_conditions is not None
                        else getattr(
                            self,
                            "_last_search_target",
                            SearchTarget.KOJI_KEIKA.value,
                        )
                    ),
                )
                if result_table
                else []
            )
        )
        # 案件名は一意ではない。同名案件を最後の1件へ集約しないよう、
        # WebFormsが一覧行へ割り当てたpostback識別子で1対1に対応付ける。
        project_entries_by_postback: Dict[
            Tuple[str, str], List[ProjectEntry]
        ] = {}
        for entry in project_entries:
            key = (entry.event_target, entry.event_argument)
            project_entries_by_postback.setdefault(key, []).append(entry)
        
        if result_table:
            # テーブル内のすべての行を取得（ヘッダー行を除く）
            rows = result_table.find_all("tr")[1:]  # 最初の行はヘッダー
            self.logger.debug(f"検索結果テーブルから{len(rows)}行を発見（ヘッダー行を除く）")
            
            filtered_count = 0
            processed_count = 0
            for row in rows:
                if cancel_check and cancel_check():
                    break
                # 工事名のリンクを探す（__doPostBackを呼び出すリンク）
                detail_link = row.find("a", href=lambda x: x and "__doPostBack" in x)
                if not detail_link:
                    # __doPostBackリンクがない場合はスキップ（ヘッダー行や無効な行の可能性）
                    continue
                
                # 検索結果ページから工事名を抽出（リンクのテキストから）
                koji_name = detail_link.get_text(strip=True)
                if not koji_name:
                    # リンクのテキストが空の場合は、同じ行の他のセルから工事名を探す
                    cells = row.find_all("td")
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        if text and text != "":
                            koji_name = text
                            break
                
                # 工事名が空文字列の場合はスキップ
                if not koji_name:
                    self.logger.debug("工事名が抽出できなかったため、この行をスキップします")
                    continue
                
                # 検索条件で工事名が指定されている場合、フィルタリング
                if search_conditions and search_conditions.effective_project_name:
                    if search_conditions.effective_project_name not in koji_name:
                        # 検索条件に一致しない場合はスキップ
                        filtered_count += 1
                        self.logger.debug(
                            "案件名フィルタリング: "
                            f"'{koji_name}' は "
                            f"'{search_conditions.effective_project_name}' "
                            "を含まないためスキップ"
                        )
                        continue
                
                # __doPostBack('dgrSearchList','$0') のような形式から詳細ページのURLを構築
                href = detail_link.get("href", "")
                postback_match = re.search(
                    r"__doPostBack\('([^']+)','([^']+)'\)", href
                )
                if not postback_match:
                    message = (
                        "検索結果行のPOSTバック情報を解析できないため、"
                        f"詳細を取得できません: ページ{page_number}"
                    )
                    self._record_search_failure("detail", message)
                    self._record_project_document_summary(
                        project_entry=ProjectEntry(
                            detail_url=base_url,
                            koji_name=koji_name,
                            metadata={},
                            page_no=page_number,
                            row_no=processed_count + 1,
                            source_url=base_url,
                            project_name=koji_name,
                            search_target=(
                                search_conditions.target.value
                                if search_conditions is not None
                                else getattr(
                                    self,
                                    "_last_search_target",
                                    SearchTarget.KOJI_KEIKA.value,
                                )
                            ),
                        ),
                        koji_name=koji_name,
                        document_rows=[],
                        candidates=[],
                        detail_error=message,
                    )
                    processed_count += 1
                    continue
                event_target = postback_match.group(1)
                event_argument = postback_match.group(2)
                entry_bucket = project_entries_by_postback.get(
                    (event_target, event_argument), []
                )
                project_entry = entry_bucket.pop(0) if entry_bucket else None
                if project_entry is None:
                    message = (
                        "検索結果行と案件エントリを対応付けできないため、"
                        f"詳細を取得できません: ページ{page_number}"
                    )
                    self._record_search_failure("detail", message)
                    self._record_project_document_summary(
                        project_entry=ProjectEntry(
                            detail_url=base_url,
                            koji_name=koji_name,
                            metadata={},
                            page_no=page_number,
                            row_no=processed_count + 1,
                            event_target=event_target,
                            event_argument=event_argument,
                            source_url=base_url,
                            project_name=koji_name,
                            search_target=(
                                search_conditions.target.value
                                if search_conditions is not None
                                else getattr(
                                    self,
                                    "_last_search_target",
                                    SearchTarget.KOJI_KEIKA.value,
                                )
                            ),
                        ),
                        koji_name=koji_name,
                        document_rows=[],
                        candidates=[],
                        detail_error=message,
                    )
                    processed_count += 1
                    continue
                # JavaScriptの__doPostBackを呼び出すリンクなので、POSTリクエストで詳細ページを取得
                # 詳細ページのURLは検索結果ページと同じURLで、__EVENTTARGETと__EVENTARGUMENTを設定
                self._last_project_delta = None
                detail_files = self._extract_files_from_detail_page_via_postback(
                    base_url,
                    "",
                    file_types,
                    soup,
                    koji_name=koji_name,
                    project_entry=project_entry,
                    cancel_check=cancel_check,
                    event_target=event_target,
                    event_argument=event_argument,
                )
                if project_entry:
                    for file_info in detail_files:
                        if file_info.metadata is None:
                            file_info.metadata = {}
                        file_info.metadata.update(project_entry.metadata)
                file_links.extend(detail_files)
                processed_count += 1
                self._emit_search_progress(
                    progress_callback,
                    SearchProgress(
                        phase="detail",
                        page_number=page_number,
                        row_number=processed_count,
                        rows_on_page=len(project_entries),
                        projects_scanned=projects_before_page + processed_count,
                        files_discovered=(
                            files_before_page + len(file_links)
                        ),
                        public_documents=(
                            self.last_search_summary.public_documents
                        ),
                        expired_only_projects=(
                            self.last_search_summary.expired_only_projects
                        ),
                        no_document_projects=(
                            self.last_search_summary.no_document_projects
                        ),
                        detail_failed_projects=(
                            self.last_search_summary.detail_failed_projects
                        ),
                        search_summary=(
                            self.last_search_summary.to_dict()
                        ),
                        project_delta=self._last_project_delta,
                        snapshot_kind="delta",
                        generation=self._search_progress_generation,
                    ),
                )
            
            if filtered_count > 0:
                self.logger.info(f"工事名フィルタリング: {filtered_count}件の工事を除外しました")
        else:
            # dgrSearchListが見つからない場合は、従来の方法で検索
            result_rows = soup.find_all("tr", class_=lambda x: x and "result" in x.lower())
            
            if not result_rows:
                # 直接ファイルリンクを抽出
                direct_files = self.extract_file_links(soup, base_url, file_types)
                # page_urlは既にextract_file_linksで設定されている（base_url）
                file_links.extend(direct_files)
            else:
                for row in result_rows:
                    detail_link = row.find("a", href=True)
                    if detail_link:
                        detail_url = urljoin(base_url, detail_link.get("href"))
                        detail_files = self._extract_files_from_detail_page(detail_url, file_types)
                        file_links.extend(detail_files)
        
        # 検索結果ページに直接ファイルリンクがある場合も抽出
        direct_files = self.extract_file_links(soup, base_url, file_types)
        file_links = self._merge_unique_files(file_links, direct_files)
        
        self.logger.info(f"このページから{len(file_links)}個のファイルリンクを抽出しました")
        return file_links

    def _extract_files_from_detail_page_via_postback(
        self,
        base_url: str,
        postback_href: str,
        file_types: List[str],
        current_soup: BeautifulSoup,
        koji_name: str = None,
        project_entry: Optional[ProjectEntry] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        *,
        event_target: Optional[str] = None,
        event_argument: Optional[str] = None,
    ) -> List[FileInfo]:
        """__doPostBackリンクから詳細ページを取得してファイルを抽出"""
        self.last_search_diagnostics.detail_attempted += 1
        try:
            if cancel_check and cancel_check():
                return []
            # 通常経路ではSearchResultParserが解析した値を直接受け取る。
            # postback_hrefの再解析は既存の内部呼出し・テスト向け互換経路。
            if event_target is None or event_argument is None:
                match = re.search(
                    r"__doPostBack\('([^']+)','([^']+)'\)",
                    postback_href,
                )
                if not match:
                    self._record_search_failure(
                        "detail",
                        "詳細ページのPOSTバック情報を解析できません: "
                        f"{postback_href}",
                    )
                    self._record_project_document_summary(
                        project_entry=project_entry,
                        koji_name=koji_name or "",
                        document_rows=[],
                        candidates=[],
                        detail_error="詳細ページのPOSTバック情報を解析できません",
                    )
                    return []
                event_target = match.group(1)
                event_argument = match.group(2)
            
            # 現在のページのformのaction属性を取得（検索結果ページのURL）
            # 重要: base_urlではなく、最後にアクセスしたページのURLを基準にする
            current_page_url = getattr(self, '_last_search_result_url', base_url)
            
            form = current_soup.find("form")
            if form and form.get("action"):
                # 相対パスを絶対URLに変換（現在のページURLを基準にする）
                post_url = urljoin(current_page_url, form.get("action"))
            else:
                post_url = current_page_url
            
            # 詳細ページのURLとして使用（page_urlに設定するため）
            detail_url = post_url
            
            # 現在のページのhidden inputを取得
            form_data = self._get_all_hidden_inputs(current_soup)
            form_data["__EVENTTARGET"] = event_target
            form_data["__EVENTARGUMENT"] = event_argument
            
            # POSTリクエストで詳細ページを取得
            response = self.http_client.post(
                post_url,
                data=form_data,
                cancel_check=cancel_check,
                purpose=NetworkPurpose.DETAIL,
            )
            detail_soup = self._parse_response_to_soup(response)
            
            if not detail_soup:
                self._record_search_failure(
                    "detail",
                    f"詳細ページのHTMLを解析できません: {detail_url}",
                )
                self._record_project_document_summary(
                    project_entry=project_entry,
                    koji_name=koji_name or "",
                    document_rows=[],
                    candidates=[],
                    detail_error="詳細ページのHTMLを解析できません",
                )
                return []
            
            # 詳細ページのHTMLから直接ファイルリンクを抽出
            # dgrKokokuとdgrKeikaテーブル内のリンクを抽出（再利用可能なメソッドを使用）
            detail_result = self._detail_page_parser.extract_detail_result(
                detail_soup, detail_url, file_types, koji_name
            )
            if not self._looks_like_detail_page(
                detail_soup, detail_result.document_rows
            ):
                message = (
                    "詳細ページではない応答が返されたため"
                    f"公開文書を解析できません: {detail_url}"
                )
                self._record_search_failure("detail", message)
                self._record_project_document_summary(
                    project_entry=project_entry,
                    koji_name=koji_name or "",
                    document_rows=[],
                    candidates=[],
                    detail_error=message,
                )
                return []

            # 検索時に選択した枝と案件詳細の担当部・事務所/HachushaIdを
            # 統合し、細分類まで一意に辿れる場合だけ補完する。
            agency_metadata = dict(detail_result.project_metadata)
            if project_entry is None:
                selected_resolution = self._selected_agency_resolution
                project_entry = ProjectEntry(
                    detail_url=detail_url,
                    koji_name=koji_name or "",
                    metadata=(
                        {
                            "project_name": koji_name,
                            "koji_name": koji_name,
                            "search_target": getattr(
                                self,
                                "_last_search_target",
                                SearchTarget.KOJI_KEIKA.value,
                            ),
                        }
                        if koji_name
                        else {}
                    ),
                    agency_path=selected_resolution.path,
                    agency_resolution=selected_resolution,
                    project_name=koji_name or "",
                    search_target=getattr(
                        self,
                        "_last_search_target",
                        SearchTarget.KOJI_KEIKA.value,
                    ),
                )
            selected_path = project_entry.agency_path
            agency_resolution = self.resolve_project_agency(
                agency_metadata,
                selected_path,
                search_url=base_url,
                cancel_check=cancel_check,
            )
            project_entry.agency_path = agency_resolution.path
            project_entry.agency_resolution = agency_resolution
            project_entry.office_name = agency_resolution.office_name
            project_entry.agency_id = agency_resolution.agency_id
            if project_entry.metadata is None:
                project_entry.metadata = {}
            project_entry.metadata.update(agency_metadata)
            project_entry.metadata.update(agency_resolution.to_metadata())

            modular_project = project_entry
            modular_files = [
                self._metadata_extractor.to_file_info(
                    candidate, modular_project, detail_url
                )
                for candidate in detail_result.candidates
            ]
            files = self._extract_files_from_tables(
                detail_soup, detail_url, file_types
            )
            files = self._merge_unique_files(files, modular_files)
            
            # フォールバック: テーブルから取得できなかった場合、通常のextract_file_linksも試す
            if not files:
                files = self.extract_file_links(detail_soup, detail_url, file_types)
            
            # 通常の成功経路でも詳細メタデータを全ファイルへ付与する。
            metadata = self.extract_metadata(detail_soup)
            metadata.update(agency_resolution.to_metadata())
            page_title = str(metadata.get("title") or "")
            announcement_at = str(metadata.get("date") or "")
            if koji_name:
                metadata["project_name"] = koji_name
                metadata["koji_name"] = koji_name
            metadata["search_target"] = project_entry.search_target
            for file_info in files:
                document_metadata = dict(file_info.metadata or {})
                file_info.metadata = dict(metadata)
                file_info.metadata["page_title"] = page_title
                file_info.metadata["announcement_at"] = announcement_at
                file_info.metadata.update(document_metadata)
                document_name = file_info.metadata.get("document_name")
                if document_name:
                    file_info.metadata["title"] = document_name

            self._record_project_document_summary(
                project_entry=project_entry,
                koji_name=koji_name or "",
                document_rows=detail_result.document_rows,
                candidates=files,
            )
            
            # ファイルが見つかった場合は、UserEntry_Download.aspxを試さない
            # （UserEntry_Download.aspxにはテーブルが存在しないため、試しても0件になる）
            if files:
                self.logger.info(f"詳細ページから{len(files)}個のファイルリンクを抽出しました（UserEntry_Download.aspxはスキップ）")
                return files
            
            # ファイルが見つからなかった場合のみ、従来の方法（UserEntry_Download.aspx）を試す
            # ただし、実際にはUserEntry_Download.aspxにはテーブルがないため、効果がない可能性が高い
            if (
                not files
                and project_entry.search_target
                == SearchTarget.KOJI_KEIKA.value
            ):
                # 詳細ページからAnkenkanriNoとHachushaIdを抽出
                ankenkanri_no = None
                hachusha_id = None
                
                # JavaScriptコードからAnkenkanriNoとHachushaIdを抽出
                script_tags = detail_soup.find_all("script")
                for script in script_tags:
                    script_text = script.string
                    if script_text and "AnkenkanriNo" in script_text:
                        # var AnkenkanriNo = "021020002022412000000486"; のような形式を抽出
                        match = re.search(r'var\s+AnkenkanriNo\s*=\s*"([^"]+)"', script_text)
                        if match:
                            ankenkanri_no = match.group(1)
                            self.logger.debug(f"AnkenkanriNoを抽出: {ankenkanri_no}")
                        
                        match = re.search(r'var\s+HachushaId\s*=\s*"([^"]+)"', script_text)
                        if match:
                            hachusha_id = match.group(1)
                            self.logger.debug(f"HachushaIdを抽出: {hachusha_id}")
                
                # UserEntry_Download.aspxからファイルリンクを取得
                if ankenkanri_no and hachusha_id:
                    download_url = f"https://www.i-ppi.jp/IPPI/DownloadServices/Web/UserEntry_Download.aspx?data1={ankenkanri_no}&data2={hachusha_id}"
                    self.logger.debug(f"UserEntry_Download.aspxにアクセス: {download_url}")
                    
                    download_response = None
                    try:
                        download_response = self.http_client.get(
                            download_url,
                            cancel_check=cancel_check,
                            purpose=NetworkPurpose.DOCUMENT_LIST,
                        )
                        if download_response.status_code == 200:
                            download_soup = self._parse_response_to_soup(download_response)
                            if download_soup:
                                # UserEntry_Download.aspxページからファイルリンクを抽出
                                # dgrKokoku/dgrKeikaテーブル走査ロジックを使用（詳細ページと同じロジック）
                                files = self._extract_files_from_tables(download_soup, download_url, file_types)
                                if not files:
                                    # フォールバック: 通常のextract_file_linksも試す
                                    files = self.extract_file_links(download_soup, download_url, file_types)
                                self.logger.info(f"UserEntry_Download.aspxから{len(files)}個のファイルリンクを抽出しました")
                                
                                # 詳細ページの文書情報（dgrKokoku、dgrKeika）を取得してメタデータに追加
                                document_names = []
                                kokoku_table = download_soup.find("table", id="dgrKokoku")
                                if kokoku_table:
                                    rows = kokoku_table.find_all("tr")[1:]  # ヘッダー行をスキップ
                                    for row in rows:
                                        cells = row.find_all("td")
                                        if len(cells) > 0:
                                            doc_name = cells[0].get_text(strip=True)
                                            if doc_name:
                                                document_names.append(doc_name)
                                
                                keika_table = download_soup.find("table", id="dgrKeika")
                                if keika_table:
                                    rows = keika_table.find_all("tr")[1:]  # ヘッダー行をスキップ
                                    for row in rows:
                                        cells = row.find_all("td")
                                        if len(cells) > 0:
                                            doc_name = cells[0].get_text(strip=True)
                                            if doc_name:
                                                document_names.append(doc_name)
                                
                                # メタデータを追加
                                metadata = self.extract_metadata(detail_soup)
                                metadata.update(
                                    agency_resolution.to_metadata()
                                )
                                if document_names:
                                    metadata["document_names"] = document_names
                                
                                # 工事名を優先的に設定（検索結果ページから取得した工事名があれば使用）
                                if koji_name:
                                    metadata["project_name"] = koji_name
                                    metadata["koji_name"] = koji_name
                                metadata["search_target"] = (
                                    project_entry.search_target
                                )
                                
                                for file_info in files:
                                    if file_info.metadata:
                                        file_info.metadata.update(metadata)
                                    else:
                                        file_info.metadata = metadata
                    except Exception as e:
                        self.logger.warning(f"UserEntry_Download.aspxからのファイル抽出エラー: {str(e)}")
                    finally:
                        close = getattr(download_response, "close", None)
                        if callable(close):
                            close()
            
            # 詳細ページに直接ファイルリンクがある場合も抽出
            if not files:
                files = self.extract_file_links(detail_soup, base_url, file_types)
                metadata = self.extract_metadata(detail_soup)
                metadata.update(agency_resolution.to_metadata())
                # 工事名を優先的に設定（検索結果ページから取得した工事名があれば使用）
                if koji_name:
                    metadata["project_name"] = koji_name
                    metadata["koji_name"] = koji_name
                metadata["search_target"] = project_entry.search_target
                for file_info in files:
                    if file_info.metadata:
                        file_info.metadata.update(metadata)
                    else:
                        file_info.metadata = metadata
            
            return files
            
        except Exception as e:
            failure = classify_request_failure(e)
            self._record_search_failure(
                "detail",
                "詳細ページからのファイル抽出エラー（POST）: "
                f"{postback_href} - {str(e)}",
                failure=failure,
            )
            self._record_project_document_summary(
                project_entry=project_entry,
                koji_name=koji_name or "",
                document_rows=[],
                candidates=[],
                detail_error=str(e),
            )
            return []

    def _extract_files_from_detail_page(self, detail_url: str, file_types: List[str]) -> List[FileInfo]:
        """案件詳細ページからファイルを抽出"""
        self.last_search_diagnostics.detail_attempted += 1
        try:
            soup = self.fetch_page(detail_url)
            if not soup:
                self._record_search_failure(
                    "detail",
                    f"詳細ページの取得に失敗しました: {detail_url}",
                    failure=self.last_request_failure,
                )
                return []
            
            files = self._merge_unique_files(
                self.extract_file_links(soup, detail_url, file_types),
                self._extract_files_with_modular_parser(
                    soup, detail_url, file_types
                ),
            )
            
            metadata = self.extract_metadata(soup)
            for file_info in files:
                if file_info.metadata:
                    file_info.metadata.update(metadata)
                else:
                    file_info.metadata = metadata
            
            return files
            
        except Exception as e:
            failure = classify_request_failure(e)
            self._record_search_failure(
                "detail",
                f"詳細ページからのファイル抽出エラー: {detail_url} - {str(e)}",
                failure=failure,
            )
            return []
