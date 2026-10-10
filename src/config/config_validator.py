# -*- coding: utf-8 -*-

"""設定検証を行うクラス"""

from datetime import date, datetime
import re
from pathlib import Path
from typing import Tuple, List
from ..models.config_model import AppConfig
from ..models.search_target import SearchTarget
from ..core.search_profiles import get_search_profile, search_profiles
from ..utils.file_utils import FileUtils
from ..utils.path_utils import resolve_verified_local_path
from ..utils.naming_template import validate_naming_rule
from ..utils.logger import Logger


class ConfigValidator:
    """設定検証を行うクラス"""

    def __init__(self, logger: Logger = None):
        """初期化"""
        self.logger = logger or Logger()

    def validate_config(self, config: AppConfig) -> Tuple[bool, List[str]]:
        """設定を検証する"""
        errors = []

        search = config.search_conditions
        profile = None
        try:
            profile = get_search_profile(search.search_target)
        except ValueError:
            errors.append(
                "検索対象はkoji_keikaまたはgyomu_keikaを指定してください"
            )

        # 対象URLの検証
        if not config.target_urls:
            errors.append("対象URLが指定されていません")
        else:
            for url in config.target_urls:
                if not self._is_valid_url(url):
                    errors.append(
                        "対象URLは公式検索URLのみ指定できます: "
                        f"{url}"
                    )
                elif profile is not None and url != profile.search_url:
                    errors.append(
                        "検索対象と対象URLが一致していません: "
                        f"{profile.target.value}"
                    )

        # 保存先の検証
        if not config.save_paths.local:
            errors.append("データルートが指定されていません")
        else:
            self._validate_local_path(
                errors,
                config.save_paths.local,
                "データルート",
            )
        if not config.logging.file:
            errors.append("ログファイルが指定されていません")
        else:
            self._validate_local_path(
                errors,
                config.logging.file,
                "ログファイル",
            )
        self._validate_save_paths(errors, config)

        # ファイルタイプの検証
        if not config.download_conditions.file_types:
            errors.append("ファイルタイプが指定されていません")

        # 取得日範囲の検証
        date_range = (
            {}
            if config.download_conditions.date_range is None
            else config.download_conditions.date_range
        )
        if not isinstance(date_range, dict):
            errors.append("取得日の範囲設定が不正です")
        else:
            start_date = self._parse_iso_date(date_range.get("start"))
            end_date = self._parse_iso_date(date_range.get("end"))
            if date_range.get("start") and start_date is None:
                errors.append("取得日の開始日はYYYY-MM-DD形式で指定してください")
            if date_range.get("end") and end_date is None:
                errors.append("取得日の終了日はYYYY-MM-DD形式で指定してください")
            if start_date and end_date and start_date > end_date:
                errors.append("取得日の開始日は終了日以前にしてください")

        # 命名規則の検証
        if not config.naming_rule:
            errors.append("命名規則が指定されていません")
        else:
            try:
                validate_naming_rule(config.naming_rule)
            except ValueError as exc:
                errors.append(f"命名規則が無効です: {exc}")

        # スケジュール設定の検証
        if config.schedule.backend not in {
            "windows_task_scheduler",
            "process",
            "legacy_process",
        }:
            errors.append("スケジュール実行方式が不正です")
        if config.schedule.timezone != "Asia/Tokyo":
            errors.append("スケジュールのタイムゾーンはAsia/Tokyoを指定してください")
        if not isinstance(config.schedule.start_when_available, bool):
            errors.append("スケジュールの実行漏れ設定は真偽値で指定してください")
        if not isinstance(config.schedule.wake_to_run, bool):
            errors.append("スケジュールのスリープ解除設定は真偽値で指定してください")
        if (
            isinstance(config.schedule.retry_count, bool)
            or not isinstance(config.schedule.retry_count, int)
            or not 0 <= config.schedule.retry_count <= 10
        ):
            errors.append("スケジュールの再試行回数は0から10の整数で指定してください")
        if (
            isinstance(config.schedule.retry_interval_minutes, bool)
            or not isinstance(config.schedule.retry_interval_minutes, int)
            or not 1 <= config.schedule.retry_interval_minutes <= 1440
        ):
            errors.append("スケジュールの再試行間隔は1から1440の整数で指定してください")
        if config.schedule.notification_policy not in {
            "off",
            "important_only",
            "all_results",
            "failures_only",
        }:
            errors.append("スケジュールの完了通知方針が不正です")
        if config.schedule.enabled:
            if config.schedule.backend != "windows_task_scheduler":
                errors.append("旧スケジュールはWindowsタスクへ移行してください")
            if config.schedule.interval == "custom":
                self.logger.warning(
                    "customスケジュールはサポート対象外のため、ジョブは登録されません"
                )
            elif config.schedule.interval not in {
                "daily",
                "weekly",
                "monthly",
            }:
                errors.append("スケジュール方式はdaily/weekly/monthlyから選択してください")
            elif not config.schedule.time:
                errors.append("スケジュール時間が指定されていません")
            else:
                try:
                    datetime.strptime(config.schedule.time, "%H:%M")
                except (TypeError, ValueError):
                    errors.append("スケジュール時間はHH:MM形式で指定してください")

        # 検索条件の検証
        if (
            search.project_name
            and search.koji_name
            and search.project_name.strip() != search.koji_name.strip()
        ):
            errors.append("案件名と旧工事名が一致していません")
        if not isinstance(search.contract_types, list):
            errors.append("入札契約方式はリストで指定してください")
        elif profile is not None:
            allowed_contracts = set(profile.default_contract_types)
            invalid_contracts = [
                value
                for value in search.contract_types
                if value not in allowed_contracts
            ]
            if invalid_contracts:
                errors.append(
                    f"{profile.display_label}で使用できない入札契約方式です: "
                    + ", ".join(str(value) for value in invalid_contracts)
                )
        if search.place_search_type not in {"list", "text"}:
            errors.append("対象地域の検索方式はlistまたはtextを指定してください")
        if profile is not None:
            if profile.target == SearchTarget.GYOMU_KEIKA and any(
                str(value or "").strip()
                for value in (search.koji_shubetsu, search.koji_gyoushu)
            ):
                errors.append("業務検索では工事種別・工事の業種を指定できません")
            if (
                profile.target == SearchTarget.KOJI_KEIKA
                and str(search.gyomu_kubun or "").strip()
            ):
                errors.append("工事検索では業務区分を指定できません")
        self._validate_hierarchy(
            errors,
            (
                ("発注機関の大分類", search.hachu_daibunrui),
                ("発注機関の中分類", search.hachu_chubunrui),
                ("発注機関の小分類", search.hachu_shoubunrui),
                ("発注機関の細分類", search.hachu_saibunrui),
            ),
        )
        if search.place_search_type == "list":
            self._validate_hierarchy(
                errors,
                (
                    ("地方", search.place_chihou),
                    ("都道府県", search.place_todofuken),
                    ("市区町村", search.place_shichouson),
                ),
            )
        if search.update_date_type not in {"none", "past"}:
            errors.append("最終更新日の指定方式が不正です")
        if search.update_date_type == "past":
            if (
                isinstance(search.update_date_days, bool)
                or not isinstance(search.update_date_days, int)
                or search.update_date_days <= 0
            ):
                errors.append("最終更新日の過去日数は1以上の整数で指定してください")

        for label, mode, start, end in (
            (
                "公告日",
                search.koukoku_date_type,
                search.koukoku_date_start,
                search.koukoku_date_end,
            ),
            (
                "開札日",
                search.kaisatsu_date_type,
                search.kaisatsu_date_start,
                search.kaisatsu_date_end,
            ),
            (
                "契約日",
                search.keiyaku_date_type,
                search.keiyaku_date_start,
                search.keiyaku_date_end,
            ),
        ):
            if mode not in {"none", "range"}:
                errors.append(f"{label}の指定方式が不正です")
                continue
            if mode == "range":
                self._validate_search_date_range(
                    errors, label, start, end
                )

        for label, minimum, maximum in (
            ("予定価格", search.yotei_price_min, search.yotei_price_max),
            (
                "落札価格／契約価格",
                search.rakusatsu_price_min,
                search.rakusatsu_price_max,
            ),
        ):
            for bound_name, value in (("下限", minimum), ("上限", maximum)):
                if value is None:
                    continue
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                ):
                    errors.append(
                        f"{label}の{bound_name}は0以上の整数で指定してください"
                    )
            if (
                isinstance(minimum, int)
                and not isinstance(minimum, bool)
                and isinstance(maximum, int)
                and not isinstance(maximum, bool)
                and minimum > maximum
            ):
                errors.append(f"{label}の下限は上限以下にしてください")

        if search.display_count not in {20, 30, 50, 100}:
            errors.append("一覧画面の表示件数は20/30/50/100から選択してください")

        return len(errors) == 0, errors

    @staticmethod
    def _validate_save_paths(errors: List[str], config: AppConfig) -> None:
        """v2互換を許容しつつ、v3/v4の各フォルダーを安全に保つ。"""

        save_paths = config.save_paths
        version = save_paths.layout_version
        if isinstance(version, bool) or version not in {2, 3, 4}:
            errors.append(
                "保存レイアウトのバージョンは2、3、4のいずれかを指定してください"
            )
            return
        if version == 2:
            return

        def validate_component(value: object, label: str) -> bool:
            text = str(value or "")
            if not text:
                errors.append(f"{label}が指定されていません")
                return False
            if (
                text in {".", ".."}
                or Path(text).is_absolute()
                or re.search(r'[\x00-\x1f<>:"/\\|?*]', text)
                or text.rstrip(" .") != text
            ):
                errors.append(f"{label}は安全な1階層のフォルダー名で指定してください")
                return False
            return True

        normal_is_valid = validate_component(
            save_paths.normal_folder,
            "通常ダウンロードフォルダー",
        )
        scheduled_is_valid = validate_component(
            save_paths.scheduled_folder,
            "定期実行フォルダー",
        )
        normal_folder = FileUtils.sanitize_path_component(
            save_paths.normal_folder
        ).casefold()
        scheduled_folder = FileUtils.sanitize_path_component(
            save_paths.scheduled_folder
        ).casefold()
        if (
            normal_is_valid
            and scheduled_is_valid
            and normal_folder == scheduled_folder
        ):
            errors.append("通常ダウンロードと定期実行のフォルダー名は分けてください")

        key = str(save_paths.schedule_storage_key or "")
        folder = str(save_paths.schedule_storage_folder or "")
        if bool(key) != bool(folder):
            errors.append("定期実行の固定保存キーとフォルダーは両方指定してください")
            return
        if not key:
            return
        if not re.fullmatch(r"S[0-9]{3,}", key):
            errors.append("定期実行の固定保存キーはS001形式で指定してください")
        validate_component(folder, "定期実行の固定保存フォルダー")
        if not folder.startswith(f"{key}_"):
            errors.append("定期実行の固定保存フォルダーは固定保存キーで始めてください")

    @staticmethod
    def _validate_hierarchy(
        errors: List[str], fields: tuple[tuple[str, object], ...]
    ) -> None:
        parent_selected = True
        for label, raw_value in fields:
            value = str(raw_value or "").strip()
            if value and not parent_selected:
                errors.append(f"{label}の上位項目を指定してください")
            parent_selected = parent_selected and bool(value)

    def _is_valid_url(self, url: str) -> bool:
        """実行対象を正規のi-ppi検索URLだけに限定する。"""

        return isinstance(url, str) and url in {
            profile.search_url for profile in search_profiles()
        }

    @staticmethod
    def _validate_local_path(
        errors: List[str],
        value: object,
        label: str,
    ) -> None:
        try:
            resolve_verified_local_path(str(value))
        except ValueError as exc:
            errors.append(f"{label}はローカルパスを指定してください: {exc}")

    @staticmethod
    def _parse_iso_date(value: object) -> date | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def _validate_search_date_range(
        self,
        errors: List[str],
        label: str,
        start: object,
        end: object,
    ) -> None:
        """検索フォームの日付範囲を検証する。"""
        start_date = self._parse_iso_date(start)
        end_date = self._parse_iso_date(end)
        if not start and not end:
            errors.append(f"{label}の期間を1つ以上指定してください")
            return
        if start and start_date is None:
            errors.append(f"{label}の開始日はYYYY-MM-DD形式で指定してください")
        if end and end_date is None:
            errors.append(f"{label}の終了日はYYYY-MM-DD形式で指定してください")
        if start_date and end_date and start_date > end_date:
            errors.append(f"{label}の開始日は終了日以前にしてください")
