"""自然语言查询 Agent 冒烟测试：用脚本化假客户端验证 ReAct 工具调用链路，无需真实 AI 服务。

运行：从 fit_analyzer 项目根目录执行
    python tests/test_nl_query_smoke.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import nl_query
from core.config import Config


class FakeAI:
    """脚本化 ReAct：第1轮调 get_track_summary，第2轮调 get_activity_summary，第3轮给最终回答。"""
    def __init__(self):
        self.calls = 0

    def chat_full(self, messages, model=None, temperature=None, timeout=None, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {"content": "", "reasoning": "先看轨迹起伏情况", "tool_calls": [
                {"id": "c1", "name": "get_track_summary", "arguments": {}}]}
        if self.calls == 2:
            return {"content": "", "reasoning": "再看整体概览", "tool_calls": [
                {"id": "c2", "name": "get_activity_summary", "arguments": {}}]}
        return {"content": "本次骑行总爬升约 330 米，轨迹点 3 个，海拔 50→380 米，中等起伏；"
                           "总距离 0.3 km、用时 0.3 分钟、均速 36.0 km/h。",
                "reasoning": "", "tool_calls": []}

    def chat(self, messages, model=None, temperature=None, timeout=None):
        return "（降级）回答"


def _sample():
    records = [
        {"t": 0.0, "lat": 30.0, "lon": 120.0, "dist_m": 0.0, "speed_ms": 0.0,
         "hr": 120, "cad": 80, "alt_m": 50.0, "temp": 20.0, "power": 150},
        {"t": 10.0, "lat": 30.001, "lon": 120.001, "dist_m": 100.0, "speed_ms": 10.0,
         "hr": 140, "cad": 90, "alt_m": 200.0, "temp": 21.0, "power": 200},
        {"t": 20.0, "lat": 30.002, "lon": 120.002, "dist_m": 300.0, "speed_ms": 10.0,
         "hr": 150, "cad": 90, "alt_m": 380.0, "temp": 22.0, "power": 220},
    ]
    act = {
        "name": "测试骑行", "start_time": "2026-08-27 08:00:00", "sport": "cycling",
        "device": "iGPSPORT IGS620", "distance_km": 0.3, "timer_s": 20.0,
        "avg_speed_ms": 10.0, "max_speed_ms": 10.0, "ascent_m": 330.0, "descent_m": 0.0,
        "calories": 30, "record_count": 3, "has_hr": True, "has_cad": True,
        "avg_hr": 137, "max_hr": 150, "avg_cad": 87,
    }
    cfg = Config(Path(__file__).resolve().parent / "_smoke_cfg.json")
    return act, records, cfg


def main():
    act, records, cfg = _sample()
    ai = FakeAI()
    res = nl_query.run_nl_query(ai, act, records, cfg, "这次爬坡多吗？", laps=[], max_rounds=5)

    print("=== 工具调用链路 ===")
    for i, s in enumerate(res["steps"], 1):
        print(f"  {i}. [{'OK' if s['ok'] else 'ERR'}] {s['tool']}({json.dumps(s['args'], ensure_ascii=False)})")
    print("\n=== 最终回答 ===")
    print(res["answer"])
    print("\n=== 自检 ===")
    tools_called = [s["tool"] for s in res["steps"]]
    assert "get_track_summary" in tools_called, "应调用 get_track_summary"
    assert "get_activity_summary" in tools_called, "应调用 get_activity_summary"
    assert res["answer"], "应有最终回答"
    assert res["fallback"] is False, "不应触发降级"
    assert ai.calls == 3, f"应恰好 3 轮对话，实际 {ai.calls}"
    print("ALL_CHECKS_PASSED ✅")


if __name__ == "__main__":
    main()
