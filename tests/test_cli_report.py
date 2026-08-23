# -*- coding: utf-8 -*-

"""CLI の --report（JSON サマリー出力）のテスト"""

import json
import sys
from pathlib import Path

import pytest
import yaml

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.cli import main as cli_main
from src.app.run_result import RunResult
from src.models.download_result import DownloadResult

ALLOWED_URL = "https://www.i-ppi.jp/IPPI/SearchServices/Web/Search/Search/Search.aspx?tab=4"


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    body = {
        "target_urls": [ALLOWED_URL],
        "network": {"audit_log": str(tmp_path / "net.log")},
        "logging": {"level": "INFO"},
    }
    path.write_text(yaml.dump(body, allow_unicode=True), encoding="utf-8")
    return path


def run_cli(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["ippi-down-cli"] + argv)
    return cli_main.main()


def test_report_is_written_on_success(tmp_path, monkeypatch):
    config = write_config(tmp_path)
    report = tmp_path / "reports" / "batch.json"

    result = DownloadResult(total=3, success=2, failed=1, skipped=0)
    run_result = RunResult(success=True, result=result, message="done")

    monkeypatch.setattr(
        cli_main.ApplicationService, "run", lambda self, *a, **k: run_result
    )

    code = run_cli(
        monkeypatch,
        ["--config", str(config), "--once", "--report", str(report)],
    )

    assert code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["tool"] == "ippi-down"
    assert payload["success"] is True
    assert payload["dry_run"] is False
    assert payload["counts"] == {"total": 3, "success": 2, "failed": 1, "skipped": 0}
    assert payload["started_at"] <= payload["ended_at"]
    assert payload["duration_seconds"] >= 0


def test_report_is_written_on_failure(tmp_path, monkeypatch):
    config = write_config(tmp_path)
    report = tmp_path / "batch.json"

    run_result = RunResult(success=False, error="サイトに接続できませんでした")
    monkeypatch.setattr(
        cli_main.ApplicationService, "run", lambda self, *a, **k: run_result
    )

    code = run_cli(
        monkeypatch,
        ["--config", str(config), "--once", "--report", str(report)],
    )

    assert code == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["success"] is False
    assert "接続できませんでした" in payload["message"]


def test_failure_summary_only_keeps_nonzero_reasons(tmp_path, monkeypatch):
    config = write_config(tmp_path)
    report = tmp_path / "batch.json"

    result = DownloadResult(total=1, success=1, failed=0, skipped=0)
    run_result = RunResult(success=True, result=result, message="done")
    monkeypatch.setattr(
        cli_main.ApplicationService, "run", lambda self, *a, **k: run_result
    )

    run_cli(monkeypatch, ["--config", str(config), "--once", "--report", str(report)])

    payload = json.loads(report.read_text(encoding="utf-8"))
    # 全理由が 0 件なら failure_summary は空にする（監視側のノイズを減らす）
    assert payload["failure_summary"] == {}


def test_no_report_argument_writes_nothing(tmp_path, monkeypatch):
    config = write_config(tmp_path)

    result = DownloadResult(total=0, success=0, failed=0, skipped=0)
    run_result = RunResult(success=True, result=result, message="done")
    monkeypatch.setattr(
        cli_main.ApplicationService, "run", lambda self, *a, **k: run_result
    )

    code = run_cli(monkeypatch, ["--config", str(config), "--once"])

    assert code == 0
    assert not list(tmp_path.glob("**/*.json"))
