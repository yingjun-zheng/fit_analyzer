"""Agent 工具扩容单测：训练负荷 / 活动对比 / 体能 / 装备台账 四个专项工具。

验证确定性计算链路（与复盘 Agent 同口径）可作为工具被 Agent 调用，
且复合问题可连续调用多个工具。
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db as db_mod
from core.month_agent import run_month_query, _tool_training_load, _tool_compare, _tool_fitness, _tool_gear, _exec_action

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def make_db(path):
    """构造带心率/踏频记录的两次活动 + 两条装备 + 一条带 TSS 缓存的活动。"""
    from core import training_load
    db = db_mod.DB(path)
    conn = db.conn
    # 两次活动（带 records：hr/cad/speed）
    acts = [
        ("h-new", "2026-09-20 08:00:00", 1758328800, 50000.0),
        ("h-old", "2026-09-05 08:00:00", 1757034600, 48000.0),
        ("h-load", "2026-09-10 08:00:00", 1757462400, 20000.0),
    ]
    sig = training_load.tss_signature({})
    for h, st, ts, dist in acts:
        tss = 60.0 if h == "h-load" else None
        conn.execute(
            "INSERT INTO activities (file_hash, file_name, name, device, sport,"
            " start_time, start_ts, total_distance_m, avg_speed_ms, avg_hr, max_hr,"
            " ascent_m, calories, record_count, imported_at, month, tss, tss_method, tss_sig)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (h, f"{h}.fit", f"骑行-{h}", "iGPSPORT", "cycling", st, ts, dist, 7.0, 145.0, 180.0,
             300.0, 500.0, 60, "2026-09-15 00:00:00", st[:7], tss,
             "hr" if tss else None, sig if tss else None))
    aid_new = conn.execute("SELECT id FROM activities WHERE file_hash='h-new'").fetchone()["id"]
    aid_old = conn.execute("SELECT id FROM activities WHERE file_hash='h-old'").fetchone()["id"]
    for aid, base_speed in ((aid_new, 7.0), (aid_old, 6.5)):
        for t in range(0, 600, 10):
            hr = 140 + (t // 120) * 5
            conn.execute(
                "INSERT INTO records (activity_id, t, lat, lon, dist_m, speed_ms, hr, cad, alt_m, temp)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (aid, t, 30.0 + t * 1e-5, 120.0 + t * 1e-5, t * base_speed, base_speed, hr, 82, 50.0, 25.0))
    # 两条装备：一条 watch（近寿命），一条 ok
    conn.execute(
        "INSERT INTO gear (name, type, start_date, start_ts, expected_km) VALUES (?,?,?,?,?)",
        ("公路车-链条", "链条", "2026-01-01", 1735689600, 3000))
    conn.execute(
        "INSERT INTO gear (name, type, start_date, start_ts, expected_km) VALUES (?,?,?,?,?)",
        ("公路车-外胎", "外胎", "2026-09-01", 1751328000, 6000))
    conn.commit()
    return db


class FakeAI:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def _pop(self):
        self.calls += 1
        return self.script.pop(0)

    def chat_full(self, messages, tools=None, **kw):
        return self._pop()

    def chat_full_stream(self, messages, tools=None, on_event=None, **kw):
        return self._pop()

    def chat(self, messages, **kw):
        return "ok"


def main():
    tmp = Path(tempfile.mkdtemp(prefix="fit_tools_"))
    try:
        db = make_db(tmp / "t.db")

        print("== 训练负荷（TSS 缓存路径）==")
        r = _tool_training_load(db, {})
        check("返回最新三指标", isinstance(r.get("latest"), dict)
              and "ctl" in r["latest"] and "tsb" in r["latest"], str(r)[:120])
        check("返回近 7 天 TSS 与恢复建议", "week_tss_7d" in r and "recovery_advice" in r)

        print("== 活动对比 ==")
        r = _tool_compare(db, config={})
        check("返回 a/b/diffs 结构", "a" in r and "b" in r and "diffs" in r and "same_route" in r)
        check("A 是较新活动", r["a"]["date"] == "2026-09-20", str(r.get("a")))
        check("指定不存在日期报错", "error" in _tool_compare(db, date="2020-01-01"))

        print("== 体能指标 ==")
        r = _tool_fitness(db, config={})
        check("返回至少一项体能指标", any(k in r for k in
              ("aerobic_efficiency", "cardiac_drift", "intensity_zones", "cadence_quality")), str(r)[:150])
        check("指定不存在日期报错", "error" in _tool_fitness(db, date="2020-01-01", config={}))

        print("== 装备台账 ==")
        r = _tool_gear(db)
        check("返回装备列表", r.get("count", 0) >= 1 and len(r.get("gears") or []) >= 1)
        r_watch = _tool_gear(db, level="watch")
        check("按状态筛选", all(g["level"] == "watch" for g in r_watch.get("gears") or []))
        r_bad = _tool_gear(db, level="due")
        check("无该状态装备时报错", "error" in r_bad)

        print("== 复合问题：连续调用多个工具 ==")
        fake = FakeAI([
            {"content": "", "reasoning": "", "tool_calls": [
                {"id": "t1", "name": "get_month_overview", "arguments": {"month": "2026-09"}},
                {"id": "t2", "name": "get_training_load", "arguments": {}}]},
            {"content": "9月骑了3次共118km，负荷适中可以继续骑", "reasoning": "", "tool_calls": []},
        ])
        r = run_month_query(fake, db, "2026-09", {}, "这个月练得怎样？我该不该休息？")
        check("两个工具都执行成功", len(r["steps"]) == 2 and all(s["ok"] for s in r["steps"]),
              str(r["steps"]))
        check("工具名正确", {s["tool"] for s in r["steps"]} == {"get_month_overview", "get_training_load"})

        print("== Action 工具（写操作确认机制）==")
        from core.config import Config
        cfg = Config(tmp / "cfg.json")

        r = _exec_action("set_ftp", {"w": 250}, {"db": db, "config": cfg, "on_action": None})
        check("无确认通道时拒绝写操作", "error" in r and "确认" in r["error"], str(r))
        r = _exec_action("set_ftp", {"w": 250}, {"db": db, "config": cfg, "on_action": lambda a: True})
        check("确认后执行 FTP 写入", "已执行" in r.get("result", ""), str(r))
        check("config.ftp_w 已更新", cfg.get("ftp_w") == 250)
        cfg.set("ftp_w", 200)
        r = _exec_action("set_ftp", {"w": 999}, {"db": db, "config": cfg, "on_action": lambda a: False})
        check("用户取消后不修改", "取消" in r.get("result", "") and cfg.get("ftp_w") == 200, str(r))
        r = _exec_action("set_ftp", {"w": -5}, {"db": db, "config": cfg, "on_action": lambda a: True})
        check("非法参数被拒绝", "error" in r, str(r))
        r = _exec_action("add_gear", {"name": "测试-链条", "type": "链条", "expected_km": 3000},
                         {"db": db, "config": cfg, "on_action": lambda a: True})
        check("确认后添加装备", "已执行" in r.get("result", ""), str(r))
        check("装备已入库", any(g["name"] == "测试-链条" for g in db.gear_list()))
        r = _exec_action("set_year_goal", {"km": 5000}, {"db": db, "config": cfg, "on_action": lambda a: True})
        check("确认后设置年度目标", "已执行" in r.get("result", "") and cfg.get("year_goal_km") == 5000.0)

        print("== Agent 复合：Action 工具进入步骤链路 ==")
        fake = FakeAI([
            {"content": "我来帮你设置 FTP", "reasoning": "", "tool_calls": [
                {"id": "a1", "name": "set_ftp", "arguments": {"w": 250}}]},
            {"content": "FTP 已设置为 250W", "reasoning": "", "tool_calls": []},
        ])
        r = run_month_query(fake, db, "2026-09", cfg, "帮我设置FTP为250", on_action=lambda a: True)
        check("Action 步骤执行成功", len(r["steps"]) == 1 and r["steps"][0]["ok"] is True,
              str(r["steps"]))
        check("Agent 链路后 config 已更新", cfg.get("ftp_w") == 250)
        db.close()

        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
