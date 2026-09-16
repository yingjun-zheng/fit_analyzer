"""导出 Excel 报表（P2-A）：活动明细 + 月度汇总，另附数据库备份。

设计：
- 活动明细：单次骑行的完整指标（含通勤标记、功率估算标注、TSS）。
- 月度汇总：按月聚合次数/里程/用时/爬升/卡路里，并拆分通勤与训练里程。
- 样式：表头加粗填色 + 冻结首行 + 自适应列宽，无需模板。
- 备份：sqlite3 backup API 在线复制 fit.db（一致性快照，不锁库）。
"""
import datetime
import logging

log = logging.getLogger("fit.excel")

_HEADER_FILL = "1E88E5"
_HEADER_FONT = "FFFFFF"


def _style_sheet(ws, headers, widths):
    from openpyxl.styles import Alignment, Font, PatternFill
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c)
        cell.value = h
        cell.font = Font(bold=True, color=_HEADER_FONT)
        cell.fill = PatternFill("solid", fgColor=_HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = widths[c - 1]
    ws.freeze_panes = "A2"


def _act_rows(acts):
    """活动 dict → 明细行（与界面口径一致：km/h、h、m）。"""
    rows = []
    for a in acts:
        rows.append([
            (a.get("start_time") or "")[:16],
            a.get("name") or "",
            a.get("device") or "",
            "通勤" if a.get("commute") else "训练",
            a.get("distance_km"),
            round((a.get("timer_s") or 0) / 3600, 2) or None,
            a.get("avg_speed_kmh"),
            a.get("max_speed_kmh"),
            round(a["ascent_m"]) if a.get("ascent_m") is not None else None,
            round(a["avg_hr"]) if a.get("avg_hr") is not None else None,
            round(a["max_hr"]) if a.get("max_hr") is not None else None,
            round(a["avg_cad"]) if a.get("avg_cad") is not None else None,
            round(a["calories"]) if a.get("calories") is not None else None,
            (f"{a['avg_power']} W（估算）" if a.get("power_estimated")
             else a.get("avg_power")) if a.get("avg_power") is not None else None,
            a.get("tss"),
        ])
    return rows


def export_excel(db, path, month=None):
    """导出 Excel 报表到 path（.xlsx）。

    month=None 导出全部活动；传 YYYY-MM 只导该月（明细+当月汇总单行）。
    返回写入的活动条数。
    """
    from openpyxl import Workbook

    acts = db.list_activities(month=month, limit=100000)
    if not acts:
        raise ValueError("没有可导出的活动数据" if not month else f"{month} 无活动数据")

    wb = Workbook()

    # ---- Sheet1 活动明细 ----
    ws = wb.active
    ws.title = "活动明细"
    headers = ["日期", "名称", "设备", "类型", "距离(km)", "用时(h)", "均速(km/h)",
               "最大速度(km/h)", "爬升(m)", "均心率(bpm)", "最大心率(bpm)",
               "均踏频(rpm)", "卡路里(kcal)", "均功率(W)", "TSS"]
    _style_sheet(ws, headers, [17, 30, 18, 8, 10, 9, 11, 14, 9, 11, 12, 11, 12, 14, 8])
    for row in _act_rows(acts):
        ws.append(row)

    # ---- Sheet2 月度汇总 ----
    ws2 = wb.create_sheet("月度汇总")
    h2 = ["月份", "次数", "总里程(km)", "训练里程(km)", "通勤里程(km)",
          "用时(h)", "爬升(m)", "卡路里(kcal)", "均速(km/h)"]
    _style_sheet(ws2, h2, [10, 8, 12, 12, 12, 9, 9, 12, 10])
    months = db.months() if month is None else [m for m in db.months() if m["month"] == month]
    # months 按 start_ts 倒序（最近在前），报表按时间正序更自然
    for m in reversed(months):
        acts_m = db.list_activities(month=m["month"], limit=100000)
        total = sum(a.get("total_distance_m") or 0 for a in acts_m)
        commute = sum(a.get("total_distance_m") or 0 for a in acts_m if a.get("commute"))
        hours = sum(a.get("timer_s") or 0 for a in acts_m) / 3600
        ascent = sum(a.get("ascent_m") or 0 for a in acts_m)
        cal = sum(a.get("calories") or 0 for a in acts_m)
        ws2.append([
            m["month"], m["count"], m["distance_km"],
            round((total - commute) / 1000, 1), round(commute / 1000, 1),
            round(hours, 1), round(ascent), round(cal),
            m.get("avg_speed_kmh"),
        ])

    wb.save(path)
    log.info("Excel 报表已导出：%s（%d 条活动）", path, len(acts))
    return len(acts)


def backup_database(db_path, dest_dir):
    """在线备份 SQLite 数据库到 dest_dir（一致性快照，主程序继续可用）。

    返回备份文件完整路径。
    """
    import sqlite3
    from pathlib import Path

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"fit_backup_{stamp}.db"
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)  # 在线备份 API：页级复制，保证一致性
        finally:
            dst.close()
    finally:
        src.close()
    log.info("数据库已备份：%s", dest)
    return dest
