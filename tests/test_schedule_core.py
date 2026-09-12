# -*- coding: utf-8 -*-
"""定时任务纯逻辑:每日触发时刻计算与配置归一化。"""
import datetime
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import schedule_core as sc


class TestParseHhmm(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(sc.parse_hhmm("04:00"), datetime.time(4, 0))
        self.assertEqual(sc.parse_hhmm("23:05"), datetime.time(23, 5))

    def test_whitespace_and_no_leading_zero(self):
        self.assertEqual(sc.parse_hhmm(" 8:30 "), datetime.time(8, 30))

    def test_seconds_form(self):
        self.assertEqual(sc.parse_hhmm("04:00:00"), datetime.time(4, 0))

    def test_invalid(self):
        self.assertIsNone(sc.parse_hhmm(""))
        self.assertIsNone(sc.parse_hhmm("25:00"))
        self.assertIsNone(sc.parse_hhmm("abc"))
        self.assertIsNone(sc.parse_hhmm("0400"))
        self.assertIsNone(sc.parse_hhmm(None))
        self.assertIsNone(sc.parse_hhmm(430))


class TestNextDailyOccurrence(unittest.TestCase):
    def test_before_time_is_today(self):
        now = datetime.datetime(2026, 9, 12, 2, 0)
        self.assertEqual(
            sc.next_daily_occurrence(datetime.time(4, 0), now),
            datetime.datetime(2026, 9, 12, 4, 0))

    def test_after_time_is_tomorrow(self):
        now = datetime.datetime(2026, 9, 12, 5, 0)
        self.assertEqual(
            sc.next_daily_occurrence(datetime.time(4, 0), now),
            datetime.datetime(2026, 9, 13, 4, 0))

    def test_exactly_now_counts_as_passed(self):
        # 恰好等于 now 视为已过:避免保存设置的一瞬(秒级重合)立刻弹窗
        now = datetime.datetime(2026, 9, 12, 4, 0, 0)
        self.assertEqual(
            sc.next_daily_occurrence(datetime.time(4, 0), now),
            datetime.datetime(2026, 9, 13, 4, 0))

    def test_none_time(self):
        self.assertIsNone(
            sc.next_daily_occurrence(None, datetime.datetime(2026, 9, 12, 4, 0)))


class TestCountdownBounds(unittest.TestCase):
    def test_clamps(self):
        self.assertEqual(sc.countdown_bounds(1), sc.COUNTDOWN_MIN)
        self.assertEqual(sc.countdown_bounds(99999), sc.COUNTDOWN_MAX)
        self.assertEqual(sc.countdown_bounds(90), 90)

    def test_bad_values_fall_back_to_default(self):
        self.assertEqual(sc.countdown_bounds(None), sc.DEFAULT_COUNTDOWN_SEC)
        self.assertEqual(sc.countdown_bounds("abc"), sc.DEFAULT_COUNTDOWN_SEC)


class TestScheduleConfig(unittest.TestCase):
    def test_enabled_normalized(self):
        cfg = sc.schedule_config({"schedule_enabled": True,
                                  "schedule_time": "8:30",
                                  "schedule_countdown_sec": 99999})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["time"], datetime.time(8, 30))
        self.assertEqual(cfg["time_text"], "08:30")
        self.assertEqual(cfg["countdown_sec"], sc.COUNTDOWN_MAX)

    def test_disabled_or_bad_time(self):
        self.assertFalse(sc.schedule_config(
            {"schedule_enabled": True, "schedule_time": "xx"})["enabled"])
        self.assertFalse(sc.schedule_config({})["enabled"])

    def test_defaults(self):
        cfg = sc.schedule_config({"schedule_enabled": True})
        self.assertEqual(cfg["time"], datetime.time(4, 0))
        self.assertEqual(cfg["countdown_sec"], sc.DEFAULT_COUNTDOWN_SEC)

    def test_countdown_still_normalized_when_disabled(self):
        cfg = sc.schedule_config({"schedule_enabled": False,
                                  "schedule_countdown_sec": 0})
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["countdown_sec"], sc.COUNTDOWN_MIN)


if __name__ == "__main__":
    unittest.main()
