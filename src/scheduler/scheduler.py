# -*- coding: utf-8 -*-

"""定期実行管理を行うクラス"""

import schedule
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable
from ..utils.logger import Logger
from ..models.config_model import ScheduleConfig


class Scheduler:
    """定期実行管理を行うクラス"""

    def __init__(self, config: ScheduleConfig, logger: Optional[Logger] = None):
        """初期化"""
        self.config = config
        self.logger = logger or Logger()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.download_callback: Optional[Callable] = None

    def set_download_callback(self, callback: Callable):
        """ダウンロードコールバックを設定"""
        self.download_callback = callback

    def start(self):
        """スケジューラーを開始"""
        if not self.config.enabled:
            self.logger.info("スケジュール機能は無効です")
            return

        if self.running:
            self.logger.warning("スケジューラーは既に実行中です")
            return

        # スケジュールを設定
        self._setup_schedule()

        # バックグラウンドスレッドで実行
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        self.logger.info("スケジューラーを開始しました")

    def stop(self):
        """スケジューラーを停止"""
        self.running = False
        schedule.clear()
        self.logger.info("スケジューラーを停止しました")

    def _setup_schedule(self):
        """スケジュールを設定"""
        schedule.clear()

        if self.config.interval == "daily":
            # 毎日実行
            self._schedule_daily()
        elif self.config.interval == "weekly":
            # 毎週実行
            self._schedule_weekly()
        elif self.config.interval == "monthly":
            # 毎月実行
            self._schedule_monthly()
        elif self.config.interval == "custom" and self.config.cron:
            # カスタム（cron形式）
            self._schedule_custom()

    def _schedule_daily(self):
        """毎日のスケジュールを設定"""
        try:
            hour, minute = map(int, self.config.time.split(":"))
            schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(self._execute_download)
            self.logger.info(f"毎日 {self.config.time} に実行するように設定しました")
        except Exception as e:
            self.logger.error(f"スケジュール設定エラー: {str(e)}")

    def _schedule_weekly(self):
        """毎週のスケジュールを設定"""
        try:
            hour, minute = map(int, self.config.time.split(":"))
            # 毎週月曜日に実行（必要に応じて変更可能）
            schedule.every().monday.at(f"{hour:02d}:{minute:02d}").do(self._execute_download)
            self.logger.info(f"毎週月曜日 {self.config.time} に実行するように設定しました")
        except Exception as e:
            self.logger.error(f"スケジュール設定エラー: {str(e)}")

    def _schedule_monthly(self):
        """毎月のスケジュールを設定"""
        try:
            hour, minute = map(int, self.config.time.split(":"))
            # 毎月1日に実行
            def monthly_job():
                today = datetime.now()
                if today.day == 1:
                    self._execute_download()

            schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(monthly_job)
            self.logger.info(f"毎月1日 {self.config.time} に実行するように設定しました")
        except Exception as e:
            self.logger.error(f"スケジュール設定エラー: {str(e)}")

    def _schedule_custom(self):
        """カスタム（cron形式）のスケジュールを設定"""
        try:
            from croniter import croniter  # pyright: ignore[reportMissingModuleSource]
            
            cron_expr = self.config.cron
            if not croniter.is_valid(cron_expr):
                raise ValueError(f"無効なcron式: {cron_expr}")
            
            # croniterを使用して次の実行時刻を計算
            base_time = datetime.now()
            cron = croniter(cron_expr, base_time)
            next_run = cron.get_next(datetime)
            
            self.logger.info(f"カスタムcron形式を設定: {cron_expr}, 次回実行予定: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # scheduleライブラリではcron形式を直接サポートしていないため、
            # 1分ごとにチェックしてcron式に一致するか確認する方式を採用
            def cron_job():
                now = datetime.now()
                cron_check = croniter(cron_expr, now)
                prev_run = cron_check.get_prev(datetime)
                # 前回実行時刻から1分以内なら実行（重複実行を防ぐ）
                if (now - prev_run).total_seconds() < 60:
                    self._execute_download()
            
            # 1分ごとにチェック
            schedule.every(1).minutes.do(cron_job)
            
        except ImportError:
            self.logger.error("croniter がインストールされていません。pip install croniter を実行してください。")
            raise
        except Exception as e:
            self.logger.error(f"カスタムcron形式の設定エラー: {str(e)}")
            raise

    def _run_scheduler(self):
        """スケジューラーを実行（バックグラウンド）"""
        self.logger.info("スケジューラーをバックグラウンドで実行中...")
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # 1分ごとにチェック

    def _execute_download(self):
        """ダウンロードを実行"""
        if self.download_callback:
            self.logger.info("スケジュールに従ってダウンロードを開始します")
            try:
                self.download_callback()
            except Exception as e:
                self.logger.error(f"スケジュール実行エラー: {str(e)}")
        else:
            self.logger.warning("ダウンロードコールバックが設定されていません")

    def get_next_run_time(self) -> Optional[datetime]:
        """次の実行時刻を取得"""
        if not schedule.jobs:
            return None

        # 最も近い実行時刻を取得
        next_run = min(job.next_run for job in schedule.jobs if job.next_run)
        return next_run

