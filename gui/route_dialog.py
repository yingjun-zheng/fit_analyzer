"""路书分析对话框：导入 GPX → 海拔剖面（爬坡段高亮）+ 爬坡分级 + AI 解读 + 导出。"""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from core import route as route_mod
from gui import charts as ch


class _AnalyzeWorker(QThread):
    """后台调用 AI 解读路书，避免阻塞 UI。"""
    done = Signal(object)  # 成功传 str，失败传 None

    def __init__(self, factory, route, question, parent=None):
        super().__init__(parent)
        self._factory = factory
        self._route = route
        self._question = question

    def run(self):
        from core import route_ai
        answer = route_ai.analyze_route(self._factory(), self._route, self._question)
        self.done.emit(answer)


class RouteDialog(QDialog):
    def __init__(self, parent=None, ai_client_factory=None, ai_enabled=False):
        super().__init__(parent)
        self.setWindowTitle("路书分析（GPX 导入 · 爬坡分级 · AI 解读）")
        self.resize(760, 720)
        self._route = None
        self._ai_factory = ai_client_factory
        self._ai_enabled = ai_enabled
        self._worker = None

        lay = QVBoxLayout(self)

        # 顶部操作行
        top = QHBoxLayout()
        self.btn_open = QPushButton("📁 打开 GPX 文件")
        self.btn_open.clicked.connect(self._open)
        self.chk_enrich = QCheckBox("缺海拔时联网补全（Open-Meteo）")
        self.btn_export = QPushButton("📤 导出路书")
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)
        self.btn_ai = QPushButton("🤖 AI 解读路书")
        self.btn_ai.clicked.connect(self._ai_analyze)
        self.btn_ai.setEnabled(False)
        top.addWidget(self.btn_open)
        top.addWidget(self.chk_enrich)
        top.addStretch(1)
        top.addWidget(self.btn_ai)
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

        # AI 解读区
        self.ai_label = QLabel("")
        self.ai_label.setWordWrap(True)
        self.ai_label.setTextFormat(Qt.RichText)
        lay.addWidget(self.ai_label)

    def load_route(self, route):
        """直接加载一个已解析的 route dict 并渲染（供「历史活动转路书」复用）。"""
        self._route = route
        self.btn_export.setEnabled(True)
        self.btn_ai.setEnabled(bool(self._ai_factory) and self._ai_enabled)
        self.ai_label.setText("")
        self._render()

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
        self.btn_ai.setEnabled(bool(self._ai_factory) and self._ai_enabled)
        self.ai_label.setText("")
        self._render()

    def _render(self):
        r = self._route
        # 摘要
        self.summary_label.setText(
            f"<b>{r['name']}</b>　·　里程 {r['total_distance_km']} km　·　"
            f"爬升 {r['total_ascent_m']} m　·　海拔 {r['ele_min_m']}~{r['ele_max_m']} m"
        )

        # 海拔剖面图（含爬坡段色带高亮）
        self._clear_layout(self.chart_container)
        prof = r["elevation_profile"]
        if prof:
            xs = [p["dist_km"] for p in prof]
            ys = [p["ele_m"] for p in prof]
            view = ch.elevation_chart_with_climbs(
                "海拔剖面（爬坡段高亮）", xs, ys, r.get("climbs", []),
                color="#1e88e5", y_label="海拔 (m)", height=300, fmt="%.0f")
            self.chart_container.addWidget(view)
        else:
            self.chart_container.addWidget(QLabel("该路书无海拔数据，无法绘制剖面。"))

        # 3D 路线景观（坡度着色立体路线）
        if prof:
            from gui.route_3d import Route3DWidget
            try:
                t3d = QLabel("3D 路线景观（坡度着色）")
                t3d.setObjectName("h3")
                self.chart_container.addWidget(t3d)
                w3d = Route3DWidget()
                w3d.set_profile(prof)
                self.chart_container.addWidget(w3d)
            except Exception:
                pass

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

    def _ai_analyze(self):
        if not self._route or not self._ai_factory:
            return
        if not self._ai_enabled:
            QMessageBox.information(self, "提示", "请先在「设置」中启用并配置 AI")
            return
        self.btn_ai.setEnabled(False)
        self.ai_label.setStyleSheet("color: #888;")
        self.ai_label.setText("AI 分析中，请稍候…")
        self._worker = _AnalyzeWorker(self._ai_factory, self._route, None, self)
        self._worker.done.connect(self._on_ai_done)
        self._worker.start()

    def _on_ai_done(self, answer):
        self.btn_ai.setEnabled(True)
        if answer:
            self.ai_label.setStyleSheet("")
            self.ai_label.setText(f"<b>AI 难度解读：</b><br>{answer}")
        else:
            self.ai_label.setStyleSheet("color: #c62828;")
            self.ai_label.setText("AI 解读失败（请检查 AI 配置或网络）。")

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
