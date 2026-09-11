# -*- coding: utf-8 -*-
"""同服务器日（凌晨 4 点每日重置）重复运行的判定降级。"""
import datetime
import os
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import runner_core as rc
from runner_core import (TASK_COMPLETED, TASK_INCOMPLETE, TASK_UNKNOWN,
                         resolve_daily_repeat, server_day)


class TestServerDay(unittest.TestCase):
    def test_before_four_am_belongs_to_previous_day(self):
        self.assertEqual(server_day(datetime.datetime(2026, 9, 12, 3, 59)),
                         datetime.date(2026, 9, 11))

    def test_at_and_after_four_am_is_same_day(self):
        self.assertEqual(server_day(datetime.datetime(2026, 9, 12, 4, 0)),
                         datetime.date(2026, 9, 12))
        self.assertEqual(server_day(datetime.datetime(2026, 9, 12, 23, 30)),
                         datetime.date(2026, 9, 12))


class TestResolveDailyRepeat(unittest.TestCase):
    def test_same_server_day_repeat_downgrades_incomplete(self):
        now = datetime.datetime(2026, 9, 12, 22, 0)
        last = datetime.datetime(2026, 9, 12, 10, 0)
        status, repeated = resolve_daily_repeat(TASK_INCOMPLETE, last, now)
        self.assertEqual((status, repeated), (TASK_COMPLETED, True))

    def test_late_night_completion_covers_after_midnight_run(self):
        # 23:00 完成，次日（自然日）00:30 再跑：仍是同一服务器日
        now = datetime.datetime(2026, 9, 13, 0, 30)
        last = datetime.datetime(2026, 9, 12, 23, 0)
        status, repeated = resolve_daily_repeat(TASK_INCOMPLETE, last, now)
        self.assertEqual((status, repeated), (TASK_COMPLETED, True))

    def test_next_server_day_alarms_again(self):
        now = datetime.datetime(2026, 9, 13, 10, 0)
        last = datetime.datetime(2026, 9, 12, 22, 0)
        self.assertEqual(resolve_daily_repeat(TASK_INCOMPLETE, last, now),
                         (TASK_INCOMPLETE, False))

    def test_just_after_reset_not_suppressed(self):
        # 昨天 23:00 完成，今天 04:00 重置后 04:01 再跑：新服务器日，照常判定
        now = datetime.datetime(2026, 9, 13, 4, 1)
        last = datetime.datetime(2026, 9, 12, 23, 0)
        self.assertEqual(resolve_daily_repeat(TASK_INCOMPLETE, last, now),
                         (TASK_INCOMPLETE, False))

    def test_no_record_or_non_incomplete_untouched(self):
        now = datetime.datetime(2026, 9, 12, 22, 0)
        self.assertEqual(resolve_daily_repeat(TASK_INCOMPLETE, None, now),
                         (TASK_INCOMPLETE, False))
        self.assertEqual(resolve_daily_repeat(TASK_COMPLETED, None, now),
                         (TASK_COMPLETED, False))
        self.assertEqual(resolve_daily_repeat(TASK_UNKNOWN, None, now),
                         (TASK_UNKNOWN, False))


class TestDailyDoneState(unittest.TestCase):
    def test_roundtrip_and_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daily_state.json")
            st = rc.DailyDoneState(path)
            self.assertIsNone(st.last_done("g1"))
            st.mark_done("g1", datetime.datetime(2026, 9, 12, 10, 0, 0))
            # 重新加载（模拟重启程序）
            again = rc.DailyDoneState(path)
            self.assertEqual(again.last_done("g1"),
                             datetime.datetime(2026, 9, 12, 10, 0, 0))
            self.assertIsNone(again.last_done("g2"))

    def test_memory_only_without_path(self):
        st = rc.DailyDoneState(None)
        st.mark_done("g1")
        self.assertIsNotNone(st.last_done("g1"))

    def test_corrupt_file_falls_back_to_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daily_state.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not json")
            st = rc.DailyDoneState(path)
            self.assertIsNone(st.last_done("g1"))
            # 损坏文件不影响后续写入
            st.mark_done("g1")
            self.assertIsNotNone(rc.DailyDoneState(path).last_done("g1"))


if __name__ == "__main__":
    unittest.main()
