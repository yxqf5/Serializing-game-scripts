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


if __name__ == "__main__":
    unittest.main()
