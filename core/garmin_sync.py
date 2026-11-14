"""佳明云同步适配器（P4 路线 A）：登录 Garmin Connect，增量下载原始 FIT。

- 下载目录 = P3 监控目录（auto_import_dir）时，自动导入零改动接管；
  未配置监控目录则落到 <data_dir>/garmin_sync。
- 增量依据：activityId 集合持久化在 state 文件，重复同步只拉新活动。
- 网络层可注入（client_factory），单元测试用 fake client，不碰真实网络。
- 依赖 garminconnect（非官方接口，登录态 tokenstore 持久化后无需重复 MFA）；
  失败静默降级：同步失败只记日志/提示，绝不影响主程序其它功能。
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("fit")

_SAFE_NAME = re.compile(r'[\\/:*?"<>|\s]+')
_STATE_VERSION = 1


class GarminSyncError(Exception):
    """同步失败（凭据错误/网络/MFA 被拒等），带用户可读信息。"""


# ---------------- 状态持久化 ----------------

def default_state_path(data_dir: Path) -> Path:
    return Path(data_dir) / "garmin_sync_state.json"


def load_state(path: Path) -> dict:
    try:
        st = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(st, dict) and st.get("v") == _STATE_VERSION:
            return st
    except Exception:
        pass
    return {"v": _STATE_VERSION, "downloaded": {}}


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------- 文件名与解包 ----------------

def fit_filename(activity: dict) -> str:
    """活动 -> 安全文件名：2026-09-13_074500_12345678.fit（同秒同 id 理论不撞）。"""
    aid = str(activity.get("activityId") or activity.get("id") or "").strip()
    if not aid:
        raise GarminSyncError("活动缺少 activityId")
    st = str(activity.get("startTimeLocal") or activity.get("startTime") or "")
    st = _SAFE_NAME.sub("_", st.replace(":", "").replace(" ", "_"))
    return f"{st or 'activity'}_{aid}.fit"


def extract_fit(data: bytes) -> bytes:
    """下载字节 -> FIT 字节。ORIGINAL 格式可能是 zip（内含一个 .fit），也可能是裸 FIT。"""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            fits = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not fits:
                raise GarminSyncError("下载包内没有 FIT 文件")
            return zf.read(fits[0])
    return data


# ---------------- 核心同步 ----------------

def _fetch_all_activities(client: Any, page_size: int = 100,
                          max_activities: int = 2000) -> list[dict]:
    """分页拉活动列表（新→旧），不足一页即止。"""
    acts: list[dict] = []
    start = 0
    while start < max_activities:
        page = client.get_activities(start, page_size)
        if not page:
            break
        acts.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return acts


def sync(client_factory: Callable, download_dir: Path, state_path: Path,
         max_activities: int = 2000,
         progress: Callable[[str], None] | None = None) -> dict:
    """执行一次增量同步。

    client_factory(prompt_mfa) -> 已登录 client（真实实现见 make_client；
    测试注入 fake）。prompt_mfa 为返回验证码字符串的回调（GUI 弹窗）。

    返回 {"total": 列表活动数, "downloaded": n, "skipped": n,
          "errors": [str], "files": [新下载文件路径]}
    """
    download_dir = Path(download_dir)
    state = load_state(state_path)
    downloaded_ids: dict = state.setdefault("downloaded", {})

    def _p(msg: str):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    _p("连接佳明云端…")
    client = client_factory(lambda: _ask_mfa_external())

    _p("获取活动列表…")
    acts = _fetch_all_activities(client, max_activities=max_activities)
    _p(f"云端共 {len(acts)} 条活动，比对增量…")

    files: list[str] = []
    errors: list[str] = []
    new_acts = [a for a in acts
                if str(a.get("activityId") or a.get("id")) not in downloaded_ids]
    for i, act in enumerate(new_acts, 1):
        aid = str(act.get("activityId") or act.get("id"))
        name = fit_filename(act)
        try:
            _p(f"下载 {i}/{len(new_acts)}：{name}")
            data = extract_fit(client.download_activity(aid))
            download_dir.mkdir(parents=True, exist_ok=True)
            fpath = download_dir / name
            fpath.write_bytes(data)
            downloaded_ids[aid] = name
            files.append(str(fpath))
            save_state(state_path, state)  # 每次落盘，中断不重复下载
        except Exception as e:  # 单条失败不中断整体
            log.warning("佳明活动 %s 下载失败：%s", aid, e)
            errors.append(f"{name}: {e}")

    _p("同步完成")
    return {"total": len(acts), "downloaded": len(files),
            "skipped": len(acts) - len(new_acts), "errors": errors, "files": files}


# MFA 回调由宿主（GUI）在 make_client 时注入；纯逻辑层留一个默认实现占位。
def _ask_mfa_external() -> str:  # pragma: no cover - 由 make_client 覆盖
    raise GarminSyncError("需要佳明验证码，但当前环境无法弹出输入框")


# ---------------- 真实客户端 ----------------

def make_client(email: str, password: str, is_cn: bool, tokenstore: Path,
                prompt_mfa: Callable[[], str] | None = None):
    """构造并登录 Garmin Connect 客户端（tokenstore 持久化登录态）。"""
    from garminconnect import Garmin  # 局部导入：未使用云同步的用户不付加载成本

    client = Garmin(email=email, password=password, is_cn=is_cn,
                    prompt_mfa=prompt_mfa)
    client.login(tokenstore=str(tokenstore))
    return client
