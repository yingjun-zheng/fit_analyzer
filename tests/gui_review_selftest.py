"""离屏验证 GUI 复盘入口渲染（不启动真实窗口，QT_QPA_PLATFORM=offscreen）。

验证内容：
1. 活动详情「AI 分析」标签页存在，且含复盘输入框/按钮/输出框。
2. 切到该 tab 后控件可见、可交互（enabled）。
3. 截屏保存到 data_dir，供人工查看。

运行：
  python tests/gui_review_selftest.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import fit_parser, logging_setup
from core.config import Config
from core import db as db_mod


def _find_fit_dir():
    for cand in (Path(r"F:\byciclefits"), Path(r"C:\Users\zhengyingjun\Documents\deepseek\fittestdata")):
        if cand.exists() and any(cand.glob("*.fit")):
            return cand
    return None


def main():
    from PySide6.QtWidgets import QApplication, QTabWidget, QLineEdit, QPushButton, QTextEdit

    fit_dir = _find_fit_dir()
    if fit_dir is None:
        print("!! 未找到 FIT 数据")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="gui_review_"))
    logging_setup.setup_logging(tmp, console=False)
    cfg = Config(tmp / "config.json")
    db = db_mod.DB(tmp / "fit.db")
    rs, es = fit_parser.parse_many(sorted(fit_dir.glob("*.fit")))
    for r in rs:
        db.upsert_activity(r["data"])
    print(f"导入 {len(rs)} 条活动")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    from gui.main_window import MainWindow
    from gui.theme import QSS, apply_light_palette
    apply_light_palette(app)
    app.setStyleSheet(QSS)

    win = MainWindow(tmp, cfg, db, [])
    win.resize(1280, 820)
    win.show()

    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" {extra}" if extra else ""))
        if not cond:
            ok = False

    # 1. 活动页本身是 QTabWidget
    acts = db.list_activities()
    check("有活动数据", len(acts) >= 1)
    if acts:
        win.show_activity(acts[0]["id"])

    act_page = win.act_page
    check("活动页是 QTabWidget", isinstance(act_page, QTabWidget))

    # 2. 找到「AI 分析」tab
    ai_idx = None
    for i in range(act_page.count()):
        if act_page.tabText(i) == "AI 分析":
            ai_idx = i
            break
    check("存在「AI 分析」标签页", ai_idx is not None, f"tabs={[act_page.tabText(i) for i in range(act_page.count())]}")

    # 3. 复盘控件存在
    rv_input = getattr(win, "rv_input", None)
    rv_btn = getattr(win, "rv_btn", None)
    rv_text = getattr(win, "rv_text", None)
    check("复盘输入框存在", isinstance(rv_input, QLineEdit))
    check("复盘按钮存在", isinstance(rv_btn, QPushButton))
    check("复盘输出框存在", isinstance(rv_text, QTextEdit))

    # 3.5 确认已合并：不应再有重复的自然语言查询控件
    check("已删除重复 nl_query 输入框", not hasattr(win, "nl_input"))
    check("已删除重复 nl_query 按钮", not hasattr(win, "nl_btn"))
    check("已删除重复 nl_query 输出框", not hasattr(win, "nl_text"))

    # 4. 切到 AI 分析 tab，验证可见性
    if ai_idx is not None:
        act_page.setCurrentIndex(ai_idx)
        app.processEvents()
        check("复盘输入框可见", rv_input is not None and rv_input.isVisible())
        check("复盘按钮可见且可点击", rv_btn is not None and rv_btn.isVisible() and rv_btn.isEnabled())
        check("按钮文案正确", rv_btn is not None and "复盘" in rv_btn.text(), f"文案={rv_btn.text() if rv_btn else None}")
        check("输入框有提示语", rv_input is not None and bool(rv_input.placeholderText()), rv_input.placeholderText() if rv_input else "")

    # 5. 截屏（AI 分析 tab）
    shot = tmp / "review_tab.png"
    app.processEvents()
    pix = win.grab()
    pix.save(str(shot))
    check("截屏已保存", shot.exists(), str(shot))
    print(f"  截图路径: {shot}")

    print(f"\n结果: {'全部通过' if ok else '存在失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
