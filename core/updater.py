"""自更新引擎：检查更新 / 增量下载 / 原子应用替换（helper 自更新）。

设计要点：
- 发布产物为 PyInstaller onedir 目录（约 560MB，其中 PySide6 依赖占大头）。
  Python 代码（exe + _internal 的 PYZ/base_library.zip）与资源文件合称
  「应用层」，依赖库（PySide6/shiboken6）单独用指纹判断。
- 增量更新：manifest 携带应用层文件清单（path+sha256），客户端对比本地
  hash 只下载变化的文件（通常仅 exe+PYZ，几 MB）；依赖指纹不一致时提示
  需完整包（url_full）。
- 原子替换：运行中的 exe 被锁，先把自身复制为 .update/updater.exe 的
  helper，主进程退出后由 helper 完成覆盖并重启主程序、清理临时目录。
- 所有网络读写走 http_utils（复用 SSL 降级策略与超时控制）。
"""
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import http_utils

log = logging.getLogger("fit.updater")

# 依赖层目录（不参与增量清单，用指纹整体判断）——相对 exe_dir 的目录前缀
_DEPS_DIRS = ("_internal/PySide6", "_internal/shiboken6")
# 依赖指纹参考文件（代表性 DLL，发布端与客户端一致）
_DEPS_FILES = (
    "_internal/PySide6/Qt6Core.dll",
    "_internal/PySide6/Qt6Gui.dll",
    "_internal/PySide6/Qt6Widgets.dll",
    "_internal/PySide6/Qt6Charts.dll",
    "_internal/PySide6/Qt6WebEngineCore.dll",
    "_internal/shiboken6/shiboken6.abi3.dll",
)
_FILES_PREFIX = "files"  # 发布目录下文件包的子目录名
_PENDING_DIR = ".update"


class UpdaterError(Exception):
    pass


# ---------------- 版本比较 ----------------
def parse_version(v):
    """'1.2.0' / 'v1.2.0' → (1, 2, 0)；非数字段忽略（如 1.2.0-beta → (1,2,0,0,beta)）。"""
    parts = []
    for seg in str(v or "").lstrip("vV").replace("-", ".").split("."):
        if seg.isdigit():
            parts.append(int(seg))
        else:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def compare_versions(a, b):
    """返回 1(a>b) / 0(=) / -1(a<b)。"""
    pa, pb = parse_version(a), parse_version(b)
    return (pa > pb) - (pa < pb)


# ---------------- 本地文件状态 ----------------
def app_layer_paths(exe_dir):
    """应用层文件相对路径列表：排除依赖层目录（PySide6/shiboken6）。发布端据此打包。"""
    out = []
    base = Path(exe_dir)
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base).as_posix()
        if any(rel.startswith(d + "/") for d in _DEPS_DIRS):
            continue
        out.append(rel)
    return out


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def deps_fingerprint(exe_dir):
    """依赖层指纹：关键 DLL 的 sha256 前 24 位拼接；文件缺失返回空串（无法判断）。"""
    base = Path(exe_dir)
    parts = []
    for rel in _DEPS_FILES:
        p = base / rel
        if not p.exists():
            return ""
        parts.append(sha256_file(p)[:24])
    return "|".join(parts)


# ---------------- manifest ----------------
def fetch_manifest(update_url, timeout=15):
    """拉取更新清单。update_url 指向 latest.json（HTTP 或 file://）。"""
    if not update_url:
        raise UpdaterError("未配置更新源地址")
    try:
        status, obj = http_utils.http_json(update_url, timeout=timeout)
    except Exception as e:  # HTTPError / URLError / 本地 file:// 异常统一转 UpdaterError
        raise UpdaterError(f"获取更新清单失败: {e}")
    if status not in (None, 200):
        # file:// 本地协议下 status 可能为 None（视为成功）；HTTP 非 200 视为失败
        raise UpdaterError(f"更新清单返回状态 {status}")
    if not isinstance(obj, dict) or not obj.get("version"):
        raise UpdaterError("更新清单格式无效")
    return obj


def _manifest_base_url(update_url):
    """manifest 所在目录的 URL（用于拼接相对下载地址，暂未使用，保留备用）。"""
    u = (update_url or "").strip()
    return u[: u.rfind("/")] if "/" in u else u


def _abs_url(manifest_url, u):
    """把相对下载地址解析为绝对 URL（相对 manifest 所在目录）；已是完整 URL 则原样返回。"""
    u = (u or "").strip()
    if not u:
        return ""
    if "://" in u or u.startswith("file:"):
        return u
    return f"{_manifest_base_url(manifest_url)}/{u}"


def should_update(local_version, manifest, ignored_version=""):
    """有更高版本且未被忽略，返回 True。"""
    if compare_versions(manifest.get("version"), local_version) > 0:
        return manifest.get("version") != ignored_version
    return False


def plan_update(local_version, exe_dir, manifest, manifest_url=""):
    """制定更新计划。

    返回 {"needs": bool, "full": bool, "url": str, "sha256": str, "size": int}。
    full=True 表示依赖库指纹不一致，需下载全量包（url_full）；
    否则下载增量包（url_incremental，内含应用层全部文件，几 MB 级）。
    依赖变更但无全量包时返回 needs=False（无法安全更新）。
    """
    if not should_update(local_version, manifest):
        return {"needs": False, "full": False, "url": "", "sha256": "", "size": 0}
    if manifest.get("deps_fingerprint"):
        local_deps = deps_fingerprint(exe_dir)
        if not local_deps or local_deps != manifest["deps_fingerprint"]:
            if manifest.get("url_full"):
                return {"needs": True, "full": True,
                        "url": _abs_url(manifest_url, manifest["url_full"]),
                        "sha256": manifest.get("sha256_full") or "",
                        "size": manifest.get("size_full") or 0}
            return {"needs": False, "full": False, "url": "", "sha256": "", "size": 0}
    if not manifest.get("url_incremental"):
        return {"needs": False, "full": False, "url": "", "sha256": "", "size": 0}
    return {"needs": True, "full": False,
            "url": _abs_url(manifest_url, manifest["url_incremental"]),
            "sha256": manifest.get("sha256_incremental") or "",
            "size": manifest.get("size_incremental") or 0}


def download_file(url, dest, on_progress=None, timeout=300):
    """流式下载到临时文件（同目录原子改名），进度回调 (done_bytes, total_bytes)。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err = None
    started = time.monotonic()
    for ctx, budget in http_utils._ssl_contexts():
        remain = max(10, timeout - (time.monotonic() - started))
        if budget:
            remain = min(remain, budget)
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "FitAnalyzerUpdater/1.0")
            with urllib.request.urlopen(req, timeout=remain, context=ctx) as resp:
                total = int(resp.headers.get("Content-Length") or 0) or None
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        b = resp.read(1 << 16)
                        if not b:
                            break
                        f.write(b)
                        done += len(b)
                        if on_progress:
                            on_progress(done, total)
            tmp.replace(dest)
            return True
        except Exception as e:
            last_err = e
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    raise UpdaterError(f"下载失败: {last_err}")


# ---------------- 应用更新（延迟替换：系统 cmd 脚本，不复制 helper） ----------------
def stage_update_dir(exe_dir):
    """返回暂存目录（.update/staged），存放下载的应用层文件。"""
    d = Path(exe_dir) / _PENDING_DIR / "staged"
    shutil.rmtree(Path(exe_dir) / _PENDING_DIR, ignore_errors=True)
    return d


def build_update_bat(exe_dir, exe_name):
    """生成延迟替换批处理（.update/apply_update.bat），返回其路径。

    脚本用相对定位（%~dp0.. = 程序目录）与 GBK 编码，避开中文路径乱码。
    """
    exe_dir = Path(exe_dir)
    pending = exe_dir / _PENDING_DIR
    pending.mkdir(parents=True, exist_ok=True)
    bat = pending / "apply_update.bat"
    bat.write_text(
        "@echo off\r\n"
        "rem 等待主进程退出（2 秒）\r\n"
        'timeout /t 2 /nobreak >nul\r\n'
        'cd /d "%~dp0.."\r\n'
        'xcopy /y /s /q ".update\\staged\\*" ".\\" >nul\r\n'
        f'start "" "{exe_name}"\r\n'
        'cd /d "%TEMP%"\r\n'
        'rd /s /q ".update" >nul 2>nul\r\n'
        'del "%~f0" >nul 2>nul\r\n',
        encoding="gbk", errors="replace")
    return bat


def apply_update_async(exe_dir):
    """生成延迟替换脚本并交给系统 cmd 执行；主进程随后退出。

    为什么不用「复制 exe 副本当 helper」：onedir 打包的 exe 依赖旁边
    _internal 目录（python313.dll/PYZ 等），孤立的 exe 副本无法启动
    （Failed to load Python DLL）。改用系统自带 cmd 执行批处理：
    等待主进程退出 → xcopy 覆盖应用层文件 → 重启主程序 → 清理。
    """
    exe_dir = Path(exe_dir)
    bat = build_update_bat(exe_dir, Path(sys.executable).name)
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            cwd=str(exe_dir), creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
        log.info("已生成延迟替换脚本并启动：%s", bat)
    except OSError as e:
        raise UpdaterError(f"启动更新脚本失败: {e}")


# ---------------- 顶层便捷入口 ----------------
def check_for_update(update_url, exe_dir, current_version, ignored_version=""):
    """拉取清单并返回更新计划；无更新/出错返回 None（错误写日志不抛）。"""
    try:
        manifest = fetch_manifest(update_url)
    except UpdaterError as e:
        log.info("检查更新：%s", e)
        return None
    if not should_update(current_version, manifest, ignored_version):
        return None
    plan = plan_update(current_version, exe_dir, manifest, manifest_url=update_url)
    plan["manifest"] = manifest
    return plan if plan.get("needs") else None
