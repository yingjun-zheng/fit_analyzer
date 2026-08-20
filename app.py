"""骑行FIT数据分析器 - 纯桌面应用入口（PySide6，无浏览器/无本地服务）。"""
import argparse
import logging
import os
import sys
from pathlib import Path

APP_NAME = "骑行FIT数据分析器"
VERSION = "1.0.0"


def resource_path(rel):
    """兼容源码运行与 PyInstaller 打包。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / rel
    return Path(__file__).parent / rel


def default_data_dir():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "FitAnalyzer"


def list_backgrounds():
    """背景图集：backgrounds/ 目录下的所有图片；为空时回退 back9.jpeg。"""
    bg_dir = resource_path("backgrounds")
    exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
    if bg_dir.is_dir():
        files = sorted(p for p in bg_dir.iterdir() if p.suffix.lower() in exts)
        if files:
            return [str(p) for p in files]
    fallback = resource_path("back9.jpeg")
    return [str(fallback)] if Path(fallback).exists() else []


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--data-dir", default=None, help="数据目录（默认 %APPDATA%/FitAnalyzer）")
    parser.add_argument("--debug", action="store_true", help="更详细日志")
    parser.add_argument("--selftest", action="store_true", help="离屏自检：导入指定目录的 FIT 并打开一个活动后退出")
    parser.add_argument("--import-dir", default=None, help="自检模式：从此目录导入 FIT（默认 F:/byciclefits）")
    parser.add_argument("--quit-test", action="store_true", help="离屏启动后 2 秒自动退出（验证正常退出路径）")
    args = parser.parse_args()

    # 离屏自检需要 offscreen 平台
    if args.selftest:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    if args.quit_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from core import logging_setup
    from core.config import Config
    from core import db as db_mod

    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    logger = logging_setup.setup_logging(data_dir, level=logging.DEBUG if args.debug else logging.INFO)
    logger.info("=" * 60)
    logger.info("%s v%s 启动（桌面版）", APP_NAME, VERSION)
    logger.info("数据目录: %s", data_dir)

    config = Config(data_dir / "config.json")
    db = db_mod.DB(data_dir / "fit.db")
    logger.info("数据库中已有活动数: %d", db.count())

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("CycleRoutePlanner")
    app.setStyle("Fusion")

    from gui.main_window import MainWindow
    from gui.theme import QSS, apply_light_palette

    apply_light_palette(app)  # 先浅色调色板（防 Windows 深色模式导致黑色块）
    app.setStyleSheet(QSS)
    app.aboutToQuit.connect(db.close)

    win = MainWindow(data_dir, config, db, list_backgrounds())

    if args.selftest:
        code = _selftest(app, win, args)
        logger.info("自检完成 code=%d", code)
        sys.exit(code)

    if args.quit_test:
        logger.info("退出测试：2 秒后正常退出")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(2000, app.quit)
        code = app.exec()
        logger.info("正常退出路径完成 code=%d", code)
        sys.exit(code)

    win.show()
    logger.info("主窗口已显示")
    sys.exit(app.exec())


def _selftest(app, win, args):
    """离屏自检：导入真实 FIT → 打开活动 → 渲染各页 → 退出。"""
    import time as _t

    from core import fit_parser

    logger = logging.getLogger("fit.selftest")
    ok_all = True

    def check(name, cond):
        nonlocal ok_all
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            ok_all = False

    import_dir = Path(args.import_dir) if args.import_dir else Path(r"F:\byciclefits")
    if import_dir.exists():
        files = sorted(import_dir.glob("*.fit"))
        logger.info("自检：导入 %d 个 FIT", len(files))
        results, errors = fit_parser.parse_many(files)
        check("解析无错误", len(errors) == 0, )
        for r in results:
            win.db.upsert_activity(r["data"])
        win.load_months()
        months = win.db.months()
        check("月份加载", len(months) >= 1)
        if months:
            win.show_month(months[0]["month"])
            win.resize(1280, 820)
            for _ in range(15):
                app.processEvents()
                _t.sleep(0.05)
            win.grab().save(str(win.data_dir / "selftest_month.png"))
        acts = win.db.list_activities()
        check("活动列表", len(acts) >= 1)
        if acts:
            win.show_activity(acts[0]["id"])
            check("活动详情渲染", win.cur_activity is not None and win.cur_analysis is not None)
            for _ in range(15):
                app.processEvents()
                _t.sleep(0.05)
            win.grab().save(str(win.data_dir / "selftest_activity.png"))
            # 轨迹控件本身（含随机背景图）
            win.track_widget.grab().save(str(win.data_dir / "selftest_track.png"))
        check("窗口构建", win.month_tree.topLevelItemCount() >= 1)
    else:
        check("未找到 FIT 目录，跳过导入", True)

    print(f"\n自检结果: {'全部通过' if ok_all else '存在失败'}")
    logger.info("自检结束 ok=%s", ok_all)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
