"""轨迹控件：固定背景图片 + 轨迹叠加（QPainter 绘制，纯桌面无浏览器）。"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

MARGIN = 0.08  # 轨迹在背景图中的留白比例


class TrackWidget(QWidget):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self.pixmap = QPixmap(image_path)
        self.points = []  # [(lat, lon, alt), ...]
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
        self.update()

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
        path = QPainterPath()
        for i, (fy, fx) in enumerate(flat):
            sx, sy = ox + fx * scale, oy + fy * scale
            if i == 0:
                path.moveTo(sx, sy)
            else:
                path.lineTo(sx, sy)
        p.setPen(QPen(QColor("#1e88e5"), 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)

        def dot(yx, color):
            sy, sx = oy + yx[0] * scale, ox + yx[1] * scale
            p.setBrush(QColor(color))
            p.setPen(QPen(QColor("white"), 2))
            p.drawEllipse(QRectF(sx - 6, sy - 6, 12, 12))

        dot(flat[0], "#2e7d32")
        dot(flat[-1], "#e53935")
