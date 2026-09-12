# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格:生成 一键长草助手Qt.exe(PySide6 版界面)"""

import glob
import os
import sys
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(os.path.abspath(SPEC))

# PyInstaller 6 自带 PySide6 hook,collect_all 兜底确保 Qt 插件/翻译/样式齐全
pyside_datas, pyside_binaries, pyside_hiddenimports = collect_all("PySide6")

# conda 版 Python 的 _ctypes.pyd 依赖 Library\bin 下的 ffi DLL,PyInstaller 分析
# 不到这层依赖;缺了运行时直接「ImportError: DLL load failed while importing _ctypes」
ffi_binaries = [
    (_p, ".")
    for _p in sorted(glob.glob(
        os.path.join(sys.prefix, "Library", "bin", "ffi*.dll")))
]

a = Analysis(
    [os.path.join(ROOT, "游戏助手Qt.pyw")],
    pathex=[ROOT, os.path.join(ROOT, "ui_qt")],
    binaries=pyside_binaries + ffi_binaries,
    datas=[
        (os.path.join(ROOT, "presets", "catalog.json"), "presets"),
        (os.path.join(ROOT, "assets", "icons", "app.ico"), "assets/icons"),
        (os.path.join(ROOT, "assets", "icons", "app.png"), "assets/icons"),
        (os.path.join(ROOT, "DISCLAIMER.md"), "."),
    ] + pyside_datas,
    hiddenimports=pyside_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PIL"],
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
    name="一键长草助手Qt",
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
