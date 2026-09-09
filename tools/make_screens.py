# -*- coding: utf-8 -*-
"""重新生成 README 截图（imgs/*.png），使文档与当前界面保持一致。

用法：
    .venv/Scripts/python.exe tools/make_screens.py [--data-dir PATH]

说明：
- 优先使用 --data-dir 里的现有数据库；库为空时自动从本机 FIT 目录
  （F:\\byciclefits 或 Documents\\deepseek\\fittestdata）导入
- 真实桌面平台渲染：窗口设 WA_DontShowOnScreen（不会真的弹到屏幕上，
  且中文字体正常，区别于 --selftest 的 offscreen 模式），grab() 截图
- 每次界面有改动后重跑一遍即可刷新 README 里的截图
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

IMGS = ROOT / "imgs"


def _settle(app, n=20):
    """处理事件循环，让图表/控件完成布局与渲染。"""
    for _ in range(n):
        app.processEvents()
        time.sleep(0.03)


def _tab_index(tabs, text):
    for i in range(tabs.count()):
        if tabs.tabText(i) == text:
            return i
    return 0


def main():
    parser = argparse.ArgumentParser(description="重新生成 README 截图")
    parser.add_argument("--data-dir", default=None, help="数据目录（默认 .tmp/screens_data）")
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else ROOT / ".tmp" / "screens_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from core import db as db_mod, fit_parser, logging_setup
    from core.config import Config

    logging_setup.setup_logging(data_dir, console=False)
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    from gui.theme import QSS, apply_light_palette
    apply_light_palette(app)
    app.setStyleSheet(QSS)

    config = Config(data_dir / "config.json")
    db = db_mod.DB(data_dir / "fit.db")
    if db.count() == 0:
        fit_dir = None
        for cand in (Path(r"F:\byciclefits"),
                     Path(r"C:\Users\zhengyingjun\Documents\deepseek\fittestdata")):
            if cand.exists() and any(cand.rglob("*.fit")):
                fit_dir = cand
                break
        if fit_dir is None:
            print("!! 无活动数据且未找到本机 FIT 目录，无法生成截图")
            return 1
        results, _ = fit_parser.parse_many(sorted(fit_dir.rglob("*.fit")))
        for r in results:
            db.upsert_activity(r["data"])
        print(f"已从 {fit_dir} 导入 {len(results)} 条活动")

    from app import list_backgrounds
    from gui.main_window import MainWindow

    win = MainWindow(data_dir, config, db, list_backgrounds())
    win.setAttribute(Qt.WA_DontShowOnScreen, True)  # 不弹窗，但用真实平台渲染（字体正常）
    win.resize(1680, 950)  # 宽度足够容纳月度页全部卡片，避免截图出现横向裁切
    win.show()
    _settle(app, 30)

    def snap(widget, name):
        _settle(app)
        widget.grab().save(str(IMGS / f"{name}.png"))
        print(f"  ✓ {name}.png")

    months = db.months()
    if not months:
        print("!! 数据库无活动，无法生成截图")
        return 1

    # 1) 月概览（含年度目标 / 训练日历热力图 / 训练负荷）
    win.show_month(months[0]["month"])
    snap(win, "月概览")

    # 2-5) 单活动各标签页
    acts = db.list_activities(month=months[0]["month"])
    win.show_activity(acts[0]["id"])
    snap(win, "单次活动概览")
    win.act_page.setCurrentIndex(_tab_index(win.act_page, "活动详情"))
    snap(win, "活动详情")
    win.act_page.setCurrentIndex(_tab_index(win.act_page, "轨迹"))
    snap(win, "骑行路径")
    win.act_page.setCurrentIndex(_tab_index(win.act_page, "AI 分析"))
    snap(win, "ai分析")

    # 6) 路书分析对话框（历史活动一键转路书）
    from core import route as route_mod
    r = route_mod.route_from_records("示例路书", db.get_records(acts[0]["id"]))
    from gui.route_dialog import RouteDialog
    dlg = RouteDialog(win, ai_client_factory=None, ai_enabled=False)
    dlg.setAttribute(Qt.WA_DontShowOnScreen, True)
    dlg.resize(760, 720)
    dlg.show()
    dlg.load_route(r)
    snap(dlg, "路书规划-路径点模式")
    dlg.close()

    # 7) 自动规划路书对话框
    from gui.auto_plan_dialog import AutoPlanDialog
    dlg2 = AutoPlanDialog(config, parent=win)
    dlg2.setAttribute(Qt.WA_DontShowOnScreen, True)
    dlg2.resize(560, 520)
    dlg2.show()
    snap(dlg2, "路径规划，ai自动模式")
    dlg2.close()

    win.close()
    db.close()
    print(f"\n截图已更新到 {IMGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
