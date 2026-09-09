"""训练日历热力图（GitHub 贡献图风格）：按日里程着色的近半年日历。

QPainter 自绘 7 行（周一~周日）× 26 列（周）网格，颜色随当日里程分级；
鼠标悬停显示当日里程与次数。选 QPainter 而非 QtCharts：网格类图形用
series 表达既别扭又低效（同 route_3d 的选型理由）。

数据由 db.daily_km_since 提供：{date_str: {km, count}}。
"""
import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QToolTip, QWidget

WEEKS = 26  # 展示近 26 周（半年）

# 里程分级色（0 → 多）：与应用主题蓝一致
LEVEL_COLORS = ["#eef1f5", "#cfe0f5", "#9dc4ef", "#5b9de8", "#1e68c8"]
_WEEKDAY_LABELS = ["一", "", "三", "", "五", "", "日"]
_GAP = 3.0
_LEFT, _TOP, _RIGHT, _BOTTOM = 26.0, 16.0, 6.0, 6.0


class RideHeatmapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._days = {}     # "YYYY-MM-DD" -> {"km", "count"}
        self._start = None  # 网格起点（对齐周一）
        self._end = None
        self._max_km = 0.0
        self.setFixedHeight(150)
        self.setMouseTracking(True)

    def set_data(self, days, end=None):
        """days: {date_str: {km, count}}；end: 结束日期（默认今天）。"""
        self._days = days or {}
        self._end = end or datetime.date.today()
        start = self._end - datetime.timedelta(days=WEEKS * 7 - 1)
        self._start = start - datetime.timedelta(days=start.weekday())  # 对齐周一
        kms = [v["km"] for v in self._days.values() if v.get("km", 0) > 0]
        self._max_km = max(kms) if kms else 0.0
        self.update()

    def _level_for(self, km):
        """里程 → 颜色分级（0~4）：按最大里程 4 等分。"""
        if km <= 0 or self._max_km <= 0:
            return 0
        return min(4, 1 + int(km / self._max_km * 4))

    def _geometry(self):
        """返回 (x0, y0, cell, n_rows)；cell 为单格边长，网格水平居中。"""
        cell = max(4.0, min((self.width() - _LEFT - _RIGHT) / WEEKS,
                            (self.height() - _TOP - _BOTTOM) / 7.0) - _GAP)
        grid_w = WEEKS * (cell + _GAP)
        x0 = _LEFT + max(0.0, (self.width() - _LEFT - _RIGHT - grid_w) / 2.0)
        return x0, _TOP, cell, 7

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if self._start is None:
            return
        x0, y0, cell, _ = self._geometry()
        step = cell + _GAP
        f = p.font()
        f.setPixelSize(9)
        p.setFont(f)

        n_days = (self._end - self._start).days + 1
        prev_month = None
        for i in range(n_days):
            d = self._start + datetime.timedelta(days=i)
            col, row = divmod(i, 7)
            x = x0 + col * step
            y = y0 + row * step
            if row == 0 and d.month != prev_month:
                p.setPen(QColor("#7a8794"))
                p.drawText(QRectF(x, 0, step * 2, _TOP - 2),
                           Qt.AlignLeft | Qt.AlignVCenter, f"{d.month}月")
                prev_month = d.month
            if d > self._end:
                continue
            info = self._days.get(d.isoformat())
            level = self._level_for(info.get("km", 0)) if info else 0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(LEVEL_COLORS[level]))
            p.drawRoundedRect(QRectF(x, y, cell, cell), 2.5, 2.5)

        # 星期标签（一/三/五/日 稀疏标注）
        p.setPen(QColor("#9aa6b2"))
        for row, label in enumerate(_WEEKDAY_LABELS):
            if label:
                y = y0 + row * step + cell / 2
                p.drawText(QRectF(0, y - 6, x0 - 6, 12),
                           Qt.AlignRight | Qt.AlignVCenter, label)

    def mouseMoveEvent(self, e):
        if self._start is not None:
            x0, y0, cell, _ = self._geometry()
            step = cell + _GAP
            col = int((e.position().x() - x0) / step)
            row = int((e.position().y() - y0) / step)
            if 0 <= col < WEEKS and 0 <= row < 7:
                d = self._start + datetime.timedelta(days=col * 7 + row)
                if d <= self._end:
                    info = self._days.get(d.isoformat())
                    if info:
                        text = f"{d.month}月{d.day}日：{info['km']} km，{info['count']} 次"
                    else:
                        text = f"{d.month}月{d.day}日：未骑行"
                    QToolTip.showText(e.globalPosition().toPoint(), text, self)
        super().mouseMoveEvent(e)
