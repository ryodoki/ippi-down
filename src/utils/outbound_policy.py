# -*- coding: utf-8 -*-

"""ippi-downが送信できるHTTPリクエストを公式endpointへ限定する。"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping, Optional, Protocol, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from requests.adapters import BaseAdapter

from ..app.exceptions import NetworkError


class NetworkPurpose(str, Enum):
    """外向きHTTP通信の用途。"""

    STARTUP_CATALOG = "STARTUP_CATALOG"
    SEARCH = "SEARCH"
    PAGINATION = "PAGINATION"
    DETAIL = "DETAIL"
    DOCUMENT_LIST = "DOCUMENT_LIST"
    DOWNLOAD = "DOWNLOAD"
    ERROR = "ERROR"


class NetworkPolicyReasonCode(str, Enum):
    """通信ポリシー判定の安定した理由コード。"""

    ALLOWED = "ALLOWED"
    INVALID_URL = "INVALID_URL"
    HTTPS_REQUIRED = "HTTPS_REQUIRED"
    CREDENTIALS_NOT_ALLOWED = "CREDENTIALS_NOT_ALLOWED"
    PORT_NOT_ALLOWED = "PORT_NOT_ALLOWED"
    FRAGMENT_NOT_ALLOWED = "FRAGMENT_NOT_ALLOWED"
    HOST_NOT_ALLOWED = "HOST_NOT_ALLOWED"
    ENDPOINT_NOT_ALLOWED = "ENDPOINT_NOT_ALLOWED"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    QUERY_NOT_ALLOWED = "QUERY_NOT_ALLOWED"
    PURPOSE_MISMATCH = "PURPOSE_MISMATCH"
    TERMINAL_ENDPOINT_ONLY = "TERMINAL_ENDPOINT_ONLY"
    REDIRECT_ORIGIN_CHANGED = "REDIRECT_ORIGIN_CHANGED"
    PROXY_NOT_ALLOWED = "PROXY_NOT_ALLOWED"
    TLS_VERIFY_REQUIRED = "TLS_VERIFY_REQUIRED"
    CLIENT_CERT_NOT_ALLOWED = "CLIENT_CERT_NOT_ALLOWED"
    AUTH_NOT_ALLOWED = "AUTH_NOT_ALLOWED"
    HOST_HEADER_MISMATCH = "HOST_HEADER_MISMATCH"


@dataclass(frozen=True)
class NetworkPolicyDecision:
    """外向きHTTP通信の判定結果。"""

    allowed: bool
    endpoint_id: str
    normalized_url: str
    reason_code: NetworkPolicyReasonCode
    reason: str
    purpose: Optional[NetworkPurpose] = None


class OutboundPolicyError(NetworkError):
    """通信前にポリシー違反を検出したことを表す非再試行例外。"""

    def __init__(
        self,
        decision: NetworkPolicyDecision,
        *,
        redirect: bool = False,
    ) -> None:
        prefix = (
            "リダイレクト先を通信ポリシーで拒否しました"
            if redirect
            else "通信先を通信ポリシーで拒否しました"
        )
        super().__init__(
            f"{prefix}: {decision.reason} "
            f"({decision.reason_code.value})"
        )
        self.decision = decision
        self.redirect = redirect
        self.reason_code = (
            "REDIRECT_POLICY_BLOCKED"
            if redirect
            else "OUTBOUND_POLICY_BLOCKED"
        )
        # ポリシー違反はURLを変えない限り解消しない。
        self.retryable = False


@dataclass(frozen=True)
class _EndpointRule:
    endpoint_id: str
    host: str
    path: str
    methods: frozenset[str]
    purposes: frozenset[NetworkPurpose]
    query_validator: Callable[[Sequence[tuple[str, str]]], bool]
    terminal_only: bool = False


_ASCII_DIGITS = re.compile(r"[0-9]{1,64}\Z")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


def _exact_query(expected: Mapping[str, str]) -> Callable[[Sequence[tuple[str, str]]], bool]:
    expected_items = dict(expected)

    def validate(items: Sequence[tuple[str, str]]) -> bool:
        if len(items) != len(expected_items):
            return False
        keys = [key for key, _value in items]
        if len(keys) != len(set(keys)):
            return False
        return dict(items) == expected_items

    return validate


def _numeric_query(expected_keys: frozenset[str]) -> Callable[[Sequence[tuple[str, str]]], bool]:
    def validate(items: Sequence[tuple[str, str]]) -> bool:
        keys = [key for key, _value in items]
        if len(items) != len(expected_keys) or len(keys) != len(set(keys)):
            return False
        if set(keys) != set(expected_keys):
            return False
        return all(_ASCII_DIGITS.fullmatch(value) for _key, value in items)

    return validate


class OutboundPolicy:
    """公式i-ppi endpointだけを許可する既定denyポリシー。"""

    _RULES = (
        _EndpointRule(
            "IPPI_SEARCH",
            "www.i-ppi.jp",
            "/IPPI/SearchServices/Web/Search/Search/Search.aspx",
            frozenset({"GET", "POST"}),
            frozenset({NetworkPurpose.SEARCH}),
            _exact_query({"tab": "4"}),
        ),
        _EndpointRule(
            "IPPI_GYOMU_SEARCH",
            "www.i-ppi.jp",
            "/IPPI/SearchServices/Web/Search/Search/Search.aspx",
            frozenset({"GET", "POST"}),
            frozenset({NetworkPurpose.SEARCH}),
            _exact_query({"tab": "7"}),
        ),
        _EndpointRule(
            "IPPI_AGENCY_CATALOG",
            "www.i-ppi.jp",
            "/IPPI/SearchServices/Web/Multi/SearchHachu.aspx",
            frozenset({"GET"}),
            frozenset({NetworkPurpose.STARTUP_CATALOG}),
            _exact_query({"type": "koji", "clear_flg": "false"}),
        ),
        _EndpointRule(
            "IPPI_GYOMU_AGENCY_CATALOG",
            "www.i-ppi.jp",
            "/IPPI/SearchServices/Web/Multi/SearchHachu.aspx",
            frozenset({"GET"}),
            frozenset({NetworkPurpose.STARTUP_CATALOG}),
            _exact_query({"type": "gyomu", "clear_flg": "false"}),
        ),
        _EndpointRule(
            "IPPI_PROJECT_DETAIL",
            "www.i-ppi.jp",
            "/IPPI/SearchServices/Web/Koji/Keika/List.aspx",
            frozenset({"GET", "POST"}),
            frozenset(
                {
                    NetworkPurpose.SEARCH,
                    NetworkPurpose.PAGINATION,
                    NetworkPurpose.DETAIL,
                }
            ),
            _exact_query({"tab": "4"}),
        ),
        _EndpointRule(
            "IPPI_GYOMU_PROJECT_DETAIL",
            "www.i-ppi.jp",
            "/IPPI/SearchServices/Web/Gyomu/Keika/List.aspx",
            frozenset({"GET", "POST"}),
            frozenset(
                {
                    NetworkPurpose.SEARCH,
                    NetworkPurpose.PAGINATION,
                    NetworkPurpose.DETAIL,
                }
            ),
            _exact_query({"tab": "7"}),
        ),
        _EndpointRule(
            "IPPI_DOCUMENT_LIST",
            "www.i-ppi.jp",
            "/IPPI/DownloadServices/Web/UserEntry_Download.aspx",
            frozenset({"GET"}),
            frozenset({NetworkPurpose.DOCUMENT_LIST}),
            _numeric_query(frozenset({"data1", "data2"})),
        ),
        _EndpointRule(
            "EBISC_DOCUMENT",
            "e2ppiw01.e-bisc.go.jp",
            "/CALS/Publish/KokaiBunshoServlet",
            frozenset({"GET"}),
            frozenset({NetworkPurpose.DOWNLOAD}),
            _numeric_query(frozenset({"AnkenKanriNo", "BunshoKanriId"})),
        ),
        _EndpointRule(
            "IPPI_TERMINAL_ERROR",
            "www.i-ppi.jp",
            "/information/error.htm",
            frozenset({"GET"}),
            frozenset({NetworkPurpose.ERROR}),
            _exact_query({}),
            terminal_only=True,
        ),
    )
    _rules_by_target_lists: dict[tuple[str, str], list[_EndpointRule]] = {}
    for _rule in _RULES:
        _rules_by_target_lists.setdefault(
            (_rule.host, _rule.path), []
        ).append(_rule)
    _RULES_BY_TARGET = {
        target: tuple(rules)
        for target, rules in _rules_by_target_lists.items()
    }
    del _rule, _rules_by_target_lists

    def validate(
        self,
        method: str,
        url: str,
        purpose: Optional[NetworkPurpose | str] = None,
        *,
        is_redirect: bool = False,
    ) -> NetworkPolicyDecision:
        """通信予定を検査する。判定だけを行い、送信はしない。"""

        normalized_method = str(method or "").upper()
        raw_url = str(url or "")
        normalized_purpose = self._normalize_purpose(purpose)

        if purpose not in (None, "") and normalized_purpose is None:
            return self._deny(
                NetworkPolicyReasonCode.PURPOSE_MISMATCH,
                "未定義の通信用途です",
            )

        if not raw_url or _CONTROL_CHARACTER.search(raw_url):
            return self._deny(
                NetworkPolicyReasonCode.INVALID_URL,
                "URLが空、または制御文字を含んでいます",
                purpose=normalized_purpose,
            )
        try:
            parsed = urlsplit(raw_url)
            port = parsed.port
        except (TypeError, ValueError):
            return self._deny(
                NetworkPolicyReasonCode.INVALID_URL,
                "URLを解析できません",
                purpose=normalized_purpose,
            )

        if parsed.scheme.casefold() != "https":
            return self._deny(
                NetworkPolicyReasonCode.HTTPS_REQUIRED,
                "HTTPS以外の通信は許可されていません",
                purpose=normalized_purpose,
            )
        if parsed.username is not None or parsed.password is not None:
            return self._deny(
                NetworkPolicyReasonCode.CREDENTIALS_NOT_ALLOWED,
                "URL内のユーザー情報は許可されていません",
                purpose=normalized_purpose,
            )
        if port not in (None, 443):
            return self._deny(
                NetworkPolicyReasonCode.PORT_NOT_ALLOWED,
                "HTTPSの標準ポート443以外は許可されていません",
                purpose=normalized_purpose,
            )
        if parsed.fragment:
            return self._deny(
                NetworkPolicyReasonCode.FRAGMENT_NOT_ALLOWED,
                "fragment付きURLは許可されていません",
                purpose=normalized_purpose,
            )

        host = (parsed.hostname or "").casefold()
        allowed_hosts = {rule.host for rule in self._RULES}
        if host not in allowed_hosts:
            return self._deny(
                NetworkPolicyReasonCode.HOST_NOT_ALLOWED,
                "公式ホスト以外への通信です",
                normalized_url=raw_url,
                purpose=normalized_purpose,
            )
        rules = self._RULES_BY_TARGET.get((host, parsed.path), ())
        if not rules:
            return self._deny(
                NetworkPolicyReasonCode.ENDPOINT_NOT_ALLOWED,
                "許可されていない公式サイト内pathです",
                normalized_url=raw_url,
                purpose=normalized_purpose,
            )
        try:
            query_items = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=8,
            )
        except ValueError:
            return self._deny(
                NetworkPolicyReasonCode.QUERY_NOT_ALLOWED,
                "queryを安全に解析できません",
                endpoint_id=rules[0].endpoint_id,
                normalized_url=raw_url,
                purpose=normalized_purpose,
            )
        query_rules = tuple(
            rule for rule in rules if rule.query_validator(query_items)
        )
        if not query_rules:
            return self._deny(
                NetworkPolicyReasonCode.QUERY_NOT_ALLOWED,
                f"{rules[0].endpoint_id}のquery形式が許可条件と一致しません",
                endpoint_id=rules[0].endpoint_id,
                normalized_url=raw_url,
                purpose=normalized_purpose,
            )
        method_rules = tuple(
            rule for rule in query_rules if normalized_method in rule.methods
        )
        if not method_rules:
            return self._deny(
                NetworkPolicyReasonCode.METHOD_NOT_ALLOWED,
                f"{query_rules[0].endpoint_id}では{normalized_method}を許可していません",
                endpoint_id=query_rules[0].endpoint_id,
                normalized_url=raw_url,
                purpose=normalized_purpose,
            )
        rule = method_rules[0]
        if rule.terminal_only and not is_redirect:
            return self._deny(
                NetworkPolicyReasonCode.TERMINAL_ENDPOINT_ONLY,
                "公式エラー画面はリダイレクト終端としてのみ許可されます",
                endpoint_id=rule.endpoint_id,
                normalized_url=raw_url,
                purpose=normalized_purpose,
            )
        if normalized_purpose is None:
            return self._deny(
                NetworkPolicyReasonCode.PURPOSE_MISMATCH,
                "通信用途が指定されていません",
                endpoint_id=rule.endpoint_id,
                normalized_url=raw_url,
            )
        if (
            normalized_purpose not in rule.purposes
            and not rule.terminal_only
        ):
            return self._deny(
                NetworkPolicyReasonCode.PURPOSE_MISMATCH,
                "通信用途とendpointが一致しません",
                endpoint_id=rule.endpoint_id,
                normalized_url=raw_url,
                purpose=normalized_purpose,
            )

        normalized_query = urlencode(query_items)
        normalized_netloc = host if port is None else f"{host}:{port}"
        normalized_url = urlunsplit(
            ("https", normalized_netloc, parsed.path, normalized_query, "")
        )
        inferred_purpose = normalized_purpose or min(
            rule.purposes,
            key=lambda item: item.value,
        )
        return NetworkPolicyDecision(
            True,
            rule.endpoint_id,
            normalized_url,
            NetworkPolicyReasonCode.ALLOWED,
            "許可された公式endpointです",
            inferred_purpose,
        )

    def enforce(
        self,
        method: str,
        url: str,
        purpose: Optional[NetworkPurpose | str] = None,
        *,
        is_redirect: bool = False,
    ) -> NetworkPolicyDecision:
        """拒否時に送信前例外を発生させる。"""

        decision = self.validate(
            method,
            url,
            purpose,
            is_redirect=is_redirect,
        )
        if not decision.allowed:
            raise OutboundPolicyError(decision, redirect=is_redirect)
        return decision

    @staticmethod
    def _normalize_purpose(
        purpose: Optional[NetworkPurpose | str],
    ) -> Optional[NetworkPurpose]:
        if purpose is None or purpose == "":
            return None
        if isinstance(purpose, NetworkPurpose):
            return purpose
        try:
            return NetworkPurpose(str(purpose))
        except ValueError:
            return None

    @staticmethod
    def _deny(
        reason_code: NetworkPolicyReasonCode,
        reason: str,
        *,
        endpoint_id: str = "",
        normalized_url: str = "",
        purpose: Optional[NetworkPurpose] = None,
    ) -> NetworkPolicyDecision:
        return NetworkPolicyDecision(
            False,
            endpoint_id,
            normalized_url,
            reason_code,
            reason,
            purpose,
        )


class RequestTransport(Protocol):
    """テスト用transportが実装する最小インターフェース。"""

    def __call__(
        self,
        request: requests.PreparedRequest,
        **kwargs: object,
    ) -> requests.Response: ...


class NetworkAuditCallback(Protocol):
    """通信監査sinkが実装する、機密値を渡さない呼出規約。"""

    def __call__(
        self,
        *,
        method: str,
        url: str,
        allowed: bool,
        endpoint_id: str = "",
        purpose: object = "",
        reason_code: object = "",
        is_redirect: bool = False,
        status_code: Optional[int] = None,
        phase: str = "policy",
    ) -> object: ...


class _TransportAdapter(BaseAdapter):
    def __init__(self, transport: RequestTransport) -> None:
        self._transport = transport

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: object = None,
        verify: bool = True,
        cert: object = None,
        proxies: object = None,
    ) -> requests.Response:
        response = self._transport(
            request,
            stream=stream,
            timeout=timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )
        if response.request is None:
            response.request = request
        if not response.url:
            response.url = request.url
        return response

    def close(self) -> None:
        close = getattr(self._transport, "close", None)
        if callable(close):
            close()


class PolicyEnforcedSession(requests.Session):
    """PreparedRequestの各送信直前に通信ポリシーを適用するSession。"""

    def __init__(
        self,
        policy: OutboundPolicy,
        *,
        transport: Optional[RequestTransport] = None,
        audit_callback: Optional[NetworkAuditCallback] = None,
    ) -> None:
        super().__init__()
        self.policy = policy
        self.trust_env = False
        self.max_redirects = 5
        self._request_context = threading.local()
        self._audit_callback = audit_callback
        if transport is not None:
            adapter = _TransportAdapter(transport)
            self.mount("http://", adapter)
            self.mount("https://", adapter)

    @contextmanager
    def purpose_context(self, purpose: Optional[NetworkPurpose | str]):
        """同期request呼び出しとそのredirectへ用途を引き継ぐ。"""

        missing = object()
        previous = getattr(self._request_context, "purpose", missing)
        self._request_context.purpose = purpose
        try:
            yield
        finally:
            if previous is missing:
                del self._request_context.purpose
            else:
                self._request_context.purpose = previous

    def send(
        self,
        request: requests.PreparedRequest,
        **kwargs: object,
    ) -> requests.Response:
        depth = int(getattr(self._request_context, "send_depth", 0))
        is_redirect = depth > 0
        purpose = getattr(self._request_context, "purpose", None)
        try:
            decision = self.policy.enforce(
                request.method or "",
                request.url or "",
                purpose,
                is_redirect=is_redirect,
            )
            current_origin = self._origin(decision.normalized_url)
            root_origin = getattr(self._request_context, "root_origin", None)
            if is_redirect and root_origin != current_origin:
                decision = NetworkPolicyDecision(
                    False,
                    decision.endpoint_id,
                    decision.normalized_url,
                    NetworkPolicyReasonCode.REDIRECT_ORIGIN_CHANGED,
                    "リダイレクトによるorigin変更は許可されていません",
                    decision.purpose,
                )
                raise OutboundPolicyError(decision, redirect=True)
            self._enforce_transport_settings(
                request,
                kwargs,
                decision,
                is_redirect=is_redirect,
            )
        except OutboundPolicyError as exc:
            self._emit_audit(
                exc.decision,
                request,
                is_redirect=is_redirect,
                phase="blocked",
            )
            raise

        self._emit_audit(
            decision,
            request,
            is_redirect=is_redirect,
            phase="preflight",
        )
        self._request_context.send_depth = depth + 1
        if depth == 0:
            self._request_context.root_origin = current_origin
        try:
            response = super().send(request, **kwargs)
        except OutboundPolicyError:
            # 内側のredirect hopですでに拒否監査を記録している。
            raise
        except Exception:
            self._emit_audit(
                decision,
                request,
                is_redirect=is_redirect,
                phase="transport_error",
            )
            raise
        else:
            self._emit_audit(
                decision,
                request,
                is_redirect=is_redirect,
                phase="response",
                status_code=response.status_code,
            )
            return response
        finally:
            self._request_context.send_depth = depth
            if depth == 0 and hasattr(self._request_context, "root_origin"):
                del self._request_context.root_origin

    def _emit_audit(
        self,
        decision: NetworkPolicyDecision,
        request: requests.PreparedRequest,
        *,
        is_redirect: bool,
        phase: str,
        status_code: Optional[int] = None,
    ) -> None:
        """監査障害を通信ポリシーやHTTP結果から分離する。"""

        if self._audit_callback is None:
            return
        try:
            self._audit_callback(
                method=request.method or "",
                url=request.url or "",
                allowed=decision.allowed,
                endpoint_id=decision.endpoint_id,
                purpose=decision.purpose,
                reason_code=decision.reason_code,
                is_redirect=is_redirect,
                status_code=status_code,
                phase=phase,
            )
        except Exception:
            # audit sink自体が壊れても、fail-closed判定は維持する。
            return

    def _enforce_transport_settings(
        self,
        request: requests.PreparedRequest,
        send_kwargs: Mapping[str, object],
        allowed_decision: NetworkPolicyDecision,
        *,
        is_redirect: bool,
    ) -> None:
        """proxy、TLS無効化、資格情報による間接送信を拒否する。"""

        def reject(code: NetworkPolicyReasonCode, reason: str) -> None:
            raise OutboundPolicyError(
                NetworkPolicyDecision(
                    False,
                    allowed_decision.endpoint_id,
                    allowed_decision.normalized_url,
                    code,
                    reason,
                    allowed_decision.purpose,
                ),
                redirect=is_redirect,
            )

        proxies = send_kwargs.get("proxies")
        if proxies or self.proxies:
            reject(
                NetworkPolicyReasonCode.PROXY_NOT_ALLOWED,
                "proxy経由のHTTP通信は許可されていません",
            )
        if send_kwargs.get("verify", self.verify) is not True:
            reject(
                NetworkPolicyReasonCode.TLS_VERIFY_REQUIRED,
                "既定のTLS証明書検証を無効化または変更できません",
            )
        if send_kwargs.get("cert", self.cert) is not None:
            reject(
                NetworkPolicyReasonCode.CLIENT_CERT_NOT_ALLOWED,
                "クライアント証明書は許可されていません",
            )
        if request.headers.get("Authorization") or request.headers.get(
            "Proxy-Authorization"
        ):
            reject(
                NetworkPolicyReasonCode.AUTH_NOT_ALLOWED,
                "HTTP認証情報の送信は許可されていません",
            )
        host_header = request.headers.get("Host")
        if host_header:
            parsed = urlsplit(request.url or "")
            expected_host = (parsed.hostname or "").casefold()
            if parsed.port not in (None, 443):
                expected_host = f"{expected_host}:{parsed.port}"
            if host_header.strip().casefold() != expected_host:
                reject(
                    NetworkPolicyReasonCode.HOST_HEADER_MISMATCH,
                    "Hostヘッダーと接続先が一致しません",
                )

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        parsed = urlsplit(url)
        return (
            parsed.scheme.casefold(),
            (parsed.hostname or "").casefold(),
            parsed.port or 443,
        )
