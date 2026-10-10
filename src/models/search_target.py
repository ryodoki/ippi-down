# -*- coding: utf-8 -*-

"""i-ppiで選択できる検索対象。"""

from enum import Enum


class SearchTarget(str, Enum):
    """設定・スナップショットへ保存する安定した検索対象ID。"""

    KOJI_KEIKA = "koji_keika"
    GYOMU_KEIKA = "gyomu_keika"

    @classmethod
    def coerce(cls, value: object) -> "SearchTarget":
        if isinstance(value, cls):
            return value
        return cls(str(value or cls.KOJI_KEIKA.value).strip().lower())


__all__ = ["SearchTarget"]
