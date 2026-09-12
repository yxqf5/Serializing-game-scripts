# -*- coding: utf-8 -*-
"""逻辑层粘合:从 tkinter 版 游戏助手.pyw 平移的模块级辅助(契约见 PORTING.md)。"""
import glob
import json
import os
import sys

from app_paths import data_dir

BASE_DIR = data_dir()
PLUGIN_DIR = os.path.join(BASE_DIR, "plugins")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DAILY_STATE_FILE = os.path.join(BASE_DIR, "daily_state.json")

# 界面日志最多保留的行数(与旧版 LOG_VIEW_LINES 一致)
LOG_VIEW_LINES = 600

WAIT_MODE_LABELS = {
    "game": "等待游戏进程（助手跑完会关游戏）",
    "helper": "等待助手自己退出（如 MAA／模拟器类）",
}


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(d: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_plugins() -> list:
    items = []
    if not os.path.isdir(PLUGIN_DIR):
        return items
    for f in glob.glob(os.path.join(PLUGIN_DIR, "*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            d["_file"] = f
            items.append(d)
        except Exception as e:
            print("读取插件失败:", f, e)
    items.sort(key=lambda x: (int(x.get("order", 999)), x.get("name", "")))
    for d in items:
        if d.get("preset_id") == "maa_gui" and "parallel" not in d:
            d["parallel"] = True
            try:
                save_plugin(d)
            except Exception:
                pass
    return items


def save_plugin(p: dict) -> None:
    data = {k: v for k, v in p.items() if not k.startswith("_")}
    try:
        with open(p["_file"], "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print("保存插件失败:", p.get("name"), e)


def log_tag_for(msg: str, level=None):
    """日志着色:结构化级别优先,无级别时回退关键词匹配(移植 App._log_tag_for)。"""
    if level:
        tag = {
            "error": "log_err",
            "warn": "log_warn",
            "gold": "log_gold",
            "blue": "log_blue",
            "ok": "log_ok",
        }.get(level)
        if tag:
            return tag
    if "[每日未完成]" in msg:
        return "log_err"
    if "[每日完成]" in msg:
        return "log_gold"
    if "[体力]" in msg:
        return "log_blue"
    if any(k in msg for k in ("[跳过]", "[失败]", "未找到启动器", "未配置启动器", "配置不完整")):
        return "log_err"
    if "[警告]" in msg:
        return "log_warn"
    if ("==========" in msg) or ("────────" in msg) or ("任务结果 ·" in msg) or ("结果输出完毕" in msg):
        return "log_ok"
    if msg.startswith(("# ", "## ", "### ")) or msg.startswith("```"):
        return "log_ok"
    return None
