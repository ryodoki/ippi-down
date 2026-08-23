# -*- coding: utf-8 -*-

"""DownloadResult サマリー拡張のテスト"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.download_result import DownloadResult
from src.models.download_task import DownloadTask
from src.models.file_info import FileInfo


def _task(url: str, status: str, local_path: str = "", error_message: str = "") -> DownloadTask:
    return DownloadTask(
        file_info=FileInfo(url=url, filename="a.pdf", file_type=".pdf"),
        local_path=local_path,
        status=status,
        error_message=error_message,
        url=url,
    )


class TestDownloadResultSummary:
    def test_summarize_skips_by_reason(self):
        result = DownloadResult(total=3)
        result.add_task(_task("u1", "skipped", error_message="url"))
        result.add_task(_task("u2", "skipped", error_message="file_exists"))
        result.add_task(_task("u3", "completed", local_path="/tmp/a.pdf"))

        summary = result.summarize_skips()
        assert summary == {"url": 1, "file_exists": 1}

    def test_get_completed_paths_limits(self):
        result = DownloadResult(total=6)
        for i in range(6):
            result.add_task(_task(f"u{i}", "completed", local_path=f"/tmp/file{i}.pdf"))

        paths = result.get_completed_paths(limit=3)
        assert len(paths) == 3
        assert paths[0] == "/tmp/file0.pdf"
