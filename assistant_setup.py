# -*- coding: utf-8 -*-
"""第三方助手推荐配置：一键写入 / 备份还原 / 自检。

把「串行化必需」的助手设置（跑完自动关游戏、自动退出等）写进助手自己的
配置文件。原则：
  - 写入前把原文件备份到 <数据目录>\\backup\\config\\<preset_id>\\<时间戳>\\
  - 文件缺失 / 解析失败立即中止，绝不盲写，回退为人工指引
  - apply_for_plugin() 写入配置；verify_for_plugin() 只检查不写入
  - 两者都返回统一结构，供向导渲染绿勾 / 黄标 / 人工项
"""

import datetime
import glob as globmod
import json
import os
import random
import re
import shutil
import string
import time

try:
    from app_paths import data_dir
except ImportError:  # 允许被第三方项目当作独立模块导入
    def data_dir():
        return os.path.dirname(os.path.abspath(__file__))


# ===================== 结果结构 =====================

def _check(name, ok, hint=""):
    return {"name": name, "ok": bool(ok), "hint": hint}


def _result(applied=None, manual=None, checks=None, error=""):
    return {
        "ok": not error,
        "applied": applied or [],
        "manual": manual or [],
        "checks": checks or [],
        "error": error,
    }


def _manual_result(manual, error=""):
    """纯人工路径：没有自动写入任何东西，视为未完成。"""
    return {"ok": False, "applied": [], "manual": manual or [], "checks": [],
            "error": error}


# ===================== 文本读写（编码自适应） =====================

def _read_text(path):
    """依次尝试 utf-8 / gbk，返回 (text, encoding)；失败返回 ("", "")。"""
    for enc in ("utf-8", "gbk"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(), enc
        except UnicodeDecodeError:
            continue
        except Exception:
            return "", ""
    return "", ""


def _write_text(path, text, encoding):
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)


def _line_sep(text):
    return "\r\n" if "\r\n" in text else "\n"


# ===================== 备份 / 还原 =====================

def _backup_root():
    return os.path.join(data_dir(), "backup", "config")


def backup_files(preset_id, paths):
    """把将要修改的文件备份到一个时间戳目录，返回该目录（空串表示没有需要备份的）。"""
    paths = [p for p in paths if p and os.path.isfile(p)]
    if not paths:
        return ""
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(_backup_root(), preset_id, ts)
    os.makedirs(dest, exist_ok=True)
    entries = []
    for p in paths:
        shutil.copy2(p, os.path.join(dest, os.path.basename(p)))
        entries.append({"original": os.path.abspath(p), "file": os.path.basename(p)})
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"time": ts, "preset_id": preset_id, "entries": entries},
                  f, ensure_ascii=False, indent=2)
    return dest


def list_backups(preset_id):
    """返回 [(时间戳目录, 目录名)]，新的在前。"""
    root = os.path.join(_backup_root(), preset_id)
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root), reverse=True):
        full = os.path.join(root, name)
        if os.path.isfile(os.path.join(full, "manifest.json")):
            out.append((full, name))
    return out


def restore_backup(backup_dir):
    """按 manifest 把备份文件复制回原位置，返回还原的原路径列表。"""
    manifest = os.path.join(backup_dir, "manifest.json")
    restored = []
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return restored
    for entry in data.get("entries", []):
        src = os.path.join(backup_dir, entry.get("file", ""))
        dst = entry.get("original", "")
        if src and dst and os.path.isfile(src):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                restored.append(dst)
            except Exception:
                pass
    return restored


# ===================== 通用工具 =====================

def _assistant_dir(plugin):
    """助手的安装目录 = 启动器所在目录。"""
    launcher = plugin.get("launcher", "") or ""
    return os.path.dirname(os.path.abspath(launcher)) if launcher else ""


def _patch_flat_yaml(text, wanted):
    """
    只改顶层键（行首无缩进）的值，保留行内注释；缺失的键追加到末尾。
    wanted: {键: 新值字符串}。返回 (新文本, 被改动/追加的键列表)。
    """
    sep = _line_sep(text)
    changed = []
    seen = set()
    out = []
    for line in text.split(sep):
        m = re.match(r"^([A-Za-z_][\w-]*)(\s*:\s*)(.*?)(\s+#.*)?$", line)
        if m and m.group(1) in wanted:
            seen.add(m.group(1))
            new_val = wanted[m.group(1)]
            if m.group(3).strip() != new_val:
                out.append(m.group(1) + m.group(2) + new_val + (m.group(4) or ""))
                changed.append(m.group(1))
                continue
        out.append(line)
    for key, val in wanted.items():
        if key not in seen:
            out.append("%s: %s" % (key, val))
            changed.append(key)
    return sep.join(out), changed


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _gen_id(k=7):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=k))


def _key_check(name, key, changed, dry_run, hint=""):
    """可写入项的检查：仅检查时「本来就是对的」才算通过；写入后必然通过。"""
    if not dry_run:
        return _check(name, True, hint)
    return _check(name, key not in changed, hint)


def _verify_from_checklist(plugin):
    """未知预设的兜底：用插件自带的 setup_checklist 渲染检查项。"""
    todo = plugin.get("setup_checklist", []) or []
    done = plugin.get("checklist_done", []) or []
    checks = []
    for item in todo:
        checks.append(_check(item, item in done,
                             "" if item in done else "请按说明在助手内手动完成"))
    return checks


# ===================== 各助手 handler =====================

def _setup_m7a(plugin, dry_run):
    """崩铁 March7th Assistant：config.yaml 设 after_finish=Exit、pause_after_success=false。"""
    d = _assistant_dir(plugin)
    cfg = os.path.join(d, "config.yaml")
    if not os.path.isfile(cfg):
        return _manual_result(
            ["未找到 March7th Assistant 的 config.yaml，请确认已安装并在「导入」中指定了正确的目录。"])
    text, enc = _read_text(cfg)
    if not text:
        return _manual_result(["config.yaml 读取失败（编码异常），请手动打开该文件修改："
                               "after_finish: Exit、pause_after_success: false。"])
    new_text, changed = _patch_flat_yaml(text, {
        "after_finish": "Exit",
        "pause_after_success": "false",
    })
    if changed and not dry_run:
        backup_files("m7a_main", [cfg])
        try:
            _write_text(cfg, new_text, enc)
        except Exception:
            return _manual_result(["config.yaml 写入失败（可能被占用），请关闭 March7th 后重试。"])
    checks = [
        _key_check("任务完成后自动退出（after_finish: Exit）", "after_finish", changed, dry_run),
        _key_check("完成后不暂停（pause_after_success: false）", "pause_after_success", changed, dry_run),
    ]
    return _result(applied=changed, checks=checks)


def _setup_bettergi(plugin, dry_run):
    """原神 BetterGI：一条龙配置 CompletionAction = 关闭游戏和软件。"""
    d = _assistant_dir(plugin)
    od_dir = os.path.join(d, "User", "OneDragon")
    files = [f for f in globmod.glob(os.path.join(od_dir, "*.json"))
             if not f.endswith((".bak", ".backup"))]
    if not files:
        return _manual_result(
            ["未找到 BetterGI 的一条龙配置（User\\OneDragon\\*.json）。",
             "请先打开 BetterGI → 一条龙 界面，任意选择/保存一次配置，再回来点「一键配置」。"])
    cfg = max(files, key=os.path.getmtime)
    try:
        data = _load_json(cfg)
    except Exception:
        return _manual_result(["一条龙配置文件解析失败：%s" % os.path.basename(cfg)])
    if not isinstance(data, dict):
        return _manual_result(["一条龙配置文件格式异常：%s" % os.path.basename(cfg)])
    wanted = "关闭游戏和软件"
    changed = []
    if data.get("CompletionAction") != wanted:
        changed.append("CompletionAction")
        if not dry_run:
            backup_files("bettergi_onedragon", [cfg])
            data["CompletionAction"] = wanted
            try:
                _dump_json(cfg, data)
            except Exception:
                return _manual_result(["配置写入失败（可能被占用），请关闭 BetterGI 后重试。"])
    tasks = data.get("TaskEnabledList")
    has_task = bool(tasks) if isinstance(tasks, (list, dict)) else False
    checks = [
        _key_check("一条龙结束后关闭游戏和软件", "CompletionAction", changed, dry_run),
        _check("已勾选至少一个一条龙任务", has_task,
               "" if has_task else "请在 BetterGI 的一条龙界面勾选你要做的任务（如日常、领奖励）。"),
    ]
    manual = [] if has_task else [
        "在 BetterGI 的一条龙界面勾选你要做的任务（日常委托、领奖励等）。",
    ]
    return _result(applied=changed, manual=manual, checks=checks)


def _setup_maa(plugin, dry_run):
    """明日方舟 MAA：gui.json 设自动开始 / 自动开模拟器 / 完成后退出模拟器+退出MAA。"""
    d = _assistant_dir(plugin)
    cfg = os.path.join(d, "config", "gui.json")
    if not os.path.isfile(cfg):
        return _manual_result(
            ["未找到 MAA 的 config\\gui.json，请确认已安装并在「导入」中指定了正确的目录。"])
    try:
        data = _load_json(cfg)
    except Exception:
        return _manual_result(
            ["MAA 配置文件解析失败，请打开 MAA → 设置 → 运行设置，手动勾选：",
             "① 启动MAA后自动开始委托  ② 启动MAA时自动开启模拟器  ③ 完成后 退出模拟器 + 退出MAA。"])
    if not isinstance(data, dict):
        return _manual_result(["MAA 配置文件格式异常。"])
    confs = data.setdefault("Configurations", {})
    cur = data.get("Current") or "Default"
    data["Current"] = cur
    conf = confs.setdefault(cur, {})
    wanted = {
        "Start.RunDirectly": "True",               # 启动 MAA 后自动开始任务
        "Start.OpenEmulatorAfterLaunch": "True",   # 启动 MAA 时自动开启模拟器
        "MainFunction.PostActions": "12",          # 完成后：退出模拟器 + 退出 MAA
    }
    changed = [k for k, v in wanted.items() if conf.get(k) != v]
    if changed and not dry_run:
        backup_files("maa_gui", [cfg])
        for k, v in wanted.items():
            conf[k] = v
        try:
            _dump_json(cfg, data)
        except Exception:
            return _manual_result(["gui.json 写入失败（可能被占用），请关闭 MAA 后重试。"])
    adb = str(conf.get("Connect.AdbPath", "") or "")
    adb_ok = bool(adb) and os.path.isfile(adb)
    checks = [
        _key_check("启动 MAA 后自动开始任务", "Start.RunDirectly", changed, dry_run),
        _key_check("启动 MAA 时自动开启模拟器", "Start.OpenEmulatorAfterLaunch", changed, dry_run),
        _key_check("完成后退出模拟器并退出 MAA", "MainFunction.PostActions", changed, dry_run),
        _check("已配置模拟器连接（ADB 路径）", adb_ok,
               "打开 MAA → 设置 → 连接设置，选择 ADB 路径与地址（MuMu 一般可自动检测）。"),
    ]
    manual = [] if adb_ok else [
        "MAA 需要配合安卓模拟器（推荐 MuMu）：先安装 MuMu 模拟器并登录明日方舟，"
        "再打开 MAA → 设置 → 连接设置 选择 ADB 路径与地址。",
    ]
    return _result(applied=changed, manual=manual, checks=checks)


_MAAEND_KILLPROC = "__MXU_KILLPROC__"


def _maaend_killproc_task(self_exit):
    return {
        "id": _gen_id(),
        "taskName": _MAAEND_KILLPROC,
        "enabled": True,
        "enabledByController": {"Win32-Front": True},
        "optionValues": {
            "__MXU_KILLPROC_SELF_OPTION__": {"type": "switch", "value": bool(self_exit)},
            "__MXU_KILLPROC_NAME_OPTION__": {"type": "input",
                                             "values": {"process_name": "Endfield.exe"}},
        },
    }


def _setup_maaend(plugin, dry_run):
    """终末地 MaaEnd：确保任务队列末尾有「结束进程 Endfield.exe」和「退出 MaaEnd」。"""
    d = _assistant_dir(plugin)
    cfg = os.path.join(d, "config", "mxu-MaaEnd.json")
    if not os.path.isfile(cfg):
        return _manual_result(
            ["未找到 MaaEnd 的 config\\mxu-MaaEnd.json，请先打开 MaaEnd 完成一次配置并保存。"])
    try:
        data = _load_json(cfg)
    except Exception:
        return _manual_result(["MaaEnd 配置文件解析失败，请在 MaaEnd 编辑页确认："
                               "任务末尾已添加「结束进程 Endfield.exe」和「退出 MaaEnd」。"])
    instances = data.get("instances") if isinstance(data, dict) else None
    if not instances:
        return _manual_result(["MaaEnd 中还没有配置实例，请先在 MaaEnd 里新建一个配置并连接一次游戏。"])
    inst = None
    for it in instances:
        dev = (it.get("savedDevice") or {}).get("connectedProgramPath", "") or ""
        if "endfield.exe" in dev.lower():
            inst = it
            break
    if inst is None:
        inst = instances[0]
    tasks = inst.setdefault("tasks", [])

    def _is_kill(t, self_exit):
        if t.get("taskName") != _MAAEND_KILLPROC:
            return False
        ov = t.get("optionValues") or {}
        self_opt = (ov.get("__MXU_KILLPROC_SELF_OPTION__") or {}).get("value")
        name_opt = ((ov.get("__MXU_KILLPROC_NAME_OPTION__") or {}).get("values") or {}) \
            .get("process_name", "")
        return bool(self_opt) == bool(self_exit) and "endfield.exe" in str(name_opt).lower()

    need_kill_game = not any(_is_kill(t, False) for t in tasks)   # 结束 Endfield.exe
    need_exit_self = not any(_is_kill(t, True) for t in tasks)    # 退出 MaaEnd 自身
    changed = []
    if (need_kill_game or need_exit_self) and not dry_run:
        backup_files("maaend_gui", [cfg])
        if need_kill_game:
            tasks.append(_maaend_killproc_task(False))
            changed.append("结束进程 Endfield.exe")
        if need_exit_self:
            tasks.append(_maaend_killproc_task(True))
            changed.append("退出 MaaEnd")
        try:
            _dump_json(cfg, data)
        except Exception:
            return _manual_result(["配置写入失败（可能被占用），请关闭 MaaEnd 后重试。"])
    elif need_kill_game or need_exit_self:
        changed = (["结束进程 Endfield.exe"] if need_kill_game else []) + \
                  (["退出 MaaEnd"] if need_exit_self else [])
    dev = (inst.get("savedDevice") or {}).get("connectedProgramPath", "") or ""
    n_enabled = sum(1 for t in tasks if t.get("enabled") and t.get("taskName") != _MAAEND_KILLPROC)
    checks = [
        _check("已绑定游戏程序（Endfield.exe）", "endfield.exe" in dev.lower(),
               "在 MaaEnd 配置的「高级选项」中选择游戏程序 Endfield.exe。"),
        _check("任务队列末尾会结束游戏并退出 MaaEnd",
               not (need_kill_game or need_exit_self) or not dry_run),
        _check("已启用至少一个日常任务", n_enabled > 0,
               "" if n_enabled > 0 else "请在 MaaEnd 里勾选你要做的日常任务。"),
    ]
    manual = []
    if "endfield.exe" not in dev.lower():
        manual.append("在 MaaEnd 配置的「高级选项」中选择游戏程序 Endfield.exe。")
    if n_enabled == 0:
        manual.append("在 MaaEnd 的任务列表里勾选你要做的日常任务。")
    return _result(applied=changed, manual=manual, checks=checks)


def _setup_onedragon(plugin, dry_run):
    """绝区零 OneDragon：config/one_dragon.yml 设 after_done=关闭游戏。"""
    d = _assistant_dir(plugin)
    cfg = os.path.join(d, "config", "one_dragon.yml")
    if not os.path.isfile(cfg):
        return _manual_result(
            ["未找到 OneDragon 的 config\\one_dragon.yml，请先打开 OneDragon-Launcher 完成初始化。"])
    text, enc = _read_text(cfg)
    if not text:
        return _manual_result(["one_dragon.yml 读取失败，请手动把 after_done 改为：关闭游戏。"])
    new_text, changed = _patch_flat_yaml(text, {"after_done": "关闭游戏"})
    if changed and not dry_run:
        backup_files("onedragon", [cfg])
        try:
            _write_text(cfg, new_text, enc)
        except Exception:
            return _manual_result(["one_dragon.yml 写入失败（可能被占用），请关闭 OneDragon 后重试。"])
    apps_ok, _n_app = _onedragon_has_enabled_app(d)
    checks = [
        _key_check("一条龙结束后自动关闭游戏（after_done）", "after_done", changed, dry_run),
        _check("已勾选至少一个一条龙应用", apps_ok,
               "" if apps_ok else "请在 OneDragon 界面勾选要跑的一条龙应用。"),
    ]
    manual = [] if apps_ok else ["在 OneDragon 界面勾选你要跑的一条龙应用（日常/领奖励等）。"]
    return _result(applied=changed, manual=manual, checks=checks)


def _onedragon_has_enabled_app(base_dir):
    """检查任一实例的一条龙应用列表里有启用项（仅做启发式统计，供提示）。"""
    for g in globmod.glob(os.path.join(base_dir, "config", "*", "one_dragon", "_group.yml")):
        text, _ = _read_text(g)
        if text and re.search(r"enabled:\s*true", text):
            return True, 1
    return False, 0


# ===================== 对外接口 =====================

HANDLERS = {
    "onedragon": _setup_onedragon,
    "bettergi_onedragon": _setup_bettergi,
    "m7a_main": _setup_m7a,
    "maa_gui": _setup_maa,
    "maaend_gui": _setup_maaend,
}

# 向导里标注「支持一键配置」的预设
SUPPORTED_PRESET_IDS = set(HANDLERS)


def apply_for_plugin(plugin):
    """对该插件对应的助手执行一键配置。未知预设只返回人工指引。"""
    pid = plugin.get("preset_id", "")
    handler = HANDLERS.get(pid)
    if handler is None:
        return _manual_result(list(plugin.get("setup_checklist", []) or []),
                              error="该脚本暂不支持一键配置，请按说明手动完成。")
    try:
        return handler(plugin, dry_run=False)
    except Exception as e:
        return _manual_result(["一键配置出现异常，请按说明手动完成。"], error=str(e))


def verify_for_plugin(plugin):
    """只检查不写入：返回检查项列表。无法自动配置的项以未完成检查呈现。"""
    pid = plugin.get("preset_id", "")
    handler = HANDLERS.get(pid)
    if handler is None:
        return _verify_from_checklist(plugin)
    try:
        r = handler(plugin, dry_run=True)
    except Exception:
        return _verify_from_checklist(plugin)
    checks = list(r.get("checks") or [])
    if not checks:
        # 文件缺失 / 解析失败等：把人工指引转成未完成检查，让向导能显示「待操作」
        for m in r.get("manual") or []:
            checks.append(_check(m, False, "需人工处理"))
    return checks


def backup_time_label(ts_dir):
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(
            os.path.join(ts_dir, "manifest.json"))).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return os.path.basename(ts_dir)
