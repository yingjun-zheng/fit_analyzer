"""AI 客户端：兼容 OpenAI Chat Completions 协议（Ollama / LM Studio / vLLM / DeepSeek / OpenAI 等）。

所有请求发往用户自己配置的地址，本软件不内置任何收费接口。
"""
import logging
import time

from . import http_utils

log = logging.getLogger("fit.ai")


class AIError(Exception):
    pass


def normalize_base_url(base_url):
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/v1") or "/v1/" in url:
        return url
    return url + "/v1"


class AIClient:
    def __init__(self, base_url, api_key="", model="", temperature=0.4, timeout=120):
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key or ""
        self.model = model or ""
        self.temperature = temperature
        self.timeout = timeout

    def _headers(self):
        h = {}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def chat(self, messages, model=None, temperature=None, timeout=None):
        """发送对话，返回回复文本（content 为空时回退 reasoning）。"""
        r = self.chat_full(messages, model=model, temperature=temperature, timeout=timeout)
        return r["content"] or r["reasoning"] or ""

    def chat_full(self, messages, model=None, temperature=None, timeout=None):
        """发送对话，返回 {"content": 结论, "reasoning": 思考过程}。"""
        if not self.base_url:
            raise AIError("未配置 AI 服务地址（设置 → AI）")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
            "max_tokens": 4096,  # 推理模型（qwen3.5 等）思考 + 结论都容纳，避免截断
        }
        log.info("AI 请求 -> %s model=%s messages=%d", self.base_url, payload["model"], len(messages))
        t0 = time.time()
        try:
            status, obj = http_utils.http_json(url, timeout=timeout or self.timeout, method="POST", payload=payload, headers=self._headers())
        except http_utils.HTTPError as e:
            msg = str(e)
            hint = ""
            if "404" in msg and "not found" in msg.lower():
                # 模型名不存在：把服务器可用模型列出来方便用户自查
                try:
                    t = self.test()
                    if t.get("ok") and t.get("models"):
                        hint = f"。服务器上可用的模型：{'、'.join(t['models'])}（请在 设置→AI 中修改模型名称，或用 ollama pull <模型> 拉取）"
                except Exception:
                    pass
            raise AIError(f"AI 服务请求失败: {msg}{hint}")
        if status != 200:
            msg = obj.get("error", {}).get("message") if isinstance(obj, dict) else ""
            raise AIError(f"AI 服务返回状态 {status}: {msg}")
        try:
            message = obj["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise AIError("AI 响应格式异常")
        content = message.get("content") or ""
        reasoning = message.get("reasoning") or message.get("reasoning_content") or ""  # DeepSeek 用 reasoning_content
        log.info("AI 响应成功 耗时=%.1fs 内容=%d 思考=%d", time.time() - t0, len(content), len(reasoning))
        return {"content": content, "reasoning": reasoning}

    def test(self):
        if not self.base_url:
            return {"ok": False, "error": "未配置服务地址"}
        url = f"{self.base_url}/models"
        try:
            status, obj = http_utils.http_json(url, timeout=15, headers=self._headers())
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if status != 200:
            return {"ok": False, "error": f"HTTP {status}"}
        models = []
        if isinstance(obj, dict):
            for m in (obj.get("data") or [])[:20]:
                mid = m.get("id") or m.get("name") or ""
                if mid:
                    models.append(mid)
        return {"ok": True, "models": models, "configured_model": self.model}
