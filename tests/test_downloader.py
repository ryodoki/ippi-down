# -*- coding: utf-8 -*-

"""Downloader の保存パス・重複スキップ等のテスト（回帰防止）"""

import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, MagicMock, patch

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.downloader import Downloader
from src.models.file_info import FileInfo
from src.models.download_result import DownloadResult
from src.core.naming import Naming
from src.models.config_model import SearchConditions
from src.utils.logger import Logger
from src.utils.http_client import HTTPClient
from src.models.config_model import LoggingConfig


class TestDownloaderSavePath:
    """保存パス組み立て（FR-012, FR-013, folder_name 反映）のテスト"""

    def test_download_files_uses_folder_name_in_path(self, tmp_path):
        """folder_name 指定時、保存先が save_dir / folder_name 以下になること"""
        mock_http = MagicMock(spec=HTTPClient)
        mock_logger = MagicMock(spec=Logger)
        downloader = Downloader(mock_http, logger=mock_logger, history_file=str(tmp_path / "history.jsonl"))

        naming = Naming(
            naming_rule="{category}_{title}_{index}",
            logger=mock_logger,
            search_conditions=SearchConditions(koji_name="工事A"),
        )
        file_info = FileInfo(
            url="https://example.com/doc.pdf",
            filename="doc.pdf",
            file_type=".pdf",
            metadata={"category": "公告", "title": "入札調書", "koji_name": "工事A"},
        )
        captured_paths = []

        def capture_download(fi, save_path, *args, **kwargs):
            captured_paths.append(save_path)
            # 成功として返す（実際には書き込まない）
            save_path_obj = Path(save_path)
            save_path_obj.parent.mkdir(parents=True, exist_ok=True)
            save_path_obj.write_bytes(b"")
            return (True, {})

        with patch.object(downloader, "download_file", side_effect=capture_download):
            with patch.object(downloader, "check_duplicate", return_value=(False, None)):
                result = downloader.download_files(
                    [file_info],
                    str(tmp_path / "base"),
                    naming,
                    folder_name="Run_202602",
                    use_subfolders=True,
                )
        assert result.total == 1
        assert len(captured_paths) == 1
        path_str = captured_paths[0]
        assert "Run_202602" in path_str
        assert "base" in path_str
        # サブフォルダ（generate_folder_name）も含まれる（工事A または その他）
        assert Path(path_str).parent.exists()

    def test_download_files_use_subfolders_false(self, tmp_path):
        """use_subfolders=False のとき、folder_name のみが付きサブフォルダが付かないこと"""
        mock_http = MagicMock(spec=HTTPClient)
        mock_logger = MagicMock(spec=Logger)
        downloader = Downloader(mock_http, logger=mock_logger, history_file=str(tmp_path / "history.jsonl"))
        naming = Naming(
            naming_rule="{index}",
            logger=mock_logger,
            search_conditions=None,
        )
        file_info = FileInfo(
            url="https://example.com/a.pdf",
            filename="a.pdf",
            file_type=".pdf",
            metadata={},
        )
        captured_paths = []

        def capture_download(fi, save_path, *args, **kwargs):
            captured_paths.append(save_path)
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            Path(save_path).write_bytes(b"")
            return (True, {})

        with patch.object(downloader, "download_file", side_effect=capture_download):
            with patch.object(downloader, "check_duplicate", return_value=(False, None)):
                downloader.download_files(
                    [file_info],
                    str(tmp_path / "save"),
                    naming,
                    folder_name="Flat",
                    use_subfolders=False,
                )
        assert len(captured_paths) == 1
        p = Path(captured_paths[0])
        assert "Flat" in str(p)
        # 親は save/Flat のみ（ファイル名以外のサブフォルダなし）
        assert p.parent.name == "Flat"
        assert p.parent.parent.name == "save"


class TestDownloaderSkipReason:
    """重複スキップ時にスキップ理由がタスクに記録されること（FR-008）"""

    def test_skipped_task_has_skip_reason(self, tmp_path):
        """check_duplicate が (True, "url") を返したとき、タスクの status と error_message に理由が入る"""
        mock_http = MagicMock(spec=HTTPClient)
        mock_logger = MagicMock(spec=Logger)
        downloader = Downloader(mock_http, logger=mock_logger, history_file=str(tmp_path / "history.jsonl"))
        naming = Naming(
            naming_rule="{index}",
            logger=mock_logger,
            search_conditions=None,
        )
        file_info = FileInfo(
            url="https://example.com/skip.pdf",
            filename="skip.pdf",
            file_type=".pdf",
            metadata={},
        )
        with patch.object(downloader, "check_duplicate", return_value=(True, "url")):
            result = downloader.download_files(
                [file_info],
                str(tmp_path / "out"),
                naming,
            )
        assert result.total == 1
        assert result.skipped == 1
        tasks = [t for t in result.tasks if t.status == "skipped"]
        assert len(tasks) == 1
        assert tasks[0].error_message == "url"

    def test_skipped_task_reason_filename_size(self, tmp_path):
        """check_duplicate が (True, "filename_size") を返したとき、error_message が filename_size"""
        mock_http = MagicMock(spec=HTTPClient)
        mock_logger = MagicMock(spec=Logger)
        downloader = Downloader(mock_http, logger=mock_logger, history_file=str(tmp_path / "history.jsonl"))
        naming = Naming(naming_rule="{index}", logger=mock_logger, search_conditions=None)
        file_info = FileInfo(url="https://example.com/a.pdf", filename="a.pdf", file_type=".pdf", metadata={})
        with patch.object(downloader, "check_duplicate", return_value=(True, "filename_size")):
            result = downloader.download_files([file_info], str(tmp_path / "out"), naming)
        assert result.skipped == 1
        skipped_task = next(t for t in result.tasks if t.status == "skipped")
        assert skipped_task.error_message == "filename_size"
