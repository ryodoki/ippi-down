# -*- coding: utf-8 -*-

"""命名テンプレートの検証と文書更新日時の正規化。"""

import re
from datetime import date, datetime, time, timedelta, timezone
from string import Formatter
from typing import Any, FrozenSet, Optional, Set


LEGACY_DEFAULT_NAMING_RULE = "{category}_{title}_{date}_{index}"
DEFAULT_NAMING_RULE = "{document_name}_{document_updated_at}"
JST = timezone(timedelta(hours=9))


ALLOWED_NAMING_PLACEHOLDERS: FrozenSet[str] = frozenset(
    {
        "filename",
        "file_type",
        "category",
        "title",
        "date",
        "index",
        "daibunrui",
        "chubunrui",
        "shoubunrui",
        "saibunrui",
        "koji_name",
        "project_name",
        "document_name",
        "document_updated_at",
        "document_id",
        "document_status",
        "document_expires_at",
        "document_section",
    }
)


_JAPANESE_DATETIME = re.compile(
    r"^\s*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日"
    r"(?:\s*[T_ ]?\s*(\d{1,2})時\s*(\d{1,2})分"
    r"(?:\s*(\d{1,2})秒)?)?\s*$"
)


def parse_document_datetime(value: Any) -> Optional[datetime]:
    """HPのJST日時、ISO 8601、``datetime``をawareなJSTへ揃える。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        text = str(value).strip().replace("　", " ")
        if not text:
            return None
        match = _JAPANESE_DATETIME.fullmatch(text)
        if match:
            year, month, day, hour, minute, second = match.groups()
            try:
                parsed = datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour or 0),
                    int(minute or 0),
                    int(second or 0),
                )
            except ValueError:
                return None
        else:
            iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
            try:
                parsed = datetime.fromisoformat(iso_text)
            except ValueError:
                parsed = None
                for pattern in (
                    "%Y/%m/%d %H:%M:%S",
                    "%Y/%m/%d %H:%M",
                    "%Y/%m/%d",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M",
                ):
                    try:
                        parsed = datetime.strptime(text, pattern)
                        break
                    except ValueError:
                        continue
                if parsed is None:
                    return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def format_document_updated_at(value: Any) -> str:
    """文書更新日時をファイル名用の``YYYYMMDD_HHmm``へ変換する。"""
    parsed = parse_document_datetime(value)
    return parsed.strftime("%Y%m%d_%H%M") if parsed is not None else ""


def document_datetime_iso(value: Any) -> str:
    """履歴保存用に文書日時をJSTのISO 8601へ変換する。"""
    parsed = parse_document_datetime(value)
    return parsed.isoformat(timespec="seconds") if parsed is not None else ""


def get_unknown_placeholders(naming_rule: str) -> Set[str]:
    """命名規則に含まれる未対応のプレースホルダーを返す。"""
    fields: Set[str] = set()
    for _, field_name, _, _ in Formatter().parse(naming_rule):
        if field_name is None:
            continue
        if not field_name:
            raise ValueError("位置引数形式の空プレースホルダーは使用できません")
        fields.add(field_name)
    return fields - ALLOWED_NAMING_PLACEHOLDERS


def validate_naming_rule(naming_rule: str) -> None:
    """命名規則の構文とプレースホルダーを検証する。"""
    if not naming_rule or not naming_rule.strip():
        raise ValueError("命名規則が空です")
    try:
        unknown = get_unknown_placeholders(naming_rule)
    except ValueError as exc:
        raise ValueError(f"命名規則の波括弧が不正です: {exc}") from exc
    if unknown:
        names = ", ".join(f"{{{name}}}" for name in sorted(unknown))
        raise ValueError(f"未対応のプレースホルダーです: {names}")
