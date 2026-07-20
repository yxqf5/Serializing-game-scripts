# -*- coding: utf-8 -*-
"""开发模式与 PyInstaller 打包后的路径解析。"""

import os
import sys


def is_frozen():
    return getattr(sys, "frozen", False)


def data_dir():
    """可写数据目录：plugins、settings.json（exe 同目录）。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir():
    """只读资源目录：预设 catalog、图标等。"""
    if is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    return os.path.join(bundle_dir(), *parts)
