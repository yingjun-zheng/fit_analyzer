"""营养补给计划：按里程/时长/强度/消耗，输出补水、碳水、电解质的量化建议。

基于骑行营养补充的通用经验口径（参考耐力运动补给指南），非医疗建议：
- 补水：约 500~750 ml/小时（视温度上调）
- 碳水：约 30~60 g/小时（1 小时以上开始补，运动饮料+能量胶/香蕉）
- 电解质（钠）：约 300~700 mg/小时（大量出汗/炎热时偏上限）

输入：活动 stat（含 distance_km/timer_s/calories/avg_temp 等）。
输出：结构化建议 dict，含文字摘要。
"""


def nutrition_plan(act, config=None):
    """根据活动数据生成补给计划。

    act: 活动 dict，至少含 timer_s（秒）、distance_km（公里）；
         可选 calories（消耗 kcal）、avg_temp（平均温度）、avg_hr（平均心率）。
    返回 dict：{title, items[], summary}；数据不足时返回 None。
    """
    timer_s = act.get("timer_s")
    if not timer_s or timer_s <= 0:
        return None

    hours = timer_s / 3600.0
    dist_km = act.get("distance_km") or 0
    calories = act.get("calories")
    avg_temp = act.get("avg_temp")
    avg_hr = act.get("avg_hr")

    # 强度判断：有心率用心率，否则按速度粗估
    intensity = _judge_intensity(act, avg_hr, hours, dist_km)

    # 1) 补水量
    base_ml = 600.0  # 每小时基础补水 ml
    if avg_temp is not None and avg_temp > 25:
        base_ml += (avg_temp - 25) * 30  # 温度每高 1°C，每小时 +30ml
    if intensity == "高":
        base_ml += 100
    water_ml = round(base_ml * hours)
    water_bottles = round(water_ml / 750.0, 1)

    # 2) 碳水
    if hours < 1:
        carbs_g = round(20 * hours)  # 1 小时内少量即可
    else:
        carb_per_h = 40 if intensity in ("中", "高") else 30
        carbs_g = round(carb_per_h * hours)

    # 3) 电解质（钠）
    if intensity == "高" or (avg_temp is not None and avg_temp > 28):
        sodium_mg = round(600 * hours)  # 大量出汗
    else:
        sodium_mg = round(350 * hours)

    title = f"{hours:.1f} 小时 · {dist_km:.1f} km" + (f" · 消耗 {round(calories)} kcal" if calories else "")
    items = [
        ("补水", f"{water_ml} ml（约 {water_bottles} 瓶 750ml 水壶）", water_ml),
        ("碳水", f"{carbs_g} g（约 {round(carbs_g / 25)} 支能量胶或 {round(carbs_g / 27)} 根香蕉）", carbs_g),
        ("电解质（钠）", f"{sodium_mg} mg（约 {round(sodium_mg / 300)} 粒电解质片）", sodium_mg),
    ]

    # 文字摘要
    summary_lines = [
        f"预计骑行 {hours:.1f} 小时、{dist_km:.1f} km，强度「{intensity}」。",
        f"建议补水约 {water_ml} ml（每 15~20 分钟小口补），",
        f"碳水约 {carbs_g} g（起骑 45~60 分钟后开始，每 30 分钟补一次），",
        f"电解质钠约 {sodium_mg} mg（大量出汗或炎热天偏上限）。",
    ]
    if avg_temp is not None and avg_temp > 28:
        summary_lines.append(f"⚠ 平均温度 {avg_temp}°C 偏高，补水和电解质按上限执行。")
    summary = "".join(summary_lines)

    return {
        "title": title,
        "intensity": intensity,
        "hours": round(hours, 1),
        "dist_km": round(dist_km, 1),
        "water_ml": water_ml,
        "carbs_g": carbs_g,
        "sodium_mg": sodium_mg,
        "items": items,
        "summary": summary,
    }


def _judge_intensity(act, avg_hr, hours, dist_km):
    """判断骑行强度：低/中/高。有心率用心率，否则按均速。"""
    if avg_hr is not None:
        # 简化：假设最大心率 185，用百分比
        max_hr = 185
        pct = avg_hr / max_hr
        if pct < 0.65:
            return "低"
        if pct < 0.80:
            return "中"
        return "高"
    # 无心率，按均速
    avg_speed = dist_km / hours if hours > 0 else 0
    if avg_speed < 18:
        return "低"
    if avg_speed < 28:
        return "中"
    return "高"


def nutrition_text(act, config=None):
    """返回补给建议的纯文本（供 AI 面板/详情页直接展示）。"""
    plan = nutrition_plan(act, config)
    if not plan:
        return "数据不足，无法生成补给建议（缺少骑行时长）。"
    return plan["summary"]
