# -*- coding: utf-8 -*-

"""cron スケジュールの回帰テスト（FR-016）"""

import pytest
from pathlib import Path
import sys
from datetime import datetime

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestCroniterNextRun:
    """croniter による次回実行時刻の算出"""

    def test_cron_valid_and_next_run(self):
        """有効な cron 式で次回実行時刻が算出できる"""
        from croniter import croniter

        base = datetime(2026, 2, 15, 8, 0, 0)
        cron = croniter("0 9 * * *", base)  # 毎日9時
        next_run = cron.get_next(datetime)
        assert next_run.year == 2026
        assert next_run.month == 2
        assert next_run.day == 15
        assert next_run.hour == 9
        assert next_run.minute == 0

    def test_cron_invalid_rejected(self):
        """無効な cron 式が is_valid で False になる"""
        from croniter import croniter

        assert croniter.is_valid("0 9 * * *") is True
        assert croniter.is_valid("invalid") is False
        assert croniter.is_valid("") is False


class TestSchedulerCustomCron:
    """Scheduler の custom cron 設定で無効な式が検出されること"""

    def test_schedule_custom_invalid_cron_raises(self):
        """無効な cron 式で _schedule_custom が ValueError を出す"""
        from src.scheduler.scheduler import Scheduler
        from src.models.config_model import ScheduleConfig
        from src.utils.logger import Logger, LoggingConfig

        config = ScheduleConfig(enabled=True, interval="custom", cron="not-a-cron")
        logger = Logger(LoggingConfig(level="WARNING"))
        scheduler = Scheduler(config, logger=logger)
        with pytest.raises(ValueError, match="無効なcron式"):
            scheduler._setup_schedule()
