"""健壮 HTTP JSON 客户端（标准库）。"""
import json
import logging
import ssl
import time
import urllib.error
import urllib.request

log = logging.getLogger("fit.http")

# HTTPS 证书校验降级开关（默认关闭）。
# 部分网络环境（代理/TLS 拦截）下默认证书校验会失败或挂起，允许降级可恢复
# 连通；但降级 = 不校验任何证书，存在中间人风险（API Key 等凭据可能被截获）。
# 因此默认关闭，仅当用户在「设置 → 诊断与日志」显式开启后才启用降级重试，
# 且首次降级时打 WARNING 留痕。应用启动时由 app.py 按配置接线。
_INSECURE_FALLBACK = False
_warned_insecure = False


def set_insecure_fallback(enabled):
    """开关「证书校验失败时降级为不校验」（默认 False，应用启动时按配置调用）。"""
    global _INSECURE_FALLBACK
    _INSECURE_FALLBACK = bool(enabled)


class HTTPError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code  # HTTP 状态码（非 HTTP 层错误为 None），供调用方结构化判断


def _has_ssl_failure(err):
    """沿异常链（URLError.reason / __cause__）检查是否为 SSL 证书类失败。"""
    seen = set()
    while err is not None and id(err) not in seen:
        seen.add(id(err))
        if isinstance(err, ssl.SSLError):
            return True
        err = getattr(err, "reason", None) or getattr(err, "__cause__", None)
    return False


def _ssl_contexts():
    """产出 (ssl_context, 超时预算) 序列。

    默认只做标准证书校验；仅当 _INSECURE_FALLBACK 开启时，才追加一次
    不校验证书的重试（首次进入打 WARNING 留痕），用于代理/TLS 拦截环境应急。"""
    try:
        yield ssl.create_default_context(), 8
    except Exception:
        pass
    if _INSECURE_FALLBACK:
        global _warned_insecure
        if not _warned_insecure:
            _warned_insecure = True
            log.warning(
                "HTTPS 证书校验失败，已按设置降级为不校验证书（存在中间人风险）；"
                "如非刻意开启请到 设置→诊断与日志 关闭"
            )
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
            last_err = HTTPError(f"HTTP {e.code} {e.reason}: {detail}", code=e.code)
            break
        except Exception as e:
            last_err = e
    err = last_err or HTTPError("网络请求失败")
    # SSL 证书校验失败且未开启降级时，给出可操作的提示（默认安全，不静默放行）
    if _has_ssl_failure(err) and not _INSECURE_FALLBACK:
        err = HTTPError(
            f"{err}（提示：若处于代理/TLS 拦截网络，可在 设置→诊断与日志 勾选"
            f"「HTTPS 证书校验失败时降级」后重试）"
        )
    raise err
