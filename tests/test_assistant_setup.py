# -*- coding: utf-8 -*-
"""assistant_setup：一键配置 / 备份还原 / dry-run 校验。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import assistant_setup as asetup


def _write(path, text, encoding="utf-8"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)


def _read(path, encoding="utf-8"):
    with open(path, "r", encoding=encoding) as f:
        return f.read()


class AssistantSetupTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # 把备份目录重定向到临时目录，避免污染真实数据
        self._orig_data_dir = asetup.data_dir
        asetup.data_dir = lambda: self.tmp

    def tearDown(self):
        asetup.data_dir = self._orig_data_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plugin(self, exe_rel, preset_id):
        exe = os.path.join(self.tmp, exe_rel)
        _write(exe, "") if not os.path.exists(exe) else None
        return {"preset_id": preset_id, "name": "T", "launcher": exe}


class TestM7a(AssistantSetupTestBase):
    YAML = ("pause_after_success: true # 是否在成功后暂停程序。\n"
            "after_finish: Loop\n"
            "other_key: keep\n")

    def _fixture(self):
        cfg = os.path.join(self.tmp, "M7A", "config.yaml")
        _write(cfg, self.YAML)
        return self._plugin(os.path.join("M7A", "March7th Launcher.exe"), "m7a_main"), cfg

    def test_apply_patches_and_keeps_comment(self):
        plugin, cfg = self._fixture()
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["error"], "")
        self.assertEqual(sorted(r["applied"]), ["after_finish", "pause_after_success"])
        text = _read(cfg)
        self.assertIn("pause_after_success: false # 是否在成功后暂停程序。", text)
        self.assertIn("after_finish: Exit", text)
        self.assertIn("other_key: keep", text)

    def test_verify_dry_run_does_not_write(self):
        plugin, cfg = self._fixture()
        checks = asetup.verify_for_plugin(plugin)
        self.assertFalse(all(c["ok"] for c in checks))  # 待配置
        self.assertEqual(_read(cfg), self.YAML)         # 未被写入

    def test_apply_then_verify_all_ok(self):
        plugin, _ = self._fixture()
        asetup.apply_for_plugin(plugin)
        checks = asetup.verify_for_plugin(plugin)
        self.assertTrue(all(c["ok"] for c in checks))

    def test_backup_created_and_restore(self):
        plugin, cfg = self._fixture()
        asetup.apply_for_plugin(plugin)
        backups = asetup.list_backups("m7a_main")
        self.assertEqual(len(backups), 1)
        self.assertEqual(_read(os.path.join(backups[0][0], "config.yaml")), self.YAML)
        # 再改动，然后还原
        _write(cfg, self.YAML + "drift: 1\n")
        restored = asetup.restore_backup(backups[0][0])
        self.assertEqual(restored, [os.path.abspath(cfg)])
        self.assertEqual(_read(cfg), self.YAML)

    def test_missing_config_returns_manual(self):
        plugin = self._plugin(os.path.join("Nope", "March7th Launcher.exe"), "m7a_main")
        r = asetup.apply_for_plugin(plugin)
        self.assertFalse(r["ok"])
        self.assertTrue(r["manual"])
        checks = asetup.verify_for_plugin(plugin)
        self.assertTrue(checks and not all(c["ok"] for c in checks))


class TestBetterGi(AssistantSetupTestBase):
    def _fixture(self, action="保持游戏运行"):
        cfg = os.path.join(self.tmp, "BetterGI", "User", "OneDragon", "默认配置.json")
        _write(cfg, json.dumps({"CompletionAction": action, "TaskEnabledList": {"a": True}},
                               ensure_ascii=False))
        return self._plugin(os.path.join("BetterGI", "BetterGI.exe"),
                            "bettergi_onedragon"), cfg

    def test_apply_sets_completion_action(self):
        plugin, cfg = self._fixture("保持游戏运行")
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["applied"], ["CompletionAction"])
        data = json.loads(_read(cfg))
        self.assertEqual(data["CompletionAction"], "关闭游戏和软件")
        self.assertTrue(all(c["ok"] for c in r["checks"]))

    def test_already_configured_no_change(self):
        plugin, cfg = self._fixture("关闭游戏和软件")
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["applied"], [])
        self.assertTrue(all(c["ok"] for c in r["checks"]))

    def test_broken_json_no_write(self):
        plugin, cfg = self._fixture()
        _write(cfg, "{not json")
        r = asetup.apply_for_plugin(plugin)
        self.assertFalse(r["ok"])
        self.assertEqual(_read(cfg), "{not json")


class TestMaa(AssistantSetupTestBase):
    def _fixture(self):
        cfg = os.path.join(self.tmp, "MAA", "config", "gui.json")
        _write(cfg, json.dumps({
            "Current": "Default",
            "Configurations": {"Default": {"GUI.UseCardLog": "True"}},
        }))
        return self._plugin(os.path.join("MAA", "MAA.exe"), "maa_gui"), cfg

    def test_apply_writes_three_keys(self):
        plugin, cfg = self._fixture()
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(sorted(r["applied"]), [
            "MainFunction.PostActions", "Start.OpenEmulatorAfterLaunch", "Start.RunDirectly"])
        data = json.loads(_read(cfg))
        conf = data["Configurations"]["Default"]
        self.assertEqual(conf["Start.RunDirectly"], "True")
        self.assertEqual(conf["Start.OpenEmulatorAfterLaunch"], "True")
        self.assertEqual(conf["MainFunction.PostActions"], "12")
        self.assertEqual(conf["GUI.UseCardLog"], "True")  # 原有键不动

    def test_adb_missing_reported_manual(self):
        plugin, _ = self._fixture()
        asetup.apply_for_plugin(plugin)
        checks = asetup.verify_for_plugin(plugin)
        adb = [c for c in checks if "ADB" in c["name"]]
        self.assertTrue(adb and not adb[0]["ok"])


class TestMaaNewFormat(AssistantSetupTestBase):
    """MAA v6+ 的 gui.new.json 嵌套新格式。"""

    def _fixture(self, run_directly=False, start_emu=False, actions="", adb=None):
        base = os.path.join(self.tmp, "MAA")
        adb_path = ""
        if adb is None:
            adb_path = os.path.join(base, "adb.exe")
            _write(adb_path, "")
            adb = adb_path
        cfg = os.path.join(base, "config", "gui.new.json")
        _write(cfg, json.dumps({
            "Current": "Default",
            "ConfigVersion": 1,
            "Configurations": {"Default": {"Gui": {
                "StartUpSettings": {"RunDirectly": run_directly, "StartEmulator": start_emu},
                "PostActions": actions,
                "ConnectSettings": {"AdbPath": adb},
            }}},
        }, ensure_ascii=False))
        return self._plugin(os.path.join("MAA", "MAA.exe"), "maa_gui"), cfg

    def test_apply_writes_new_format(self):
        plugin, cfg = self._fixture()
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["applied"], ["RunDirectly", "StartEmulator", "PostActions"])
        gui = json.loads(_read(cfg))["Configurations"]["Default"]["Gui"]
        self.assertIs(gui["StartUpSettings"]["RunDirectly"], True)
        self.assertIs(gui["StartUpSettings"]["StartEmulator"], True)
        self.assertEqual(gui["PostActions"], "ExitEmulator, ExitSelf")

    def test_already_configured_no_change(self):
        plugin, _ = self._fixture(True, True, "ExitEmulator, ExitSelf")
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["applied"], [])
        self.assertTrue(all(c["ok"] for c in r["checks"]))

    def test_verify_dry_run_no_write(self):
        plugin, cfg = self._fixture()
        before = _read(cfg)
        checks = asetup.verify_for_plugin(plugin)
        self.assertFalse(all(c["ok"] for c in checks))
        self.assertEqual(_read(cfg), before)

    def test_new_file_takes_precedence_over_old(self):
        plugin, _ = self._fixture(True, True, "ExitEmulator, ExitSelf")
        old = os.path.join(self.tmp, "MAA", "config", "gui.json")
        old_text = json.dumps({"Current": "Default", "Configurations": {"Default": {}}})
        _write(old, old_text)
        self.assertTrue(all(c["ok"] for c in asetup.verify_for_plugin(plugin)))
        self.assertEqual(_read(old), old_text)

    def test_corrupt_new_file_falls_back_to_old(self):
        plugin, _ = self._fixture()
        old = os.path.join(self.tmp, "MAA", "config", "gui.json")
        _write(old, json.dumps({
            "Current": "Default",
            "Configurations": {"Default": {"Start.RunDirectly": "False"}},
        }))
        _write(os.path.join(self.tmp, "MAA", "config", "gui.new.json"), "{broken")
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(sorted(r["applied"]),
                         ["MainFunction.PostActions", "Start.OpenEmulatorAfterLaunch",
                          "Start.RunDirectly"])

    def test_adb_missing_warns(self):
        plugin, _ = self._fixture(adb="")
        r = asetup.apply_for_plugin(plugin)
        adb = [c for c in r["checks"] if "ADB" in c["name"]]
        self.assertTrue(adb and not adb[0]["ok"])


class TestMaaEnd(AssistantSetupTestBase):
    TASK = {"id": "abc1234", "taskName": "DailyRewards", "enabled": True,
            "enabledByController": {"Win32-Front": True}, "optionValues": {}}

    def _fixture(self, tasks, device="E:\\x\\Endfield.exe"):
        cfg = os.path.join(self.tmp, "MaaEnd", "config", "mxu-MaaEnd.json")
        _write(cfg, json.dumps({"version": "1.0", "instances": [
            {"id": "i1", "name": "全套日常", "tasks": tasks,
             "savedDevice": {"connectedProgramPath": device}},
        ]}, ensure_ascii=False))
        return self._plugin(os.path.join("MaaEnd", "MaaEnd.exe"), "maaend_gui"), cfg

    def test_appends_missing_kill_tasks(self):
        plugin, cfg = self._fixture([dict(self.TASK)])
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["applied"], ["结束进程 Endfield.exe", "退出 MaaEnd"])
        data = json.loads(_read(cfg))
        tasks = data["instances"][0]["tasks"]
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[-1]["optionValues"]["__MXU_KILLPROC_SELF_OPTION__"]["value"], True)
        self.assertEqual(tasks[-2]["optionValues"]["__MXU_KILLPROC_NAME_OPTION__"]["values"]["process_name"],
                         "Endfield.exe")

    def test_no_duplicate_when_present(self):
        plugin, cfg = self._fixture([
            dict(self.TASK),
            asetup._maaend_killproc_task(False),
            asetup._maaend_killproc_task(True),
        ])
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["applied"], [])
        data = json.loads(_read(cfg))
        self.assertEqual(len(data["instances"][0]["tasks"]), 3)

    def test_no_instance_returns_manual(self):
        plugin = self._plugin(os.path.join("MaaEnd", "MaaEnd.exe"), "maaend_gui")
        cfg = os.path.join(self.tmp, "MaaEnd", "config", "mxu-MaaEnd.json")
        _write(cfg, json.dumps({"version": "1.0", "instances": []}))
        r = asetup.apply_for_plugin(plugin)
        self.assertFalse(r["ok"])
        self.assertTrue(r["manual"])


class TestOneDragon(AssistantSetupTestBase):
    def _fixture(self, after_done="退出程序"):
        cfg = os.path.join(self.tmp, "zzz", "config", "one_dragon.yml")
        _write(cfg, "instance_list:\n- idx: 1\n  name: '01'\nafter_done: %s\n" % after_done)
        return self._plugin(os.path.join("zzz", "OneDragon-Launcher.exe"), "onedragon"), cfg

    def test_apply_sets_after_done(self):
        plugin, cfg = self._fixture("退出程序")
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["applied"], ["after_done"])
        self.assertIn("after_done: 关闭游戏", _read(cfg))

    def test_missing_key_appended(self):
        plugin, cfg = self._fixture()
        text = _read(cfg).replace("after_done: 退出程序\n", "")
        _write(cfg, text)
        r = asetup.apply_for_plugin(plugin)
        self.assertEqual(r["applied"], ["after_done"])
        self.assertTrue(_read(cfg).rstrip().endswith("after_done: 关闭游戏"))


class TestUnknownPreset(AssistantSetupTestBase):
    def test_falls_back_to_checklist(self):
        plugin = self._plugin(os.path.join("X", "x.exe"), "some_custom")
        plugin["setup_checklist"] = ["做某事"]
        r = asetup.apply_for_plugin(plugin)
        self.assertTrue(r["manual"])
        checks = asetup.verify_for_plugin(plugin)
        self.assertEqual([c["name"] for c in checks], ["做某事"])
        self.assertFalse(checks[0]["ok"])


class TestBackupRestore(AssistantSetupTestBase):
    def test_restore_recreates_missing_dirs(self):
        cfg = os.path.join(self.tmp, "M7A", "config.yaml")
        plugin = self._plugin(os.path.join("M7A", "March7th Launcher.exe"), "m7a_main")
        _write(cfg, "after_finish: Loop\n")
        asetup.apply_for_plugin(plugin)
        backups = asetup.list_backups("m7a_main")
        os.remove(cfg)
        restored = asetup.restore_backup(backups[0][0])
        self.assertEqual(restored, [os.path.abspath(cfg)])
        self.assertTrue(os.path.isfile(cfg))


if __name__ == "__main__":
    unittest.main()
