"""复盘 Agent 单元测试：compare / training_load / review_agent 意图路由与派发。

覆盖：
- compare.compare_two 对比 + same_route 同路线识别
- compare.period_trend / week_trend 趋势
- training_load 的 TSS/NP/IF 计算与 HR/无数据降级
- training_load 的 CTL/ATL/TSB 曲线与恢复建议
- review_agent 的规则意图分类 + 派发（用 mock AI，不依赖真实 LLM）

运行：python tests/test_review_agent.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import analysis, fit_parser, logging_setup
from core.config import Config
from core import compare, db as db_mod, training_load, review_agent

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def _find_fit_dir():
    for cand in (Path(r"F:\byciclefits"), Path(r"C:\Users\zhengyingjun\Documents\deepseek\fittestdata")):
        if cand.exists() and any(cand.glob("*.fit")):
            return cand
    return None


def _build_db(fit_dir):
    files = sorted(fit_dir.glob("*.fit"))
    tmp = Path(tempfile.mkdtemp(prefix="review_test_"))
    logging_setup.setup_logging(tmp, console=False)
    cfg = Config(tmp / "config.json")
    cfg.set("ftp_w", 200)  # 设个 FTP 方便功率 TSS 测试
    db = db_mod.DB(tmp / "fit.db")
    results, errors = fit_parser.parse_many(files)
    for r in results:
        db.upsert_activity(r["data"])
    return cfg, db, len(results), len(errors)


def test_training_load(cfg, db):
    print("== training_load ==")
    acts = db.list_activities()
    any_tss = False
    seen_methods = set()
    for act in acts:
        records = db.get_records(act["id"])
        # 关键：这里不补功率，直接测真实分支——真实码表无功率计，应走心率 hrTSS
        tss, method, np_w, avg_w, intensity = training_load.compute_activity_tss(
            records, config=cfg, ftp=cfg.get("ftp_w"), max_hr=act.get("max_hr") or None)
        if tss is not None:
            any_tss = True
            seen_methods.add(method)
    check("至少一次活动能算出 TSS", any_tss)
    check("真实无功率计数据走 hr 路径（不用估功率）", "hr" in seen_methods and "power" not in seen_methods,
          f"methods={seen_methods}")

    # NP 数学正确性（构造已知序列）
    fake = [{"power": 200.0} for _ in range(60)]  # 恒定 200W
    np_val, avg = training_load.normalized_power(fake)
    check("恒定功率 NP≈平均功率", np_val is not None and avg is not None and abs(np_val - avg) < 0.5,
          f"np={np_val} avg={avg}")

    # 有真实功率 + FTP → power 路径
    fake_power = [{"t": i, "power": 200.0} for i in range(3600)]  # 1 小时恒定 200W
    tss, method, *_ = training_load.compute_activity_tss(fake_power, config=cfg, ftp=200, max_hr=None)
    check("真实功率+FTP 走 power 路径且 TSS≈100", method == "power" and tss is not None and abs(tss - 100) < 20,
          f"tss={tss} method={method}")

    # 无功率无心率 → 返回 None
    r = training_load.compute_activity_tss([{"t": 0}, {"t": 1}], config=cfg, ftp=200, max_hr=None)
    check("无功率无心率 TSS=None", r[0] is None)

    # 恢复建议
    check("深度疲劳建议", "疲劳" in training_load.recovery_advice(-35))
    check("状态佳建议", "状态良好" in training_load.recovery_advice(15))


def test_compare(cfg, db):
    print("== compare ==")
    acts = db.list_activities(limit=50)
    check("有至少 2 条活动可对比", len(acts) >= 2, f"只有 {len(acts)} 条")
    if len(acts) >= 2:
        r = compare.compare_two(db, acts[0], acts[1], cfg)
        check("对比返回结构", "diffs" in r and "same_route" in r and "a" in r and "b" in r)
        check("对比字段非空", len(r["diffs"]) > 0)

    trend = compare.period_trend(db, months_back=4)
    check("月度趋势返回", isinstance(trend, list))
    week = compare.week_trend(db, days_back=14)
    check("日趋势返回", isinstance(week, list))


def test_intent_routing():
    print("== review_agent 意图分类 ==")
    check("负荷意图", review_agent._rule_intent("这周该不该休息") == "load")
    check("对比意图", review_agent._rule_intent("和上次比有没有进步") == "compare")
    check("周期意图", review_agent._rule_intent("复盘这周") == "period")
    check("单次意图", review_agent._rule_intent("这次骑得怎么样") == "single")
    check("体能意图", review_agent._rule_intent("我体能进步了吗") == "fitness")
    check("效率意图", review_agent._rule_intent("有氧效率怎么样") == "fitness")
    check("未知兜底", review_agent._rule_intent("你好") is None)


def test_fitness(cfg, db):
    print("== fitness（体能/训练质量）==")
    from core import fitness
    acts = db.list_activities()
    act = acts[0]
    records = db.get_records(act["id"])
    s = fitness.fitness_summary(records, max_hr=act.get("max_hr"), config=cfg)
    check("有氧效率可计算", s["aerobic_efficiency"] is not None)
    check("踏频质量可计算", s["cadence_quality"] is not None)
    # 心率漂移可能为 None（取决于时长），强度分布应有值
    check("强度分布返回", s["intensity_distribution"] is not None)

    # 单项函数的基础正确性
    eff = s["aerobic_efficiency"]
    check("心速比数值合理", eff and 0 < eff["hr_per_kmh"] < 30, f"hr_per_kmh={eff and eff['hr_per_kmh']}")
    cad = s["cadence_quality"]
    check("踏频存在且合理", cad and 30 < cad["avg_cad"] < 150, f"avg_cad={cad and cad['avg_cad']}")


class _MockAI:
    def __init__(self):
        self.calls = []
        self.reply = "mock 回复"

    def chat(self, messages, model=None, temperature=None, timeout=None, max_tokens=None, reasoning_effort=None):
        self.calls.append(messages)
        return self.reply

    def chat_full(self, messages, tools=None, max_tokens=None, reasoning_effort=None, **kw):
        self.calls.append(messages)
        # 不发起工具调用，直接返回内容（让单次/周期链路走"无工具调用→直接作答"分支）
        return {"content": self.reply, "reasoning": "", "tool_calls": []}


def test_dispatch(cfg, db):
    print("== review_agent 派发（mock AI）==")
    ai = _MockAI()
    # 对比复盘（纯本地 + 单次 LLM）
    r = review_agent.run_review(ai, db, cfg, "和上次比有没有进步")
    check("对比复盘返回 answer", r["intent"] == "compare" and "answer" in r, str(r.get("intent")))
    # 负荷复盘
    r2 = review_agent.run_review(ai, db, cfg, "这周该不该休息")
    check("负荷复盘返回 answer", r2["intent"] == "load" and "answer" in r2, str(r2.get("intent")))
    # 周期复盘
    r3 = review_agent.run_review(ai, db, cfg, "复盘这个月")
    check("周期复盘返回 answer", r3["intent"] == "period" and "answer" in r3, str(r3.get("intent")))
    # 体能复盘
    r4 = review_agent.run_review(ai, db, cfg, "我体能进步了吗")
    check("体能复盘返回 answer", r4["intent"] == "fitness" and "answer" in r4, str(r4.get("intent")))


def test_current_activity(cfg, db):
    print("== review_agent current_activity 上下文 ==")
    # 用 mock 替换 nl_query.run_nl_query，捕获传入的 act
    captured = {}
    orig_nl = review_agent.nl_query.run_nl_query

    def fake_nl(ai, act, records, config, question, laps=None, max_rounds=5):
        captured["act"] = act
        return {"answer": "mock", "intent": "single", "activity": act.get("name"), "steps": []}

    review_agent.nl_query.run_nl_query = fake_nl
    try:
        ai = _MockAI()
        acts = db.list_activities()
        # 指定最早的一条活动（非最新）
        target = acts[-1]  # list_activities 默认按 start_ts 降序，最后一条是最早
        r = review_agent.run_review(ai, db, cfg, "这次心率怎么样", current_activity=target)
        check("single 意图针对指定活动", captured.get("act") and captured["act"]["id"] == target["id"],
              f"期望 {target['id']} 实际 {captured.get('act', {}).get('id')}")
        check("返回活动名正确", r.get("activity") == target.get("name"))
    finally:
        review_agent.nl_query.run_nl_query = orig_nl


def main():
    fit_dir = _find_fit_dir()
    if fit_dir is None:
        print("!! 未找到 FIT 测试数据")
        return 1
    cfg, db, n_parsed, n_err = _build_db(fit_dir)
    print(f"真实 FIT：解析 {n_parsed} 成功 / {n_err} 失败（来自 {fit_dir}）")
    check("解析成功数 > 0", n_parsed > 0)

    test_training_load(cfg, db)
    test_compare(cfg, db)
    test_fitness(cfg, db)
    test_intent_routing()
    test_dispatch(cfg, db)
    test_current_activity(cfg, db)

    print(f"\n结果: {PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
