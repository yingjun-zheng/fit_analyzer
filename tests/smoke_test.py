"""核心冒烟测试：FIT 解析、数据库、统计分析、配置、AI 错误提示（无需 GUI/网络服务）。"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import analysis, fit_parser, logging_setup
from core.config import Config
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


def main():
    # 测试数据：优先 F:\byciclefits，其次 C:\Users\zhengyingjun\Documents\deepseek\fittestdata
    fit_dir = None
    for cand in (Path(r"F:\byciclefits"), Path(r"C:\Users\zhengyingjun\Documents\deepseek\fittestdata")):
        if cand.exists() and any(cand.glob("*.fit")):
            fit_dir = cand
            break
    if fit_dir is None:
        print("!! 未找到 FIT 测试数据（F:\\byciclefits 或 fittestdata）")
        return 1
    files = sorted(fit_dir.glob("*.fit"))
    print(f"真实 FIT 文件: {len(files)} 个（来自 {fit_dir}）")

    tmp = Path(tempfile.mkdtemp(prefix="fit_smoke_"))
    logging_setup.setup_logging(tmp, console=False)
    config = Config(tmp / "config.json")
    db = db_mod.DB(tmp / "fit.db")

    print("== 解析全部真实文件 ==")
    results, errors = fit_parser.parse_many(files)
    check("全部解析无错误", len(errors) == 0, str(errors))
    check("解析数量", len(results) == len(files))

    if results:
        d = results[0]["data"]
        s = d["summary"]
        print(f"  示例: {d['name']} {s['total_distance_m']/1000:.2f}km "
              f"均速{s['avg_speed_ms']*3.6:.1f}km/h 卡路里{s['calories']} 爬升{s['ascent_m']}m "
              f"均踏频{s['avg_cad']} 记录{d['record_count']}条 laps={len(d['laps'])}")
        check("距离>0", (s["total_distance_m"] or 0) > 0)
        check("速度>0", (s["avg_speed_ms"] or 0) > 0)
        check("有轨迹点", any(r["lat"] for r in d["records"]))
        check("海拔字段", any(r["alt_m"] is not None for r in d["records"]))
        check("温度字段", any(r["temp"] is not None for r in d["records"]))
        check("时间字段(本地时区)", d["start_time"] is not None)
        check("laps 非空", len(d["laps"]) >= 1)

        print("== 入库 ==")
        ids = []
        for r in results:
            aid, is_new = db.upsert_activity(r["data"])
            ids.append(aid)
        check("入库数量", db.count() == len(files))
        _, is_new2 = db.upsert_activity(results[0]["data"])
        check("重复导入 is_new=False", is_new2 is False)
        check("重复导入不增加", db.count() == len(files))

        print("== 月度汇总 ==")
        months = db.months()
        check("月份数量", len(months) >= 2, f"{[m['month'] for m in months]}")
        if months:
            check("月度有汇总数据", months[0]["count"] > 0 and months[0]["distance_km"] > 0)

        print("== 统计分析 ==")
        records = db.get_records(ids[0])
        check("per_km 非空", len(analysis.per_km(records)) > 0)
        check("speed_zones 非空", len(analysis.speed_zones(records, config.get("speed_zone_kmh"))) > 0)
        check("cadence_zones 非空", len(analysis.cadence_zones(records, config.get("cadence_zone_rpm"))) > 0)
        act = db.get_activity(ids[0])
        hr_max = config.get("hr_max_override") or act.get("max_hr")
        hz = analysis.hr_zones(records, hr_max, config.get("hr_zone_pcts"))
        if hz:
            check("hr_zones 非空", True)
        else:
            print("  [INFO] 该文件无心率数据（符合预期）")
        check("temp_stats", analysis.temp_stats(records)["has"])
        check("elevation 非空", len(analysis.elevation_series(records)) > 0)
        check("track 非空", len(analysis.track_points(records, 2000)) > 0)
        check("series.speed 非空", len(analysis.downsample_series(records, "speed_ms", 500)) > 0)

        print("== 配置 ==")
        config.update({"speed_zone_kmh": [10, 15, 20, 25, 30], "ai_api_key": "sk-secret-test"})
        check("配置保存", config.get("speed_zone_kmh") == [10, 15, 20, 25, 30])
        check("配置脱敏", config.public_dict()["ai_api_key"] == "******")
        config.update({"ai_api_key": "******"})
        check("遮蔽值不覆盖", config.get("ai_api_key") == "sk-secret-test")

        print("== AI 错误提示（模型名不存在时列出可用模型）==")
        try:
            from core.ai_client import AIClient, AIError

            bad = AIClient("http://127.0.0.1:11434/v1", "", "qwen3.5:2b", timeout=20)
            try:
                bad.chat([{"role": "user", "content": "你好"}])
                print("  [INFO] 未报错（Ollama 未运行或模型存在），跳过")
            except AIError as e:
                msg = str(e)
                check("错误含可用模型列表", "可用的模型" in msg, msg[:200])
        except Exception:
            print("  [INFO] AI 客户端导入失败，跳过")

    db.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
