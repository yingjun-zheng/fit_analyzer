"""统计分析：按公里分桶、速度/心率/踏频区间、海拔/温度序列、轨迹抽稀。"""
import math


def _weighted_zone_times(records, value_key, boundaries):
    """按记录的时间权重统计各区间秒数。records 需按 t 升序。boundaries 为区间上边界列表。"""
    zones = [0.0] * (len(boundaries) + 1)
    for i in range(len(records)):
        v = records[i].get(value_key)
        if v is None:
            continue
        dt = 1.0
        if i + 1 < len(records):
            nxt = records[i + 1].get("t")
            cur = records[i].get("t")
            if nxt is not None and cur is not None:
                dt = max(0.0, min(nxt - cur, 30.0))
            if dt == 0:
                dt = 1.0
        idx = 0
        for b in boundaries:
            if v >= b:
                idx += 1
            else:
                break
        zones[idx] += dt
    total = sum(zones)
    return [
        {"zone": i + 1, "seconds": round(z, 1), "pct": round(z / total * 100, 1) if total > 0 else 0}
        for i, z in enumerate(zones)
    ]


def zone_labels(boundaries, unit):
    labels = []
    for i in range(len(boundaries) + 1):
        lo = boundaries[i - 1] if i > 0 else None
        hi = boundaries[i] if i < len(boundaries) else None
        if lo is None:
            labels.append(f"< {hi}{unit}")
        elif hi is None:
            labels.append(f">= {lo}{unit}")
        else:
            labels.append(f"{lo}-{hi}{unit}")
    return labels


def speed_zones(records, boundaries_kmh):
    """速度区间（km/h），按时间权重。"""
    b = [float(x) for x in boundaries_kmh]
    zones = _weighted_zone_times(records, "speed_ms", [x / 3.6 for x in b])
    labels = zone_labels(b, "km/h")
    for z, lb in zip(zones, labels):
        z["label"] = lb
    return zones


def hr_zones(records, max_hr, pcts):
    """心率区间（最大心率百分比 5 区）。无心率数据返回 []. """
    if max_hr is None or max_hr <= 0:
        return []
    b = [max_hr * p for p in pcts]
    zones = _weighted_zone_times(records, "hr", b)
    labels = []
    for i in range(len(b) + 1):
        lo = round(b[i - 1]) if i > 0 else None
        hi = round(b[i]) if i < len(b) else None
        plo = int(pcts[i - 1] * 100) if i > 0 else 0
        phi = int(pcts[i] * 100) if i < len(pcts) else 100
        if lo is None:
            labels.append(f"Z{i + 1} < {hi}bpm(<{phi}%)")
        elif hi is None:
            labels.append(f"Z{i + 1} >= {lo}bpm({plo}%+)")
        else:
            labels.append(f"Z{i + 1} {lo}-{hi}bpm({plo}-{phi}%)")
    for z, lb in zip(zones, labels):
        z["label"] = lb
    return zones


def cadence_zones(records, boundaries_rpm):
    b = [float(x) for x in boundaries_rpm]
    zones = _weighted_zone_times(records, "cad", b)
    labels = zone_labels(b, "rpm")
    for z, lb in zip(zones, labels):
        z["label"] = lb
    return zones


def per_km(records):
    """按 1km 分桶：每公里时间/均速/最大速度/平均心率/平均踏频/平均海拔。"""
    buckets = []
    cur = None
    for r in records:
        dist = r.get("dist_m") or 0.0
        km = int(dist // 1000.0)
        if cur is None or cur["km"] != km:
            if cur:
                buckets.append(cur)
            cur = {
                "km": km, "t0": r.get("t"), "t1": r.get("t"),
                "dist0": dist, "dist1": dist,
                "speeds": [], "hrs": [], "cads": [], "alts": [],
            }
        cur["t1"] = r.get("t")
        cur["dist1"] = dist
        if r.get("speed_ms") is not None:
            cur["speeds"].append(r["speed_ms"])
        if r.get("hr") is not None:
            cur["hrs"].append(r["hr"])
        if r.get("cad") is not None:
            cur["cads"].append(r["cad"])
        if r.get("alt_m") is not None:
            cur["alts"].append(r["alt_m"])
    if cur:
        buckets.append(cur)

    out = []
    for b in buckets:
        dt = ((b["t1"] or 0) - (b["t0"] or 0))
        seg_dist = (b["dist1"] - b["dist0"]) / 1000.0
        avg_speed = (seg_dist / dt * 3600.0) if dt > 0 else None
        out.append({
            "km": b["km"],
            "time_s": round(dt, 1) if dt > 0 else 0,
            "avg_speed_kmh": round(avg_speed, 1) if avg_speed else None,
            "max_speed_kmh": round(max(b["speeds"]) * 3.6, 1) if b["speeds"] else None,
            "avg_hr": round(sum(b["hrs"]) / len(b["hrs"])) if b["hrs"] else None,
            "max_hr": round(max(b["hrs"])) if b["hrs"] else None,
            "avg_cad": round(sum(b["cads"]) / len(b["cads"])) if b["cads"] else None,
            "avg_alt": round(sum(b["alts"]) / len(b["alts"]), 1) if b["alts"] else None,
        })
    return out


def downsample_series(records, key, max_points=600):
    """时间序列抽稀（等间隔采样）为 [{t, v}]。"""
    pts = [(r.get("t"), r.get(key)) for r in records if r.get(key) is not None]
    if len(pts) <= max_points:
        return [{"t": t, "v": v} for t, v in pts]
    step = len(pts) / max_points
    out = []
    for i in range(max_points):
        idx = min(len(pts) - 1, int(i * step))
        out.append({"t": pts[idx][0], "v": pts[idx][1]})
    return out


def elevation_series(records, max_points=600):
    items = [{"t": (r.get("dist_m") or 0) / 1000.0, "v": r.get("alt_m")} for r in records if r.get("alt_m") is not None]
    return downsample_series(items, "v", max_points)


def temp_stats(records):
    temps = [r["temp"] for r in records if r.get("temp") is not None]
    if not temps:
        return {"has": False, "series": [], "min": None, "max": None, "avg": None}
    return {
        "has": True,
        "series": downsample_series(records, "temp", 400),
        "min": round(min(temps), 1),
        "max": round(max(temps), 1),
        "avg": round(sum(temps) / len(temps), 1),
    }


def track_points(records, max_points=2000):
    """轨迹抽稀：保留经纬度点（含海拔），均匀采样。"""
    pts = [(r["lat"], r["lon"], r.get("alt_m")) for r in records if r.get("lat") is not None and r.get("lon") is not None]
    if not pts:
        return []
    if len(pts) <= max_points:
        return pts
    step = (len(pts) - 1) / (max_points - 1)
    out = []
    for i in range(max_points):
        idx = int(round(i * step))
        out.append(pts[idx])
    # 保证首尾
    if out[-1] != pts[-1]:
        out[-1] = pts[-1]
    return out


def moving_time(records):
    """移动时间估算：速度 > 0.5 m/s 视为移动。"""
    mt = 0.0
    for i in range(len(records)):
        if (records[i].get("speed_ms") or 0) > 0.5:
            dt = 1.0
            if i + 1 < len(records):
                nxt, cur = records[i + 1].get("t"), records[i].get("t")
                if nxt is not None and cur is not None:
                    dt = max(0.0, nxt - cur)
            mt += dt
    return mt
