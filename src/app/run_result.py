<<<<<<< HEAD
﻿"""実行結果データモデル"""
=======
# -*- coding: utf-8 -*-

"""実行結果データモデル"""
>>>>>>> e3609c39835dfe38ae2925fb5dae86c473bfaa33

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
