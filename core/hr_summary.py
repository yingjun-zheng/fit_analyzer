"""心率区间深度总结：从 5 区心率分布诊断训练结构，输出配速对比与训练建议。

基于心率（无功率计场景）的教练级诊断口径：
- Z2（有氧）占比 → 有氧基础是否扎实（长距离耐力训练的基石）
- Z4（阈值）占比 → 阈值训练强度
- Z5（无氧）占比 → 是否过度泡在高强度区
- Z1（恢复）占比 → 热身/恢复是否充分

输出结构化文字建议，纯数据侧实现，无外部依赖。
参考通用心率训练区间定义（Z1 恢复 / Z2 有氧 / Z3 节奏 / Z4 阈值 / Z5 无氧）。
"""


def hr_summary(hr_zones, records=None, max_hr=None):
    """根据 hr_zones（analysis.hr_zones 返回）生成深度总结。

    hr_zones: [{zone, seconds, pct, label}, ...]，zone 从 1 开始（5 区）。
    返回 dict：{items[], summary[]}；无数据返回 None。
    """
    if not hr_zones:
        return None

    total = sum(z["seconds"] for z in hr_zones)
    if total <= 0:
        return None

    # 各区间秒数（Z1..Z5，缺省补 0）
    sec = {z["zone"]: z["seconds"] for z in hr_zones}
    pct = {z["zone"]: z["pct"] for z in hr_zones}

    def _p(z):
        return pct.get(z, 0.0)

    z1, z2, z3, z4, z5 = _p(1), _p(2), _p(3), _p(4), _p(5)

    # 训练结构诊断
    aero_pct = z1 + z2          # 有氧+恢复
    threshold_pct = z3 + z4     # 节奏+阈值
    anaerobic_pct = z5          # 无氧

    items = [
        ("有氧区间（Z1+Z2）", f"{aero_pct:.0f}%（恢复+有氧基础）", aero_pct),
        ("中高强度（Z3+Z4）", f"{threshold_pct:.0f}%（节奏+阈值）", threshold_pct),
        ("无氧区间（Z5）", f"{anaerobic_pct:.0f}%", anaerobic_pct),
    ]

    # 训练建议
    summary = []
    if aero_pct >= 70:
        summary.append("以有氧为主，基础耐力扎实，适合长距离耐力骑行。")
    elif aero_pct >= 50:
        summary.append("有氧基础尚可，可适当增加低强度长距离骑行夯实耐力。")
    else:
        summary.append("有氧占比偏低（<50%），建议增加 Z2 区间的长距离慢骑打基础。")

    if anaerobic_pct > 15:
        summary.append("无氧区（Z5）时间偏长，注意别频繁冲极限，避免过度疲劳。")

    if threshold_pct > 40:
        summary.append("阈值/节奏占比高，偏向高强度训练，注意穿插恢复日。")

    # 配速对比（如有 records，算有氧段 vs 阈值段的均速）
    speed_note = None
    if records:
        speed_note = _zone_speed_compare(records, max_hr)
        if speed_note:
            summary.append(speed_note)

    return {
        "items": items,
        "summary": summary,
        "aero_pct": round(aero_pct, 1),
        "threshold_pct": round(threshold_pct, 1),
        "anaerobic_pct": round(anaerobic_pct, 1),
    }


def _zone_speed_compare(records, max_hr):
    """对比有氧段(Z2)与阈值段(Z4)的平均速度，给出配速效率。"""
    if not max_hr or max_hr <= 0:
        return None
    z2_lo, z2_hi = max_hr * 0.7, max_hr * 0.8
    z4_lo, z4_hi = max_hr * 0.9, max_hr * 1.0
    z2_s = [r.get("speed_ms") for r in records
            if r.get("hr") is not None and r.get("speed_ms") is not None
            and z2_lo <= r.get("hr") < z2_hi]
    z4_s = [r.get("speed_ms") for r in records
            if r.get("hr") is not None and r.get("speed_ms") is not None
            and z4_lo <= r.get("hr") < z4_hi]
    if len(z2_s) < 5 or len(z4_s) < 5:
        return None
    v2 = sum(z2_s) / len(z2_s) * 3.6
    v4 = sum(z4_s) / len(z4_s) * 3.6
    return f"配速对比：Z2 均速 {v2:.1f} km/h，Z4 均速 {v4:.1f} km/h（阈值-有氧差 {v4 - v2:.1f} km/h）。"


def hr_summary_text(hr_zones, records=None, max_hr=None):
    """返回心率深度总结的纯文本。"""
    s = hr_summary(hr_zones, records, max_hr)
    if not s:
        return "无心率区间数据，无法总结。"
    lines = ["心率训练结构："]
    lines.append("  " + "，".join(f"{k} {v}" for k, v, _ in s["items"]))
    lines.append("建议：" + "".join(s["summary"]))
    return "\n".join(lines)
