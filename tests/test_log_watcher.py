# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import time
import unittest
import unittest.mock

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
            # 完成与失败关键词同时命中时按已完成处理（崩铁脚本的正常行为）
            self.assertEqual(result["task_status"], lw.TASK_COMPLETED)

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

    def test_line_split_across_polls_not_missed_or_misread(self):
        """一行日志被两次 poll 截断：不误报也不漏报。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "split.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(log_file=p, encoding="gbk",
                                    daily_done_patterns=["每日实训已完成"])
            self.assertTrue(w.start())
            _append_gbk(p, "2026-08-02 | INFO | 每日实训")
            w.poll()  # 只写了半行：半行被缓存，不参与分类
            self.assertEqual(w._daily_done, [])
            _append_gbk(p, "已完成\n")
            w.poll()
            result = w.finish()
            self.assertEqual(len(result["daily_done"]), 1)

    def test_multibyte_char_split_across_polls_utf8(self):
        """utf-8 三字节汉字被 chunk 边界截断：不产生乱码、正常匹配。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "mb.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(log_file=p, encoding="utf-8",
                                    daily_done_patterns=["已完成"])
            w.start()
            full = "任务已完成".encode("utf-8")
            with open(p, "ab") as f:
                f.write(full[:7])  # 截断在「已」的第二个字节处
            w.poll()
            with open(p, "ab") as f:
                f.write(full[7:])
            w.poll()
            result = w.finish()
            self.assertEqual(len(result["daily_done"]), 1)
            self.assertNotIn("\ufffd", result["daily_done"][0])

    def test_multibyte_char_split_across_polls_gbk(self):
        """gbk 双字节汉字被 chunk 边界截断：正常匹配。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "mbg.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(log_file=p, encoding="gbk",
                                    daily_done_patterns=["已完成"])
            w.start()
            full = "日常已完成".encode("gbk")
            with open(p, "ab") as f:
                f.write(full[:5])  # 截断在「已」的引导字节处
            w.poll()
            with open(p, "ab") as f:
                f.write(full[5:])
            w.poll()
            result = w.finish()
            self.assertEqual(len(result["daily_done"]), 1)

    def test_rotation_new_file_larger_than_offset(self):
        """日志被替换成更大的新文件：从新文件开头重读（旧实现会漏掉开头）。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rot.log")
            newp = os.path.join(d, "new.log")
            _write_gbk(p, "旧日志内容，用于占满 offset\n")
            w = lw.ScriptLogWatcher(log_file=p, encoding="gbk",
                                    daily_done_patterns=["新任务已完成"])
            self.assertTrue(w.start())
            # 新文件比旧 offset 更大，且匹配行位于旧 offset 之前
            _write_gbk(newp, "新任务已完成\n" + "x" * 100)
            os.replace(newp, p)
            w.poll()
            result = w.finish()
            self.assertTrue(any("新任务已完成" in line for line in result["daily_done"]))

    def test_finish_caps_per_category_and_reports_truncation(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cap.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(log_file=p, encoding="gbk",
                                    daily_done_patterns=["完成"], max_per_category=5)
            w.start()
            _append_gbk(p, "".join("第%d次完成\n" % i for i in range(12)))
            w.poll()
            result = w.finish()
            self.assertEqual(len(result["daily_done"]), 5)
            self.assertTrue(result["truncated"]["daily_done"])
            self.assertIn("第11次完成", result["daily_done"][-1])
            self.assertFalse(result["truncated"]["stamina"])

class TestResolveTaskStatus(unittest.TestCase):
    def test_no_patterns_unknown(self):
        self.assertEqual(
            lw.resolve_task_status([], [], done_configured=False, pending_configured=False),
            lw.TASK_UNKNOWN)

    def test_done_wins_when_both_hit(self):
        """崩铁完成后会补打「未检测到奖励」，应判已完成。"""
        self.assertEqual(
            lw.resolve_task_status(["每日实训已完成"], ["未检测到每日实训奖励"],
                                   done_configured=True, pending_configured=True),
            lw.TASK_COMPLETED)

    def test_done_configured_but_missing_is_incomplete(self):
        self.assertEqual(
            lw.resolve_task_status([], [], done_configured=True, pending_configured=True),
            lw.TASK_INCOMPLETE)

    def test_only_failure_configured_and_clean_is_completed(self):
        """MaaEnd / OneDragon 只配失败关键词：没有失败行就是已完成。"""
        self.assertEqual(
            lw.resolve_task_status([], [], done_configured=False, pending_configured=True),
            lw.TASK_COMPLETED)

    def test_only_failure_configured_and_hit_is_incomplete(self):
        self.assertEqual(
            lw.resolve_task_status([], ["执行失败"],
                                   done_configured=False, pending_configured=True),
            lw.TASK_INCOMPLETE)

    def test_done_only_missing_is_incomplete(self):
        self.assertEqual(
            lw.resolve_task_status([], [], done_configured=True, pending_configured=False),
            lw.TASK_INCOMPLETE)


class TestFollowGuardAndReadCap(unittest.TestCase):
    """轮转跟随守卫（防旧文件被触碰后整份误读）与单次读取上限。"""

    def test_should_follow_rejects_old_file_when_current_alive(self):
        """候选文件创建时间早于本次运行开始：不跟随（防外部触碰旧文件）。"""
        with tempfile.TemporaryDirectory() as d:
            cur = os.path.join(d, "cur.log")
            old = os.path.join(d, "old.log")
            _write_gbk(cur, "x")
            _write_gbk(old, "y")
            w = lw.ScriptLogWatcher(log_file=os.path.join(d, "*.log"))
            w.path = cur
            w._started_at = time.time()
            with unittest.mock.patch("os.path.getctime", return_value=w._started_at - 100):
                self.assertFalse(w._should_follow(old))
            # 候选是本次运行期间创建的（ctime 晚于 start）→ 跟随
            self.assertTrue(w._should_follow(old))
            # 当前文件已不存在 → 必须跟随，否则监控中断
            os.remove(cur)
            with unittest.mock.patch("os.path.getctime", return_value=w._started_at - 100):
                self.assertTrue(w._should_follow(old))

    def test_poll_keeps_following_current_when_only_old_file_touched(self):
        """运行中旧文件被触碰成为 mtime 最新：不切过去，继续读当前文件。"""
        with tempfile.TemporaryDirectory() as d:
            cur = os.path.join(d, "cur.log")
            old = os.path.join(d, "old.log")
            _write_gbk(cur, "")
            _write_gbk(old, "旧任务已完成\n")
            os.utime(old, (1, 1))
            w = lw.ScriptLogWatcher(log_file=os.path.join(d, "*.log"), encoding="gbk",
                                    daily_done_patterns=["任务已完成"])
            w.start()
            self.assertTrue(w.path.endswith("old.log") or w.path.endswith("cur.log"))
            w.path = cur          # 模拟已锁定当前文件
            w._offset = 0
            _append_gbk(cur, "新任务已完成\n")
            os.utime(old, (time.time() + 10,) * 2)  # 旧文件 mtime 被外部刷新到最新
            real_ctime = os.path.getctime
            with unittest.mock.patch(
                    "os.path.getctime",
                    side_effect=lambda p: w._started_at - 100 if p == old else real_ctime(p)):
                w.poll()
            result = w.finish()
            # 未切到 old.log：旧日志里的「旧任务已完成」没有混进来
            self.assertEqual(len(result["daily_done"]), 1)
            self.assertIn("新任务已完成", result["daily_done"][0])
            self.assertTrue(all("旧任务" not in line for line in result["daily_done"]))

    def test_poll_follows_genuinely_new_file(self):
        """脚本运行期间创建的新日志文件正常跟随（守卫不误伤）。"""
        with tempfile.TemporaryDirectory() as d:
            stale = os.path.join(d, "2026-09-10-1.log")
            fresh = os.path.join(d, "2026-09-11-1.log")
            _write_gbk(stale, "旧会话内容\n")
            os.utime(stale, (1, 1))
            w = lw.ScriptLogWatcher(log_file=os.path.join(d, "*.log"), encoding="gbk",
                                    daily_done_patterns=["收尾任务已提交"])
            w.start()
            self.assertTrue(w.path.endswith("2026-09-10-1.log"))
            _write_gbk(fresh, "收尾任务已提交\n")
            w.poll()
            result = w.finish()
            self.assertEqual(len(result["daily_done"]), 1)
            self.assertTrue(w.path.endswith("2026-09-11-1.log"))

    def test_poll_read_capped_and_catches_up(self):
        """单次 poll 读入量受上限约束，后续 poll 分批消化不丢行。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "big.log")
            _write_gbk(p, "")
            w = lw.ScriptLogWatcher(log_file=p, encoding="gbk",
                                    daily_done_patterns=["任务已完成"])
            w.start()
            payload = "前缀内容" * 20 + "任务已完成\n"
            _append_gbk(p, payload)
            size = os.path.getsize(p)
            with unittest.mock.patch.object(lw, "MAX_POLL_READ", 8):
                w.poll()
                self.assertLess(w._offset, size)   # 首次只读入上限字节
                while w._offset < size:             # 分批追上剩余增量
                    w.poll()
            result = w.finish()
            self.assertEqual(len(result["daily_done"]), 1)
            self.assertEqual(w._offset, size)

    def test_decode_lossy_prefers_configured_encoding(self):
        """残留字节按配置编码容错解码，不再硬编码 utf-8。"""
        gbk_bytes = "完成".encode("gbk")
        self.assertEqual(lw._decode_lossy(gbk_bytes, ["gbk"]), "完成")
        self.assertIn("\ufffd", lw._decode_lossy(gbk_bytes[:1], ["gbk"]))
        utf8_bytes = "完成".encode("utf-8")
        self.assertEqual(lw._decode_lossy(utf8_bytes, ["utf-8", "gbk"]), "完成")


if __name__ == "__main__":
    unittest.main()
