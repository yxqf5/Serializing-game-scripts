# -*- coding: utf-8 -*-
import os
import sys
import unittest
from unittest.mock import patch

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import preflight


class TestPreflight(unittest.TestCase):
    def test_no_enabled_plugins_is_error(self):
        issues = preflight.check_plugins([{"enabled": False, "name": "x"}])
        self.assertTrue(preflight.has_blocking_errors(issues))

    def test_missing_launcher_warns(self):
        issues = preflight.check_plugins([
            {"enabled": True, "name": "原神", "launcher": "", "game_processes": [], "helper_processes": []}
        ])
        levels = [i["level"] for i in issues]
        self.assertIn("warn", levels)

    def test_valid_launcher_no_path_error(self):
        issues = preflight.check_plugins([
            {
                "enabled": True,
                "name": "测试",
                "launcher": __file__,
                "game_processes": [],
                "helper_processes": [],
            }
        ])
        path_issues = [i for i in issues if "找不到启动器" in i.get("message", "")]
        self.assertEqual(len(path_issues), 0)

    @patch("preflight.runner_core.snapshot_running_processes", return_value={"starrail.exe"})
    def test_running_process_warns(self, _mock):
        issues = preflight.check_plugins([
            {
                "enabled": True,
                "name": "崩铁",
                "launcher": __file__,
                "game_processes": ["StarRail.exe"],
                "helper_processes": [],
            }
        ])
        self.assertTrue(any("已在运行" in i["message"] for i in issues))

    def test_single_parallel_plugin_no_warning(self):
        issues = preflight.check_plugins([
            {"enabled": True, "name": "明日方舟", "launcher": __file__,
             "game_processes": [], "helper_processes": [], "parallel": True},
        ])
        self.assertFalse(any("并行" in i["message"] for i in issues))

    def test_multiple_parallel_plugins_warn(self):
        issues = preflight.check_plugins([
            {"enabled": True, "name": "游戏A", "launcher": __file__,
             "game_processes": [], "helper_processes": [], "parallel": True},
            {"enabled": True, "name": "游戏B", "launcher": __file__,
             "game_processes": [], "helper_processes": [], "parallel": True},
        ])
        warns = [i for i in issues if i["level"] == "warn" and "并行" in i["message"]]
        self.assertEqual(len(warns), 1)
        self.assertIn("游戏A", warns[0]["message"])
        self.assertIn("游戏B", warns[0]["message"])


if __name__ == "__main__":
    unittest.main()
