"""路书分析：GPX 导入 + 海拔剖面 + 爬坡分级 + 路书导出。

不依赖 gpxpy，用标准库 xml.etree 解析 GPX 1.1，保持轻量、离线可测。

核心数据模型（route dict）：
{
    "name": str,
    "points": [{"lat", "lon", "ele", "dist_km"}],   # 按距离排序的轨迹点
    "total_distance_km": float,
    "total_ascent_m": float,
    "total_descent_m": float,
    "ele_min_m": float, "ele_max_m": float,
    "elevation_profile": [{"dist_km", "ele_m"}],     # 抽稀后的海拔剖面
    "climbs": [                                        # 爬坡段
        {"start_km", "end_km", "length_km", "gain_m",
         "avg_gradient_pct", "score", "category", "name"}
    ],
}

爬坡分级参考 Strava 的评分体系：score = 坡度(%)² × 长度(m)
    分类阈值：Cat 4 >= 8000，Cat 3 >= 16000，Cat 2 >= 32000，
              Cat 1 >= 64000，HC >= 80000。
"""
import math
import xml.etree.ElementTree as ET

NS_GPX = "http://www.topografix.com/GPX/1/1"

# 注册默认命名空间，避免 toprettyxml 序列化时加 ns0: 前缀
ET.register_namespace("", NS_GPX)

# 爬坡分级阈值（grade_pct^2 * length_m）
CLIMB_CATEGORIES = [
    (80000, "HC", "超级爬坡"),
    (64000, "Cat 1", "一级爬坡"),
    (32000, "Cat 2", "二级爬坡"),
    (16000, "Cat 3", "三级爬坡"),
    (8000, "Cat 4", "四级爬坡"),
]

# 判定爬坡的最小坡度（%）与最小爬升（m）
_MIN_GRADIENT_PCT = 3.0
_MIN_CLIMB_GAIN_M = 15.0


def _haversine(lat1, lon1, lat2, lon2):
    """两点球面距离（米）。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _ns(tag):
    return f"{{{NS_GPX}}}{tag}"


# ---------------- 导入 ----------------

def parse_gpx(source, enrich_elevation=False):
    """解析 GPX 文件，返回 route dict。

    source: 文件路径（str/Path）或 GPX 文本内容。
    enrich_elevation: GPX 缺海拔时，是否联网（Open-Meteo）补全海拔。默认 False（离线）。
    """
    if isinstance(source, (str,)) and ("<" in source and "gpx" in source.lower()):
        root = ET.fromstring(source)
    else:
        root = ET.parse(str(source)).getroot()

    # 路线名
    name = ""
    name_el = root.find(f".//{_ns('trk')}/{_ns('name')}")
    if name_el is None:
        name_el = root.find(f".//{_ns('rte')}/{_ns('name')}")
    if name_el is not None and name_el.text:
        name = name_el.text.strip()

    # 收集轨迹点：优先 <trkpt>，回退 <rtept>
    raw_pts = []
    for pt in root.iter(_ns("trkpt")):
        raw_pts.append(pt)
    if not raw_pts:
        for pt in root.iter(_ns("rtept")):
            raw_pts.append(pt)

    points = []
    prev = None
    dist = 0.0
    for pt in raw_pts:
        try:
            lat = float(pt.get("lat"))
            lon = float(pt.get("lon"))
        except (TypeError, ValueError):
            continue
        ele_el = pt.find(_ns("ele"))
        ele = None
        if ele_el is not None and ele_el.text:
            try:
                ele = float(ele_el.text)
            except ValueError:
                ele = None
        if prev is not None:
            dist += _haversine(prev["lat"], prev["lon"], lat, lon)
        else:
            dist = 0.0
        points.append({"lat": lat, "lon": lon, "ele": ele, "dist_km": dist / 1000.0})
        prev = {"lat": lat, "lon": lon}

    if not points:
        raise ValueError("GPX 文件里没有有效的轨迹点（trkpt/rtept）")

    route = {
        "name": name or "未命名路书",
        "points": points,
        "total_distance_km": round(points[-1]["dist_km"], 2),
    }

    # 缺海拔且要求联网补全
    if enrich_elevation and not any(p.get("ele") is not None for p in points):
        enrich_elevation_from_api(route)

    _compute_elevation(route)
    _compute_climbs(route)
    return route


# ---------------- 海拔补全（联网，可选） ----------------

def enrich_elevation_from_api(route, max_query_points=200):
    """用 Open-Meteo Elevation API 补全缺海拔的轨迹。

    原理：抽稀到 ≤max_query_points 个点，分批（每批 100）查询海拔，
    再按距离线性插值回填到所有轨迹点。离线/失败时静默降级（海拔保持 None）。

    route: parse_gpx 返回的 dict（原地修改 points 的 ele）。
    """
    from . import http_utils

    points = route["points"]
    if not points:
        return

    # 抽稀到 ≤max_query_points 个采样点（均匀）
    n = len(points)
    idxs = list(range(0, n, max(1, n // max_query_points)))[:max_query_points]
    idxs[-1] = n - 1  # 保证含最后一个点

    # 分批查询（每批 100）
    ele_by_idx = {}
    for b in range(0, len(idxs), 100):
        batch = idxs[b:b + 100]
        lats = ",".join(f"{points[i]['lat']:.6f}" for i in batch)
        lons = ",".join(f"{points[i]['lon']:.6f}" for i in batch)
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"
        try:
            status, obj = http_utils.http_json(url, timeout=20)
            if status == 200 and isinstance(obj, dict) and "elevation" in obj:
                for i, ele in zip(batch, obj["elevation"]):
                    ele_by_idx[i] = ele
        except Exception:
            pass

    if not ele_by_idx:
        return

    # 线性插值回填
    keys = sorted(ele_by_idx.keys())
    for i in range(n):
        if points[i].get("ele") is not None:
            continue
        if i in ele_by_idx:
            points[i]["ele"] = round(ele_by_idx[i], 1)
            continue
        # 找左右两个采样点
        lo = hi = None
        for k in keys:
            if k <= i:
                lo = k
            if k >= i and hi is None:
                hi = k
        if lo is None or hi is None:
            continue
        d_lo = points[i]["dist_km"] - points[lo]["dist_km"]
        d_hi = points[hi]["dist_km"] - points[lo]["dist_km"]
        if d_hi <= 0:
            continue
        t = d_lo / d_hi
        val = ele_by_idx[lo] + (ele_by_idx[hi] - ele_by_idx[lo]) * t
        points[i]["ele"] = round(val, 1)


# ---------------- 海拔剖面 ----------------

def _compute_elevation(route):
    """填充累计爬升/下降、最高最低点、海拔剖面。"""
    points = route["points"]
    ascent = 0.0
    descent = 0.0
    prev_ele = None
    eles = [p["ele"] for p in points if p.get("ele") is not None]

    for p in points:
        ele = p.get("ele")
        if ele is None:
            continue
        if prev_ele is not None:
            d = ele - prev_ele
            if d > 0:
                ascent += d
            elif d < 0:
                descent -= d
        prev_ele = ele

    route["total_ascent_m"] = round(ascent, 1)
    route["total_descent_m"] = round(descent, 1)
    route["ele_min_m"] = round(min(eles), 1) if eles else None
    route["ele_max_m"] = round(max(eles), 1) if eles else None

    # 海拔剖面（沿距离，抽稀到 ≤600 点）
    raw = [{"dist_km": p["dist_km"], "ele_m": p["ele"]} for p in points if p.get("ele") is not None]
    if len(raw) > 600:
        step = (len(raw) - 1) / 599
        prof = [raw[int(round(i * step))] for i in range(600)]
        prof[-1] = raw[-1]
    else:
        prof = raw
    route["elevation_profile"] = prof


# ---------------- 爬坡分级 ----------------

def _compute_climbs(route):
    """识别连续爬坡段并按坡级分类。"""
    points = route["points"]
    climbs = []
    # 用滑动平均平滑坡度，减少单点噪声
    cur = None  # 当前爬坡段累计状态
    seg = []    # 当前爬坡段的点

    # 先算相邻点坡度（%），基于 3 点滑动窗口平滑
    grads = [0.0] * len(points)
    for i in range(1, len(points)):
        p0, p1 = points[i - 1], points[i]
        if p0.get("ele") is None or p1.get("ele") is None:
            grads[i] = 0.0
            continue
        dh = p1["ele"] - p0["ele"]
        dd = (p1["dist_km"] - p0["dist_km"]) * 1000.0  # 米
        if dd > 0.5:
            grads[i] = dh / dd * 100.0

    # 识别连续爬坡段
    seg_start = None
    seg_points = []
    for i in range(len(points)):
        g = grads[i] if i > 0 else 0.0
        if g >= _MIN_GRADIENT_PCT and points[i].get("ele") is not None:
            if seg_start is None:
                seg_start = points[i - 1] if i > 0 else points[i]
                seg_points = [seg_start, points[i]]
            else:
                seg_points.append(points[i])
        else:
            if seg_start is not None:
                _finalize_climb(climbs, seg_points)
                seg_start = None
                seg_points = []
    if seg_start is not None:
        _finalize_climb(climbs, seg_points)

    route["climbs"] = climbs


def _finalize_climb(climbs, seg_points):
    """把一个连续爬坡段的数据整理成 climb dict，达标才加入。"""
    start = seg_points[0]
    end = seg_points[-1]
    start_ele = start.get("ele")
    end_ele = end.get("ele")
    if start_ele is None or end_ele is None:
        return
    gain = end_ele - start_ele
    length_km = end["dist_km"] - start["dist_km"]
    length_m = length_km * 1000.0
    if gain < _MIN_CLIMB_GAIN_M or length_m < 100:
        return
    grad_pct = gain / length_m * 100.0
    score = grad_pct * grad_pct * length_m
    category = None
    cat_name = ""
    for thresh, cat, cn in CLIMB_CATEGORIES:
        if score >= thresh:
            category = cat
            cat_name = cn
            break
    climbs.append({
        "start_km": round(start["dist_km"], 2),
        "end_km": round(end["dist_km"], 2),
        "length_km": round(length_km, 2),
        "gain_m": round(gain, 1),
        "avg_gradient_pct": round(grad_pct, 1),
        "score": round(score, 0),
        "category": category,
        "category_name": cat_name,
    })


# ---------------- 导出 ----------------

def export_route_gpx(route, output_path=None):
    """把路书（含爬坡段标注）导出为 GPX 1.1 文件。

    output_path 为空时返回 XML 字符串，否则写入文件并返回路径。
    """
    root = ET.Element(_ns("gpx"), attrib={
        "version": "1.1",
        "creator": "FitAnalyzer/1.0",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": f"{NS_GPX} http://www.topografix.com/GPX/1/1/gpx.xsd",
    })

    # 元数据（含路书摘要）
    metadata = ET.SubElement(root, _ns("metadata"))
    name_el = ET.SubElement(metadata, _ns("name"))
    name_el.text = route.get("name", "未命名路书")
    desc_el = ET.SubElement(metadata, _ns("desc"))
    desc_el.text = (
        f"距离 {route.get('total_distance_km', 0)}km，"
        f"爬升 {route.get('total_ascent_m', 0)}m，"
        f"爬坡 {len(route.get('climbs', []))} 段"
    )

    # 单个 trkseg，或按爬坡段分 seg（用 <type> 标注坡级）
    trk = ET.SubElement(root, _ns("trk"))
    trk_name = ET.SubElement(trk, _ns("name"))
    trk_name.text = route.get("name", "未命名路书")

    # 轨迹点全部放一个 trkseg（路书轨迹）
    trkseg = ET.SubElement(trk, _ns("trkseg"))
    for p in route["points"]:
        pt = ET.SubElement(trkseg, _ns("trkpt"), attrib={
            "lat": f"{p['lat']:.7f}",
            "lon": f"{p['lon']:.7f}",
        })
        if p.get("ele") is not None:
            ele = ET.SubElement(pt, _ns("ele"))
            ele.text = str(round(p["ele"], 1))

    # 爬坡段作为独立的 rte（route）标记，方便外部工具识别
    for i, c in enumerate(route.get("climbs", [])):
        rte = ET.SubElement(root, _ns("rte"))
        rte_name = ET.SubElement(rte, _ns("name"))
        rte_name.text = f"爬坡{i + 1} {c.get('category', '')} {c.get('category_name', '')}（{c['avg_gradient_pct']}%·{c['gain_m']}m）"

    # 格式化输出
    import xml.dom.minidom
    raw = ET.tostring(root, encoding="unicode")
    dom = xml.dom.minidom.parseString(raw)
    pretty = dom.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
    xml_str = "\n".join(line for line in pretty.splitlines() if line.strip())

    if output_path:
        from pathlib import Path
        Path(output_path).write_text(xml_str, encoding="utf-8")
        return str(output_path)
    return xml_str


def summarize(route):
    """返回路书的可读摘要（供 CLI 打印 / LLM 解读）。"""
    lines = [
        f"路书：{route['name']}",
        f"总里程：{route['total_distance_km']} km",
        f"累计爬升：{route['total_ascent_m']} m / 下降：{route['total_descent_m']} m",
        f"海拔范围：{route['ele_min_m']} ~ {route['ele_max_m']} m",
    ]
    climbs = route.get("climbs", [])
    if climbs:
        lines.append(f"爬坡段：{len(climbs)} 段")
        for i, c in enumerate(climbs, 1):
            cat = c.get("category") or "未分级"
            lines.append(
                f"  {i}. {cat} {c['category_name']}：{c['start_km']}~{c['end_km']}km，"
                f"长度 {c['length_km']}km，爬升 {c['gain_m']}m，坡度 {c['avg_gradient_pct']}%"
            )
    else:
        lines.append("无明显爬坡段（多为平路或缓坡）")
    return "\n".join(lines)


def route_from_records(name, records):
    """把数据库活动记录（含 lat/lon/alt_m）转成 route dict（供「历史活动转路书」）。

    records: db.get_records() 返回的 list[dict]，每项含 lat/lon，可选 alt_m。
    返回与 parse_gpx 相同结构的 route dict（已算海拔剖面与爬坡分级）。
    """
    points = []
    prev = None
    dist = 0.0
    for r in records:
        lat = r.get("lat")
        lon = r.get("lon")
        if lat is None or lon is None:
            continue
        ele = r.get("alt_m")
        if prev is not None:
            dist += _haversine(prev["lat"], prev["lon"], lat, lon)
        else:
            dist = 0.0
        points.append({"lat": lat, "lon": lon, "ele": ele, "dist_km": dist / 1000.0})
        prev = {"lat": lat, "lon": lon}

    if not points:
        raise ValueError("该活动没有可用于转路书的轨迹点（缺少经纬度）")

    route = {
        "name": name or "未命名路书",
        "points": points,
        "total_distance_km": round(points[-1]["dist_km"], 2),
    }
    _compute_elevation(route)
    _compute_climbs(route)
    return route
