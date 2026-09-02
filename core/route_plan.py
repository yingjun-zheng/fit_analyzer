"""路径规划：接高德 Web服务 API 骑行路线规划，生成可分析的路书。

使用高德「Web服务」类型的 key（不是 Web端 JS API key）。
- 骑行路径规划：https://restapi.amap.com/v4/direction/bicycling
- 地理编码（地名→坐标）：https://restapi.amap.com/v3/geocode/geo

产出的 route dict 复用 core.route 的海拔剖面 + 爬坡分级 + 导出能力。

坐标系说明：高德接口返回的是 GCJ-02（火星坐标），而软件内部（FIT/GPX）
全链路使用 WGS-84。因此规划出的坐标必须从 GCJ-02 转回 WGS-84 再进入
route，否则导出的路书会在地图上漂移约 300~500 米。
"""
import math

from . import route as route_mod

GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
BICYCLING_URL = "https://restapi.amap.com/v4/direction/bicycling"

# WGS-84 椭球参数
_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lng, lat):
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _gcj02_to_wgs84(lng, lat):
    """GCJ-02（火星坐标）→ WGS-84，迭代逼近法。国内精度 ~2 米。"""
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lng - dlng, lat - dlat


def gcj02_to_wgs84(lng, lat):
    """公开接口：GCJ-02 → WGS-84。"""
    return _gcj02_to_wgs84(lng, lat)


def geocode(address, key):
    """地名 → (lon, lat)。失败返回 None。"""
    import urllib.parse
    from . import http_utils
    city_fallback = ""  # 让高德全国范围搜
    params = urllib.parse.urlencode({"address": address, "key": key})
    url = f"{GEOCODE_URL}?{params}"
    status, obj = http_utils.http_json(url, timeout=15)
    if status == 200 and isinstance(obj, dict) and obj.get("status") == "1":
        geos = obj.get("geocodes") or []
        if geos:
            loc = geos[0].get("location", "")
            if loc and "," in loc:
                lon, lat = loc.split(",", 1)
                return float(lon), float(lat)
    return None


def bicycling_plan(origin, destination, key):
    """骑行路径规划，返回原始 data dict（含 paths）；失败返回 None。

    origin/destination: (lon, lat) 或 "lon,lat" 字符串。
    """
    from . import http_utils

    def _fmt(c):
        if isinstance(c, (tuple, list)):
            return f"{c[0]},{c[1]}"
        return str(c)

    url = (f"{BICYCLING_URL}?origin={_fmt(origin)}"
           f"&destination={_fmt(destination)}&key={key}")
    status, obj = http_utils.http_json(url, timeout=20)
    if status == 200 and isinstance(obj, dict) and obj.get("errcode") == 0:
        return obj.get("data")
    return None


def _polyline_to_points(polyline):
    """高德 polyline 字符串 "lon,lat;lon,lat;..." → [(lon, lat), ...]。"""
    pts = []
    if not polyline:
        return pts
    for seg in polyline.split(";"):
        seg = seg.strip()
        if not seg or "," not in seg:
            continue
        lon, lat = seg.split(",", 1)
        try:
            pts.append((float(lon), float(lat)))
        except ValueError:
            continue
    return pts


def _coords_to_route(coords, name="规划路线", plan_meta=None):
    """把坐标列表（lon,lat）转成 route dict（复用 route 的海拔/爬坡计算）。

    注意：coords 是高德返回的 GCJ-02 坐标，此处统一转成 WGS-84 存储，
    与软件内部 FIT/GPX 轨迹坐标系一致，避免导出路书漂移。
    """
    if len(coords) < 2:
        return None
    points = []
    gcj_points = []  # 保留原始 GCJ-02，供地图渲染（高德地图是 GCJ-02 坐标系）
    prev = None
    dist = 0.0
    for lon, lat in coords:
        w_lng, w_lat = _gcj02_to_wgs84(lon, lat)
        if prev is not None:
            dist += route_mod._haversine(prev["lat"], prev["lon"], w_lat, w_lng)
        else:
            dist = 0.0
        points.append({"lat": w_lat, "lon": w_lng, "ele": None, "dist_km": dist / 1000.0})
        gcj_points.append([lon, lat])
        prev = {"lat": w_lat, "lon": w_lng}

    r = {
        "name": name,
        "points": points,
        "total_distance_km": round(points[-1]["dist_km"], 2),
        "gcj_points": gcj_points,  # 原始 GCJ-02 坐标（地图渲染用）
    }
    if plan_meta:
        r.update(plan_meta)
    route_mod._compute_elevation(r)
    route_mod._compute_climbs(r)
    return r


def plan_to_route(data, name="规划路线"):
    """把高德骑行规划返回的 data 转成 route dict（含海拔剖面/爬坡）。

    data: bicycling_plan 返回的 data dict（含 paths）。
    返回 route dict；无有效路径时返回 None。
    """
    if not data:
        return None
    paths = data.get("paths") or []
    if not paths:
        return None

    # 取第一条路径，拼接所有 step 的 polyline 得到完整折线
    path = paths[0]
    coords = []
    for step in path.get("steps") or []:
        coords.extend(_polyline_to_points(step.get("polyline")))

    return _coords_to_route(coords, name=name, plan_meta={
        "plan_distance_m": path.get("distance"),
        "plan_duration_s": path.get("duration"),
    })


def plan_route_with_waypoints(key, points, name="规划路线", enrich=False):
    """途经点串联规划：逐段调高德骑行规划，拼接成完整路线。

    points: 有序坐标列表 [(lon,lat), (lon,lat), ...]，至少 2 个点，依次为
            起点 → 途经点1 → 途经点2 → ... → 终点。
    每相邻两点之间由高德规划合理骑行路径（非直线），整条路线由用户控制，
    避免起点终点间的"火箭路径"。
    """
    if len(points) < 2:
        raise ValueError("至少需要 2 个点（起点和终点）")

    all_coords = []
    total_dist_m = 0
    total_dur_s = 0
    for i in range(len(points) - 1):
        o = points[i]
        d = points[i + 1]
        data = bicycling_plan(o, d, key)
        if not data:
            raise ValueError(f"第 {i + 1} 段规划失败（{o} → {d}）")
        paths = data.get("paths") or []
        if not paths:
            raise ValueError(f"第 {i + 1} 段无有效路径（{o} → {d}）")
        path = paths[0]
        seg = []
        for step in path.get("steps") or []:
            seg.extend(_polyline_to_points(step.get("polyline")))
        if i > 0 and all_coords and seg:
            # 避免相邻段的首点重复
            if seg[0] == all_coords[-1]:
                seg = seg[1:]
        all_coords.extend(seg)
        total_dist_m += path.get("distance") or 0
        total_dur_s += path.get("duration") or 0

    r = _coords_to_route(all_coords, name=name, plan_meta={
        "plan_distance_m": total_dist_m,
        "plan_duration_s": total_dur_s,
    })
    if r is None:
        raise ValueError("规划失败：拼接后无有效坐标")
    if enrich and not any(p.get("ele") is not None for p in r["points"]):
        route_mod.enrich_elevation_from_api(r)
        route_mod._compute_elevation(r)
        route_mod._compute_climbs(r)
    return r


def plan_route(key, origin, destination, name=None, enrich=False):
    """一站式：坐标（或地名）规划 → 生成 route。

    origin/destination: 可以是 (lon,lat) 坐标，或地名字符串（自动地理编码）。
    enrich: 缺海拔时是否调用 Open-Meteo 补全（默认 False）。
    """
    o = origin
    d = destination
    if isinstance(origin, str) and "," not in origin:
        o = geocode(origin, key)
        if o is None:
            raise ValueError(f"无法解析起点「{origin}」")
    if isinstance(destination, str) and "," not in destination:
        d = geocode(destination, key)
        if d is None:
            raise ValueError(f"无法解析终点「{destination}」")

    return plan_route_with_waypoints(key, [o, d], name=name or "规划路线", enrich=enrich)
