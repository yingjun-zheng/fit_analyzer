"""界面主题样式（QSS）与格式化工具。"""

from PySide6.QtGui import QColor, QPalette


def apply_light_palette(app):
    """强制浅色调色板（用户 Windows 若为深色模式，Qt 默认调色板会把窗口/图表画成深色）。"""
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#f4f6f8"))
    p.setColor(QPalette.WindowText, QColor("#26313b"))
    p.setColor(QPalette.Base, QColor("#ffffff"))
    p.setColor(QPalette.AlternateBase, QColor("#f7fafd"))
    p.setColor(QPalette.Text, QColor("#26313b"))
    p.setColor(QPalette.Button, QColor("#ffffff"))
    p.setColor(QPalette.ButtonText, QColor("#26313b"))
    p.setColor(QPalette.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.Highlight, QColor("#1e88e5"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Link, QColor("#1e88e5"))
    p.setColor(QPalette.Light, QColor("#ffffff"))
    p.setColor(QPalette.Midlight, QColor("#e8edf2"))
    p.setColor(QPalette.Mid, QColor("#d0d8e0"))
    p.setColor(QPalette.Dark, QColor("#b8c2cc"))
    p.setColor(QPalette.Shadow, QColor("#a0aab4"))
    p.setColor(QPalette.ToolTipBase, QColor("#26313b"))
    p.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    app.setPalette(p)

QSS = """
QWidget { font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI"; font-size: 13px; color: #26313b; }
QMainWindow, QDialog { background: #f4f6f8; }
QToolBar { background: #ffffff; border-bottom: 1px solid #dde3e8; spacing: 8px; padding: 6px 8px; }
QToolBar QToolButton { background: #ffffff; border: 1px solid #c9d2da; border-radius: 5px; padding: 5px 14px; }
QToolBar QToolButton:hover { border-color: #1e88e5; color: #1e88e5; }
QToolBar QToolButton:pressed { background: #eef4fb; }
QPushButton { background: #ffffff; border: 1px solid #c9d2da; border-radius: 5px; padding: 5px 14px; }
QPushButton:hover { border-color: #1e88e5; color: #1e88e5; }
QPushButton:pressed { background: #eef4fb; }
QPushButton:disabled { color: #b0b8c0; border-color: #e0e5ea; }
QPushButton#primary { background: #1e88e5; color: white; border: 1px solid #1e88e5; }
QPushButton#primary:hover { background: #1565c0; color: white; }
QPushButton#danger { color: #e53935; border-color: #f0b9b7; }
QPushButton#danger:hover { background: #fdecea; border-color: #e53935; }
QTreeWidget, QTableWidget, QPlainTextEdit, QTextEdit, QListWidget {
    background: white; border: 1px solid #dde3e8; border-radius: 6px; alternate-background-color: #f7fafd;
}
QTreeWidget::item { padding: 4px 2px; }
QTreeWidget::item:selected { background: #dcebfa; color: #1565c0; }
QTreeWidget::item:hover { background: #eef4fb; }
QHeaderView::section { background: #eef3f8; border: none; border-bottom: 1px solid #dde3e8; padding: 5px 8px; font-weight: 600; }
QTabWidget::pane { border: 1px solid #dde3e8; background: white; border-radius: 6px; top: -1px; }
QTabBar::tab { padding: 7px 16px; background: transparent; color: #7a8794; }
QTabBar::tab:selected { color: #1e88e5; border-bottom: 2px solid #1e88e5; font-weight: 600; }
QStatusBar { background: #ffffff; border-top: 1px solid #dde3e8; }
QScrollArea { border: none; background: transparent; }
QFrame#card { background: white; border: 1px solid #dde3e8; border-radius: 8px; }
QFrame#stat { background: #f7f9fb; border: 1px solid #dde3e8; border-radius: 8px; }
QLabel#statKey { color: #7a8794; font-size: 11px; }
QLabel#statVal { font-size: 15px; font-weight: 700; }
QLabel#h2 { font-size: 17px; font-weight: 700; }
QLabel#muted { color: #7a8794; font-size: 11px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #c9d2da; border-radius: 5px; padding: 4px 8px; }
QLineEdit:focus, QComboBox:focus { border-color: #1e88e5; }
QCheckBox { spacing: 6px; }
QMessageBox QLabel { font-size: 13px; }
QProgressBar { border: 1px solid #c9d2da; border-radius: 5px; text-align: center; background: white; }
QProgressBar::chunk { background: #1e88e5; border-radius: 4px; }
QSplitter::handle { background: #e8edf2; width: 3px; }
QToolTip { background: #26313b; color: white; border: none; padding: 4px 8px; }
QTableCornerButton::section { background: #eef3f8; border: none; }
QAbstractScrollArea::corner { background: #ffffff; border: none; }
QScrollBar:horizontal { background: #f0f2f5; height: 12px; border: none; }
QScrollBar::handle:horizontal { background: #b8c2cc; border-radius: 5px; min-width: 30px; margin: 2px; }
QScrollBar:vertical { background: #f0f2f5; width: 12px; border: none; }
QScrollBar::handle:vertical { background: #b8c2cc; border-radius: 5px; min-height: 30px; margin: 2px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""


def fmt_duration(sec):
    if sec is None:
        return "—"
    sec = int(round(float(sec)))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_km(km):
    if km is None:
        return "—"
    return f"{km:.2f} km" if km < 100 else f"{km:.1f} km"


def kmh(ms):
    if ms is None:
        return "—"
    return f"{ms * 3.6:.1f} km/h"


def fmt_dt(ts):
    return (ts or "")[:16]
