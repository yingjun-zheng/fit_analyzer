"""周报生成：确定性统计（近 7 天 vs 前 7 天 + 训练负荷三指标）+ LLM 教练解读。

流程：
1. build_weekly_data：从 DB 计算近 7 天与上周的里程/次数/TSS/爬升/心率对比
   与最新 CTL/ATL/TSB 快照（复用训练负荷缓存链路）。
2. generate_weekly_report：有 AI 配置时用 LLM 教练语气生成；
   未配置 AI 时降级为确定性模板文本（不依赖网络）。
3. store_weekly_report：写入 notifications（target=week:<周一日期> 天然去重），
   返回通知 dict 供 UI 弹气泡与注入 AI 会话历史。
"""
import datetime
import json
import logging

from . import training_load

log = logging.getLogger("fit.weekly")

WEEK_DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _daily_tss(db, config):
    """按日期排序的日 TSS 列表；无数据返回 None。"""
    acts = db.list_activities(limit=90)
    sig = training_load.tss_signature(config)
    daily, missing = training_load.partition_cached_tss(acts, sig)
    computed = training_load.compute_missing_tss(db, missing, config=config) if missing else []
    for c in computed:
        if c["tss"] is not None and c["date"]:
            daily.append((c["date"], c["tss"]))
    if not daily:
        return None
    return training_load.daily_tss_from_activities(daily)


def _summarize(rows):
    """活动行列表 → 汇总统计。"""
    if not rows:
        return {"count": 0, "distance_km": 0.0, "ascent_m": 0, "hr_avg": None, "tss": 0}
    dist = sum(r.get("total_distance_m") or 0 for r in rows) / 1000.0
    ascent = sum(r.get("ascent_m") or 0 for r in rows)
    hrs = [r.get("avg_hr") for r in rows if r.get("avg_hr")]
    tss = sum(r.get("tss") or 0 for r in rows)
    return {"count": len(rows), "distance_km": round(dist, 1),
            "ascent_m": round(ascent), "hr_avg": round(sum(hrs) / len(hrs)) if hrs else None,
            "tss": round(tss, 1)}


def _week_window(today):
    """近 7 天窗口（含今天）与上周窗口（前 7 天）。返回 (this_start, last_start, this_days, last_days)。"""
    dates = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(14)]
    this_days = set(dates[:7])
    last_days = set(dates[7:])
    return dates[6], dates[13], this_days, last_days


def build_weekly_data(db, config, today=None):
    """周报确定性数据。today: datetime.date；默认今天。"""
    today = today or datetime.date.today()
    this_start, last_start, this_days, last_days = _week_window(today)
    rows = db.list_activities(limit=500)
    this_rows = [r for r in rows if (r.get("start_time") or "")[:10] in this_days]
    last_rows = [r for r in rows if (r.get("start_time") or "")[:10] in last_days]
    this_sum = _summarize(this_rows)
    last_sum = _summarize(last_rows)
    daily = _daily_tss(db, config)
    latest = None
    if daily:
        _, _, _, latest = training_load.build_performance_curve(daily)
    return {
        "window": {"this_start": this_start, "last_start": last_start},
        "this_week": this_sum,
        "last_week": last_sum,
        "tss_this_7d": round(sum(v for d, v in (daily or []) if d in this_days), 1),
        "tss_last_7d": round(sum(v for d, v in (daily or []) if d in last_days), 1),
        "latest": latest,
    }


def _diff_text(this, last, key, unit, better_high=True):
    """本周 vs 上周差异文案。"""
    v1, v2 = this.get(key) or 0, last.get(key) or 0
    if last.get("count") == 0:
        return f"本周{key_cn(key)}{v1}{unit}（上周无骑行记录）"
    delta = v1 - v2
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    return f"本周{key_cn(key)}{v1}{unit}（{arrow}{abs(delta):.0f} vs 上周）"


def key_cn(key):
    return {"count": "骑行", "distance_km": "里程", "ascent_m": "爬升",
            "hr_avg": "平均心率", "tss": "训练量(TSS)"}.get(key, key)


def _template_report(data):
    """无 AI 时的确定性周报文本。"""
    t, l, latest = data["this_week"], data["last_week"], data["latest"]
    lines = [
        "【本周训练周报】",
        f"骑行 {t['count']} 次，共 {t['distance_km']} km"
        f"（上周 {l['count']} 次 / {l['distance_km']} km）",
        f"总爬升 {t['ascent_m']} m；本周 TSS {data['tss_this_7d']}（上周 {data['tss_last_7d']}）",
    ]
    if t["hr_avg"]:
        lines.append(f"平均心率 {t['hr_avg']} bpm")
    if latest and latest.get("tsb") is not None:
        lines.append(f"当前状态：CTL {latest['ctl']:.0f} / ATL {latest['atl']:.0f} / "
                     f"TSB {latest['tsb']:.0f}（{training_load.recovery_advice(latest['tsb'])}）")
    if t["count"] == 0:
        lines.append("本周没有骑行记录，下周可以安排恢复性或轻松有氧训练。")
    return "\n".join(lines)


_REPORT_SYSTEM = (
    "你是骑行训练教练。根据本周训练数据生成一份简洁中文周报（150~250 字）：\n"
    "1) 本周训练量概述（次数/里程/与上周对比）；\n"
    "2) 训练负荷与疲劳状态（CTL/ATL/TSB 解读）；\n"
    "3) 下周训练建议（具体可执行）。\n"
    "不用 Markdown 标题，语气像私人教练。"
)


def generate_weekly_report(ai, db, config, today=None):
    """生成周报文本；返回 (text, data)。ai 可为 None（降级模板）。"""
    data = build_weekly_data(db, config, today=today)
    if data["this_week"]["count"] == 0 and data["last_week"]["count"] == 0:
        return "近两周没有骑行记录，暂无周报内容。", data
    if ai is None:
        return _template_report(data), data
    try:
        t, l, latest = data["this_week"], data["last_week"], data["latest"]
        ctx = (f"本周（{data['window']['this_start']} 起 7 天）：骑行 {t['count']} 次，"
               f"{t['distance_km']} km，爬升 {t['ascent_m']} m，"
               f"TSS {data['tss_this_7d']}。"
               f"上周：{l['count']} 次，{l['distance_km']} km，TSS {data['tss_last_7d']}。")
        if t["hr_avg"]:
            ctx += f" 本周平均心率 {t['hr_avg']} bpm。"
        if latest:
            ctx += (f" 当前 CTL {latest['ctl']:.0f} / ATL {latest['atl']:.0f} / "
                    f"TSB {latest['tsb']:.0f}。")
        answer = ai.chat([
            {"role": "system", "content": _REPORT_SYSTEM},
            {"role": "user", "content": ctx},
        ], max_tokens=1200, reasoning_effort="low")
        return (answer or _template_report(data)).strip(), data
    except Exception as e:  # noqa: BLE001
        log.warning("AI 周报生成失败，降级模板：%s", e)
        return _template_report(data), data


def store_weekly_report(db, config, ai=None, today=None):
    """生成并入库周报；返回 (notification_dict | None, data)。

    去重：target=week:<窗口起始日> 唯一——同一窗口只会入库一次，
    定时器重复触发不会重复生成提醒（AI 调用也会跳过）。
    """
    today = today or datetime.date.today()
    this_start, *_ = _week_window(today)
    data = build_weekly_data(db, config, today=today)
    if data["this_week"]["count"] == 0 and data["last_week"]["count"] == 0:
        return None, data
    text = generate_weekly_report(ai, db, config, today=today)[0]
    inserted = db.insert_notification(
        "weekly", f"week:{this_start}", "📊 本周训练周报", text)
    if not inserted:
        return None, data
    log.info("周报已生成并入库存档（窗口 %s）", this_start)
    # 5.5：配置了 Webhook 时同步推送周报到群机器人
    try:
        from . import notify_channels
        notify_channels.push_text(config, "📊 本周训练周报", text)
    except Exception:  # noqa: BLE001
        log.exception("Webhook 推送周报异常")
    return {"kind": "weekly", "title": "📊 本周训练周报", "body": text}, data


def due_for_weekly_report(config, today=None, now=None):
    """判断当前是否到周报时间点（配置的星期 + 时间）。now 可注入（测试用）。"""
    if not config.get("weekly_report_enabled"):
        return False
    today = today or datetime.date.today()
    weekday_cn = WEEK_DAYS[today.weekday()]  # 周一=0
    if weekday_cn != config.get("weekly_report_weekday"):
        return False
    t = str(config.get("weekly_report_time") or "").strip()
    if len(t) != 5 or ":" not in t:
        return False
    try:
        hh, mm = int(t.split(":")[0]), int(t.split(":")[1])
    except ValueError:
        return False
    now = now or datetime.datetime.now()
    return now.hour >= hh and now.minute >= mm
