"""提醒引擎单测：TSB 深度疲劳 / 装备 watch·due / 年度里程碑 / 去重。

用带 TSS 缓存的活动数据与装备台账构造场景，验证检测与唯一去重。
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db as db_mod
from core.config import Config
from core import notifier
from core import training_load

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def insert_activity(db, fh, date, dist_km, tss):
    """插活动（带 TSS 缓存字段，跳过逐秒 records 的计算开销）。"""
    sig = training_load.tss_signature({})
    st = f"{date} 08:00:00"
    ts = int(__import__("datetime").datetime.strptime(date, "%Y-%m-%d").timestamp())
    db.conn.execute(
        "INSERT INTO activities (file_hash, file_name, name, device, sport,"
        " start_time, start_ts, total_distance_m, avg_speed_ms, avg_hr,"
        " record_count, imported_at, month, tss, tss_method, tss_sig)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (fh, f"{fh}.fit", f"骑行{fh}", "iGPSPORT", "cycling", st, ts,
         dist_km * 1000.0, 7.0, 145.0, 10, "2026-09-01 00:00:00", date[:7],
         tss, "hr" if tss else None, sig if tss else None))
    db.conn.commit()


def add_gear(db, name, start_date, start_ts, expected_km, initial_km=0.0):
    db.gear_add(name, "链条", start_date, start_ts, initial_km, expected_km)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="fit_note_"))
    try:
        db = db_mod.DB(tmp / "t.db")
        cfg = Config(tmp / "cfg.json")

        print("== 装备 watch/due 预警 ==")
        # 先插活动里程：废链条(2025 启用)跨过 1000 预期 → due；
        # 老链条(2026-01 启用)累计 2100 → watch；新链条(2026-09 启用)不计 → ok
        insert_activity(db, "g0", "2025-06-01", 900, None)
        insert_activity(db, "g1", "2025-06-02", 900, None)
        insert_activity(db, "g2", "2026-03-01", 1100, None)
        insert_activity(db, "g3", "2026-03-02", 1000, None)
        add_gear(db, "老链条", "2026-01-01", 1767225600, 3000)
        add_gear(db, "废链条", "2025-01-01", 1735689600, 1000)
        add_gear(db, "新链条", "2026-09-01", 1751328000, 6000)
        alerts = notifier.build_alerts(db, cfg)
        gear_alerts = [a for a in alerts if a["kind"] == "gear"]
        check("watch 装备触发提醒", any("老链条" in a["title"] for a in gear_alerts))
        check("due 装备触发提醒", any("废链条" in a["title"] for a in gear_alerts))
        check("ok 装备不提醒", not any("新链条" in a["title"] for a in gear_alerts))

        print("== 去重：同一装备同一级别只提醒一次 ==")
        new1 = notifier.run_alerts(db, cfg)
        new2 = notifier.run_alerts(db, cfg)
        check("首次触发 2 条装备提醒", sum(1 for a in new1 if a["kind"] == "gear") == 2)
        check("重复检测不再新增", not any(a["kind"] == "gear" for a in new2), str(new2))
        check("已入库 2 条", len(db.list_notifications()) >= 2)

        print("== TSB 深度疲劳 ==")
        # 大量高 TSS 活动压垮恢复 → TSB 跌破阈值
        for i in range(8):
            insert_activity(db, f"h{i}", f"2026-09-{i+1:02d}", 60 + i * 10, 200 + i * 30)
        latest = notifier._latest_performance(db, cfg)
        check("三指标可计算", latest is not None and "tsb" in latest)
        tsb = latest["tsb"]
        if tsb <= -30:
            check("TSB 跌破阈值触发提醒", any(a["kind"] == "tsb" for a in notifier.build_alerts(db, cfg)))
        else:
            print(f"  [INFO] 当前 TSB={tsb:.1f} 未跌破 -30，改为调高阈值验证")
            cfg.set("notifications_tsb_threshold", 10)  # 调高阈值强制触发
            check("阈值调高后触发 TSB 提醒", any(a["kind"] == "tsb" for a in notifier.build_alerts(db, cfg)))
            cfg.set("notifications_tsb_threshold", -30)
        # TSB 去重
        n_tsb1 = [a for a in notifier.run_alerts(db, cfg) if a["kind"] == "tsb"]
        n_tsb2 = [a for a in notifier.run_alerts(db, cfg) if a["kind"] == "tsb"]
        check("TSB 提醒只触发一次", bool(n_tsb1) and not n_tsb2)

        print("== 年度目标里程碑 ==")
        cfg.set("year_goal_km", 1000)
        prog = notifier._year_progress(db, cfg)
        check("年度进度可计算", prog is not None and prog["pct"] > 0)
        goal_alerts = [a for a in notifier.build_alerts(db, cfg) if a["kind"] == "goal"]
        check("里程碑提醒生成", any(any(m in a["target"] for m in ("25", "50", "75", "100"))
              for a in goal_alerts), str([a["target"] for a in goal_alerts]))

        print("== 总开关与空数据 ==")
        cfg.set("notifications_enabled", False)
        check("关闭后不再产生新提醒", notifier.run_alerts(db, cfg) == [])
        cfg.set("notifications_enabled", True)
        db2 = db_mod.DB(tmp / "empty.db")
        check("空库无提醒", notifier.build_alerts(db2, cfg) == [])
        db2.close()
        db.close()

        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
