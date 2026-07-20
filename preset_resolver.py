# -*- coding: utf-8 -*-
"""启动器路径探测：hints 优先，有限深度 glob，结果可缓存。"""

import os
import fnmatch
import time

SCAN_TIMEOUT_SEC = 10


def narrow_search_roots(base_dir):
    """快速探测：仅助手目录及相邻路径，避免 UI 卡顿。"""
    roots = []
    for p in [base_dir, os.path.dirname(base_dir)]:
        p = os.path.normpath(p)
        if os.path.isdir(p) and p not in roots:
            roots.append(p)
    for p in ["E:\\Games", "D:\\Games"]:
        p = os.path.normpath(p)
        if os.path.isdir(p) and p not in roots:
            roots.append(p)
    return roots


def default_search_roots(base_dir):
    """完整探测：常见游戏目录 + 盘符根（盘符仅浅层扫描）。"""
    roots = list(narrow_search_roots(base_dir))
    for p in ["E:\\", "D:\\"]:
        p = os.path.normpath(p)
        if os.path.isdir(p) and p not in roots:
            roots.append(p)
    return roots


def _max_depth_for_root(root, default_depth=5):
    """盘符根目录浅扫，子目录深扫。"""
    root = os.path.normpath(root)
    if root.rstrip("\\").upper() in ("E:", "D:", "C:"):
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
        search_roots = ["E:\\", "D:\\"]

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


def resolve_all_candidates(script, search_roots=None, max_results=10, timeout_sec=SCAN_TIMEOUT_SEC):
    """返回所有候选路径（去重），供用户选择。"""
    if search_roots is None:
        search_roots = ["E:\\", "D:\\"]

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
