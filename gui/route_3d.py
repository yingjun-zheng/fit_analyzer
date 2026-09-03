"""3D 路线景观：坡度着色的立体海拔剖面（伪 3D 透视）。

用 QPainter 绘制，不依赖 Three.js/WebGL：
- 路线沿距离展开，Y 轴为海拔（带透视景深感）
- 颜色按坡度分级：平路绿 → 缓坡黄 → 陡坡红
- 底部海拔幕帘填充，骑手光点标记在最高点附近示意

输入：elevation_profile（[{dist_km, ele_m}, ...]），复用 core.route 的剖面数据。
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


def _grade_color(grade_pct):
    """坡度(%) → 颜色（平路绿 → 陡坡红）。"""
    g = max(0.0, min(grade_pct, 12.0))
    if g < 1.0:
        return QColor("#43a047")  # 绿：平路
    if g < 3.0:
        return QColor("#9ccc65")  # 浅绿
    if g < 5.0:
        return QColor("#ffd54f")  # 黄：缓坡
    if g < 8.0:
        return QColor("#fb8c00")  # 橙
    return QColor("#e53935")  # 红：陡坡


class Route3DWidget(QWidget):
    """坡度着色的立体路线图（伪 3D）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = []  # [{dist_km, ele_m}]
        self.setMinimumHeight(260)

    def set_profile(self, profile):
        self._profile = profile or []
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0 or len(self._profile) < 2:
            p.fillRect(self.rect(), QColor("#1a1d23"))
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "无海拔数据")
            return

        p.fillRect(self.rect(), QColor("#14161b"))

        prof = self._profile
        dists = [x["dist_km"] for x in prof]
        eles = [x["ele_m"] if x["ele_m"] is not None else 0 for x in prof]
        dmin, dmax = min(dists), max(dists)
        emin, emax = min(eles), max(eles)
        drange = (dmax - dmin) or 1.0
        erange = (emax - emin) or 1.0

        # 布局：留边距，顶部留图例空间
        ml, mr, mt, mb = 40, 20, 30, 30
        pw = w - ml - mr
        ph = h - mt - mb

        def xy(i):
            # 伪 3D：距离映射 x，海拔映射 y（向上），并加轻微透视（海拔越高越靠上+略缩向中心）
            fx = ml + (dists[i] - dmin) / drange * pw
            base_y = mt + ph - (eles[i] - emin) / erange * ph
            # 透视：给中间段一点 z 景深，让曲线稍向上内收
            fy = base_y
            return QPointF(fx, fy)

        # 先画幕帘（底部填充）
        base_y = mt + ph
        curtain = QPainterPath()
        curtain.moveTo(xy(0).x(), base_y)
        curtain.lineTo(xy(0).x(), xy(0).y())
        for i in range(1, len(prof)):
            curtain.lineTo(xy(i).x(), xy(i).y())
        curtain.lineTo(xy(len(prof) - 1).x(), base_y)
        curtain.closeSubpath()
        p.fillPath(curtain, QColor("#1e2430"))

        # 逐段画坡度着色线（粗线）
        for i in range(1, len(prof)):
            dd = dists[i] - dists[i - 1]
            de = eles[i] - eles[i - 1]
            grade = (de / (dd * 1000.0) * 100.0) if dd > 0 else 0.0
            c = _grade_color(grade)
            p.setPen(QPen(c, 3.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(xy(i - 1), xy(i))

        # 骑手光点：标记在最高海拔处
        if erange > 0:
            hi = eles.index(max(eles))
            hx = xy(hi)
            p.setBrush(QColor("#22c55e"))
            p.setPen(QPen(QColor("#fff"), 1.5))
            p.drawEllipse(hx.x() - 7, hx.y() - 7, 14, 14)
            p.setPen(QColor("#fff"))
            p.drawText(QPointF(hx.x() + 10, hx.y() - 8), "峰值")

        # 图例
        p.setPen(QColor("#aaa"))
        legend = [("平", "#43a047"), ("缓", "#ffd54f"), ("陡", "#e53935")]
        lx = ml
        ly = h - mb + 6
        for label, color in legend:
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRect(lx, ly - 8, 12, 8)
            p.setPen(QColor("#aaa"))
            p.drawText(QPointF(lx + 15, ly), label)
            lx += 52

        # 起终点标注
        p.setPen(QColor("#bbb"))
        p.drawText(QPointF(xy(0).x(), base_y - 4), "起")
        p.drawText(QPointF(xy(len(prof) - 1).x() - 10, base_y - 4), "终")
