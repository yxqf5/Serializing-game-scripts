# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import log_watcher as lw


def _write_gbk(path, text):
    with open(path, "wb") as f:
        f.write(text.encode("gbk"))


def _append_gbk(path, text):
    with open(path, "ab") as f:
        f.write(text.encode("gbk"))


class TestResolveLogFile(unittest.TestCase):
    def test_direct_path_exists(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.log")
            _write_gbk(p, "x")
            self.assertEqual(lw.resolve_log_file(p), p)

    def test_direct_path_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "nope.log")
            self.assertIsNone(lw.resolve_log_file(p))

    def test_glob_picks_latest(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.log")
            b = os.path.join(d, "b.log")
            _write_gbk(a, "x")
            _write_gbk(b, "yy")
            os.utime(a, (1, 1))
            os.utime(b, (2, 2))
            self.assertEqual(lw.resolve_log_file(os.path.join(d, "*.log")), b)

    def test_empty_pattern(self):
        self.assertIsNone(lw.resolve_log_file(""))


class TestScriptLogWatcher(unittest.TestCase):
    def test_classify_daily_and_stamina_gbk(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "run.log")
            _write_gbk(p, "2026-08-02 | INFO | 开始\n")
            w = lw.ScriptLogWatcher(
                log_file=p, encoding="gbk",
                daily_done_patterns=["每日实训已完成"],
                daily_pending_patterns=["未检测到每日实训奖励"],
                stamina_patterns=["开拓力"])
            self.assertTrue(w.start())
            w.poll()  # 已有内容不重复读
            _append_gbk(p, "2026-08-02 | INFO | 未检测到每日实训奖励\n"
                            "2026-08-02 | INFO | 开拓力: 36/300\n"
                            "2026-08-02 | INFO | 开拓力剩余36/300\n"
                            "2026-08-02 | INFO | 每日实训已完成\n"
                            "2026-08-02 | INFO | 开拓力剩余69/300\n")
            w.poll()
            result = w.finish()
            self.assertTrue(any("每日实训已完成" in line for line in result["daily_done"]))
            self.assertTrue(any("未检测到每日实训奖励" in line for line in result["daily_pending"]))
            # 体力只保留最新一条
            self.assertEqual(len(result["stamina"]), 1)
            self.assertIn("69/300", result["stamina"][0])

    def test_stamina_latest_wins_over_done(self):
        """体力行出现多次只留最新；先命中体力后命中其他分类互不干扰。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(log_file=p, encoding="gbk",
                                    daily_done_patterns=["完成"],
                                    stamina_patterns=["体力"])
            w.start()
            _append_gbk(p, "体力: 10\n每日完成\n体力: 99\n")
            w.poll()
            result = w.finish()
            self.assertEqual(len(result["stamina"]), 1)
            self.assertIn("99", result["stamina"][0])
            self.assertEqual(len(result["daily_done"]), 1)

    def test_rotation_detects_truncated_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "run.log")
            _write_gbk(p, "很长很长的旧日志内容，超过新文件长度\n")
            w = lw.ScriptLogWatcher(log_file=p, encoding="gbk",
                                    daily_done_patterns=["完成"])
            self.assertTrue(w.start())
            # 模拟轮转：日志被清空并重写为更短的新内容（旧 offset 大于新大小）
            _write_gbk(p, "今日日常完成\n")
            w.poll()
            result = w.finish()
            self.assertTrue(any("今日日常完成" in line for line in result["daily_done"]))

    def test_no_file_start_false(self):
        with tempfile.TemporaryDirectory() as d:
            w = lw.ScriptLogWatcher(log_file=os.path.join(d, "missing.log"))
            self.assertFalse(w.start())
            self.assertEqual(w.finish()["daily_done"], [])

    def test_utf8_auto_decode(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "u.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(log_file=p, encoding="auto",
                                    daily_done_patterns=["已完成"])
            self.assertTrue(w.start())
            with open(p, "a", encoding="utf-8") as f:
                f.write("2026-08-02 | INFO | 日常任务已完成\n")
            w.poll()
            result = w.finish()
            self.assertTrue(any("日常任务已完成" in line for line in result["daily_done"]))

    def test_dedup_keep_order(self):
        lines = ["a", "b", "a", "c"]
        self.assertEqual(lw._dedup_keep_order(lines), ["a", "b", "c"])

    def test_invalid_regex_falls_back_to_literal(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(log_file=p, encoding="gbk",
                                    daily_done_patterns=["[invalid"])
            self.assertTrue(w.start())
            _append_gbk(p, "line with [invalid\n")
            w.poll()
            result = w.finish()
            self.assertEqual(len(result["daily_done"]), 1)

    def test_json_regex_pattern(self):
        """MAA 日志 JSON 行：正则含转义引号。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "maa.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(
                log_file=p, encoding="auto",
                daily_done_patterns=['TaskChainCompleted.*"taskchain":"Award"'],
                stamina_patterns=["Current Sanity: \\d+"])
            w.start()
            _append_gbk(p, 'Assistant::append_callback | TaskChainCompleted {"taskchain":"Award","taskid":6}\n'
                            'Current Sanity: 82 , Max Sanity: 205\n')
            w.poll()
            result = w.finish()
            self.assertEqual(len(result["daily_done"]), 1)
            self.assertIn("82", result["stamina"][0])


if __name__ == "__main__":
    unittest.main()
