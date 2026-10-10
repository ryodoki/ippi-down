# -*- coding: utf-8 -*-

"""i-ppiの発注機関4階層を表すデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional, Tuple


class AgencyLevel(str, Enum):
    """「発注機関（リスト検索）」の階層。"""

    DAIBUNRUI = "daibunrui"
    CHUBUNRUI = "chubunrui"
    SHOUBUNRUI = "shoubunrui"
    SAIBUNRUI = "saibunrui"

    @property
    def depth(self) -> int:
        return _AGENCY_LEVELS.index(self)

    @property
    def next_level(self) -> Optional["AgencyLevel"]:
        next_depth = self.depth + 1
        return (
            _AGENCY_LEVELS[next_depth]
            if next_depth < len(_AGENCY_LEVELS)
            else None
        )


_AGENCY_LEVELS: Tuple[AgencyLevel, ...] = (
    AgencyLevel.DAIBUNRUI,
    AgencyLevel.CHUBUNRUI,
    AgencyLevel.SHOUBUNRUI,
    AgencyLevel.SAIBUNRUI,
)


class AgencyResolutionStatus(str, Enum):
    """案件の発注機関パスを確定した状態。"""

    SELECTED = "selected"
    DETAIL_MATCHED = "detail_matched"
    UNRESOLVED = "unresolved"


class AgencyResolutionReasonCode(str, Enum):
    """発注機関パスの確定根拠または未解決理由を表す固定コード。"""

    SELECTED = "AGENCY_SELECTED"
    OFFICE_LABEL_MATCH = "OFFICE_LABEL_MATCH"
    LEGACY_ID_MATCH = "LEGACY_ID_MATCH"
    AGENCY_SELECTION_MISSING = "AGENCY_SELECTION_MISSING"
    AGENCY_DETAIL_MISSING = "AGENCY_DETAIL_MISSING"
    AGENCY_FINE_NOT_FOUND = "AGENCY_FINE_NOT_FOUND"
    AGENCY_FINE_AMBIGUOUS = "AGENCY_FINE_AMBIGUOUS"
    AGENCY_OFFICE_CONFLICT = "AGENCY_OFFICE_CONFLICT"
    AGENCY_CATALOG_FETCH_FAILED = "AGENCY_CATALOG_FETCH_FAILED"
    PATH_INCOMPLETE = "AGENCY_PATH_INCOMPLETE"

    # 初期実装名を内部・外部コードの移行期間用aliasとして維持する。
    DETAIL_LABEL_MATCHED = OFFICE_LABEL_MATCH
    LEGACY_EXACT_ID_MATCHED = LEGACY_ID_MATCH
    NOT_SELECTED = AGENCY_SELECTION_MISSING
    DETAIL_METADATA_MISSING = AGENCY_DETAIL_MISSING
    OPTIONS_UNAVAILABLE = AGENCY_CATALOG_FETCH_FAILED
    MATCH_NOT_FOUND = AGENCY_FINE_NOT_FOUND
    MATCH_AMBIGUOUS = AGENCY_FINE_AMBIGUOUS
    OFFICE_MISMATCH = AGENCY_OFFICE_CONFLICT


class AgencyOptionSource(str, Enum):
    """発注機関候補を得た経路。"""

    MULTI_TREE = "MULTI_TREE"
    LIST_EMBEDDED = "LIST_EMBEDDED"
    POSTBACK = "POSTBACK"
    MEMORY = "MEMORY"


class AgencyOptionsErrorCode(str, Enum):
    """候補取得で利用者へ伝播できる安定したエラーコード。"""

    CANCELLED = "AGENCY_OPTIONS_CANCELLED"
    INVALID_URL = "AGENCY_OPTIONS_INVALID_URL"
    FETCH_FAILED = "AGENCY_OPTIONS_FETCH_FAILED"
    RESPONSE_URL_INVALID = "AGENCY_OPTIONS_RESPONSE_URL_INVALID"
    CONTENT_TYPE_INVALID = "AGENCY_OPTIONS_CONTENT_TYPE_INVALID"
    PAGE_INVALID = "AGENCY_OPTIONS_PAGE_INVALID"
    TREE_MISSING = "AGENCY_OPTIONS_TREE_MISSING"
    TREE_INVALID = "AGENCY_OPTIONS_TREE_INVALID"
    DUPLICATE_PATH = "AGENCY_OPTIONS_DUPLICATE_PATH"
    PARENT_NOT_FOUND = "AGENCY_OPTIONS_PARENT_NOT_FOUND"
    DROPDOWN_MISSING = "AGENCY_OPTIONS_DROPDOWN_MISSING"
    CATALOG_REFRESH_FAILED = "AGENCY_CATALOG_REFRESH_FAILED"
    SELECTION_REMOVED = "AGENCY_SELECTION_REMOVED"


@dataclass(frozen=True)
class AgencyOption:
    """サイト上の発注機関候補。

    ``parent_path`` を保持するため、同名候補でも所属する枝を失わない。
    """

    level: AgencyLevel
    code: str
    label: str
    parent_path: "AgencyPath" = field(
        default_factory=lambda: AgencyPath()
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", AgencyLevel(self.level))
        object.__setattr__(self, "code", str(self.code or "").strip())
        object.__setattr__(self, "label", str(self.label or "").strip())
        if not self.label:
            raise ValueError("発注機関候補のlabelは空にできません")
        expected_depth = len(self.parent_path.segments)
        if self.level.depth != expected_depth:
            raise ValueError(
                "発注機関候補のlevelとparent_pathが連続していません"
            )

    def to_mapping(self, *, include_parent: bool = True) -> dict[str, Any]:
        """JSONへそのまま保存できる辞書に変換する。"""

        result: dict[str, Any] = {
            "level": self.level.value,
            "code": self.code,
            "label": self.label,
        }
        if include_parent:
            result["parent_path"] = self.parent_path.to_mapping()
        return result


@dataclass(frozen=True)
class AgencyPath:
    """大分類から細分類までの、順序付き発注機関パス。"""

    segments: Tuple[AgencyOption, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(self.segments)
        object.__setattr__(self, "segments", normalized)
        if len(normalized) > len(_AGENCY_LEVELS):
            raise ValueError("発注機関パスは4階層までです")
        for depth, option in enumerate(normalized):
            if option.level is not _AGENCY_LEVELS[depth]:
                raise ValueError("発注機関パスの階層順が不正です")
            expected_parent = AgencyPath(normalized[:depth])
            if option.parent_path != expected_parent:
                raise ValueError("発注機関候補のparent_pathが不正です")

    @property
    def labels(self) -> Tuple[str, ...]:
        return tuple(segment.label for segment in self.segments)

    @property
    def codes(self) -> Tuple[str, ...]:
        return tuple(segment.code for segment in self.segments)

    @property
    def is_complete(self) -> bool:
        return len(self.segments) == len(_AGENCY_LEVELS)

    @property
    def next_level(self) -> Optional[AgencyLevel]:
        return (
            _AGENCY_LEVELS[len(self.segments)]
            if len(self.segments) < len(_AGENCY_LEVELS)
            else None
        )

    @property
    def leaf(self) -> Optional[AgencyOption]:
        return self.segments[-1] if self.segments else None

    def get(self, level: AgencyLevel) -> Optional[AgencyOption]:
        requested = AgencyLevel(level)
        return next(
            (
                segment
                for segment in self.segments
                if segment.level is requested
            ),
            None,
        )

    def append(self, option: AgencyOption) -> "AgencyPath":
        """直下の候補を追加する。同一segmentの再追加は無視する。"""

        if option.level.depth < len(self.segments):
            current = self.get(option.level)
            if (
                current is not None
                and current.code == option.code
                and current.label == option.label
            ):
                return self
            raise ValueError("同じ階層へ異なる発注機関を追加できません")
        if option.level is not self.next_level or option.parent_path != self:
            raise ValueError("発注機関候補は現在のパスの直下ではありません")
        return AgencyPath((*self.segments, option))

    def to_mapping(
        self,
        *,
        resolution: Optional["AgencyPathResolution"] = None,
    ) -> dict[str, Any]:
        """保存形式へ変換する。

        ``segments[].level`` は保存レイアウト側との契約として
        ``daibunrui/chubunrui/shoubunrui/saibunrui`` に固定する。
        """

        result: dict[str, Any] = {
            "version": 2,
            "segments": [
                segment.to_mapping(include_parent=False)
                for segment in self.segments
            ],
        }
        if resolution is not None:
            result["resolution"] = resolution.resolution_mapping()
        return result

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "AgencyPath":
        """保存済み辞書からパスを復元する。未知キーは無視する。"""

        if not isinstance(value, Mapping):
            return cls()
        raw_segments = value.get("segments", ())
        if not isinstance(raw_segments, Iterable) or isinstance(
            raw_segments, (str, bytes, Mapping)
        ):
            return cls()

        path = cls()
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, Mapping):
                raise ValueError("agency_path.segmentsの要素が辞書ではありません")
            option = AgencyOption(
                level=AgencyLevel(str(raw_segment.get("level", ""))),
                code=str(raw_segment.get("code", "") or ""),
                label=str(raw_segment.get("label", "") or ""),
                parent_path=path,
            )
            path = path.append(option)
        return path

    @classmethod
    def from_labels_and_codes(
        cls,
        labels: Iterable[str],
        codes: Iterable[str] = (),
    ) -> "AgencyPath":
        """検索条件のラベル列と解決済みコード列から構築する。"""

        label_values = list(labels)
        code_values = list(codes)
        path = cls()
        for depth, label in enumerate(label_values[: len(_AGENCY_LEVELS)]):
            clean_label = str(label or "").strip()
            if not clean_label:
                break
            code = (
                str(code_values[depth] or "").strip()
                if depth < len(code_values)
                else ""
            )
            path = path.append(
                AgencyOption(
                    level=_AGENCY_LEVELS[depth],
                    code=code,
                    label=clean_label,
                    parent_path=path,
                )
            )
        return path


AgencyPathKey = Tuple[Tuple[str, str, str], ...]


def agency_path_key(path: "AgencyPath") -> AgencyPathKey:
    """キャッシュ・カタログ用の安定したパスキーを返す。"""

    return tuple(
        (segment.level.value, segment.code, segment.label)
        for segment in path.segments
    )


@dataclass(frozen=True)
class AgencyOptionsError:
    """通信失敗と正常な0件を区別する構造化エラー。"""

    code: AgencyOptionsErrorCode
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", AgencyOptionsErrorCode(self.code))
        object.__setattr__(self, "message", str(self.message or "").strip())

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"


@dataclass(frozen=True)
class AgencyCatalogSnapshot:
    """複数選択TreeViewから作った、プロセス内だけの候補カタログ。"""

    source_url: str
    children: Mapping[AgencyPathKey, Tuple[AgencyOption, ...]] = field(
        default_factory=dict
    )
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: AgencyOptionSource = AgencyOptionSource.MULTI_TREE
    request_count: int = 0
    elapsed_seconds: float = 0.0
    error: Optional[AgencyOptionsError] = None
    generation: int = 0
    added_count: int = 0
    removed_count: int = 0

    def __post_init__(self) -> None:
        normalized = {
            tuple(key): tuple(options)
            for key, options in self.children.items()
        }
        object.__setattr__(self, "source_url", str(self.source_url or ""))
        object.__setattr__(self, "children", MappingProxyType(normalized))
        fetched_at = self.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        object.__setattr__(self, "fetched_at", fetched_at)
        object.__setattr__(self, "source", AgencyOptionSource(self.source))
        object.__setattr__(self, "request_count", max(0, int(self.request_count)))
        object.__setattr__(
            self, "elapsed_seconds", max(0.0, float(self.elapsed_seconds))
        )
        object.__setattr__(self, "generation", max(0, int(self.generation)))
        object.__setattr__(self, "added_count", max(0, int(self.added_count)))
        object.__setattr__(
            self, "removed_count", max(0, int(self.removed_count))
        )

    @property
    def is_valid(self) -> bool:
        return self.error is None and bool(self.children)

    @property
    def option_count(self) -> int:
        return sum(len(options) for options in self.children.values())

    def contains_parent(self, parent_path: Optional[AgencyPath] = None) -> bool:
        parent = parent_path or AgencyPath()
        canonical = self._canonical_path(parent)
        return canonical is not None and agency_path_key(canonical) in self.children

    def get_children(
        self, parent_path: Optional[AgencyPath] = None
    ) -> Tuple[AgencyOption, ...]:
        parent = parent_path or AgencyPath()
        canonical = self._canonical_path(parent)
        if canonical is None:
            return ()
        return self.children.get(agency_path_key(canonical), ())

    def resolve_path(
        self,
        labels: Iterable[str],
        codes: Iterable[str] = (),
    ) -> Optional[AgencyPath]:
        """表示名（必要ならコード）をカタログ上の正規パスへ解決する。"""

        label_values = [str(value or "").strip() for value in labels]
        code_values = [str(value or "").strip() for value in codes]
        path = AgencyPath()
        for depth, label in enumerate(label_values[: len(_AGENCY_LEVELS)]):
            if not label:
                break
            expected_code = code_values[depth] if depth < len(code_values) else ""
            candidates = [
                option
                for option in self.children.get(agency_path_key(path), ())
                if option.label == label
                and (not expected_code or option.code == expected_code)
            ]
            if len(candidates) != 1:
                return None
            path = path.append(candidates[0])
        return path

    def _canonical_path(self, path: AgencyPath) -> Optional[AgencyPath]:
        if not path.segments:
            return AgencyPath()
        return self.resolve_path(path.labels, path.codes)


@dataclass(frozen=True)
class AgencyOptionsResult:
    """1階層分の候補取得結果と診断情報。"""

    options: Tuple[AgencyOption, ...]
    parent_path: AgencyPath = field(default_factory=AgencyPath)
    source: Optional[AgencyOptionSource] = None
    request_count: int = 0
    elapsed_seconds: float = 0.0
    error: Optional[AgencyOptionsError] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options))
        if self.source is not None:
            object.__setattr__(self, "source", AgencyOptionSource(self.source))
        object.__setattr__(self, "request_count", max(0, int(self.request_count)))
        object.__setattr__(
            self, "elapsed_seconds", max(0.0, float(self.elapsed_seconds))
        )

    @property
    def ok(self) -> bool:
        """正常な0件を含む成功ならTrue。"""

        return self.error is None


@dataclass(frozen=True)
class AgencyPathResolution:
    """選択値と案件詳細から確定したパス、および根拠。"""

    path: AgencyPath
    status: AgencyResolutionStatus
    method: str = ""
    reason: str = ""
    office_name: str = ""
    agency_id: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", AgencyResolutionStatus(self.status)
        )
        for name in (
            "method",
            "reason",
            "office_name",
            "agency_id",
            "reason_code",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())

    @property
    def hachusha_id(self) -> str:
        """詳細ページの文書取得用HachushaId。

        ``agency_id`` は既存利用者向けの互換名であり、発注機関リストの
        細分類コードと同じ名前空間であることを意味しない。
        """

        return self.agency_id

    def resolution_mapping(self) -> dict[str, str]:
        """パス辞書内に埋め込むJSON互換の解決情報。"""

        return {
            "status": self.status.value,
            "method": self.method,
            "reason": self.reason,
            "reason_code": self.reason_code,
        }

    def to_mapping(self) -> dict[str, Any]:
        """パスと解決状態を1つの保存辞書へ変換する。"""

        return self.path.to_mapping(resolution=self)

    def to_metadata(self) -> dict[str, Any]:
        """FileInfo.metadataへ追加する安定したキーを返す。"""

        return {
            "agency_path": self.to_mapping(),
            "office_name": self.office_name,
            "agency_id": self.agency_id,
            "agency_resolution_status": self.status.value,
            "agency_resolution_reason_code": self.reason_code,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Optional[Mapping[str, Any]],
        *,
        office_name: str = "",
        agency_id: str = "",
    ) -> "AgencyPathResolution":
        path = AgencyPath.from_mapping(value)
        raw_resolution = (
            value.get("resolution", {}) if isinstance(value, Mapping) else {}
        )
        if not isinstance(raw_resolution, Mapping):
            raw_resolution = {}
        raw_status = str(raw_resolution.get("status", "") or "")
        status = (
            AgencyResolutionStatus(raw_status)
            if raw_status
            else AgencyResolutionStatus.UNRESOLVED
        )
        return cls(
            path=path,
            status=status,
            method=str(raw_resolution.get("method", "") or ""),
            reason=str(raw_resolution.get("reason", "") or ""),
            office_name=office_name,
            agency_id=agency_id,
            reason_code=str(raw_resolution.get("reason_code", "") or ""),
        )


__all__ = [
    "AgencyCatalogSnapshot",
    "AgencyLevel",
    "AgencyOption",
    "AgencyOptionSource",
    "AgencyOptionsError",
    "AgencyOptionsErrorCode",
    "AgencyOptionsResult",
    "AgencyPath",
    "AgencyPathKey",
    "AgencyPathResolution",
    "AgencyResolutionReasonCode",
    "AgencyResolutionStatus",
    "agency_path_key",
]
