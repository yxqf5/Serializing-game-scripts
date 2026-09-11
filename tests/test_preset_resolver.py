# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import preset_resolver as pr


class TestPresetResolver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake_exe = os.path.join(self.tmp, "BetterGI.exe")
        with open(self.fake_exe, "wb") as f:
            f.write(b"")

    def test_resolve_hint_in_script(self):
        script = {
            "id": "test",
            "launcher_hints": [self.fake_exe],
            "launcher_globs": [],
        }
        path, src = pr.resolve_launcher(script, {}, [self.tmp], use_cache=False)
        self.assertEqual(path, os.path.normpath(self.fake_exe))
        self.assertEqual(src, "hint")

    def test_resolve_glob_limited(self):
        sub = os.path.join(self.tmp, "a", "b", "BetterGI")
        os.makedirs(sub)
        exe = os.path.join(sub, "BetterGI.exe")
        with open(exe, "wb") as f:
            f.write(b"")
        script = {
            "id": "test2",
            "launcher_hints": [],
            "launcher_globs": ["**/BetterGI/BetterGI.exe"],
        }
        path, src = pr.resolve_launcher(script, {}, [self.tmp], use_cache=False)
        self.assertTrue(path.endswith("BetterGI.exe"))
        self.assertEqual(src, "glob")

    def test_path_cache(self):
        cached_path = os.path.normpath(__file__)
        settings = {}
        pr.update_path_cache(settings, "abc", cached_path)
        self.assertEqual(settings["path_cache"]["abc"], cached_path)
        script = {"id": "abc", "launcher_hints": [], "launcher_globs": []}
        path, src = pr.resolve_launcher(script, settings, [], use_cache=True)
        self.assertEqual(path, cached_path)
        self.assertEqual(src, "cache")

    def test_resolve_skips_glob_when_disabled(self):
        script = {
            "id": "test3",
            "launcher_hints": [],
            "launcher_globs": ["**/BetterGI.exe"],
        }
        path, src = pr.resolve_launcher(script, {}, [self.tmp], use_cache=False, allow_glob=False)
        self.assertEqual(path, "")
        self.assertEqual(src, "none")

    def test_narrow_roots_excludes_drive_root(self):
        roots = pr.narrow_search_roots(BASE)
        self.assertTrue(all(not r.rstrip("\\").upper() in ("E:", "D:", "C:") for r in roots))

    def test_resolve_times_out(self):
        script = {
            "id": "slow",
            "launcher_hints": [],
            "launcher_globs": ["**/BetterGI.exe"],
        }
        path, src = pr.resolve_launcher(
            script, {}, [self.tmp], use_cache=False, timeout_sec=0,
        )
        self.assertEqual(path, "")
        self.assertEqual(src, "timeout")


class TestAssistantsRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_get_assistants_root(self):
        self.assertEqual(pr.get_assistants_root(None), "")
        self.assertEqual(pr.get_assistants_root({}), "")
        raw = os.path.join(self.tmp, "asroot")
        self.assertEqual(pr.get_assistants_root({"assistants_root": raw}),
                         os.path.normpath(raw))

    def test_narrow_roots_put_assistants_root_first(self):
        sub = os.path.join(self.tmp, "asroot")
        os.makedirs(sub)
        roots = pr.narrow_search_roots(self.tmp, {"assistants_root": sub})
        self.assertEqual(roots[0], os.path.normpath(sub))

    def test_default_roots_contain_fixed_drives(self):
        roots = pr.default_search_roots(self.tmp, {})
        drives = pr.fixed_drives()
        self.assertTrue(drives)
        for drv in drives:
            self.assertIn(os.path.normpath(drv), roots)

    def test_assistants_root_scanned_deep(self):
        # 助手根目录下的深层结构也能扫到（盘符根只浅扫，根目录深扫）
        root = os.path.join(self.tmp, "asroot")
        exe = os.path.join(root, "a", "b", "c", "MaaEnd.exe")
        os.makedirs(os.path.dirname(exe))
        with open(exe, "wb") as f:
            f.write(b"")
        script = {"id": "maaend_gui", "launcher_hints": [],
                  "launcher_globs": ["**/MaaEnd.exe"]}
        path, src = pr.resolve_launcher(script, {"assistants_root": root},
                                        use_cache=False)
        self.assertEqual(src, "glob")
        self.assertTrue(path.endswith("MaaEnd.exe"))

    def test_max_depth_for_drive_root(self):
        self.assertEqual(pr._max_depth_for_root("E:\\"), 2)
        self.assertEqual(pr._max_depth_for_root("Q:\\"), 2)
        self.assertEqual(pr._max_depth_for_root(os.path.join(self.tmp, "x")), 5)


if __name__ == "__main__":
    unittest.main()
