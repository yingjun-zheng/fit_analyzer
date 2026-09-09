"""装备维护管家对话框：装备台账 + 里程驱动的保养提醒。

- 台账：名称/类型/启用日期/累计里程/预期寿命/使用进度/状态
- 状态色：>=100% 红（建议更换）、70%~100% 橙（关注）、其余绿（良好）
- 保养归零：更换/保养后把启用日期重置为今天，重新计寿命
- 退役：不再参与提醒（里程截止到退役日）
"""
import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core import gear as gear_mod

_STATUS_COLOR = {"due": "#e53935", "watch": "#f57c00", "ok": "#43a047", "none": "#7a8794"}
_LEVEL_CN = {"due": "建议更换", "watch": "关注", "ok": "良好", "none": "未设寿命"}


class _GearEditDialog(QDialog):
    """添加 / 编辑装备的子表单。"""

    def __init__(self, parent=None, item=None):
        super().__init__(parent)
        self.setWindowTitle("编辑装备" if item else "添加装备")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)

        self.ed_name = QLineEdit((item or {}).get("name") or "")
        self.ed_name.setPlaceholderText("如：ATX810 原装链条")
        self.cb_type = QComboBox()
        self.cb_type.setEditable(True)
        self.cb_type.addItems(list(gear_mod.GEAR_TYPES.keys()))
        self.cb_type.setCurrentText((item or {}).get("type") or "链条")
        start = (item or {}).get("start_date")
        self.de_start = QDateEdit(QDate.currentDate(), calendarPopup=True,
                                  displayFormat="yyyy-MM-dd")
        if start:
            qd = QDate.fromString(start, "yyyy-MM-dd")
            if qd.isValid():
                self.de_start.setDate(qd)
        self.ed_initial = QLineEdit(str((item or {}).get("initial_km") or 0))
        self.ed_initial.setPlaceholderText("启用时已有里程（新件填 0）")
        self.ed_expected = QLineEdit(str((item or {}).get("expected_km") or ""))
        self.ed_expected.setPlaceholderText(f"预期寿命 km（留空不提醒；如链条 {gear_mod.GEAR_TYPES['链条']}）")
        self.ed_note = QLineEdit((item or {}).get("note") or "")

        for label, w in [("名称", self.ed_name), ("类型", self.cb_type),
                         ("启用日期", self.de_start), ("启用时已有里程 km", self.ed_initial),
                         ("预期寿命 km", self.ed_expected), ("备注", self.ed_note)]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setMinimumWidth(110)
            row.addWidget(lbl)
            row.addWidget(w, 1)
            lay.addLayout(row)

        buttons = QHBoxLayout()
        btn_ok = QPushButton("保存")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(btn_ok)
        buttons.addWidget(btn_cancel)
        lay.addLayout(buttons)

    def fields(self):
        """收集表单为 dict；非法输入返回 (None, 错误信息)。"""
        name = self.ed_name.text().strip()
        if not name:
            return None, "请填写名称"
        try:
            initial = float(self.ed_initial.text().strip() or "0")
            expected = float(self.ed_expected.text().strip() or "0")
        except ValueError:
            return None, "里程/寿命需为数字"
        d = self.de_start.date().toString("yyyy-MM-dd")
        return {
            "name": name, "type": self.cb_type.currentText().strip(),
            "start_date": d, "start_ts": gear_mod.date_to_ts(d),
            "initial_km": max(0.0, initial), "expected_km": max(0.0, expected),
            "note": self.ed_note.text().strip(),
        }, ""


class GearDialog(QDialog):
    """装备管家主对话框。"""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("装备管家（里程驱动的保养提醒）")
        self.resize(820, 480)
        lay = QVBoxLayout(self)

        tip = QLabel("装备里程 = 启用日期以来的全部活动里程（+启用时已有里程）。"
                     "达到预期寿命自动提醒；更换/保养后点「保养归零」重新计时。")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["名称", "类型", "启用日期", "累计里程", "预期寿命", "使用进度", "状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        lay.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        for text, handler, primary in [
                ("➕ 添加", self._add, True), ("✏️ 编辑", self._edit, False),
                ("🔄 保养归零", self._reset, False), ("📦 退役/恢复", self._retire_toggle, False),
                ("🗑 删除", self._delete, False)]:
            btn = QPushButton(text)
            if primary:
                btn.setObjectName("primary")
            btn.clicked.connect(handler)
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        self.refresh()

    def refresh(self):
        report = gear_mod.gear_report(self.db, include_retired=True)
        self.table.setRowCount(len(report))
        for r, s in enumerate(report):
            status = "已退役" if s["retired"] else _LEVEL_CN[s["level"]]
            vals = [s["name"], s["type"] or "—", s["start_date"] or "—",
                    f"{s['km']:.0f} km",
                    f"{s['expected_km']:.0f} km" if s["expected_km"] else "—",
                    f"{s['pct']:.0f}%" if s["pct"] is not None else "—", status]
            color = QColor(_STATUS_COLOR.get(s["level"], "#26313b"))
            if s["retired"]:
                color = QColor("#b0b8c0")
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if c >= 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setData(Qt.UserRole, s["id"])
                item.setToolTip(s["advice"])
                if c in (5, 6):
                    item.setForeground(QBrush(color))
                self.table.setItem(r, c, item)

    def _selected_gear(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        gid = it.data(Qt.UserRole) if it else None
        for g in self.db.gear_list():
            if g["id"] == gid:
                return g
        return None

    def _add(self):
        dlg = _GearEditDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        f, err = dlg.fields()
        if not f:
            QMessageBox.information(self, "提示", err)
            return
        self.db.gear_add(f["name"], f["type"], f["start_date"], f["start_ts"],
                         f["initial_km"], f["expected_km"], f["note"])
        self.refresh()

    def _edit(self):
        g = self._selected_gear()
        if not g:
            QMessageBox.information(self, "提示", "请先选中一件装备")
            return
        dlg = _GearEditDialog(self, item=g)
        if dlg.exec() != QDialog.Accepted:
            return
        f, err = dlg.fields()
        if not f:
            QMessageBox.information(self, "提示", err)
            return
        self.db.gear_update(g["id"], f)
        self.refresh()

    def _reset(self):
        g = self._selected_gear()
        if not g:
            QMessageBox.information(self, "提示", "请先选中一件装备")
            return
        if QMessageBox.question(self, "保养归零",
                                f"把「{g['name']}」的启用日期重置为今天？\n（更换/保养完成后使用，里程重新计）",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        today = datetime.date.today().isoformat()
        self.db.gear_update(g["id"], {"start_date": today,
                                      "start_ts": gear_mod.date_to_ts(today),
                                      "initial_km": 0})
        self.refresh()

    def _retire_toggle(self):
        g = self._selected_gear()
        if not g:
            QMessageBox.information(self, "提示", "请先选中一件装备")
            return
        if g["retired"]:
            self.db.gear_update(g["id"], {"retired": 0, "retired_ts": None})
        else:
            self.db.gear_update(g["id"], {"retired": 1,
                                          "retired_ts": int(datetime.datetime.now().timestamp())})
        self.refresh()

    def _delete(self):
        g = self._selected_gear()
        if not g:
            QMessageBox.information(self, "提示", "请先选中一件装备")
            return
        if QMessageBox.question(self, "删除装备", f"确定删除「{g['name']}」？",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.db.gear_delete(g["id"])
        self.refresh()
