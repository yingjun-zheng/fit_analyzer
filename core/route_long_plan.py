"""长途/跨市骑行自动规划：分段接力 + 就近标定休息点。

思路（面向"按能力定休息点 + 跨市远程骑行"）：
1. 起点/终点地理编码 → 坐标
2. 若全程超长，用「分段接力」：拆成若干 20~40km 的段，段与段之间是中间城镇（天然休息点）
3. 每段之间调高德骑行规划（复用 route_plan）
4. 在每个休息点附近用 POI 搜索「补给/住宿」就近标定
5. 拼接成完整路书 + 休息点清单

依赖：高德 Web服务 key（地理编码/骑行规划/POI 搜索）。
"""
import math

from . import route_plan
from . import route as route_mod

# 高德 POI 类型码（大/中类），对应休息/补给偏好
REST_TYPE_CODES = {
    "便利店": "060700",
    "超市": "060100",
    "餐馆": "050000",
    "加油站": "010100",
    "住宿": "100000",
    "药店": "090300",
}
_DEFAULT_REST = "便利店"


def poi_search(key, location, rest_type="便利店", radius=3000, limit=5):
    """高德周边 POI 搜索，返回 [{name, type, distance_m, location:(lon,lat)}, ...]。

    location: (lon, lat)。rest_type: REST_TYPE_CODES 的键之一。
    """
    import urllib.parse
    from . import http_utils
    types = REST_TYPE_CODES.get(rest_type, REST_TYPE_CODES[_DEFAULT_REST])
    params = urllib.parse.urlencode({
        "key": key,
        "location": f"{location[0]},{location[1]}",
        "types": types,
        "radius": str(radius),
        "sortrule": "distance",
        "offset": str(limit),
        "page": "1",
    })
    url = f"https://restapi.amap.com/v3/place/around?{params}"
    status, obj = http_utils.http_json(url, timeout=15)
    if status != 200 or not isinstance(obj, dict) or obj.get("status") != "1":
        return []
    out = []
    for p in obj.get("pois") or []:
        loc = p.get("location", "")
        if "," not in loc:
            continue
        lon, lat = loc.split(",", 1)
        out.append({
            "name": p.get("name", ""),
            "type": p.get("type", ""),
            "distance_m": p.get("distance"),
            "location": (float(lon), float(lat)),
        })
    return out


def _haversine_km(lon1, lat1, lon2, lat2):
    """两点球面距离（km）。"""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def plan_long_route(key, origin, dest, segment_km=30, rest_type="便利店",
                    name="规划路线", enrich=False, progress_cb=None):
    """分段接力规划长途路线，标定休息点。

    origin/dest: 地名或 (lon,lat)。
    segment_km: 单段最大里程（骑手体能阈值）。
    rest_type: 休息点 POI 类型。
    progress_cb: 可选回调 (step, total, msg)，用于 GUI 进度提示。

    返回 dict：
      {route, segments:[{from,to,km}], rest_points:[{name,type,distance_m,location,at_km}]}
    失败返回 None 或抛 ValueError。
    """
    # 1) 解析起终点坐标
    o = route_plan.geocode(origin, key) if isinstance(origin, str) else origin
    d = route_plan.geocode(dest, key) if isinstance(dest, str) else dest
    if o is None:
        raise ValueError(f"无法解析起点「{origin}」")
    if d is None:
        raise ValueError(f"无法解析终点「{dest}」")

    total_km = _haversine_km(o[0], o[1], d[0], d[1])
    seg_km = max(5, int(segment_km or 30))

    # 2) 决定途经点：若全程超长，在中间按 segment_km 等分插入中间点
    #    中间点用「大圆插值」近似（真实路网会由高德逐段规划修正）
    n_seg = max(1, int(math.ceil(total_km / seg_km)))
    if n_seg > 8:
        n_seg = 8  # 限制最多 8 段，避免逐段规划次数过多、超时

    waypoints = [o]
    if n_seg > 1:
        for i in range(1, n_seg):
            t = i / n_seg
            mid_lon = o[0] + (d[0] - o[0]) * t
            mid_lat = o[1] + (d[1] - o[1]) * t
            waypoints.append((mid_lon, mid_lat))
    waypoints.append(d)

    if progress_cb:
        progress_cb(0, n_seg, f"全程约 {total_km:.0f} km，分 {n_seg} 段规划")

    # 3) 逐段调高德骑行规划，拼接
    all_coords = []
    segments = []
    total_d_m = 0
    total_dur = 0
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        data = route_plan.bicycling_plan(a, b, key)
        if not data:
            # 该段失败，跳过并继续（长途规划容错）
            if progress_cb:
                progress_cb(i + 1, n_seg, f"第 {i + 1} 段规划失败，跳过")
            continue
        paths = data.get("paths") or []
        if not paths:
            continue
        path = paths[0]
        coords = []
        for step in path.get("steps") or []:
            coords.extend(route_plan._polyline_to_points(step.get("polyline")))
        if i > 0 and all_coords and coords and coords[0] == all_coords[-1]:
            coords = coords[1:]
        all_coords.extend(coords)
        total_d_m += path.get("distance") or 0
        total_dur += path.get("duration") or 0
        segments.append({
            "from": waypoints[i],
            "to": waypoints[i + 1],
            "distance_m": path.get("distance"),
            "duration_s": path.get("duration"),
        })
        if progress_cb:
            progress_cb(i + 1, n_seg, f"第 {i + 1}/{n_seg} 段完成")

    if len(all_coords) < 2:
        raise ValueError("规划失败：未获得有效路线坐标")

    r = route_plan._coords_to_route(all_coords, name=name, plan_meta={
        "plan_distance_m": total_d_m,
        "plan_duration_s": total_dur,
    })

    # 4) 就近标定休息点（在每个分段接点附近搜 POI）
    rest_points = []
    if n_seg > 1:
        for i in range(1, n_seg):
            wp = waypoints[i]
            pois = poi_search(key, wp, rest_type=rest_type, radius=3000, limit=1)
            if pois:
                p = pois[0]
                at_km = round(total_km * i / n_seg, 1)
                rest_points.append({
                    "name": p["name"],
                    "type": p["type"],
                    "distance_m": p["distance_m"],
                    "location": p["location"],
                    "at_km": at_km,
                })

    if enrich and not any(p.get("ele") is not None for p in r["points"]):
        route_mod.enrich_elevation_from_api(r)
        route_mod._compute_elevation(r)
        route_mod._compute_climbs(r)

    return {
        "route": r,
        "segments": segments,
        "rest_points": rest_points,
        "total_km_est": round(total_km, 1),
    }
