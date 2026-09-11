# -*- coding: utf-8 -*-
"""运行前自检。"""

import os

try:
    import runner_core
except ImportError:
    runner_core = None


def _proc_running(name, running_names=None):
    if not name:
        return False
    key = name.lower()
    if running_names is not None:
        return key in running_names
    if not runner_core:
        return False
    return runner_core._tasklist_running(name)


def check_plugins(plugins, running_names=None):
    """
    返回 issue 列表，每项 dict:
      level: error|warn|info
      plugin_name: str
      message: str

    running_names: 可选，已缓存的进程名集合；不传则只调用一次 tasklist。
    """
    issues = []
    enabled = [p for p in plugins if p.get("enabled", True)]

    if not enabled:
        issues.append({
            "level": "error",
            "plugin_name": "",
            "message": "没有勾选任何游戏，请至少开启一个。",
        })
        return issues

    if running_names is None and runner_core:
        running_names = runner_core.snapshot_running_processes()

    if runner_core and not runner_core.is_admin():
        issues.append({
            "level": "warn",
            "plugin_name": "",
            "message": "当前非管理员模式，部分脚本可能无法正常启动（建议以管理员运行 exe）。",
        })

    parallel_names = [p.get("name", "未命名") for p in enabled if p.get("parallel")]
    if len(parallel_names) >= 2:
        # 只勾 1 个并行任务时是常规用法，不提醒；≥2 个才可能出现互相抢占
        issues.append({
            "level": "warn",
            "plugin_name": "",
            "message": "%d 个任务勾选了并行，将同时启动（%s）——请确认它们互不抢占鼠标、"
                       "也不共用同一个模拟器。" % (len(parallel_names), "、".join(parallel_names)),
        })

    for p in enabled:
        name = p.get("name", "未命名")
        launcher = p.get("launcher", "")
        if not launcher or not os.path.isfile(launcher):
            issues.append({
                "level": "warn",
                "plugin_name": name,
                "message": "找不到启动器，运行时将被跳过。",
            })

        for proc in p.get("game_processes", []) + p.get("helper_processes", []):
            if proc and _proc_running(proc, running_names):
                issues.append({
                    "level": "warn",
                    "plugin_name": name,
                    "message": "进程 %s 已在运行，可能与本次串行冲突。" % proc,
                })
                break

    return issues


def has_blocking_errors(issues):
    return any(i.get("level") == "error" for i in issues)
