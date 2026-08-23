# -*- coding: utf-8 -*-

"""静的インバリアント: 通信経路を1か所に閉じ込めておく"""

import ast
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

SOURCE_ROOT = project_root / "src"

# requests を直接使ってよいのは共有セッションを持つこのモジュールだけ
HTTP_OWNER = "http_client.py"
SOCKET_OWNER = "netguard.py"

FORBIDDEN_MODULES = {
    "selenium",
    "playwright",
    "pycurl",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "telnetlib",
    "socketserver",
    "xmlrpc",
    "webbrowser",
}


def iter_source_modules():
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


# 例外型の参照は通信ではないので許可し、送信系の呼び出しだけを禁止する
REQUEST_SENDERS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "request",
    "Session",
    "session",
}


def test_requests_is_sent_only_by_the_http_client():
    offenders = []
    for path, tree in iter_source_modules():
        if path.name == HTTP_OWNER:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "requests"
                and node.attr in REQUEST_SENDERS
            ):
                offenders.append(f"{path.relative_to(SOURCE_ROOT)}: requests.{node.attr}")
    assert not offenders, (
        "共有セッション以外から送信しています（http_client 経由にしてください）: "
        + ", ".join(offenders)
    )


def test_socket_is_used_only_by_the_guard():
    users = sorted(
        {
            path.name
            for path, tree in iter_source_modules()
            if any(name.split(".")[0] == "socket" for name in imported_modules(tree))
        }
    )
    assert users == [SOCKET_OWNER], f"socket を直接使うモジュール: {users}"


def test_no_browser_automation_or_other_network_stacks():
    offenders = []
    for path, tree in iter_source_modules():
        for name in sorted(imported_modules(tree)):
            if name.split(".")[0] in FORBIDDEN_MODULES:
                offenders.append(f"{path.relative_to(SOURCE_ROOT)}: {name}")
    assert not offenders, "許可されていない通信手段が使われています: " + ", ".join(offenders)


def test_urllib_request_is_not_used():
    offenders = []
    for path, tree in iter_source_modules():
        for name in imported_modules(tree):
            if name.startswith("urllib.request") or name.startswith("urllib.error"):
                offenders.append(f"{path.relative_to(SOURCE_ROOT)}: {name}")
    assert not offenders, (
        "urllib による独自取得は共有セッションとガードを迂回します: " + ", ".join(offenders)
    )


def test_entry_points_install_the_guard():
    for relative in ("main.py", "cli/main.py"):
        source = (SOURCE_ROOT / relative).read_text(encoding="utf-8")
        assert "netguard.install_guard()" in source, f"{relative} でガードが有効化されていません"


def test_shell_true_is_never_used():
    offenders = []
    for path, tree in iter_source_modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    offenders.append(str(path.relative_to(SOURCE_ROOT)))
    assert not offenders, "shell=True が使われています: " + ", ".join(offenders)
