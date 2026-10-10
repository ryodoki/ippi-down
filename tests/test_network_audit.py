# -*- coding: utf-8 -*-

"""外向き通信監査ログの安全性と障害分離。"""

from __future__ import annotations

import json

from src.utils.network_audit import NetworkAuditLedger


def test_network_audit_does_not_store_query_values_or_userinfo(tmp_path):
    path = tmp_path / "network-audit.jsonl"
    ledger = NetworkAuditLedger(path)

    assert ledger.record(
        method="GET",
        url=(
            "https://user:password@e2ppiw01.e-bisc.go.jp/"
            "CALS/Publish/KokaiBunshoServlet?"
            "AnkenKanriNo=SECRET-CASE&BunshoKanriId=40#private"
        ),
        allowed=False,
        endpoint_id="EBISC_DOCUMENT",
        purpose="DOWNLOAD",
        reason_code="CREDENTIALS_NOT_ALLOWED",
    )

    raw = path.read_text(encoding="utf-8")
    assert "SECRET-CASE" not in raw
    assert "password" not in raw
    assert "private" not in raw
    payload = json.loads(raw)
    assert payload["host"] == "e2ppiw01.e-bisc.go.jp"
    assert payload["path"] == "/CALS/Publish/KokaiBunshoServlet"
    assert payload["query_names"] == ["AnkenKanriNo", "BunshoKanriId"]
    assert payload["allowed"] is False


def test_network_audit_rotates_bounded_jsonl(tmp_path):
    path = tmp_path / "network-audit.jsonl"
    ledger = NetworkAuditLedger(path, max_bytes=1024, backup_count=2)

    for _index in range(20):
        assert ledger.record(
            method="GET",
            url=(
                "https://www.i-ppi.jp/IPPI/SearchServices/Web/"
                "Search/Search/Search.aspx?tab=4"
            ),
            allowed=True,
            endpoint_id="IPPI_SEARCH",
            purpose="SEARCH",
            reason_code="ALLOWED",
        )

    assert path.exists()
    assert path.with_name("network-audit.jsonl.1").exists()
    assert not path.with_name("network-audit.jsonl.3").exists()


def test_network_audit_write_failure_does_not_escape(tmp_path, monkeypatch):
    # ファイルではなく既存directoryを渡してopenを失敗させる。
    ledger = NetworkAuditLedger(tmp_path)
    warnings: list[str] = []
    monkeypatch.setattr(ledger, "_warn", warnings.append)

    assert not ledger.record(
        method="GET",
        url="https://www.i-ppi.jp/information/error.htm",
        allowed=False,
        reason_code="TERMINAL_ENDPOINT_ONLY",
    )
    assert any("通信監査ログを保存できません" in item for item in warnings)


def test_network_audit_rejects_remote_path_without_writing(
    tmp_path,
    monkeypatch,
):
    ledger = NetworkAuditLedger(tmp_path / "network-audit.jsonl")
    warnings: list[str] = []
    monkeypatch.setattr(ledger, "_warn", warnings.append)
    monkeypatch.setattr(
        "src.utils.network_audit.resolve_verified_local_path",
        lambda _path: (_ for _ in ()).throw(
            ValueError("ネットワークドライブは使用できません")
        ),
    )

    assert not ledger.record(
        method="GET",
        url="https://www.i-ppi.jp/information/error.htm",
        allowed=False,
    )
    assert not (tmp_path / "network-audit.jsonl").exists()
    assert any("ネットワークドライブ" in item for item in warnings)


def test_network_audit_redacts_attacker_controlled_unknown_path(tmp_path):
    path = tmp_path / "network-audit.jsonl"
    ledger = NetworkAuditLedger(path)

    assert ledger.record(
        method="GET",
        url="https://attacker.example/private/TOP-SECRET",
        allowed=False,
        reason_code="HOST_NOT_ALLOWED",
    )

    raw = path.read_text(encoding="utf-8")
    assert "TOP-SECRET" not in raw
    assert json.loads(raw)["path"] == "<blocked>"
