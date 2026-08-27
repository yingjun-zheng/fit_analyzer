"""离屏自检：TrackMapPanel（高德地图/图片背景 自动切换）逻辑验证。

不联网、不打开真实窗口（offscreen）。验证：
1. 未配置 Key：显示图片背景，底部出现「未配置高德地图 Key…」提醒
2. 配置 Key 但环境无 WebEngine：仍图片背景 + 「缺少 WebEngine」提醒
3. build_amap_html：Key/安全密钥/轨迹点全部正确注入 HTML
运行：python tests/test_amap_track.py（在项目根目录）
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import Config  # noqa: E402

app = QApplication([])

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


tmp = Path(tempfile.mkdtemp())
cfg = Config(tmp / "config.json")

from gui.amap_track import TrackMapPanel, build_amap_html, _HAS_WEBENGINE  # noqa: E402

bg = str(ROOT / "back9.jpeg")
points = [(41.75 + i * 1e-4, 123.44 + i * 1e-4, 40.0 + i * 0.1) for i in range(300)]

# --- 1. 未配置 Key：图片背景 + 提醒 ---
panel = TrackMapPanel(cfg, bg)
panel.resize(900, 500)
panel.set_track(points, bg, "轨迹点 300 个")
app.processEvents()
check("未配置Key→图片背景", panel.stack.currentWidget() is panel.image_w)
check("未配置Key→底部提醒", "未配置高德地图 Key" in panel.reminder.text())
check("未配置Key→轨迹已设置", len(panel.image_w.points) == 300)

# --- 2. 配置 Key（WebEngine 有无取决于环境） ---
cfg.set("amap_key", "TESTKEY123")
cfg.set("amap_security", "TESTSEC456")
panel2 = TrackMapPanel(cfg, bg)
panel2.resize(900, 500)
panel2.set_track(points, bg, "info")
app.processEvents()
if _HAS_WEBENGINE:
    check("有Key+WebEngine→切在线地图", panel2.stack.currentWidget() is panel2._map)
    check("有Key→无未配置提醒", "未配置高德地图 Key" not in panel2.reminder.text())
else:
    check("有Key但无WebEngine→仍图片背景", panel2.stack.currentWidget() is panel2.image_w)
    check("有Key但无WebEngine→WebEngine提醒", "WebEngine" in panel2.reminder.text())

# 无轨迹时即使有 Key 也应回退
panel3 = TrackMapPanel(cfg, bg)
panel3.set_track([], bg, "")
check("无轨迹→回退图片背景", panel3.stack.currentWidget() is panel3.image_w)

# --- 3. HTML 注入 ---
html = build_amap_html("TESTKEY123", "TESTSEC456", points)
check("HTML:Key注入", "key: 'TESTKEY123'" in html)
check("HTML:安全密钥注入", "TESTSEC456" in html)
m = re.search(r"var PTS = (.*?);", html, re.S)
check("HTML:轨迹点JSON合法", m and len(json.loads(m.group(1))) == 300)
check("HTML:占位符全替换", "__" not in html.replace("__SEC__", "") or not any(
    p in html for p in ("__KEY__", "__DATA__", "__WGS__", "__SECURITY__")))

# --- 4. Config 脱敏 ---
pub = cfg.public_dict()
check("Config:安全密钥脱敏", pub.get("amap_security") == "******")

# --- 5. 截图留档 ---
shot = tmp / "amap_panel.png"
panel.grab().save(str(shot))
check("截图保存", shot.exists())

ok = all(c for _, c in results)
print(f"\nTrackMapPanel 自检: {'全部通过' if ok else '存在失败'}（WebEngine 可用: {_HAS_WEBENGINE}）")
sys.exit(0 if ok else 1)
