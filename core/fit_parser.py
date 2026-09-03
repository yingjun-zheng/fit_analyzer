"""FIT 文件解析：基于 fitparse，输出标准化活动/赛段/逐条记录数据。

兼容 iGPSPORT / Garmin / 行者等主流码表导出的 FIT（含无心率数据等缺字段情况）。
"""
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path

import fitparse

log = logging.getLogger("fit.parser")

SEMICIRCLE = 2**31

# ---- 码表识别：品牌显示名 / 产品码 → 型号 ----
MANUFACTURER_DISPLAY = {
    "igpsport": "iGPSPORT",
    "magene": "Magene（迈金）",
    "bryton": "Bryton（百锐腾）",
    "garmin": "Garmin（佳明）",
    "wahoo_fitness": "Wahoo",
    "coros": "COROS（高驰）",
    "xoss": "XOSS（行者）",
    "sportdevices": "SportDevices",
    "polar": "Polar（博能）",
    "sigma": "Sigma（西格玛）",
    "suunto": "Suunto（颂拓）",
    "hammerhead": "Hammerhead",
    "karoo": "Hammerhead",
    "stages": "Stages",
    "4iiii": "4iiii",
    "cycling_computers": "Cycling Computers",
}

def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _format_device(manufacturer, product, product_name, overrides=None, hw_version=None, sw_version=None):
    """组装设备显示名。

    识别彻底止步于「品牌」：程序自动识别只认品牌，不做任何型号翻译——
    厂商产品码开放且不断新增，文件自带的 product_name 也五花八门（如
    'C606P_41338'），自动补全型号既收不全又易误判。因此：
      - 品牌（manufacturer）是 FIT 标准枚举，能收全 → 只认品牌
      - 唯一例外：用户在「设置→设备型号表」手动登记的具体型号（用户自己的选择）
      - 不自动展开文件自带的 product_name，不显示「产品码 XX」兜底格式
    """
    brand = MANUFACTURER_DISPLAY.get(manufacturer, manufacturer) if manufacturer else "未知设备"
    if isinstance(brand, int) or (isinstance(brand, str) and brand.isdigit()):
        brand = f"厂商{manufacturer}"
    p = _to_int(product)
    # 仅在用户手动登记（设置→设备型号表）时附带具体型号；其余一律只显示品牌
    if overrides and p is not None and manufacturer:
        key = f"{manufacturer}/{p}"
        v = overrides.get(key)
        if v is not None and str(v).strip():
            return f"{brand} {str(v).strip()}"
    return brand


class FitParseError(Exception):
    pass


def _num(v):
    """把 fitparse 返回值安全转成 float/None（处理元组等包装）。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, tuple):
        for item in v:
            if isinstance(item, (int, float)):
                return float(item)
        return None
    if isinstance(v, datetime):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _msg_fields(msg):
    return {f.name: f.value for f in msg.fields}


def _semicircle_to_deg(v):
    n = _num(v)
    if n is None:
        return None
    return n * 180.0 / SEMICIRCLE


def parse_fit_file(path: Path):
    """解析单个 FIT 文件，返回标准化 dict；失败抛 FitParseError。"""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise FitParseError(f"读取文件失败: {e}")
    file_hash = hashlib.sha1(data).hexdigest()
    file_name = path.name

    try:
        fit = fitparse.FitFile(str(path))
        messages = list(fit.get_messages())
    except Exception as e:
        raise FitParseError(f"FIT 解析失败: {e}")

    file_id = {}
    sessions = []
    laps = []
    records = []
    activities = []
    device_infos = []

    for msg in messages:
        name = msg.name or ""
        f = _msg_fields(msg)
        if name == "file_id":
            file_id = f
        elif name == "session":
            sessions.append(f)
        elif name == "lap":
            laps.append(f)
        elif name == "record":
            records.append(f)
        elif name == "activity":
            activities.append(f)
        elif name == "device_info":
            device_infos.append(f)

    if not sessions and not records:
        raise FitParseError("未找到会话/记录数据（可能不是骑行活动文件）")

    # 会话：取距离最大的
    session = None
    if sessions:
        session = max(sessions, key=lambda s: _num(s.get("total_distance")) or 0.0)

    # 起点时间：优先 session.start_time，否则第一条 record 时间
    start_dt = None
    if session and session.get("start_time") is not None:
        start_dt = session["start_time"]
    elif records:
        start_dt = records[0].get("timestamp")
    if not start_dt and activities:
        start_dt = activities[0].get("timestamp")
    if start_dt is None:
        raise FitParseError("无法确定活动开始时间")

    # 时区换算：FIT 时间戳为 UTC，用 activity.local_timestamp 推算本地偏移（显示用）
    utc_offset_s = 0
    for a in activities:
        lt = a.get("local_timestamp")
        ts = a.get("timestamp")
        if lt is not None and ts is not None:
            diff = (lt - ts).total_seconds()
            if abs(diff) <= 14 * 3600:
                utc_offset_s = int(diff)
                break
    display_dt = start_dt + timedelta(seconds=utc_offset_s)

    start_ts = start_dt.timestamp()

    # ---- 逐条记录 ----
    rec_out = []
    prev = None  # (dist, speed)
    for f in records:
        ts = f.get("timestamp")
        if ts is None:
            continue
        t = max(0.0, ts.timestamp() - start_ts)
        lat = _semicircle_to_deg(f.get("position_lat"))
        lon = _semicircle_to_deg(f.get("position_long"))
        dist = _num(f.get("distance"))
        speed = _num(f.get("enhanced_speed"))
        if speed is None:
            speed = _num(f.get("speed"))
        alt = _num(f.get("enhanced_altitude"))
        if alt is None:
            alt = _num(f.get("altitude"))
        hr = _num(f.get("heart_rate"))
        cad = _num(f.get("cadence"))
        temp = _num(f.get("temperature"))
        power = _num(f.get("power"))
        # 缺失速度时用距离差推导
        if speed is None and prev and dist is not None and prev[0] is not None and t > prev[2]:
            d = max(0.0, dist - prev[0])
            speed = d / (t - prev[2])
        if speed is None:
            speed = 0.0
        rec_out.append({
            "t": round(t, 1),
            "lat": None if lat is None else round(lat, 7),
            "lon": None if lon is None else round(lon, 7),
            "dist_m": None if dist is None else round(dist, 1),
            "speed_ms": None if speed is None else round(speed, 3),
            "hr": None if hr is None else round(hr),
            "cad": None if cad is None else round(cad),
            "alt_m": None if alt is None else round(alt, 1),
            "temp": None if temp is None else round(temp, 1),
            "power": None if power is None else round(power),
        })
        prev = (dist, speed, t)

    if not rec_out:
        raise FitParseError("没有逐条记录数据")

    # 距离缺失时用速度积分补全
    last_dist = 0.0
    for i, r in enumerate(rec_out):
        if r["dist_m"] is None:
            if i > 0:
                dt = r["t"] - rec_out[i - 1]["t"]
                last_dist += (r["speed_ms"] or 0.0) * dt
            r["dist_m"] = round(last_dist, 1)
        else:
            last_dist = r["dist_m"]

    # ---- 汇总 ----
    def sget(*keys):
        if not session:
            return None
        for k in keys:
            v = session.get(k)
            if v is not None:
                return v
        return None

    total_dist = _num(sget("total_distance"))
    if total_dist is None and rec_out:
        total_dist = rec_out[-1]["dist_m"] or 0.0
    timer = _num(sget("total_timer_time")) or _num(sget("total_moving_time"))
    if timer is None and rec_out:
        timer = rec_out[-1]["t"]
    elapsed = _num(sget("total_elapsed_time"))
    moving = _num(sget("total_moving_time"))
    avg_speed = _num(sget("enhanced_avg_speed", "avg_speed"))
    if avg_speed is None and timer and timer > 0 and total_dist:
        avg_speed = total_dist / timer

    def first_num(*keys):
        for k in keys:
            v = sget(k)
            n = _num(v)
            if n is not None:
                return n
        return None

    avg_hr = first_num("avg_heart_rate")
    max_hr = first_num("max_heart_rate")
    min_hr = first_num("min_heart_rate")
    if avg_hr is None and rec_out:
        hrs = [r["hr"] for r in rec_out if r["hr"] is not None]
        if hrs:
            avg_hr = sum(hrs) / len(hrs)
            max_hr = max_hr if max_hr is not None else max(hrs)
            min_hr = min_hr if min_hr is not None else min(hrs)

    avg_cad = first_num("avg_cadence")
    max_cad = first_num("max_cadence")
    if avg_cad is None and rec_out:
        cads = [r["cad"] for r in rec_out if r["cad"] is not None]
        if cads:
            avg_cad = sum(cads) / len(cads)
            max_cad = max_cad if max_cad is not None else max(cads)

    calories = first_num("total_calories")
    ascent = first_num("total_ascent")
    descent = first_num("total_descent")
    if (ascent is None or descent is None) and rec_out:
        alts = [(r["t"], r["alt_m"]) for r in rec_out if r["alt_m"] is not None]
        if alts:
            a = d = 0.0
            for i in range(1, len(alts)):
                diff = alts[i][1] - alts[i - 1][1]
                if diff > 0:
                    a += diff
                else:
                    d += -diff
            if ascent is None:
                ascent = a
            if descent is None:
                descent = d

    avg_alt = first_num("enhanced_avg_altitude", "avg_altitude")
    max_alt = first_num("enhanced_max_altitude", "max_altitude")
    min_alt = first_num("enhanced_min_altitude", "min_altitude")
    if avg_alt is None and rec_out:
        alts = [r["alt_m"] for r in rec_out if r["alt_m"] is not None]
        if alts:
            avg_alt = sum(alts) / len(alts)
            max_alt = max_alt if max_alt is not None else max(alts)
            min_alt = min_alt if min_alt is not None else min(alts)

    avg_temp = first_num("avg_temperature")
    max_temp = first_num("max_temperature")
    min_temp = first_num("min_temperature")
    if avg_temp is None and rec_out:
        temps = [r["temp"] for r in rec_out if r["temp"] is not None]
        if temps:
            avg_temp = sum(temps) / len(temps)
            max_temp = max_temp if max_temp is not None else max(temps)
            min_temp = min_temp if min_temp is not None else min(temps)

    start_lat = _semicircle_to_deg(sget("start_position_lat"))
    start_lon = _semicircle_to_deg(sget("start_position_long"))
    if (start_lat is None or start_lon is None) and rec_out:
        for r in rec_out:
            if r["lat"] is not None:
                start_lat, start_lon = r["lat"], r["lon"]
                break

    sport = sget("sport") or "cycling"
    sub_sport = sget("sub_sport") or ""

    # sub_sport 中文翻译
    SUB_SPORT_CN = {
        "generic": "通用", "road": "公路骑行", "mountain": "山地骑行",
        "gravel": "砾石骑行", "cyclocross": "公路越野", "commuting": "通勤",
        "touring": "长途骑行", "track": "场地骑行", "indoor_cycling": "室内骑行",
        "virtual_ride": "虚拟骑行", "e_bike": "电助力",
    }
    sub_sport_cn = SUB_SPORT_CN.get(str(sub_sport).lower(), str(sub_sport)) if sub_sport else ""

    manufacturer = file_id.get("manufacturer")
    product = file_id.get("product")
    product_name = file_id.get("product_name")
    # 主机信息：从与 file_id 同厂商的 device_info 里补充固件/硬件版本与型号名
    hw_version = sw_version = None
    for di in device_infos:
        if di.get("manufacturer") and manufacturer and di.get("manufacturer") == manufacturer:
            if di.get("hardware_version") is not None:
                hw_version = di.get("hardware_version")
            if di.get("software_version") is not None:
                sw_version = di.get("software_version")
            if not product_name and di.get("product_name"):
                product_name = di.get("product_name")
    device = _format_device(manufacturer, product, product_name, hw_version=hw_version, sw_version=sw_version)

    # ---- 记圈 ----
    lap_out = []
    for i, lap in enumerate(laps):
        st = lap.get("start_time")
        et = lap.get("timestamp")
        l = {
            "index": i + 1,
            "start_time": (st + timedelta(seconds=utc_offset_s)).strftime("%Y-%m-%d %H:%M:%S") if st else None,
            "end_time": (et + timedelta(seconds=utc_offset_s)).strftime("%Y-%m-%d %H:%M:%S") if et else None,
            "timer_s": _num(lap.get("total_timer_time")),
            "distance_m": _num(lap.get("total_distance")),
            "avg_speed_ms": _num(lap.get("enhanced_avg_speed", "avg_speed")) if "enhanced_avg_speed" in lap or "avg_speed" in lap else None,
            "max_speed_ms": _num(lap.get("enhanced_max_speed", "max_speed")) if "enhanced_max_speed" in lap or "max_speed" in lap else None,
            "avg_hr": _num(lap.get("avg_heart_rate")),
            "max_hr": _num(lap.get("max_heart_rate")),
            "avg_cad": _num(lap.get("avg_cadence")),
            "max_cad": _num(lap.get("max_cadence")),
            "calories": _num(lap.get("total_calories")),
            "ascent_m": _num(lap.get("total_ascent")),
            "descent_m": _num(lap.get("total_descent")),
        }
        if l["avg_speed_ms"] is None and l["distance_m"] and l["timer_s"]:
            l["avg_speed_ms"] = l["distance_m"] / l["timer_s"]
        lap_out.append(l)
    if not lap_out and rec_out:
        lap_out.append({
            "index": 1,
            "start_time": display_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": (display_dt + timedelta(seconds=timer or 0)).strftime("%Y-%m-%d %H:%M:%S"),
            "timer_s": timer, "distance_m": total_dist,
            "avg_speed_ms": avg_speed, "max_speed_ms": first_num("enhanced_max_speed", "max_speed"),
            "avg_hr": avg_hr, "max_hr": max_hr, "avg_cad": avg_cad, "max_cad": max_cad,
            "calories": calories, "ascent_m": ascent, "descent_m": descent,
        })

    start_display = display_dt.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "file_hash": file_hash,
        "file_name": file_name,
        "device": device,
        "device_brand": str(manufacturer) if manufacturer else "",
        "product": _to_int(product),
        "product_name": str(product_name).strip() if product_name else "",
        "hw_version": str(hw_version) if hw_version is not None else "",
        "sw_version": str(sw_version) if sw_version is not None else "",
        "sport": sport,
        "sub_sport": sub_sport,
        "sub_sport_cn": sub_sport_cn,
        "start_time": start_display,
        "start_ts": int(start_ts),
        "name": f"{display_dt.strftime('%Y-%m-%d')} 骑行",
        "summary": {
            "total_distance_m": round(total_dist, 1) if total_dist else 0.0,
            "timer_s": round(timer, 1) if timer else 0.0,
            "elapsed_s": round(elapsed, 1) if elapsed else None,
            "moving_s": round(moving, 1) if moving else None,
            "avg_speed_ms": round(avg_speed, 3) if avg_speed else None,
            "max_speed_ms": first_num("enhanced_max_speed", "max_speed"),
            "avg_hr": round(avg_hr) if avg_hr else None,
            "max_hr": round(max_hr) if max_hr else None,
            "min_hr": round(min_hr) if min_hr else None,
            "avg_cad": round(avg_cad) if avg_cad else None,
            "max_cad": round(max_cad) if max_cad else None,
            "calories": round(calories) if calories else None,
            "ascent_m": round(ascent, 1) if ascent else None,
            "descent_m": round(descent, 1) if descent else None,
            "avg_alt_m": round(avg_alt, 1) if avg_alt else None,
            "max_alt_m": round(max_alt, 1) if max_alt else None,
            "min_alt_m": round(min_alt, 1) if min_alt else None,
            "avg_temp": round(avg_temp, 1) if avg_temp else None,
            "max_temp": round(max_temp, 1) if max_temp else None,
            "min_temp": round(min_temp, 1) if min_temp else None,
            "lat": round(start_lat, 7) if start_lat is not None else None,
            "lon": round(start_lon, 7) if start_lon is not None else None,
        },
        "laps": lap_out,
        "records": rec_out,
        "record_count": len(rec_out),
    }


def parse_many(paths):
    """批量解析；返回 (results, errors)。results: [{path, data}]，errors: [{path, error}]。"""
    results, errors = [], []
    for p in paths:
        try:
            results.append({"path": str(p), "data": parse_fit_file(p)})
        except FitParseError as e:
            errors.append({"path": str(p), "error": str(e)})
        except Exception as e:  # 兜底
            log.exception("解析 %s 异常", p)
            errors.append({"path": str(p), "error": f"未知错误: {e}"})
    return results, errors
