"""AI 运动数据分析：把活动/月度统计整理成摘要文本，交给 AI 分析。"""
import logging

from . import ai_client

log = logging.getLogger("fit.aianalysis")

ACTIVITY_SYSTEM = """你是专业的骑行运动数据分析教练。根据给出的活动统计数据，输出一段 200-350 字的中文分析报告，
包含：1) 本次骑行整体评价；2) 强度与节奏分析（心率区间/速度分布）；3) 发现的问题或亮点；
4) 1-3 条针对性的训练建议。不要编造数据中没有的信息，数据缺失的项目不要强行分析。
请先简短思考（不超过 200 字），然后直接给出结论，不要长篇推理。"""

MONTH_SYSTEM = """你是骑行训练数据分析师。根据给出的月度汇总数据，输出一段 200-300 字的中文月度训练总结，
包含：训练量评价、强度结构、规律性、下月训练建议。只依据给出的数据，不要编造。
请先简短思考（不超过 200 字），然后直接给出结论，不要长篇推理。"""


def _kmh(ms):
    return round((ms or 0) * 3.6, 1)


def activity_summary_text(act, zones):
    s = act
    lines = [
        f"活动: {s.get('name')}  设备: {s.get('device') or '未知'}",
        f"开始时间: {s.get('start_time')}  运动类型: {s.get('sport') or '骑行'}",
        f"距离: {s.get('distance_km')} km  用时(计时): {round((s.get('timer_s') or 0)/60)} 分钟",
        f"平均速度: {_kmh(s.get('avg_speed_ms'))} km/h  最大速度: {_kmh(s.get('max_speed_ms'))} km/h",
        f"累计爬升: {round(s.get('ascent_m') or 0)} m  累计下降: {round(s.get('descent_m') or 0)} m",
        f"卡路里: {round(s.get('calories') or 0)} kcal",
    ]
    if s.get("avg_hr"):
        lines.append(f"心率: 平均 {round(s['avg_hr'])} / 最大 {round(s.get('max_hr') or 0)} bpm")
    if s.get("avg_cad"):
        lines.append(f"踏频: 平均 {round(s['avg_cad'])} / 最大 {round(s.get('max_cad') or 0)} rpm")
    if s.get("avg_temp"):
        lines.append(f"温度: 平均 {s['avg_temp']}°C / 最大 {s.get('max_temp')}°C")
    if zones:
        lines.append("区间占比:")
        for z in zones:
            lines.append(f"  - {z['label']}: {z['pct']}%")
    return "\n".join(lines)


def month_summary_text(m):
    return "\n".join([
        f"月份: {m['month']}",
        f"骑行次数: {m['count']}",
        f"总里程: {m['distance_km']} km",
        f"总用时: {m['hours']} 小时",
        f"总爬升: {m['ascent_m']} m",
        f"总消耗: {m['calories']} kcal",
        f"平均配速(按里程/时间): {m['avg_speed_kmh']} km/h",
    ])


def _ai_result(raw):
    """把 chat_full 返回的 {"content","reasoning"} 整理为 {"answer","thinking"}。"""
    content = (raw.get("content") or "").strip()
    reasoning = (raw.get("reasoning") or "").strip()
    if not content:
        # 推理被 max_tokens 截断时 content 可能为空，用思考兜底
        content = reasoning
        reasoning = ""
    return {"answer": content, "thinking": reasoning}


def analyze_activity(act, zones, ai):
    text = activity_summary_text(act, zones)
    raw = ai.chat_full([
        {"role": "system", "content": ACTIVITY_SYSTEM},
        {"role": "user", "content": f"请分析以下骑行活动数据：\n{text}"},
    ])
    return _ai_result(raw)


def analyze_month(m, ai):
    text = month_summary_text(m)
    raw = ai.chat_full([
        {"role": "system", "content": MONTH_SYSTEM},
        {"role": "user", "content": f"请总结以下月度训练数据：\n{text}"},
    ])
    return _ai_result(raw)
