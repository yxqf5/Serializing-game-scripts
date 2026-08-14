# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import log_saver as ls


class TestRetention(unittest.TestCase):
    def test_retention_days_mapping(self):
        self.assertEqual(ls.retention_days("week"), 7)
        self.assertEqual(ls.retention_days("month"), 30)
        self.assertIsNone(ls.retention_days("forever"))
        self.assertEqual(ls.retention_days(""), 30)  # 未知值回退一个月
        self.assertEqual(ls.retention_days("最近一周"), 7)
        self.assertEqual(ls.retention_days("不清理"), None)

    def test_today_filename(self):
        self.assertEqual(ls.today_filename(datetime.datetime(2026, 8, 13, 10, 0)),
                         "2026-08-13.md")


class TestBuildMarkdown(unittest.TestCase):
    def test_build_run_markdown_structure(self):
        start = datetime.datetime(2026, 8, 13, 8, 12, 33)
        end = datetime.datetime(2026, 8, 13, 8, 47, 2)
        md = ls.build_run_markdown(
            1, start, end, "completed",
            [("原神", "completed"), ("崩铁", "skipped")],
            ["[08:12:33] 开始串行执行，共 2 个游戏。", "    结果行"])
        self.assertIn("## 运行记录 · 第 1 次 · 08:12:33 → 08:47:02 · 全部完成", md)
        self.assertIn("### 摘要", md)
        self.assertIn("- 共 2 个游戏，完成 1 个，1 个未完成", md)
        self.assertIn("- ✅ 原神", md)
        self.assertIn("- ⏭ 崩铁", md)
        self.assertIn("### 日志", md)
        self.assertIn("```text", md)
        self.assertIn("[08:12:33] 开始串行执行", md)
        self.assertTrue(md.endswith("```\n"))

    def test_build_run_markdown_stopped_no_tasks(self):
        start = datetime.datetime(2026, 8, 13, 9, 0, 0)
        md = ls.build_run_markdown(1, start, start, "stopped", [], ["x"])
        self.assertIn("用户停止", md)
        self.assertIn("- 未启动任何游戏", md)


class TestAppendAndCleanup(unittest.TestCase):
    def test_append_creates_file_with_header_and_divider(self):
        with tempfile.TemporaryDirectory() as d:
            now = datetime.datetime(2026, 8, 13, 10, 0)
            rec = ls.build_run_markdown(1, now, now, "completed", [], ["a"])
            path, no = ls.append_run_record(d, rec, now=now)
            self.assertEqual(no, 1)
            self.assertTrue(path.endswith("2026-08-13.md"))
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertTrue(text.startswith("# 运行日志 · 2026-08-13\n"))
            self.assertIn("## 运行记录 · 第 1 次", text)

            # 第二次运行：同一天追加，分割线隔开，编号 +1
            rec2 = ls.build_run_markdown(2, now, now, "stopped", [], ["b"])
            path2, no2 = ls.append_run_record(d, rec2, now=now)
            self.assertEqual(no2, 2)
            with open(path2, encoding="utf-8") as f:
                text = f.read()
            self.assertEqual(text.count("## 运行记录"), 2)
            self.assertIn("\n---\n\n", text)
            self.assertEqual(ls.today_record_count(d, now=now), 2)

    def test_cleanup_removes_only_old_own_files(self):
        with tempfile.TemporaryDirectory() as d:
            now = datetime.datetime(2026, 8, 13, 10, 0)
            with open(os.path.join(d, "2026-01-01.md"), "w", encoding="utf-8") as f:
                f.write("old")
            with open(os.path.join(d, "2026-08-10.md"), "w", encoding="utf-8") as f:
                f.write("recent")
            with open(os.path.join(d, "mynote.txt"), "w", encoding="utf-8") as f:
                f.write("keep me")
            with open(os.path.join(d, "notes.md"), "w", encoding="utf-8") as f:
                f.write("user file")
            # 保留 30 天：2026-01-01 早于截止线 → 删除；日期命名的近文件与无关文件保留
            removed = ls.cleanup_old_logs(d, 30, now=now)
            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(os.path.join(d, "2026-01-01.md")))
            self.assertTrue(os.path.exists(os.path.join(d, "2026-08-10.md")))
            self.assertTrue(os.path.exists(os.path.join(d, "mynote.txt")))
            self.assertTrue(os.path.exists(os.path.join(d, "notes.md")))
            # forever：不清理
            self.assertEqual(ls.cleanup_old_logs(d, None, now=now), 0)
            # 不存在目录：安全返回 0
            self.assertEqual(ls.cleanup_old_logs(os.path.join(d, "nope"), 30, now=now), 0)


if __name__ == "__main__":
    unittest.main()
