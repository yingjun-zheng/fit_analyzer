# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（PySide6 桌面版）。"""
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
APP = str(ROOT / "app.py")
ICON = str(ROOT / "build" / "icon.ico")
# 背景图集与回退图打入包内（resource_path("backgrounds") / resource_path("back9.jpeg") 可找到）
DATAS = [
    (str(ROOT / "backgrounds"), "backgrounds"),
    (str(ROOT / "back9.jpeg"), "."),
]
# 轨迹地图用到的高德 WebEngine 组件：amap_track.py 用 try/except 包住顶层 import，
# 显式声明 hiddenimports 确保 PyInstaller 收集 WebEngine hook 及其资源（进程/翻译/库）。
_WEBENGINE_IMPORTS = [
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
]

onefile = os.environ.get("CRP_ONEFILE") == "1"

a = Analysis(
    [APP],
    pathex=[str(ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=_WEBENGINE_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    noarchive=False,
    optimize=0,
)
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
