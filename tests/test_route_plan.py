"""路径规划模块单元测试：plan_to_route 折线解析 / 地理编码 / 规划调用（mock HTTP）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import route_plan

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


# 模拟高德 bikycling 返回的 data（含 polyline）
MOCK_DATA = {
    "paths": [{
        "distance": 1000,
        "duration": 600,
        "steps": [
            {"polyline": "116.0,39.0;116.001,39.0;116.002,39.0"},
            {"polyline": "116.002,39.0;116.003,39.001"},
        ],
    }]
}


def test_polyline_to_points():
    print("== polyline 解析 ==")
    pts = route_plan._polyline_to_points("116.0,39.0;116.001,39.001;bad;116.002,39.002")
    check("解析 3 个有效点", len(pts) == 3, f"got {len(pts)}")
    check("坐标顺序 lon,lat", pts[0] == (116.0, 39.0))


def test_plan_to_route():
    print("== plan_to_route ==")
    r = route_plan.plan_to_route(MOCK_DATA, name="测试")
    check("生成 route", r is not None)
    if r:
        check("有轨迹点", len(r["points"]) >= 2)
        check("里程为正", r["total_distance_km"] > 0, str(r["total_distance_km"]))
        check("保留规划距离", r.get("plan_distance_m") == 1000)
        check("有海拔字段(可能为None)", "total_ascent_m" in r)
        check("有爬坡字段", "climbs" in r)
    # 空 data
    check("空 data 返回 None", route_plan.plan_to_route(None) is None)
    check("空 paths 返回 None", route_plan.plan_to_route({"paths": []}) is None)


def test_geocode(mock_http_get):
    print("== 地理编码 ==")
    c = route_plan.geocode("北京天安门", "fakekey")
    check("返回坐标", c is not None and len(c) == 2, str(c))


def test_bicycling_plan(mock_http_get):
    print("== 骑行规划 ==")
    data = route_plan.bicycling_plan((116.0, 39.0), (116.01, 39.01), "fakekey")
    check("返回 data", data is not None and "paths" in data)


def test_plan_route_with_waypoints():
    print("== 途经点串联 ==")
    # mock：每段都返回相同 MOCK_DATA
    import core.http_utils as hu
    orig = hu.http_json

    def fake(url, timeout=30, **kw):
        if "direction" in url or "bicycling" in url:
            return 200, {"errcode": 0, "data": MOCK_DATA}
        return 200, {}

    hu.http_json = fake
    try:
        pts = [(116.0, 39.0), (116.01, 39.01), (116.02, 39.02)]
        r = route_plan.plan_route_with_waypoints("fakekey", pts, name="三段")
        check("串联生成 route", r is not None)
        if r:
            check("有轨迹点", len(r["points"]) >= 2)
            check("里程为正", r["total_distance_km"] > 0)
            # 3 个点 = 2 段规划，距离应累加（mock 每段 1000m）
            check("距离累加", r.get("plan_distance_m") == 2000, str(r.get("plan_distance_m")))
        # 少于 2 点应报错
        try:
            route_plan.plan_route_with_waypoints("k", [(116.0, 39.0)])
            check("少于2点报错", False)
        except ValueError:
            check("少于2点报错", True)
    finally:
        hu.http_json = orig


def main():
    # mock http_utils.http_json
    import core.http_utils as hu
    orig = hu.http_json

    def fake_json(url, timeout=30, **kw):
        if "geocode" in url:
            return 200, {"status": "1", "geocodes": [{"location": "116.397,39.909"}]}
        if "bicycling" in url or "direction" in url:
            return 200, {"errcode": 0, "data": MOCK_DATA}
        return 200, {}

    hu.http_json = fake_json
    try:
        test_polyline_to_points()
        test_plan_to_route()
        test_geocode(fake_json)
        test_bicycling_plan(fake_json)
        test_plan_route_with_waypoints()
    finally:
        hu.http_json = orig

    print(f"\n结果: {PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
