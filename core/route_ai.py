"""路书 AI 解读：把路书结构化数据交给 LLM，产出难度分析与骑行建议。

复用 fit_analyzer 的 AIClient（Ollama / DeepSeek / OpenAI 兼容端点）。
"""
from . import route as route_mod


_SYSTEM = (
    "你是资深骑行路线规划师。基于给定的路书结构化数据，用中文给出简洁、实用的分析，"
    "不要用 Markdown 标题，直接分段叙述。分析要点：1) 整体难度定级与适合人群；"
    "2) 爬坡段逐个点评（坡度、长度、应对策略）；3) 补给与休息建议；"
    "4) 安全提醒（下坡、弯道、交通）。控制在 300 字以内。"
)


def analyze_route(ai, route_or_summary, question=None):
    """调用 LLM 解读路书。

    ai: AIClient 实例。
    route_or_summary: route dict 或 summarize() 返回的文本。
    question: 用户附加问题（可选）。
    返回 LLM 回答文本；失败时返回 None（不抛异常，便于 GUI 降级展示）。
    """
    if isinstance(route_or_summary, dict):
        summary = route_mod.summarize(route_or_summary)
        name = route_or_summary.get("name", "路书")
    else:
        summary = str(route_or_summary)
        name = "路书"

    user = f"以下是路书「{name}」的结构化数据：\n\n{summary}"
    if question and question.strip():
        user += f"\n\n用户额外想了解：{question.strip()}"

    try:
        answer = ai.chat(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": user}],
            max_tokens=900,
            reasoning_effort="low",
        )
    except Exception:
        return None
    return (answer or "").strip() or None
