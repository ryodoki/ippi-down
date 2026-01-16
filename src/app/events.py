"""進捗イベント定義"""

from dataclasses import dataclass
from typing import Optional, Any
from enum import Enum


class EventType(Enum):
    """イベントタイプ"""
    START = "start"
    PROGRESS = "progress"
    SUCCESS = "success"
    FAIL = "fail"
    SKIP = "skip"
    MESSAGE = "message"
    COMPLETE = "complete"


@dataclass
class ProgressEvent:
    """進捗イベント"""
    type: EventType
    message: str = ""
    current: int = 0
    total: int = 0
    file_id: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[dict] = None

    def __post_init__(self):
        """型チェック"""
        if isinstance(self.type, str):
            self.type = EventType(self.type)
