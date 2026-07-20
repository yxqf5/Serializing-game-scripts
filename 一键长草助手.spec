# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：生成 一键长草助手.exe"""

import os
import sys
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(os.path.abspath(SPEC))
PREFIX = sys.prefix


def conda_dlls(*names):
    """Conda 下 Tcl/Tk、Pillow 等 DLL 需手动打入（PyInstaller 常解析不到）。"""
    search = [
        os.path.join(PREFIX, "Library", "bin"),
        os.path.join(PREFIX, "DLLs"),
    ]
    out = []
    seen = set()
    for name in names:
        for folder in search:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                key = (name, folder)
                if key not in seen:
                    seen.add(key)
                    out.append((path, "."))
                break
    return out


# PyInstaller 6：Tcl/Tk 数据走 hook-_tkinter；DLL 在 conda 下须显式加入
tk_datas, tk_binaries, tk_hiddenimports = collect_all("tkinter")
pil_datas, pil_binaries, pil_hiddenimports = collect_all("PIL")

extra_binaries = conda_dlls(
    "tcl86t.dll",
    "tk86t.dll",
    "libjpeg.dll",
    "zlib.dll",
    "libwebp.dll",
    "libwebpdemux.dll",
    "libwebpmux.dll",
    "lcms2.dll",
    "tiff.dll",
    "ffi.dll",
    "liblzma.dll",
    "libmpdec-4.dll",
)

a = Analysis(
    [os.path.join(ROOT, "游戏助手.pyw")],
    pathex=[ROOT],
    binaries=tk_binaries + pil_binaries + extra_binaries,
    datas=[
        (os.path.join(ROOT, "presets", "catalog.json"), "presets"),
        (os.path.join(ROOT, "assets", "icons", "app.ico"), "assets/icons"),
        (os.path.join(ROOT, "assets", "icons", "app.png"), "assets/icons"),
        (os.path.join(ROOT, "DISCLAIMER.md"), "."),
    ] + tk_datas + pil_datas,
    hiddenimports=tk_hiddenimports + pil_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="一键长草助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "icons", "app.ico"),
    uac_admin=True,
)
