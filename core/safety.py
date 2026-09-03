"""骑行安全分析：从已记录数据检测异常事件（急刹、长时间骤停、速度异常）。

说明：码表 FIT 无加速度计/陀螺仪，无法做真正的摔车检测。这里用启发式——
速度骤降 + 后续长时间静止，标记为「疑似急停/摔车」待人工复盘确认。
纯数据侧实现，无外部依赖。
"""


def detect_events(records, speed_threshold_kmh=15.0, still_s=20):
    """检测骑行中的异常事件。

    records: 逐条记录，需含 speed_ms（m/s）、timestamp（或按序递增）。
    返回 list[dict]：{time, type, desc}，按时间升序。

    启发式：
    - 急刹/疑似摔车：上一刻速度 ≥ speed_threshold（突然有速度），紧接着
      长时间（≥ still_s 秒）速度≈0
    """
    events = []

    # 先算逐条速度（km/h，缺失跳过）
    n = len(records)
    i = 0
    while i < n:
        r = records[i]
        spd = r.get("speed_ms")
        if spd is None:
            i += 1
            continue
        spd_kmh = spd * 3.6
        # 找到一次「从有速度 → 静止」的转折
        if spd_kmh >= speed_threshold_kmh:
            # 检查之后是否长时间静止
            # 收集之后连续静止的时长（按记录数近似秒）
            j = i + 1
            still_sec = 0
            while j < n:
                s2 = records[j].get("speed_ms")
                if s2 is not None and s2 * 3.6 < 1.0:
                    still_sec += 1
                    j += 1
                else:
                    break
            if still_sec >= still_s:
                t = r.get("timestamp") or r.get("time") or ""
                events.append({
                    "idx": i,
                    "time": str(t),
                    "type": "急停",
                    "desc": f"以 {spd_kmh:.0f} km/h 骑行后骤停约 {still_sec}s（疑似急刹/摔车，请确认）",
                })
            i = j if j > i + 1 else i + 1
        else:
            i += 1
    return events


def safety_summary(records):
    """返回安全分析文字摘要。"""
    events = detect_events(records)
    if not events:
        return "未检测到明显的急停/异常事件。"
    lines = [f"检测到 {len(events)} 处疑似急停/异常事件："]
    for e in events[:10]:
        lines.append(f"· {e['time'] or '未知时刻'}：{e['desc']}")
    if len(events) > 10:
        lines.append(f"… 共 {len(events)} 处，仅列前 10 处。")
    return "\n".join(lines)
