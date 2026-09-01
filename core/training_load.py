"""训练负荷：TSS / NP / IF + CTL/ATL/TSB 三指标（教练视角的疲劳监控）。

参考 Andy Coggan 的训练压力理论：
- NP（归一化功率）：对逐秒功率做 30 秒平均后取四次方再均值开四次方，反映等效强度。
- IF（强度因子）= NP / FTP。
- TSS（训练压力分数）= (秒 × NP × IF) / (FTP × 3600) × 100。
- CTL（长期体能/慢性负荷）：TSS 的 42 天指数加权。
- ATL（短期疲劳/急性负荷）：TSS 的 7 天指数加权。
- TSB（状态）= CTL - ATL，正值偏"恢复/状态佳"，负值偏"疲劳"。

无功率数据时的降级：
- 若有心率 → 用 hrTSS（基于心率区间的训练压力，近似 TRIMP×36 区间法）。
- 若都无 → 用 RPE×时长 的粗估（主观强度 × 小时）。
"""
import math

# 指数加权衰减时间常数（天）
CTL_TAU = 42.0
ATL_TAU = 7.0


def _lactate_zones_pcts():
    """按最大心率百分比的心率 5 区（与 config.hr_zone_pcts 一致，缺省 60/70/80/90%）。"""
    return [0.6, 0.7, 0.8, 0.9]


def normalized_power(records, ftp=None):
    """计算 NP（归一化功率，瓦）。

    records: 含 power 字段的逐条记录。返回 (np, avg_power)。
    """
    powers = [r.get("power") for r in records if r.get("power") is not None]
    if not powers:
        return None, None
    avg = sum(powers) / len(powers)
    # 30 秒滚动平均后再四次方
    n = len(powers)
    window = min(30, n)
    smoothed = []
    for i in range(n):
        win = powers[max(0, i - window + 1):i + 1]
        smoothed.append(sum(win) / len(win))
    mean_fourth = sum(p ** 4 for p in smoothed) / len(smoothed)
    np_val = mean_fourth ** 0.25
    return round(np_val, 1), round(avg, 1)


def _tss_from_power(records, ftp):
    """功率 TSS。records 需含 power。"""
    if not ftp or ftp <= 0:
        return None
    np_val, _ = normalized_power(records)
    if np_val is None:
        return None
    # 总时长（秒）：用首尾时间戳
    ts = [r.get("t") for r in records if r.get("t") is not None]
    seconds = (max(ts) - min(ts)) if len(ts) >= 2 else len(records)
    if seconds <= 0:
        return None
    intensity = np_val / ftp
    return round((seconds * np_val * intensity) / (ftp * 3600.0) * 100.0, 1)


def _tss_from_hr(records, max_hr):
    """心率 TSS（hrTSS）近似。

    用「等效强度因子 IF」框架：每档心率区映射一个 IF（0~1），
    TSS = Σ(每区时长小时 × IF²) × 100，对齐功率 TSS 的数量级（1 小时 FTP 节奏 ≈ 100）。
    IF 映射（按最大心率百分比）：
      Z1 <60% → 0.50，Z2 60-70% → 0.65，Z3 70-80% → 0.75，
      Z4 80-90% → 0.85，Z5 >90% → 0.95。
    """
    if not max_hr or max_hr <= 0:
        return None
    pcts = _lactate_zones_pcts()  # [0.6, 0.7, 0.8, 0.9]
    ifs = [0.50, 0.65, 0.75, 0.85, 0.95]
    zone_seconds = [0.0] * 5
    n = len(records)
    for i in range(n):
        v = records[i].get("hr")
        if v is None:
            continue
        dt = 1.0
        if i + 1 < n:
            nxt_t = records[i + 1].get("t")
            cur_t = records[i].get("t")
            if nxt_t is not None and cur_t is not None:
                dt = max(0.0, min(nxt_t - cur_t, 30.0))
        zone = 0
        for p in pcts:
            if v >= max_hr * p:
                zone += 1
            else:
                break
        zone = min(zone, 4)
        zone_seconds[zone] += dt
    total = 0.0
    for zs, if_ in zip(zone_seconds, ifs):
        total += (zs / 3600.0) * (if_ ** 2) * 100.0
    return round(total, 1)


def compute_activity_tss(records, config=None, ftp=None, max_hr=None):
    """计算单次活动的 TSS。

    优先级：功率计 FTP TSS > 心率 hrTSS > None。
    返回 (tss, method, np_w, avg_w, intensity)。
    """
    cfg = config
    ftp = ftp or (cfg.get("ftp_w") if cfg else None)
    max_hr = max_hr or (cfg.get("hr_max_override") if cfg and cfg.get("hr_max_override") else None)

    has_power = any(r.get("power") is not None for r in records)

    if has_power and ftp:
        np_val, avg = normalized_power(records)
        tss = _tss_from_power(records, ftp)
        if tss is not None:
            intensity = round(np_val / ftp, 2) if np_val else None
            return tss, "power", np_val, avg, intensity

    if max_hr:
        tss = _tss_from_hr(records, max_hr)
        if tss is not None:
            return tss, "hr", None, None, None

    return None, None, None, None, None


def _ewma_daily(daily_tss, tau):
    """按日历天连续计算指数加权移动平均（正确版本）。

    daily_tss: 按日期升序的 [(date_str, tss)] 列表。
    关键：空档天数也参与衰减——对缺失的日期 tss=0，逐日推进。这样
    数月的训练空档会让 CTL/ATL 正确衰减，而不是错误地保持高位。

    返回 {date_str: ewma_value}，仅包含有活动的日期。
    """
    import datetime as _dt
    alpha = 1 - math.exp(-1.0 / tau)
    result = {}
    prev = None
    prev_date = None
    for date_str, tss in daily_tss:
        d = _dt.date.fromisoformat(date_str)
        if prev is None:
            prev = tss
            prev_date = d
        else:
            # 先按空档天数衰减（每天 tss=0 推进一次）
            gap_days = (d - prev_date).days
            for _ in range(max(0, gap_days - 1)):  # 中间缺失的整天
                prev = prev + alpha * (0 - prev)
            # 当天有负荷
            prev = prev + alpha * (tss - prev)
            prev_date = d
        result[date_str] = prev
    return result


def build_performance_curve(daily_tss, ftp=None):
    """由每日 TSS 序列计算 CTL/ATL/TSB 曲线（按日历天连续衰减）。

    daily_tss: 按日期升序的 [(date_str, tss)] 列表。
    返回 (ctl_by_date, atl_by_date, tsb_by_date)，以及最新一天的快照。
    """
    dates = [d for d, _ in daily_tss]
    ctls = _ewma_daily(daily_tss, CTL_TAU)
    atls = _ewma_daily(daily_tss, ATL_TAU)
    tsbs = {}
    for d in dates:
        if d in ctls and d in atls:
            # 当日 TSB 用「前一天 CTL - 前一天 ATL」更准确，这里用当日值近似
            tsbs[d] = round(ctls[d] - atls[d], 1)
        else:
            tsbs[d] = None
    # 最新快照
    latest_date = dates[-1] if dates else None
    latest = {}
    if latest_date:
        latest = {
            "date": latest_date,
            "ctl": round(ctls[latest_date], 1),
            "atl": round(atls[latest_date], 1),
            "tsb": tsbs[latest_date],
        }
    return ctls, atls, tsbs, latest


def recent_week_tss(daily_tss, days=7):
    """计算最近 N 个自然日的 TSS 合计（不是「最后 N 条记录」）。

    daily_tss: 按日期升序的 [(date_str, tss)]。
    以最后一条记录为锚点，向前推 days 天窗口求和。
    """
    import datetime as _dt
    if not daily_tss:
        return 0.0
    anchor = _dt.date.fromisoformat(daily_tss[-1][0])
    start = anchor - _dt.timedelta(days=days - 1)
    total = 0.0
    for date_str, tss in daily_tss:
        d = _dt.date.fromisoformat(date_str)
        if start <= d <= anchor:
            total += tss
    return round(total, 1)


def daily_tss_from_activities(acts_with_tss):
    """把多条活动的 (date, tss) 聚合成每日总和，按日期升序。

    acts_with_tss: [(date_str, tss)] 可散乱。
    返回 [(date, total_tss)] 升序。
    """
    from collections import defaultdict
    agg = defaultdict(float)
    for d, tss in acts_with_tss:
        if tss is not None:
            agg[d] += tss
    return sorted(agg.items())


def recovery_advice(tsb):
    """根据 TSB 给出恢复/训练提示文本。"""
    if tsb is None:
        return "缺训练负荷数据，无法评估疲劳状态。"
    if tsb < -30:
        return f"TSB={tsb}，深度疲劳，建议休息或轻松恢复骑行，避免高强度。"
    if tsb < -10:
        return f"TSB={tsb}，疲劳累积，可安排低强度有氧，避免连续高强度。"
    if tsb <= 10:
        return f"TSB={tsb}，负荷适中，可按计划正常训练。"
    if tsb <= 25:
        return f"TSB={tsb}，恢复充分、状态良好，适合安排高强度或比赛。"
    return f"TSB={tsb}，过度恢复（训练量偏低），可适度上量。"
