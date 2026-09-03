"""对话框：设置、日志。"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from core import logging_setup


def _parse_float_list(text):
    out = []
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None, on_reidentify=None, db=None):
        super().__init__(parent)
        self.config = config
        self._on_reidentify = on_reidentify
        self._db = db
        self.setWindowTitle("设置")
        self.setMinimumWidth(480)
        d = config.public_dict()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.edHrPcts = QLineEdit(",".join(str(x) for x in (d.get("hr_zone_pcts") or [])))
        self.edHrMax = QLineEdit(str(d.get("hr_max_override") or 0))
        self.edSpeed = QLineEdit(",".join(str(x) for x in (d.get("speed_zone_kmh") or [])))
        self.edCad = QLineEdit(",".join(str(x) for x in (d.get("cadence_zone_rpm") or [])))
        form.addRow("心率区间边界 %（逗号分隔）", self.edHrPcts)
        form.addRow("最大心率覆盖值（0=自动）", self.edHrMax)
        form.addRow("速度区间边界 km/h", self.edSpeed)
        form.addRow("踏频区间边界 rpm", self.edCad)

        self.chkAi = QCheckBox("启用 AI 分析")
        self.edBase = QLineEdit(d.get("ai_base_url") or "")
        self.edKey = QLineEdit(d.get("ai_api_key") or "")
        self.edKey.setEchoMode(QLineEdit.Password)
        self.edModel = QLineEdit(d.get("ai_model") or "")
        self.edTemp = QLineEdit(str(d.get("ai_temperature") or 0.4))
        self.edTimeout = QLineEdit(str(d.get("ai_timeout") or 120))
        self.chkAi.setChecked(bool(d.get("ai_enabled")))
        form.addRow(self.chkAi)
        form.addRow("接口地址（OpenAI 兼容）", self.edBase)
        form.addRow("API Key（本地模型留空）", self.edKey)
        form.addRow("模型名称", self.edModel)
        form.addRow("温度", self.edTemp)
        form.addRow("超时（秒）", self.edTimeout)

        tip = QLabel("支持 Ollama / LM Studio / vLLM 等本地模型，或 DeepSeek / OpenAI 等远程接口（用自己的 Key）。")
        tip.setObjectName("muted")
        tip.setWordWrap(True)

        # FTP（功能阈值功率）：手动填 + 从最近活动自动估算
        ftp_title = QLabel("FTP（功能阈值功率）")
        ftp_title.setObjectName("h3")
        form.addRow(ftp_title)
        self.edFtp = QLineEdit(str(d.get("ftp_w") or ""))
        self.edFtp.setPlaceholderText("手动填写 FTP，单位 W（0 或留空 = 未设置）")
        form.addRow("FTP (W)", self.edFtp)
        ftp_row = QHBoxLayout()
        self.btnEstFtp = QPushButton("🧮 从最近活动估算 FTP")
        self.btnEstFtp.clicked.connect(self._estimate_ftp)
        ftp_row.addWidget(self.btnEstFtp)
        self.lblFtpEst = QLabel("")
        self.lblFtpEst.setObjectName("muted")
        self.lblFtpEst.setWordWrap(True)
        ftp_row.addWidget(self.lblFtpEst, 1)
        form.addRow("", ftp_row)

        # 设备型号表：新码表可在此手动登记（厂商/产品码 = 型号名）
        dm = d.get("device_models") or {}
        self.edDevice = QPlainTextEdit()
        self.edDevice.setPlainText("\n".join(f"{k} = {v}" for k, v in dm.items()))
        self.edDevice.setPlaceholderText("每行一个：厂商/产品码 = 型号名\n例：\nbryton/1801 = 百锐腾 Rider 15\nmagene/310 = C606 Pro")
        self.edDevice.setMaximumHeight(110)
        form.addRow("设备型号表（新码表登记）", self.edDevice)

        # 重新识别按钮：改完型号表后点击，立即按新表重算所有活动的型号
        if on_reidentify is not None:
            reid_row = QHBoxLayout()
            reid_btn = QPushButton("🔄 立即按型号表重新识别所有设备")
            reid_btn.clicked.connect(self._do_reidentify)
            reid_row.addWidget(reid_btn)
            reid_row.addStretch(1)
            reid_tip = QLabel("保存后生效，或点此立即重算。")
            reid_tip.setObjectName("muted")
            form.addRow("", reid_row)

        # 高德地图（在线轨迹地图，可选）
        amap_title = QLabel("高德地图（在线轨迹地图，可选）")
        amap_title.setObjectName("h3")
        form.addRow(amap_title)
        self.edAmapKey = QLineEdit(d.get("amap_key") or "")
        self.edAmapKey.setPlaceholderText("高德开放平台申请的 Web端(JS API) Key")
        self.edAmapSec = QLineEdit(d.get("amap_security") or "")
        self.edAmapSec.setEchoMode(QLineEdit.Password)
        self.edAmapSec.setPlaceholderText("安全密钥 securityJsCode（设置页生成）")
        form.addRow("高德 Key", self.edAmapKey)
        form.addRow("安全密钥", self.edAmapSec)
        amap_tip = QLabel("配置后「轨迹」页显示真实地图轨迹；不配置则保留原固定背景图示意轨迹。")
        amap_tip.setObjectName("muted")
        amap_tip.setWordWrap(True)
        form.addRow(amap_tip)

        # 高德路径规划（Web服务 Key，与上面的 JS API Key 是不同类型）
        plan_title = QLabel("高德路径规划（可选）")
        plan_title.setObjectName("h3")
        form.addRow(plan_title)
        self.edAmapWebKey = QLineEdit(d.get("amap_web_key") or "")
        self.edAmapWebKey.setPlaceholderText("高德开放平台申请的 Web服务 Key（用于骑行路径规划）")
        form.addRow("Web服务 Key", self.edAmapWebKey)
        plan_tip = QLabel("注意：此 Key 与上方「高德 Key(JS API)」是不同类型，需在高德控制台单独申请「Web服务」类型。")
        plan_tip.setObjectName("muted")
        plan_tip.setWordWrap(True)
        form.addRow(plan_tip)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(tip)
        lay.addWidget(buttons)

    def _estimate_ftp(self):
        """从数据库中最近的一次活动估算 FTP（用估功率补全，无功率计时）。"""
        if self._db is None:
            self.lblFtpEst.setText("无法估算：未连数据库")
            return
        try:
            from core import analysis, ftp_estimate
            acts = self._db.list_activities(limit=20)
            if not acts:
                self.lblFtpEst.setText("无活动数据，请先导入 FIT")
                return
            # 找最近一条有足够时长的活动
            chosen = None
            chosen_recs = None
            for a in acts:
                recs = self._db.get_records(a["id"])
                if len(recs) >= 300:  # 至少约 5 分钟
                    chosen = a
                    chosen_recs = recs
                    break
            if chosen is None:
                self.lblFtpEst.setText("无足够时长的活动（需 ≥5 分钟）")
                return
            recs = analysis.estimate_power(chosen_recs, self.config)
            est = ftp_estimate.estimate_ftp(recs, self.config)
            if not est:
                self.lblFtpEst.setText("该活动无有效功率数据，无法估算")
                return
            self.edFtp.setText(str(est["ftp_w"]))
            self.lblFtpEst.setText(
                f"已按「{chosen['name']}」估算：最佳20分钟 {est['best_20min_w']}W → FTP {est['ftp_w']}W"
                + (f"（{est['wkg']} W/kg）" if est.get("wkg") else "")
            )
        except Exception as e:
            self.lblFtpEst.setText(f"估算失败：{e}")

    def _do_reidentify(self):
        """先保存当前设置（含型号表），再触发主窗口重新识别所有设备。"""
        self._save()
        if self._on_reidentify is not None:
            self._on_reidentify()

    def _save(self):
        try:
            hr_max = int(self.edHrMax.text().strip() or "0")
        except ValueError:
            hr_max = 0
        try:
            temp = float(self.edTemp.text().strip() or "0.4")
        except ValueError:
            temp = 0.4
        try:
            timeout = int(self.edTimeout.text().strip() or "120")
        except ValueError:
            timeout = 120
        # 设备型号表解析：每行 "厂商/产品码 = 型号名"
        device_models = {}
        try:
            ftp_w = int(self.edFtp.text().strip() or "0")
        except ValueError:
            ftp_w = 0
        for line in self.edDevice.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
            elif " " in line:
                k, v = line.split(None, 1)
            else:
                continue
            k = k.strip()
            v = v.strip()
            if k and v and "/" in k:
                device_models[k] = v
        self.config.update({
            "hr_zone_pcts": _parse_float_list(self.edHrPcts.text()),
            "hr_max_override": hr_max,
            "speed_zone_kmh": _parse_float_list(self.edSpeed.text()),
            "cadence_zone_rpm": _parse_float_list(self.edCad.text()),
            "ai_enabled": self.chkAi.isChecked(),
            "ai_base_url": self.edBase.text().strip(),
            "ai_api_key": self.edKey.text().strip(),
            "ai_model": self.edModel.text().strip(),
            "ai_temperature": temp,
            "ai_timeout": timeout,
            "device_models": device_models,
            "ftp_w": ftp_w,
            "amap_key": self.edAmapKey.text().strip(),
            "amap_security": self.edAmapSec.text().strip(),
            "amap_web_key": self.edAmapWebKey.text().strip(),
        })
        self.accept()


class LogsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("日志")
        self.resize(760, 460)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        btn_refresh = QPushButton("刷新")
        btn_clear = QPushButton("清空内存日志")
        btn_clear.setObjectName("danger")
        btn_close = QPushButton("关闭")
        btn_refresh.clicked.connect(self.refresh)
        btn_clear.clicked.connect(self.clear)
        btn_close.clicked.connect(self.accept)
        bar = QHBoxLayout()
        bar.addWidget(btn_refresh)
        bar.addWidget(btn_clear)
        bar.addStretch(1)
        bar.addWidget(btn_close)
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.view)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        items = logging_setup.get_ring(500)
        lines = []
        for ts, level, msg in items:
            import time

            hh = time.strftime("%H:%M:%S", time.localtime(ts))
            lines.append(f"{hh}  {level:<5}  {msg}")
        self.view.setPlainText("\n".join(lines))
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear(self):
        logging_setup.clear_ring()
        self.refresh()

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)
