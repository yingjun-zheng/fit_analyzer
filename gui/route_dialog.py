"""路书分析对话框：导入 GPX → 海拔剖面 + 爬坡分级 + 导出。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from core import route as route_mod
from gui import charts as ch


class RouteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("路书分析（GPX 导入 · 爬坡分级）")
        self.resize(760, 640)
        self._route = None

        lay = QVBoxLayout(self)

        # 顶部操作行
        top = QHBoxLayout()
        self.btn_open = QPushButton("📁 打开 GPX 文件")
        self.btn_open.clicked.connect(self._open)
        self.chk_enrich = QCheckBox("缺海拔时联网补全（Open-Meteo）")
        self.btn_export = QPushButton("📤 导出路书")
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)
        top.addWidget(self.btn_open)
        top.addWidget(self.chk_enrich)
        top.addStretch(1)
        top.addWidget(self.btn_export)
        lay.addLayout(top)

        # 指标卡区（动态填充）
        self.summary_label = QLabel("打开一个 GPX 路书文件，自动分析海拔与爬坡。")
        self.summary_label.setWordWrap(True)
        lay.addWidget(self.summary_label)

        # 图表区
        self.chart_container = QVBoxLayout()
        lay.addLayout(self.chart_container, 1)

        # 爬坡段列表
        self.climb_label = QLabel("")
        self.climb_label.setWordWrap(True)
        lay.addWidget(self.climb_label)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 GPX 路书", "", "GPX 文件 (*.gpx)")
        if not path:
            return
        try:
            self._route = route_mod.parse_gpx(path, enrich_elevation=self.chk_enrich.isChecked())
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))
            return
        self.btn_export.setEnabled(True)
        self._render()

    def _render(self):
        r = self._route
        # 摘要
        self.summary_label.setText(
            f"<b>{r['name']}</b>　·　里程 {r['total_distance_km']} km　·　"
            f"爬升 {r['total_ascent_m']} m　·　海拔 {r['ele_min_m']}~{r['ele_max_m']} m"
        )

        # 海拔剖面图
        self._clear_layout(self.chart_container)
        prof = r["elevation_profile"]
        if prof:
            xs = [p["dist_km"] for p in prof]
            ys = [p["ele_m"] for p in prof]
            view = ch.line_chart("海拔剖面", xs, ys, color="#1e88e5",
                                 y_label="海拔 (m)", height=280, fmt="%.0f")
            self.chart_container.addWidget(view)
        else:
            self.chart_container.addWidget(QLabel("该路书无海拔数据，无法绘制剖面。"))

        # 爬坡段
        climbs = r.get("climbs", [])
        if climbs:
            lines = [f"<b>爬坡段（{len(climbs)} 段）：</b>"]
            for i, c in enumerate(climbs, 1):
                cat = c.get("category") or "未分级"
                lines.append(
                    f"{i}. {cat} {c['category_name']}　{c['start_km']}~{c['end_km']}km　"
                    f"长 {c['length_km']}km　爬 {c['gain_m']}m　坡 {c['avg_gradient_pct']}%"
                )
            self.climb_label.setText("<br>".join(lines))
        else:
            self.climb_label.setText("无明显爬坡段（多为平路或缓坡）。")

    def _export(self):
        if not self._route:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出路书", "路书.gpx", "GPX 文件 (*.gpx)")
        if not path:
            return
        try:
            out = route_mod.export_route_gpx(self._route, path)
            QMessageBox.information(self, "导出成功", f"已导出到：\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
