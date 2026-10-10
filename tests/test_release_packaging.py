# -*- coding: utf-8 -*-

"""配布スクリプトと配布向け文書の回帰テスト。"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def package_local_markdown_links(markdown: str) -> set[str]:
    """Return package-local Markdown link targets without anchors."""
    import re

    targets: set[str] = set()
    for target in re.findall(r"\]\(([^)]+)\)", markdown):
        target = target.strip().strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        targets.add(unquote(parsed.path).replace("\\", "/"))
    return targets


def run_powershell_script(
    script: Path, output_dir: Path
) -> subprocess.CompletedProcess:
    """配布スクリプトを隔離出力先で実行する。"""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShellが利用できない環境")
    return subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-OutputDir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def test_build_scripts_are_not_hidden_by_root_build_ignore():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/build/" in gitignore.splitlines()
    assert "build/" not in {
        line for line in gitignore.splitlines() if not line.startswith("/")
    }
    assert "!scripts/build/build.spec" in gitignore.splitlines()


def test_runtime_schedule_identity_is_ignored():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "config/schedule-instance-id" in gitignore.splitlines()
    assert "config/install-location.json" in gitignore.splitlines()


def test_setup_rejects_conda_and_resolves_project_from_script_location():
    setup_script = (PROJECT_ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")

    assert "$PSScriptRoot" in setup_script
    assert "sys.version_info.minor" in setup_script
    assert "$Info.minor -ne 11" in setup_script
    assert "(?:mini)?conda|anaconda" in setup_script
    assert "[IO.Path]::GetTempPath()" in setup_script
    assert "Move-Item -LiteralPath $ResolvedVenvDir" in setup_script
    assert "miniconda3\\python.exe" not in setup_script.lower()


@pytest.mark.parametrize(
    "relative_script",
    [
        "scripts/start_gui.ps1",
        "scripts/start_background.ps1",
        "scripts/build/build_exe.ps1",
        "scripts/build/rebuild_exe.ps1",
    ],
)
def test_entry_scripts_validate_non_conda_python311(relative_script):
    script = (PROJECT_ROOT / relative_script).read_text(encoding="utf-8")

    assert "$PSScriptRoot" in script
    assert "sys.version_info[:2] == (3, 11)" in script
    assert "'conda' not in" in script
    assert "setup.ps1" in script


@pytest.mark.parametrize(
    "relative_script",
    [
        "scripts/build/build_exe.ps1",
        "scripts/build/rebuild_exe.ps1",
    ],
)
def test_japanese_build_scripts_are_parseable_by_windows_powershell(
    relative_script,
):
    # Windows PowerShell 5.1 treats BOM-less files as the active ANSI code
    # page. A UTF-8 BOM prevents Japanese text from corrupting PowerShell
    # tokens before the build can start.
    script = (PROJECT_ROOT / relative_script).read_bytes()
    assert script.startswith(b"\xef\xbb\xbf")


def test_exe_readme_only_uses_links_available_in_package():
    readme = (PROJECT_ROOT / "docs" / "README_EXE.md").read_text(encoding="utf-8")

    # This file is copied from docs/ to the exe package root. Its local links
    # must therefore target files that are copied beside README.md.
    assert "download_folder_spec.md" in package_local_markdown_links(readme)
    assert "memory_resource_management.md" in package_local_markdown_links(readme)
    assert "network_security.md" in package_local_markdown_links(readme)

    release_script = (
        PROJECT_ROOT / "scripts" / "tools" / "make_exe_release.ps1"
    ).read_text(encoding="utf-8")
    assert r"docs\README_EXE.md" in release_script
    assert r"docs\download_folder_spec.md" in release_script
    assert r"docs\memory_resource_management.md" in release_script
    assert r"docs\network_security.md" in release_script


def test_pyinstaller_build_guide_is_canonical_and_linked():
    guide_path = PROJECT_ROOT / "docs" / "pyinstaller_build.md"
    guide = guide_path.read_text(encoding="utf-8")

    required_fragments = (
        "Windows 10/11",
        "Python 3.11",
        "Tcl/Tk",
        "Conda",
        r".\scripts\setup.ps1 -WithBuild",
        r".\scripts\build\build_exe.ps1",
        r"scripts\build\build.spec",
        "requirements/windows-ci-py311.lock",
        "--require-hashes",
        "pip check",
        "generate_sbom.py",
        "compileall",
        "Ruff",
        "pytest",
        "--self-check",
        "make_source_release.ps1",
        "make_exe_release.ps1",
        "SHA-256",
        "run_offline_self_check.ps1",
        "build\\",
        "dist\\",
    )
    for fragment in required_fragments:
        assert fragment in guide, fragment

    expected_links = {
        "README.md": "docs/pyinstaller_build.md",
        "docs/DEPLOYMENT.md": "pyinstaller_build.md",
        "docs/technology_selection.md": "pyinstaller_build.md",
        "docs/requirements.md": "pyinstaller_build.md",
        "docs/system_design.md": "pyinstaller_build.md",
    }
    for relative_document, expected_target in expected_links.items():
        document_path = PROJECT_ROOT / relative_document
        links = package_local_markdown_links(document_path.read_text(encoding="utf-8"))
        assert expected_target in links, relative_document
        assert (document_path.parent / expected_target).is_file()


def test_schedule_ownership_and_explicit_migration_are_documented():
    documents = {
        relative: (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "README.md",
            "docs/README_EXE.md",
            "docs/requirements.md",
            "docs/implementation_design.md",
            "docs/system_design.md",
        )
    }

    for relative in ("README.md", "docs/README_EXE.md"):
        document = documents[relative]
        assert "config/schedule-instance-id" in document
        assert r"%LOCALAPPDATA%\ippi-down\install-id" in document
        assert "task namespace ID" in document
        assert "coordination ID" in document
        assert "旧設定を取り込む" in document
        assert "MIGRATED_OUT" in document
        assert "孤立タスク" in document
        assert "管理外の旧Windowsタスク" in document
        assert "管理外の旧タスク" in document
        assert "選択した外部タスクを解除" in document
        assert "一意な名前" in document
        assert "EXTERNAL_TASK_CLEANUP_PENDING" in document

    combined = "\n".join(documents.values())
    assert r"\ippi-down\Download-<task-namespace-id>-<schedule-id>" in combined
    assert r"\ippi-down\Download-<install-id>-<schedule-id>" not in combined
    assert "exe単体" in combined
    assert "旧タスクを無効化" in combined
    assert "旧タスクを削除" in combined
    assert "削除失敗時は旧タスクの無効状態を維持" in combined
    assert "取得済み文書と履歴" in combined
    assert "EXTERNAL_HISTORY_IMPORT_FAILED" in combined
    assert "preview_external_imports()" in documents["docs/implementation_design.md"]
    assert "import_external_schedule()" in documents["docs/implementation_design.md"]
    assert "remove_external_task()" in documents["docs/implementation_design.md"]

    memory_spec = (PROJECT_ROOT / "docs" / "memory_resource_management.md").read_text(
        encoding="utf-8"
    )
    assert "coordination ID" in memory_spec
    assert "task namespace ID" in memory_spec
    assert r"%LOCALAPPDATA%\ippi-down\install-id" in memory_spec

    folder_spec = (PROJECT_ROOT / "docs" / "download_folder_spec.md").read_text(
        encoding="utf-8"
    )
    assert "別配置から明示的に取り込む場合" in folder_spec
    assert "固定保存キー、保存フォルダーを引き継ぎます" in folder_spec


def test_source_release_keeps_fixtures_and_excludes_runtime_artifacts(tmp_path):
    script = PROJECT_ROOT / "scripts" / "tools" / "make_source_release.ps1"
    completed = run_powershell_script(script, tmp_path)
    assert completed.returncode == 0, completed.stderr or completed.stdout

    archive = tmp_path / "ippi-down-source.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())

    assert "ippi-down-source/scripts/build/build.spec" in names
    assert "ippi-down-source/tests/fixtures/test_detail_page.html" in names
    assert "ippi-down-source/tests/fixtures/id40_bid_sheet.html" in names
    assert "ippi-down-source/tests/fixtures/id41_pdf_response.json" in names
    assert "ippi-down-source/src/resources/self_check_bid_sheet.html" in names
    assert "ippi-down-source/README.md" in names
    assert "ippi-down-source/docs/download_folder_spec.md" in names
    assert "ippi-down-source/docs/pyinstaller_build.md" in names
    assert "ippi-down-source/requirements/runtime.txt" in names

    forbidden_top_level = {
        ".agents",
        ".codex",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "artifacts",
        "build",
        "debug",
        "dist",
        "downloads",
        "logs",
        "release",
    }
    for name in names:
        parts = Path(name).parts
        relative_parts = parts[1:]
        if relative_parts:
            assert relative_parts[0] not in forbidden_top_level, name
        assert "__pycache__" not in relative_parts, name
        assert not name.endswith(
            (
                ".exe",
                ".log",
                ".part",
                ".pyc",
                ".pyo",
                ".pdf",
                ".doc",
                ".docx",
                ".xls",
                ".xlsx",
                ".ppt",
                ".pptx",
                ".rtf",
            )
        ), name
        assert not name.endswith("/config/config.yaml"), name


def test_source_release_excludes_secret_like_files_without_false_positive(
    tmp_path,
):
    isolated_root = tmp_path / "project"
    (isolated_root / "scripts" / "tools").mkdir(parents=True)
    (isolated_root / "src" / "utils").mkdir(parents=True)
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "tools" / "make_source_release.ps1",
        isolated_root / "scripts" / "tools" / "make_source_release.ps1",
    )
    (isolated_root / ".env.production").write_text("TOKEN=real-value", encoding="utf-8")
    (isolated_root / "credentials.json").write_text(
        '{"token": "real-value"}', encoding="utf-8"
    )
    (isolated_root / "private.pem").write_text("private material", encoding="utf-8")
    (isolated_root / "self-check-result.txt").write_text(
        "diagnostic output", encoding="utf-8"
    )
    (isolated_root / "captured-document.pdf").write_bytes(b"%PDF-downloaded-document")
    (isolated_root / "config" / "schedule-profiles").mkdir(parents=True)
    (isolated_root / "config" / "install-id").write_text(
        "local-install", encoding="utf-8"
    )
    (isolated_root / "config" / "schedule-instance-id").write_text(
        "local-task-namespace", encoding="utf-8"
    )
    (isolated_root / "config" / "install-location.json").write_text(
        '{"app_root": "C:/private/path"}', encoding="utf-8"
    )
    (isolated_root / "config" / "installation-relocation-journal.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (isolated_root / "config" / "schedule-registration.json").write_text(
        '{"task_name": "local-task"}', encoding="utf-8"
    )
    (isolated_root / "config" / "schedule-profiles" / "local-profile.yaml").write_text(
        "search_conditions: {}\n", encoding="utf-8"
    )
    (isolated_root / "src" / "utils" / "secret_provider.py").write_text(
        "class SecretProvider: pass\n", encoding="utf-8"
    )

    output_dir = tmp_path / "output"
    completed = run_powershell_script(
        isolated_root / "scripts" / "tools" / "make_source_release.ps1",
        output_dir,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    with zipfile.ZipFile(output_dir / "ippi-down-source.zip") as package:
        names = set(package.namelist())

    assert "ippi-down-source/.env.production" not in names
    assert "ippi-down-source/credentials.json" not in names
    assert "ippi-down-source/private.pem" not in names
    assert "ippi-down-source/self-check-result.txt" not in names
    assert "ippi-down-source/captured-document.pdf" not in names
    assert "ippi-down-source/config/install-id" not in names
    assert "ippi-down-source/config/install-location.json" not in names
    assert "ippi-down-source/config/installation-relocation-journal.json" not in names
    assert "ippi-down-source/config/schedule-instance-id" not in names
    assert "ippi-down-source/config/schedule-registration.json" not in names
    assert not any("/schedule-profiles/" in name for name in names)
    assert "ippi-down-source/src/utils/secret_provider.py" in names


def test_exe_release_uses_exact_safe_manifest(tmp_path):
    isolated_root = tmp_path / "project"
    for relative_dir in (
        "config",
        "dist",
        "docs",
        "scripts/tools",
        "src/resources/fonts",
    ):
        (isolated_root / relative_dir).mkdir(parents=True, exist_ok=True)

    shutil.copy2(
        PROJECT_ROOT / "scripts" / "tools" / "make_exe_release.ps1",
        isolated_root / "scripts" / "tools" / "make_exe_release.ps1",
    )
    shutil.copy2(
        PROJECT_ROOT / "config" / "config.example.yaml",
        isolated_root / "config" / "config.example.yaml",
    )
    shutil.copy2(
        PROJECT_ROOT / "docs" / "README_EXE.md",
        isolated_root / "docs" / "README_EXE.md",
    )
    canonical_spec = b"# canonical download folder specification\n"
    (isolated_root / "docs" / "download_folder_spec.md").write_bytes(canonical_spec)
    canonical_memory_spec = b"# canonical memory resource specification\n"
    (isolated_root / "docs" / "memory_resource_management.md").write_bytes(
        canonical_memory_spec
    )
    canonical_network_spec = b"# canonical network security specification\n"
    (isolated_root / "docs" / "network_security.md").write_bytes(canonical_network_spec)
    canonical_pdf_spec = b"# canonical PDF conversion specification\n"
    (isolated_root / "docs" / "pdf_conversion_reliability.md").write_bytes(
        canonical_pdf_spec
    )
    shutil.copy2(
        PROJECT_ROOT / "THIRD_PARTY_NOTICES.txt",
        isolated_root / "THIRD_PARTY_NOTICES.txt",
    )
    shutil.copy2(
        PROJECT_ROOT / "src" / "resources" / "fonts" / "OFL-1.1.txt",
        isolated_root / "src" / "resources" / "fonts" / "OFL-1.1.txt",
    )
    # The packaging script only requires an existing file. A tiny PE-like
    # fixture is sufficient because this test verifies the archive manifest.
    (isolated_root / "dist" / "ippi-down.exe").write_bytes(b"MZ\0\0fixture")

    output_dir = tmp_path / "output"
    completed = run_powershell_script(
        isolated_root / "scripts" / "tools" / "make_exe_release.ps1",
        output_dir,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    archive = output_dir / "ippi-down-windows-x64.zip"
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        packaged_readme = package.read("ippi-down/README.md").decode("utf-8")
        packaged_spec = package.read("ippi-down/download_folder_spec.md")
        packaged_memory_spec = package.read("ippi-down/memory_resource_management.md")
        packaged_network_spec = package.read("ippi-down/network_security.md")
        packaged_pdf_spec = package.read("ippi-down/pdf_conversion_reliability.md")

    assert names == {
        "ippi-down/config/config.example.yaml",
        "ippi-down/ippi-down.exe",
        "ippi-down/README.md",
        "ippi-down/download_folder_spec.md",
        "ippi-down/memory_resource_management.md",
        "ippi-down/network_security.md",
        "ippi-down/pdf_conversion_reliability.md",
        "ippi-down/THIRD_PARTY_NOTICES.txt",
        "ippi-down/OFL-1.1.txt",
        "ippi-down/SHA256SUMS.txt",
    }
    assert "ippi-down/pyinstaller_build.md" not in names
    assert packaged_spec == canonical_spec
    assert packaged_memory_spec == canonical_memory_spec
    assert packaged_network_spec == canonical_network_spec
    assert packaged_pdf_spec == canonical_pdf_spec
    for target in package_local_markdown_links(packaged_readme):
        assert f"ippi-down/{target}" in names
