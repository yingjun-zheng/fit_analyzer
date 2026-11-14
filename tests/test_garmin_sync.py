"""佳明云同步单元测试：fake client 全链路，不碰真实网络。

运行：.venv/Scripts/python.exe tests/test_garmin_sync.py
"""
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import garmin_sync as gs

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def make_zip_bytes(inner_name="2026-09-13_074500.ACTIVITY.fit", payload=b"FAKE-FIT-DATA"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, payload)
    return buf.getvalue()


class FakeClient:
    """模拟 garminconnect.Garmin：分页列表 + 下载。"""

    def __init__(self, activities: list[dict], blobs: dict[str, bytes],
                 fail_ids: set[str] | None = None):
        self.acts = activities
        self.blobs = blobs
        self.fail_ids = fail_ids or set()
        self.downloaded: list[str] = []

    def get_activities(self, start: int, limit: int):
        return self.acts[start:start + limit]

    def download_activity(self, activity_id, dl_fmt=None):
        aid = str(activity_id)
        if aid in self.fail_ids:
            raise RuntimeError("network boom")
        self.downloaded.append(aid)
        return self.blobs[aid]


def act(aid, t="2026-09-13 07:45:00", name="晨骑"):
    return {"activityId": aid, "activityName": name, "startTimeLocal": t}


def run_sync(activities, blobs, tmp: Path, fail_ids=None, state=None):
    ddir = tmp / "dl"
    spath = tmp / "state.json"
    if state is not None:
        spath.write_text(json.dumps(state), encoding="utf-8")
    factory = lambda prompt: FakeClient(activities, blobs, fail_ids)
    return gs.sync(client_factory=factory, download_dir=ddir, state_path=spath,
                   progress=lambda m: None)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="garmintest_"))
    blob = make_zip_bytes()

    print("== 1) fit_filename ==")
    check("常规文件名", gs.fit_filename(act(123)) == "2026-09-13_074500_123.fit",
          gs.fit_filename(act(123)))
    check("缺时间回退", gs.fit_filename({"activityId": 9}).startswith("activity_9"))
    check("非法字符清洗", "/" not in gs.fit_filename({"activityId": 1, "startTimeLocal": "a/b\\c:d"}))
    try:
        gs.fit_filename({"startTimeLocal": "x"})
        check("缺 id 报错", False)
    except gs.GarminSyncError:
        check("缺 id 报错", True)

    print("== 2) extract_fit ==")
    check("zip 解包", gs.extract_fit(make_zip_bytes()) == b"FAKE-FIT-DATA")
    check("裸 FIT 直传", gs.extract_fit(b"RAWFIT") == b"RAWFIT")
    try:
        gs.extract_fit(make_zip_bytes(inner_name="only.txt"))
        check("zip 无 FIT 报错", False)
    except gs.GarminSyncError:
        check("zip 无 FIT 报错", True)

    print("== 3) 全量下载 ==")
    acts = [act(1), act(2, "2026-09-12 08:00:00"), act(3, "2026-09-11 06:30:00")]
    r = run_sync(acts, {"1": blob, "2": blob, "3": b"RAW"}, tmp)
    check("下载数 3", r["downloaded"] == 3, r)
    check("skipped 0", r["skipped"] == 0)
    check("落盘 3 文件", len(list((tmp / "dl").glob("*.fit"))) == 3)
    check("state 记录 3", len(json.loads((tmp / "state.json").read_text())["downloaded"]) == 3)
    check("errors 空", not r["errors"])

    print("== 4) 增量：二次同步只拉新 ==")
    acts2 = [act(9, "2026-09-14 07:00:00")] + acts
    r2 = run_sync(acts2, {"1": blob, "2": blob, "3": b"RAW", "9": blob}, tmp)
    check("增量下载 1", r2["downloaded"] == 1, r2)
    check("跳过 3", r2["skipped"] == 3, r2)
    check("state 记录 4", len(json.loads((tmp / "state.json").read_text())["downloaded"]) == 4)

    print("== 5) 分页 ==")
    many = [act(1000 + i) for i in range(250)]
    blobs = {str(1000 + i): blob for i in range(250)}
    r3 = run_sync(many, blobs, tmp / "paged")
    check("分页 250 条全下", r3["downloaded"] == 250, r3["downloaded"])

    print("== 6) 单条失败不中断 ==")
    r4 = run_sync([act(11), act(12), act(13)],
                  {"11": blob, "12": blob, "13": blob}, tmp / "err",
                  fail_ids={"12"})
    check("成功 2 条", r4["downloaded"] == 2, r4)
    check("errors 记录 1 条", len(r4["errors"]) == 1 and "12" in r4["errors"][0], r4)

    print("== 7) state 版本不符重置 ==")
    check("坏 state 回退空", gs.load_state(tmp / "nofile.json") == {"v": 1, "downloaded": {}})

    print("== 8) 状态损坏容错 ==")
    (tmp / "bad.json").write_text("not-json", encoding="utf-8")
    check("坏 json 容错", gs.load_state(tmp / "bad.json")["v"] == 1)

    print()
    print(f"通过 {PASS}，失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
