"""健壮 HTTP JSON 客户端（标准库）。"""
import json
import logging
import ssl
import time
import urllib.error
import urllib.request

log = logging.getLogger("fit.http")


class HTTPError(Exception):
    pass


def _ssl_contexts():
    """默认证书优先，但给短预算（8s）；失败/卡住后回退到不校验证书。
    部分网络环境（代理/TLS 拦截）下默认证书握手会挂起，快速回退可避免整体超时。"""
    try:
        yield ssl.create_default_context(), 8
    except Exception:
        pass
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    yield ctx, None  # 回退尝试使用完整剩余超时


def http_json(url, timeout=30, method="GET", payload=None, headers=None):
    last_err = None
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    started = time.monotonic()
    for ctx, budget in _ssl_contexts():
        remain = max(5, timeout - (time.monotonic() - started))
        if budget:
            remain = min(remain, budget)
        try:
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("User-Agent", "FitAnalyzer/1.0")
            req.add_header("Accept", "application/json")
            if payload is not None:
                req.add_header("Content-Type", "application/json")
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=remain, context=ctx) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                if "json" in ctype or body[:1] in (b"{", b"["):
                    return resp.status, json.loads(body.decode("utf-8", "replace"))
                return resp.status, body
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            last_err = HTTPError(f"HTTP {e.code} {e.reason}: {detail}")
            break
        except Exception as e:
            last_err = e
    raise last_err or HTTPError("网络请求失败")
