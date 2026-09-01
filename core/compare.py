"""跨活动对比：同路线识别 + 两次骑行对比 + 周期进度趋势。

不依赖 LLM，纯本地计算，产出结构化对比数据，供 review_agent 交给 LLM 解读。
设计要点：
- 同路线识别：用轨迹起终点距离 + 总里程的近似度判断（不要求逐点重合）。
- compare_two：两次活动逐项对比（距离/均速/心率/爬升/功率等），输出差值 + 方向。
- period_trend：按周期（周/月）聚合里程/时长/爬升/平均强度，输出趋势序列。
"""
import math

from . import analysis


def _haversine(lat1, lon1, lat2, lon2):
    """两点球面距离（米）。"""
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _track_endpoints(records):
    """取轨迹真正起终点（首个/末个有 GPS 的点）。"""
    pts = [(r.get("lat"), r.get("lon")) for r in records
           if r.get("lat") is not None and r.get("lon") is not None]
    if not pts:
        return None, None
    return pts[0], pts[-1]


def _norm(v):
    return -1 if v < 0 else (1 if v > 0 else 0)


def same_route(records_a, records_b, dist_tol=0.10, endpoint_tol_m=1500):
    """判断两次骑行的轨迹是否为同一路线。

    dist_tol: 总里程相对差容忍（0.10 = 10%）。
    endpoint_tol_m: 起终点的最大间距（米），任一端点超差即判不同。
    """
    da = sum((r.get("dist_m") or 0) for r in records_a) or 0
    db = sum((r.get("dist_m") or 0) for r in records_b) or 0
    if da <= 0 or db <= 0:
        return False
    if abs(da - db) / max(da, db) > dist_tol:
        return False
    sa, ea = _track_endpoints(records_a)
    sb, eb = _track_endpoints(records_b)
    if sa is None or sb is None:
        return False
    if _haversine(sa[0], sa[1], sb[0], sb[1]) > endpoint_tol_m:
        return False
    if ea is None or eb is None:
        return True
    return _haversine(ea[0], ea[1], eb[0], eb[1]) <= endpoint_tol_m


def _activity_profile(db, act, config):
    """提取一条活动的对比画像（复用 db 行 + 逐条记录统计）。"""
    records = db.get_records(act["id"])
    # 功率：优先功率计，否则估值
    if not any(r.get("power") is not None for r in records):
        records = analysis.estimate_power(records, config)
    powers = [r.get("power") for r in records if r.get("power") is not None]
    wpk = None
    if powers:
        moving_h = (act.get("moving_s") or 0) / 3600.0
        if moving_h > 0:
            # 简单平均功率（不做 NP 归一，NP 在 training_load 里精确算）
            wpk = round(sum(powers) / len(powers))
    return {
        "id": act["id"],
        "name": act.get("name"),
        "date": (act.get("start_time") or "")[:10],
        "distance_km": act.get("distance_km"),
        "moving_h": round((act.get("moving_s") or 0) / 3600.0, 2),
        "avg_speed_kmh": act.get("avg_speed_kmh"),
        "avg_hr": round(act.get("avg_hr")) if act.get("avg_hr") else None,
        "ascent_m": round(act.get("ascent_m") or 0),
        "calories": round(act.get("calories") or 0),
        "avg_power_w": wpk and int(wpk),
        "has_hr": bool(act.get("has_hr")),
    }


def _compare_field(label, a, b, unit="", invert=False):
    """对比单个数值字段，返回带方向的描述。invert=True 表示越低越好（如用时）。"""
    if a is None or b is None:
        return None
    delta = round(a - b, 1)
    if delta == 0:
        return {"label": label, "a": a, "b": b, "delta": delta, "unit": unit, "verdict": "持平"}
    # 方向：更优 baseline 记 better/better_invert
    better = (delta < 0) != invert
    return {
        "label": label, "a": a, "b": b, "delta": abs(delta), "unit": unit,
        "direction": "上升" if delta > 0 else "下降",
        "improved": better,
    }


def compare_two(db, act_a, act_b, config=None):
    """对比两次骑行，返回结构化差异。a 为基准（较新），b 为对比（较旧）。

    返回 dict，含 profile + 各字段对比 + 是否同路线 + 结论摘要。
    """
    pa = _activity_profile(db, act_a, config)
    pb = _activity_profile(db, act_b, config)
    records_a = db.get_records(act_a["id"])
    records_b = db.get_records(act_b["id"])
    fields = [
        ("均速", pa["avg_speed_kmh"], pb["avg_speed_kmh"], "km/h", False),
        ("用时", pa["moving_h"], pb["moving_h"], "h", True),
        ("里程", pa["distance_km"], pb["distance_km"], "km", False),
        ("爬升", pa["ascent_m"], pb["ascent_m"], "m", False),
        ("平均心率", pa["avg_hr"], pb["avg_hr"], "bpm", False),
        ("平均功率", pa["avg_power_w"], pb["avg_power_w"], "W", False),
    ]
    diffs = [c for c in (_compare_field(*f) for f in fields) if c]
    same = same_route(records_a, records_b)
    return {
        "same_route": same,
        "a": pa, "b": pb,
        "diffs": diffs,
    }


def period_trend(db, months_back=4):
    """按月聚合近 N 个月的训练趋势（里程/时长/爬升/均速/次数）。"""
    months = db.months()
    months = months[:months_back]
    # months 已按月份降序，反转为升序便于看趋势
    months = list(reversed(months))
    return [
        {
            "month": m["month"],
            "count": m["count"],
            "distance_km": m["distance_km"],
            "hours": m["hours"],
            "ascent_m": m["ascent_m"],
            "calories": m["calories"],
            "avg_speed_kmh": m.get("avg_speed_kmh"),
        }
        for m in months
    ]


def week_trend(db, days_back=14):
    """按日聚合近 N 天里程趋势（用于观察训练频率/连续性）。"""
    from collections import defaultdict
    acts = db.list_activities()
    cutoff = None
    # 简化：取最近 N 天（用 db 里最新活动日期做锚点）
    by_day = defaultdict(lambda: {"distance_km": 0.0, "count": 0})
    for a in acts:
        d = (a.get("start_time") or "")[:10]
        if not d:
            continue
        by_day[d]["distance_km"] += (a.get("total_distance_m") or 0) / 1000.0
        by_day[d]["count"] += 1
    days = sorted(by_day.items())[-days_back:]
    return [{"date": d, "distance_km": round(v["distance_km"], 1),
             "count": v["count"]} for d, v in days]
