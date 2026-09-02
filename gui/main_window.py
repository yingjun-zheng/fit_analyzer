"""主窗口：左侧月份-活动树 + 月度汇总 / 活动详情（原生桌面界面）。"""
import logging
import os
import random
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import ai_analysis, ai_client, analysis, fit_parser, logging_setup, month_agent
from core.config import Config
from core.db import DB
from gui import charts as ch
from gui.dialogs import LogsDialog, SettingsDialog
from gui.theme import fmt_dt, fmt_duration, fmt_km, kmh
from gui.track_widget import TrackWidget
from gui.amap_track import TrackMapPanel

log = logging.getLogger("fit.gui")

MONTH, ACTIVITY = 0, 1


def make_app_icon():
    """程序/托盘图标（QPainter 绘制，无需图片文件）。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#1e88e5"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QPen(QColor("white"), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pts = [(10, 44), (20, 26), (30, 34), (40, 16), (52, 26)]
    for i in range(1, len(pts)):
        p.drawLine(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
    p.setBrush(QColor("#ffdc3c"))
    p.drawEllipse(36, 11, 9, 9)
    p.setBrush(QColor("white"))
    p.drawEllipse(46, 21, 12, 12)
    p.end()
    return pm


class Worker(QThread):
    """通用后台任务：fn(*args) 在线程中执行，结果通过信号回主线程。"""

    done = Signal(bool, object)  # (ok, payload)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.args = args

    def run(self):
        try:
            self.done.emit(True, self.fn(*self.args))
        except Exception as e:  # noqa: BLE001
            log.exception("后台任务失败")
            self.done.emit(False, str(e))


def _short_zone_labels(boundaries, unit=""):
    """区间柱状图的短标签（长标签会挤在一起）。"""
    labels = []
    for i in range(len(boundaries) + 1):
        lo = boundaries[i - 1] if i > 0 else None
        hi = boundaries[i] if i < len(boundaries) else None
        def f(v):
            return f"{int(v)}" if float(v).is_integer() else f"{v}"
        if lo is None:
            labels.append(f"<{f(hi)}{unit}")
        elif hi is None:
            labels.append(f">={f(lo)}{unit}")
        else:
            labels.append(f"{f(lo)}-{f(hi)}{unit}")
    return labels


def _format_ai_result(res):
    """把 {"answer","thinking"} 格式化为可读文本（思考过程 + 结论）。"""
    if isinstance(res, dict):
        answer = (res.get("answer") or "").strip()
        thinking = (res.get("thinking") or "").strip()
        if thinking:
            return f"【思考过程】\n{thinking}\n\n【分析结论】\n{answer}"
        return answer or ""
    return str(res)


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path, config: Config, db: DB, backgrounds: list):
        super().__init__()
        self.data_dir = data_dir
        self.config = config
        self.db = db
        self.backgrounds = [b for b in backgrounds if Path(b).exists()] or []
        self.cur_activity = None
        self.cur_analysis = None
        self.cur_laps = []
        self._workers = []

        self.setWindowTitle(f"{config.get('app_name')} v{config.get('version')}")
        self.setWindowIcon(QIcon(make_app_icon()))
        self.resize(1280, 820)

        self._build_ui()
        self.load_months()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        tb = QToolBar()
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)

        act_import = QAction("📁 批量导入 FIT 文件", self)
        act_import.triggered.connect(self.import_files)
        act_refresh = QAction("刷新", self)
        act_refresh.triggered.connect(self.load_months)
        act_settings = QAction("设置", self)
        act_settings.triggered.connect(self.open_settings)
        act_logs = QAction("日志", self)
        act_logs.triggered.connect(self.open_logs)
        act_dir = QAction("数据目录", self)
        act_dir.triggered.connect(self.open_data_dir)
        act_export = QAction("📤 导出 GPX", self)
        act_export.triggered.connect(self.export_gpx)
        # 「导入路书」暂隐藏——路径规划（阶段三）上线后再启用，届时路书可存入数据库复用。
        # act_route = QAction("🗺 导入路书", self)
        # act_route.triggered.connect(self.open_route)
        act_to_route = QAction("🔁 转路书", self)
        act_to_route.triggered.connect(self.export_route)
        # 删除选中（批量）
        act_delete = QAction("🗑 删除选中", self)
        act_delete.triggered.connect(self.delete_selected)

        tb.addAction(act_import)
        tb.addAction(act_refresh)
        tb.addAction(act_delete)
        tb.addSeparator()
        tb.addAction(act_export)
        # tb.addAction(act_route)
        tb.addAction(act_to_route)
        tb.addSeparator()
        tb.addAction(act_settings)
        tb.addAction(act_logs)
        tb.addAction(act_dir)
        self.addToolBar(tb)

        self.month_tree = QTreeWidget()
        self.month_tree.setHeaderLabels(["训练记录"])
        self.month_tree.setColumnCount(1)
        self.month_tree.itemClicked.connect(self.on_tree_click)
        self.month_tree.setMinimumWidth(260)
        self.month_tree.setMaximumWidth(340)
        # 多选（Ctrl/Shift+点击）+ 右键菜单（单选/批量/清空）
        from PySide6.QtWidgets import QAbstractItemView

        self.month_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.month_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.month_tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        self.stack = QStackedWidget()
        self.month_page = self._build_month_page()
        self.act_page = self._build_activity_page()
        self.stack.addWidget(self.month_page)
        self.stack.addWidget(self.act_page)

        # 左侧：训练记录树 + 月度 AI 对话面板（垂直分割）
        self.left_vsplit = QSplitter(Qt.Vertical)
        self.left_vsplit.addWidget(self.month_tree)
        self.left_vsplit.addWidget(self._build_ai_panel())
        self.left_vsplit.setStretchFactor(0, 3)
        self.left_vsplit.setStretchFactor(1, 2)
        self.left_vsplit.setChildrenCollapsible(False)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left_vsplit)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 940])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("就绪", 3000)

    # ---------------- 左侧月度 AI 对话面板 ----------------
    def _build_ai_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # 标题
        head = QHBoxLayout()
        title = QLabel("月度 AI 查询")
        title.setObjectName("h3")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        # 当前范围/策略标签
        self.ai_scope_label = QLabel("当前范围：月度（将使用当前选中的月份）")
        self.ai_scope_label.setObjectName("muted")
        lay.addWidget(self.ai_scope_label)

        # 诉求输入 + 开始按钮
        in_row = QHBoxLayout()
        self.ai_input = QLineEdit()
        self.ai_input.setPlaceholderText("用自然语言提问，例如：本月训练量如何？爬坡多吗？哪天骑得最快？")
        self.ai_input.returnPressed.connect(self.ai_chat_ask)
        self.ai_ask_btn = QPushButton("开始")
        self.ai_ask_btn.setObjectName("primary")
        self.ai_ask_btn.clicked.connect(self.ai_chat_ask)
        in_row.addWidget(self.ai_input, 1)
        in_row.addWidget(self.ai_ask_btn)
        lay.addLayout(in_row)

        # 思考过程 / 工具调用日志（可折叠）
        think_box = QGroupBox("思考过程（工具调用）")
        think_lay = QVBoxLayout(think_box)
        think_lay.setContentsMargins(8, 8, 8, 8)
        self.ai_think = QTextEdit()
        self.ai_think.setReadOnly(True)
        self.ai_think.setPlaceholderText("模型选择的工具、参数与结果会显示在这里。")
        self.ai_think.setMinimumHeight(80)
        think_lay.addWidget(self.ai_think)
        think_box.setMaximumHeight(160)
        lay.addWidget(think_box)

        # 最终回答
        self.ai_answer = QTextEdit()
        self.ai_answer.setReadOnly(True)
        self.ai_answer.setPlaceholderText("AI 回复将显示在这里。")
        self.ai_answer.setMinimumHeight(90)
        lay.addWidget(self.ai_answer, 1)

        # 历史记录（可折叠）
        hist_box = QGroupBox("历史记录")
        hist_lay = QVBoxLayout(hist_box)
        hist_lay.setContentsMargins(8, 8, 8, 8)
        self.ai_history = QTextEdit()
        self.ai_history.setReadOnly(True)
        self.ai_history.setPlaceholderText("过往提问与回答摘要。")
        self.ai_history.setMaximumHeight(120)
        hist_lay.addWidget(self.ai_history)
        lay.addWidget(hist_box)

        return panel

    def _on_ai_mode_changed(self, _=None):
        self.ai_scope_label.setText("当前范围：月度（将使用当前选中的月份）")

    def _card(self):
        f = QFrame()
        f.setObjectName("card")
        f.setLayout(QVBoxLayout())
        f.layout().setContentsMargins(10, 10, 10, 10)
        return f

    def _chart_block(self, view, width):
        """把一张图包进独立的横向滚动区：图太宽时该图自带横向滚动条，其他图不受影响。"""
        card = self._card()
        card.setFixedWidth(max(width, 400))
        card.layout().addWidget(view)
        sc = QScrollArea()
        sc.setWidgetResizable(False)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setMinimumWidth(120)  # 不把外层页面撑宽
        sc.setWidget(card)
        return sc

    def _stat_card(self, key, value):
        f = QFrame()
        f.setObjectName("stat")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        k = QLabel(key)
        k.setObjectName("statKey")
        v = QLabel(value)
        v.setObjectName("statVal")
        v.setWordWrap(True)
        lay.addWidget(k)
        lay.addWidget(v)
        return f

    def _scroll_of(self, widget):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(widget)
        return sc

    # ---------- 月度页 ----------
    def _build_month_page(self):
        page = QWidget()
        page.setMinimumWidth(1000)  # 窄窗口出横向滚动条
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        self.mv_title = QLabel("月度训练汇总")
        self.mv_title.setObjectName("h2")
        self.mv_ai_btn = QPushButton("🤖 AI 月度总结")
        self.mv_ai_btn.setObjectName("primary")
        self.mv_ai_btn.clicked.connect(self.ai_month)
        head.addWidget(self.mv_title)
        head.addStretch(1)
        head.addWidget(self.mv_ai_btn)
        lay.addLayout(head)

        self.mv_stats = QGridLayout()
        self.mv_stats.setSpacing(8)
        lay.addLayout(self.mv_stats)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        c1 = self._card()
        self.mv_chart_dist = None
        c1.layout().addWidget(QLabel("各月里程 (km)"))
        self.mv_dist_holder = QVBoxLayout()
        self.mv_dist_holder.setSpacing(6)
        c1.layout().addLayout(self.mv_dist_holder)
        c2 = self._card()
        self.mv_count_holder = QVBoxLayout()
        self.mv_count_holder.setSpacing(6)
        c2.layout().addWidget(QLabel("各月骑行次数"))
        c2.layout().addLayout(self.mv_count_holder)
        charts_row.addWidget(c1, 1)
        charts_row.addWidget(c2, 1)
        lay.addLayout(charts_row)

        # 训练负荷趋势图（CTL/ATL/TSB，全量数据）
        load_card = self._card()
        load_card.layout().addWidget(QLabel("训练负荷趋势（CTL ↔ 体能 / ATL ↔ 疲劳 / TSB ↔ 状态）"))
        self.mv_load_holder = QVBoxLayout()
        self.mv_load_holder.setSpacing(6)
        load_card.layout().addLayout(self.mv_load_holder)
        lay.addWidget(load_card)

        card = self._card()
        card.layout().addWidget(QLabel("本月活动列表"))
        self.mv_table = QTableWidget(0, 7)
        self.mv_table.setHorizontalHeaderLabels(["日期", "名称", "距离", "用时", "均速", "爬升", "卡路里"])
        self.mv_table.verticalHeader().setVisible(False)  # 隐藏行号表头（避免深色竖带）
        self.mv_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.mv_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.mv_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.mv_table.cellDoubleClicked.connect(self.on_mv_table_dbl)
        card.layout().addWidget(self.mv_table)
        lay.addWidget(card, 1)

        ai_card = self._card()
        ai_card.setVisible(False)
        self.mv_ai_text = QTextEdit()
        self.mv_ai_text.setReadOnly(True)
        self.mv_ai_text.setMaximumHeight(260)
        ai_card.layout().addWidget(self.mv_ai_text)
        self.mv_ai_card = ai_card
        lay.addWidget(ai_card)

        # 月度页整体放入滚动区，防止内容超出窗口时显示不全
        self.mv_scroll = QScrollArea()
        self.mv_scroll.setWidgetResizable(True)
        self.mv_scroll.setWidget(page)
        return self.mv_scroll

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    # ---------------- 轨迹 ----------------
    def _random_background(self):
        """从背景图集中随机选一张。"""
        if self.backgrounds:
            return random.choice(self.backgrounds)
        # 回退：用 app.py 的 resource_path 定位 back9.jpeg
        from app import resource_path
        fb = resource_path("back9.jpeg")
        return str(fb) if fb.exists() else ""

    def _build_activity_page(self):
        tabs = QTabWidget()
        # 概览：统计卡 + 图表（每张图自带横向滚动条，页面本身不做横向扩展）
        self.ov_scroll = QScrollArea()
        self.ov_container = QWidget()
        self.ov_container.setMinimumWidth(600)
        self.ov_lay = QVBoxLayout(self.ov_container)
        self.ov_lay.setContentsMargins(12, 12, 12, 12)
        self.ov_lay.setSpacing(10)
        self.ov_stats = QGridLayout()
        self.ov_stats.setSpacing(8)
        self.ov_lay.addLayout(self.ov_stats)
        self.ov_charts = QVBoxLayout()
        self.ov_charts.setSpacing(16)
        self.ov_lay.addLayout(self.ov_charts)
        self.ov_lay.addStretch(1)
        self.ov_scroll.setWidgetResizable(True)
        self.ov_scroll.setWidget(self.ov_container)
        tabs.addTab(self.ov_scroll, "概览")

        # 区间统计
        self.zs_scroll = QScrollArea()
        self.zs_container = QWidget()
        self.zs_container.setMinimumWidth(600)
        self.zs_lay = QVBoxLayout(self.zs_container)
        self.zs_lay.setContentsMargins(12, 12, 12, 12)
        self.zs_lay.setSpacing(10)
        self.zs_charts = QVBoxLayout()
        self.zs_charts.setSpacing(16)
        self.zs_lay.addLayout(self.zs_charts)
        self.zs_lay.addStretch(1)
        self.zs_scroll.setWidgetResizable(True)
        self.zs_scroll.setWidget(self.zs_container)
        tabs.addTab(self.zs_scroll, "区间统计")

        # 记圈
        self.lap_table = QTableWidget(0, 12)
        self.lap_table.setHorizontalHeaderLabels([
            "圈", "开始时间", "时长", "距离", "均速", "最大速度",
            "平均心率", "最大心率", "平均踏频", "卡路里", "爬升", "下降"])
        self.lap_table.verticalHeader().setVisible(False)  # 隐藏行号表头（避免深色竖带）
        self.lap_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.lap_table.setEditTriggers(QTableWidget.NoEditTriggers)
        tabs.addTab(self.lap_table, "记圈")

        # 轨迹（高德在线地图 / 固定图片背景 自动切换）
        track_page = QWidget()
        tp_lay = QVBoxLayout(track_page)
        tp_lay.setContentsMargins(12, 12, 12, 12)
        self.track_widget = TrackMapPanel(self.config, self._random_background())
        tp_lay.addWidget(self.track_widget, 1)
        tabs.addTab(track_page, "轨迹")

        # 活动详情
        det_page = QScrollArea()
        self.det_container = QWidget()
        self.det_grid = QGridLayout(self.det_container)
        self.det_grid.setContentsMargins(12, 12, 12, 12)
        self.det_grid.setSpacing(8)
        self.det_grid.setColumnStretch(0, 1)
        self.det_grid.setColumnStretch(1, 1)
        det_page.setWidgetResizable(True)
        det_page.setWidget(self.det_container)
        tabs.addTab(det_page, "活动详情")

        # AI 分析
        ai_page = QWidget()
        ai_lay = QVBoxLayout(ai_page)
        ai_lay.setContentsMargins(12, 12, 12, 12)

        # 智能复盘（统一入口：自动路由到单次/周期/对比/训练负荷/体能分析）
        rv_label = QLabel("智能复盘（一句话触发，自动判断分析类型）")
        rv_label.setObjectName("h3")
        ai_lay.addWidget(rv_label)
        rv_in_row = QHBoxLayout()
        self.rv_input = QLineEdit()
        self.rv_input.setPlaceholderText(
            "例：帮我复盘上周 · 和上次比有没有进步 · 这周该不该休息 · 我体能进步了吗 · 这次爬坡多吗")
        self.rv_input.returnPressed.connect(self.review_query)
        self.rv_btn = QPushButton("🧭 智能复盘")
        self.rv_btn.setObjectName("primary")
        self.rv_btn.clicked.connect(self.review_query)
        rv_in_row.addWidget(self.rv_input, 1)
        rv_in_row.addWidget(self.rv_btn)
        ai_lay.addLayout(rv_in_row)
        self.rv_text = QTextEdit()
        self.rv_text.setReadOnly(True)
        self.rv_text.setPlaceholderText("在这里查看复盘结果（自动路由 + 教练解读）。")
        self.rv_text.setMinimumHeight(160)
        ai_lay.addWidget(self.rv_text, 3)

        # 传统报告生成
        btn_row = QHBoxLayout()
        self.ai_run_btn = QPushButton("🤖 生成 AI 分析报告")
        self.ai_run_btn.setObjectName("primary")
        self.ai_run_btn.clicked.connect(self.ai_activity)
        self.ai_test_btn = QPushButton("测试 AI 连接")
        self.ai_test_btn.clicked.connect(self.ai_test)
        btn_row.addWidget(self.ai_run_btn)
        btn_row.addWidget(self.ai_test_btn)
        btn_row.addStretch(1)
        ai_lay.addLayout(btn_row)
        self.ai_text = QTextEdit()
        self.ai_text.setReadOnly(True)
        self.ai_text.setPlaceholderText("点击按钮，由本地或配置的 AI 模型分析本次骑行数据。")
        ai_lay.addWidget(self.ai_text, 1)
        tabs.addTab(ai_page, "AI 分析")

        return tabs

    def closeEvent(self, e):
        """关闭窗口即退出。"""
        QApplication.instance().quit()

    # ---------------- 数据加载 ----------------
    def load_months(self):
        months = self.db.months()
        self.month_tree.clear()
        self._month_items = {}
        for m in months:
            top = QTreeWidgetItem([f"{m['month']}   {m['count']} 次 · {fmt_km(m['distance_km'])}"])
            top.setData(0, Qt.UserRole, (MONTH, m["month"]))
            top.setExpanded(True)
            self.month_tree.addTopLevelItem(top)
            self._month_items[m["month"]] = top
            for a in self.db.list_activities(month=m["month"]):
                child = QTreeWidgetItem([
                    f"{fmt_dt(a['start_time'])}  {a['name']}  {fmt_km(a['distance_km'])}  {fmt_duration(a['timer_s'])}"])
                child.setData(0, Qt.UserRole, (ACTIVITY, a["id"]))
                top.addChild(child)
        if months:
            self.show_month(months[0]["month"])

    def on_tree_click(self, item, col):
        kind, data = item.data(0, Qt.UserRole)
        if kind == MONTH:
            self.show_month(data)
        elif kind == ACTIVITY:
            self.show_activity(data)

    # ---------------- 删除数据（单选 / 批量 / 清空） ----------------
    def _selected_activity_ids(self):
        ids = []
        for item in self.month_tree.selectedItems():
            kind, data = item.data(0, Qt.UserRole)
            if kind == ACTIVITY and data not in ids:
                ids.append(data)
        return ids

    def delete_selected(self):
        """工具栏：删除选中的活动（可多选）。"""
        ids = self._selected_activity_ids()
        if not ids:
            QMessageBox.information(self, "删除", "请先在左侧选中要删除的活动\n（多选：按住 Ctrl 或 Shift 点击）")
            return
        self._delete_ids(ids, f"确定删除选中的 {len(ids)} 条记录？")

    def reidentify_devices(self):
        """按当前“设备型号表”重新识别所有活动的码表型号。"""
        from core.fit_parser import _format_device

        overrides = self.config.get("device_models") or {}
        n = self.db.reidentify_devices(
            lambda brand, product, pn, hw, sw: _format_device(
                brand, product, pn, overrides=overrides, hw_version=hw, sw_version=sw))
        self.load_months()
        self.statusBar().showMessage(f"已按设备型号表重新识别 {n} 条记录", 5000)

    def _on_tree_context_menu(self, pos):
        item = self.month_tree.itemAt(pos)
        if item is None:
            return
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        act_one = None
        if item.data(0, Qt.UserRole)[0] == ACTIVITY:
            act_one = menu.addAction("删除此记录")
        sel_ids = self._selected_activity_ids()
        act_sel = None
        if len(sel_ids) > 1:
            act_sel = menu.addAction(f"删除选中的 {len(sel_ids)} 条记录")
        menu.addSeparator()
        act_all = menu.addAction("清空全部记录…")
        chosen = menu.exec(self.month_tree.viewport().mapToGlobal(pos))
        if chosen is act_one:
            self._delete_ids([item.data(0, Qt.UserRole)[1]], "确定删除这条记录？")
        elif chosen is act_sel:
            self._delete_ids(sel_ids, f"确定删除选中的 {len(sel_ids)} 条记录？")
        elif chosen is act_all:
            all_ids = [a["id"] for a in self.db.list_activities(limit=100000)]
            if all_ids:
                self._delete_ids(all_ids, f"确定清空全部 {len(all_ids)} 条记录？此操作不可恢复！")

    def _delete_ids(self, ids, question):
        if not ids:
            return
        ret = QMessageBox.question(self, "确认删除", question + "\n（FIT 原文件不受影响，可重新导入）",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        for aid in ids:
            self.db.delete_activity(aid)
        log.info("删除活动 %d 条: %s", len(ids), ids[:10])
        self._after_delete()

    def _after_delete(self):
        self.load_months()
        if self.cur_activity is not None and self.db.get_activity(self.cur_activity["id"]) is None:
            # 当前打开的活动被删除 → 回到月度页
            self.cur_activity = None
            self.cur_analysis = None
            self.stack.setCurrentWidget(self.month_page)
            months = self.db.months()
            if months:
                self.show_month(months[0]["month"])
            else:
                self.mv_title.setText("暂无数据，请导入 FIT 文件")
        self.statusBar().showMessage("已删除", 4000)

    # ---------------- 月度页 ----------------
    def show_month(self, month):
        self.stack.setCurrentWidget(self.month_page)
        self.mv_title.setText(f"{month} 训练汇总")
        self.mv_ai_card.setVisible(False)
        self._on_ai_mode_changed()  # 同步左侧 AI 对话面板的范围提示
        m = next((x for x in self.db.months() if x["month"] == month), None)
        acts = self.db.list_activities(month=month)
        if m is None:
            m = {"count": 0, "distance_km": 0, "hours": 0, "ascent_m": 0, "calories": 0, "avg_speed_kmh": 0}
        values = [
            ("骑行次数", f"{m['count']} 次"),
            ("总里程", fmt_km(m["distance_km"])),
            ("总用时", f"{m['hours']} 小时"),
            ("总爬升", f"{round(m['ascent_m'] or 0)} m"),
            ("总消耗", f"{round(m['calories'] or 0)} kcal"),
            ("平均速度", f"{m['avg_speed_kmh']} km/h"),
        ]
        self._clear_layout(self.mv_stats)
        for i, (k, v) in enumerate(values):
            self.mv_stats.addWidget(self._stat_card(k, v), i // 3, i % 3)

        months = self.db.months()[::-1]
        self._clear_layout(self.mv_dist_holder)
        self._clear_layout(self.mv_count_holder)
        if months:
            self.mv_dist_holder.addWidget(ch.line_chart_cat(
                "各月里程 (km)", [m0["month"] for m0 in months],
                [m0["distance_km"] for m0 in months], "#1e88e5", "km", 260, "%.1f"))
            self.mv_count_holder.addWidget(ch.line_chart_cat(
                "各月骑行次数", [m0["month"] for m0 in months],
                [m0["count"] for m0 in months], "#43a047", "次", 260, "%.0f"))

        # 训练负荷趋势（CTL/ATL/TSB，全量数据）
        self._clear_layout(self.mv_load_holder)
        self._render_training_load(months)

        self.mv_table.setRowCount(len(acts))
        for r, a in enumerate(acts):
            vals = [
                fmt_dt(a["start_time"]), a["name"], fmt_km(a["distance_km"]),
                fmt_duration(a["timer_s"]),
                a["avg_speed_kmh"] if a["avg_speed_kmh"] is not None else "—",
                f"{round(a['ascent_m'] or 0)} m" if a["ascent_m"] is not None else "—",
                f"{round(a['calories'] or 0)} kcal" if a["calories"] is not None else "—",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if c >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.mv_table.setItem(r, c, item)
            self.mv_table.item(r, 0).setData(Qt.UserRole, a["id"])
        self.mv_table.resizeRowsToContents()

    def on_mv_table_dbl(self, row, col):
        item = self.mv_table.item(row, 0)
        if item is not None and item.data(Qt.UserRole):
            self.show_activity(item.data(Qt.UserRole))

    def _render_training_load(self, months):
        """渲染训练负荷趋势图（CTL/ATL/TSB）：全量活动数据计算，跨月展示。"""
        from core import training_load

        ftp = self.config.get("ftp_w") or None
        max_hr_override = self.config.get("hr_max_override") or None
        daily = []
        for act in self.db.list_activities(limit=200):
            records = self.db.get_records(act["id"])
            hrs = [r.get("hr") for r in records if r.get("hr")]
            mhr = max_hr_override or (max(hrs) if hrs else act.get("max_hr"))
            tss, _, _, _, _ = training_load.compute_activity_tss(
                records, config=self.config, ftp=ftp, max_hr=mhr)
            d = (act.get("start_time") or "")[:10]
            if tss and d:
                daily.append((d, tss))

        if not daily:
            self.mv_load_holder.addWidget(QLabel("暂无训练负荷数据（需要心率或功率数据）。"))
            return

        daily_sorted = training_load.daily_tss_from_activities(daily)
        ctls, atls, tsbs, latest = training_load.build_performance_curve(daily_sorted)
        dates = [d for d, _ in daily_sorted]

        if not dates:
            return

        ctl_vals = [ctls.get(d) for d in dates]
        atl_vals = [atls.get(d) for d in dates]
        tsb_vals = [tsbs.get(d) for d in dates]

        # 精简日期标签（太多时只保留部分）
        show_dates = dates
        if len(dates) > 30:
            step = max(1, len(dates) // 25)
            show_dates = [dates[i] if i % step == 0 else "" for i in range(len(dates))]

        view = ch.multi_line_chart_cat(
            "训练负荷趋势（CTL · ATL · TSB）",
            show_dates,
            [
                {"name": "CTL（体能）", "values": ctl_vals, "color": "#1e88e5"},
                {"name": "ATL（疲劳）", "values": atl_vals, "color": "#e53935"},
                {"name": "TSB（状态）", "values": tsb_vals, "color": "#43a047"},
            ],
            y_label="", height=280, fmt="%.0f",
        )
        self.mv_load_holder.addWidget(view)

    # ---------------- 活动页 ----------------
    def stat_values(self, a):
        return [
            ("记录时间", fmt_dt(a.get("start_time"))),
            ("平均速度", kmh(a.get("avg_speed_ms"))),
            ("卡路里", f"{round(a['calories'])} kcal" if a.get("calories") is not None else "—"),
            ("最大速度", kmh(a.get("max_speed_ms"))),
            ("平均心率", f"{round(a['avg_hr'])} bpm" if a.get("avg_hr") is not None else "—"),
            ("平均踏频", f"{round(a['avg_cad'])} rpm" if a.get("avg_cad") is not None else "—"),
            ("累计爬升", f"{round(a['ascent_m'])} m" if a.get("ascent_m") is not None else "—"),
            ("骑行距离", fmt_km(a.get("distance_km"))),
            ("骑行用时", fmt_duration(a.get("timer_s"))),
            ("累计下降", f"{round(a['descent_m'])} m" if a.get("descent_m") is not None else "—"),
            ("平均海拔", f"{a['avg_alt_m']} m" if a.get("avg_alt_m") is not None else "—"),
            ("最高海拔", f"{a['max_alt_m']} m" if a.get("max_alt_m") is not None else "—"),
            ("最大心率", f"{round(a['max_hr'])} bpm" if a.get("max_hr") is not None else "—"),
            ("最大踏频", f"{round(a['max_cad'])} rpm" if a.get("max_cad") is not None else "—"),
            ("平均温度", f"{a['avg_temp']} °C" if a.get("avg_temp") is not None else "—"),
            ("平均功率", f"{a['avg_power']} W" if a.get("avg_power") is not None else "—"),
            ("最大功率", f"{a['max_power']} W" if a.get("max_power") is not None else "—"),
            ("设备", a.get("device") or "—"),
        ]

    def show_activity(self, aid):
        act = self.db.get_activity(aid)
        if act is None:
            QMessageBox.warning(self, "提示", "活动不存在")
            return
        records = self.db.get_records(aid)
        # 功率估算（无功率计时自动估算）
        records = analysis.estimate_power(records, self.config)
        # 计算平均/最大功率
        powers = [r["power"] for r in records if r.get("power") is not None]
        if powers:
            act["avg_power"] = round(sum(powers) / len(powers))
            act["max_power"] = max(powers)
        self.cur_records = records
        laps = self.db.get_laps(aid)
        self.cur_activity = act
        self.cur_laps = laps
        self.stack.setCurrentWidget(self.act_page)
        self.act_page.setWindowTitle("")  # noop
        self.statusBar().showMessage(f"活动：{act['name']}（{fmt_dt(act['start_time'])}）", 5000)
        self._on_ai_mode_changed()  # 同步左侧 AI 对话面板的范围提示

        # 概览统计卡
        self._clear_layout(self.ov_stats)
        for i, (k, v) in enumerate(self.stat_values(act)):
            self.ov_stats.addWidget(self._stat_card(k, v), i // 4, i % 4)

        # 分析数据
        hr_max = self.config.get("hr_max_override") or act.get("max_hr")
        an = {
            "per_km": analysis.per_km(records),
            "speed_zones": analysis.speed_zones(records, self.config.get("speed_zone_kmh")),
            "hr_zones": analysis.hr_zones(records, hr_max, self.config.get("hr_zone_pcts")),
            "cadence_zones": analysis.cadence_zones(records, self.config.get("cadence_zone_rpm")),
            "temp": analysis.temp_stats(records),
            "series": {
                "speed": analysis.downsample_series(records, "speed_ms", 500),
                "hr": analysis.downsample_series(records, "hr", 500),
                "cad": analysis.downsample_series(records, "cad", 500),
                "alt": analysis.downsample_series(records, "alt_m", 500),
                "power": analysis.downsample_series(records, "power", 500),
            },
            "track": analysis.track_points(records, self.config.get("track_max_points")),
        }
        self.cur_analysis = an

        # 概览图表（Web 式自适应：图表填满宽度，坐标轴刻度随尺寸自动调整，绝不重叠）
        self._clear_layout(self.ov_charts)
        km_data = an["per_km"]
        if km_data:
            cats = [str(p["km"] + 1) if (p["km"] + 1) % 5 == 0 else "" for p in km_data]
            c = self._card()
            c.layout().addWidget(ch.line_chart_cat(
                "每公里平均速度 (km/h)", cats, [p.get("avg_speed_kmh") or 0 for p in km_data],
                "#1e88e5", "km/h", 300, "%.1f"))
            self.ov_charts.addWidget(c)
        series = an["series"]
        for key, title, color, unit in [
            ("speed", "速度 (km/h) — 时间", "#e53935", "km/h"),
            ("hr", "心率 (bpm) — 时间", "#d81b60", "bpm"),
            ("cad", "踏频 (rpm) — 时间", "#2e7d32", "rpm"),
        ]:
            pts = series.get(key) or []
            if not pts:
                continue
            xs = [p["t"] for p in pts]
            ys = [p["v"] * 3.6 if key == "speed" else p["v"] for p in pts]
            c = self._card()
            c.layout().addWidget(ch.line_chart_time(title, xs, ys, color, unit, 320, "%.0f"))
            self.ov_charts.addWidget(c)
        alt_pts = series.get("alt") or []
        if alt_pts:
            c = self._card()
            c.layout().addWidget(ch.line_chart(
                "海拔 (m) — 里程 (km)", [p["t"] for p in alt_pts], [p["v"] for p in alt_pts],
                "#8d6e63", "m", 320, "%.0f"))
            self.ov_charts.addWidget(c)
        t = an["temp"]
        if t.get("has"):
            c = self._card()
            c.layout().addWidget(ch.line_chart_time(
                f"设备温度 (°C) · 平均{t['avg']} 最高{t['max']} 最低{t['min']}",
                [p["t"] for p in t["series"]], [p["v"] for p in t["series"]],
                "#00acc1", "°C", 260, "%.1f"))
            self.ov_charts.addWidget(c)
        power_pts = series.get("power") or []
        if power_pts:
            xs = [p["t"] for p in power_pts]
            ys = [p["v"] for p in power_pts]
            has_native = any(r.get("power") is not None for r in records)
            label = "功率 (W) — 时间" if has_native else "估算功率 (W) — 时间"
            c = self._card()
            c.layout().addWidget(ch.line_chart_time(label, xs, ys, "#f57c00", "W", 320, "%.0f"))
            self.ov_charts.addWidget(c)

        # 区间统计（Web 式自适应；短标签）
        self._clear_layout(self.zs_charts)
        sz = an["speed_zones"]
        if sz:
            c = self._card()
            c.layout().addWidget(ch.bar_chart(
                "速度区间时长 (秒)", _short_zone_labels(self.config.get("speed_zone_kmh"), "km/h"),
                [z["seconds"] for z in sz], "#1e88e5", "秒", 300, "%.0f"))
            tip = QLabel(ch.zone_text(sz))
            tip.setObjectName("muted")
            tip.setWordWrap(True)
            c.layout().addWidget(tip)
            self.zs_charts.addWidget(c)
        hz = an["hr_zones"]
        if hz:
            c = self._card()
            c.layout().addWidget(ch.bar_chart(
                "心率区间时长 (秒)", [f"Z{i + 1}" for i in range(len(hz))],
                [z["seconds"] for z in hz], "#d81b60", "秒", 300, "%.0f"))
            tip = QLabel(ch.zone_text(hz))
            tip.setObjectName("muted")
            tip.setWordWrap(True)
            c.layout().addWidget(tip)
            self.zs_charts.addWidget(c)
        cz = an["cadence_zones"]
        if cz:
            c = self._card()
            c.layout().addWidget(ch.bar_chart(
                "踏频区间时长 (秒)", _short_zone_labels(self.config.get("cadence_zone_rpm"), "rpm"),
                [z["seconds"] for z in cz], "#2e7d32", "秒", 300, "%.0f"))
            tip = QLabel(ch.zone_text(cz))
            tip.setObjectName("muted")
            tip.setWordWrap(True)
            c.layout().addWidget(tip)
            self.zs_charts.addWidget(c)

        # 记圈
        self.lap_table.setRowCount(len(laps))
        for r, l in enumerate(laps):
            vals = [
                str(l["lap_index"]), fmt_dt(l.get("start_time"))[11:], fmt_duration(l.get("timer_s")),
                f"{l.get('distance_km', 0):.2f} km",
                kmh(l.get("avg_speed_ms")), kmh(l.get("max_speed_ms")),
                f"{round(l['avg_hr'])}" if l.get("avg_hr") is not None else "—",
                f"{round(l['max_hr'])}" if l.get("max_hr") is not None else "—",
                f"{round(l['avg_cad'])}" if l.get("avg_cad") is not None else "—",
                f"{round(l['calories'])}" if l.get("calories") is not None else "—",
                f"{round(l['ascent_m'])} m" if l.get("ascent_m") is not None else "—",
                f"{round(l['descent_m'])} m" if l.get("descent_m") is not None else "—",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if c >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.lap_table.setItem(r, c, item)
        self.lap_table.resizeRowsToContents()

        # 轨迹：高德在线地图（若配置 Key）或 固定图片背景（带底部提示）
        track = an["track"]
        bg = self._random_background()
        alts = [p[2] for p in track if len(p) > 2 and p[2] is not None]
        info = f"轨迹点 {len(track)} 个"
        if alts:
            info += f" · 海拔 {round(min(alts))}~{round(max(alts))} m"
        if act.get("distance_km"):
            info += f" · 全程 {fmt_km(act['distance_km'])}"
        self.track_widget.set_track(track, bg, info)

        # 活动详情
        self._clear_layout(self.det_grid)
        details = self.stat_values(act)
        details += [
            ("运动类型", act.get("sub_sport_cn") or act.get("sub_sport") or "骑行"),
            ("移动时间", fmt_duration(act.get("moving_s"))),
            ("记录点数", f"{act.get('record_count')} 个"),
            ("文件名", act.get("file_name") or "—"),
            ("导入时间", act.get("imported_at") or "—"),
        ]
        for i, (k, v) in enumerate(details):
            self.det_grid.addWidget(self._stat_card(k, str(v)), i // 2, i % 2)

        # AI 页
        self.ai_text.setPlainText("点击「生成 AI 分析报告」按钮。")

    # ---------------- 导入 ----------------
    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 FIT 文件", "", "FIT 文件 (*.fit)")
        if not paths:
            return
        self.statusBar().showMessage(f"正在导入 {len(paths)} 个文件…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self._run_worker(self._do_import, self._on_import_done, paths)

    def _do_import(self, paths):
        results, errors = fit_parser.parse_many([Path(p) for p in paths])
        imported = updated = skipped = 0
        for r in results:
            _, is_new = self.db.upsert_activity(r["data"])
            if is_new:
                imported += 1
            else:
                updated += 1
        skipped += len(errors)
        return {"imported": imported, "updated": updated, "skipped": skipped,
                "errors": errors, "total": self.db.count()}

    def _on_import_done(self, ok, payload):
        QApplication.restoreOverrideCursor()
        if not ok:
            QMessageBox.critical(self, "导入失败", str(payload))
            return
        r = payload
        msg = f"导入完成：新增 {r['imported']}，更新 {r['updated']}，跳过 {r['skipped']}，共 {r['total']} 条"
        if r["errors"]:
            detail = "\n".join(f"{e['file']}: {e['error']}" for e in r["errors"][:8])
            QMessageBox.warning(self, "导入完成（部分失败）", f"{msg}\n\n{detail}")
        self.statusBar().showMessage(msg, 8000)
        self.load_months()

    # ---------------- AI ----------------
    def _ai_client(self):
        return ai_client.AIClient(
            base_url=self.config.get("ai_base_url"),
            api_key=self.config.get("ai_api_key"),
            model=self.config.get("ai_model"),
            temperature=self.config.get("ai_temperature"),
            timeout=self.config.get("ai_timeout"),
        )

    def ai_activity(self):
        if not self.config.get("ai_enabled"):
            QMessageBox.information(self, "提示", "请先在「设置」中启用并配置 AI")
            return
        if not self.cur_activity:
            return
        act = self.cur_activity
        zones = self.cur_analysis.get("hr_zones") or [] if self.cur_analysis else []
        self.ai_run_btn.setEnabled(False)
        self.ai_text.setPlainText("AI 分析中，请稍候…")
        self._run_worker(self._do_ai_activity, self._on_ai_done, act, zones)

    def _do_ai_activity(self, act, zones):
        return ai_analysis.analyze_activity(act, zones, self._ai_client())

    def ai_month(self):
        if not self.config.get("ai_enabled"):
            QMessageBox.information(self, "提示", "请先在「设置」中启用并配置 AI")
            return
        month = self.mv_title.text().split()[0]
        m = next((x for x in self.db.months() if x["month"] == month), None)
        if not m:
            return
        self.mv_ai_btn.setEnabled(False)
        self.mv_ai_card.setVisible(True)
        self.mv_ai_text.setPlainText("AI 分析中，请稍候…")
        self._run_worker(self._do_ai_month, self._on_ai_month_done, m)

    def _do_ai_month(self, m):
        return ai_analysis.analyze_month(m, self._ai_client())

    def _on_ai_done(self, ok, payload):
        self.ai_run_btn.setEnabled(True)
        if ok:
            self.ai_text.setPlainText(_format_ai_result(payload))
        else:
            self.ai_text.setPlainText(f"错误：{payload}")

    def _on_ai_month_done(self, ok, payload):
        self.mv_ai_btn.setEnabled(True)
        if ok:
            self.mv_ai_text.setPlainText(_format_ai_result(payload))
        else:
            self.mv_ai_text.setPlainText(f"错误：{payload}")

    def ai_test(self):
        self.ai_test_btn.setEnabled(False)
        self.ai_text.setPlainText("测试连接中…")
        self._run_worker(self._do_ai_test, self._on_ai_test_done)

    def _do_ai_test(self):
        return self._ai_client().test()

    def _on_ai_test_done(self, ok, payload):
        self.ai_test_btn.setEnabled(True)
        if not ok:
            self.ai_text.setPlainText(f"错误：{payload}")
            return
        if payload.get("ok"):
            models = "、".join(payload.get("models") or []) or "（无）"
            self.ai_text.setPlainText(
                f"连接成功 ✅\n配置模型：{payload.get('configured_model')}\n服务器可用模型：{models}")
        else:
            self.ai_text.setPlainText(f"连接失败：{payload.get('error')}")

    # ---------------- 智能复盘（统一路由 Agent） ----------------
    def review_query(self):
        """智能复盘入口：一句话触发，自动路由到单次/周期/对比/训练负荷/体能。"""
        if not self.config.get("ai_enabled"):
            QMessageBox.information(self, "提示", "请先在「设置」中启用并配置 AI")
            return
        q = self.rv_input.text().strip()
        if not q:
            return
        self.rv_btn.setEnabled(False)
        self.rv_text.setPlainText("复盘分析中…（正在判断分析类型并调用数据）")
        self._run_worker(self._do_review, self._on_review_done, q)

    def _do_review(self, q):
        from core import review_agent

        return review_agent.run_review(
            self._ai_client(), self.db, self.config, q,
            current_activity=self.cur_activity)

    def _on_review_done(self, ok, payload):
        self.rv_btn.setEnabled(True)
        if not ok:
            self.rv_text.setPlainText(f"错误：{payload}")
            return
        if not isinstance(payload, dict):
            self.rv_text.setPlainText(str(payload))
            return
        intent = payload.get("intent") or "single"
        intent_cn = {"single": "单次复盘", "period": "周期复盘", "compare": "对比复盘",
                     "load": "训练负荷", "fitness": "体能分析"}.get(intent, intent)
        lines = [f"【复盘类型】{intent_cn}", ""]
        answer = (payload.get("answer") or "").strip()
        if not answer:
            answer = "（未返回内容）"
        lines.append("【结论】")
        lines.append(answer)
        self.rv_text.setPlainText("\n".join(lines))

    # ---------------- 左侧 AI 对话面板（统一入口） ----------------
    def ai_chat_ask(self):
        if not self.config.get("ai_enabled"):
            QMessageBox.information(self, "提示", "请先在「设置」中启用并配置 AI")
            return
        q = self.ai_input.text().strip()
        if not q:
            return
        month = self.mv_title.text().split()[0] if self.mv_title.text() else None
        if not month or month == "暂无数据，请导入":
            QMessageBox.information(self, "提示", "请先在左侧选择一个月份")
            return
        self.ai_scope_label.setText(f"当前范围：月度 {month}")
        self._run_worker(self._do_ai_chat_month, self._on_ai_chat_done, month, q)

    def _do_ai_chat_month(self, month, q):
        return month_agent.run_month_query(
            self._ai_client(), self.db, month, self.config, q, max_rounds=5)

    def _on_ai_chat_done(self, ok, payload):
        if not ok:
            self.ai_answer.setPlainText(f"错误：{payload}")
            return
        steps = payload.get("steps") or []
        think_lines = []
        if steps:
            think_lines.append("【工具调用链路】")
            for i, s in enumerate(steps, 1):
                status = "✅" if s.get("ok") else "❌"
                args = s.get("args") or {}
                arg_s = " ".join(f"{k}={v}" for k, v in args.items()) if args else ""
                think_lines.append(f"  {i}. {status} {s['tool']}({arg_s})")
        else:
            think_lines.append("（未调用工具，直接作答）")
        if payload.get("fallback"):
            think_lines.append("\n⚠️ 当前模型不支持工具调用，已降级为预计算摘要 + 单次问答")
        self.ai_think.setPlainText("\n".join(think_lines))

        thinking = (payload.get("thinking") or "").strip()
        answer = payload.get("answer") or "（模型未返回内容）"
        self.ai_answer.setPlainText((f"【思考】\n{thinking}\n\n" if thinking else "") + f"【回答】\n{answer}")

        # 追加历史
        q = self.ai_input.text().strip()
        prev = self.ai_history.toPlainText()
        new_entry = f"[月度] {q}\n→ {answer[:120]}{'…' if len(answer) > 120 else ''}\n"
        self.ai_history.setPlainText(new_entry + "\n" + prev)
        self.ai_input.clear()

    # ---------------- 后台任务 ----------------
    def _run_worker(self, fn, on_done, *args):
        worker = Worker(fn, *args)
        self._workers.append(worker)

        def _finish(ok, payload):
            try:
                on_done(ok, payload)
            except Exception:
                log.exception("任务回调异常")
            self._worker_finished(worker)

        worker.done.connect(_finish)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _worker_finished(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)

    # ---------------- 其他 ----------------
    def open_settings(self):
        dlg = SettingsDialog(self.config, self, on_reidentify=self.reidentify_devices)
        dlg.exec()

    def open_logs(self):
        dlg = LogsDialog(self)
        dlg.exec()

    def open_data_dir(self):
        try:
            os.startfile(str(self.data_dir))  # noqa: S606  Windows only
        except Exception as e:
            log.warning("打开数据目录失败: %s", e)

    def export_gpx(self):
        """导出当前活动为 GPX 文件。"""
        if not self.cur_activity:
            QMessageBox.information(self, "提示", "请先在左侧选中一条活动记录")
            return
        act = self.cur_activity
        default_name = f"{act.get('start_time','')[:10]}_{act.get('name','骑行')}.gpx"
        default_name = default_name.replace(" ", "_").replace("/", "-").replace("\\", "-")
        path, _ = QFileDialog.getSaveFileName(self, "导出 GPX", str(Path.home() / "Desktop" / default_name), "GPX 文件 (*.gpx)")
        if not path:
            return
        try:
            from core import gpx_export
            records = self.cur_records if hasattr(self, 'cur_records') else analysis.estimate_power(self.db.get_records(act["id"]), self.config)
            laps = self.cur_laps if hasattr(self, 'cur_laps') else self.db.get_laps(act["id"])
            gpx_export.export_gpx(act, records, laps=laps, output_path=path)
            self.statusBar().showMessage(f"GPX 已导出: {Path(path).name}", 5000)
            log.info("GPX 导出成功: %s", path)
        except Exception as e:
            log.exception("GPX 导出失败")
            QMessageBox.critical(self, "导出失败", str(e))

    def open_route(self):
        """打开路书分析对话框。"""
        from gui.route_dialog import RouteDialog
        dlg = RouteDialog(self, ai_client_factory=self._ai_client,
                          ai_enabled=self.config.get("ai_enabled"))
        dlg.exec()

    def export_route(self):
        """把当前活动一键转成路书：解析轨迹 → 海拔/爬坡分析 → 弹出路书对话框。"""
        if not self.cur_activity:
            QMessageBox.information(self, "提示", "请先在左侧选中一条活动记录")
            return
        act = self.cur_activity
        try:
            from core import route
            records = self.cur_records if hasattr(self, 'cur_records') else self.db.get_records(act["id"])
            r = route.route_from_records(act.get("name") or "骑行", records)
        except Exception as e:
            QMessageBox.critical(self, "转路书失败", str(e))
            return

        from gui.route_dialog import RouteDialog
        dlg = RouteDialog(self, ai_client_factory=self._ai_client,
                          ai_enabled=self.config.get("ai_enabled"))
        dlg.load_route(r)
        dlg.exec()
