# -*- coding: utf-8 -*-

"""CI依存lockとSBOM生成の回帰テスト。"""

from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "requirements" / "windows-ci-py311.lock"


def _load_sbom_module():
    path = PROJECT_ROOT / "scripts" / "security" / "generate_sbom.py"
    spec = importlib.util.spec_from_file_location("generate_sbom", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_ci_lock_is_exact_and_hash_pinned():
    module = _load_sbom_module()

    components = module.read_lock(LOCK_PATH)

    assert len(components) >= 20
    assert {item["name"] for item in components} >= {
        "requests",
        "pyyaml",
        "pytest",
        "ruff",
        "pyinstaller",
    }
    assert all(len(item["hash"]) == 64 for item in components)

    constraint_versions: dict[str, str] = {}
    for raw in (
        PROJECT_ROOT / "requirements" / "constraints.txt"
    ).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        constraint_versions[name.replace("_", "-").casefold()] = version
    assert all(
        constraint_versions.get(item["name"]) == item["version"]
        for item in components
    )


def test_sbom_contains_lock_hashes_without_runtime_secrets():
    module = _load_sbom_module()

    document = module.build_sbom(LOCK_PATH)

    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.5"
    components = document["components"]
    assert len(components) == len(module.read_lock(LOCK_PATH))
    assert all(item["purl"].startswith("pkg:pypi/") for item in components)
    assert all(item["hashes"][0]["alg"] == "SHA-256" for item in components)


def test_offline_self_check_firewall_rules_are_scoped_and_always_removed():
    script = (
        PROJECT_ROOT / "scripts" / "security" / "run_offline_self_check.ps1"
    ).read_text(encoding="utf-8")

    assert "[guid]::NewGuid()" in script
    assert "-Direction Outbound" in script
    assert "-Action Block" in script
    assert "-Program $Programs[$Index]" in script
    assert "finally" in script
    assert "Remove-NetFirewallRule -Name $RuleName" in script
    assert "Remove-NetFirewallRule -DisplayName" not in script
