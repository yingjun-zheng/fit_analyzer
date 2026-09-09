# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（PySide6 桌面版）。"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
APP = str(ROOT / "app.py")
ICON = str(ROOT / "build" / "icon.ico")
# 背景图集与回退图打入包内（resource_path("backgrounds") / resource_path("back9.jpeg") 可找到）
DATAS = [
    (str(ROOT / "backgrounds"), "backgrounds"),
    (str(ROOT / "back9.jpeg"), "."),
    (str(ROOT / "imgs" / "logo.png"), "imgs"),
]
# 轨迹地图用到的高德 WebEngine 组件：amap_track.py 用 try/except 包住顶层 import，
# 显式声明 hiddenimports 确保 PyInstaller 收集 WebEngine hook 及其资源（进程/翻译/库）。
_WEBENGINE_IMPORTS = [
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
]

# 复盘 agent 等动态 import 的模块，PyInstaller 扫描不到，需显式声明
_CORE_IMPORTS = [
    "core.review_agent",
    "core.compare",
    "core.training_load",
    "core.fitness",
]

onefile = os.environ.get("CRP_ONEFILE") == "1"

a = Analysis(
    [APP],
    pathex=[str(ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=_WEBENGINE_IMPORTS + _CORE_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    noarchive=False,
    optimize=0,
)

# _ssl.pyd 只能与构建用 Python 配套的 OpenSSL DLL（DLLs/libcrypto|libssl-3-x64.dll）协作。
# PyInstaller 的依赖分析按 PATH 搜索同名 DLL，构建环境里若有其它来源的
# libcrypto-3-x64.dll（如 Git 自带），会抓到旧版导致运行时
# "ImportError: DLL load failed while importing _ssl"。此处强制替换为配套版本。
_DLLS_DIR = Path(sys.base_prefix) / "DLLs"
_SSL_DLLS = {name: str(_DLLS_DIR / name)
             for name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll")
             if (_DLLS_DIR / name).exists()}
if _SSL_DLLS:
    _seen = set()
    _fixed = []
    for dest, src, kind in a.binaries:
        name = Path(dest).name
        if name in _SSL_DLLS:
            if name in _seen:
                continue  # 重复项丢弃
            _seen.add(name)
            _fixed.append((dest, _SSL_DLLS[name], kind))  # 替换为配套版本
        else:
            _fixed.append((dest, src, kind))
    a.binaries = _fixed

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True if not onefile else False,
    name="骑行FIT数据分析器",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON,
)
if onefile:
    exe.binaries = a.binaries
    exe.datas = a.datas
else:
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="骑行FIT数据分析器",
    )