# -*- coding: utf-8 -*-

"""実行結果データモデル"""

from dataclasses import dataclass
from typing import Optional
from ..models.download_result import DownloadResult, RunOutcome
from ..models.search_summary import SearchExtractionSummary


@dataclass
class RunResult:
    """アプリケーション実行結果"""
    success: bool
    result: Optional[DownloadResult] = None
    error: Optional[str] = None
    message: str = ""
    outcome: Optional[RunOutcome] = None
    search_summary: Optional[SearchExtractionSummary] = None

    def __post_init__(self):
        """旧APIのsuccessと新しいoutcomeを同期する。"""
        if self.result is not None:
            derived = self.result.outcome
            if self.outcome is None:
                self.outcome = derived
            elif self.outcome in {
                RunOutcome.SUCCESS,
                RunOutcome.PARTIAL,
            }:
                # 検索元URLの一部失敗は、ファイル結果がSUCCESSの場合だけ
                # 明示PARTIALとして表現できる。ファイル側の
                # FAILED/CANCELLED/NO_MATCHを成功系状態で上書きしない。
                if self.outcome == RunOutcome.SUCCESS or derived != RunOutcome.SUCCESS:
                    self.outcome = derived
        elif self.outcome is None:
            self.outcome = (
                RunOutcome.SUCCESS if self.success else RunOutcome.FAILED
            )
        self.success = self.outcome in {
            RunOutcome.SUCCESS,
            RunOutcome.PARTIAL,
        }


__all__ = ["RunResult", "RunOutcome"]
