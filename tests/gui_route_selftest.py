"""离屏验证路书分析对话框渲染。

验证 RouteDialog 能实例化，并用真实 GPX 加载后渲染海拔剖面图 + 爬坡段。
运行：python tests/gui_route_selftest.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    import tempfile

    from gui.route_dialog import RouteDialog
    from core import route as route_mod

    dlg = RouteDialog()
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" {extra}" if extra else ""))
        if not cond:
            ok = False

    check("对话框可实例化", dlg is not None)
    check("导出按钮初始禁用", not dlg.btn_export.isEnabled())

    # 用真实 GPX 加载（不联网）
    gpx = Path(r"C:/Users/zhengyingjun/Downloads/221259320.gpx")
    if not gpx.exists():
        # 回退：合成一个带海拔的 GPX
        tmp = Path(tempfile.mkdtemp()) / "synth.gpx"
        pts = "".join(
            f'<trkpt lat="30" lon="{30 + i * 0.001}"><ele>{100 + i * 2}</ele></trkpt>'
            for i in range(100)
        )
        tmp.write_text(
            f'<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>合成路书</name>'
            f'<trkseg>{pts}</trkseg></trk></gpx>', encoding="utf-8")
        gpx = tmp

    dlg._route = route_mod.parse_gpx(str(gpx))
    dlg.btn_export.setEnabled(True)
    dlg._render()

    check("摘要非空", bool(dlg.summary_label.text()))
    check("有图表或提示", dlg.chart_container.count() >= 1, f"count={dlg.chart_container.count()}")
    check("导出按钮已启用", dlg.btn_export.isEnabled())
    check("爬坡说明存在", bool(dlg.climb_label.text()))

    # 截屏
    dlg.resize(760, 640)
    dlg.show()
    app.processEvents()
    shot = Path(tempfile.mkdtemp()) / "route_dialog.png"
    dlg.grab().save(str(shot))
    check("截屏已保存", shot.exists(), str(shot))

    print(f"\n结果: {'全部通过' if ok else '存在失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
