# -*- coding: utf-8 -*-

"""ダウンロードフォルダー正本仕様と実装の整合性テスト。"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from src import __version__
from src.core.naming import Naming
from src.models.config_model import SavePaths


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = PROJECT_ROOT / "docs" / "download_folder_spec.md"


def _load_spec() -> tuple[dict[str, object], str]:
    text = SPEC_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "仕様書にYAML front matterがありません"
    front_matter, separator, body = text[4:].partition("\n---\n")
    assert separator, "仕様書のYAML front matterが閉じられていません"
    metadata = yaml.safe_load(front_matter)
    assert isinstance(metadata, dict)
    return metadata, body


def test_storage_spec_metadata_matches_runtime_defaults():
    metadata, _ = _load_spec()
    defaults = SavePaths()

    assert metadata["document_id"] == "IPPI-DOWN-STORAGE"
    assert metadata["document_revision"] == "1.3"
    assert metadata["layout_version"] == defaults.layout_version
    assert metadata["applies_to"] == f"ippi-down {__version__}"
    assert str(metadata["last_updated"]) == "2026-09-11"
    assert metadata["status"] == "current"


def test_storage_spec_covers_current_observable_contract():
    _, body = _load_spec()
    defaults = SavePaths()

    required_terms = {
        defaults.normal_folder,
        defaults.scheduled_folder,
        "99_分類未解決",
        "99_区分不明",
        ".ippi-download-history.jsonl",
        ".part",
        "240",
        "SearchHachu.aspx",
        "tab=4",
        "--run-once",
        "--scheduled-run",
        "document_revision",
        "layout_version",
        "保存済みファイルを再分類...",
        "AGENCY_FINE_NOT_FOUND",
        "旧ファイルは削除せず保持",
        "RECLASSIFICATION_RUN_LOCKED",
    }
    required_terms.update(Naming.DOCUMENT_SECTION_FOLDERS.values())

    missing = sorted(term for term in required_terms if term not in body)
    assert not missing, f"正本仕様に必要な用語がありません: {missing}"


def test_storage_spec_is_linked_from_all_entry_documents():
    documents = (
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs" / "README_EXE.md",
        PROJECT_ROOT / "docs" / "requirements.md",
        PROJECT_ROOT / "docs" / "implementation_design.md",
    )

    for document in documents:
        text = document.read_text(encoding="utf-8")
        targets = re.findall(r"\[[^]]+\]\(([^)]*download_folder_spec\.md)\)", text)
        assert targets, f"正本仕様へのリンクがありません: {document.name}"
        for target in targets:
            resolved = (document.parent / target).resolve()
            assert resolved == SPEC_PATH.resolve(), (
                f"正本仕様以外を参照しています: {document.name} -> {target}"
            )
