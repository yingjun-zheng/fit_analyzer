"""周报生成单测：近 7 天统计 / 上周对比 / TSS 窗口 / 入库去重 / 降级模板 / 到点判断。"""
import datetime
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db as db_mod
from core.config import Config
from core import weekly_report
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
    sig = training_load.tss_signature({})
    st = f"{date} 08:00:00"
    ts = int(datetime.datetime.strptime(date, "%Y-%m-%d").timestamp())
    db.conn.execute(
        "INSERT INTO activities (file_hash, file_name, name, device, sport,"
        " start_time, start_ts, total_distance_m, avg_speed_ms, avg_hr,"
        " record_count, imported_at, month, tss, tss_method, tss_sig)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (fh, f"{fh}.fit", f"骑行{fh}", "iGPSPORT", "cycling", st, ts,
         dist_km * 1000.0, 7.0, 145.0, 10, "2026-09-01 00:00:00", date[:7],
         tss, "hr" if tss else None, sig if tss else None))
    db.conn.commit()


class FakeAI:
    def __init__(self, answer):
        self.answer = answer

    def chat(self, messages, **kw):
        self.messages = messages
        return self.answer


def main():
    tmp = Path(tempfile.mkdtemp(prefix="fit_week_"))
    try:
        db = db_mod.DB(tmp / "t.db")
        cfg = Config(tmp / "cfg.json")
        today = datetime.date(2026, 9, 16)  # 周三

        # 近 7 天（09-10~09-16）：3 次骑行 50/40/30km，TSS 120/100/80
        insert_activity(db, "w1", "2026-09-11", 50, 120)
        insert_activity(db, "w2", "2026-09-13", 40, 100)
        insert_activity(db, "w3", "2026-09-16", 30, 80)
        # 上周（09-03~09-09）：2 次 20/15km
        insert_activity(db, "w4", "2026-09-04", 20, 50)
        insert_activity(db, "w5", "2026-09-06", 15, 40)

        print("== 周报数据统计 ==")
        data = weekly_report.build_weekly_data(db, cfg, today=today)
        t, l = data["this_week"], data["last_week"]
        check("本周 3 次骑行", t["count"] == 3, str(t))
        check("本周里程 120km", t["distance_km"] == 120.0, str(t["distance_km"]))
        check("上周 2 次 / 35km", l["count"] == 2 and l["distance_km"] == 35.0)
        check("本周 TSS 300", data["tss_this_7d"] == 300.0, str(data["tss_this_7d"]))
        check("上周 TSS 90", data["tss_last_7d"] == 90.0, str(data["tss_last_7d"]))
        check("三指标快照存在", data["latest"] is not None and "tsb" in data["latest"])

        print("== 无 AI 降级模板 ==")
        text, _ = weekly_report.generate_weekly_report(None, db, cfg, today=today)
        check("模板含关键数字", "3 次" in text and "120" in text and "上周" in text, text[:100])

        print("== AI 生成 ==")
        fake = FakeAI("本周训练量适中，建议下周安排一次恢复性骑行。")
        text_ai, _ = weekly_report.generate_weekly_report(fake, db, cfg, today=today)
        check("AI 周报生效", text_ai == fake.answer)
        check("AI prompt 含本周数据", any("120" in (m.get("content") or "") for m in fake.messages))

        print("== 入库与去重 ==")
        note1, _ = weekly_report.store_weekly_report(db, cfg, ai=None, today=today)
        note2, _ = weekly_report.store_weekly_report(db, cfg, ai=None, today=today)
        check("首次入库返回通知", note1 is not None and note1["kind"] == "weekly")
        check("同窗口重复触发不再入库", note2 is None)
        weekly = [n for n in db.list_notifications() if n["kind"] == "weekly"]
        check("周报仅存一条", len(weekly) == 1)

        print("== 到点判断 ==")
        cfg.set("weekly_report_enabled", True)
        cfg.set("weekly_report_weekday", "周三")
        cfg.set("weekly_report_time", "21:00")
        at = datetime.datetime(2026, 9, 16, 21, 30)
        check("今天周三到点", weekly_report.due_for_weekly_report(cfg, today=today, now=at))
        check("未到时间不触发", not weekly_report.due_for_weekly_report(
            cfg, today=today, now=datetime.datetime(2026, 9, 16, 20, 59)))
        cfg.set("weekly_report_weekday", "周四")
        check("星期不符不触发", not weekly_report.due_for_weekly_report(cfg, today=today, now=at))
        cfg.set("weekly_report_weekday", "周三")
        cfg.set("weekly_report_enabled", False)
        check("总开关关闭不触发", not weekly_report.due_for_weekly_report(cfg, today=today, now=at))

        print("== 空数据安全 ==")
        db2 = db_mod.DB(tmp / "empty.db")
        note_none, _ = weekly_report.store_weekly_report(db2, cfg, ai=None)
        check("空库返回 None", note_none is None)
        db2.close()
        db.close()

        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
