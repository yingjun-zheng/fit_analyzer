"""系统托盘与气泡通知（主动提醒的推送渠道）。

QSystemTrayIcon 不可用时（无托盘环境/offscreen 自检）优雅降级为 None，
所有调用方走安全空操作，不影响功能。
"""
import logging

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core import notifier

log = logging.getLogger("fit.tray")


class TrayNotifier(QObject):
    """托盘图标 + 气泡通知 + 提醒引擎接线。"""

    def __init__(self, main_window, icon, parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("系统托盘不可用，提醒仅记录入库（不弹气泡）")
            return
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(main_window.config.get("app_name"))
        menu = QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self.show_main)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(QApplication.instance().quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    # ---------------- 对外接口 ----------------
    @property
    def available(self):
        return self._tray is not None

    def show_main(self):
        mw = self._mw
        mw.showNormal()
        mw.raise_()
        mw.activateWindow()

    def notify(self, title, body, on_click=None):
        """弹气泡通知（系统不支持时仅记日志）；on_click 在用户点击气泡时调用。"""
        if self._tray is None:
            log.info("[提醒] %s：%s", title, body)
            if on_click:
                on_click()
            return
        self._click_cb = on_click
        self._tray.showMessage(title, body,
                               QSystemTrayIcon.MessageIcon.Information, 8000)

    def notify_alerts(self, alerts):
        """对一批新提醒逐个弹气泡（主线程调用）。"""
        for a in alerts or []:
            self.notify(a.get("title") or "提醒", a.get("body") or "")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.MessageClicked:
            cb = getattr(self, "_click_cb", None)
            if cb:
                cb()
                return
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_main()

    def unread_count(self):
        """未读提醒数（供铃铛角标/错过补发）。"""
        try:
            return len(self._mw.db.list_notifications(unread_only=True, limit=100000))
        except Exception:  # noqa: BLE001
            return 0

    # ---------------- 提醒引擎接线 ----------------
    def compute_alerts(self):
        """worker 线程调用：检测并入库新提醒，返回新触发列表。"""
        return notifier.run_alerts(self._mw.db, self._mw.config)

    def run_alerts_async(self, callback=None):
        """后台检测提醒；完成后主线程弹气泡（callback 可叠加处理，如刷新铃铛）。"""
        if self._tray is None:
            # 无托盘环境：仍入库（下次打开软件可见），不弹气泡
            self._mw._run_worker(self.compute_alerts, lambda ok, al: None)
            return
        self._mw._run_worker(self.compute_alerts, lambda ok, al: self._on_computed(ok, al, callback))

    def _on_computed(self, ok, alerts, callback=None):
        if ok and alerts:
            self.notify_alerts(alerts)
            self._mw.statusBar().showMessage(f"🔔 新增 {len(alerts)} 条提醒", 6000)
        if callback:
            try:
                callback()
            except Exception:
                log.debug("提醒回调异常", exc_info=True)
