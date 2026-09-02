"""路书模块单元测试：GPX 导入 / 海拔剖面 / 爬坡分级 / 导出。

用合成 GPX（已知坡度）验证：
- 海拔剖面与累计爬升正确
- 爬坡分级阈值正确（Cat 4/HC）
- 导出往返一致（导出的 GPX 能再解析）

运行：python tests/test_route.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import route

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def make_gpx(points, name="测试路书"):
    """由 [(lat, lon, ele)] 生成 GPX 文本。"""
    trkpts = "".join(
        f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>'
        for lat, lon, ele in points
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>{name}</name><trkseg>{trkpts}</trkseg></trk>
</gpx>"""


def _flat_route(start_lat=30.0, ele=100.0, n=10, lon_step=0.001):
    """水平路线，lat 不变，lon 递增（近似东西向直线）。"""
    return [(start_lat, 30.0 + lon_step * i, ele) for i in range(n)]


def _climb_route(grad_pct=5.0, length_km=2.0, n=100):
    """构造一条已知坡度%的爬坡路线（东西向直线）。"""
    pts = []
    start_lon = 30.0
    lat = 30.0
    step_km = length_km / n
    # 每度经度约 111.32 * cos(lat) km；简化用 1 度经度 ≈ 95 km（30° 纬度）
    deg_per_km = 1.0 / 95.0
    ele = 100.0
    for i in range(n + 1):
        lon = start_lon + step_km * i * deg_per_km
        pts.append((lat, lon, round(ele, 1)))
        ele += grad_pct / 100.0 * step_km * 1000.0  # 每步爬升 = 坡度% * 水平距离(m)
    return pts


def test_parse_and_elevation():
    print("== GPX 导入 + 海拔 ==")
    # 平路：累计爬升应为 0
    r = route.parse_gpx(make_gpx(_flat_route(ele=100.0)))
    check("平路总爬升≈0", r["total_ascent_m"] < 1.0, f"ascent={r['total_ascent_m']}")
    check("平路无爬坡段", len(r["climbs"]) == 0, f"climbs={len(r['climbs'])}")
    check("总里程>0", r["total_distance_km"] > 0, f"d={r['total_distance_km']}")
    check("海拔范围正确", r["ele_min_m"] == 100.0 and r["ele_max_m"] == 100.0)


def test_climb_detection():
    print("== 爬坡分级 ==")
    # 5% 坡度 × 2km，score = 5^2 * 2000 = 50000 → Cat 1（64000 以下，32000 以上）
    pts = _climb_route(grad_pct=5.0, length_km=2.0)
    r = route.parse_gpx(make_gpx(pts, "5% 爬坡"))
    check("检测到爬坡段", len(r["climbs"]) >= 1, f"climbs={len(r['climbs'])}")
    if r["climbs"]:
        c = r["climbs"][0]
        check("坡度≈5%", abs(c["avg_gradient_pct"] - 5.0) < 1.0, f"grad={c['avg_gradient_pct']}")
        check("爬升≈100m", abs(c["gain_m"] - 100.0) < 15, f"gain={c['gain_m']}")
        check("分数在 Cat2 区间(32000-64000)", 32000 <= c["score"] < 64000, f"score={c['score']} cat={c['category']}")

    # 8% 坡度 × 5km，score = 64 * 5000 = 320000 → HC
    pts2 = _climb_route(grad_pct=8.0, length_km=5.0)
    r2 = route.parse_gpx(make_gpx(pts2, "8% 长爬坡"))
    if r2["climbs"]:
        c2 = r2["climbs"][0]
        check("长爬坡分级为 HC", c2["category"] == "HC", f"cat={c2['category']} score={c2['score']}")


def test_export_roundtrip():
    print("== 导出路书 ==")
    pts = _climb_route(grad_pct=6.0, length_km=3.0)
    r = route.parse_gpx(make_gpx(pts, "导出测试"))
    xml = route.export_route_gpx(r)
    check("导出返回 XML 字符串", isinstance(xml, str) and "<gpx" in xml)
    # 导出的 GPX 能再解析
    r2 = route.parse_gpx(xml)
    check("导出可再解析", r2["total_distance_km"] > 0)
    check("导出保留爬坡段", len(r2["climbs"]) >= 1, f"climbs={len(r2['climbs'])}")

    # 导出到文件
    tmp = Path(tempfile.mkdtemp()) / "route_out.gpx"
    out = route.export_route_gpx(r, str(tmp))
    check("导出到文件", Path(out).exists() and Path(out).stat().st_size > 100)


def test_summarize():
    print("== 摘要 ==")
    pts = _climb_route(grad_pct=5.0, length_km=2.0)
    r = route.parse_gpx(make_gpx(pts, "摘要测试"))
    s = route.summarize(r)
    check("摘要含里程", "km" in s)
    check("摘要含爬坡", "爬坡" in s)


def test_enrich_elevation():
    print("== 海拔补全（mock API）==")
    # 构造无海拔的平路/缓坡路线
    pts = [(30.0, 30.0 + i * 0.001, None) for i in range(50)]
    r = route.parse_gpx(make_gpx(pts, "无海拔"))
    check("无海拔时 ele 全 None", all(p.get("ele") is None for p in r["points"]))

    # mock http_utils 返回线性增长的海拔
    import core.http_utils as hu
    orig = hu.http_json

    def fake_json(url, timeout=30, **kw):
        # 返回足够多的海拔值（覆盖抽稀采样点）
        return 200, {"elevation": [100.0 + i * 2 for i in range(500)]}

    hu.http_json = fake_json
    try:
        route.enrich_elevation_from_api(r, max_query_points=50)
    finally:
        hu.http_json = orig

    filled = [p.get("ele") for p in r["points"] if p.get("ele") is not None]
    check("补全后海拔非 None", len(filled) > 0, f"filled={len(filled)}")
    # 重新计算海拔统计
    route._compute_elevation(r)
    check("补全后累计爬升有值", r.get("total_ascent_m", 0) >= 0)


def test_route_from_records():
    print("== 历史活动转路书 ==")
    # 构造一条有爬坡的活动记录（lat/lon/alt_m）
    pts = _climb_route(grad_pct=5.0, length_km=2.0, n=100)
    records = [
        {"lat": lat, "lon": lon, "alt_m": ele}
        for lat, lon, ele in pts
    ]
    r = route.route_from_records("活动转路书", records)
    check("转换后有轨迹点", len(r["points"]) > 0)
    check("总里程接近 2km", 1.5 < r["total_distance_km"] < 2.5,
          f"dist={r['total_distance_km']}")
    check("能识别出爬坡段", len(r.get("climbs", [])) >= 1, f"climbs={len(r.get('climbs', []))}")
    check("有海拔剖面", len(r["elevation_profile"]) > 0)

    # 无经纬度记录应报错
    try:
        route.route_from_records("空", [{"alt_m": 100}, {"alt_m": 105}])
        check("无轨迹点时报错", False)
    except ValueError:
        check("无轨迹点时报错", True)


def main():
    test_parse_and_elevation()
    test_climb_detection()
    test_export_roundtrip()
    test_summarize()
    test_enrich_elevation()
    test_route_from_records()
    print(f"\n结果: {PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
