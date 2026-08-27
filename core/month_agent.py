"""月度骑行数据查询 Agent：用工具调用回答关于「某月训练」的问题。

设计要点：
- 不读取逐秒 records，只从 DB 做聚合/列表查询 → 响应快、上下文小。
- 模型只看到月份名称与活动数量等最小骨架，真实统计通过工具获取。
- 多轮 ReAct：模型可连续调用多个工具，最后基于结果作答。
- 若后端不支持工具调用，自动降级为「预计算月度摘要 + 单次问答」。
"""
import json
import logging

from . import ai_client

log = logging.getLogger("fit.monthagent")

AGENT_SYSTEM = """你是月度骑行训练分析助手，通过调用工具来回答用户关于「某月训练」的问题。
规则：
1. 必须先调用合适的工具获取真实数据，再基于数据回答；不要编造未查询到的数字。
2. 可以连续调用多个工具（例如先看月度概览，再看活动列表与趋势）。
3. 工具返回聚合数据，不是每次骑行的逐秒数据；如需单活动细节，引导用户切换到该活动再问。
4. 数据缺失的维度不要强行分析，直接说明「无该数据」。
5. 用简洁中文回答，给出具体数值与单位；涉及对比时引用工具返回的具体数字。"""


MONTH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_month_overview",
            "description": "获取指定月份的整体训练概览：骑行次数、总里程(km)、总用时(小时)、总爬升(m)、总消耗(kcal)、平均速度(km/h)。",
            "parameters": {
                "type": "object",
                "properties": {},
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
                "properties": {},
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
                "properties": {},
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
                "properties": {},
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
                "properties": {},
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
    return {
        "month": month,
        "count": len(rows),
        "distance_km": round(total_dist / 1000, 1),
        "hours": round(total_time / 3600, 1),
        "ascent_m": round(total_ascent),
        "calories": round(total_cal),
        "avg_speed_kmh": round(_safe_avg([s * 3.6 for s in speeds]), 1) if speeds else None,
        "weighted_avg_speed_kmh": round(weighted_speed, 1) if weighted_speed else None,
    }


def _month_activities(db, month, limit=None):
    rows = db.list_activities(month=month)
    if not rows:
        return {"error": "该月无活动数据"}
    out = []
    for r in rows[:limit] if limit else rows:
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
        })
    return {"count": len(rows), "shown": len(out), "activities": out}


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


def _dispatch(name, args, ctx):
    db, month = ctx["db"], ctx["month"]
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


def run_month_query(ai, db, month, config, question, max_rounds=5):
    """月度自然语言查询入口。

    返回 {"answer", "thinking", "steps":[{tool,args,ok}], "fallback":bool}。
    """
    ctx = {"db": db, "month": month, "config": config}
    skeleton = f"当前查询范围：月份 {month}"
    system = AGENT_SYSTEM + "\n\n## " + skeleton
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    steps = []
    final = None

    try:
        for _ in range(max_rounds):
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
                try:
                    result = _dispatch(name, args, ctx)
                    ok = "error" not in result
                except Exception as e:  # noqa: BLE001
                    result, ok = {"error": str(e)}, False
                steps.append({"tool": name, "args": args, "ok": ok})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        else:
            final = {"content": ai.chat(messages), "reasoning": "", "tool_calls": []}
    except ai_client.AIError as e:
        if _looks_like_unsupported(str(e)):
            digest = build_full_digest(db, month)
            answer = ai.chat([
                {"role": "system", "content": AGENT_SYSTEM + "\n\n" + digest},
                {"role": "user", "content": question},
            ])
            return {"answer": answer, "thinking": "", "steps": steps, "fallback": True}
        raise

    if final is None:
        final = {"content": "", "reasoning": ""}
    return {
        "answer": final.get("content") or "",
        "thinking": final.get("reasoning") or "",
        "steps": steps,
        "fallback": False,
    }
