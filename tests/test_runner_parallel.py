# -*- coding: utf-8 -*-
"""并行运行功能测试：分区、并发执行、日志前缀、停止与回归。"""
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import runner_core as rc


def _make_runner(logs, stop_event=None, events=None):
    return rc.Runner(lambda m, level=None: logs.append((m, level)), stop_event,
                     event_func=(events.append if events is not None else None),
                     settle_sec=0)


class TestSplitQueue(unittest.TestCase):
    def test_split_preserves_order(self):
        a = {"name": "A"}
        b = {"name": "B", "parallel": True}
        c = {"name": "C", "parallel": True}
        d = {"name": "D"}
        par, ser = rc.split_queue([a, b, c, d])
        self.assertEqual([p["name"] for p in par], ["B", "C"])
        self.assertEqual([p["name"] for p in ser], ["A", "D"])

    def test_split_empty(self):
        self.assertEqual(rc.split_queue([]), ([], []))


class TestRunnerParallel(unittest.TestCase):
    def setUp(self):
        # 测试里不让第二个并行任务真的等 3 秒
        self._stagger = patch.object(rc, "PARALLEL_STAGGER_SEC", 0)
        self._stagger.start()
        self.fake_exe = os.path.join(BASE, "tests", "_fake_launcher.exe")
        with open(self.fake_exe, "wb") as f:
            f.write(b"")

    def tearDown(self):
        self._stagger.stop()
        try:
            os.remove(self.fake_exe)
        except Exception:
            pass

    def _plugin(self, name, parallel=False, launcher=None):
        p = {
            "name": name,
            "launcher": launcher if launcher is not None else self.fake_exe,
            "args": [],
            "wait_mode": "helper",
            "helper_processes": [],
            "game_processes": [],
        }
        if parallel:
            p["parallel"] = True
        return p

    def test_parallel_and_serial_both_run(self):
        logs, events = [], []
        runner = _make_runner(logs, events=events)
        with patch.object(rc.subprocess, "Popen"):
            runner.run_all([
                self._plugin("并行游戏", parallel=True),
                self._plugin("串行游戏"),
            ])

        started = [e for e in events if e["type"] == "task_started"]
        finished = [e for e in events if e["type"] == "task_finished"]
        self.assertEqual({e["name"] for e in started}, {"并行游戏", "串行游戏"})
        self.assertEqual({e["name"] for e in finished}, {"并行游戏", "串行游戏"})
        par_started = [e for e in started if e["name"] == "并行游戏"][0]
        self.assertTrue(par_started.get("parallel"))
        ser_started = [e for e in started if e["name"] == "串行游戏"][0]
        self.assertNotIn("parallel", ser_started)
        # 并行事件不占用串行进度位
        self.assertEqual(par_started.get("index"), 0)
        self.assertEqual(ser_started.get("index"), 1)
        self.assertEqual(events[0]["type"], "queue_started")
        self.assertEqual(events[0]["total"], 1)
        self.assertEqual(events[0]["parallel_total"], 1)
        self.assertEqual(events[-1]["type"], "queue_finished")
        self.assertEqual(events[-1]["result"], "completed")

    def test_parallel_logs_carry_name_prefix(self):
        logs = []
        runner = _make_runner(logs)
        with patch.object(rc.subprocess, "Popen"):
            runner.run_all([
                self._plugin("并行游戏", parallel=True),
                self._plugin("串行游戏"),
            ])
        texts = [m for m, _ in logs]
        self.assertTrue(any("⇉ [并行] 并行游戏" in m for m in texts))
        # 该任务的所有日志行都带名字前缀，交错时可分辨归属
        self.assertTrue(any(m.startswith("[并行游戏]") and "[启动]" in m for m in texts))
        self.assertTrue(any(m.startswith("[并行游戏]") and "[完成]" in m for m in texts))
        # 串行任务日志不带前缀
        self.assertTrue(any("[完成] 串行游戏" in m for m in texts))

    def test_summary_includes_both(self):
        logs = []
        runner = _make_runner(logs)
        with patch.object(rc.subprocess, "Popen"):
            runner.run_all([
                self._plugin("并行游戏", parallel=True),
                self._plugin("串行游戏"),
            ])
        texts = [m for m, _ in logs]
        self.assertTrue(any("每日奖励完成情况汇总" in m for m in texts))
        self.assertTrue(any("⚠ 未能确认 · 并行游戏" in m for m in texts))
        self.assertTrue(any("⚠ 未能确认 · 串行游戏" in m for m in texts))

    def test_parallel_invalid_launcher_skips(self):
        logs, events = [], []
        runner = _make_runner(logs, events=events)
        runner.run_all([
            self._plugin("坏并行", parallel=True, launcher=r"C:\no\such\file.exe"),
        ])
        texts = [m for m, _ in logs]
        self.assertTrue(any(m.startswith("[坏并行]") and "[跳过]" in m for m in texts))
        skipped = [e for e in events if e["type"] == "task_finished"
                   and e.get("result") == "skipped"]
        self.assertTrue(skipped and skipped[0].get("name") == "坏并行")
        self.assertEqual(events[-1]["result"], "completed")

    def test_parallel_only_queue(self):
        logs, events = [], []
        runner = _make_runner(logs, events=events)
        with patch.object(rc.subprocess, "Popen"):
            runner.run_all([self._plugin("只有并行", parallel=True)])
        texts = [m for m, _ in logs]
        self.assertTrue(any("共 1 个游戏，其中 1 个并行" in m for m in texts))
        self.assertTrue(any("每日奖励完成情况汇总" in m for m in texts))
        self.assertEqual(events[-1]["result"], "completed")

    def test_stop_before_start_launches_nothing(self):
        stop = threading.Event()
        stop.set()
        logs, events = [], []
        runner = _make_runner(logs, stop_event=stop, events=events)
        with patch.object(rc.subprocess, "Popen") as mock_popen:
            runner.run_all([
                self._plugin("并行游戏", parallel=True),
                self._plugin("串行游戏"),
            ])
        mock_popen.assert_not_called()
        self.assertEqual(events[-1]["type"], "queue_finished")
        self.assertEqual(events[-1]["result"], "stopped")
        texts = [m for m, _ in logs]
        self.assertTrue(any("已被用户中止" in m for m in texts))

    def test_no_parallel_keeps_old_behavior(self):
        """全串行（无 parallel 字段）时事件与日志与旧版一致。"""
        logs, events = [], []
        runner = _make_runner(logs, events=events)
        with patch.object(rc.subprocess, "Popen"):
            runner.run_all([self._plugin("游戏A"), self._plugin("游戏B")])
        self.assertEqual(events[0]["type"], "queue_started")
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[0]["parallel_total"], 0)
        texts = [m for m, _ in logs]
        self.assertTrue(any("开始串行执行，共 2 个游戏。" in m for m in texts))
        self.assertFalse(any("[并行]" in m for m in texts))


class TestDailyStateThreadSafety(unittest.TestCase):
    def test_concurrent_mark_done_keeps_file_valid(self):
        path = os.path.join(BASE, "tests", "_tmp_daily_state.json")
        if os.path.exists(path):
            os.remove(path)
        try:
            state = rc.DailyDoneState(path)

            def worker(i):
                for k in range(30):
                    state.mark_done("游戏%d" % (k % 3))

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("games", data)
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
