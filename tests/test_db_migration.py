"""数据库迁移回归测试：旧库（无 month 列）升级路径 + 新库直接建库路径。

背景：month 物化列引入时，索引曾放在 _SCHEMA 中先于迁移执行，
旧库启动直接报 sqlite3.OperationalError: no such column: month。
本测试用贴近历史版本的旧 schema 建库后由新 DB 类打开，防止回归。
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db as db_mod

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


# 历史版本 schema（引入 month 物化列之前）：无 month 列、无设备识别/TSS 列
_OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash TEXT UNIQUE NOT NULL,
    file_name TEXT,
    name TEXT,
    device TEXT,
    sport TEXT,
    start_time TEXT,
    start_ts INTEGER,
    total_distance_m REAL,
    timer_s REAL,
    elapsed_s REAL,
    moving_s REAL,
    avg_speed_ms REAL,
    max_speed_ms REAL,
    avg_hr REAL, max_hr REAL, min_hr REAL,
    avg_cad REAL, max_cad REAL,
    calories REAL,
    ascent_m REAL, descent_m REAL,
    avg_alt_m REAL, max_alt_m REAL, min_alt_m REAL,
    avg_temp REAL, max_temp REAL, min_temp REAL,
    lat REAL, lon REAL,
    record_count INTEGER,
    imported_at TEXT
);
CREATE TABLE IF NOT EXISTS laps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    lap_index INTEGER, start_time TEXT, end_time TEXT,
    timer_s REAL, distance_m REAL
);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    t REAL, lat REAL, lon REAL, dist_m REAL,
    speed_ms REAL, hr REAL, cad REAL, alt_m REAL, temp REAL, power REAL
);
"""


def make_old_db(path):
    """构造一个「升级前」的旧库：老 schema + 若干数据行。"""
    conn = sqlite3.connect(str(path))
    conn.executescript(_OLD_SCHEMA)
    rows = [
        ("hash-a", "2026-08-03 08:00:00", 1754179200, 50000.0),
        ("hash-b", "2026-08-20 09:00:00", 1755648000, 30000.0),
        ("hash-c", "2026-09-05 07:30:00", 1757034600, 42000.0),
    ]
    for h, st, ts, dist in rows:
        conn.execute(
            "INSERT INTO activities (file_hash, file_name, name, device, sport,"
            " start_time, start_ts, total_distance_m, record_count, imported_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (h, f"{h}.fit", "旧数据", "iGPSPORT", "cycling", st, ts, dist, 100, "2026-09-01 00:00:00"),
        )
    # hash-a 附带记圈与逐条记录，用于验证按月删除的级联清理
    aid = conn.execute("SELECT id FROM activities WHERE file_hash='hash-a'").fetchone()[0]
    conn.execute(
        "INSERT INTO laps (activity_id, lap_index, timer_s, distance_m) VALUES (?,1,600.0,2000.0)", (aid,))
    for t in range(3):
        conn.execute(
            "INSERT INTO records (activity_id, t, lat, lon, speed_ms) VALUES (?,?,?,?,?)",
            (aid, t, 30.0 + t * 0.001, 120.0 + t * 0.001, 5.0))
    conn.commit()
    conn.close()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="fit_migration_"))
    try:
        print("== 旧库升级路径（历史 schema + 旧数据）==")
        old_path = tmp / "old_fit.db"
        make_old_db(old_path)

        # 旧库由新 DB 类打开：_SCHEMA 会因 IF NOT EXISTS 跳过建表，
        # 迁移负责加列 + 回填 + 建索引——此前版本在此直接崩溃
        db = db_mod.DB(old_path)
        check("旧库打开不崩溃（原 no such column: month 场景）", True)

        cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(activities)")}
        check("month 列已添加", "month" in cols)
        check("其他迁移列已添加", {"device_brand", "tss", "tss_sig"} <= cols)

        idx = {r["name"] for r in db.conn.execute("PRAGMA index_list(activities)")}
        check("month 索引已创建", "idx_act_month_col" in idx, str(idx))

        months = db.months()
        check("月度汇总按物化列聚合", [m["month"] for m in months] == ["2026-09", "2026-08"],
              str([m["month"] for m in months]))
        check("月度里程正确", months[-1]["distance_km"] == 80.0, str(months))

        acts_aug = db.list_activities("2026-08")
        check("按月查询 2026-08 = 2 条", len(acts_aug) == 2, str(len(acts_aug)))
        acts_sep = db.list_activities("2026-09")
        check("按月查询 2026-09 = 1 条", len(acts_sep) == 1)
        check("查询结果含旧数据字段", acts_aug[0]["file_hash"] == "hash-a" or
              all(a["file_hash"] in ("hash-a", "hash-b") for a in acts_aug))

        # 旧库上继续写入（upsert 路径带 month 列）
        aid, is_new = db.upsert_activity({
            "file_hash": "hash-new", "file_name": "new.fit", "name": "新活动",
            "device": "Garmin", "device_brand": "garmin", "product": 1,
            "product_name": "", "hw_version": "", "sw_version": "",
            "sport": "cycling", "sub_sport_cn": "", "start_time": "2026-09-10 08:00:00",
            "start_ts": 1757462400,
            "summary": {"total_distance_m": 10000.0, "timer_s": 1800.0, "elapsed_s": 1900.0,
                        "moving_s": 1700.0, "avg_speed_ms": 5.5, "max_speed_ms": 9.0,
                        "avg_hr": None, "max_hr": None, "min_hr": None, "avg_cad": None,
                        "max_cad": None, "calories": 200, "ascent_m": 50.0, "descent_m": 50.0,
                        "avg_alt_m": None, "max_alt_m": None, "min_alt_m": None,
                        "avg_temp": None, "max_temp": None, "min_temp": None,
                        "lat": None, "lon": None},
            "laps": [], "records": [], "record_count": 0,
        })
        check("旧库 upsert 新活动成功", is_new and aid > 0)
        # list_activities 按 start_ts DESC 排序，新活动(09-10)应排在最前
        check("新活动 month 已物化", db.list_activities("2026-09")[0]["file_hash"] == "hash-new")
        db.close()

        print("== 新库直接建库路径 ==")
        new_db = db_mod.DB(tmp / "fresh_fit.db")
        check("新库打开正常", True)
        check("新库月度为空", new_db.months() == [])
        new_db.close()

        print("== 幂等性：再次打开同一旧库 ==")
        db2 = db_mod.DB(old_path)
        check("二次打开正常（迁移幂等）", True)
        check("数据未丢失", db2.count() == 4)

        print("== 按月删除（delete_month）==")
        n = db2.delete_month("2026-09")
        check("删除 2026-09 返回 2 条", n == 2, f"n={n}")
        check("剩余活动 2 条", db2.count() == 2, f"count={db2.count()}")
        check("月度汇总只剩 2026-08", [m["month"] for m in db2.months()] == ["2026-08"])
        orphan_recs = db2.conn.execute(
            "SELECT COUNT(*) AS c FROM records WHERE activity_id NOT IN (SELECT id FROM activities)"
        ).fetchone()["c"]
        orphan_laps = db2.conn.execute(
            "SELECT COUNT(*) AS c FROM laps WHERE activity_id NOT IN (SELECT id FROM activities)"
        ).fetchone()["c"]
        check("records 无孤儿行（级联清理）", orphan_recs == 0, f"orphan={orphan_recs}")
        check("laps 无孤儿行（级联清理）", orphan_laps == 0, f"orphan={orphan_laps}")
        n2 = db2.delete_month("2026-08")
        check("删除 2026-08 返回 2 条", n2 == 2, f"n={n2}")
        check("全部删除后 count=0", db2.count() == 0)
        check("空月份删除返回 0", db2.delete_month("2026-08") == 0)
        db2.close()

        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
