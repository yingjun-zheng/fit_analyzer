"""提醒中心：查看未读提醒（阈值预警 / 周报 / 更新），标记已读与清空。"""
import logging
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

log = logging.getLogger("fit.notifcenter")

_KIND_CN = {"tsb": "⚠️ 疲劳预警", "gear": "🔧 装备提醒", "goal": "🎯 目标进度",
            "weekly": "📊 训练周报", "update": "🔄 软件更新"}


def format_time(ts):
    try:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except Exception:
        return ""


class ReminderCenterDialog(QDialog):
    """未读/全部提醒列表：双击标记已读，支持全部已读与清空。"""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("🔔 提醒中心")
        self.setMinimumSize(480, 420)
        lay = QVBoxLayout(self)

        head = QHBoxLayout()
        self.head_label = QLabel("")
        self.head_label.setObjectName("h3")
        head.addWidget(self.head_label)
        head.addStretch(1)
        btn_read_all = QPushButton("全部已读")
        btn_read_all.clicked.connect(self._mark_all_read)
        btn_clear = QPushButton("清空提醒")
        btn_clear.clicked.connect(self._clear_all)
        head.addWidget(btn_read_all)
        head.addWidget(btn_clear)
        lay.addLayout(head)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._mark_read)
        self.list.setWordWrap(True)
        lay.addWidget(self.list, 1)

        tip = QLabel("双击单条可标记已读；提醒来自训练负荷预警、装备保养、周报与更新。")
        tip.setObjectName("muted")
        lay.addWidget(tip)

        self.reload()

    # ---------------- 数据 ----------------
    def reload(self):
        rows = self.db.list_notifications(limit=200)
        self.list.clear()
        unread = 0
        for n in rows:
            kind = _KIND_CN.get(n["kind"], n["kind"])
            title = n["title"] or kind
            body = (n["body"] or "").replace("\n", " ")
            if len(body) > 90:
                body = body[:90] + "…"
            text = f"{title}  ·  {format_time(n['created_ts'])}\n{body}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, n["id"])
            if not n["read"]:
                unread += 1
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.list.addItem(item)
        self.head_label.setText(f"提醒中心（未读 {unread} 条 / 共 {len(rows)} 条）")

    def _mark_read(self, item):
        nid = item.data(Qt.UserRole)
        self.db.mark_notifications_read(ids=[nid])
        self.reload()

    def _mark_all_read(self):
        self.db.mark_notifications_read()
        self.reload()

    def _clear_all(self):
        from PySide6.QtWidgets import QMessageBox
        ret = QMessageBox.question(self, "清空提醒", "确定清空全部提醒记录？",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.db.clear_notifications()
            self.reload()
