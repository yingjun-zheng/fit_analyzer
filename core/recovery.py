"""训练后恢复建议：按强度/时长/温度/爬升，输出冷身、营养、睡眠的量化建议。

基于耐力运动恢复的通用经验口径（非医疗建议）：
- 冷身放松：强度越高/时间越长，放松骑与拉伸时间越长
- 补糖：运动后 30 分钟内按体重 0.6~1.2 g/kg 补碳水，修复肌糖原
- 蛋白质：中高强度课后 1 小时内补 20~40g
- 补水：按骑行时长估算课后补水量（尿色清亮为达标）
- 睡眠：高强度/长时长课后需要更多睡眠

输入：活动 stat（timer_s/distance_km/calories/avg_temp/ascent_m/avg_hr/max_hr）。
输出：与 nutrition 同构的结构化建议 dict；数据不足（无时长）返回 None。
"""


def recovery_plan(act, config=None):
    """根据活动数据生成训练后恢复建议。

    act: 活动 dict，至少含 timer_s（秒）；可选 distance_km/ascent_m/avg_temp/
         avg_hr/max_hr。强度判定优先心率（最大心率取设置覆盖或活动内最大）。
    返回 dict：{title, intensity, items[], summary}；无时长返回 None。
    """
    timer_s = act.get("timer_s")
    if not timer_s or timer_s <= 0:
        return None

    hours = timer_s / 3600.0
    dist_km = act.get("distance_km") or 0
    ascent = act.get("ascent_m") or 0
    avg_temp = act.get("avg_temp")

    intensity = _judge_intensity(act, config)
    weight = float(config.get("power_rider_weight_kg", 70.0)) if config else 70.0

    # 1) 冷身放松
    if intensity == "高" or hours >= 3:
        cooldown = "10 分钟低踏频放松骑收尾，课后 15 分钟下肢拉伸/泡沫轴放松"
    elif intensity == "中" or hours >= 1:
        cooldown = "5~10 分钟放松骑收尾，课后 10 分钟拉伸"
    else:
        cooldown = "轻松拉伸 5~10 分钟即可"

    # 2) 补糖（30 分钟窗口，修复肌糖原）
    carb_per_kg = 1.2 if intensity == "高" else (1.0 if intensity == "中" else 0.6)
    carb_g = round(weight * carb_per_kg)
    carb = (f"运动后 30 分钟内补 {carb_g} g 碳水"
            f"（约 {max(1, round(carb_g / 27))} 根香蕉或 {max(1, round(carb_g / 25))} 支能量胶）")

    # 3) 蛋白质
    if intensity == "高":
        protein = "1 小时内补 30 g 蛋白质（蛋/奶/乳清），帮助肌肉修复"
    elif intensity == "中":
        protein = "1 小时内补 20 g 蛋白质，正餐正常吃即可"
    else:
        protein = "正常饮食即可，无需额外补剂"

    # 4) 补水（课后恢复性补水 ≈ 骑行中补水量 × 1.2）
    water_ml = round(hours * 500 * 1.2 / 50) * 50
    water = f"课后分次补水约 {water_ml} ml（尿色清亮为达标）"

    # 5) 睡眠
    if intensity == "高" or hours >= 3:
        sleep = "今晚保证 7.5 小时以上睡眠，睡前可做轻拉伸助眠"
    else:
        sleep = "保持规律作息，7 小时左右睡眠"

    items = [
        ("冷身放松", cooldown),
        ("补糖", carb),
        ("蛋白质", protein),
        ("补水", water),
        ("睡眠", sleep),
    ]

    summary_lines = [
        f"本次骑行 {hours:.1f} 小时、{dist_km:.1f} km，强度「{intensity}」。",
        f"重点是 {('恢复性补糖与充分睡眠' if intensity != '低' else '放松与正常饮食')}。",
    ]
    if avg_temp is not None and avg_temp > 28:
        summary_lines.append(f"⚠ 平均温度 {avg_temp}°C 偏高，课后继续补电解质，避免立即冲凉水澡。")
    if avg_temp is not None and avg_temp < 5:
        summary_lines.append(f"平均温度 {avg_temp}°C 偏低，课后尽快换干衣物并保暖。")
    if ascent >= 500:
        summary_lines.append("爬升较大，重点放松大腿前侧（股四头肌）与小腿。")
    summary = "".join(summary_lines)

    return {
        "title": f"{hours:.1f} 小时 · {dist_km:.1f} km · 强度「{intensity}」",
        "intensity": intensity,
        "hours": round(hours, 1),
        "dist_km": round(dist_km, 1),
        "items": items,
        "summary": summary,
    }


def _judge_intensity(act, config):
    """强度判定（低/中/高）：优先心率（最大心率取设置覆盖或活动内最大），无心率按均速。"""
    max_hr = (config.get("hr_max_override") if config else None) or act.get("max_hr")
    avg_hr = act.get("avg_hr")
    if max_hr and avg_hr:
        pct = avg_hr / max_hr
        if pct < 0.65:
            return "低"
        if pct < 0.80:
            return "中"
        return "高"
    hours = (act.get("timer_s") or 0) / 3600.0
    avg_speed = (act.get("distance_km") or 0) / hours if hours > 0 else 0
    if avg_speed < 18:
        return "低"
    if avg_speed < 28:
        return "中"
    return "高"


def recovery_text(act, config=None):
    """返回恢复建议的纯文本（供 AI 面板/详情页直接展示）。"""
    plan = recovery_plan(act, config)
    if not plan:
        return "数据不足，无法生成恢复建议（缺少骑行时长）。"
    return plan["summary"]
