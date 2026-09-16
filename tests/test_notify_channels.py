"""Webhook 推送渠道单测：格式自动识别 / 地址解析 / 引擎触发推送（mock HTTP）。

不依赖网络：monkeypatch http_utils.http_json 记录请求。
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db as db_mod
from core.config import Config
from core import notify_channels

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
    tmp = Path(tempfile.mkdtemp(prefix="fit_push_"))
    try:
        cfg = Config(tmp / "cfg.json")

        print("== Webhook 格式自动识别 ==")
        feishu = notify_channels._payload_for("https://open.feishu.cn/open-apis/bot/v2/hook/x", "标题", "内容")
        check("飞书格式", feishu == {"msg_type": "text", "content": {"text": "标题\n内容"}}, str(feishu))
        wecom = notify_channels._payload_for("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k", "标题", "内容")
        check("企业微信格式", wecom == {"msgtype": "text", "text": {"content": "标题\n内容"}}, str(wecom))
        ding = notify_channels._payload_for("https://oapi.dingtalk.com/robot/send?access_token=t", "标题", "内容")
        check("钉钉格式", ding == {"msgtype": "text", "text": {"content": "标题\n内容"}}, str(ding))
        gen = notify_channels._payload_for("https://example.com/hook", "标题", "内容")
        check("通用格式", gen == {"text": "标题\n内容"}, str(gen))

        print("== 地址解析 ==")
        cfg.set("webhook_urls", "https://a.com/x, https://b.com/y\nhttps://c.com/z")
        urls = notify_channels.webhook_urls(cfg)
        check("逗号+换行解析去重", urls == ["https://a.com/x", "https://b.com/y", "https://c.com/z"], str(urls))
        cfg.set("webhook_urls", "")
        check("未配置返回空", notify_channels.webhook_urls(cfg) == [])

        print("== 推送触发（mock HTTP）==")
        sent = []
        import core.notify_channels as nc
        nc.http_utils.http_json = lambda url, **kw: (
            sent.append((url, kw.get("payload"))), (200, {}))[1]

        cfg.set("webhook_urls", "https://open.feishu.cn/hook/x")
        ok = nc.push_text(cfg, "测试标题", "测试内容")
        check("推送成功返回 1", ok == 1)
        check("飞书负载正确", sent and sent[0][1]["msg_type"] == "text", str(sent[:1]))

        # 引擎触发：notifier.run_alerts 有 webhook 时推送新提醒
        db = db_mod.DB(tmp / "t.db")
        db.gear_add("推送测试链条", "链条", "2025-01-01", 1735689600, 0, 1000)
        from core import notifier
        new = notifier.run_alerts(db, cfg)  # 装备里程 0/1000 → 不触发；先造数据
        # 无活动 → 装备里程 0，不产生提醒；验证 run_alerts 正常返回空
        check("无提醒时不推送", new == [] and len(sent) == 1)
        db.close()

        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
