"""提醒引擎：阈值预警检测（确定性规则，零 AI 依赖）。

检测项（每次导入新数据 / 每日首次打开时调用 run_alerts）：
- TSB 深度疲劳：CTL/ATL/TSB 最新 TSB <= 阈值（默认 -30）→ 建议休息
- 装备保养：进入 watch(70%) / due(100%) 时提醒（两级各一次）
- 年度目标里程碑：达成 25/50/75/100% 时提醒

去重：notifications 表 (kind, target) 唯一键——同类目标只提醒一次，
装备保养归零/阈值调整后 target 变化会重新触发。
"""
import datetime
import logging

from . import gear as gear_mod
from . import training_load

log = logging.getLogger("fit.notifier")


def _daily_tss(db, config):
    """按日期排序的日 TSS 列表（复用训练负荷缓存与补算链路）；无数据返回 None。"""
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


def _latest_performance(db, config):
    """最新 CTL/ATL/TSB 快照；无数据返回 None。"""
    daily_sorted = _daily_tss(db, config)
    if not daily_sorted:
        return None
    _, _, _, latest = training_load.build_performance_curve(daily_sorted)
    return latest


def _year_progress(db, config):
    """年度里程完成度：{km, goal_km, pct}；目标未启用返回 None。"""
    goal = float(config.get("year_goal_km") or 0)
    if goal <= 0:
        return None
    year = str(datetime.date.today().year)
    rows = db.list_activities(limit=100000)
    km = sum((r.get("total_distance_m") or 0) for r in rows
             if (r.get("start_time") or "").startswith(year)) / 1000.0
    return {"km": km, "goal_km": goal, "pct": km / goal * 100.0}


def _fmt_tsb_body(latest, week_tss):
    advice = training_load.recovery_advice(latest["tsb"]) if latest else "—"
    return (f"当前 TSB {latest['tsb']:.0f}（CTL {latest['ctl']:.0f} / ATL {latest['atl']:.0f}），"
            f"近 7 天训练量 {week_tss} TSS。{advice}")


def build_alerts(db, config):
    """计算所有待触发提醒；返回 [{kind, target, title, body}]（未去重）。"""
    out = []

    # 1) TSB 深度疲劳
    threshold = float(config.get("notifications_tsb_threshold") or -30)
    latest = _latest_performance(db, config)
    if latest and latest.get("tsb") is not None and latest["tsb"] <= threshold:
        daily_sorted = _daily_tss(db, config)
        week_tss = training_load.recent_week_tss(daily_sorted, days=7) if daily_sorted else 0
        out.append({
            "kind": "tsb",
            "target": "tsb",
            "title": "⚠️ 训练深度疲劳",
            "body": _fmt_tsb_body(latest, week_tss),
        })

    # 2) 装备保养 watch / due
    for s in gear_mod.gear_report(db):
        if s["level"] in ("watch", "due") and not s["retired"]:
            level_cn = {"watch": "接近寿命，留意磨损", "due": "已到寿命，建议更换"}[s["level"]]
            out.append({
                "kind": "gear",
                "target": f"gear:{s['id']}:{s['level']}",
                "title": f"🔧 装备提醒：{s['name']}",
                "body": f"{s['advice']}（{level_cn}）",
            })

    # 3) 年度目标里程碑（25/50/75/100% 各触发一次；超过 100% 视为达成 100%）
    prog = _year_progress(db, config)
    if prog and prog["pct"] >= 25:
        milestone = min(int(prog["pct"] // 25 * 25), 100)
        out.append({
            "kind": "goal",
            "target": f"goal:{milestone}",
            "title": f"🎯 年度目标 {milestone}%",
            "body": (f"今年已骑 {prog['km']:.0f} km / {prog['goal_km']:.0f} km"
                     f"（{prog['pct']:.0f}%），达成 {milestone}% 里程碑！"),
        })
    return out


def run_alerts(db, config):
    """检测并入库新提醒；返回本次新触发的提醒列表（供 UI 弹出气泡）。

    重复检测安全：同一 (kind, target) 只会入库一次（INSERT OR IGNORE）。
    """
    if not config.get("notifications_enabled"):
        return []
    new_alerts = []
    for a in build_alerts(db, config):
        if db.insert_notification(a["kind"], a["target"], a["title"], a["body"]):
            a["id"] = None
            new_alerts.append(a)
    if new_alerts:
        log.info("提醒引擎：新增 %d 条提醒 %s",
                 len(new_alerts), [a["kind"] for a in new_alerts])
    return new_alerts
