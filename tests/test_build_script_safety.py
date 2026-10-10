# -*- coding: utf-8 -*-

"""PyInstallerビルドが実行用distの利用者データを削除しないことを固定する。"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPTS = (
    PROJECT_ROOT / "scripts" / "build" / "build_exe.ps1",
    PROJECT_ROOT / "scripts" / "build" / "build_exe.bat",
    PROJECT_ROOT / "scripts" / "build" / "rebuild_exe.ps1",
    PROJECT_ROOT / "scripts" / "build" / "rebuild_exe.bat",
)
PRIMARY_BUILD_SCRIPTS = BUILD_SCRIPTS[:2]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("script", BUILD_SCRIPTS, ids=lambda path: path.name)
def test_build_scripts_never_delete_dist_directory(script: Path):
    """distへの再帰削除・ファイル一括削除を再導入させない。"""

    text = _text(script)
    destructive_patterns = (
        r"(?im)^\s*Remove-Item\b[^\r\n]*(?:\$DistDir|[\\/]?dist(?:[\\/]|\b))",
        r"(?im)^\s*(?:rmdir|rd)\b[^\r\n]*(?:%DIST_DIR%|[\\/]?dist(?:[\\/]|\b))",
        r"(?im)^\s*del\b[^\r\n]*(?:%DIST_DIR%|[\\/]?dist(?:[\\/]|\b))",
    )

    assert not any(re.search(pattern, text) for pattern in destructive_patterns)


@pytest.mark.parametrize(
    "script",
    PRIMARY_BUILD_SCRIPTS,
    ids=lambda path: path.name,
)
def test_primary_builds_stage_validate_and_atomically_replace_only_exe(
    script: Path,
):
    text = _text(script)
    lower = text.lower()

    assert "staged-dist" in lower
    assert "--workpath" in lower
    assert "--distpath" in lower
    assert "os.replace" in lower
    assert "ippi-down.exe" in lower
    assert (
        "b'mz'" in lower
        or 'b"mz"' in lower
        or "bytes((77, 90))" in lower
    )
    assert "旧exe" in text
    assert all(term in lower for term in ("config", "downloads", "logs"))


def test_rebuild_scripts_delegate_to_safe_primary_build_after_pip():
    powershell = _text(BUILD_SCRIPTS[2]).lower()
    batch = _text(BUILD_SCRIPTS[3]).lower()

    assert "pip install" in powershell
    assert "build_exe.ps1" in powershell
    assert "pip install" in batch
    assert "build_exe.bat" in batch


def test_powershell_validation_reads_only_signature_bytes():
    text = _text(BUILD_SCRIPTS[0])

    assert (
        "with path.open(\"rb\") as stream:" in text
        or "with path.open(mode=chr(114) + chr(98)) as stream:" in text
    )
    assert "signature = stream.read(2)" in text
    assert "read_bytes()" not in text


@pytest.mark.parametrize(
    "script",
    (BUILD_SCRIPTS[0], BUILD_SCRIPTS[2]),
    ids=lambda path: path.name,
)
def test_powershell_build_scripts_parse_without_execution(script: Path):
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell parserを利用できません")
    escaped_path = str(script).replace("'", "''")
    command = (
        "$tokens = $null; $errors = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{escaped_path}', [ref]$tokens, [ref]$errors) > $null; "
        "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }"
    )

    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_build_guide_documents_safe_dist_contract():
    text = (PROJECT_ROOT / "docs" / "pyinstaller_build.md").read_text(
        encoding="utf-8"
    )

    required = (
        "`build\\`だけを削除",
        "`build\\staged-dist\\ippi-down.exe`",
        "原子的に置換",
        "`dist\\`自体",
        "従来の`dist\\ippi-down.exe`を保持",
        "`dist\\ippi-down.exe`を置換できない",
    )
    missing = [term for term in required if term not in text]
    assert not missing, f"安全なビルド説明が不足しています: {missing}"
