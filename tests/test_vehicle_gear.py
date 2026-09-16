"""多车管理（P2-B）定向单测：activities/gear.vehicle 迁移、按车里程口径、
set_vehicle Action、get_gear_status 车辆筛选、备份后标记持久化。

直接跑：python tests/test_vehicle_gear.py
"""
import sys
import tempfile
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import DB
from core.config import Config
from core import gear as gear_mod
from core import month_agent

_ok, _fail = 0, 0


def check(name, cond, extra=""):
    global _ok, _fail
    print(("  [PASS]" if cond else "  [FAIL]"), name, extra)
    _ok, _fail = _ok + (1 if cond else 0), _fail + (0 if cond else 1)


d = Path(tempfile.mkdtemp())

# 1) 旧库迁移：activities/gear 均补 vehicle 列
old = sqlite3.connect(d / "old.db")
old.execute("""CREATE TABLE activities (id INTEGER PRIMARY KEY AUTOINCREMENT, file_hash TEXT UNIQUE,
    name TEXT, device TEXT, sport TEXT, start_time TEXT, start_ts INTEGER, month TEXT,
    total_distance_m REAL, timer_s REAL, elapsed_s REAL, moving_s REAL,
    avg_speed_ms REAL, max_speed_ms REAL, avg_hr REAL, max_hr REAL, min_hr REAL,
    avg_cad REAL, max_cad REAL, calories REAL, ascent_m REAL, descent_m REAL,
    avg_alt_m REAL, max_alt_m REAL, min_alt_m REAL, avg_temp REAL, max_temp REAL,
    min_temp REAL, lat REAL, lon REAL, record_count INTEGER, imported_at TEXT)""")
old.execute("""CREATE TABLE gear (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT,
    start_date TEXT, start_ts INTEGER, initial_km REAL DEFAULT 0, expected_km REAL DEFAULT 0,
    note TEXT, retired INTEGER DEFAULT 0, retired_ts INTEGER)""")
acts = [
    ("h1", "公路车骑行", "2026-09-01 07:00:00", 1787904000, 30000),
    ("h2", "山地车骑行", "2026-09-02 09:00:00", 1787990400, 20000),
    ("h3", "未标记骑行", "2026-09-03 07:00:00", 1788076800, 10000),
]
for fh, name, st, ts, dist in acts:
    old.execute(
        "INSERT INTO activities (file_hash,name,start_time,start_ts,month,total_distance_m,timer_s,elapsed_s,moving_s,avg_speed_ms,max_speed_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (fh, name, st, ts, st[:7], dist, 3600, 3700, 3500, 4.5, 7))
old.commit()
old.close()
db = DB(d / "old.db")
acols = {r["name"] for r in db.conn.execute("PRAGMA table_info(activities)")}
gcols = {r["name"] for r in db.conn.execute("PRAGMA table_info(gear)")}
check("activities.vehicle 已迁移", "vehicle" in acols)
check("gear.vehicle 已迁移", "vehicle" in gcols)

# 2) 标记车辆 + 按车里程口径
db.set_activity_vehicle(1, "公路车")
db.set_activity_vehicle(2, "山地车")
check("按车里程（公路车 30km）",
      db.sum_distance_between(0, vehicle="公路车") == 30000.0)
check("按车里程（山地车 20km）",
      db.sum_distance_between(0, vehicle="山地车") == 20000.0)
check("按车里程（未标记 10km）",
      db.sum_distance_between(0, vehicle="") == 10000.0)
check("全部里程（兼容旧口径）", db.sum_distance_between(0) == 60000.0)

# 3) 装备里程按车辆
db.gear_add("公路车-链条", "链条", "2026-08-01", 1785523200, 100, 3000, vehicle="公路车")
db.gear_add("通用外胎", "外胎", "2026-08-01", 1785523200, 0, 6000)
gs = {g["name"]: g for g in db.gear_list()}
chain_km = gear_mod.gear_mileage_km(db, gs["公路车-链条"])
check("挂车装备只算该车活动里程 100+30=130",
      abs(chain_km - 130.0) < 0.01, str(chain_km))
tire_km = gear_mod.gear_mileage_km(db, gs["通用外胎"])
check("未挂车装备按全部活动 0+60=60", abs(tire_km - 60.0) < 0.01, str(tire_km))
st_chain = gear_mod.gear_status(db, gs["公路车-链条"])
check("状态含 vehicle 字段", st_chain.get("vehicle") == "公路车")

# 4) get_gear_status 按车辆筛选（AI 工具）
r = month_agent._tool_gear(db, vehicle="公路车")
check("按车筛选命中 1 件", r.get("count") == 1, str(r.get("count")))
r = month_agent._tool_gear(db, vehicle="死飞")
check("按车筛选无结果报错", "error" in r)

# 5) set_vehicle Action 全路径
cfg = Config(d / "cfg.json")
ctx_ok = {"db": db, "month": "2026-09", "config": cfg, "on_action": lambda a: True}
r = month_agent._exec_action("set_vehicle", {"date": "2026-09-03", "vehicle": "山地车"}, ctx_ok)
check("确认后标记车辆", "已执行" in str(r.get("result", "")), str(r.get("result")))
check("DB 已写入", db.get_activity(3).get("vehicle") == "山地车")
r = month_agent._exec_action("set_vehicle", {"date": "2026-09-03", "vehicle": ""}, ctx_ok)
check("空车辆名=清除标记", db.get_activity(3).get("vehicle") == "")
r = month_agent._exec_action("set_vehicle", {"date": "2026-09-03", "vehicle": "山地车"},
                             {"db": db, "month": "2026-09", "config": cfg, "on_action": None})
check("无确认通道拒绝", "error" in r)
r = month_agent._exec_action("set_vehicle", {"date": "bad", "vehicle": "x"}, ctx_ok)
check("非法日期拒绝", "error" in r)

# 6) 车辆清单
db.gear_add("公路车整车", "整车", "2026-08-01", 1785523200, 0, 0, vehicle="公路车")
check("车辆清单来自装备台账", db.vehicle_names() == ["公路车"], str(db.vehicle_names()))

# 7) gear_update 改挂车辆
db.gear_update(gs["通用外胎"]["id"], {"vehicle": "山地车"})
check("gear_update 可改挂车辆",
      gear_mod.gear_mileage_km(db, {**gs["通用外胎"], "vehicle": "山地车"}) == 20.0)

db.close()
print(f"结果: {_ok} 通过, {_fail} 失败")
sys.exit(1 if _fail else 0)
