"""QtCharts 图表封装：折线图 / 柱状图。"""
from PySide6.QtCharts import (
    QAreaSeries,
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


def multi_line_chart_cat(title, categories, series_list, y_label="", height=280, fmt="%.0f"):
    """类别 X 轴多线图：多条折线 + 数据点叠加。

    series_list: [{"name": "CTL", "values": [...], "color": "#1e88e5"}, ...]
    categories: ["2026-08-01", ...]  X 轴标签
    """
    chart = QChart()
    _style(chart, title)

    # 图例（显示多线名称）
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignTop)
    chart.legend().setFont(QFont("Microsoft YaHei", 8))

    for s in series_list:
        vals = s["values"]
        color = s.get("color", "#1e88e5")
        line = QLineSeries()
        line.setName(s["name"])
        line.setPen(QPen(QColor(color), 1.6))
        for i, v in enumerate(vals):
            if v is not None:
                line.append(float(i), float(v))
        chart.addSeries(line)

        # 数据点标记
        pts = QScatterSeries()
        pts.setMarkerSize(4.0)
        pts.setColor(QColor(color))
        for i, v in enumerate(vals):
            if v is not None:
                pts.append(float(i), float(v))
        chart.addSeries(pts)

    ax_x = QCategoryAxis()
    ax_x.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
    ax_x.setLabelsFont(_axis_font())
    _no_title(ax_x)
    # 自动精简标签数量（每 95px 一个标签）
    n = len(categories)
    if n > 0:
        for i, cat in enumerate(categories):
            ax_x.append(cat, float(i))
    ax_x.setRange(-0.5, float(max(n - 1, 0)) + 0.5)

    ax_y = _y_axis(y_label, fmt)
    ax_y.setGridLineColor(QColor("#e8e8e8"))
    ax_y.setTickCount(5)

    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    for s in chart.series():
        if isinstance(s, QAreaSeries):
            continue
        s.attachAxis(ax_x)
        s.attachAxis(ax_y)
    return _view(chart, height, adaptive={"type": "cat", "cats": list(categories)})


# 爬坡分级 → 高亮色（Cat4 浅 → HC 深红，对应 Strava 分级的难度递进）
CLIMB_COLORS = {
    "Cat 4": "#fbc02d",
    "Cat 3": "#f9a825",
    "Cat 2": "#f57c00",
    "Cat 1": "#e53935",
    "HC": "#b71c1c",
}


def elevation_chart_with_climbs(title, xs, ys, climbs, color="#1e88e5",
                                y_label="海拔 (m)", height=300, fmt="%.0f"):
    """海拔剖面图，并在爬坡段叠加半透明竖直色带高亮。

    xs/ys：沿距离的海拔剖面（与 line_chart 同构）。
    climbs：route 的 climbs 列表，每项含 start_km/end_km/category。
    """
    chart = QChart()
    _style(chart, title)

    # 1) 海拔折线
    line = QLineSeries()
    line.setPen(QPen(QColor(color), 1.6))
    for x, y in zip(xs, ys):
        if y is None:
            continue
        line.append(float(x), float(y))
    chart.addSeries(line)

    ax_x = _x_axis_numeric()
    ax_y = _y_axis(y_label, fmt)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    line.attachAxis(ax_x)
    line.attachAxis(ax_y)

    y_min = min((y for y in ys if y is not None), default=0)
    y_max = max((y for y in ys if y is not None), default=0)
    if y_max - y_min < 1:
        y_min -= 5
        y_max += 5

    # 2) 爬坡段色带：每个爬坡段一条竖直矩形区域（X 轴为爬坡起止距离）
    for i, c in enumerate(climbs):
        x0 = c.get("start_km")
        x1 = c.get("end_km")
        if x0 is None or x1 is None:
            continue
        cat = c.get("category") or ""
        band_color = CLIMB_COLORS.get(c.get("category_name", ""), CLIMB_COLORS.get(cat, "#f57c00"))

        upper = QLineSeries()
        lower = QLineSeries()
        upper.setPen(QPen(Qt.NoPen))
        lower.setPen(QPen(Qt.NoPen))
        upper.append(float(x0), float(y_max))
        upper.append(float(x1), float(y_max))
        lower.append(float(x0), float(y_min))
        lower.append(float(x1), float(y_min))

        band = QAreaSeries(upper, lower)
        band.setName(f"爬坡 {i + 1}")
        band.setColor(QColor(band_color))
        band.setBorderColor(QColor(Qt.transparent))
        band.setOpacity(0.28)
        chart.addSeries(band)
        band.attachAxis(ax_x)
        band.attachAxis(ax_y)
        # 关键：QAreaSeries 的上下界 QLineSeries 必须保持存活引用，
        # 否则函数返回后被 GC 回收，QAreaSeries 内部指针悬空，渲染时段错误。
        band.upperSeriesRef = upper
        band.lowerSeriesRef = lower

    return _view(chart, height, adaptive={"type": "numeric"})


# 心率区间配色（Z1 恢复 → Z5 无氧，由浅到深/冷到暖）
HR_ZONE_COLORS = ["#90a4ae", "#43a047", "#fdd835", "#fb8c00", "#e53935"]


def hr_curve_with_zones(title, xs_sec, ys, hr_max, pcts, height=300, fmt="%.0f"):
    """带心率区间色带背景的心率曲线。

    在心率曲线上按 5 区阈值叠加半透明水平色带（视觉同路书爬坡色带），
    一眼看出「哪段时间落在哪个心率区」。

    xs_sec/ys：心率时间序列。
    hr_max：最大心率（用于算区间边界）。pcts：区间百分比边界（如 [0.6,0.7,0.8,0.9]）。
    """
    chart = QChart()
    _style(chart, title)
    x_max = max(xs_sec) if xs_sec else 0

    # 区间边界（bpm）
    bounds = [hr_max * p for p in pcts] if hr_max else []
    valid_ys = [y for y in ys if y is not None]
    y_hi = max(valid_ys) if valid_ys else hr_max
    if hr_max:
        y_hi = max(y_hi, hr_max)

    zones = []  # [(lo_bpm, hi_bpm)]
    if bounds:
        prev = 0.0
        for b in bounds:
            zones.append((prev, b))
            prev = b
        zones.append((prev, max(prev + 1, y_hi)))

    # 1) 先画区间色带（背景）
    for i, (zlo, zhi) in enumerate(zones):
        color = HR_ZONE_COLORS[i % len(HR_ZONE_COLORS)]
        upper = QLineSeries()
        lower = QLineSeries()
        upper.setPen(QPen(Qt.NoPen))
        lower.setPen(QPen(Qt.NoPen))
        upper.append(0.0, float(zhi))
        upper.append(float(x_max), float(zhi))
        lower.append(0.0, float(zlo))
        lower.append(float(x_max), float(zlo))
        band = QAreaSeries(upper, lower)
        band.setName(f"Z{i + 1}")
        band.setColor(QColor(color))
        band.setBorderColor(QColor(Qt.transparent))
        band.setOpacity(0.20)
        chart.addSeries(band)
        band.upperSeriesRef = upper
        band.lowerSeriesRef = lower

    # 2) 再画心率折线
    line = QLineSeries()
    line.setPen(QPen(QColor("#111111"), 1.8))
    for x, y in zip(xs_sec, ys):
        if y is None:
            continue
        line.append(float(x), float(y))
    chart.addSeries(line)

    ax_x = QCategoryAxis()
    ax_x.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
    _no_title(ax_x)
    ax_x.setLabelsFont(_axis_font())
    import math
    step = max(60, int(math.ceil(x_max / 5)))
    for nice in (60, 120, 300, 600, 900, 1800, 3600):
        if step <= nice:
            step = nice
            break
    for t in range(0, int(x_max) + step, step):
        ax_x.append(f"{t // 60}:{t % 60:02d}", float(t))
    ax_x.setRange(0, float(x_max))

    ax_y = _y_axis("心率 (bpm)", fmt)
    ax_y.setRange(max(0, -5), y_hi + 5)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    for s in chart.series():
        s.attachAxis(ax_x)
        s.attachAxis(ax_y)

    return _view(chart, height, adaptive={"type": "time", "xs": list(xs_sec)})


# ---------------- 渐变折线（按 Y 值分段着色） ----------------

def _lerp_color(c1, c2, t):
    """在两种 QColor 间线性插值（t: 0~1）。"""
    t = max(0.0, min(1.0, t))
    r = int(c1.red() + (c2.red() - c1.red()) * t)
    g = int(c1.green() + (c2.green() - c1.green()) * t)
    b = int(c1.blue() + (c2.blue() - c1.blue()) * t)
    return QColor(r, g, b)


def _gradient_color(stops, v01):
    """stops: [(pos, QColor)] 按 pos 升序；v01: 归一化值 0~1。返回插值颜色。"""
    if not stops:
        return QColor("#1e88e5")
    if v01 <= stops[0][0]:
        return stops[0][1]
    if v01 >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= v01 <= p1:
            span = (p1 - p0) or 1.0
            return _lerp_color(c0, c1, (v01 - p0) / span)
    return stops[-1][1]


# 海拔渐变：低海拔绿 → 中黄 → 高海拔红
ALTITUDE_STOPS = [(0.0, "#2e7d32"), (0.5, "#fdd835"), (1.0, "#e53935")]
# 速度渐变：低速蓝 → 中速青 → 高速橙
SPEED_STOPS = [(0.0, "#1565c0"), (0.5, "#00acc1"), (1.0, "#ef6c00")]


def gradient_line_numeric(title, xs, ys, stops, y_label="", height=300, fmt="%.0f"):
    """数值 X 轴渐变折线：按 Y 值归一化后分段着色。

    xs/ys：数据；stops：[(pos, color_hex)] 渐变映射（pos 为 y 归一化位置 0~1）。
    """
    chart = QChart()
    _style(chart, title)
    vmin = min((y for y in ys if y is not None), default=0)
    vmax = max((y for y in ys if y is not None), default=1)
    if vmax - vmin < 1e-6:
        vmax = vmin + 1.0
    stops_color = [(p, QColor(c)) for p, c in stops]

    pts = [(float(x), float(y)) for x, y in zip(xs, ys) if y is not None]
    ax_x = _x_axis_numeric()
    ax_y = _y_axis(y_label, fmt)
    ax_y.setRange(vmin, vmax)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        vmid = (y0 + y1) / 2.0
        v01 = (vmid - vmin) / (vmax - vmin)
        seg = QLineSeries()
        seg.setPen(QPen(_gradient_color(stops_color, v01), 1.8))
        seg.append(x0, y0)
        seg.append(x1, y1)
        chart.addSeries(seg)
        seg.attachAxis(ax_x)
        seg.attachAxis(ax_y)
    return _view(chart, height, adaptive={"type": "numeric"})


def gradient_line_time(title, xs_sec, ys, stops, y_label="", height=300, fmt="%.0f"):
    """时间 X 轴渐变折线（X 轴 mm:ss，按 Y 值分段着色）。"""
    chart = QChart()
    _style(chart, title)
    vmin = min((y for y in ys if y is not None), default=0)
    vmax = max((y for y in ys if y is not None), default=1)
    if vmax - vmin < 1e-6:
        vmax = vmin + 1.0
    stops_color = [(p, QColor(c)) for p, c in stops]

    pts = [(float(x), float(y)) for x, y in zip(xs_sec, ys) if y is not None]
    x_max = max(xs_sec) if xs_sec else 0

    ax_x = QCategoryAxis()
    ax_x.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
    _no_title(ax_x)
    ax_x.setLabelsFont(_axis_font())
    import math
    step = max(60, int(math.ceil(x_max / 5)))
    for nice in (60, 120, 300, 600, 900, 1800, 3600):
        if step <= nice:
            step = nice
            break
    for t in range(0, int(x_max) + step, step):
        ax_x.append(f"{t // 60}:{t % 60:02d}", float(t))
    ax_x.setRange(0, float(x_max))

    ax_y = _y_axis(y_label, fmt)
    ax_y.setRange(vmin, vmax)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        vmid = (y0 + y1) / 2.0
        v01 = (vmid - vmin) / (vmax - vmin)
        seg = QLineSeries()
        seg.setPen(QPen(_gradient_color(stops_color, v01), 1.8))
        seg.append(x0, y0)
        seg.append(x1, y1)
        chart.addSeries(seg)
        seg.attachAxis(ax_x)
        seg.attachAxis(ax_y)
    return _view(chart, height, adaptive={"type": "time", "xs": list(xs_sec)})


def altitude_area_chart(title, xs, ys, height=320, fmt="%.0f"):
    """海拔面积填充图：填充色随海拔高度渐变（低处绿 → 高处红）。

    实现：把海拔曲线切成 N 段，每段一个 QAreaSeries（上界=曲线段，下界=基线），
    颜色按该段中点海拔做绿色→红色插值，叠加后形成自然的垂直渐变填充。
    X 轴为里程 km（数值轴）。
    """
    chart = QChart()
    _style(chart, title)
    vmin = min((y for y in ys if y is not None), default=0)
    vmax = max((y for y in ys if y is not None), default=1)
    if vmax - vmin < 1e-6:
        vmax = vmin + 1.0

    pts = [(float(x), float(y)) for x, y in zip(xs, ys) if y is not None]
    if len(pts) < 2:
        return _view(chart, height, adaptive={"type": "numeric"})

    ax_x = _x_axis_numeric()
    ax_y = _y_axis("海拔 (m)", fmt)
    ax_y.setRange(vmin, vmax + (vmax - vmin) * 0.12)
    chart.addAxis(ax_x, Qt.AlignBottom)
    chart.addAxis(ax_y, Qt.AlignLeft)

    # 颜色渐变：低海拔绿 #2e7d32 → 中黄 #fdd835 → 高红 #e53935
    stops_color = [(p, QColor(c)) for p, c in ALTITUDE_STOPS]

    def _color_for(alt):
        v01 = (alt - vmin) / (vmax - vmin)
        return _gradient_color(stops_color, v01)

    # 分段面积填充：相邻两点之间一段，颜色取该段中点海拔
    base = vmin
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        col = _color_for((y0 + y1) / 2.0)
        upper = QLineSeries()
        lower = QLineSeries()
        upper.setPen(QPen(Qt.NoPen))
        lower.setPen(QPen(Qt.NoPen))
        upper.append(x0, y0)
        upper.append(x1, y1)
        lower.append(x0, base)
        lower.append(x1, base)
        band = QAreaSeries(upper, lower)
        band.setColor(QColor(col.red(), col.green(), col.blue(), 140))
        band.setBorderColor(QColor(Qt.transparent))
        chart.addSeries(band)
        band.upperSeriesRef = upper
        band.lowerSeriesRef = lower
        band.attachAxis(ax_x)
        band.attachAxis(ax_y)

    # 顶部再画一条实线（清晰地勾出轮廓）
    line = QLineSeries()
    line.setPen(QPen(QColor("#37474f"), 2.0))
    for x, y in pts:
        line.append(x, y)
    chart.addSeries(line)
    line.attachAxis(ax_x)
    line.attachAxis(ax_y)

    return _view(chart, height, adaptive={"type": "numeric"})
