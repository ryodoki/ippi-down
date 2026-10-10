# -*- coding: utf-8 -*-

"""命名規則、ダウンロード条件、設定入力の回帰テスト。"""

from datetime import datetime

import pytest

from src.config.config_validator import ConfigValidator
from src.core.filter import Filter
from src.core.naming import Naming
from src.gui.settings_dialog import SettingsDialog
from src.models.config_model import AppConfig, DownloadConditions, SearchConditions
from src.models.file_info import FileInfo


class StubLogger:
    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message, exc_info=False):
        pass


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value


def make_file(metadata=None):
    return FileInfo(
        url="https://example.com/document.pdf",
        filename="document.pdf",
        file_type=".pdf",
        metadata=metadata or {},
    )


def test_naming_rule_is_used_with_metadata_and_search_conditions():
    naming = Naming(
        "{daibunrui}_{koji_name}_{title}_{index}",
        logger=StubLogger(),
        search_conditions=SearchConditions(hachu_daibunrui="国の機関"),
    )

    result = naming.generate_filename(
        make_file({"koji_name": "庁舎工事", "title": "公告/資料"}),
        index=7,
    )

    assert result == "国の機関_庁舎工事_公告_資料_7.pdf"


def test_naming_filename_placeholder_does_not_duplicate_extension():
    naming = Naming("{filename}", logger=StubLogger())

    assert naming.generate_filename(make_file()) == "document.pdf"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026年02月04日 14時22分", "入札調書_20260204_1422.pdf"),
        (
            "2026-02-04T05:22:00+00:00",
            "入札調書_20260204_1422.pdf",
        ),
        (datetime(2026, 2, 4, 14, 22), "入札調書_20260204_1422.pdf"),
    ],
)
def test_document_updated_at_is_normalized_to_jst_filename(value, expected):
    file_info = make_file(
        {
            "document_name": "入札調書",
            "document_updated_at": value,
            "document_id": "40",
        }
    )

    actual = Naming(
        "{document_name}_{document_updated_at}",
        logger=StubLogger(),
    ).generate_filename(file_info)

    assert actual == expected


def test_missing_document_updated_at_uses_document_id_not_current_time():
    file_info = FileInfo(
        url=(
            "https://example.test/KokaiBunshoServlet?"
            "AnkenKanriNo=123&BunshoKanriId=41"
        ),
        filename="document.pdf",
        file_type=".pdf",
        metadata={"document_name": "入札調書（総合評価落札方式）"},
    )

    actual = Naming(
        "{document_name}_{document_updated_at}",
        logger=StubLogger(),
    ).generate_filename(file_info)

    assert actual == "入札調書（総合評価落札方式）_更新日時不明_41.pdf"


@pytest.mark.parametrize(
    "rule",
    [
        "{unknown}_{filename}",
        "{filename",
        "{}",
    ],
)
def test_naming_rejects_unknown_or_malformed_placeholders(rule):
    with pytest.raises(ValueError):
        Naming(rule, logger=StubLogger())


def test_config_validator_reports_invalid_naming_placeholder():
    config = AppConfig(naming_rule="{unknown}")

    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is False
    assert any("未対応のプレースホルダー" in error for error in errors)


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"date": "2026-07-15"}, True),
        ({"date_公告日": "2026年7月30日"}, True),
        ({"publication_date": datetime(2026, 8, 1, 12, 0)}, False),
        ({"date": "2026-06-30"}, False),
        ({}, False),
    ],
)
def test_filter_evaluates_metadata_date_range(metadata, expected):
    conditions = DownloadConditions(
        date_range={"start": "2026-07-01", "end": "2026-07-30"}
    )
    file_filter = Filter(conditions, logger=StubLogger())

    assert file_filter.match_date_range(make_file(metadata)) is expected


def test_filter_end_date_includes_any_time_on_that_date():
    conditions = DownloadConditions(
        date_range={"start": None, "end": "2026-07-30"}
    )
    file_filter = Filter(conditions, logger=StubLogger())

    assert file_filter.match_date_range(
        make_file({"date": "2026-07-30T23:59:59+09:00"})
    )


def test_config_validator_checks_download_date_range():
    config = AppConfig(
        download_conditions=DownloadConditions(
            date_range={"start": "2026-08-01", "end": "2026-07-01"}
        )
    )

    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is False
    assert "取得日の開始日は終了日以前にしてください" in errors


def test_config_validator_checks_search_dates_and_numbers():
    config = AppConfig()
    config.search_conditions.update_date_type = "past"
    config.search_conditions.update_date_days = 0
    config.search_conditions.koukoku_date_type = "range"
    config.search_conditions.koukoku_date_start = "2026-08-01"
    config.search_conditions.koukoku_date_end = "2026-07-01"
    config.search_conditions.yotei_price_min = 200
    config.search_conditions.yotei_price_max = 100

    valid, errors = ConfigValidator(logger=StubLogger()).validate_config(config)

    assert valid is False
    assert "最終更新日の過去日数は1以上の整数で指定してください" in errors
    assert "公告日の開始日は終了日以前にしてください" in errors
    assert "予定価格の下限は上限以下にしてください" in errors


def test_settings_list_parser_normalizes_extensions_and_removes_duplicates():
    assert SettingsDialog._parse_list_setting(
        "pdf, .XLSX、pdf\n.docx", normalize_extensions=True
    ) == [".pdf", ".xlsx", ".docx"]


def test_settings_list_parser_preserves_keyword_order():
    assert SettingsDialog._parse_list_setting("道路, 橋梁,道路") == ["道路", "橋梁"]


def test_settings_preserves_search_fields_without_ui_controls():
    dialog = SettingsDialog.__new__(SettingsDialog)
    dialog._loaded_search_conditions = SearchConditions(
        hachu_shoubunrui="小分類",
        hachu_saibunrui="細分類",
        hachu_multi=["既存の複数選択"],
    )
    dialog.hachu_daibunrui_var = FakeVar("大分類")
    dialog.hachu_chubunrui_var = FakeVar("中分類")
    dialog.koji_name_var = FakeVar("工事")
    dialog.place_list_radio_var = FakeVar("list")
    dialog.place_chihou_var = FakeVar("")
    dialog.place_todofuken_var = FakeVar("")
    dialog.place_shichouson_var = FakeVar("")
    dialog.place_text_var = FakeVar("")
    dialog.contract_vars = {"一般競争入札": FakeVar(True)}
    dialog.update_date_radio_var = FakeVar("none")
    dialog.update_date_days_var = FakeVar("")
    dialog.koukoku_date_radio_var = FakeVar("none")
    dialog.koukoku_date_start_var = FakeVar("")
    dialog.koukoku_date_end_var = FakeVar("")
    dialog.kaisatsu_date_radio_var = FakeVar("none")
    dialog.kaisatsu_date_start_var = FakeVar("")
    dialog.kaisatsu_date_end_var = FakeVar("")
    dialog.keiyaku_date_radio_var = FakeVar("none")
    dialog.keiyaku_date_start_var = FakeVar("")
    dialog.keiyaku_date_end_var = FakeVar("")
    dialog.koji_shubetsu_var = FakeVar("")
    dialog.koji_gyoushu_var = FakeVar("")
    dialog.yotei_price_min_var = FakeVar("")
    dialog.yotei_price_max_var = FakeVar("")
    dialog.rakusatsu_price_min_var = FakeVar("")
    dialog.rakusatsu_price_max_var = FakeVar("")
    dialog.rakusatsu_name_var = FakeVar("")
    dialog.denshi_var = FakeVar(False)
    dialog.koukai_var = FakeVar(False)
    dialog.display_count_var = FakeVar("20")

    result = dialog.get_search_conditions_from_ui()

    assert result.hachu_shoubunrui == "小分類"
    assert result.hachu_saibunrui == "細分類"
    assert result.hachu_multi == ["既存の複数選択"]
