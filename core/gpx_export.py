"""GPX 导出：将活动记录转为标准 GPX 1.1 格式（含心率/踏频/温度/速度/功率扩展）。

GPX schema: https://www.topografix.com/GPX/1/1/
扩展使用 Garmin TrackPointExtension v1 命名空间（被 Strava/Garmin Connect/行者等主流平台兼容）。
"""
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone


NS_GPX = "http://www.topografix.com/GPX/1/1"
NS_TPE = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
NS_CLMB = "http://www.garmin.com/xmlschemas/ClimbExtension/v1"

ET.register_namespace("", NS_GPX)
ET.register_namespace("gpxtpx", NS_TPE)
ET.register_namespace("gpxclmb", NS_CLMB)


def _ns(tag):
    return f"{{{NS_GPX}}}{tag}"


def _tpe(tag):
    return f"{{{NS_TPE}}}{tag}"


def _clmb(tag):
    return f"{{{NS_CLMB}}}{tag}"


def _fmt_dt(ts):
    """将 Unix 时间戳转为 ISO 8601 UTC 字符串。"""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(el, v):
    if v is not None:
        el.text = str(v)


def export_gpx(act, records, laps=None, output_path=None):
    """导出单条活动为 GPX 1.1 文件。

    参数:
        act: db.get_activity() 返回的 dict（含 distance_km/timer_s/start_ts/device/sport 等）。
        records: db.get_records() 返回的 list[dict]，需含 t/lat/lon/alt_m/speed_ms/hr/cad/temp/power。
        laps: list[dict]（可选，用于分圈/trkseg）。
        output_path: 输出文件路径（可选，留空则返回 XML 字符串）。

    返回:
        output_path 不为空时返回该路径；否则返回 XML 字符串。
    """
    # 从 start_time 解析起始时间戳
    start_ts = act.get("start_ts")
    if not start_ts and act.get("start_time"):
        try:
            start_ts = int(datetime.strptime(act["start_time"], "%Y-%m-%d %H:%M:%S").timestamp())
        except Exception:
            start_ts = 0

    root = ET.Element(_ns("gpx"), attrib={
        "version": "1.1",
        "creator": f"FitAnalyzer/1.0",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": (
            f"{NS_GPX} http://www.topografix.com/GPX/1/1/gpx.xsd "
            f"{NS_TPE} http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd"
        ),
    })

    # 元数据
    metadata = ET.SubElement(root, _ns("metadata"))
    name_el = ET.SubElement(metadata, _ns("name"))
    name_el.text = act.get("name") or "骑行"
    desc_el = ET.SubElement(metadata, _ns("desc"))
    desc_el.text = act.get("device") or ""
    if start_ts:
        ET.SubElement(metadata, _ns("time")).text = _fmt_dt(start_ts)

    # 轨迹
    trk = ET.SubElement(root, _ns("trk"))
    trk_name = ET.SubElement(trk, _ns("name"))
    trk_name.text = act.get("name") or "骑行"
    trk_type = ET.SubElement(trk, _ns("type"))
    trk_type.text = act.get("sport") or "cycling"

    # 按记圈分 trkseg；无记圈时一个 trkseg 包含全部记录
    segs = []
    if laps:
        # 按 lap 时间范围分组
        for lap in laps:
            segs.append([])
        for r in records:
            rt = r.get("t", 0)
            for i, lap in enumerate(laps):
                lap_start = lap.get("timer_s_offset", 0)
                lap_end = lap_start + (lap.get("timer_s") or 0)
                if lap_start <= rt < lap_end or i == len(laps) - 1:
                    segs[i].append(r)
                    break
            else:
                segs[-1].append(r)
    else:
        segs = [records]

    seen_any_ext = False
    for seg_recs in segs:
        if not seg_recs:
            continue
        trkseg = ET.SubElement(trk, _ns("trkseg"))
        for r in seg_recs:
            if r.get("lat") is None or r.get("lon") is None:
                continue
            pt = ET.SubElement(trkseg, _ns("trkpt"), attrib={
                "lat": str(r["lat"]),
                "lon": str(r["lon"]),
            })

            # 海拔
            if r.get("alt_m") is not None:
                ele = ET.SubElement(pt, _ns("ele"))
                ele.text = str(round(r["alt_m"], 1))

            # 时间戳
            if start_ts:
                ts = start_ts + r["t"]
                time_el = ET.SubElement(pt, _ns("time"))
                time_el.text = _fmt_dt(ts)

            # 扩展字段（心率/踏频/温度/速度/功率）
            ext = None
            hr = r.get("hr")
            cad = r.get("cad")
            temp = r.get("temp")
            speed = r.get("speed_ms")
            power = r.get("power")

            if any(v is not None for v in (hr, cad, temp, speed, power)):
                seen_any_ext = True
                ext = ET.SubElement(pt, _ns("extensions"))
                tpe_ext = ET.SubElement(ext, _tpe("TrackPointExtension"))

                if hr is not None:
                    _text(ET.SubElement(tpe_ext, _tpe("hr")), round(hr))
                if cad is not None:
                    _text(ET.SubElement(tpe_ext, _tpe("cad")), round(cad))
                if temp is not None:
                    _text(ET.SubElement(tpe_ext, _tpe("atemp")), round(temp, 1))
                if speed is not None:
                    _text(ET.SubElement(tpe_ext, _tpe("speed")), round(speed, 3))
                if power is not None:
                    _text(ET.SubElement(tpe_ext, _tpe("power")), round(power))

    # 如果没有扩展字段，去掉根元素的多余命名空间声明
    if not seen_any_ext:
        root.attrib.pop("xsi:schemaLocation", None)

    # 格式化输出
    raw = ET.tostring(root, encoding="unicode")
    dom = xml.dom.minidom.parseString(raw)
    pretty = dom.toprettyxml(indent="  ", encoding="UTF-8")
    xml_str = pretty.decode("utf-8")
    # toprettyxml 自带 XML 声明，去掉空行
    xml_str = "\n".join(line for line in xml_str.splitlines() if line.strip())

    if output_path:
        from pathlib import Path
        Path(output_path).write_text(xml_str, encoding="utf-8")
        return output_path
    return xml_str