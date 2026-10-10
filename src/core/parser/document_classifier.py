# -*- coding: utf-8 -*-

"""公開文書リンクをダウンロード候補へ分類する共通処理。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


_KNOWN_FILE_TYPES = {
    ".pdf",
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".rtf",
    ".zip",
}
_PUBLISH_SERVLET_PATH = "/cals/publish/kokaibunshoservlet"


@dataclass(frozen=True)
class DocumentClassification:
    """詳細ページ上の公開文書リンクの分類結果。"""

    file_type: str = ""
    allow_html_to_pdf: bool = False


def classify_document_candidate(
    url: str,
    document_name: str,
    file_types: Iterable[str],
) -> DocumentClassification:
    """URLと文書名から候補種別とHTML→PDF変換可否を判定する。"""

    allowed = {
        value.lower() if value.startswith(".") else f".{value.lower()}"
        for value in file_types
    }
    allow_html_to_pdf = (
        ".pdf" in allowed
        and is_html_bid_sheet_candidate(url, document_name)
    )

    url_suffix = Path(urlparse(url).path).suffix.lower()
    if url_suffix in _KNOWN_FILE_TYPES:
        file_type = url_suffix if url_suffix in allowed else ""
        return DocumentClassification(
            file_type=file_type,
            allow_html_to_pdf=(
                allow_html_to_pdf and file_type == ".pdf"
            ),
        )

    name_suffix = Path(document_name or "").suffix.lower()
    if name_suffix in _KNOWN_FILE_TYPES:
        file_type = name_suffix if name_suffix in allowed else ""
        return DocumentClassification(
            file_type=file_type,
            allow_html_to_pdf=(
                allow_html_to_pdf and file_type == ".pdf"
            ),
        )

    normalized_name = (document_name or "").casefold()
    keyword_groups = (
        ((".xlsx", ".xls"), ("excel", "エクセル")),
        ((".docx", ".doc"), ("word", "ワード")),
        ((".pptx", ".ppt"), ("powerpoint", "パワーポイント")),
        ((".pdf",), ("pdf",)),
        ((".rtf",), ("rtf",)),
        ((".zip",), ("zip", "圧縮")),
    )
    for extensions, keywords in keyword_groups:
        if any(keyword in normalized_name for keyword in keywords):
            file_type = next(
                (
                    extension
                    for extension in extensions
                    if extension in allowed
                ),
                "",
            )
            return DocumentClassification(
                file_type=file_type,
                allow_html_to_pdf=(
                    allow_html_to_pdf and file_type == ".pdf"
                ),
            )

    if is_known_publish_servlet(url) and ".pdf" in allowed:
        return DocumentClassification(
            file_type=".pdf",
            allow_html_to_pdf=allow_html_to_pdf,
        )

    return DocumentClassification()


def is_known_publish_servlet(url: str) -> bool:
    """信頼対象のe-bisc公開文書Servletかを判定する。"""

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    return (
        parsed.scheme.casefold() == "https"
        and (
            hostname == "e-bisc.go.jp"
            or hostname.endswith(".e-bisc.go.jp")
        )
        and parsed.path.rstrip("/").casefold() == _PUBLISH_SERVLET_PATH
    )


def is_html_bid_sheet_candidate(url: str, document_name: str) -> bool:
    """取得後にHTML→PDF変換を許可できる入札調書候補かを判定する。"""

    return (
        is_known_publish_servlet(url)
        and (document_name or "").strip().startswith("入札調書")
    )
