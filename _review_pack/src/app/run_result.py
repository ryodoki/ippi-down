# -*- coding: utf-8 -*-

"""実行結果データモデル"""

from dataclasses import dataclass
from typing import Optional
from ..models.download_result import DownloadResult


@dataclass
class RunResult:
    """アプリケーション実行結果"""
    success: bool
    result: Optional[DownloadResult] = None
    error: Optional[str] = None
    message: str = ""
