# -*- coding: utf-8 -*-
"""一键长草 · 游戏串行助手(Qt 版)入口。逻辑层与 tkinter 版完全共用。"""
import os
import sys

# 把脚本目录插到 sys.path 最前,保证双击/打包/任意 cwd 下都能 import ui_qt 与逻辑层
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui_qt.app import main

if __name__ == "__main__":
    sys.exit(main())
