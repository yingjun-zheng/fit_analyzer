"""骑行复盘 Agent 编排层：意图路由 + 派发到各子链路。

这是「复盘」区别于「被动查询」的入口。用户一句话（如「帮我复盘上周」），
本模块判断意图后路由到：
- single  单次复盘   -> nl_query.run_nl_query（复用现有 8 工具 ReAct）
- period  周期复盘   -> month_agent.run_month_query（复用现有 6 工具 ReAct）
- compare 对比复盘   -> compare.compare_two / period_trend + LLM 解读（新增）
- load    训练负荷   -> training_load 三指标 + LLM 解读（新增）

意图分类：先用关键词规则（快、稳、零成本），规则命中不了再让 LLM 判断。
"""
import datetime
import json
import logging
import re

from . import ai_client
from . import month_agent
from . import nl_query

log = logging.getLogger("fit.review")

# 意图关键词（按优先级，先命中先赢）
_INTENT_RULES = [
    ("load", ["训练负荷", "疲劳", "该不该骑", "休息", "恢复", "tsb", "tss", "状态怎么样"]),
    ("fitness", ["体能", "有氧效率", "心速", "心率漂移", "有氧能力", "耐力", "踏频", "效率"]),
    ("compare", ["进步", "对比", "比较", "又骑", "重骑", "退步", "上次", "上回", "这条路线", "和之前"]),
    ("period", ["这周", "上周", "本周", "这个月", "上月", "上个月", "月度", "周训练", "这月", "复盘这周", "复盘这个月"]),
    ("single", ["这次", "这条", "这段", "复盘", "分析一下", "骑得怎么样", "表现"]),
]


def _rule_intent(question):
    q = (question or "").lower()
    for intent, kws in _INTENT_RULES:
        for kw in kws:
            if kw in q:
                return intent
    return None


def _llm_intent(ai, question):
    """规则未命中时，用 LLM 判断意图（单次 LLM 调用，返回 JSON）。"""
    prompt = (
        "判断以下骑行相关问题的意图，只能返回一个 JSON：{\"intent\": \"single|period|compare|load|fitness\"}。\n"
        "single=针对单次骑行的分析；period=针对某周/某月的整体复盘；"
        "compare=对比两次骑行或看进步退步；load=询问训练负荷/疲劳/恢复；"
        "fitness=询问体能/有氧效率/心率漂移/踏频等技术指标。\n"
        f"\n问题：{question}"
    )
    raw = ai.chat([
        {"role": "system", "content": "你是意图分类器，只输出 JSON，不要解释。"},
        {"role": "user", "content": prompt},
    ], temperature=0.0, max_tokens=50)
    m = re.search(r"\{[^{}]*\"intent\"[^{}]*\}", raw or "")
    if m:
        try:
            obj = json.loads(m.group(0))
            if obj.get("intent") in ("single", "period", "compare", "load", "fitness"):
                return obj["intent"]
        except Exception:
            pass
    return "single"  # 兜底


def classify_intent(question, ai=None):
    intent = _rule_intent(question)
    if intent:
        return intent, True  # rule-based
    if ai:
        return _llm_intent(ai, question), False
    return "single", True


def _recent_activity(db):
    acts = db.list_activities(limit=1)
    return acts[0] if acts else None


def _current_month():
    return datetime.date.today().strftime("%Y-%m")


def _resolve_month(question):
    """从问题里解析目标月份（YYYY-MM）。

    优先级：
    1. 明确的 YYYY-MM（如「2026年8月」「2026-08」）。
    2. 相对时间词转月（「上周」「最近」等 → 数据里最近有活动的月份）。
    3. 兜底当前月。
    """
    m = re.search(r"(\d{4})[年/\-](\d{1,2})", question or "")
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    # 相对时间词（上周/最近/近段时间）不指向具体月份，交给调用方按数据回退
    if re.search(r"上周|最近|近几天|这几天|前阵|这段时间", question or ""):
        return None
    return _current_month()


def _latest_month_with_data(db):
    """返回数据库里最近有活动的月份（YYYY-MM）；无数据返回 None。"""
    months = db.months()
    return months[0]["month"] if months else None


def _run_single(ai, db, config, question, current_activity=None):
    act = current_activity or _recent_activity(db)
    if not act:
        return {"intent": "single", "answer": "数据库里还没有骑行记录，请先导入 FIT 文件。"}
    records = db.get_records(act["id"])
    laps = db.get_laps(act["id"])
    r = nl_query.run_nl_query(ai, act, records, config, question, laps=laps)
    r["intent"] = "single"
    r["activity"] = act.get("name")
    return r


def _run_fitness(ai, db, config, question, current_activity=None):
    """体能/训练质量分析：心速比、心率漂移、心率区间、踏频质量 + LLM 解读。"""
    from . import fitness
    act = current_activity or _recent_activity(db)
    if not act:
        return {"intent": "fitness", "answer": "数据库里还没有骑行记录，请先导入 FIT 文件。"}
    records = db.get_records(act["id"])
    summary = fitness.fitness_summary(records, max_hr=act.get("max_hr"), config=config)

    # 组织成给 LLM 的文本
    lines = [f"以下是骑行（{act.get('name')}，{act.get('distance_km')}km）的体能/训练质量分析：", ""]
    eff = summary["aerobic_efficiency"]
    if eff:
        lines.append(f"心速比（有氧效率）：{eff['hr_per_kmh']} bpm/(km/h)"
                     f"（平均心率 {eff['avg_hr']}bpm，均速 {eff['avg_speed_kmh']}km/h），越低越高效")
    drift = summary["cardiac_drift"]
    if drift:
        lines.append(f"心率漂移（有氧解耦）：{drift['decoupling_pct']}%"
                     f"（正值 = 后程效率下降，耐力不足），"
                     f"前半 {drift['front_hr']}bpm/{drift['front_speed_kmh']}km/h → "
                     f"后半 {drift['back_hr']}bpm/{drift['back_speed_kmh']}km/h")
    dist = summary["intensity_distribution"]
    if dist:
        zz = "，".join(f"{d['zone']} {d['pct']}%" for d in dist)
        lines.append(f"心率区间分布：{zz}")
    cad = summary["cadence_quality"]
    if cad:
        lines.append(f"踏频质量：平均 {cad['avg_cad']}rpm（中位 {cad.get('median_cad')}），"
                     f"变异系数 {cad['cv_pct']}%"
                     + (f"，爬坡段 {cad['climb_avg_cad']}rpm（偏低，注意爬坡控制）"
                        if cad.get("drop_on_climb") else ""))
    if not any([eff, drift, dist, cad]):
        return {"intent": "fitness", "answer": "本次骑行缺少心率/踏频/速度数据，无法做体能分析。"}

    lines.append("")
    lines.append("请作为骑行教练用中文解读：① 有氧效率如何；② 心率漂移是否提示耐力不足；"
                 "③ 训练强度结构是否合理；④ 踏频控制建议。给出具体可执行的改进方向。不用 Markdown 标题。")
    nl = "\n"
    answer = ai.chat([
        {"role": "system", "content": "你是专业骑行教练，基于体能指标给出中文分析。不用 Markdown 标题。"},
        {"role": "user", "content": f"{question}\n\n{nl.join(lines)}"},
    ], max_tokens=1200, reasoning_effort="low")
    return {"intent": "fitness", "answer": answer, "fitness": summary}


def _run_period(ai, db, config, question, current_activity=None):
    month = _resolve_month(question)
    if month is None:
        # 相对时间词（上周/最近等）→ 用数据里最近有活动的月份
        month = _latest_month_with_data(db)
        if month is None:
            return {"intent": "period", "answer": "数据库里还没有骑行记录，请先导入 FIT 文件。"}
    r = month_agent.run_month_query(ai, db, month, config, question)
    r["intent"] = "period"
    r["month"] = month
    return r


def _run_compare(ai, db, config, question, current_activity=None):
    from . import compare
    acts = db.list_activities(limit=50)
    if len(acts) < 2:
        return {"intent": "compare", "answer": "至少需要两次骑行记录才能做对比复盘。"}
    # 找最相似的两条（优先同路线且日期相邻）
    new_a, old_b = acts[0], acts[1]
    result = compare.compare_two(db, new_a, old_b, config)
    # 组织成给 LLM 的结构化文本
    lines = ["以下是对比复盘的数据（A 为较新，B 为较旧）：", ""]
    lines.append(f"是否同路线：{'是' if result['same_route'] else '否（线路不同，对比仅供参考）'}")
    a, b = result["a"], result["b"]
    lines.append(f"A：{a['name']}（{a['date']}）距离 {a['distance_km']}km 均速 {a['avg_speed_kmh']}km/h"
                 f"爬升 {a['ascent_m']}m{' 心率 ' + str(a['avg_hr']) + 'bpm' if a['avg_hr'] else ''}")
    lines.append(f"B：{b['name']}（{b['date']}）距离 {b['distance_km']}km 均速 {b['avg_speed_kmh']}km/h"
                 f"爬升 {b['ascent_m']}m{' 心率 ' + str(b['avg_hr']) + 'bpm' if b['avg_hr'] else ''}")
    lines.append("")
    for d in result["diffs"]:
        arrow = "▲" if d["direction"] == "上升" else "▼"
        verdict = "（改善）" if d["improved"] else "（退步/需关注）"
        lines.append(f"- {d['label']}：{arrow} {d['delta']}{d['unit']} {verdict}")
    system = ("你是骑行教练，根据对比数据用中文点评进步/退步、分析原因（训练/天气/路线差异），"
              "并给出下一步建议。不要用 Markdown 标题。")
    nl = "\n"
    answer = ai.chat([
        {"role": "system", "content": system},
        {"role": "user", "content": f"{question}\n\n{nl.join(lines)}"},
    ], max_tokens=1500, reasoning_effort="low")
    return {"intent": "compare", "answer": answer, "compare": result}


def _run_load(ai, db, config, question, current_activity=None):
    from . import training_load
    acts = db.list_activities(limit=90)  # 近几十条，覆盖数周
    ftp = config.get("ftp_w") or None
    max_hr_override = config.get("hr_max_override") or None
    daily = []
    meta = []
    for act in acts:
        records = db.get_records(act["id"])
        # 单次最大心率（无 override 时）
        mhr = max_hr_override
        if not mhr:
            hrs = [r.get("hr") for r in records if r.get("hr") is not None]
            mhr = max(hrs) if hrs else act.get("max_hr")
        # compute_activity_tss 内部自行判断：有真实功率计 + FTP → 功率 TSS；
        # 否则有心率 → hrTSS。注意：不能用估算功率算 TSS（误差过大），
        # 因此这里不调 estimate_power。
        tss, method, np_w, avg_w, intensity = training_load.compute_activity_tss(
            records, config=config, ftp=ftp, max_hr=mhr)
        d = (act.get("start_time") or "")[:10]
        if tss is not None:
            daily.append((d, tss))
        meta.append({"date": d, "tss": tss, "method": method})
    if not daily:
        return {"intent": "load", "answer": "缺少心率和功率数据，无法计算训练负荷。"}
    daily_sorted = training_load.daily_tss_from_activities(daily)
    _, _, _, latest = training_load.build_performance_curve(daily_sorted)
    # 最近 7 个自然日的 TSS 合计（周训练量，不是「最后 7 条记录」）
    week_tss = training_load.recent_week_tss(daily_sorted, days=7)
    advice = training_load.recovery_advice(latest["tsb"]) if latest else "无"
    lines = [
        "以下是训练负荷分析（基于 TSS）：",
        f"当前状态快照：CTL={latest.get('ctl') if latest else '—'}，"
        f"ATL={latest.get('atl') if latest else '—'}，TSB={latest.get('tsb') if latest else '—'}",
        f"近 7 天累计 TSS：{week_tss}",
        f"恢复建议：{advice}",
        "",
        "请作为教练用中文解读负荷趋势、判断是否训练过度/恢复不足，并给出接下来一周的具体安排。",
    ]
    system = "你是骑行训练教练，结合训练负荷三指标（CTL体能/ATL疲劳/TSB状态）给出中文建议。不用 Markdown 标题。"
    nl = "\n"
    answer = ai.chat([
        {"role": "system", "content": system},
        {"role": "user", "content": f"{question}\n\n{nl.join(lines)}"},
    ], max_tokens=1500, reasoning_effort="low")
    return {"intent": "load", "answer": answer, "load": {
        "latest": latest, "week_tss": week_tss, "advice": advice}}


_DISPATCH = {
    "single": _run_single,
    "period": _run_period,
    "compare": _run_compare,
    "load": _run_load,
    "fitness": _run_fitness,
}


def run_review(ai, db, config, question, current_activity=None):
    """复盘主入口。

    返回 dict: {intent, answer, ...附加数据}。
    ai: AIClient；db: DB；config: Config；question: 用户问题。
    current_activity: 可选，当前选中的活动 dict（GUI 场景传入，优先于数据库最新活动）；
                      用于 single/fitness 等针对单条活动的意图。
    """
    intent, _ = classify_intent(question, ai=ai)
    log.info("复盘意图: %s (%s)", intent, question)
    return _DISPATCH[intent](ai, db, config, question, current_activity=current_activity)
