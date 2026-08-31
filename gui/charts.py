"""QtCharts 图表封装：折线图 / 柱状图。"""
from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QCategoryAxis,
    QChart,
    QChartView,
    QLineSeries,
    QScatterSeries,
    QValueAxis,
)
from PySide6.QtCore import QEvent, QMargins, QObject, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy

PALETTE = ["#1e88e5", "#43a047", "#f57c00", "#8e24aa", "#e53935", "#00acc1", "#6d4c41"]


class _WheelForward(QObject):
    """图表上的滚轮处理（QChartView 是滚动区子类，默认会吞掉滚轮事件）：
    1) 若图表所在横向滚动条还能滚（每图独立横滚），先横向滚动该图表；
    2) 该图横向到头后，滚轮继续滚动外层页面。"""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False
        dy = event.angleDelta().y()
        dx = event.angleDelta().x()
        if dy == 0 and dx == 0:
            return False
        view = obj.parent()  # viewport 的父级 = 图表视图
        p = view.parent() if view is not None else None
        chart_hsb = None
        page_scroll = None
        while p is not None:
            if isinstance(p, QScrollArea):
                hsb = p.horizontalScrollBar()
                vsb = p.verticalScrollBar()
                if chart_hsb is None and hsb is not None and hsb.maximum() > 0:
                    chart_hsb = hsb
                if vsb is not None and vsb.maximum() > 0:
                    page_scroll = p
            p = p.parent()
        step = dy if dy != 0 else dx
        if chart_hsb is not None:
            can_scroll = (step < 0 and chart_hsb.value() < chart_hsb.maximum()) or \
                         (step > 0 and chart_hsb.value() > chart_hsb.minimum())
            if can_scroll:
                chart_hsb.setValue(chart_hsb.value() - step // 2)
                return True
        if page_scroll is not None:
            QApplication.sendEvent(page_scroll.viewport(), event)
            return True
        return False


def _view(chart, height, adaptive=None):
    v = ScrollableChartView(chart, adaptive=adaptive)
    v.setRenderHint(QPainter.Antialiasing)
    v.setMinimumHeight(height)
    v.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    v._wheel_forward = _WheelForward(v)
    v.viewport().installEventFilter(v._wheel_forward)
    return v


class ScrollableChartView(QChartView):
    """图表视图：滚轮转发 + 自适应坐标轴（像 Web 图表一样，尺寸变化时自动调整刻度密度，永不重叠）。"""

    def __init__(self, chart, adaptive=None):
        super().__init__(chart)
        self._adaptive = adaptive  # {"type": "time"|"numeric"|"cat", ...}

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._adaptive:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._tune_axes)

    def _replace_x_axis(self, chart, series, new_ax):
        """用新横轴替换旧横轴（QCategoryAxis/QBarCategoryAxis 无 clear，只能换对象）。"""
        old = chart.axisX(series)
        if old is not None:
            chart.removeAxis(old)
        chart.addAxis(new_ax, Qt.AlignBottom)
        series.attachAxis(new_ax)

    def _tune_axes(self):
        try:
            chart = self.chart()
            if chart is None or not chart.series():
                return
            plot = chart.plotArea()
            pw, ph = plot.width(), plot.height()
            if pw <= 0 or ph <= 0:
                return
            s = chart.series()[0]
            ax_x = chart.axisX(s)
            ax_y = chart.axisY(s)
        except Exception:
            return
        import math

        # 纵轴刻度数随高度自适应（每 45px 一个刻度，3~8 个）
        if isinstance(ax_y, QValueAxis):
            ax_y.setTickCount(max(3, min(8, int(ph / 45))))
        t = self._adaptive.get("type")
        try:
            if t == "time" and isinstance(ax_x, QCategoryAxis):
                maxv = max(self._adaptive.get("xs") or [0.0]) or 0.0
                target = max(1, int(pw / 95))  # 每 95px 一个时间标签
                step = max(60, int(math.ceil(maxv / target)))
                for nice in (60, 120, 300, 600, 900, 1800, 3600):
                    if step <= nice:
                        step = nice
                        break
                new_ax = QCategoryAxis()
                new_ax.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
                new_ax.setLabelsFont(_axis_font())
                _no_title(new_ax)
                for t0 in range(0, int(maxv) + step, step):
                    new_ax.append(f"{t0 // 60}:{t0 % 60:02d}", float(t0))
                new_ax.setRange(0, float(maxv))
                self._replace_x_axis(chart, s, new_ax)
            elif t == "cat" and isinstance(ax_x, QBarCategoryAxis):
                cats = self._adaptive.get("cats") or []
                n = len(cats)
                if n > 0:
                    skip = max(1, int(90 / max(1.0, pw / n)))  # 保证标签间距 ≥90px
                    newcats = [cats[i] if (i % skip == 0 or i == n - 1) else "" for i in range(n)]
                    new_ax = QBarCategoryAxis()
                    new_ax.setLabelsFont(_axis_font())
                    new_ax.append(newcats)
                    self._replace_x_axis(chart, s, new_ax)
            elif t == "numeric" and isinstance(ax_x, QValueAxis):
                ax_x.setTickCount(max(3, min(8, int(pw / 170))))
        except Exception:
            pass


def _style(chart, title):
    chart.setTitle(title)
    chart.legend().hide()
    chart.setTheme(QChart.ChartThemeLight)
    chart.setMargins(QMargins(6, 6, 6, 6))
    f = QFont("Microsoft YaHei", 9)
    chart.setTitleFont(f)


def _axis_font(size=8):
    f = QFont("Microsoft YaHei", size)
    f.setPixelSize(10)  # 坐标刻度文字用固定小字号，避免在窄高度下互相挤压
    return f


def _no_title(ax):
    """去掉轴标题（图表标题已说明含义），避免轴标题与刻度文字碰撞。"""
    ax.setTitleVisible(False)
    ax.setTitleText("")
    return ax


def _x_axis_numeric():
    ax = QValueAxis()
    ax.setLabelFormat("%.0f")
    ax.setTickCount(6)  # 横轴最多 6 个刻度，防标签重叠
    ax.setLabelsFont(_axis_font())
    return _no_title(ax)


def _y_axis(label, fmt):
    ax = QValueAxis()
    ax.setTitleText(label)
    ax.setLabelFormat(fmt)
    ax.setTickCount(5)  # 纵轴固定 5 个刻度，防标签重叠
    ax.setLabelsFont(_axis_font())
    ax.setGridLineVisible(True)
    return _no_title(ax)


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
    ax_x = _x_axis_numeric()
    ax_y = _y_axis(y_label, fmt)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    s.attachAxis(ax_x)
    s.attachAxis(ax_y)
    return _view(chart, height, adaptive={"type": "numeric"})


def line_chart_time(title, xs_sec, ys, color="#1e88e5", y_label="", height=200, fmt="%.0f"):
    """X 轴为时间（mm:ss 标签，最多 6 个防重叠）。"""
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
    _no_title(ax_x)
    ax_x.setLabelsFont(_axis_font())
    maxv = max(xs_sec) if xs_sec else 0
    import math

    step = max(60, int(math.ceil(maxv / 5)))
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
    return _view(chart, height, adaptive={"type": "time", "xs": list(xs_sec)})


def line_chart_cat(title, categories, values, color="#1e88e5", y_label="", height=220, fmt="%.0f"):
    """类别 X 轴折线图（X 轴为字符串类别，如月份/公里序号）。带数据点标记。"""
    chart = QChart()
    _style(chart, title)

    line = QLineSeries()
    line.setPen(QPen(QColor(color), 1.8))
    for i, v in enumerate(values):
        line.append(float(i), float(v or 0))
    chart.addSeries(line)

    # 数据点标记
    pts = QScatterSeries()
    pts.setMarkerSize(6.0)
    pts.setColor(QColor(color))
    pts.setBorderColor(QColor("#ffffff"))
    for i, v in enumerate(values):
        pts.append(float(i), float(v or 0))
    chart.addSeries(pts)

    ax_x = QCategoryAxis()
    ax_x.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
    _no_title(ax_x)
    ax_x.setLabelsFont(_axis_font())
    ax_x.setGridLineVisible(False)
    for i, c in enumerate(categories):
        ax_x.append(str(c), float(i))
    ax_x.setRange(0, float(max(len(categories) - 1, 1)))
    ax_y = _y_axis(y_label, fmt)
    ax_y.setGridLineColor(QColor("#e8e8e8"))
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    line.attachAxis(ax_x)
    line.attachAxis(ax_y)
    pts.attachAxis(ax_x)
    pts.attachAxis(ax_y)
    return _view(chart, height, adaptive={"type": "numeric"})


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
    ax_x.setLabelsFont(_axis_font())
    if label_angle:
        ax_x.setLabelsAngle(label_angle)
    ax_y = _y_axis(y_label, fmt)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    series.attachAxis(ax_x)
    series.attachAxis(ax_y)
    return _view(chart, height, adaptive={"type": "cat", "cats": list(categories)})


def bar_chart_clean(title, categories, values, color="#1e88e5", y_label="", height=300, fmt="%.0f"):
    """干净看板风格柱状图：白色背景、淡色网格线、细柱体、无标题、5 公里间隔标签。"""
    chart = QChart()
    # 白色背景，无标题
    chart.setBackgroundBrush(QColor("#ffffff"))
    chart.setBackgroundRoundness(0)
    chart.layout().setContentsMargins(0, 0, 0, 0)
    chart.legend().hide()
    chart.setMargins(QMargins(6, 6, 6, 6))

    # 细柱体，更窄的间距
    bs = QBarSet("")
    bs.setColor(QColor(color))
    for v in values:
        bs.append(float(v or 0))
    series = QBarSeries()
    series.append(bs)
    series.setBarWidth(0.55)
    chart.addSeries(series)

    ax_x = QBarCategoryAxis()
    ax_x.append([str(c) for c in categories])
    ax_x.setLabelsFont(_axis_font())
    ax_x.setGridLineVisible(False)
    _no_title(ax_x)

    ax_y = _y_axis(y_label, fmt)
    ax_y.setGridLineColor(QColor("#e8e8e8"))
    ax_y.setTickCount(5)

    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    series.attachAxis(ax_x)
    series.attachAxis(ax_y)
    return _view(chart, height, adaptive={"type": "cat", "cats": list(categories)})


def zone_text(zones):
    """区间统计文字摘要。"""
    lines = []
    for z in zones:
        label = z.get("label", "")
        sec = z.get("seconds", 0)
        pct = z.get("pct", 0)
        lines.append(f"{label}: {sec:.0f} 秒 ({pct:.1f}%)")
    return "   ".join(lines) if lines else ""
