"""体能进步 / 训练质量分析（无功率计骑手的教练视角指标）。

针对只有心率+踏频+速度数据的场景（iGPSPORT 无功率计），提供 LLM 无法直接
从原始数据"看见"的深度指标：

1. aerobic_efficiency  心速比：平均心率(bpm) / 平均速度(km/h)，越低越高效。
                       同路线对比时，心速比下降 = 有氧体能进步。
2. cardiac_drift       心率漂移：把骑行分前后两半，同样速度水平下后半段心率
                       相对前半段的上升幅度（%），反映有氧耐力。
3. intensity_distribution  心率区间累计时长与占比（Z1~Z5），衡量训练结构。
4. cadence_quality     踏频质量：平均踏频 + 变异系数（稳定性），爬坡段掉踏频检测。

所有函数纯本地计算，不依赖 LLM，产出结构化 dict 供 review_agent 交给 LLM 解读。
"""
import statistics


def _safe_mean(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def _paired(records, key_a, key_b):
    """抽取两个字段同时非空的点对列表 [(a, b)]。"""
    return [(r[key_a], r[key_b]) for r in records
            if r.get(key_a) is not None and r.get(key_b) is not None]


def aerobic_efficiency(records):
    """心速比 = 平均心率 / 平均速度(kph)。越低越高效。

    返回 {"hr_per_kmh", "avg_hr", "avg_speed_kmh"}；缺数据返回 None。
    """
    pairs = _paired(records, "hr", "speed_ms")
    if not pairs or sum(s for _, s in pairs) == 0:
        return None
    avg_hr = _safe_mean([h for h, _ in pairs])
    avg_speed_ms = _safe_mean([s for _, s in pairs])
    if not avg_hr or not avg_speed_ms:
        return None
    avg_speed_kmh = avg_speed_ms * 3.6
    return {
        "hr_per_kmh": round(avg_hr / avg_speed_kmh, 2),
        "avg_hr": round(avg_hr, 1),
        "avg_speed_kmh": round(avg_speed_kmh, 1),
    }


def cardiac_drift(records):
    """心率漂移（aerobic decoupling，有氧解耦）。

    标准定义：持续有氧强度下，同等输出所需心率随时间上升的现象。
    无功率计时用「速度/心率」作效率因子（越大越高效），对比前后两半：
        decoupling% = (前半效率 - 后半效率) / 前半效率 × 100%
    正值 = 后程效率下降（同等速度需更高心率），提示有氧耐力不足。

    过滤：仅取速度 > 1 m/s（排除停车/推车）；前后半各有足够采样点。
    """
    pts = [(r.get("t") or 0, r.get("hr"), r.get("speed_ms")) for r in records
           if r.get("hr") is not None and r.get("speed_ms") is not None
           and r.get("speed_ms") > 1.0]  # 排除停车点
    if len(pts) < 40:
        return None
    ts = [p[0] for p in pts]
    t0, t1 = min(ts), max(ts)
    if t1 <= t0:
        return None
    mid = (t0 + t1) / 2
    front = [(h, s) for t, h, s in pts if t < mid]
    back = [(h, s) for t, h, s in pts if t >= mid]
    if len(front) < 15 or len(back) < 15:
        return None
    # 效率因子 = 速度(m/s) / 心率(bpm)，越大越高效
    def eff_factor(seg):
        h = _safe_mean([h for h, _ in seg])
        s = _safe_mean([s for _, s in seg])
        return (s / h) if h and s else None
    ef_front, ef_back = eff_factor(front), eff_factor(back)
    if not ef_front or ef_front <= 0:
        return None
    decoupling = round((ef_front - ef_back) / ef_front * 100.0, 1)
    return {
        "decoupling_pct": decoupling,
        "front_hr": round(_safe_mean([h for h, _ in front])),
        "back_hr": round(_safe_mean([h for h, _ in back])),
        "front_speed_kmh": round(_safe_mean([s for _, s in front]) * 3.6, 1),
        "back_speed_kmh": round(_safe_mean([s for _, s in back]) * 3.6, 1),
    }


def intensity_distribution(records, max_hr, pcts=None):
    """心率区间累计时长与占比（Z1~Z5）。

    pcts 默认 [0.6,0.7,0.8,0.9]；返回 [{zone,pct,minutes}]。
    """
    if not max_hr or max_hr <= 0:
        return None
    pcts = pcts or [0.6, 0.7, 0.8, 0.9]
    zone_seconds = [0.0] * 5
    n = len(records)
    for i in range(n):
        v = records[i].get("hr")
        if v is None:
            continue
        dt = 1.0
        if i + 1 < n:
            nxt = records[i + 1].get("t")
            cur = records[i].get("t")
            if nxt is not None and cur is not None:
                dt = max(0.0, min(nxt - cur, 30.0))
        z = 0
        for p in pcts:
            if v >= max_hr * p:
                z += 1
            else:
                break
        zone_seconds[min(z, 4)] += dt
    total = sum(zone_seconds)
    if total <= 0:
        return None
    out = []
    zone_names = ["Z1 恢复", "Z2 有氧", "Z3 节奏", "Z4 阈值", "Z5 无氧"]
    for i, s in enumerate(zone_seconds):
        out.append({
            "zone": zone_names[i],
            "minutes": round(s / 60.0, 1),
            "pct": round(s / total * 100.0, 1),
        })
    return out


def cadence_quality(records):
    """踏频质量：平均踏频、标准差、变异系数、以及爬坡段是否掉踏频。

    过滤：仅保留踏频 > 20 rpm 的有效值（0 或极低值多为采集中断/停车），
    排除后计算，避免把平均值拉低、变异系数虚高。
    返回 {"avg_cad", "std_cad", "cv_pct", "climb_avg_cad", "drop_on_climb"}。
    """
    cads = [r.get("cad") for r in records
            if r.get("cad") is not None and r.get("cad") > 20]
    if len(cads) < 10:
        return None
    avg = _safe_mean(cads)
    # 用中位数 + 四分位距过滤离群值，再算统计
    med = statistics.median(cads)
    std = statistics.pstdev(cads) if len(cads) >= 2 else 0.0
    cv = (std / avg * 100.0) if avg else None
    # 爬坡段判定：取海拔最高 20% 的记录看踏频是否偏低（同样过滤无效踏频）
    climbs = [(r.get("cad"), r.get("alt_m")) for r in records
              if r.get("cad") is not None and r.get("cad") > 20 and r.get("alt_m") is not None]
    climb_cad = None
    if climbs:
        alts = [a for _, a in climbs]
        lo, hi = min(alts), max(alts)
        if hi - lo > 30:  # 有 30m+ 爬升才算有坡
            thr = lo + (hi - lo) * 0.85
            climb_cads = [c for c, a in climbs if a >= thr]
            climb_cad = round(_safe_mean(climb_cads), 1) if climb_cads else None
    return {
        "avg_cad": round(avg, 1),
        "median_cad": round(med, 1),
        "std_cad": round(std, 1),
        "cv_pct": round(cv, 1) if cv is not None else None,
        "climb_avg_cad": climb_cad,
        "drop_on_climb": (climb_cad is not None and avg and climb_cad < avg - 5),
    }


def fitness_summary(records, max_hr=None, config=None):
    """汇总本次骑行的所有训练质量指标，供 review_agent 一次性注入给 LLM。

    返回 dict，各子指标可能为 None（数据缺失时）。
    """
    if max_hr is None and config:
        max_hr = config.get("hr_max_override") or None
    if not max_hr:
        hrs = [r.get("hr") for r in records if r.get("hr") is not None]
        max_hr = max(hrs) if hrs else None
    return {
        "aerobic_efficiency": aerobic_efficiency(records),
        "cardiac_drift": cardiac_drift(records),
        "intensity_distribution": intensity_distribution(records, max_hr),
        "cadence_quality": cadence_quality(records),
    }
