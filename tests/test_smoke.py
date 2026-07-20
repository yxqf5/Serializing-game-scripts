# -*- coding: utf-8 -*-
"""无 GUI 冒烟：模块可导入、预设可解析。"""
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import preset_catalog as pc
import preflight
from preset_resolver import resolve_launcher, default_search_roots


class TestSmoke(unittest.TestCase):
    def test_resolve_real_hints(self):
        cat = pc.load_catalog()
        g = pc.get_game(cat, "zzz")
        s = pc.get_script(g, "onedragon")
        roots = default_search_roots(BASE)
        path, src = resolve_launcher(s, {}, roots, use_cache=False)
        if os.path.isfile(r"E:\Games\py\zzz\OneDragon-Launcher.exe"):
            self.assertTrue(path)
            self.assertIn(src, ("hint", "glob", "cache"))

    def test_preflight_on_loaded_plugins(self):
        plugins = []
        pdir = os.path.join(BASE, "plugins")
        for fn in os.listdir(pdir):
            if fn.endswith(".json"):
                import json
                with open(os.path.join(pdir, fn), encoding="utf-8") as f:
                    plugins.append(json.load(f))
        issues = preflight.check_plugins([p for p in plugins if p.get("enabled", True)])
        self.assertFalse(preflight.has_blocking_errors(issues))


if __name__ == "__main__":
    unittest.main()
