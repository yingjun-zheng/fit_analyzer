"""轨迹控件：固定背景图片 + 轨迹叠加（QPainter 绘制，纯桌面无浏览器）。

轨迹画完后有一个 🚴 骑手沿路线循环骑行（时间驱动、可暂停），增添一点趣味。
"""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

MARGIN = 0.08  # 轨迹在背景图中的留白比例
ANIM_INTERVAL_MS = 16  # 起点→终点绘制动画的帧间隔
RIDER_INTERVAL_MS = 33  # 骑手动画帧间隔（约 30fps）

_BTN_QSS = (
    "QPushButton{background:rgba(15,17,21,185);color:#fff;border:none;"
    "border-radius:17px;font-size:15px;padding:0px;}"
    "QPushButton:hover{background:rgba(15,17,21,225);}"
)


class TrackWidget(QWidget):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self.pixmap = QPixmap(image_path)
        self.points = []  # [(lat, lon, alt), ...]
        self._progress = 1.0  # 轨迹绘制进度 0→1（起点→终点动画）
        self._anim_duration = 1200
        self._anim = QTimer(self)
        self._anim.setInterval(ANIM_INTERVAL_MS)
        self._anim.timeout.connect(self._tick)
        # ---- 🚴 骑手循环动画：绘制动画结束后启动 ----
        self._rider_timer = QTimer(self)
        self._rider_timer.setInterval(RIDER_INTERVAL_MS)
        self._rider_timer.timeout.connect(self._rider_tick)
        self._rider_elapsed_ms = 0
        self._rider_total_ms = 30000  # 骑一整圈的时长（随点数自适应）
        self._rider_paused = False
        # 浮动控制按钮：暂停/继续骑手
        self._btn = QPushButton("⏸", self)
        self._btn.setFixedSize(34, 34)
        self._btn.setToolTip("暂停 / 继续 骑行小人")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setStyleSheet(_BTN_QSS)
        self._btn.clicked.connect(self._toggle_rider)
        self._btn.setVisible(False)
        self.setMinimumHeight(460)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_background(self, image_path):
        """切换背景图（换图后保持轨迹并重绘）。"""
        if image_path and image_path != self._image_path:
            self._image_path = image_path
            self.pixmap = QPixmap(image_path)
        self.update()

    def set_track(self, points):
        self.points = [p for p in (points or []) if p[0] is not None and p[1] is not None]
        # 重置骑手状态（切换活动时）
        self._rider_timer.stop()
        self._rider_elapsed_ms = 0
        self._rider_paused = False
        self._btn.setVisible(False)
        # 起点→终点渐进绘制动画，时长随点数自适应（0.8s ~ 2s）
        self._anim_duration = max(800, min(2000, len(self.points)))
        if len(self.points) >= 2:
            self._progress = 0.0
            self._anim.start()
        else:
            self._progress = 1.0
            self._anim.stop()
        self.update()

    def _tick(self):
        step = ANIM_INTERVAL_MS / max(self._anim_duration, 1)
        self._progress = min(1.0, self._progress + step)
        if self._progress >= 1.0:
            self._anim.stop()
            self._start_rider()  # 轨迹画完 → 骑手出发
        self.update()

    # ---------------- 🚴 骑手循环动画 ----------------
    def _start_rider(self):
        if len(self.points) < 2:
            return
        # 一圈时长随点数自适应：15s ~ 45s
        self._rider_total_ms = max(15000, min(45000, len(self.points) * 30))
        self._rider_elapsed_ms = 0
        self._rider_paused = False
        self._btn.setText("⏸")
        self._btn.setVisible(True)
        self._place_btn()
        self._rider_timer.start()
        self.update()

    def _toggle_rider(self):
        if self._rider_paused:
            self._rider_paused = False
            self._btn.setText("⏸")
            self._rider_timer.start()
        else:
            self._rider_paused = True
            self._btn.setText("▶")
            self._rider_timer.stop()

    def _rider_tick(self):
        self._rider_elapsed_ms += RIDER_INTERVAL_MS
        self.update()

    def _place_btn(self):
        self._btn.move(self.width() - self._btn.width() - 10,
                       self.height() - self._btn.height() - 10)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_btn()

    def _rider_pos(self, flat):
        """按已流逝时间计算骑手在轨迹上的（浮点插值）位置。"""
        n = len(flat)
        if n < 2:
            return None
        t = (self._rider_elapsed_ms % self._rider_total_ms) / self._rider_total_ms
        i_f = t * (n - 1)
        k = int(i_f)
        frac = i_f - k
        k2 = min(k + 1, n - 1)
        y = flat[k][0] + (flat[k2][0] - flat[k][0]) * frac
        x = flat[k][1] + (flat[k2][1] - flat[k][1]) * frac
        return y, x

    def _to_flat(self, iw, ih):
        """经纬度 → 背景图像素坐标（按包围盒缩放居中）。返回 [(y, x)]。"""
        pts = self.points
        if len(pts) < 2:
            return []
        lat_min, lat_max = 90.0, -90.0
        lon_min, lon_max = 180.0, -180.0
        for lat, lon, *_ in pts:
            lat_min = min(lat_min, lat)
            lat_max = max(lat_max, lat)
            lon_min = min(lon_min, lon)
            lon_max = max(lon_max, lon)
        span_lat = max(lat_max - lat_min, 1e-6)
        span_lon = max(lon_max - lon_min, 1e-6)
        scale = min(iw * (1 - 2 * MARGIN) / span_lon, ih * (1 - 2 * MARGIN) / span_lat)
        out = []
        for lat, lon, *_ in pts:
            y = ih * MARGIN + (lat_max - lat) * scale
            x = iw * MARGIN + (lon - lon_min) * scale
            out.append((y, x))
        return out

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#f2f4f7"))
        w, h = self.width(), self.height()
        if self.pixmap.isNull():
            p.setPen(QColor("#7a8794"))
            p.drawText(self.rect(), Qt.AlignCenter, "未找到背景图片 back9.jpeg")
            return
        iw, ih = self.pixmap.width(), self.pixmap.height()
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        ox, oy = (w - dw) / 2, (h - dh) / 2
        p.drawPixmap(QRectF(ox, oy, dw, dh), self.pixmap, QRectF(0, 0, iw, ih))
        if len(self.points) < 2:
            p.setPen(QColor("#7a8794"))
            p.drawText(QRectF(ox, oy, dw, dh), Qt.AlignCenter, "无轨迹数据")
            return
        flat = self._to_flat(iw, ih)
        n = len(flat)
        # 按 _progress 渐进绘制（动画结束后画出完整轨迹）
        prog = max(0.0, min(1.0, self._progress))
        count = 1.0 + prog * (n - 1)  # 已画出的“点数”（含小数插值部分）
        k = int(count)
        frac = count - k
        path = QPainterPath()
        path.moveTo(ox + flat[0][1] * scale, oy + flat[0][0] * scale)
        for i in range(1, min(k, n)):
            fy, fx = flat[i]
            path.lineTo(ox + fx * scale, oy + fy * scale)
        head = flat[k - 1] if k >= 1 else flat[0]
        if frac > 0 and k < n:
            fy0, fx0 = flat[k - 1]
            fy1, fx1 = flat[k]
            hy = fy0 + (fy1 - fy0) * frac
            hx = fx0 + (fx1 - fx0) * frac
            path.lineTo(ox + hx * scale, oy + hy * scale)
            head = (hy, hx)
        p.setPen(QPen(QColor("#1e88e5"), 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)

        def dot(yx, color):
            sy, sx = oy + yx[0] * scale, ox + yx[1] * scale
            p.setBrush(QColor(color))
            p.setPen(QPen(QColor("white"), 2))
            p.drawEllipse(QRectF(sx - 6, sy - 6, 12, 12))

        dot(flat[0], "#2e7d32")
        if prog >= 1.0:
            dot(flat[-1], "#e53935")
            self._draw_rider(p, flat, ox, oy, scale)
        else:
            # 动画进行中：画一个随轨迹移动的“骑手”点
            sy, sx = oy + head[0] * scale, ox + head[1] * scale
            p.setBrush(QColor("#1e88e5"))
            p.setPen(QPen(QColor("white"), 2))
            p.drawEllipse(QRectF(sx - 7, sy - 7, 14, 14))

    def _draw_rider(self, p, flat, ox, oy, scale):
        """轨迹画完后：🚴 骑手沿路线循环骑行。"""
        pos = self._rider_pos(flat)
        if pos is None:
            return
        sy, sx = oy + pos[0] * scale, ox + pos[1] * scale
        # 地面小椭圆底座：白底蓝边，任何背景都清晰可见（emoji 渲染异常时仍能定位骑手）
        p.setBrush(QColor(255, 255, 255, 215))
        p.setPen(QPen(QColor("#1e88e5"), 2))
        p.drawEllipse(QRectF(sx - 7, sy - 2, 14, 6))
        p.setFont(QFont("Segoe UI Emoji", 19))
        p.drawText(QRectF(sx - 18, sy - 40, 36, 36), Qt.AlignCenter, "🚴")
