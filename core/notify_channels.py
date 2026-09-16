"""Webhook 推送渠道：把提醒发到飞书 / 企业微信 / 钉钉 群机器人。

- 配置：config.webhook_urls（多个地址用逗号分隔）
- 自动识别格式：URL 含 feishu → 飞书；qyapi/weixin → 企业微信；
  dingtalk → 钉钉；其他 → 通用 {"text": "..."}
- 失败只记日志不抛（推送是尽力而为，不影响主流程）
"""
import logging

from . import http_utils

log = logging.getLogger("fit.push")


def _payload_for(url, title, body):
    text = f"{title}\n{body}" if title else body
    u = (url or "").lower()
    if "feishu" in u or "larksuite" in u:
        return {"msg_type": "text", "content": {"text": text}}
    if "qyapi" in u or "weixin" in u:
        return {"msgtype": "text", "text": {"content": text}}
    if "dingtalk" in u or "oapi" in u:
        return {"msgtype": "text", "text": {"content": text}}
    return {"text": text}  # 通用格式


def webhook_urls(config):
    """解析配置中的 webhook 地址列表（逗号/换行分隔）。"""
    raw = str(config.get("webhook_urls") or "")
    out = []
    for u in raw.replace("\n", ",").split(","):
        u = u.strip()
        if u and u not in out:
            out.append(u)
    return out


def push_text(config, title, body):
    """向所有已配置 webhook 推送一条文本（尽力而为）。返回成功数。"""
    urls = webhook_urls(config)
    if not urls:
        return 0
    ok = 0
    for url in urls:
        try:
            status, _ = http_utils.http_json(
                url, timeout=10, method="POST", payload=_payload_for(url, title, body))
            if status in (None, 200):
                ok += 1
            else:
                log.warning("Webhook 推送返回状态 %s（%s）", status, url)
        except Exception as e:  # noqa: BLE001
            log.warning("Webhook 推送失败（%s）：%s", url, e)
    if ok:
        log.info("Webhook 推送成功 %d/%d 条", ok, len(urls))
    return ok


def push_alerts(config, alerts):
    """推送一批提醒（每条约 200 字截断）。"""
    for a in alerts or []:
        body = (a.get("body") or "")
        if len(body) > 200:
            body = body[:200] + "…"
        push_text(config, a.get("title") or "提醒", body)
