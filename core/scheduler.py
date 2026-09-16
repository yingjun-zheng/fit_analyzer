"""定时调度器：到点触发周报等周期性任务。

主窗口常驻时每分钟检查一次到期任务（周报按配置的星期 + 时间）；
到期且本周尚未生成（notifications 去重）时触发。
"""
import logging

from PySide6.QtCore import QObject, QTimer

from core import weekly_report

log = logging.getLogger("fit.scheduler")

CHECK_INTERVAL_MS = 60_000


class WeeklyScheduler(QObject):
    """周报定时调度：到点调用 on_due()（由 GUI 负责后台生成与推送）。"""

    def __init__(self, config, on_due, parent=None):
        super().__init__(parent)
        self.config = config
        self.on_due = on_due
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self.tick)
        self._fired_window = None  # 本会话已触发过的周报窗口（防重复弹）

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def tick(self):
        """每分钟检查：到周报时间点 → 触发（窗口去重）。"""
        try:
            if not weekly_report.due_for_weekly_report(self.config):
                return
            import datetime
            this_start, *_ = weekly_report._week_window(datetime.date.today())
            if this_start == self._fired_window:
                return  # 本会话已触发过该窗口
            self._fired_window = this_start
            log.info("周报到点触发（窗口 %s）", this_start)
            self.on_due()
        except Exception:  # noqa: BLE001
            log.exception("调度检查异常")
