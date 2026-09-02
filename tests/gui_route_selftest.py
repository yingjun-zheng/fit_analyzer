"""离屏验证路书分析对话框渲染（阶段二增强版）。

验证：RouteDialog 实例化、AI 解读按钮、load_route、海拔剖面（含爬坡段高亮）渲染。
运行：python tests/gui_route_selftest.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _climb_points(grad_pct=5.0, length_km=2.0, n=120):
    """构造一条已知坡度的爬坡路线（东西向直线，海拔线性上升）。"""
    # 每点前进 distance；坡度% = 海拔增量 / 水平距离；角 lon_step 对应实际距离约 111km/度
    lon_per_km = 1.0 / 111.0  # 纬度 30° 附近 1° 经度 ≈ 96km，简化用 111 系数
    step_km = length_km / n
    pts = []
    for i in range(n):
        lon = 30.0 + i * step_km * lon_per_km
        ele = 100.0 + i * step_km * grad_pct * 10.0  # % 坡 → 每 km 升 grad_pct*10 米
        pts.append((30.0, lon, round(ele, 1)))
    return pts


def main():
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    from gui.route_dialog import RouteDialog
    from core import route as route_mod

    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" {extra}" if extra else ""))
        if not cond:
            ok = False

    # 带 AI factory 的对话框（模拟主窗口传参）
    captured = {}

    def fake_factory():
        class A:
            pass
        return A()

    dlg = RouteDialog(ai_client_factory=fake_factory, ai_enabled=True)
    check("对话框可实例化", dlg is not None)
    check("AI 按钮存在", isinstance(dlg.btn_ai, QPushButton))
    check("AI 按钮初始禁用", not dlg.btn_ai.isEnabled())

    # 用合成爬坡数据转 route，测试 load_route + 爬坡高亮渲染
    try:
        from core import route
        r = route.route_from_records(
            "合成爬坡路书",
            [{"lat": lat, "lon": lon, "alt_m": ele} for lat, lon, ele in _climb_points()],
        )
        dlg.load_route(r)
    except Exception as e:
        check("load_route 成功", False, str(e))
        return 1

    check("load_route 后导出启用", dlg.btn_export.isEnabled())
    check("load_route 后 AI 启用", dlg.btn_ai.isEnabled())
    check("摘要非空", bool(dlg.summary_label.text()))
    check("图表区有内容", dlg.chart_container.count() >= 1, f"count={dlg.chart_container.count()}")
    check("有爬坡段说明", "爬坡" in dlg.climb_label.text(), dlg.climb_label.text()[:40])
    check("路书含爬坡段数据", len(r.get("climbs", [])) >= 1, f"climbs={len(r.get('climbs', []))}")

    # 截屏
    dlg.resize(760, 720)
    dlg.show()
    app.processEvents()
    shot = Path(tempfile.mkdtemp()) / "route_dialog_v2.png"
    dlg.grab().save(str(shot))
    check("截屏已保存", shot.exists(), str(shot))
    print(f"  截屏路径: {shot}")

    print(f"\n结果: {'全部通过' if ok else '存在失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
