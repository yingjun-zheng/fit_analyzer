"""装备维护管家：里程驱动的保养提醒。

装备（链条/碟片/把带/轮胎等消耗件）按「启用日期以来的活动里程」累计
使用量，达到预期寿命给出更换提醒。

口径：
- 装备里程 = initial_km（启用时已有里程）+ 启用日期以来的活动总里程
  （已退役则截止到退役日）
- 使用进度 = 装备里程 / expected_km：>=100% 建议更换，70%~100% 关注
- 保养归零 = 把启用日期重置为今天（预期寿命重新计）

说明：v1 的里程按全部活动累计（不区分车辆）；单人单车场景足够精确，
多车用户可为每辆车分别建账（如「公路车-链条」「山地车-链条」）。
"""
import datetime

# 常见消耗件的预期寿命（km），供添加装备时快速填入
GEAR_TYPES = {
    "链条": 3000, "飞轮": 6000, "牙盘": 8000, "刹车片": 4000, "碟片": 4000,
    "外胎": 6000, "内带": 8000, "把带": 8000, "变速线": 8000, "刹车线": 8000,
    "中轴": 10000, "脚踏": 10000,
}


def date_to_ts(d):
    """YYYY-MM-DD → 当天 0 点的本地时间戳。"""
    return int(datetime.datetime.strptime(d, "%Y-%m-%d").timestamp())


def ts_to_date(ts):
    """时间戳 → YYYY-MM-DD；空返回空串。"""
    return datetime.date.fromtimestamp(ts).isoformat() if ts else ""


def gear_mileage_km(db, g):
    """单件装备的累计使用里程（km）。"""
    end_ts = g.get("retired_ts") if g.get("retired") else None
    return (g.get("initial_km") or 0) + \
        db.sum_distance_between(g.get("start_ts") or 0, end_ts) / 1000.0


def gear_status(db, g):
    """单件装备状态。

    返回 {id, name, type, start_date, km, expected_km, pct, level, advice, retired}；
    level: none(未设寿命) / ok(<70%) / watch(70%~100%) / due(>=100%)。
    """
    km = gear_mileage_km(db, g)
    expected = g.get("expected_km") or 0
    if expected > 0:
        pct = km / expected * 100.0
        if pct >= 100:
            level = "due"
            advice = f"已 {km:.0f} km，超过预期 {expected:.0f} km，建议更换/保养"
        elif pct >= 70:
            level = "watch"
            advice = f"已 {km:.0f} km（预期 {expected:.0f} km），留意磨损"
        else:
            level = "ok"
            advice = f"已 {km:.0f} km（预期 {expected:.0f} km），状态良好"
    else:
        pct, level = None, "none"
        advice = f"已 {km:.0f} km（未设预期寿命）"
    return {
        "id": g["id"], "name": g.get("name"), "type": g.get("type"),
        "start_date": g.get("start_date"), "km": round(km, 1),
        "expected_km": expected or None,
        "pct": round(pct, 1) if pct is not None else None,
        "level": level, "advice": advice, "retired": bool(g.get("retired")),
    }


def gear_report(db, include_retired=False):
    """全部装备状态，按使用进度降序（最接近寿命的在前）。"""
    out = [gear_status(db, g) for g in db.gear_list()]
    if not include_retired:
        out = [s for s in out if not s["retired"]]
    out.sort(key=lambda s: -(s["pct"] or 0))
    return out


def due_gears(db):
    """需要提醒的装备（watch + due），供月度页提醒卡。"""
    return [s for s in gear_report(db) if s["level"] in ("watch", "due")]
