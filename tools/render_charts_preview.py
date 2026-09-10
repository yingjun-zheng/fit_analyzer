"""离屏渲染美化后的图表 → PNG（自查视觉效果用）。

用默认 windows 平台（不 show 窗口、只 grab，中文字体正常），
曲线放进白色容器，等 650ms 入场动画播完再截。
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtCore import Qt, QTimer

app = QApplication([])

from gui.theme import apply_light_palette
apply_light_palette(app)

from gui import charts as ch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)

pending = []  # (container, filename)


def queue_render(view, name, w=860):
    view.resize(w, view.minimumHeight())
    holder = QWidget()
    holder.setAttribute(Qt.WA_StyledBackground, True)
    holder.setStyleSheet("background: #ffffff;")
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.addWidget(view)
    holder.resize(w + 24, view.minimumHeight() + 24)
    pending.append((holder, name))


xs = list(range(0, 2700, 60))
ys = [22 + 10 * math.sin(t / 300) + (t / 300 % 3) for t in xs]

queue_render(ch.gradient_line_time("速度 (km/h) — 时间", xs, ys, ch.SPEED_STOPS, "km/h", 300, "%.0f"), "01_speed_gradient.png")
queue_render(ch.hr_curve_with_zones("心率 (bpm) — 时间", xs, [120 + 30 * math.sin(t / 400) for t in xs], 185, [0.6, 0.7, 0.8, 0.9], 300, "%.0f"), "02_hr_zones.png")
queue_render(ch.altitude_area_chart("海拔 (m) — 里程 (km)", list(range(0, 1800, 30)), [50 + 40 * math.sin(t / 500) for t in range(0, 1800, 30)], 300, "%.0f"), "03_altitude.png")
queue_render(ch.line_chart_cat("每公里平均速度 (km/h)", ["5", "10", "15", "20", "25", "30"], [24.1, 26.3, 22.8, 27.5, 25.0, 28.2], "#1e88e5", "km/h", 260, "%.1f"), "04_per_km.png")
queue_render(ch.bar_chart("心率区间时长 (秒)", ["Z1", "Z2", "Z3", "Z4", "Z5"], [400, 900, 1500, 800, 300], "#d81b60", "秒", 260, "%.0f"), "05_hr_bars.png")
queue_render(ch.multi_line_chart_cat("训练负荷趋势 (CTL · ATL · TSB)", ["08-01", "08-08", "08-15", "08-22", "08-29", "09-05"],
                                     [{"name": "CTL", "values": [40, 45, 52, 58, 61, 66], "color": "#1e88e5"},
                                      {"name": "ATL", "values": [30, 70, 50, 80, 55, 90], "color": "#f57c00"},
                                      {"name": "TSB", "values": [10, -15, 12, -12, 16, -14], "color": "#43a047"}], "", 280, "%.0f"), "06_ctl_atl.png")

STEP_MS = 900  # > 650ms 动画时长


def grab_next(i=0, warmed=False):
    if i >= len(pending):
        print("ALL DONE")
        app.quit()
        return
    holder, name = pending[i]
    if not warmed:
        holder.grab()  # 预热：首次渲染会启动入场动画
        QTimer.singleShot(STEP_MS, lambda: grab_next(i, True))
        return
    holder.grab().save(os.path.join(OUT, name))
    print("saved", name)
    QTimer.singleShot(30, lambda: grab_next(i + 1, False))


QTimer.singleShot(STEP_MS, grab_next)
app.exec()
