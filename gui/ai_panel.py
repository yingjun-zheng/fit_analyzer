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

        # 输入行：总结本月 + 提问 + 新对话
        row1 = QHBoxLayout()
        self.btn_summary = QPushButton("📝 总结本月")
        self.btn_summary.setToolTip("一键生成当前月份的 AI 训练总结")
        self.btn_summary.clicked.connect(self.ask_summary)
        self.btn_new = QPushButton("🆕")
        self.btn_new.setToolTip("新对话（切换月份也会自动重置）")
        self.btn_new.clicked.connect(self.new_session)
        row1.addWidget(self.btn_summary)
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

    def ask(self):
        """自由提问（多轮会话 + 流式 + Action 确认）。"""
        if not self._mw.config.get("ai_enabled"):
            QMessageBox.information(self._mw, "提示", "请先在「设置」中启用并配置 AI")
            return
        q = self.input.text().strip()
        if not q:
            return
        month = self._current_month()
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
