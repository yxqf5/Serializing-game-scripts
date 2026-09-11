# -*- coding: utf-8 -*-
import os
import sys
import threading
import unittest
from unittest.mock import patch

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import runner_core as rc


class TestRunnerSkip(unittest.TestCase):
    def test_plugin_skip_reason_empty(self):
        self.assertEqual(rc.plugin_skip_reason({"launcher": ""}), "未配置启动器路径")

    def test_plugin_skip_reason_missing_file(self):
        reason = rc.plugin_skip_reason({"launcher": r"C:\no\such\file.exe"})
        self.assertIn("启动器不存在", reason)

    def test_plugin_skip_reason_ok(self):
        self.assertIsNone(rc.plugin_skip_reason({"launcher": __file__}))

    def test_run_all_skips_invalid(self):
        logs = []
        runner = rc.Runner(logs.append)
        runner.run_all([
            {"name": "坏配置", "launcher": "", "enabled": True},
        ])
        skip_lines = [l for l in logs if "[跳过]" in l]
        self.assertEqual(len(skip_lines), 1)
        self.assertIn("坏配置", skip_lines[0])
        self.assertIn("未配置启动器路径", skip_lines[0])

    def test_runner_emits_structured_events_and_keeps_old_log_api(self):
        logs = []
        events = []
        runner = rc.Runner(logs.append, event_func=events.append)
        runner.run_all([
            {"name": "坏配置", "launcher": "", "enabled": True},
        ])

        self.assertTrue(any("[跳过]" in line for line in logs))
        self.assertEqual(events[0]["type"], "queue_started")
        self.assertEqual(events[1]["type"], "task_started")
        self.assertEqual(events[1]["name"], "坏配置")
        self.assertTrue(any(
            event.get("type") == "task_finished" and event.get("result") == "skipped"
            for event in events
        ))
        self.assertEqual(events[-1]["type"], "queue_finished")

    def test_event_callback_failure_never_breaks_runner(self):
        logs = []

        def broken_event_callback(_event):
            raise RuntimeError("UI callback failed")

        runner = rc.Runner(logs.append, event_func=broken_event_callback)
        runner.run_all([{"name": "坏配置", "launcher": ""}])
        self.assertTrue(any("[跳过]" in line for line in logs))

    def test_stop_still_runs_existing_helper_cleanup(self):
        stop = threading.Event()
        killed = []

        class StopWhileWaitingRunner(rc.Runner):
            def _wait_until_all_gone(self, procs, on_tick=None):
                stop.set()

        plugin = {
            "name": "测试停止收尾",
            "launcher": __file__,
            "args": [],
            "wait_mode": "game",
            "game_processes": ["Game.exe"],
            "helper_processes": ["Helper.exe"],
            "start_timeout_min": 1,
        }
        runner = StopWhileWaitingRunner(lambda _line: None, stop)
        runner._wait_until_any_appear = lambda _procs, _timeout, on_tick=None: True
        with patch.object(rc.subprocess, "Popen"), patch.object(
                rc, "_kill", side_effect=lambda name, _log, label="助手": killed.append((name, label))):
            result = runner._run_one(1, 1, plugin)

        self.assertEqual(result, "stopped")
        self.assertIn(("Helper.exe", "助手"), killed)

    def test_run_all_logs_checklist_warnings(self):
        logs = []
        runner = rc.Runner(logs.append)
        fake_exe = os.path.join(BASE, "tests", "_fake_launcher.exe")
        with open(fake_exe, "wb") as f:
            f.write(b"")
        try:
            runner.run_all([{
                "name": "测试游戏",
                "launcher": fake_exe,
                "args": [],
                "wait_mode": "helper",
                "helper_processes": [],
                "setup_checklist": ["请在脚本内开启完成后关游戏"],
                "checklist_done": [],
                "doc_url": "https://example.com/doc",
            }])
        finally:
            try:
                os.remove(fake_exe)
            except Exception:
                pass
        warn_lines = [l for l in logs if "[警告]" in l]
        self.assertGreaterEqual(len(warn_lines), 3)
        self.assertTrue(any("请在脚本内开启完成后关游戏" in l for l in warn_lines))
        self.assertTrue(any("编辑" in l for l in warn_lines))
        self.assertTrue(any("example.com" in l for l in warn_lines))

    def test_pre_launch_missing_file_warns_but_continues(self):
        logs = []
        runner = rc.Runner(logs.append)
        runner._run_pre_launch({"pre_launcher": r"C:\no\such\game.exe"},
                               r"C:\no\such\game.exe")
        self.assertTrue(any("[警告]" in l and "前置程序不存在" in l for l in logs))

    def test_pre_launch_skips_when_already_running(self):
        logs = []
        runner = rc.Runner(logs.append)
        orig = rc._tasklist_running
        rc._tasklist_running = lambda name: True
        try:
            runner._run_pre_launch(
                {"pre_launcher": __file__, "pre_delay_sec": 0}, __file__)
        finally:
            rc._tasklist_running = orig
        self.assertTrue(any("已在运行，跳过启动" in l for l in logs))

    def test_pre_launch_delay_respects_stop_event(self):
        import threading
        import time as _time
        stop = threading.Event()
        stop.set()
        runner = rc.Runner(lambda m: None, stop)
        t0 = _time.time()
        runner._sleep_interruptible(10)
        self.assertLess(_time.time() - t0, 2)

    def test_build_pre_cmd_default_uses_explorer_proxy(self):
        cmd, used = rc.build_pre_cmd(r"D:\Game\Endfield.exe", [])
        self.assertEqual(used, "explorer")
        self.assertTrue(cmd[0].lower().endswith("explorer.exe"))
        self.assertEqual(cmd[1], r"D:\Game\Endfield.exe")

    def test_build_pre_cmd_direct_when_args_present(self):
        cmd, used = rc.build_pre_cmd(r"D:\Game\Endfield.exe", ["-abc"])
        self.assertEqual(used, "direct")
        self.assertEqual(cmd, [r"D:\Game\Endfield.exe", "-abc"])

    def test_build_pre_cmd_direct_when_method_direct(self):
        cmd, used = rc.build_pre_cmd(r"D:\Game\Endfield.exe", [], method="direct")
        self.assertEqual(used, "direct")
        self.assertEqual(cmd, [r"D:\Game\Endfield.exe"])


class FakeWatcher:
    """日志监控替身：记录 poll 次数并返回固定提取结果。"""

    max_per_category = 20

    def __init__(self, result=None):
        self.result = result or {
            "daily_done": ["完成一"],
            "daily_pending": [],
            "stamina": [],
            "truncated": {},
        }
        self.polls = 0

    def poll(self):
        self.polls += 1

    def finish(self):
        return self.result


class TestRunnerLogReporting(unittest.TestCase):
    def test_report_result_only_prints_configured_sections(self):
        """未配置的分类不再输出「未捕捉到相关记录」噪音。"""
        logs = []
        runner = rc.Runner(lambda msg, level=None: logs.append((msg, level)), settle_sec=0)
        runner._report_task_result(
            {"name": "测试游戏", "daily_done_patterns": ["完成"]}, FakeWatcher())
        texts = [m for m, _ in logs]
        self.assertTrue(any("[每日完成]" in m for m in texts))
        self.assertFalse(any("[每日未完成]" in m for m in texts))
        self.assertFalse(any("[体力]" in m for m in texts))
        self.assertTrue(any("[每日完成]" in m and lvl == "gold" for m, lvl in logs))

    def test_report_result_no_patterns_prints_nothing(self):
        logs = []
        runner = rc.Runner(lambda msg, level=None: logs.append((msg, level)), settle_sec=0)
        runner._report_task_result({"name": "测试游戏"}, FakeWatcher())
        self.assertEqual(logs, [])

    def test_report_result_final_poll_after_settle(self):
        """报告前必须强制 poll 一次，避免最后一截日志漏读。"""
        w = FakeWatcher()
        runner = rc.Runner(lambda msg, level=None: None, settle_sec=0)
        runner._report_task_result({"name": "测试游戏", "daily_done_patterns": ["完成"]}, w)
        self.assertGreaterEqual(w.polls, 1)

    def test_runner_logs_carry_structured_levels(self):
        """level 关键字传给支持它的 log 回调（旧回调仍可用）。"""
        logs = []
        runner = rc.Runner(lambda msg, level=None: logs.append((msg, level)), settle_sec=0)
        runner.run_all([{"name": "坏配置", "launcher": ""}])
        self.assertTrue(any(lvl == "error" and "[跳过]" in m for m, lvl in logs))
        self.assertTrue(any(lvl == "ok" and "全部任务执行完成" in m for m, lvl in logs))

    def test_log_func_without_level_still_works(self):
        """只接受 msg 的旧回调不受影响。"""
        logs = []
        runner = rc.Runner(logs.append, settle_sec=0)
        runner.run_all([{"name": "坏配置", "launcher": ""}])
        self.assertTrue(any("[跳过]" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
