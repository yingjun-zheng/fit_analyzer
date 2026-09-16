"""自更新引擎单测：版本比较 / manifest / 更新计划 / 指纹 / 本地下载。

不依赖网络：用临时目录 + file:// 协议模拟发布源。
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import updater

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def make_exe_dir(path, with_deps=True):
    """构造模拟程序目录：应用层文件 + 依赖指纹文件。"""
    base = Path(path)
    (base / "_internal" / "PySide6").mkdir(parents=True, exist_ok=True)
    (base / "_internal" / "shiboken6").mkdir(parents=True, exist_ok=True)
    (base / "_internal" / "imgs").mkdir(parents=True, exist_ok=True)
    (base / "骑行FIT数据分析器.exe").write_bytes(b"MZ" + b"\x00" * 100)
    (base / "_internal" / "PYZ-00.pyz").write_bytes(b"PYZ-DATA")
    (base / "_internal" / "imgs" / "logo.png").write_bytes(b"PNG-DATA")
    if with_deps:
        for rel in updater._DEPS_FILES:
            p = base / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"DEPS" + rel.encode())
    return base


def make_publish_dir(base, exe_dir, version="1.2.0", with_full=False, tag=""):
    """模拟发布源：latest.json + 增量包 zip（复用 pack.py 的发布逻辑核心）。"""
    pub = Path(base) / ("pub" + tag)
    pub.mkdir(parents=True, exist_ok=True)
    # 增量包：应用层文件
    inc_name = f"update-{version}.zip"
    import zipfile
    with zipfile.ZipFile(pub / inc_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in updater.app_layer_paths(exe_dir):
            zf.write(exe_dir / rel, rel)
    inc_path = pub / inc_name
    manifest = {
        "version": version,
        "name": "骑行FIT数据分析器",
        "published_at": time.strftime("%Y-%m-%d"),
        "deps_fingerprint": updater.deps_fingerprint(exe_dir),
        "url_incremental": inc_name,
        "sha256_incremental": updater.sha256_file(inc_path),
        "size_incremental": inc_path.stat().st_size,
        "changelog": [{"version": version, "date": time.strftime("%Y-%m-%d"),
                       "notes": ["更新功能测试"]}],
    }
    if with_full:
        full_name = f"full-{version}.zip"
        with zipfile.ZipFile(pub / full_name, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in updater.app_layer_paths(exe_dir):
                zf.write(exe_dir / rel, rel)
            for rel in updater._DEPS_FILES:
                zf.write(exe_dir / rel, rel)
        full_path = pub / full_name
        manifest["url_full"] = full_name
        manifest["sha256_full"] = updater.sha256_file(full_path)
        manifest["size_full"] = full_path.stat().st_size
    (pub / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return pub, manifest


def main():
    tmp = Path(tempfile.mkdtemp(prefix="fit_upd_"))
    try:
        print("== 版本比较 ==")
        check("1.1.0 < 1.2.0", updater.compare_versions("1.1.0", "1.2.0") == -1)
        check("v1.2.0 == 1.2.0", updater.compare_versions("v1.2.0", "1.2.0") == 0)
        check("1.10.0 > 1.9.9", updater.compare_versions("1.10.0", "1.9.9") == 1)
        check("1.2.0-beta 可解析", isinstance(updater.parse_version("1.2.0-beta"), tuple))

        print("== 依赖指纹 ==")
        exe_dir = make_exe_dir(tmp / "app")
        fp = updater.deps_fingerprint(exe_dir)
        check("指纹非空且稳定", bool(fp) and fp == updater.deps_fingerprint(exe_dir))
        exe_no_deps = make_exe_dir(tmp / "app2", with_deps=False)
        check("缺依赖文件指纹为空", updater.deps_fingerprint(exe_no_deps) == "")

        print("== 更新计划 ==")
        pub, manifest = make_publish_dir(tmp, exe_dir)
        manifest_url = (pub / "latest.json").as_uri()
        # 本地版本低于发布版本 → 应更新（增量）
        plan = updater.plan_update("1.1.0", exe_dir, manifest, manifest_url)
        check("版本落后 → 需要更新", plan["needs"] and not plan["full"], str(plan))
        check("相对 URL 已绝对化", plan["url"].startswith("file://"), plan["url"])
        check("sha256 与大小", plan["sha256"] == manifest["sha256_incremental"] and plan["size"] > 0)
        # 同版本 → 不更新
        plan_same = updater.plan_update("1.2.0", exe_dir, manifest, manifest_url)
        check("版本相同 → 不更新", not plan_same["needs"])
        # 忽略版本 → 不更新
        check("忽略该版本 → 不更新", not updater.should_update("1.1.0", manifest, ignored_version="1.2.0"))
        # 依赖指纹不一致 + 有全量包 → full
        bad_app = make_exe_dir(tmp / "app3", with_deps=True)
        (bad_app / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(b"OTHER-VERSION")
        pub_full, manifest_full = make_publish_dir(tmp, exe_dir, version="1.3.0", with_full=True, tag="full")
        plan_full = updater.plan_update("1.1.0", bad_app, manifest_full, (pub_full / "latest.json").as_uri())
        check("依赖不一致 → 需全量包", plan_full["needs"] and plan_full["full"], str(plan_full))
        check("全量包 URL 已绝对化", plan_full["url"].startswith("file://"), plan_full["url"])
        # 依赖不一致但发布方没全量包 → 无法更新
        pub2, manifest2 = make_publish_dir(tmp, exe_dir, version="1.2.0", with_full=False, tag="nofull")
        manifest2["deps_fingerprint"] = "other-fp"
        (pub2 / "latest.json").write_text(json.dumps(manifest2, ensure_ascii=False), encoding="utf-8")
        plan_none = updater.plan_update("1.1.0", bad_app, manifest2, (pub2 / "latest.json").as_uri())
        check("依赖不一致且无包 → 不更新", not plan_none["needs"])

        print("== 增量包下载与校验 ==")
        dest = tmp / "dl" / "update.zip"
        updater.download_file(plan["url"], dest)
        check("下载成功且内容一致", dest.exists() and updater.sha256_file(dest) == manifest["sha256_incremental"])
        check("下载校验函数", updater.sha256_file(dest).lower() == plan["sha256"].lower())

        print("== check_for_update 顶层入口（file:// manifest）==")
        plan_top = updater.check_for_update(manifest_url, exe_dir, "1.1.0")
        check("顶层入口返回计划", plan_top is not None and plan_top.get("needs"))
        plan_top_same = updater.check_for_update(manifest_url, exe_dir, "1.2.0")
        check("同版本顶层入口返回 None", plan_top_same is None)
        plan_bad_url = updater.check_for_update((tmp / "nope" / "latest.json").as_uri(), exe_dir, "1.1.0")
        check("无效地址返回 None（不抛）", plan_bad_url is None)

        print("== 延迟替换脚本（bat）生成 ==")
        from core import updater as _up
        fake_app = make_exe_dir(tmp / "app_bat")
        bat = _up.build_update_bat(fake_app, "骑行FIT数据分析器.exe")
        check("bat 已生成", bat.exists())
        text = bat.read_text(encoding="gbk")
        check("含覆盖/重启/清理命令", "xcopy" in text and 'start "" "骑行FIT数据分析器.exe"' in text
              and "rd /s /q" in text, text[:200])
        check("相对定位避开中文路径", '"%~dp0.."' in text and ".update\\staged" in text)

        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
