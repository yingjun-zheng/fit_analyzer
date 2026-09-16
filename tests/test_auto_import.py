"""自动导入（P3）定向单测：scan_new_files 指纹识别 + GUI 轮询全链路。

直接跑：python tests/test_auto_import.py
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.auto_import import scan_new_files

_ok, _fail = 0, 0


def check(name, cond, extra=""):
    global _ok, _fail
    print(("  [PASS]" if cond else "  [FAIL]"), name, extra)
    _ok, _fail = _ok + (1 if cond else 0), _fail + (0 if cond else 1)


def main():
    d = Path(tempfile.mkdtemp())

    print("== scan_new_files 指纹识别 ==")
    seen = {}
    new, seen = scan_new_files(d, seen)
    check("空目录 → 无新文件", new == [] and seen == {})

    new, seen = scan_new_files(str(d / "不存在"), seen)
    check("目录不存在 → 无新文件不报错", new == [])

    f1 = d / "a.fit"
    f1.write_bytes(b"FIT-A")
    (d / "b.txt").write_text("ignore me")
    sub = d / "sub"
    sub.mkdir()
    (sub / "c.fit").write_bytes(b"FIT-C")  # 子目录不扫
    new, seen = scan_new_files(d, seen)
    check("只识别顶层 .fit", new == [str(f1)], str(new))

    new, seen = scan_new_files(d, seen)
    check("未变化不再报新", new == [])

    f1.write_bytes(b"FIT-A-CHANGED")  # 内容变化（size/mtime 变）
    new, seen = scan_new_files(d, seen)
    check("文件变化重新报新", new == [str(f1)])

    f1.unlink()
    new, seen = scan_new_files(d, seen)
    check("已删除文件从 seen 清除", str(f1) not in seen and new == [])

    print("== GUI 轮询全链路（真实 MainWindow + 真实 FIT）==")
    real_fit_dir = Path(r"C:\Users\zhengyingjun\Documents\deepseek\fittestdata")
    real_fits = sorted(real_fit_dir.glob("*.fit"))
    if not real_fits:
        print("  [SKIP] 无真实 FIT 测试数据")
    else:
        os_environ_set()
        app = get_app()

        data_dir = Path(tempfile.mkdtemp())
        from core.config import Config
        from core import db as db_mod
        config = Config(data_dir / "config.json")
        db = db_mod.DB(data_dir / "fit.db")
        from gui.main_window import MainWindow
        win = MainWindow(data_dir, config, db, [])

        watch = data_dir / "watch"
        watch.mkdir()
        config.set("auto_import_enabled", True)
        config.set("auto_import_dir", str(watch))

        # 启动基线轮：目录为空 → 只建立基线
        win._auto_import_tick()
        check("基线轮后 auto_baseline=False", win._auto_baseline is False)

        # 拷入真实 FIT → 下一次 tick 应派发 worker
        shutil.copy(real_fits[0], watch / real_fits[0].name)
        win._auto_import_tick()
        check("发现新文件后 worker 启动（auto_busy=True）", win._auto_busy is True)

        # 事件循环外用 processEvents 等 worker 完成（超时 30s）
        t0 = time.monotonic()
        while win._auto_busy and time.monotonic() - t0 < 30:
            app.processEvents()
            time.sleep(0.05)
        check("worker 完成（auto_busy=False）", win._auto_busy is False)
        check("活动入库 1 条", db.count() == 1, str(db.count()))

        # 再次 tick：文件未变 → 不重复导入
        win._auto_import_tick()
        time.sleep(0.2)
        app.processEvents()
        check("未变化不重复派发", win._auto_busy is False and db.count() == 1)

        # 关闭开关 → tick 直接返回
        config.set("auto_import_enabled", False)
        shutil.copy(real_fits[1], watch / real_fits[1].name)
        win._auto_import_tick()
        check("开关关闭不派发", win._auto_busy is False and db.count() == 1)

        db.close()
    print(f"结果: {_ok} 通过, {_fail} 失败")
    sys.exit(1 if _fail else 0)


def os_environ_set():
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"


_APP = None


def get_app():
    global _APP
    from PySide6.QtWidgets import QApplication
    if _APP is None:
        _APP = QApplication([])
    return _APP


if __name__ == "__main__":
    main()
