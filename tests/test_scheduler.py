# -*- coding: utf-8 -*-

from src.models.config_model import ScheduleConfig
from src.scheduler.scheduler import Scheduler
from threading import Event


class StubLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


def test_weekly_schedule_uses_configured_weekday():
    scheduler = Scheduler(
        ScheduleConfig(
            enabled=True,
            interval="weekly",
            time="10:30",
            weekday="friday",
        ),
        StubLogger(),
    )

    scheduler._setup_schedule()

    assert len(scheduler._scheduler.jobs) == 1
    assert scheduler._scheduler.jobs[0].start_day == "friday"
    assert scheduler.get_next_run_time() is not None


def test_monthly_schedule_uses_daily_guard():
    scheduler = Scheduler(
        ScheduleConfig(
            enabled=True,
            interval="monthly",
            time="08:15",
            day_of_month=28,
        ),
        StubLogger(),
    )

    scheduler._setup_schedule()

    assert len(scheduler._scheduler.jobs) == 1
    assert scheduler._scheduler.jobs[0].at_time.hour == 8
    assert scheduler._scheduler.jobs[0].at_time.minute == 15


def test_custom_schedule_is_disabled_with_warning():
    logger = StubLogger()
    scheduler = Scheduler(
        ScheduleConfig(
            enabled=True,
            interval="custom",
            cron="0 9 * * *",
        ),
        logger,
    )

    assert scheduler.start() is False
    assert scheduler._scheduler.jobs == []
    assert any(level == "warning" for level, _ in logger.messages)


def test_reconfigure_disabled_clears_jobs():
    scheduler = Scheduler(
        ScheduleConfig(enabled=True, interval="daily", time="09:00"),
        StubLogger(),
    )
    scheduler._setup_schedule()
    assert scheduler._scheduler.jobs

    result = scheduler.reconfigure(ScheduleConfig(enabled=False))

    assert result is False
    assert scheduler.config.enabled is False
    assert scheduler._scheduler.jobs == []


def test_scheduled_callback_runs_outside_scheduler_loop():
    completed = Event()
    scheduler = Scheduler(ScheduleConfig(), StubLogger())
    scheduler.set_download_callback(completed.set)

    scheduler._execute_download()

    assert completed.wait(1)
