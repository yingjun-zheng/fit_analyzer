"""月度骑行数据查询 Agent：用工具调用回答关于「骑行训练」的问题。

设计要点：
- 不读取逐秒 records，只从 DB 做聚合/列表查询 → 响应快、上下文小。
- 模型只看到月份名称与活动数量等最小骨架，真实统计通过工具获取。
- 多轮 ReAct：模型可连续调用多个工具，最后基于结果作答。
- 支持多轮会话：history 注入历史问答（user/assistant 精华对），模型能
  理解「那上周呢」这类指代追问；所有工具支持可选 month 参数跨月查询。
- 若后端不支持工具调用，自动降级为「预计算月度摘要 + 单次问答」。
"""
import datetime
import json
import logging
import re

from . import ai_client

log = logging.getLogger("fit.monthagent")

AGENT_SYSTEM = """你是骑行训练分析助手，通过调用工具来回答用户关于「骑行训练」的问题。
规则：
1. 必须先调用合适的工具获取真实数据，再基于数据回答；不要编造未查询到的数字。
2. 可以连续调用多个工具（例如先看月度概览，再看活动列表与趋势；复合问题可分步查询后综合分析）。
3. 所有月度类工具都接受可选的 month 参数（YYYY-MM），省略时查询当前会话默认月份。
   若问题涉及其他月份（如「那8月呢」「上个月」），传入对应月份即可跨月查询。
4. 工具返回聚合数据，不是每次骑行的逐秒数据。
5. 数据缺失的维度不要强行分析，直接说明「无该数据」。
6. 用简洁中文回答，给出具体数值与单位；涉及对比时引用工具返回的具体数字。
7. 若存在历史对话，结合上下文理解指代（如「那上周呢」「再详细点」）；
   「上周/上个月」等相对时间请结合当前日期推断对应月份后再查询。
8. 专项工具（无 month 参数）：get_training_load 查训练负荷与恢复建议（「该不该休息」）、
   compare_activities 查两次活动对比（「进步了没」）、get_fitness_summary 查体能指标
   （心速比/心率漂移/踏频质量）、get_gear_status 查装备台账（「装备要换了吗」）。
   复合问题（如「对比这周和上周，然后看看我该不该休息」）可连续调用多个工具。
9. 写操作（set_ftp / set_year_goal / add_gear / set_commute / set_vehicle）会先弹出确认框征求用户同意：
   调用前先用一句话说明打算做什么（如「我来帮你把 FTP 设为 250W，请确认」），
   工具返回「已执行/用户取消」后再基于结果作答，不要假装已经修改。"""

# 会话历史限制：最多保留最近 N 轮（user+assistant 成对），防止上下文膨胀
MAX_HISTORY_ROUNDS = 8
# 单次工具结果注入上下文的最大字符数（超出截断，避免撑爆上下文）
TOOL_RESULT_MAX_CHARS = 6000

_MONTH_ARG_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DATE_ARG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 每个工具共有的可选 month 参数（跨月追问）
_MONTH_PARAM = {
    "month": {
        "type": "string",
        "description": "要查询的月份，格式 YYYY-MM；省略则查询当前会话默认月份",
    }
}


MONTH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_month_overview",
            "description": "获取指定月份的整体训练概览：骑行次数、总里程(km)、总用时(小时)、总爬升(m)、总消耗(kcal)、平均速度(km/h)。",
            "parameters": {
                "type": "object",
                "properties": dict(_MONTH_PARAM),
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_month_activities",
            "description": "获取指定月份的每次骑行摘要列表：日期、名称、距离、用时、均速、爬升、卡路里、设备。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回最近 N 条活动；省略则返回全部",
                    },
                    **_MONTH_PARAM,
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_month_distance_trend",
            "description": "按日期返回该月每日骑行里程(km)与次数，用于观察训练频率与负荷分布。",
            "parameters": {
                "type": "object",
                "properties": dict(_MONTH_PARAM),
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_month_hr_summary",
            "description": "月度心率聚合：有平均心率的活动数、平均心率均值、最大心率最大值。",
            "parameters": {
                "type": "object",
                "properties": dict(_MONTH_PARAM),
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_month_speed_summary",
            "description": "月度速度聚合：所有活动平均速度的最小/最大/均值(km/h)，以及按里程加权的加权平均速度。",
            "parameters": {
                "type": "object",
                "properties": dict(_MONTH_PARAM),
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_month_device_summary",
            "description": "按设备统计该月骑行次数与总里程。",
            "parameters": {
                "type": "object",
                "properties": dict(_MONTH_PARAM),
            },
        },
    },
    # ---- 专项能力（无 month 参数，跨活动综合分析）----
    {
        "type": "function",
        "function": {
            "name": "get_training_load",
            "description": "训练负荷分析：最近 CTL（体能）/ ATL（疲劳）/ TSB（状态）快照、近 7 天累计 TSS、恢复建议。用于「该不该休息」「是否训练过度」类问题。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_activities",
            "description": "对比两次活动（默认：最近一次 vs 与之最相似的旧活动；可用 date 指定较新的那次，格式 YYYY-MM-DD）。返回距离/均速/爬升/心率差异与同路线判断。用于「进步了没」「和上次比怎么样」。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "要对比的较新活动日期 YYYY-MM-DD；省略则用最近一次",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fitness_summary",
            "description": "体能/训练质量指标（默认最近一次有数据的活动，可用 date 指定）：心速比（有氧效率）、心率漂移（有氧解耦）、心率区间分布、踏频质量。用于「体能如何」「耐力够不够」类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "要分析的骑行日期 YYYY-MM-DD；省略则用最近一次",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_gear_status",
            "description": "装备台账：链条/碟片等消耗件的累计里程、预期寿命进度、状态（ok/watch/due）与保养建议。可用 level 筛选（due=需更换 watch=留意）、vehicle 筛选所属车辆。用于「装备要换了吗」类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["due", "watch", "ok", "none"],
                        "description": "按状态筛选；省略则返回全部非退役装备",
                    },
                    "vehicle": {
                        "type": "string",
                        "description": "按所属车辆筛选（如「公路车」）；省略则返回全部",
                    },
                },
            },
        },
    },
    # ---- Action 工具（写操作，执行前会请求用户确认）----
    {
        "type": "function",
        "function": {
            "name": "set_ftp",
            "description": "设置 FTP（功能阈值功率，瓦）。写操作：会弹出确认框，用户同意后才生效，影响训练负荷计算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "w": {"type": "integer", "description": "FTP 功率（瓦），需为正数"},
                },
                "required": ["w"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_year_goal",
            "description": "设置年度骑行里程目标（km，0=关闭）。写操作：会弹出确认框。",
            "parameters": {
                "type": "object",
                "properties": {
                    "km": {"type": "number", "description": "年度目标里程 km，0 表示关闭"},
                },
                "required": ["km"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_gear",
            "description": "添加一件装备到消耗件台账（链条/碟片/外胎等），可设预期寿命。写操作：会弹出确认框。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "装备名称，如：公路车-链条"},
                    "type": {"type": "string", "description": "装备类型，如：链条/飞轮/外胎/刹车片"},
                    "expected_km": {"type": "integer", "description": "预期寿命里程 km，如 3000"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_commute",
            "description": "把某天的骑行动作标记为「通勤」或取消标记（用于区分通勤里程与训练里程）。写操作：会弹出确认框。同一天多次骑行时标记最近一次。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "骑行日期 YYYY-MM-DD"},
                    "flag": {"type": "boolean", "description": "true=标记为通勤，false=取消标记，默认 true"},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_vehicle",
            "description": "把某天的骑行标记为骑的哪辆车（用于装备按车辆分开统计里程）。车辆名需与装备台账中的车辆一致。写操作：会弹出确认框。同一天多次骑行时标记最近一次。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "骑行日期 YYYY-MM-DD"},
                    "vehicle": {"type": "string", "description": "车辆名（如「公路车」）；空字符串表示清除标记"},
                },
                "required": ["date", "vehicle"],
            },
        },
    },
]


def _safe_avg(values):
    v = [x for x in values if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def _month_overview(db, month):
    rows = db.list_activities(month=month)
    if not rows:
        return {"error": "该月无活动数据"}
    total_dist = sum(r.get("total_distance_m") or 0 for r in rows)
    total_time = sum(r.get("timer_s") or 0 for r in rows)
    total_ascent = sum(r.get("ascent_m") or 0 for r in rows)
    total_cal = sum(r.get("calories") or 0 for r in rows)
    speeds = [r.get("avg_speed_ms") for r in rows if r.get("avg_speed_ms")]
    weighted_speed = (sum((r.get("avg_speed_ms") or 0) * (r.get("total_distance_m") or 0) for r in rows) / total_dist * 3.6) if total_dist else None
    # 通勤/训练口径：通勤按 commute 标记拆分（P1-B）
    commute_dist = sum(r.get("total_distance_m") or 0 for r in rows if r.get("commute"))
    commute_cnt = sum(1 for r in rows if r.get("commute"))
    return {
        "month": month,
        "count": len(rows),
        "distance_km": round(total_dist / 1000, 1),
        "hours": round(total_time / 3600, 1),
        "ascent_m": round(total_ascent),
        "calories": round(total_cal),
        "avg_speed_kmh": round(_safe_avg([s * 3.6 for s in speeds]), 1) if speeds else None,
        "weighted_avg_speed_kmh": round(weighted_speed, 1) if weighted_speed else None,
        "commute": {"count": commute_cnt, "distance_km": round(commute_dist / 1000, 1)},
        "training_distance_km": round((total_dist - commute_dist) / 1000, 1),
    }


def _month_activities(db, month, limit=None):
    rows = db.list_activities(month=month)
    if not rows:
        return {"error": "该月无活动数据"}
    out = []
    src = rows[:limit] if limit else rows
    capped = False
    if len(src) > 60:  # 防止大月份撑爆上下文
        src = src[:60]
        capped = True
    for r in src:
        out.append({
            "date": r.get("start_time", "")[:10],
            "name": r.get("name"),
            "device": r.get("device") or "未知",
            "distance_km": r.get("distance_km"),
            "timer_min": round((r.get("timer_s") or 0) / 60, 1),
            "avg_speed_kmh": r.get("avg_speed_kmh"),
            "ascent_m": round(r.get("ascent_m") or 0),
            "calories": round(r.get("calories") or 0),
            "has_hr": bool(r.get("avg_hr")),
            "has_cad": bool(r.get("avg_cad")),
            "commute": bool(r.get("commute")),
        })
    res = {"count": len(rows), "shown": len(out), "activities": out}
    if capped:
        res["note"] = "活动较多，仅返回最近 60 条"
    return res


def _month_distance_trend(db, month):
    rows = db.list_activities(month=month)
    if not rows:
        return {"error": "该月无活动数据"}
    days = {}
    for r in rows:
        d = r.get("start_time", "")[:10]
        days.setdefault(d, {"distance_km": 0.0, "count": 0})
        days[d]["distance_km"] += (r.get("total_distance_m") or 0) / 1000.0
        days[d]["count"] += 1
    trend = [{"date": d, "distance_km": round(v["distance_km"], 1), "count": v["count"]} for d, v in sorted(days.items())]
    distances = [t["distance_km"] for t in trend]
    return {
        "day_count": len(trend),
        "max_daily_distance_km": round(max(distances), 1) if distances else None,
        "min_daily_distance_km": round(min(distances), 1) if distances else None,
        "trend": trend,
    }


def _month_hr_summary(db, month):
    rows = db.list_activities(month=month)
    hrs = [r.get("avg_hr") for r in rows if r.get("avg_hr")]
    max_hrs = [r.get("max_hr") for r in rows if r.get("max_hr")]
    if not hrs:
        return {"error": "该月活动无心率数据"}
    return {
        "activities_with_hr": len(hrs),
        "avg_hr_mean": round(_safe_avg(hrs)),
        "max_hr_max": round(max(max_hrs)) if max_hrs else None,
    }


def _month_speed_summary(db, month):
    rows = db.list_activities(month=month)
    speeds = [r.get("avg_speed_kmh") for r in rows if r.get("avg_speed_kmh")]
    if not speeds:
        return {"error": "该月活动无有效速度数据"}
    total_dist = sum(r.get("total_distance_m") or 0 for r in rows)
    weighted = (sum((r.get("avg_speed_ms") or 0) * (r.get("total_distance_m") or 0) for r in rows) / total_dist * 3.6) if total_dist else None
    return {
        "avg_speed_min_kmh": round(min(speeds), 1),
        "avg_speed_max_kmh": round(max(speeds), 1),
        "avg_speed_mean_kmh": round(_safe_avg(speeds), 1),
        "weighted_avg_speed_kmh": round(weighted, 1) if weighted else None,
    }


def _month_device_summary(db, month):
    rows = db.list_activities(month=month)
    devs = {}
    for r in rows:
        dev = r.get("device") or "未知"
        devs.setdefault(dev, {"count": 0, "distance_km": 0.0})
        devs[dev]["count"] += 1
        devs[dev]["distance_km"] += (r.get("total_distance_m") or 0) / 1000.0
    return {"devices": [{"device": k, "count": v["count"], "distance_km": round(v["distance_km"], 1)} for k, v in sorted(devs.items(), key=lambda x: -x[1]["distance_km"])]}


def _tool_training_load(db, config):
    """训练负荷：复用确定性计算链路（与复盘 Agent 同口径），结果给 LLM 解读。"""
    from . import training_load
    acts = db.list_activities(limit=90)
    sig = training_load.tss_signature(config)
    daily, missing = training_load.partition_cached_tss(acts, sig)
    computed = training_load.compute_missing_tss(db, missing, config=config) if missing else []
    for c in computed:
        if c["tss"] is not None and c["date"]:
            daily.append((c["date"], c["tss"]))
    if not daily:
        return {"error": "缺少心率或功率数据，无法计算训练负荷"}
    daily_sorted = training_load.daily_tss_from_activities(daily)
    _, _, _, latest = training_load.build_performance_curve(daily_sorted)
    return {
        "latest": latest,
        "week_tss_7d": training_load.recent_week_tss(daily_sorted, days=7),
        "recovery_advice": training_load.recovery_advice(latest["tsb"]) if latest else "无",
    }


def _tool_compare(db, date=None, config=None):
    """活动对比：最近一次 vs 最相似旧活动（里程 ±10% + 同路线验证）。"""
    from . import compare
    acts = db.list_activities(limit=50)
    if len(acts) < 2:
        return {"error": "至少需要两次骑行记录才能做对比"}
    if date:
        new_a = next((a for a in acts if (a.get("start_time") or "")[:10] == date), None)
        if new_a is None:
            return {"error": f"未找到 {date} 的骑行记录"}
        rest = [a for a in acts if a["id"] != new_a["id"]]
    else:
        new_a, rest = acts[0], acts[1:]
    old_b = rest[0]
    dist_a = new_a.get("total_distance_m") or 0
    if dist_a > 0:
        for cand in rest:
            dist_b = cand.get("total_distance_m") or 0
            if dist_b <= 0 or abs(dist_a - dist_b) / max(dist_a, dist_b) > 0.10:
                continue
            if compare.same_route(db.get_records(new_a["id"]), db.get_records(cand["id"])):
                old_b = cand
                break
    result = compare.compare_two(db, new_a, old_b, config)
    out = {"same_route": result.get("same_route"), "note": "非同一路线，对比仅供参考" if not result.get("same_route") else None}
    for side, x in (("a", result["a"]), ("b", result["b"])):
        out[side] = {"name": x.get("name"), "date": x.get("date"),
                     "distance_km": x.get("distance_km"), "avg_speed_kmh": x.get("avg_speed_kmh"),
                     "ascent_m": x.get("ascent_m"), "avg_hr": x.get("avg_hr")}
    out["diffs"] = [{"label": d.get("label"), "delta": d.get("delta"), "unit": d.get("unit"),
                     "direction": d.get("direction"), "improved": d.get("improved")}
                    for d in (result.get("diffs") or [])]
    return out


def _tool_fitness(db, date=None, config=None):
    """体能指标：心速比 / 心率漂移 / 区间分布 / 踏频质量。"""
    from . import fitness
    acts = db.list_activities(limit=20)
    if not acts:
        return {"error": "数据库里还没有骑行记录"}
    act = None
    if date:
        act = next((a for a in acts if (a.get("start_time") or "")[:10] == date), None)
        if act is None:
            return {"error": f"未找到 {date} 的骑行记录"}
    else:
        act = acts[0]
    records = db.get_records(act["id"])
    summary = fitness.fitness_summary(records, max_hr=act.get("max_hr"), config=config)
    out = {"activity": f"{act.get('name')}（{(act.get('start_time') or '')[:10]}）"}
    eff = summary.get("aerobic_efficiency")
    if eff:
        out["aerobic_efficiency"] = {"hr_per_kmh": eff.get("hr_per_kmh"),
                                     "avg_hr": eff.get("avg_hr"), "avg_speed_kmh": eff.get("avg_speed_kmh")}
    drift = summary.get("cardiac_drift")
    if drift:
        out["cardiac_drift"] = {"decoupling_pct": drift.get("decoupling_pct"),
                                "front_hr": drift.get("front_hr"), "back_hr": drift.get("back_hr")}
    zones = summary.get("intensity_distribution")
    if zones:
        out["intensity_zones"] = [{"zone": z.get("zone"), "pct": z.get("pct")} for z in zones]
    cad = summary.get("cadence_quality")
    if cad:
        out["cadence_quality"] = {"avg_cad": cad.get("avg_cad"), "cv_pct": cad.get("cv_pct"),
                                  "climb_avg_cad": cad.get("climb_avg_cad"),
                                  "drop_on_climb": bool(cad.get("drop_on_climb"))}
    if not any(k in out for k in ("aerobic_efficiency", "cardiac_drift", "intensity_zones", "cadence_quality")):
        return {"error": "该活动缺少心率/踏频/速度数据，无法做体能分析"}
    return out


def _tool_gear(db, level=None, vehicle=None):
    """装备台账与保养提醒（可按状态/所属车辆筛选）。"""
    from . import gear
    report = gear.gear_report(db)
    if not report:
        return {"error": "装备台账为空（工具 → 装备管家 可添加）"}
    if vehicle:
        report = [s for s in report if s.get("vehicle") == vehicle]
        if not report:
            return {"error": f"没有所属车辆为「{vehicle}」的装备"}
    if level:
        report = [s for s in report if s["level"] == level]
        if not report:
            return {"error": f"没有状态为 {level} 的装备"}
    return {"count": len(report), "gears": report}


def _exec_action(name, args, ctx):
    """Action 工具：先请求用户确认（on_action 回调），确认后才执行写操作。

    无确认通道（on_action=None）时直接拒绝，保证任何环境下写操作都安全。
    返回给模型的提示：已执行 / 用户取消 / 错误。
    """
    db, config = ctx["db"], ctx["config"]
    if name == "set_ftp":
        w = args.get("w")
        if not w or int(w) <= 0:
            return {"error": "FTP 需为正数（瓦）"}
        action = {
            "type": "set_ftp",
            "description": f"将 FTP（功能阈值功率）设置为 {int(w)} W",
            "apply": lambda: config.set("ftp_w", int(w)),
        }
    elif name == "set_year_goal":
        km = args.get("km")
        if km is None or float(km) < 0:
            return {"error": "年度目标需为非负数（km）"}
        action = {
            "type": "set_year_goal",
            "description": f"将年度里程目标设置为 {float(km)} km（0=关闭）",
            "apply": lambda: config.set("year_goal_km", float(km)),
        }
    elif name == "add_gear":
        gname = (args.get("name") or "").strip()
        gtype = (args.get("type") or "").strip() or "其他"
        exp = int(args.get("expected_km") or 0)
        if not gname:
            return {"error": "装备名称不能为空"}
        today = datetime.date.today().isoformat()
        ts = int(datetime.datetime.now().timestamp())
        action = {
            "type": "add_gear",
            "description": f"添加装备「{gname}」（类型：{gtype}，预期寿命 {exp} km）",
            "apply": lambda: db.gear_add(gname, gtype, today, ts, 0, exp),
        }
    elif name == "set_commute":
        date = (args.get("date") or "").strip()
        flag = bool(args.get("flag", True))
        if not _DATE_ARG_RE.match(date):
            return {"error": "日期格式需为 YYYY-MM-DD"}
        rows = [r for r in db.list_activities(month=date[:7])
                if (r.get("start_time") or "")[:10] == date]
        if not rows:
            return {"error": f"{date} 没有骑行记录"}
        act = rows[0]  # 同日多次取最近一次（list_activities 按 start_ts 倒序）
        action = {
            "type": "set_commute",
            "description": f"把 {date} 的骑行《{act.get('name')}》"
                           f"（{act.get('distance_km')}km）标记为{'通勤' if flag else '训练'}",
            "apply": lambda: db.set_commute(act["id"], flag),
        }
    elif name == "set_vehicle":
        date = (args.get("date") or "").strip()
        vehicle = (args.get("vehicle") or "").strip()
        if not _DATE_ARG_RE.match(date):
            return {"error": "日期格式需为 YYYY-MM-DD"}
        rows = [r for r in db.list_activities(month=date[:7])
                if (r.get("start_time") or "")[:10] == date]
        if not rows:
            return {"error": f"{date} 没有骑行记录"}
        act = rows[0]
        desc = (f"把 {date} 的骑行《{act.get('name')}》标记为骑「{vehicle}」"
                if vehicle else f"清除 {date} 骑行《{act.get('name')}》的车辆标记")
        action = {
            "type": "set_vehicle",
            "description": desc,
            "apply": lambda: db.set_activity_vehicle(act["id"], vehicle),
        }
    else:
        return {"error": f"未知操作: {name}"}
    on_action = ctx.get("on_action")
    if on_action is None:
        return {"error": "该操作需要用户确认，当前环境未提供确认通道，已取消"}
    if not on_action(action):
        return {"result": "用户已取消该操作，未做任何修改"}
    try:
        action["apply"]()
        return {"result": f"已执行：{action['description']}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"执行失败: {e}"}


def _resolve_month_arg(args, ctx):
    """解析模型传入的 month 参数：合法 YYYY-MM 才生效，否则回退会话默认月份。"""
    m = (args.get("month") or "").strip()
    if m and _MONTH_ARG_RE.match(m):
        return m
    return ctx["month"]


def _dispatch(name, args, ctx):
    db = ctx["db"]
    month = _resolve_month_arg(args, ctx)  # 支持模型跨月查询（如「那上个月呢」）
    if name == "get_month_overview":
        return _month_overview(db, month)
    if name == "get_month_activities":
        return _month_activities(db, month, args.get("limit"))
    if name == "get_month_distance_trend":
        return _month_distance_trend(db, month)
    if name == "get_month_hr_summary":
        return _month_hr_summary(db, month)
    if name == "get_month_speed_summary":
        return _month_speed_summary(db, month)
    if name == "get_month_device_summary":
        return _month_device_summary(db, month)
    if name == "get_training_load":
        return _tool_training_load(db, ctx["config"])
    if name == "compare_activities":
        return _tool_compare(db, args.get("date"), ctx["config"])
    if name == "get_fitness_summary":
        return _tool_fitness(db, args.get("date"), ctx["config"])
    if name == "get_gear_status":
        return _tool_gear(db, args.get("level"), args.get("vehicle"))
    if name in ("set_ftp", "set_year_goal", "add_gear", "set_commute", "set_vehicle"):
        return _exec_action(name, args, ctx)
    return {"error": f"未知工具: {name}"}


def _looks_like_unsupported(msg):
    m = (msg or "").lower()
    kw = ["tool", "function calling", "does not support", "not support", "400", "invalid", "unknown parameter", "additional properties"]
    return any(k in m for k in kw)


def build_full_digest(db, month):
    """降级路径：一次性预计算月度摘要。"""
    overview = _month_overview(db, month)
    if "error" in overview:
        return "无月度数据"
    parts = ["## 月度数据摘要", json.dumps(overview, ensure_ascii=False)]
    parts.append("活动列表: " + json.dumps(_month_activities(db, month, limit=30), ensure_ascii=False))
    parts.append("里程趋势: " + json.dumps(_month_distance_trend(db, month), ensure_ascii=False))
    parts.append("心率: " + json.dumps(_month_hr_summary(db, month), ensure_ascii=False))
    parts.append("速度: " + json.dumps(_month_speed_summary(db, month), ensure_ascii=False))
    parts.append("设备: " + json.dumps(_month_device_summary(db, month), ensure_ascii=False))
    return "\n".join(parts)


def append_round(history, question, answer):
    """把一轮问答（user+assistant）追加进会话历史，超出上限丢最旧轮次。

    历史只保留对话精华（不含中间工具调用轮）：模型据此理解指代追问，
    token 可控；调用方保存返回值并在下次请求时回传即可实现多轮会话。
    """
    h = list(history or [])
    h.append({"role": "user", "content": str(question or "")})
    h.append({"role": "assistant", "content": str(answer or "")})
    return h[-MAX_HISTORY_ROUNDS * 2:]


def run_month_query(ai, db, month, config, question, max_rounds=5, history=None, on_event=None, on_action=None):
    """月度自然语言查询入口（支持多轮会话；传 on_event 启用流式输出；传 on_action 启用写操作）。

    history: 既往问答精华（[{role: user|assistant, content}, ...]），
             调用方保存上次返回的 history 并回传即可实现多轮追问。
    on_event: 可选回调 on_event(kind, *args)。传入后走流式请求，事件：
              ("thinking_delta"|"delta", text)  思考/回答逐字增量
              ("round", n)                      第 n 轮工具调用
              ("tool", name, args)              开始调用工具
              ("tool_result", name, ok)         工具执行完成
    on_action: 可选回调 on_action(action) -> bool。Action 工具（set_ftp /
               set_year_goal / add_gear / set_commute / set_vehicle）先调它征求用户确认；返回 True 才执行。
               不传则所有写操作被拒绝（安全默认）。
    返回 {"answer", "thinking", "steps":[{tool,args,ok}], "fallback", "history"}，
    history 为包含本轮问答的完整会话历史。
    """
    ctx = {"db": db, "month": month, "config": config, "on_action": on_action}
    skeleton = f"当前会话默认月份：{month}"
    system = AGENT_SYSTEM + "\n\n## " + skeleton
    messages = [{"role": "system", "content": system}]
    messages.extend(dict(m) for m in (history or []))
    messages.append({"role": "user", "content": question})
    steps = []
    final = None

    def emit(kind, *args_):
        # 事件统一打包为单参数元组（kind, ...args）回调——调用方可以是
        # queue.put / list.append 这类单参数收集器；双参会触发 TypeError
        # 且被下方 except 静默吞掉（曾踩坑：多参回调导致事件全部丢失）。
        if on_event:
            try:
                on_event((kind,) + args_)
            except Exception:
                log.debug("on_event 回调异常", exc_info=True)

    try:
        for round_no in range(1, max_rounds + 1):
            emit("round", round_no)
            if on_event is not None:
                # 流式路径：增量回调透传给调用方，返回结构与非流式完全一致。
                # chat_full_stream 的回调契约是 (kind, text) 双参，此处适配为单参元组
                resp = ai.chat_full_stream(messages, tools=MONTH_TOOLS,
                                           on_event=lambda k, t: emit(k, t))
            else:
                resp = ai.chat_full(messages, tools=MONTH_TOOLS)
            content = resp.get("content") or ""
            tcs = resp.get("tool_calls") or []

            asst = {"role": "assistant", "content": content or ""}
            if tcs:
                asst["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)}}
                    for tc in tcs
                ]
            messages.append(asst)

            if not tcs:
                final = resp
                break

            for tc in tcs:
                name, args = tc["name"], tc.get("arguments") or {}
                emit("tool", name, args)
                try:
                    result = _dispatch(name, args, ctx)
                    ok = "error" not in result
                except Exception as e:  # noqa: BLE001
                    result, ok = {"error": str(e)}, False
                steps.append({"tool": name, "args": args, "ok": ok})
                emit("tool_result", name, ok)
                tool_content = json.dumps(result, ensure_ascii=False, default=str)
                if len(tool_content) > TOOL_RESULT_MAX_CHARS:
                    tool_content = tool_content[:TOOL_RESULT_MAX_CHARS] + "\n…（结果过长已截断）"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_content,
                })
        else:
            answer_fallback = ai.chat(messages)
            emit("delta", answer_fallback)  # 轮数耗尽兜底：一次性流出
            final = {"content": answer_fallback, "reasoning": "", "tool_calls": []}
    except ai_client.AIError as e:
        if _looks_like_unsupported(str(e)):
            digest = build_full_digest(db, month)
            answer = ai.chat([
                {"role": "system", "content": AGENT_SYSTEM + "\n\n" + digest},
                {"role": "user", "content": question},
            ])
            emit("delta", answer)
            return {"answer": answer, "thinking": "", "steps": steps, "fallback": True,
                    "history": append_round(history, question, answer)}
        raise

    if final is None:
        final = {"content": "", "reasoning": ""}
    answer = final.get("content") or ""
    return {
        "answer": answer,
        "thinking": final.get("reasoning") or "",
        "steps": steps,
        "fallback": False,
        "history": append_round(history, question, answer),
    }
