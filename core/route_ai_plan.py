"""AI 需求拆解：把自然语言骑行需求拆成结构化规划参数。

例：「从北京到天津，走国道，每 35km 休一次，要在有补给的地方」
→ {origin_city, dest_city, segment_km, prefer_highway, prefer_rest_type, ...}

LLM 失败或返回无法解析时返回 None，由上层降级到表单输入。
"""
import json

_SYSTEM = (
    "你是骑行路线规划助手。把用户的自然语言骑行需求拆解成 JSON 参数。"
    "只输出一个 JSON 对象，不要输出任何解释文字、不要用 Markdown 代码块。"
    "字段：origin_city(起点城市/地名，string)、dest_city(终点城市/地名，string)、"
    "segment_km(单段最大里程，number，缺省 30)、"
    "max_total_km(全程最大里程，number，缺省 150)、"
    "avoid_highway(是否避开高速，boolean，缺省 true)、"
    "rest_type(休息点偏好类型，string，如 便利店/餐馆/加油站/住宿，缺省 便利店)、"
    "start_point(可选，具体起点地名)、end_point(可选，具体终点地名)。"
    "示例输入「北京到天津走国道每35公里休息」→ "
    '{"origin_city":"北京","dest_city":"天津","segment_km":35,"avoid_highway":true,"rest_type":"便利店"}'
)


def parse_requirement(ai, text):
    """调用 LLM 把需求文字拆成结构化参数。

    ai: AIClient 实例。
    text: 用户输入的自然语言需求。
    返回 dict（含 origin_city/dest_city/segment_km 等）；失败返回 None。
    """
    if not ai or not text or not text.strip():
        return None
    try:
        answer = ai.chat(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": text.strip()}],
            max_tokens=400,
            reasoning_effort="low",
        )
    except Exception:
        return None

    if not answer:
        return None

    # 提取 JSON（容忍 LLM 偶尔带 ```json 包装）
    s = answer.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.strip()
        if s.startswith("json"):
            s = s[4:].strip()

    # 截取第一个 { 到最后一个 }
    lo = s.find("{")
    hi = s.rfind("}")
    if lo == -1 or hi == -1 or hi <= lo:
        return None
    try:
        obj = json.loads(s[lo:hi + 1])
    except Exception:
        return None

    if not isinstance(obj, dict):
        return None
    # 校验关键字段
    if not obj.get("origin_city") or not obj.get("dest_city"):
        return None
    return obj
