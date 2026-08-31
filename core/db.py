"""SQLite 存储：活动/记圈/逐条记录 + 月度汇总查询。"""
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger("fit.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash TEXT UNIQUE NOT NULL,
    file_name TEXT,
    name TEXT,
    device TEXT,
    device_brand TEXT,
    product INTEGER,
    product_name TEXT,
    hw_version TEXT,
    sw_version TEXT,
    sport TEXT,
    sub_sport_cn TEXT,
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
CREATE INDEX IF NOT EXISTS idx_act_start ON activities(start_ts);
CREATE INDEX IF NOT EXISTS idx_act_month ON activities(start_time);

CREATE TABLE IF NOT EXISTS laps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    lap_index INTEGER, start_time TEXT, end_time TEXT,
    timer_s REAL, distance_m REAL,
    avg_speed_ms REAL, max_speed_ms REAL,
    avg_hr REAL, max_hr REAL, avg_cad REAL, max_cad REAL,
    calories REAL, ascent_m REAL, descent_m REAL
);
CREATE INDEX IF NOT EXISTS idx_lap_act ON laps(activity_id);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    t REAL, lat REAL, lon REAL, dist_m REAL,
    speed_ms REAL, hr REAL, cad REAL, alt_m REAL, temp REAL, power REAL
);
CREATE INDEX IF NOT EXISTS idx_rec_act ON records(activity_id);
"""


class DB:
    def __init__(self, path: Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """旧库补新列（设备识别字段）。"""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(activities)")}
        adds = {
            "device_brand": "TEXT",
            "product": "INTEGER",
            "product_name": "TEXT",
            "hw_version": "TEXT",
            "sw_version": "TEXT",
            "sub_sport_cn": "TEXT",
        }
        for col, typ in adds.items():
            if col not in cols:
                self.conn.execute(f"ALTER TABLE activities ADD COLUMN {col} {typ}")
                log.info("数据库迁移：activities 增加列 %s", col)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # ---------------- 导入 ----------------
    def upsert_activity(self, data: dict):
        """写入解析结果；返回 (activity_id, is_new)。"""
        s = data["summary"]
        existing = self.conn.execute("SELECT id FROM activities WHERE file_hash=?", (data["file_hash"],)).fetchone()
        is_new = existing is None
        self.conn.execute(
            """INSERT INTO activities (
                file_hash, file_name, name, device, device_brand, product, product_name, hw_version, sw_version,
                sport, sub_sport_cn, start_time, start_ts,
                total_distance_m, timer_s, elapsed_s, moving_s,
                avg_speed_ms, max_speed_ms, avg_hr, max_hr, min_hr,
                avg_cad, max_cad, calories, ascent_m, descent_m,
                avg_alt_m, max_alt_m, min_alt_m, avg_temp, max_temp, min_temp,
                lat, lon, record_count, imported_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(file_hash) DO UPDATE SET
                file_name=excluded.file_name, name=excluded.name,
                device=excluded.device, device_brand=excluded.device_brand,
                product=excluded.product, product_name=excluded.product_name,
                hw_version=excluded.hw_version, sw_version=excluded.sw_version,
                start_time=excluded.start_time, start_ts=excluded.start_ts,
                total_distance_m=excluded.total_distance_m, timer_s=excluded.timer_s,
                avg_speed_ms=excluded.avg_speed_ms, max_speed_ms=excluded.max_speed_ms,
                avg_hr=excluded.avg_hr, max_hr=excluded.max_hr, avg_cad=excluded.avg_cad,
                max_cad=excluded.max_cad, calories=excluded.calories,
                ascent_m=excluded.ascent_m, descent_m=excluded.descent_m,
                record_count=excluded.record_count, imported_at=excluded.imported_at
            """,
            (
                data["file_hash"], data["file_name"], data["name"], data["device"],
                data.get("device_brand", ""), data.get("product"), data.get("product_name", ""),
                data.get("hw_version", ""), data.get("sw_version", ""),
                data["sport"], data.get("sub_sport_cn", ""), data["start_time"], data["start_ts"],
                s["total_distance_m"], s["timer_s"], s["elapsed_s"], s["moving_s"],
                s["avg_speed_ms"], s["max_speed_ms"], s["avg_hr"], s["max_hr"], s["min_hr"],
                s["avg_cad"], s["max_cad"], s["calories"], s["ascent_m"], s["descent_m"],
                s["avg_alt_m"], s["max_alt_m"], s["min_alt_m"],
                s["avg_temp"], s["max_temp"], s["min_temp"],
                s["lat"], s["lon"], data["record_count"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        # 冲突更新时 lastrowid 不可靠，统一按 file_hash 查询 id
        row = self.conn.execute("SELECT id FROM activities WHERE file_hash=?", (data["file_hash"],)).fetchone()
        aid = row["id"]
        self.conn.execute("DELETE FROM laps WHERE activity_id=?", (aid,))
        self.conn.execute("DELETE FROM records WHERE activity_id=?", (aid,))
        for lap in data["laps"]:
            self.conn.execute(
                """INSERT INTO laps (activity_id, lap_index, start_time, end_time, timer_s,
                   distance_m, avg_speed_ms, max_speed_ms, avg_hr, max_hr, avg_cad, max_cad,
                   calories, ascent_m, descent_m)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, lap["index"], lap.get("start_time"), lap.get("end_time"),
                 lap.get("timer_s"), lap.get("distance_m"), lap.get("avg_speed_ms"),
                 lap.get("max_speed_ms"), lap.get("avg_hr"), lap.get("max_hr"),
                 lap.get("avg_cad"), lap.get("max_cad"), lap.get("calories"),
                 lap.get("ascent_m"), lap.get("descent_m")),
            )
        self.conn.executemany(
            """INSERT INTO records (activity_id, t, lat, lon, dist_m, speed_ms, hr, cad, alt_m, temp, power)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [(aid, r["t"], r["lat"], r["lon"], r["dist_m"], r["speed_ms"],
              r["hr"], r["cad"], r["alt_m"], r["temp"], r["power"]) for r in data["records"]],
        )
        self.conn.commit()
        return aid, is_new

    def reidentify_devices(self, formatter):
        """按当前设备型号表重算所有活动的 device 显示名。
        formatter(device_brand, product, product_name, hw_version, sw_version) -> str"""
        rows = self.conn.execute(
            "SELECT id, device_brand, product, product_name, hw_version, sw_version FROM activities"
        ).fetchall()
        n = 0
        for r in rows:
            try:
                new_dev = formatter(r["device_brand"], r["product"], r["product_name"],
                                    r["hw_version"], r["sw_version"])
            except Exception:
                continue
            if new_dev:
                self.conn.execute("UPDATE activities SET device=? WHERE id=?", (new_dev, r["id"]))
                n += 1
        self.conn.commit()
        log.info("重新识别设备：更新 %d 条", n)
        return n

    # ---------------- 查询 ----------------
    def months(self):
        rows = self.conn.execute(
            """SELECT substr(start_time,1,7) AS month, COUNT(*) AS cnt,
                      SUM(total_distance_m) AS dist, SUM(timer_s) AS timer,
                      SUM(ascent_m) AS ascent, SUM(calories) AS cal
               FROM activities GROUP BY month ORDER BY month DESC"""
        ).fetchall()
        out = []
        for r in rows:
            month = r["month"] or "未知"
            dist_km = (r["dist"] or 0) / 1000.0
            hours = (r["timer"] or 0) / 3600.0
            out.append({
                "month": month,
                "count": r["cnt"],
                "distance_km": round(dist_km, 1),
                "hours": round(hours, 1),
                "ascent_m": round(r["ascent"] or 0),
                "calories": round(r["cal"] or 0),
                "avg_speed_kmh": round(dist_km / hours, 1) if hours > 0 else 0,
            })
        return out

    def list_activities(self, month=None, limit=500):
        if month:
            rows = self.conn.execute(
                """SELECT * FROM activities WHERE substr(start_time,1,7)=?
                   ORDER BY start_ts DESC LIMIT ?""", (month, limit)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM activities ORDER BY start_ts DESC LIMIT ?", (limit,)).fetchall()
        return [self._act_row(r) for r in rows]

    def get_activity(self, aid):
        r = self.conn.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
        return self._act_row(r) if r else None

    def _act_row(self, r):
        d = dict(r)
        s = d["timer_s"] or 0
        d["distance_km"] = round((d["total_distance_m"] or 0) / 1000.0, 2)
        d["moving_h"] = round((d.get("moving_s") or s) / 3600.0, 2)
        d["avg_speed_kmh"] = round((d["avg_speed_ms"] or 0) * 3.6, 1) if d["avg_speed_ms"] else None
        d["max_speed_kmh"] = round((d["max_speed_ms"] or 0) * 3.6, 1) if d["max_speed_ms"] else None
        d["has_hr"] = d["avg_hr"] is not None
        d["has_cad"] = d["avg_cad"] is not None
        return d

    def get_laps(self, aid):
        rows = self.conn.execute(
            "SELECT * FROM laps WHERE activity_id=? ORDER BY lap_index", (aid,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["distance_km"] = round((d["distance_m"] or 0) / 1000.0, 2)
            d["avg_speed_kmh"] = round((d["avg_speed_ms"] or 0) * 3.6, 1) if d["avg_speed_ms"] else None
            d["max_speed_kmh"] = round((d["max_speed_ms"] or 0) * 3.6, 1) if d["max_speed_ms"] else None
            out.append(d)
        return out

    def get_records(self, aid):
        rows = self.conn.execute(
            """SELECT t, lat, lon, dist_m, speed_ms, hr, cad, alt_m, temp, power
               FROM records WHERE activity_id=? ORDER BY t""", (aid,)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_activity(self, aid):
        self.conn.execute("DELETE FROM activities WHERE id=?", (aid,))
        self.conn.commit()

    def count(self):
        return self.conn.execute("SELECT COUNT(*) AS c FROM activities").fetchone()["c"]

    def month_activities(self, month):
        return self.list_activities(month=month)
