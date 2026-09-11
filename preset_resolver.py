# -*- coding: utf-8 -*-
"""启动器路径探测：缓存 → 助手根目录 → hints → 有限深度 glob，结果可缓存。"""

import os
import fnmatch
import re
import time

SCAN_TIMEOUT_SEC = 10


def get_assistants_root(settings):
    """用户在向导/设置里指定的「助手安装根目录」（可为空）。"""
    root = ""
    try:
        root = (settings or {}).get("assistants_root", "") or ""
    except Exception:
        root = ""
    return os.path.normpath(root) if root else ""


def fixed_drives():
    """枚举所有固定磁盘盘符（跳过光驱 / U 盘 / 网络盘）。"""
    drives = []
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            bitmask = k32.GetLogicalDrives()
            for i in range(26):
                if (bitmask >> i) & 1:
                    letter = "%s:\\" % chr(ord("A") + i)
                    if k32.GetDriveTypeW(letter) == 3:  # DRIVE_FIXED
                        drives.append(letter)
        except Exception:
            drives = []
    if not drives:  # 非 Windows 或枚举失败：退回常见盘符
        drives = [p for p in ("C:\\", "D:\\", "E:\\") if os.path.isdir(p)]
    return drives


def _add_root(roots, p):
    p = os.path.normpath(p)
    if os.path.isdir(p) and p not in roots:
        roots.append(p)


def narrow_search_roots(base_dir, settings=None):
    """快速探测：助手根目录 → 助手目录及相邻路径，避免 UI 卡顿。"""
    roots = []
    ar = get_assistants_root(settings)
    if ar:
        _add_root(roots, ar)
    if base_dir:
        for p in [base_dir, os.path.dirname(base_dir)]:
            _add_root(roots, p)
    for p in ["E:\\Games", "D:\\Games"]:
        _add_root(roots, p)
    return roots


def default_search_roots(base_dir, settings=None):
    """完整探测：助手根目录 → 常见游戏目录 → 全部固定盘符（盘符仅浅层扫描）。"""
    roots = list(narrow_search_roots(base_dir, settings))
    for drv in fixed_drives():
        _add_root(roots, drv)
    return roots


def _max_depth_for_root(root, default_depth=5):
    """盘符根目录浅扫，其余（含助手根目录）深扫。"""
    root = os.path.normpath(root)
    if re.match(r"^[A-Za-z]:$", root.rstrip("\\").upper()):
        return 2
    return default_depth


def _walk_limited(root, pattern, max_depth=4, stop_after=0, deadline=None):
    """在 root 下有限深度查找匹配 pattern 的文件（fnmatch 文件名）。"""
    found = []
    root = os.path.normpath(root)
    if not os.path.isdir(root):
        return found
    depth_limit = _max_depth_for_root(root, max_depth)
    for dirpath, dirnames, filenames in os.walk(root):
        if deadline is not None and time.monotonic() >= deadline:
            return found
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > depth_limit:
            dirnames[:] = []
            continue
        for name in filenames:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                found.append(os.path.join(dirpath, name))
                if stop_after and len(found) >= stop_after:
                    return found
    return found


def _scan_deadline(timeout_sec):
    """None 表示不限时；<=0 表示立即超时。"""
    if timeout_sec is None:
        return None
    if timeout_sec <= 0:
        return time.monotonic()
    return time.monotonic() + timeout_sec


def _glob_pattern_to_fnmatch(glob_pat):
    """**/BetterGI.exe -> BetterGI.exe"""
    name = glob_pat.replace("\\", "/").split("/")[-1]
    return name


def resolve_launcher(script, settings=None, search_roots=None, use_cache=True, allow_glob=True,
                     timeout_sec=SCAN_TIMEOUT_SEC):
    """
    返回 (path_or_empty, source)  source: cache|hint|glob|none|timeout
    allow_glob=False 时仅查缓存与 hints，供 UI 切换下拉框快速响应。
    timeout_sec 限制 glob 搜索时长，超时返回 timeout。
    """
    settings = settings or {}
    preset_id = script.get("id", "")
    cache = settings.get("path_cache", {})

    if use_cache and preset_id and preset_id in cache:
        cached = cache[preset_id]
        if cached and os.path.isfile(cached):
            return cached, "cache"

    for hint in script.get("launcher_hints", []):
        hint = os.path.normpath(hint)
        if os.path.isfile(hint):
            return hint, "hint"

    if not allow_glob:
        return "", "none"

    if search_roots is None:
        search_roots = default_search_roots(None, settings)

    deadline = _scan_deadline(timeout_sec)
    seen = set()
    for glob_pat in script.get("launcher_globs", []):
        if deadline is not None and time.monotonic() >= deadline:
            return "", "timeout"
        fn_pat = _glob_pattern_to_fnmatch(glob_pat)
        for root in search_roots:
            if deadline is not None and time.monotonic() >= deadline:
                return "", "timeout"
            for path in _walk_limited(root, fn_pat, max_depth=5, stop_after=1, deadline=deadline):
                path = os.path.normpath(path)
                if path not in seen:
                    seen.add(path)
                    if os.path.isfile(path):
                        return path, "glob"

    if deadline is not None and time.monotonic() >= deadline:
        return "", "timeout"

    return "", "none"


def resolve_all_candidates(script, search_roots=None, max_results=10, timeout_sec=SCAN_TIMEOUT_SEC,
                           settings=None):
    """返回所有候选路径（去重），供用户选择。"""
    if search_roots is None:
        search_roots = default_search_roots(None, settings)

    deadline = _scan_deadline(timeout_sec)

    out = []
    seen = set()
    for hint in script.get("launcher_hints", []):
        hint = os.path.normpath(hint)
        if os.path.isfile(hint) and hint not in seen:
            seen.add(hint)
            out.append(hint)
    for glob_pat in script.get("launcher_globs", []):
        if deadline is not None and time.monotonic() >= deadline:
            return out
        fn_pat = _glob_pattern_to_fnmatch(glob_pat)
        for root in search_roots:
            if deadline is not None and time.monotonic() >= deadline:
                return out
            for path in _walk_limited(root, fn_pat, max_depth=4, deadline=deadline):
                path = os.path.normpath(path)
                if path not in seen and os.path.isfile(path):
                    seen.add(path)
                    out.append(path)
                if len(out) >= max_results:
                    return out
    return out


def update_path_cache(settings, preset_script_id, path):
    if not preset_script_id:
        return settings
    cache = settings.setdefault("path_cache", {})
    if path:
        cache[preset_script_id] = path
    elif preset_script_id in cache:
        del cache[preset_script_id]
    return settings
