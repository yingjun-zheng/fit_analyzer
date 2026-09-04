"""输入内容自动规划路书：自然语言需求 → 分段接力 → 休息点标定 → 完整路书。

提供自然语言输入（AI 拆解）+ 表单兜底。规划在后台线程执行，避免阻塞 UI。
"""
import json
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QComboBox,
)


class _PlanWorker(QThread):
    done = Signal(object)   # 成功传 result dict，失败传 str
    progress = Signal(int, int, str)

    def __init__(self, key, params, parent=None):
        super().__init__(parent)
        self._key = key
        self._params = params

    def run(self):
        from core import route_long_plan
        try:
            result = route_long_plan.plan_long_route(
                self._key,
                self._params["origin"], self._params["dest"],
                segment_km=self._params.get("segment_km", 30),
                rest_type=self._params.get("rest_type", "便利店"),
                name=self._params.get("name", "规划路线"),
                enrich=self._params.get("enrich", False),
                progress_cb=lambda s, t, m: self.progress.emit(s, t, m),
            )
            self.done.emit(result)
        except Exception as e:
            self.done.emit(f"规划失败：{e}")


class AutoPlanDialog(QDialog):
    def __init__(self, config, ai_client_factory=None, ai_enabled=False, parent=None):
        super().__init__(parent)
        self.config = config
        self._ai_factory = ai_client_factory
        self._ai_enabled = ai_enabled
        self._worker = None
        self.setWindowTitle("输入内容自动规划路书（长途/跨市）")
        self.resize(560, 520)

        lay = QVBoxLayout(self)

        tip = QLabel(
            "一句话描述骑行需求，AI 自动拆解并规划路线、标定休息点。\n"
            "例：「从北京到天津走国道，每 35 公里休息一次，要在有补给的地方」")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # 自然语言输入
        self.ed_text = QPlainTextEdit()
        self.ed_text.setPlaceholderText("输入需求，如：从北京到天津走国道，每35公里休息，要有补给点")
        self.ed_text.setMaximumHeight(80)
        lay.addWidget(self.ed_text)

        btn_ai = QPushButton("🤖 AI 拆解需求")
        btn_ai.setObjectName("primary")
        btn_ai.clicked.connect(self._ai_parse)
        lay.addWidget(btn_ai)

        # 表单兜底（AI 失败或想手动填时用）
        sep = QLabel("—— 或手动填写 ——")
        sep.setObjectName("muted")
        sep.setAlignment(Qt.AlignCenter)
        lay.addWidget(sep)

        self.ed_origin = QLineEdit()
        self.ed_origin.setPlaceholderText("起点（地名或「lon,lat」）")
        self.ed_dest = QLineEdit()
        self.ed_dest.setPlaceholderText("终点")
        self.ed_seg = QLineEdit("30")
        self.ed_seg.setPlaceholderText("单段最大里程 km（你的体能阈值）")
        self.cb_rest = QComboBox()
        self.cb_rest.addItems(["便利店", "超市", "餐馆", "加油站", "住宿", "药店"])

        lay.addWidget(QLabel("起点"))
        lay.addWidget(self.ed_origin)
        lay.addWidget(QLabel("终点"))
        lay.addWidget(self.ed_dest)
        lay.addWidget(QLabel("单段里程 km"))
        lay.addWidget(self.ed_seg)
        lay.addWidget(QLabel("休息点类型"))
        lay.addWidget(self.cb_rest)

        btn_plan = QPushButton("🧭 开始规划")
        btn_plan.setObjectName("primary")
        btn_plan.clicked.connect(self._plan)
        lay.addWidget(btn_plan)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self._result = None

    def _ai_parse(self):
        text = self.ed_text.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先输入需求描述")
            return
        if not self._ai_factory or not self._ai_enabled:
            QMessageBox.information(self, "提示", "请先在「设置」中启用并配置 AI")
            return
        self.status.setStyleSheet("color: #888;")
        self.status.setText("AI 正在拆解需求…")
        try:
            from core import route_ai_plan
            params = route_ai_plan.parse_requirement(self._ai_factory(), text)
        except Exception:
            params = None
        if not params:
            self.status.setStyleSheet("color: #c62828;")
            self.status.setText("AI 拆解失败，请用下方表单手动填写。")
            return
        self.ed_origin.setText(params.get("origin_city") or "")
        self.ed_dest.setText(params.get("dest_city") or "")
        self.ed_seg.setText(str(params.get("segment_km") or 30))
        rest = params.get("rest_type") or "便利店"
        idx = self.cb_rest.findText(rest)
        if idx >= 0:
            self.cb_rest.setCurrentIndex(idx)
        self.status.setStyleSheet("")
        self.status.setText(f"已解析：{params.get('origin_city')} → {params.get('dest_city')}，单段 {params.get('segment_km')}km")

    def _plan(self):
        key = (self.config.get("amap_web_key") or "").strip()
        if not key:
            QMessageBox.information(self, "提示", "请先在「设置」中配置高德 Web服务 Key")
            return
        origin = self.ed_origin.text().strip()
        dest = self.ed_dest.text().strip()
        if not origin or not dest:
            QMessageBox.information(self, "提示", "请填写起点和终点")
            return
        try:
            seg = int(self.ed_seg.text().strip() or "30")
        except ValueError:
            seg = 30

        params = {
            "origin": origin, "dest": dest,
            "segment_km": seg,
            "rest_type": self.cb_rest.currentText(),
            "name": f"{origin} → {dest}",
        }
        self.status.setStyleSheet("color: #888;")
        self.status.setText("规划中…")
        self._worker = _PlanWorker(key, params, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, step, total, msg):
        self.status.setText(f"[{step}/{total}] {msg}")

    def _on_done(self, payload):
        if isinstance(payload, str):
            self.status.setStyleSheet("color: #c62828;")
            self.status.setText(payload)
            return

        self._result = payload
        r = payload.get("route")
        if not r or not isinstance(r, dict) or not r.get("points"):
            self.status.setStyleSheet("color: #c62828;")
            self.status.setText("规划失败：路线数据不完整")
            return

        rp = payload.get("rest_points") or []
        lines = [
            f"规划完成：{r.get('total_distance_km', '?')} km，共 {len(payload.get('segments', []))} 段",
        ]
        if rp:
            lines.append("休息点：")
            for p in rp:
                lines.append(f"  · {p.get('at_km', '?')}km 处：{p.get('name', '?')}")
        self.status.setStyleSheet("")
        self.status.setText("\n".join(lines))

        # 弹出路书分析对话框展示完整路书
        try:
            from gui.route_dialog import RouteDialog
            dlg = RouteDialog(self, ai_client_factory=self._ai_factory,
                              ai_enabled=self._ai_enabled)
            dlg.load_route(r)
            dlg.exec()
        except Exception as e:
            self.status.setStyleSheet("color: #c62828;")
            self.status.setText(f"路书展示失败：{e}")
