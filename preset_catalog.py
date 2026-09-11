# -*- coding: utf-8 -*-
"""预设目录加载、插件生成、默认导入。"""

import os
import json
import re
import glob

from preset_resolver import resolve_launcher, default_search_roots, update_path_cache
from app_paths import data_dir, resource_path

BASE_DIR = data_dir()
CATALOG_PATH = resource_path("presets", "catalog.json")
PLUGIN_DIR = os.path.join(BASE_DIR, "plugins")

# 内置四套预设（用于一键导入）
DEFAULT_PRESET_IDS = [
    ("zzz", "onedragon"),
    ("genshin", "bettergi_onedragon"),
    ("hsr", "m7a_main"),
    ("arknights", "maa_gui"),
]


def load_catalog():
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def list_games(catalog=None):
    catalog = catalog or load_catalog()
    return [g for g in catalog.get("games", []) if g.get("id") != "custom"]


def get_game(catalog, game_id):
    for g in catalog.get("games", []):
        if g.get("id") == game_id:
            return g
    return None


def get_script(game, script_id):
    if not game:
        return None
    for s in game.get("scripts", []):
        if s.get("id") == script_id:
            return s
    return None


def find_script_by_preset_id(catalog, preset_id):
    for g in catalog.get("games", []):
        for s in g.get("scripts", []):
            if s.get("id") == preset_id:
                return g, s
    return None, None


def _slug(text):
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text)
    return text.strip("_")[:40] or "game"


def next_plugin_order():
    items = glob.glob(os.path.join(PLUGIN_DIR, "*.json"))
    if not items:
        return 1
    orders = []
    for f in items:
        try:
            with open(f, encoding="utf-8") as fh:
                orders.append(int(json.load(fh).get("order", 999)))
        except Exception:
            pass
    return max(orders, default=0) + 1


def build_plugin(game, script, launcher_path, order=None, checklist_done=None):
    """从预设生成插件 dict（不含 _file）。"""
    order = order or next_plugin_order()
    preset_id = script.get("id", "")
    game_procs = script.get("game_processes")
    if game_procs is None:
        game_procs = game.get("game_processes", [])

    plugin = {
        "id": "%s_%s" % (game.get("id", "custom"), preset_id),
        "name": "%s · %s" % (game.get("name", ""), script.get("name", "")),
        "launcher": launcher_path or "",
        "args": list(script.get("args", [])),
        "wait_mode": script.get("wait_mode", "game"),
        "game_processes": list(game_procs),
        "helper_processes": list(script.get("helper_processes", [])),
        "start_timeout_min": int(script.get("start_timeout_min", 15)),
        "parallel": bool(script.get("parallel_default", False)),
        "enabled": True,
        "order": order,
        "notes": script.get("notes", ""),
        "preset_id": preset_id,
        "preset_game_id": game.get("id", ""),
        "setup_checklist": list(script.get("setup_checklist", [])),
        "checklist_done": checklist_done if checklist_done is not None else [],
        "doc_url": game.get("doc_url", script.get("doc_url", "")),
    }
    if script.get("pre_launcher"):
        plugin["pre_launcher"] = script.get("pre_launcher", "")
        plugin["pre_args"] = list(script.get("pre_args", []))
        plugin["pre_delay_sec"] = int(script.get("pre_delay_sec", 0))
    return plugin


def save_plugin_file(plugin, filename=None):
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    order = plugin.get("order", next_plugin_order())
    if not filename:
        slug = _slug(plugin.get("name", "game"))
        filename = "%d_%s.json" % (order, slug)
    path = os.path.join(PLUGIN_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plugin, f, ensure_ascii=False, indent=2)
    plugin["_file"] = path
    return path


def resolve_and_build(game_id, script_id, settings, launcher_override=None):
    catalog = load_catalog()
    game = get_game(catalog, game_id)
    script = get_script(game, script_id)
    if not game or not script:
        raise ValueError("未知预设：%s / %s" % (game_id, script_id))

    if script_id == "manual":
        return build_plugin(game, script, "", order=next_plugin_order())

    if launcher_override:
        path = os.path.normpath(launcher_override)
    else:
        roots = default_search_roots(BASE_DIR, settings)
        path, _ = resolve_launcher(script, settings, roots)

    return build_plugin(game, script, path)


def import_default_plugins(settings, overwrite=False):
    """
    导入四套默认插件。若 plugins 非空且 overwrite=False 则跳过。
    返回 (created_count, skipped_count)
    """
    existing = glob.glob(os.path.join(PLUGIN_DIR, "*.json"))
    if existing and not overwrite:
        return 0, len(existing)

    if overwrite and existing:
        for f in existing:
            try:
                os.remove(f)
            except Exception:
                pass

    catalog = load_catalog()
    roots = default_search_roots(BASE_DIR, settings)
    created = 0
    order = 1
    for game_id, script_id in DEFAULT_PRESET_IDS:
        game = get_game(catalog, game_id)
        script = get_script(game, script_id)
        if not game or not script:
            continue
        path, _ = resolve_launcher(script, settings, roots)
        plugin = build_plugin(game, script, path, order=order)
        save_plugin_file(plugin)
        if path and script_id:
            update_path_cache(settings, script_id, path)
        order += 1
        created += 1
    return created, 0


def pending_checklist_count(plugin):
    """未完成 checklist 条数（软警告用）。"""
    return len(pending_checklist_items(plugin))


def pending_checklist_items(plugin):
    """返回未完成的 checklist 条目列表。"""
    items = plugin.get("setup_checklist") or []
    done = set(plugin.get("checklist_done") or [])
    return [item for item in items if item not in done]
