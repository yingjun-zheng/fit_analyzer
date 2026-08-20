"""QtCharts 图表封装：折线图 / 柱状图。"""
from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QCategoryAxis,
    QChart,
    QChartView,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QEvent, QMargins, QObject, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy

PALETTE = ["#1e88e5", "#43a047", "#f57c00", "#8e24aa", "#e53935", "#00acc1", "#6d4c41"]


class _WheelForward(QObject):
    """把图表上的滚轮事件转发给外层 QScrollArea（QChartView 是滚动区子类，
    默认会吞掉滚轮事件导致页面无法滚动）。
    优先竖向滚动；若外层只有横向滚动条（横向图表条），把竖直滚轮转为横向滚动。"""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False
        dy = event.angleDelta().y()
        dx = event.angleDelta().x()
        if dy == 0 and dx == 0:
            return False
        view = obj.parent()  # viewport 的父级 = 图表视图
        p = view.parent() if view is not None else None
        while p is not None:
            if isinstance(p, QScrollArea):
                vsb = p.verticalScrollBar()
                hsb = p.horizontalScrollBar()
                if vsb is not None and vsb.maximum() > 0 and dy != 0:
                    QApplication.sendEvent(p.viewport(), event)
                    return True
                if hsb is not None and hsb.maximum() > 0:
                    step = dy if dy != 0 else dx
                    hsb.setValue(hsb.value() - step // 2)
                    return True
            p = p.parent()
        return False


def _view(chart, height):
    v = ScrollableChartView(chart)
    v.setRenderHint(QPainter.Antialiasing)
    v.setMinimumHeight(height)
    v.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    v._wheel_forward = _WheelForward(v)
    v.viewport().installEventFilter(v._wheel_forward)
    return v


class ScrollableChartView(QChartView):
    """图表视图（QChartView 本身无需特殊处理，滚轮转发由事件过滤器完成）。"""

    pass


def _style(chart, title):
    chart.setTitle(title)
    chart.legend().hide()
    chart.setTheme(QChart.ChartThemeLight)
    chart.setMargins(QMargins(8, 8, 8, 8))
    f = QFont("Microsoft YaHei", 9)
    chart.setTitleFont(f)


def _y_axis(label, fmt):
    ax = QValueAxis()
    ax.setTitleText(label)
    ax.setLabelFormat(fmt)
    ax.setGridLineVisible(True)
    return ax


def line_chart(title, xs, ys, color="#1e88e5", y_label="", height=200, fmt="%.0f"):
    """数值 X 轴折线图。"""
    chart = QChart()
    _style(chart, title)
    s = QLineSeries()
    s.setPen(QPen(QColor(color), 1.6))
    for x, y in zip(xs, ys):
        if y is None:
            continue
        s.append(float(x), float(y))
    chart.addSeries(s)
    ax_x = QValueAxis()
    ax_x.setLabelFormat("%.0f")
    ax_y = _y_axis(y_label, fmt)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    s.attachAxis(ax_x)
    s.attachAxis(ax_y)
    return _view(chart, height)


def line_chart_time(title, xs_sec, ys, color="#1e88e5", y_label="", height=200, fmt="%.0f"):
    """X 轴为时间（mm:ss 标签）。"""
    chart = QChart()
    _style(chart, title)
    s = QLineSeries()
    s.setPen(QPen(QColor(color), 1.6))
    for x, y in zip(xs_sec, ys):
        if y is None:
            continue
        s.append(float(x), float(y))
    chart.addSeries(s)
    ax_x = QCategoryAxis()
    ax_x.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
    ax_x.setTitleText("时间")
    maxv = max(xs_sec) if xs_sec else 0
    # 自适应标签数量（约 8 个），避免时间轴标签重叠
    import math

    step = max(60, int(math.ceil(maxv / 8)))
    for nice in (60, 120, 300, 600, 900, 1800, 3600):
        if step <= nice:
            step = nice
            break
    for t in range(0, int(maxv) + step, step):
        ax_x.append(f"{t // 60}:{t % 60:02d}", float(t))
    ax_x.setRange(0, float(maxv))
    ax_y = _y_axis(y_label, fmt)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    s.attachAxis(ax_x)
    s.attachAxis(ax_y)
    return _view(chart, height)


def bar_chart(title, categories, values, color="#1e88e5", y_label="", height=220, fmt="%.0f", label_angle=0):
    """柱状图。label_angle: X 轴标签旋转角度（长标签用 -45 防重叠）。"""
    chart = QChart()
    _style(chart, title)
    bs = QBarSet("")
    bs.setColor(QColor(color))
    for v in values:
        bs.append(float(v or 0))
    series = QBarSeries()
    series.append(bs)
    series.setBarWidth(0.7)
    chart.addSeries(series)
    ax_x = QBarCategoryAxis()
    ax_x.append([str(c) for c in categories])
    if label_angle:
        ax_x.setLabelsAngle(label_angle)
    ax_y = _y_axis(y_label, fmt)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    series.attachAxis(ax_x)
    series.attachAxis(ax_y)
    return _view(chart, height)


def zone_text(zones):
    """区间统计文字摘要。"""
    lines = []
    for z in zones:
        label = z.get("label", "")
        sec = z.get("seconds", 0)
        pct = z.get("pct", 0)
        lines.append(f"{label}: {sec:.0f} 秒 ({pct:.1f}%)")
    return "   ".join(lines) if lines else ""
