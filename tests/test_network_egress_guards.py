# -*- coding: utf-8 -*-

"""標準テストの通信遮断とHTTP実装境界を検証する。"""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest


def test_default_test_suite_blocks_dns_and_socket_connections():
    with pytest.raises(AssertionError, match="実ネットワーク通信は禁止"):
        socket.getaddrinfo("www.i-ppi.jp", 443)

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(AssertionError, match="実ネットワーク通信は禁止"):
            probe.connect(("127.0.0.1", 9))
    finally:
        probe.close()


def test_runtime_network_transports_are_confined_to_http_boundary():
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src"
    allowed = {
        (source_root / "utils" / "http_client.py").resolve(),
        (source_root / "utils" / "outbound_policy.py").resolve(),
    }
    forbidden_roots = {
        "requests",
        "httpx",
        "aiohttp",
        "socket",
        "ftplib",
        "smtplib",
        "websocket",
    }
    forbidden_imports: list[str] = []

    for source_path in source_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for module_name in imported:
                root_name = module_name.split(".", 1)[0]
                if (
                    root_name in forbidden_roots
                    and source_path.resolve() not in allowed
                ):
                    forbidden_imports.append(
                        f"{source_path.relative_to(project_root)}:{node.lineno} "
                        f"{module_name}"
                    )

    assert forbidden_imports == []


def test_runtime_http_calls_declare_network_purpose():
    project_root = Path(__file__).resolve().parents[1]
    missing: list[str] = []

    for source_path in (project_root / "src" / "core").rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute):
                continue
            if function.attr not in {"get", "post"}:
                continue
            owner = function.value
            if not (
                isinstance(owner, ast.Attribute)
                and owner.attr == "http_client"
            ):
                continue
            if not any(keyword.arg == "purpose" for keyword in node.keywords):
                missing.append(
                    f"{source_path.relative_to(project_root)}:{node.lineno}"
                )

    assert missing == []
