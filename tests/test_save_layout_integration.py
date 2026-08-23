# -*- coding: utf-8 -*-

"""発注機関 ON/OFF × naming_rule の保存レイアウト統合テスト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.path_builder import build_save_dir
from src.core.naming import Naming
from src.models.config_model import AppConfig, SavePaths
from src.models.file_info import FileInfo
from src.utils.logger import Logger


def _make_config(enable_agency: bool, naming_rule: str) -> AppConfig:
    return AppConfig(
        save_paths=SavePaths(
            local="./downloads",
            use_subfolders=True,
            enable_agency_root_folders=enable_agency,
        ),
        naming_rule=naming_rule,
    )


def _sample_file(koji_name: str) -> FileInfo:
    return FileInfo(
        url="https://example.com/a.pdf",
        filename="入札公告.pdf",
        file_type=".pdf",
        metadata={
            "daibunrui": "国の機関",
            "chubunrui": "国土交通省",
            "shoubunrui": "東北地方整備局",
            "saibunrui": "",
            "search_tab": "works",
            "koji_name": koji_name,
            "title": "入札公告",
            "category": "入札公告",
            "date": "2026-02-01",
        },
    )


class TestSaveLayoutIntegration:
    def test_agency_off_uses_flat_base_with_descriptive_filename(self, tmp_path):
        config = _make_config(enable_agency=False, naming_rule="{category}_{title}_{date}_{index}")
        naming = Naming(config.naming_rule, Logger())
        fi = _sample_file("桂巣トンネル外照明設備工事")

        save_dir = build_save_dir(tmp_path, fi, config)
        fname = naming.generate_filename(fi, index=0)

        assert save_dir == tmp_path
        assert "入札公告" in fname
        assert "20260201" in fname
        assert not fname.startswith("0.pdf")

    def test_agency_on_separates_koji_into_distinct_dirs(self, tmp_path):
        config = _make_config(enable_agency=True, naming_rule="{category}_{title}_{date}_{index}")
        naming = Naming(config.naming_rule, Logger())
        files = [
            _sample_file("桂巣トンネル外照明設備工事"),
            _sample_file("猪ノ鼻トンネル外照明設備工事"),
        ]

        dirs = [build_save_dir(tmp_path, fi, config) for fi in files]
        assert dirs[0] != dirs[1]
        assert "桂巣トンネル外照明設備工事" in str(dirs[0])
        assert "猪ノ鼻トンネル外照明設備工事" in str(dirs[1])

        names = [naming.generate_filename(fi, index=0) for fi in files]
        assert all("入札公告" in n for n in names)
