"""界面主题：骑行配色（Strava 橙 × 炭灰深色）+ 扁平圆角 QSS（sound-sleuth 式布局语言）。

配色依据主流骑行平台的惯例：
- 品牌/强调色：Strava 橙 #FC5200（骑行软件最具辨识度的品牌色；深色底上只用于
  强调元素，不做正文颜色，避免对比度/视觉振动问题）。
- 深色底：近黑炭灰（Strava / Garmin Connect 深色模式同款思路），数据线高对比。
- 训练负荷三线：TrainingPeaks 惯例 —— CTL 蓝 / ATL 紫 / TSB 黄。
- 心率五区（灰→绿→黄→橙→红）、爬坡分级（Cat4→HC 黄→深红）、
  海拔渐变（绿→黄→红）：骑行圈通用的语义色，深浅主题下都保留。
"""

from PySide6.QtGui import QColor, QPalette


THEMES = {
    # ---------------- 深色（默认）：炭灰底 + 骑行橙 ----------------
    "dark": {
        "bg": "#14161a",
        "surface": "#1d2026",
        "surface2": "#262b33",
        "border": "#2e3440",
        "text": "#eceff3",
        "muted": "#8f9aa8",
        "accent": "#fc5200",
        "accent_hover": "#ff6a1f",
        "accent_text": "#1a0e06",
        "accent_soft": "#3a2317",
        "accent_text_soft": "#ffab73",
        "danger": "#ff5252",
        "ok": "#66bb6a",
        "warn": "#ffa726",
        # 图表
        "chart_axis": "#8f9aa8",
        "chart_grid": "#262b33",
        "bubble_bg": "#2a2f38",
        "bubble_text": "#eceff3",
        "line_strong": "#eceff3",
        "alt_outline": "#cfd6df",
        "overlay_line": "#ff7a3d",
        "scatter_border": "#1d2026",
        "primary_series": "#fc5200",
        # 数据系列（骑行语义色）
        "series": {
            "speed": "#4da3ff", "hr": "#ff5252", "cad": "#9ccc65",
            "power": "#ffa726", "temp": "#26c6da",
            "ctl": "#4da3ff", "atl": "#c084fc", "tsb": "#f5c542",
            "dist": "#fc5200", "count": "#4da3ff",
        },
        # 训练日历热力图：橙梯度（Strava 年度热力图同款思路）
        "heatmap": ["#23262c", "#5a3119", "#8f4415", "#c85a12", "#fc5200"],
    },
    # ---------------- 浅色（可选）：白底 + 橙强调 ----------------
    "light": {
        "bg": "#f4f6f8",
        "surface": "#ffffff",
        "surface2": "#eef1f5",
        "border": "#d9e0e7",
        "text": "#1c2733",
        "muted": "#6b7887",
        "accent": "#f4511e",
        "accent_hover": "#e64a19",
        "accent_text": "#ffffff",
        "accent_soft": "#fde8dd",
        "accent_text_soft": "#c93e10",
        "danger": "#e53935",
        "ok": "#43a047",
        "warn": "#f57c00",
        "chart_axis": "#6b7887",
        "chart_grid": "#e8edf3",
        "bubble_bg": "#0c447c",
        "bubble_text": "#ffffff",
        "line_strong": "#111111",
        "alt_outline": "#37474f",
        "overlay_line": "#185fa5",
        "scatter_border": "#ffffff",
        "primary_series": "#f4511e",
        "series": {
            "speed": "#1e6fd9", "hr": "#e53935", "cad": "#558b2f",
            "power": "#ef6c00", "temp": "#0097a7",
            "ctl": "#1e6fd9", "atl": "#ab47bc", "tsb": "#b98a1d",
            "dist": "#f4511e", "count": "#1e6fd9",
        },
        "heatmap": ["#eef1f5", "#f7cdb4", "#f2a377", "#ea7a3c", "#e05a00"],
    },
}

_CURRENT = "dark"


def set_theme(name):
    """切换当前主题（"dark" / "light"）。QSS()/T() 等随取随新。"""
    global _CURRENT
    _CURRENT = name if name in THEMES else "dark"


def current():
    return _CURRENT


def T(key):
    """取当前主题的 token（hex 字符串）。"""
    return THEMES[_CURRENT][key]


def series():
    """当前主题的数据系列语义色（speed/hr/cad/power/ctl/atl/tsb/...）。"""
    return THEMES[_CURRENT]["series"]


def heatmap_levels():
    """当前主题的训练日历热力图 5 级配色。"""
    return THEMES[_CURRENT]["heatmap"]


def apply_palette(app):
    """按当前主题设置 QPalette（防 Windows 系统深色模式把未样式化控件画花）。"""
    dark = _CURRENT == "dark"
    t = THEMES[_CURRENT]
    p = QPalette()
    p.setColor(QPalette.Window, QColor(t["bg"]))
    p.setColor(QPalette.WindowText, QColor(t["text"]))
    p.setColor(QPalette.Base, QColor(t["surface"]))
    p.setColor(QPalette.AlternateBase, QColor(t["surface2"]))
    p.setColor(QPalette.Text, QColor(t["text"]))
    p.setColor(QPalette.Button, QColor(t["surface"]))
    p.setColor(QPalette.ButtonText, QColor(t["text"]))
    p.setColor(QPalette.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.Highlight, QColor(t["accent"]))
    p.setColor(QPalette.HighlightedText, QColor(t["accent_text"]))
    p.setColor(QPalette.Link, QColor(t["accent"]))
    p.setColor(QPalette.Light, QColor(t["surface2"]))
    p.setColor(QPalette.Midlight, QColor(t["border"]))
    p.setColor(QPalette.Mid, QColor(t["border"]))
    p.setColor(QPalette.Dark, QColor("#000000" if dark else "#b8c2cc"))
    p.setColor(QPalette.Shadow, QColor("#000000" if dark else "#a0aab4"))
    p.setColor(QPalette.ToolTipBase, QColor(t["bubble_bg"]))
    p.setColor(QPalette.ToolTipText, QColor(t["bubble_text"]))
    p.setColor(QPalette.PlaceholderText, QColor(t["muted"]))
    app.setPalette(p)


def QSS():
    """扁平圆角 QSS（布局语言参考 sound-sleuth：大圆角卡片、药丸选中态、hover 高亮边）。"""
    t = THEMES[_CURRENT]
    return f"""
QWidget {{ font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "Segoe UI"; font-size: 13px; color: {t['text']}; }}
QMainWindow, QDialog {{ background: {t['bg']}; }}
QToolBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; spacing: 4px; padding: 6px 10px; }}
QToolBar::separator {{ width: 1px; background: {t['border']}; margin: 5px 8px; }}
QToolBar QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 6px 14px; }}
QToolBar QToolButton:hover {{ background: {t['surface2']}; color: {t['accent_text_soft']}; }}
QToolBar QToolButton:pressed {{ background: {t['accent_soft']}; }}
QMenuBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
QMenuBar::item {{ padding: 6px 12px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {t['surface2']}; color: {t['accent_text_soft']}; }}
QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 28px 7px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['accent_text_soft']}; }}
QMenu::item:disabled {{ color: {t['muted']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 5px 14px; }}
QPushButton:hover {{ border-color: {t['accent']}; color: {t['accent_text_soft']}; }}
QPushButton:pressed {{ background: {t['surface2']}; }}
QPushButton:disabled {{ color: {t['muted']}; border-color: {t['border']}; background: transparent; }}
QPushButton#primary {{ background: {t['accent']}; color: {t['accent_text']}; border: 1px solid {t['accent']}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {t['accent_hover']}; color: {t['accent_text']}; }}
QPushButton#danger {{ color: {t['danger']}; border-color: {t['danger']}; }}
QPushButton#danger:hover {{ background: rgba(255,82,82,0.12); border-color: {t['danger']}; }}
QTreeWidget, QTableWidget, QPlainTextEdit, QTextEdit, QListWidget {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;
    alternate-background-color: {t['surface2']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['accent_text_soft']};
}}
QTreeWidget::item {{ padding: 4px 2px; }}
QTreeWidget::item:selected {{ background: {t['accent_soft']}; color: {t['accent_text_soft']}; }}
QTreeWidget::item:hover {{ background: {t['surface2']}; }}
QHeaderView::section {{ background: {t['surface2']}; border: none; border-bottom: 1px solid {t['border']}; padding: 5px 8px; font-weight: 600; color: {t['muted']}; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; background: {t['surface']}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ padding: 7px 16px; margin: 2px; background: transparent; color: {t['muted']}; border-radius: 6px; }}
QTabBar::tab:selected {{ background: {t['accent_soft']}; color: {t['accent_text_soft']}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; color: {t['muted']}; }}
QScrollArea {{ border: none; background: transparent; }}
QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
QFrame#stat {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
QFrame#stat:hover {{ border: 1px solid {t['accent']}; }}
QLabel#statKey {{ color: {t['muted']}; font-size: 11px; }}
QLabel#statVal {{ font-size: 21px; font-weight: 700; color: {t['text']}; }}
QLabel#statUnit {{ color: {t['muted']}; font-size: 11px; }}
QLabel#h2 {{ font-size: 17px; font-weight: 700; }}
QLabel#h3 {{ font-size: 14px; font-weight: 700; }}
QLabel#muted {{ color: {t['muted']}; font-size: 11px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 4px 8px;
    selection-background-color: {t['accent_soft']}; selection-color: {t['accent_text_soft']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{ border-color: {t['accent']}; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']}; selection-background-color: {t['accent_soft']}; selection-color: {t['accent_text_soft']}; }}
QCheckBox {{ spacing: 6px; }}
QMessageBox {{ background: {t['bg']}; }}
QMessageBox QLabel {{ font-size: 13px; color: {t['text']}; }}
QProgressBar {{ border: none; border-radius: 5px; text-align: center; background: {t['surface2']}; color: {t['text']}; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 5px; }}
QSplitter::handle {{ background: {t['bg']}; width: 3px; }}
QToolTip {{ background: {t['bubble_bg']}; color: {t['bubble_text']}; border: 1px solid {t['border']}; padding: 4px 8px; }}
QTableCornerButton::section {{ background: {t['surface2']}; border: none; }}
QAbstractScrollArea::corner {{ background: transparent; border: none; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; border: none; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 30px; margin: 2px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['muted']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; border: none; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


# ---------------- 兼容旧调用（app.py 已改用 set_theme + apply_palette） ----------------

def apply_light_palette(app):
    """旧接口：强制浅色。保留给可能的外部引用；应用入口已改用 apply_palette。"""
    set_theme("light")
    apply_palette(app)


def __getattr__(name):
    # 模块级 `QSS` 兼容导出（PEP 562）：`from gui.theme import QSS` 仍可用，
    # 且取值时按当前主题即时构建。
    if name == "QSS":
        return QSS()
    raise AttributeError(name)


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
