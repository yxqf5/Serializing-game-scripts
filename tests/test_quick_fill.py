# -*- coding: utf-8 -*-
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import quick_fill as qf


class TestQuickFill(unittest.TestCase):
    def test_parse_basic(self):
        text = """
名称: 测试游戏
启动器: E:\\test\\app.exe
参数: -o --close-game
等待模式: game
游戏进程: Game.exe
助手进程: Helper.exe
超时: 20
备注: 一行备注
"""
        fields, err = qf.parse_quick_fill(text)
        self.assertEqual(err, "")
        self.assertEqual(fields["name"], "测试游戏")
        self.assertEqual(fields["launcher"], "E:\\test\\app.exe")
        self.assertEqual(fields["args"], ["-o", "--close-game"])
        self.assertEqual(fields["wait_mode"], "game")
        self.assertEqual(fields["game_processes"], ["Game.exe"])
        self.assertEqual(fields["helper_processes"], ["Helper.exe"])
        self.assertEqual(fields["start_timeout_min"], 20)
        self.assertEqual(fields["notes"], "一行备注")

    def test_parse_game_script_aliases(self):
        fields, err = qf.parse_quick_fill("游戏: 原神\n脚本: BetterGI · 一条龙\n")
        self.assertEqual(err, "")
        self.assertEqual(fields["game"], "原神")
        self.assertEqual(fields["script"], "BetterGI · 一条龙")

    def test_parse_checklist_bullets(self):
        text = """
待办完成:
- 第一项
- 第二项
"""
        fields, err = qf.parse_quick_fill(text)
        self.assertEqual(fields["checklist_done"], ["第一项", "第二项"])

    def test_parse_empty_fails(self):
        _, err = qf.parse_quick_fill("# only comment\n")
        self.assertNotEqual(err, "")

    def test_export_roundtrip_keys(self):
        plugin = {
            "name": "A", "launcher": "C:\\a.exe", "args": ["x"],
            "wait_mode": "helper", "game_processes": [], "helper_processes": ["H.exe"],
            "start_timeout_min": 10, "notes": "n", "checklist_done": ["done1"],
        }
        text = qf.export_plugin_to_text(plugin)
        fields, err = qf.parse_quick_fill(text)
        self.assertEqual(err, "")
        self.assertEqual(fields["name"], "A")
        self.assertEqual(fields["args"], ["x"])
        self.assertEqual(fields["wait_mode"], "helper")


if __name__ == "__main__":
    unittest.main()
