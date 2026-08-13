# -*- coding: utf-8 -*-
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from ui_helpers import LogStore, clamp_window_bounds, elide_end, elide_middle, group_tagged_lines


class TestLogStore(unittest.TestCase):
    def test_keeps_only_latest_lines(self):
        store = LogStore(max_lines=3)
        dropped = store.append_many(["a", "b", "c", "d"])
        self.assertEqual(dropped, 1)
        self.assertEqual([t for t, _ in store.lines], ["b", "c", "d"])
        self.assertEqual(store.dropped_total, 1)

    def test_export_text_has_one_trailing_newline(self):
        store = LogStore(max_lines=10)
        store.append_many(["a\n", "b"])
        self.assertEqual(store.export_text(), "a\nb\n")

    def test_accepts_structured_level_entries(self):
        store = LogStore(max_lines=10)
        store.append_many([("完成", "gold"), "普通", ("出错", "error")])
        self.assertEqual(store.lines, [("完成", "gold"), ("普通", None), ("出错", "error")])
        self.assertEqual(store.export_text(), "完成\n普通\n出错\n")


class TestBatchHelpers(unittest.TestCase):
    def test_groups_adjacent_lines_with_same_tag(self):
        groups = group_tagged_lines(
            ["普通", "[警告] 一", "[警告] 二", "普通二"],
            lambda line: "warn" if "[警告]" in line else None,
        )
        self.assertEqual(groups, [
            (None, "普通\n"),
            ("warn", "[警告] 一\n[警告] 二\n"),
            (None, "普通二\n"),
        ])

    def test_groups_leveled_entries_pass_level_to_tag_func(self):
        def tag_func(line, level=None):
            return level or ("warn" if "[警告]" in line else None)

        groups = group_tagged_lines(
            ["普通", ("完成", "gold"), ("第二行", "gold"), "[警告] 一"],
            tag_func,
        )
        self.assertEqual(groups, [
            (None, "普通\n"),
            ("gold", "完成\n第二行\n"),
            ("warn", "[警告] 一\n"),
        ])

    def test_elides_middle_without_losing_filename(self):
        path = r"E:\\Games\\a-very-long-folder\\nested\\BetterGI.exe"
        short = elide_middle(path, 28)
        self.assertLessEqual(len(short), 28)
        self.assertTrue(short.endswith("BetterGI.exe"))
        self.assertIn("…", short)

    def test_elides_title_at_end(self):
        self.assertEqual(elide_end("崩坏：星穹铁道 · March7th", 10), "崩坏：星穹铁道 …")


class TestWindowBounds(unittest.TestCase):
    def test_clamps_window_back_to_visible_screen(self):
        bounds = clamp_window_bounds(
            {"x": 3000, "y": -900, "width": 1200, "height": 900},
            screen_width=1920,
            screen_height=1080,
            min_width=940,
            min_height=660,
        )
        self.assertGreaterEqual(bounds[0], 0)
        self.assertGreaterEqual(bounds[1], 0)
        self.assertLessEqual(bounds[0] + bounds[2], 1920)
        self.assertLessEqual(bounds[1] + bounds[3], 1080)


if __name__ == "__main__":
    unittest.main()
