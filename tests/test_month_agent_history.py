"""多轮会话单元测试：month_agent 的 history 注入/返回、跨月查询、结果截断。

不依赖真实 AI/网络：FakeAI 按脚本返回 tool_calls 与最终回答。
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db as db_mod
from core.month_agent import append_round, run_month_query, _month_activities

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


class FakeAI:
    """按脚本依次返回 chat_full/chat_full_stream 结果；记录每次收到的 messages 与事件。"""

    def __init__(self, script):
        self.script = list(script)
        self.chat_full_calls = []
        self.events = []

    def _pop(self):
        return self.script.pop(0)

    def chat_full(self, messages, tools=None, **kw):
        self.chat_full_calls.append([dict(m) for m in messages])
        return self._pop()

    def chat_full_stream(self, messages, tools=None, on_event=None, **kw):
        self.chat_full_calls.append([dict(m) for m in messages])
        resp = self._pop()
        if on_event:
            # 模拟流式：思考与回答拆成两段增量回调
            if resp.get("reasoning"):
                on_event("thinking_delta", resp["reasoning"][:2])
                on_event("thinking_delta", resp["reasoning"][2:])
            if resp.get("content"):
                on_event("delta", resp["content"][:1])
                on_event("delta", resp["content"][1:])
        return resp

    def chat(self, messages, **kw):
        return "（最终回答）"


def make_db(path):
    """临时库：2026-09 两条、2026-08 一条活动。"""
    db = db_mod.DB(path)
    conn = db.conn
    rows = [
        ("h-a", "2026-09-05 08:00:00", 1757034600, 50000.0),
        ("h-b", "2026-09-20 08:00:00", 1758328800, 20000.0),
        ("h-c", "2026-08-10 08:00:00", 1754787600, 30000.0),
    ]
    for h, st, ts, dist in rows:
        conn.execute(
            "INSERT INTO activities (file_hash, file_name, name, device, sport,"
            " start_time, start_ts, total_distance_m, record_count, imported_at, month)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (h, f"{h}.fit", f"骑行-{h}", "iGPSPORT", "cycling", st, ts, dist, 10,
             "2026-09-15 00:00:00", st[:7]))
    conn.commit()
    return db


def main():
    tmp = Path(tempfile.mkdtemp(prefix="fit_hist_"))
    try:
        db = make_db(tmp / "t.db")

        print("== history 注入与返回 ==")
        hist = [{"role": "user", "content": "早前问题"},
                {"role": "assistant", "content": "早前回答"}]
        fake = FakeAI([{"content": "回答A", "reasoning": "", "tool_calls": []}])
        r = run_month_query(fake, db, "2026-09", {}, "本月如何", history=hist)
        first = fake.chat_full_calls[0]
        check("system 在首位", first[0]["role"] == "system")
        check("历史被注入 messages",
              any(m.get("content") == "早前问题" for m in first)
              and any(m.get("content") == "早前回答" for m in first))
        check("本轮提问在历史之后", first[-1] == {"role": "user", "content": "本月如何"})
        check("返回 history 含本轮问答",
              len(r["history"]) == 4 and r["history"][-1]["content"] == "回答A"
              and r["history"][-2]["content"] == "本月如何")

        print("== 跨月查询（模型传 month 参数）==")
        fake = FakeAI([
            {"content": "", "reasoning": "", "tool_calls": [
                {"id": "c1", "name": "get_month_overview", "arguments": {"month": "2026-08"}}]},
            {"content": "8月共30.0km", "reasoning": "", "tool_calls": []},
        ])
        r = run_month_query(fake, db, "2026-09", {}, "那8月呢", history=r["history"])
        second = fake.chat_full_calls[1]
        tool_msgs = [m for m in second if m.get("role") == "tool"]
        check("工具结果包含 8 月数据", "2026-08" in tool_msgs[0]["content"]
              and "30.0" in tool_msgs[0]["content"], tool_msgs[0]["content"][:120])
        check("工具调用标记成功", r["steps"][0]["ok"] is True)
        check("会话历史继续累积", len(r["history"]) == 6)

        print("== 非法 month 回退默认月份 ==")
        fake = FakeAI([
            {"content": "", "reasoning": "", "tool_calls": [
                {"id": "c2", "name": "get_month_overview", "arguments": {"month": "abc"}}]},
            {"content": "ok", "reasoning": "", "tool_calls": []},
        ])
        r = run_month_query(fake, db, "2026-09", {}, "概览")
        second = fake.chat_full_calls[1]
        tool_msgs = [m for m in second if m.get("role") == "tool"]
        check("非法 month 回退 2026-09", "2026-09" in tool_msgs[0]["content"])

        print("== 工具结果截断 ==")
        fake = FakeAI([
            {"content": "", "reasoning": "", "tool_calls": [
                {"id": "c3", "name": "get_month_activities", "arguments": {}}]},
            {"content": "ok", "reasoning": "", "tool_calls": []},
        ])
        # 把结果撑过截断阈值：直接验证 messages 中 tool 内容不超限
        from core import month_agent as ma
        ma.TOOL_RESULT_MAX_CHARS = 50  # 临时调小阈值验证截断逻辑
        run_month_query(fake, db, "2026-09", {}, "列表")
        second = fake.chat_full_calls[1]
        tool_msgs = [m for m in second if m.get("role") == "tool"]
        check("超长工具结果被截断", len(tool_msgs[0]["content"]) <= 50 + 20
              and "已截断" in tool_msgs[0]["content"], tool_msgs[0]["content"])
        ma.TOOL_RESULT_MAX_CHARS = 6000

        print("== 历史轮数上限 ==")
        h = []
        for i in range(12):
            h = append_round(h, f"问{i}", f"答{i}")
        check("历史最多保留 8 轮（16 条）", len(h) == 16, f"len={len(h)}")
        check("保留的是最近轮次", h[-1]["content"] == "答11" and h[-2]["content"] == "问11")

        print("== 活动列表条数上限 ==")
        for i in range(70):
            db.conn.execute(
                "INSERT INTO activities (file_hash, file_name, name, sport, start_time,"
                " start_ts, total_distance_m, record_count, imported_at, month)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"x{i}", f"x{i}.fit", "批量", "cycling", f"2026-07-{(i % 28) + 1:02d} 08:00:00",
                 1751300000 + i * 86400, 10000.0, 5, "2026-09-15 00:00:00", "2026-07"))
        db.conn.commit()
        acts = _month_activities(db, "2026-07")
        check("70 条活动只返回 60 条", acts["shown"] == 60 and acts["count"] == 70,
              f"shown={acts.get('shown')}")
        check("截断附提示", "note" in acts)

        print("== 流式路径（on_event）==")
        from core import month_agent as ma
        events = []
        fake = FakeAI([
            {"content": "", "reasoning": "", "tool_calls": [
                {"id": "s1", "name": "get_month_overview", "arguments": {}}]},
            {"content": "九月概览好的", "reasoning": "推理中", "tool_calls": []},
        ])
        r = run_month_query(fake, db, "2026-09", {}, "本月概览", on_event=events.append)
        kinds = [e[0] for e in events]
        check("事件包含 round/tool/tool_result/delta",
              "round" in kinds and "tool" in kinds and "tool_result" in kinds and "delta" in kinds,
              str(kinds))
        check("工具完成事件 ok=True", any(e[0] == "tool_result" and e[2] is True for e in events))
        check("回答增量拼接=完整回答",
              "".join(e[1] for e in events if e[0] == "delta") == "九月概览好的")
        check("思考增量拼接=完整思考",
              "".join(e[1] for e in events if e[0] == "thinking_delta") == "推理中")
        check("流式返回结构与非流式一致",
              r["answer"] == "九月概览好的" and r["steps"][0]["ok"] is True and "history" in r)

        print("== SSE 解析（iter_sse_data）==")
        from core.http_utils import iter_sse_data

        class FakeResp:
            def __init__(self, lines):
                self.lines = lines

            def __iter__(self):
                return iter(self.lines)

        sse = FakeResp([
            b'data: {"choices":[{"delta":{"content":"A"}}]}',
            b'',
            b': keep-alive',
            b'data: not-json',          # 坏行跳过
            b'data: {"choices":[{"delta":{"content":"B"}}]}',
            b'data: [DONE]',
            b'data: {"after":"done"}',  # DONE 后不应出现
        ])
        objs = list(iter_sse_data(sse))
        check("SSE 解析出 2 个有效块", len(objs) == 2, str(objs))
        check("SSE 增量内容正确",
              "".join((o["choices"][0]["delta"].get("content") or "") for o in objs) == "AB")
        db.close()

        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
