"""自然语言查询 Agent：把「单次 LLM 调用」升级为「LLM 选工具 → 本地执行 → 回灌 → 再决策」的多轮链路。

设计要点（对应 AI Agent 学习路线 Week 7 工具调用原型）：
- 模型只看到一份极小的「活动概览骨架」，真实数字必须通过调用工具获取 → 强制模型做工具选择（planning + tool use）。
- 所有重计算都在本地（analysis.py）完成，工具返回的是聚合统计而非原始逐秒数据 → 上下文保持很小。
- 多轮循环（ReAct 风格）：模型可连续调用多个工具，最后基于结果作答；超出轮数则强制收尾。
- 若后端模型不支持工具调用（报错），自动降级为「预计算全量摘要 + 单次问答」，保证可用。
"""
import json
import logging

from . import ai_client, analysis

log = logging.getLogger("fit.nlquery")

AGENT_SYSTEM = """你是骑行数据分析助手，通过调用工具来回答用户关于「单次骑行活动」的问题。
规则：
1. 必须先调用合适的工具获取真实数据，再基于数据回答；不要编造未查询到的数字。
2. 一个问题可以连续调用多个工具（例如先看整体概览，再看心率区间与每公里速度）。
3. 工具返回的是聚合统计，不是原始逐秒数据；如需某公里/某圈细节，调用对应工具并传入参数。
4. 数据缺失的维度（如没有心率/温度/轨迹）不要强行分析，直接说明「无该数据」。
5. 用简洁中文回答，给出具体数值与单位；涉及对比时引用工具返回的具体数字。"""


# ---------------- 工具定义（OpenAI function-calling 格式） ----------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_activity_summary",
            "description": "获取本次骑行的整体概览统计：距离、用时、均速/最大速度、卡路里、爬升/下降、设备，以及是否存在心率/踏频/温度/功率/轨迹数据。适合先了解活动全貌。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_speed_zones",
            "description": "速度区间分布（按时间加权，单位 km/h）：返回各区间的时长(秒)与占比(%)。可选 boundaries_kmh 自定义区间上边界。",
            "parameters": {
                "type": "object",
                "properties": {
                    "boundaries_kmh": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "速度区间上边界，单位 km/h，例如 [10,15,20,25,30,35]。省略则用用户默认设置。",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_heart_rate_zones",
            "description": "心率区间分布（按最大心率百分比分 5 区）：返回各 Z 区时长与占比(%)。可选 max_hr(整数 bpm)，省略则用心率数据内最大值。",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_hr": {
                        "type": "integer",
                        "description": "最大心率 bpm；省略用数据内最大值",
                    },
                    "pcts": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "区间边界百分比，例如 [0.6,0.7,0.8,0.9]",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cadence_zones",
            "description": "踏频区间分布（rpm）：返回各区间时长(秒)与占比(%)。可选 boundaries_rpm 自定义上边界。",
            "parameters": {
                "type": "object",
                "properties": {
                    "boundaries_rpm": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "踏频区间上边界 rpm，例如 [60,70,80,90,100]",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_per_km_stats",
            "description": "按每公里分桶统计：每公里用时、均速、最大速度、平均心率、平均踏频、平均海拔。可选 km(整数)只看某一公里；省略返回全部公里摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "km": {
                        "type": "integer",
                        "description": "要看的具体公里序号(从 0 开始)；省略返回全部公里摘要(超 60 公里时仅含统计与首尾)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_temperature_stats",
            "description": "设备温度统计：是否有温度数据、最小/最大/平均温度(°C)。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_track_summary",
            "description": "轨迹摘要：轨迹点数、起终点经纬度、海拔范围、总上升/下降(米)、移动时间(秒)。适合评估路线起伏。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lap_summary",
            "description": "记圈摘要：每圈的用时、距离、均速、平均/最大心率、平均踏频、爬升/下降。适合分析分段表现。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


# ---------------- 工具本地实现 ----------------
def _activity_summary(act):
    out = {
        "name": act.get("name"),
        "start_time": act.get("start_time"),
        "sport": act.get("sport") or "骑行",
        "device": act.get("device") or "未知",
        "distance_km": act.get("distance_km"),
        "timer_min": round((act.get("timer_s") or 0) / 60, 1),
        "avg_speed_kmh": act.get("avg_speed_kmh"),
        "max_speed_kmh": act.get("max_speed_kmh"),
        "ascent_m": round(act.get("ascent_m") or 0),
        "descent_m": round(act.get("descent_m") or 0),
        "calories": round(act.get("calories") or 0),
        "record_count": act.get("record_count"),
        "has_hr": bool(act.get("has_hr")),
        "has_cad": bool(act.get("has_cad")),
    }
    if act.get("has_hr"):
        out["avg_hr"] = round(act["avg_hr"]) if act.get("avg_hr") else None
        out["max_hr"] = round(act["max_hr"]) if act.get("max_hr") else None
    if act.get("has_cad"):
        out["avg_cad"] = round(act["avg_cad"]) if act.get("avg_cad") else None
    return out


def _dispatch(name, args, ctx):
    """执行一个工具调用，返回可 JSON 序列化的结果 dict。"""
    act, records, config, laps = ctx["act"], ctx["records"], ctx["config"], ctx.get("laps") or []
    if name == "get_activity_summary":
        return _activity_summary(act)

    if name == "get_speed_zones":
        b = args.get("boundaries_kmh") or config.get("speed_zone_kmh")
        return analysis.speed_zones(records, b)

    if name == "get_heart_rate_zones":
        hr_max = args.get("max_hr") or config.get("hr_max_override") or act.get("max_hr")
        pcts = args.get("pcts") or config.get("hr_zone_pcts")
        if not hr_max:
            return {"error": "无心率数据"}
        return analysis.hr_zones(records, hr_max, pcts)

    if name == "get_cadence_zones":
        b = args.get("boundaries_rpm") or config.get("cadence_zone_rpm")
        return analysis.cadence_zones(records, b)

    if name == "get_per_km_stats":
        rows = analysis.per_km(records)
        km = args.get("km")
        if km is not None:
            for r in rows:
                if r["km"] == km:
                    return r
            return {"error": f"无第 {km} 公里数据（共 {len(rows)} 公里）"}
        if len(rows) <= 60:
            return {"km_count": len(rows), "rows": rows}
        # 长里程：返回统计 + 首尾片段，避免上下文爆炸
        speeds = [r["avg_speed_kmh"] for r in rows if r.get("avg_speed_kmh") is not None]
        return {
            "km_count": len(rows),
            "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "max_speed_kmh": round(max(speeds), 1) if speeds else None,
            "min_speed_kmh": round(min(speeds), 1) if speeds else None,
            "head": rows[:8],
            "tail": rows[-8:],
            "note": "里程过长，仅展示前 8 与后 8 公里；可传入 km 参数查询特定公里",
        }

    if name == "get_temperature_stats":
        return analysis.temp_stats(records)

    if name == "get_track_summary":
        track = analysis.track_points(records, config.get("track_max_points"))
        alts = [r["alt_m"] for r in records if r.get("alt_m") is not None]
        latlons = [(r["lat"], r["lon"]) for r in records if r.get("lat") is not None and r.get("lon") is not None]
        moving = analysis.moving_time(records)
        return {
            "track_points": len(track),
            "has_track": bool(latlons),
            "start": list(latlons[0]) if latlons else None,
            "end": list(latlons[-1]) if latlons else None,
            "alt_min_m": round(min(alts), 1) if alts else None,
            "alt_max_m": round(max(alts), 1) if alts else None,
            "moving_time_s": round(moving, 1),
            "total_distance_km": act.get("distance_km"),
        }

    if name == "get_lap_summary":
        if not laps:
            return {"error": "无记圈数据"}
        out = []
        for l in laps[:50]:
            out.append({
                "lap": l.get("lap_index"),
                "timer_s": round(l.get("timer_s") or 0, 1),
                "distance_km": l.get("distance_km"),
                "avg_speed_kmh": l.get("avg_speed_kmh"),
                "avg_hr": round(l["avg_hr"]) if l.get("avg_hr") is not None else None,
                "max_hr": round(l["max_hr"]) if l.get("max_hr") is not None else None,
                "avg_cad": round(l["avg_cad"]) if l.get("avg_cad") is not None else None,
                "ascent_m": round(l.get("ascent_m") or 0),
                "descent_m": round(l.get("descent_m") or 0),
            })
        return {"lap_count": len(out), "laps": out}

    return {"error": f"未知工具: {name}"}


def _looks_like_unsupported(msg):
    m = (msg or "").lower()
    kw = ["tool", "function calling", "does not support", "not support", "400", "invalid", "unknown parameter", "additional properties"]
    return any(k in m for k in kw)


def build_full_digest(ctx):
    """降级路径用：一次性预计算所有统计，拼成文本交给模型单次回答。"""
    parts = ["## 数据摘要"]
    parts.append("活动概览: " + json.dumps(_dispatch("get_activity_summary", {}, ctx), ensure_ascii=False))
    act = ctx["act"]
    if act.get("has_hr"):
        parts.append("心率区间: " + json.dumps(_dispatch("get_heart_rate_zones", {}, ctx), ensure_ascii=False))
    if act.get("has_cad"):
        parts.append("踏频区间: " + json.dumps(_dispatch("get_cadence_zones", {}, ctx), ensure_ascii=False))
    parts.append("速度区间: " + json.dumps(_dispatch("get_speed_zones", {}, ctx), ensure_ascii=False))
    parts.append("每公里: " + json.dumps(_dispatch("get_per_km_stats", {}, ctx), ensure_ascii=False))
    parts.append("轨迹: " + json.dumps(_dispatch("get_track_summary", {}, ctx), ensure_ascii=False))
    if any(r.get("temp") is not None for r in ctx["records"]):
        parts.append("温度: " + json.dumps(_dispatch("get_temperature_stats", {}, ctx), ensure_ascii=False))
    if ctx.get("laps"):
        parts.append("记圈: " + json.dumps(_dispatch("get_lap_summary", {}, ctx), ensure_ascii=False))
    return "\n".join(parts)


def run_nl_query(ai, act, records, config, question, laps=None, max_rounds=5):
    """自然语言查询主入口。

    返回 {"answer", "thinking", "steps":[{tool,args,ok}], "fallback":bool}。
    ai: AIClient 实例；act/records/config/laps: 来自 db 的本次活动数据。
    """
    ctx = {"act": act, "records": records, "config": config, "laps": laps or []}

    # 极小的活动概览骨架：强制模型通过工具取真实数字
    has_temp = any(r.get("temp") is not None for r in records)
    has_power = any(r.get("power") is not None for r in records)
    has_track = any(r.get("lat") is not None and r.get("lon") is not None for r in records)
    skeleton = (
        f"活动：{act.get('name')}（{act.get('start_time')}）\n"
        f"距离：{act.get('distance_km')} km，用时：{round((act.get('timer_s') or 0) / 60)} 分钟\n"
        f"传感器可用性：心率={'有' if act.get('has_hr') else '无'}，踏频={'有' if act.get('has_cad') else '无'}，"
        f"温度={'有' if has_temp else '无'}，功率={'有' if has_power else '无'}，轨迹={'有' if has_track else '无'}"
    )
    system = AGENT_SYSTEM + "\n\n## 当前活动概览\n" + skeleton

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    steps = []
    final = None

    try:
        for _ in range(max_rounds):
            resp = ai.chat_full(messages, tools=TOOLS)
            content = resp.get("content") or ""
            tcs = resp.get("tool_calls") or []

            # 回写 assistant 消息（含 tool_calls，供下一轮 context）
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
            # 超过 max_rounds 仍在调用工具 → 强制收尾（不再带 tools）
            final = {"content": ai.chat(messages), "reasoning": "", "tool_calls": []}
    except ai_client.AIError as e:
        # 后端不支持工具调用 → 降级为预计算摘要 + 单次问答
        if _looks_like_unsupported(str(e)):
            digest = build_full_digest(ctx)
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
