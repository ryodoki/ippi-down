# -*- coding: utf-8 -*-

"""定期実行管理を行うクラス"""

import schedule
import threading
from datetime import datetime
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
        self._scheduler = schedule.Scheduler()
        self._lock = threading.RLock()
        self._wake_event = threading.Event()

    def set_download_callback(self, callback: Callable):
        """ダウンロードコールバックを設定"""
        self.download_callback = callback

    def start(self) -> bool:
        """スケジューラーを開始。開始できた場合はTrueを返す。"""
        if not self.config.enabled:
            self.logger.info("スケジュール機能は無効です")
            return False
        if not self.config.is_supported:
            self.logger.warning(
                f"スケジュール方式 '{self.config.interval}' はサポート対象外です。"
                "daily/weekly/monthly のいずれかを指定してください"
            )
            return False

        if self.running:
            self.logger.warning("スケジューラーは既に実行中です")
            return False

        with self._lock:
            self._setup_schedule()
            if not self._scheduler.jobs:
                return False

        self.running = True
        self._wake_event.clear()
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        self.logger.info("スケジューラーを開始しました")
        return True

    def stop(self):
        """スケジューラーを停止"""
        self.running = False
        self._wake_event.set()
        current_thread = threading.current_thread()
        if self.thread and self.thread is not current_thread:
            self.thread.join(timeout=2)
        with self._lock:
            self._scheduler.clear()
        self.thread = None
        self.logger.info("スケジューラーを停止しました")

    def reconfigure(self, config: ScheduleConfig) -> bool:
        """設定を置き換え、必要に応じてスケジューラーを再起動する。

        GUIで保存した設定をプロセス再起動なしで反映するためのAPI。
        新設定が無効または非対応の場合は停止状態にしてFalseを返す。
        """
        self.stop()
        self.config = config
        if not config.enabled:
            self.logger.info("更新後の設定ではスケジュール機能は無効です")
            return False
        return self.start()

    def _setup_schedule(self):
        """スケジュールを設定"""
        self._scheduler.clear()

        if self.config.interval == "daily":
            self._schedule_daily()
        elif self.config.interval == "weekly":
            self._schedule_weekly()
        elif self.config.interval == "monthly":
            self._schedule_monthly()
        else:
            self.logger.warning(
                f"スケジュール方式 '{self.config.interval}' はサポート対象外のため無効です"
            )

    def _schedule_daily(self):
        """毎日のスケジュールを設定"""
        try:
            self._scheduler.every().day.at(self.config.time).do(self._execute_download)
            self.logger.info(f"毎日 {self.config.time} に実行するように設定しました")
        except Exception as e:
            self.logger.error(f"スケジュール設定エラー: {str(e)}")

    def _schedule_weekly(self):
        """毎週のスケジュールを設定"""
        try:
            weekday_job = getattr(self._scheduler.every(), self.config.weekday)
            weekday_job.at(self.config.time).do(self._execute_download)
            self.logger.info(
                f"毎週 {self.config.weekday} {self.config.time} に実行するように設定しました"
            )
        except Exception as e:
            self.logger.error(f"スケジュール設定エラー: {str(e)}")

    def _schedule_monthly(self):
        """毎月のスケジュールを設定"""
        try:
            def monthly_job():
                today = datetime.now()
                if today.day == self.config.day_of_month:
                    self._execute_download()

            self._scheduler.every().day.at(self.config.time).do(monthly_job)
            self.logger.info(
                f"毎月{self.config.day_of_month}日 {self.config.time} に実行するように設定しました"
            )
        except Exception as e:
            self.logger.error(f"スケジュール設定エラー: {str(e)}")

    def _run_scheduler(self):
        """スケジューラーを実行（バックグラウンド）"""
        self.logger.info("スケジューラーをバックグラウンドで実行中...")
        while self.running:
            with self._lock:
                self._scheduler.run_pending()
            self._wake_event.wait(1)
            self._wake_event.clear()

    def _execute_download(self):
        """スケジューラーループを塞がずにダウンロードを開始する。"""
        if self.download_callback:
            self.logger.info("スケジュールに従ってダウンロードを開始します")
            threading.Thread(
                target=self._invoke_download_callback,
                name="ippi-scheduled-download",
                daemon=True,
            ).start()
        else:
            self.logger.warning("ダウンロードコールバックが設定されていません")

    def _invoke_download_callback(self):
        """ダウンロードコールバック本体。"""
        try:
            if self.download_callback:
                self.download_callback()
        except Exception as e:
            self.logger.error(f"スケジュール実行エラー: {str(e)}")

    def get_next_run_time(self) -> Optional[datetime]:
        """次の実行時刻を取得"""
        with self._lock:
            jobs = [job for job in self._scheduler.jobs if job.next_run]
            if not jobs:
                return None
            return min(job.next_run for job in jobs)
