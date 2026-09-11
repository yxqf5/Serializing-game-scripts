# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import preset_catalog as pc


class TestPresetCatalog(unittest.TestCase):
    def test_catalog_loads(self):
        cat = pc.load_catalog()
        self.assertGreaterEqual(cat.get("version", 0), 1)
        self.assertGreaterEqual(len(cat.get("games", [])), 4)

    def test_list_games_excludes_custom_only_in_full_catalog(self):
        cat = pc.load_catalog()
        games = pc.list_games(cat)
        ids = [g["id"] for g in games]
        self.assertIn("genshin", ids)
        self.assertIn("wuwa", ids)
        self.assertIn("reverse1999", ids)
        self.assertNotIn("custom", ids)
        self.assertGreaterEqual(len(games), 6)

    def test_get_game_and_script(self):
        cat = pc.load_catalog()
        g = pc.get_game(cat, "genshin")
        self.assertEqual(g["name"], "原神")
        s = pc.get_script(g, "bettergi_onedragon")
        self.assertIn("startOneDragon", s.get("args", []))
        g2 = pc.get_game(cat, "wuwa")
        s2 = pc.get_script(g2, "okww_daily")
        self.assertEqual(s2.get("args"), ["-t", "1", "-e"])
        g3 = pc.get_game(cat, "reverse1999")
        s3 = pc.get_script(g3, "m9a_cli")
        self.assertEqual(s3.get("args"), ["-d"])

    def test_build_plugin_fields(self):
        cat = pc.load_catalog()
        g = pc.get_game(cat, "zzz")
        s = pc.get_script(g, "onedragon")
        p = pc.build_plugin(g, s, r"E:\test\OneDragon-Launcher.exe", order=99)
        self.assertEqual(p["order"], 99)
        self.assertEqual(p["preset_id"], "onedragon")
        self.assertIn("-o", p["args"])
        self.assertEqual(p["wait_mode"], "game")
        self.assertFalse(p.get("parallel", True))

    def test_build_plugin_parallel_default(self):
        """MAA 预设默认并行；其他预设默认串行。"""
        cat = pc.load_catalog()
        g = pc.get_game(cat, "arknights")
        s = pc.get_script(g, "maa_gui")
        p = pc.build_plugin(g, s, r"E:\test\MAA.exe", order=98)
        self.assertTrue(p["parallel"])
        g2 = pc.get_game(cat, "reverse1999")
        s2 = pc.get_script(g2, "m9a_cli")
        p2 = pc.build_plugin(g2, s2, r"E:\test\MaaPiCli.exe", order=97)
        self.assertFalse(p2["parallel"])

    def test_pending_checklist_count(self):
        p = {"setup_checklist": ["a", "b"], "checklist_done": ["a"]}
        self.assertEqual(pc.pending_checklist_count(p), 1)
        self.assertEqual(pc.pending_checklist_items(p), ["b"])
        p2 = {"setup_checklist": [], "checklist_done": []}
        self.assertEqual(pc.pending_checklist_count(p2), 0)
        self.assertEqual(pc.pending_checklist_items(p2), [])


class TestPluginFileIO(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(BASE, "tests", "_tmp_plugins")
        os.makedirs(self.tmp, exist_ok=True)
        self._orig = pc.PLUGIN_DIR
        pc.PLUGIN_DIR = self.tmp

    def tearDown(self):
        pc.PLUGIN_DIR = self._orig
        for f in os.listdir(self.tmp):
            try:
                os.remove(os.path.join(self.tmp, f))
            except Exception:
                pass

    def test_save_plugin_file(self):
        cat = pc.load_catalog()
        g = pc.get_game(cat, "hsr")
        s = pc.get_script(g, "m7a_main")
        p = pc.build_plugin(g, s, r"C:\fake\March7th Launcher.exe", order=1)
        path = pc.save_plugin_file(p)
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["preset_id"], "m7a_main")
        self.assertNotIn("_file", data)


class TestImportDefaults(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(BASE, "tests", "_tmp_plugins_import")
        os.makedirs(self.tmp, exist_ok=True)
        self._orig = pc.PLUGIN_DIR
        pc.PLUGIN_DIR = self.tmp

    def tearDown(self):
        pc.PLUGIN_DIR = self._orig
        for f in os.listdir(self.tmp):
            try:
                os.remove(os.path.join(self.tmp, f))
            except Exception:
                pass

    def test_import_empty_dir(self):
        settings = {}
        created, skipped = pc.import_default_plugins(settings)
        self.assertEqual(created, 4)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(os.listdir(self.tmp)), 4)

    def test_import_skips_when_nonempty(self):
        open(os.path.join(self.tmp, "1_x.json"), "w", encoding="utf-8").write("{}")
        created, skipped = pc.import_default_plugins({})
        self.assertEqual(created, 0)
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
