"""AI 训练助手浮层面板：跟随主窗口右侧的独立浮窗（不挤压中央布局）。

设计要点：
- 顶层 Tool 浮窗（无边框、圆角深色卡片），打开/关闭时**覆盖**在内容区
  右缘，中央布局完全不变——解决 QDockWidget 侧栏挤压问题。
- 自包含多轮会话 + 流式输出 + Action 确认的全部交互逻辑；
  复用主窗口的后台任务（_run_worker）、数据库与 AI 客户端。
- 关闭后从主窗口工具栏「🤖 AI 助手」或快捷键 Ctrl+B 找回。
"""
import datetime
import logging
import queue

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import month_agent

log = logging.getLogger("fit.aipanel")

_PANEL_QSS = """
#aiPanel {
    background: #1a2027;
    border: 1px solid #2b3744;
    border-radius: 12px;
}
#aiPanel QLabel#muted { color: #8b98a5; }
#aiPanel QTextEdit {
    background: #141a20; color: #dbe4ec; border: 1px solid #2b3744;
    border-radius: 8px; font-size: 13px;
}
#aiPanel QLineEdit {
    background: #141a20; color: #dbe4ec; border: 1px solid #2b3744;
    border-radius: 8px; padding: 6px 8px; font-size: 13px;
}
#aiPanel QPushButton {
    background: #26303b; color: #dbe4ec; border: none;
    border-radius: 8px; padding: 6px 10px; font-size: 13px;
}
#aiPanel QPushButton:hover { background: #33404d; }
#aiPanel QPushButton#primary { background: #1e6fd9; color: #fff; font-weight: 600; }
#aiPanel QPushButton#primary:hover { background: #2a7ee8; }
#aiPanel QPushButton#closeBtn { padding: 2px 7px; font-size: 14px; }
"""

_TOOL_CN = {
    "get_month_overview": "月度概览", "get_month_activities": "活动列表",
    "get_month_distance_trend": "里程趋势", "get_month_hr_summary": "心率汇总",
    "get_month_speed_summary": "速度汇总", "get_month_device_summary": "设备统计",
    "get_training_load": "训练负荷", "compare_activities": "活动对比",
    "get_fitness_summary": "体能指标", "get_gear_status": "装备台账",
}


class AiAssistantPanel(QWidget):
    """AI 训练助手浮窗（多轮会话 / 流式 / Action 确认）。"""

    PANEL_WIDTH = 348

    def __init__(self, main_window):
        super().__init__(main_window, Qt.Tool | Qt.FramelessWindowHint)
        self._mw = main_window
        self.setObjectName("aiPanel")
        self.setStyleSheet(_PANEL_QSS)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)

        # ---- 会话状态（面板常驻，页面切换不丢失）----
        self.history = []              # user/assistant 精华对
        self._activity = None          # 当前关联的活动（P1-A：选中活动时由主窗口注入）
        self._events = queue.Queue()   # worker → 主线程 流式事件
        self._confirm_queue = queue.Queue()
        self._confirm_showing = False
        self._think_buf = ""
        self._answer_buf = ""
        self._tool_rows = []
        self._poll = QTimer(self)
        self._poll.setInterval(80)
        self._poll.timeout.connect(self._drain)

        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        # 标题行：标题 + 收起按钮
        head = QHBoxLayout()
        title = QLabel("🤖 AI 训练助手")
        title.setObjectName("h2")
        head.addWidget(title)
        head.addStretch(1)
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.setToolTip("收起（工具栏「🤖 AI 助手」或 Ctrl+B 可再打开）")
        self.btn_close.clicked.connect(self.hide_panel)
        head.addWidget(self.btn_close)
        lay.addLayout(head)

        self.scope = QLabel("当前范围：—")
        self.scope.setObjectName("muted")
        lay.addWidget(self.scope)

        # 关联活动上下文条（选中活动时显示，可一键清除）
        self.ctx_bar = QWidget()
        ctx_lay = QHBoxLayout(self.ctx_bar)
        ctx_lay.setContentsMargins(0, 0, 0, 0)
        ctx_lay.setSpacing(4)
        self.ctx_label = QLabel("")
        self.ctx_label.setObjectName("muted")
        self.ctx_label.setWordWrap(True)
        self.btn_clear_ctx = QPushButton("✕")
        self.btn_clear_ctx.setFixedWidth(24)
        self.btn_clear_ctx.setToolTip("清除活动关联，回到按月份回答")
        self.btn_clear_ctx.clicked.connect(self.clear_activity)
        ctx_lay.addWidget(self.ctx_label, 1)
        ctx_lay.addWidget(self.btn_clear_ctx)
        self.ctx_bar.setVisible(False)
        lay.addWidget(self.ctx_bar)

        # 输入行：总结本月 + 提问 + 新对话
        row1 = QHBoxLayout()
        self.btn_summary = QPushButton("📝 总结本月")
        self.btn_summary.setToolTip("一键生成当前月份的 AI 训练总结")
        self.btn_summary.clicked.connect(self.ask_summary)
        self.btn_review = QPushButton("🚴 复盘本次骑行")
        self.btn_review.setToolTip("针对当前关联活动做单次复盘（功率/心率/踏频分区点评）")
        self.btn_review.clicked.connect(self.ask_review)
        self.btn_review.setVisible(False)
        self.btn_new = QPushButton("🆕")
        self.btn_new.setToolTip("新对话（切换月份也会自动重置）")
        self.btn_new.clicked.connect(self.new_session)
        row1.addWidget(self.btn_summary)
        row1.addWidget(self.btn_review)
        row1.addWidget(self.btn_new)
        row1.addStretch(1)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("提问或让 AI 帮你操作，例如：\n本月爬坡多吗？我该不该休息？帮我把 FTP 设为 250W")
        self.input.returnPressed.connect(self.ask)
        self.btn_ask = QPushButton("提问")
        self.btn_ask.setObjectName("primary")
        self.btn_ask.clicked.connect(self.ask)
        row2.addWidget(self.input, 1)
        row2.addWidget(self.btn_ask)
        lay.addLayout(row2)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText(
            "在这里与 AI 对话（数据仅本机，提问时才调用 AI）。\n\n"
            "· 自由提问：本月训练量如何？那 8 月呢？\n"
            "· 专项分析：我该不该休息？和上次比进步了吗？\n"
            "· 让 AI 干活：帮我把 FTP 设为 250W（会弹确认）")
        lay.addWidget(self.output, 1)

    # ---------------- 对外接口（主窗口调用） ----------------
    def set_scope(self, text):
        self.scope.setText(text)

    # ---------------- 活动上下文（P1-A） ----------------
    @staticmethod
    def _activity_month(act):
        return act.get("month") or (act.get("start_time") or "")[:7] or None

    def set_activity(self, act):
        """主窗口选中活动时注入上下文：之后的提问锚定这次骑行。"""
        if not act:
            return self.clear_activity()
        self._activity = act
        self.ctx_label.setText(
            f"🎯 关联活动：{act.get('name')} · {(act.get('start_time') or '')[:10]}"
            f" · {act.get('distance_km')}km")
        self.ctx_bar.setVisible(True)
        self.btn_review.setVisible(True)
        month = self._activity_month(act)
        if month:
            self.set_scope(f"当前范围：活动《{act.get('name')}》（数据取自 {month}）")

    def clear_activity(self):
        self._activity = None
        self.ctx_bar.setVisible(False)
        self.btn_review.setVisible(False)

    def _activity_prefix(self, act):
        """给提问加活动锚定前缀（模型仍可用月份工具查更多数据）。"""
        parts = [f"活动《{act.get('name')}》",
                 f"日期 {(act.get('start_time') or '')[:16]}",
                 "通勤骑行" if act.get("commute") else "训练骑行"]
        if act.get("distance_km") is not None:
            parts.append(f"距离 {act['distance_km']}km")
        if act.get("moving_h") is not None:
            parts.append(f"骑行 {act['moving_h']}h")
        if act.get("avg_speed_kmh"):
            parts.append(f"均速 {act['avg_speed_kmh']}km/h（最大 {act.get('max_speed_kmh') or '—'}）")
        if act.get("total_ascent_m"):
            parts.append(f"爬升 {act['total_ascent_m']}m")
        if act.get("avg_hr"):
            parts.append(f"均心率 {act['avg_hr']}bpm")
        if act.get("avg_cad"):
            parts.append(f"均踏频 {act['avg_cad']}rpm")
        if act.get("avg_power"):
            parts.append(f"均功率 {act['avg_power']}W"
                         + ("（估算）" if act.get("power_estimated") else ""))
        if act.get("calories"):
            parts.append(f"消耗 {act['calories']}kcal")
        return "【当前选中的活动】" + "，".join(parts) + "。请优先围绕这次骑行回答。"

    def reset_session(self):
        """切换月份时调用：清空会话（旧月上下文不再有效）。"""
        self.history = []
        self.input.clear()

    def reposition(self):
        """跟随主窗口：定位在内容区右缘，不参与布局（覆盖式）。"""
        g = self._mw.geometry()
        w = self.PANEL_WIDTH
        self.setGeometry(g.x() + g.width() - w - 12, g.y() + 12, w, g.height() - 24)

    def show_panel(self):
        self.reposition()
        self.show()
        self.input.setFocus()

    def hide_panel(self):
        self.hide()

    def toggle_panel(self):
        if self.isVisible():
            self.hide_panel()
        else:
            self.show_panel()

    # ---------------- 交互 ----------------
    def _current_month(self):
        title = self._mw.mv_title.text() if hasattr(self._mw, "mv_title") else ""
        month = title.split()[0] if title else None
        return month if month and month not in ("月度训练汇总", "暂无数据，请导入") else None

    def ask_summary(self):
        """一键生成当前月份总结（原月度页按钮能力迁移至此）。"""
        if not self._mw.config.get("ai_enabled"):
            QMessageBox.information(self._mw, "提示", "请先在「设置」中启用并配置 AI")
            return
        month = self._current_month()
        m = next((x for x in self._mw.db.months() if x["month"] == month), None) if month else None
        if not m:
            QMessageBox.information(self._mw, "提示", "请先在左侧选择一个月份")
            return
        self.btn_summary.setEnabled(False)
        self._set_text("AI 生成月度总结中，请稍候…")
        self._mw._run_worker(self._do_summary, self._on_summary_done, month, m)

    def _do_summary(self, month, m):
        from core import ai_analysis
        return month, ai_analysis.analyze_month(m, self._mw._ai_client())

    def _on_summary_done(self, ok, payload):
        self.btn_summary.setEnabled(True)
        if not ok:
            self._set_text(f"错误：{payload}")
            return
        from gui.main_window import _format_ai_result
        month, res = payload
        text = _format_ai_result(res)
        self._set_text(text)
        self.history = month_agent.append_round(self.history, f"生成 {month} 的月度训练总结", text)

    def ask_review(self):
        """一键复盘当前关联活动（review_agent 单次复盘链路）。"""
        if not self._mw.config.get("ai_enabled"):
            QMessageBox.information(self._mw, "提示", "请先在「设置」中启用并配置 AI")
            return
        act = self._activity
        if not act:
            QMessageBox.information(self._mw, "提示", "请先在活动列表选择一次骑行")
            return
        self.btn_review.setEnabled(False)
        self._set_text(f"AI 复盘《{act.get('name')}》中，请稍候…")
        self._mw._run_worker(self._do_review, self._on_review_done, act)

    def _do_review(self, act):
        from core import review_agent
        return review_agent.run_review(
            self._mw._ai_client(), self._mw.db, self._mw.config,
            "请复盘这次骑行：结合速度/心率/踏频/功率数据点评表现，"
            "指出做得好与需改进的地方，给出具体可执行的训练建议。",
            current_activity=act)

    def _on_review_done(self, ok, payload):
        self.btn_review.setEnabled(True)
        if not ok:
            self._set_text(f"错误：{payload}")
            return
        text = payload.get("answer") if isinstance(payload, dict) else str(payload)
        self._set_text(text)
        if self._activity:
            self.history = month_agent.append_round(
                self.history, f"复盘活动《{self._activity.get('name')}》", text)

    def ask(self):
        """自由提问（多轮会话 + 流式 + Action 确认）。"""
        if not self._mw.config.get("ai_enabled"):
            QMessageBox.information(self._mw, "提示", "请先在「设置」中启用并配置 AI")
            return
        q = self.input.text().strip()
        if not q:
            return
        month = self._current_month()
        if self._activity:
            # 关联活动优先：问题锚定到这次骑行，数据取其所在月份
            month = self._activity_month(self._activity) or month
            q = f"{self._activity_prefix(self._activity)}\n\n用户问题：{q}"
        if not month:
            QMessageBox.information(self._mw, "提示", "请先在左侧选择一个月份")
            return
        round_no = len(self.history) // 2 + 1
        self.btn_ask.setEnabled(False)
        self._think_buf, self._answer_buf, self._tool_rows = "", "", []
        self._set_text(f"（第 {round_no} 问）思考中…")
        self._poll.start()
        self._mw._run_worker(self._do_chat, self._on_chat_done, month, q,
                             list(self.history))

    def _do_chat(self, month, q, history):
        return month_agent.run_month_query(
            self._mw._ai_client(), self._mw.db, month, self._mw.config, q,
            max_rounds=5, history=history, on_event=self._events.put,
            on_action=self._confirm_action)

    def new_session(self):
        self.history = []
        self.input.clear()
        self._set_text("已开启新对话，开始提问吧～")
        self._mw.statusBar().showMessage("AI 会话已重置", 3000)

    def inject_context(self, title, text):
        """外部注入上下文（如定时周报）进会话历史——之后可追问「周报里说的建议是什么」。"""
        if not (title or "").strip() or not (text or "").strip():
            return
        self.history = month_agent.append_round(self.history, title, text)

    # ---------------- 流式渲染 ----------------
    def _set_text(self, text):
        self.output.setPlainText(text)
        sb = self.output.verticalScrollBar()
        if sb is not None:
            sb.setValue(sb.maximum())

    def _drain(self):
        self._poll_confirm()
        drained = False
        while True:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                break
            self._apply_event(ev)
            drained = True
        if drained:
            self._render_stream()

    def _apply_event(self, ev):
        kind = ev[0]
        if kind == "tool":
            self._tool_rows.append([ev[1], None])
        elif kind == "tool_result":
            if self._tool_rows:
                self._tool_rows[-1][1] = bool(ev[2])
        elif kind == "thinking_delta":
            self._think_buf += ev[1]
        elif kind == "delta":
            self._answer_buf += ev[1]

    def _render_stream(self):
        lines = []
        for name, ok in self._tool_rows:
            mark = "…" if ok is None else ("✅" if ok else "❌")
            lines.append(f"🔍 查询{_TOOL_CN.get(name, name)} {mark}")
        text = "\n".join(lines)
        if text:
            text += "\n\n"
        if self._think_buf:
            text += "【思考】\n" + self._think_buf + "\n\n"
        if self._answer_buf:
            text += "【回答】\n" + self._answer_buf
        self._set_text(text.strip() or "…")

    def _on_chat_done(self, ok, payload):
        self.btn_ask.setEnabled(True)
        self._poll.stop()
        self._think_buf, self._answer_buf, self._tool_rows = "", "", []
        if not ok:
            self._set_text(f"错误：{payload}")
            return
        steps = payload.get("steps") or []
        head = f"（已查询 {len(steps)} 次骑行数据）\n\n" if steps else ""
        thinking = (payload.get("thinking") or "").strip()
        answer = payload.get("answer") or "（模型未返回内容）"
        self._set_text(head + ((f"【思考】\n{thinking}\n\n" if thinking else "") + f"【回答】\n{answer}"))
        self.history = payload.get("history") or self.history
        self.input.clear()

    # ---------------- Action 写操作确认 ----------------
    def _confirm_action(self, action):
        """worker 线程：投递确认请求，阻塞等待主线程弹窗结果。"""
        reply_q = queue.Queue()
        self._confirm_queue.put((action, reply_q))
        return reply_q.get()

    def _poll_confirm(self):
        if self._confirm_showing:
            return
        try:
            while True:
                action, reply_q = self._confirm_queue.get_nowait()
                self._confirm_showing = True
                try:
                    ret = QMessageBox.question(
                        self._mw, "AI 操作确认",
                        f"{action.get('description', '执行操作')}\n\n是否执行？",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    reply_q.put(ret == QMessageBox.Yes)
                finally:
                    self._confirm_showing = False
        except queue.Empty:
            pass
