# -*- coding: utf-8 -*-
"""ui_qt 离屏冒烟测试:不依赖显示器,验证主窗口构建/页面切换/日志上限/定时任务。"""
import datetime
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402


class TestUiQt(unittest.TestCase):
    app = None
    win = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from ui_qt.app import MainWindow
        cls.win = MainWindow()
        # 测试只改内存里的 settings,关窗前还原,避免写回真实 settings.json
        cls._orig_settings = dict(cls.win.settings)

    @classmethod
    def tearDownClass(cls):
        cls.win.settings.clear()
        cls.win.settings.update(cls._orig_settings)
        cls.win.close()

    # ---- 原有冒烟 ----
    def test_main_window_boots(self):
        self.assertIsNotNone(self.win.home_page)
        self.assertIsNotNone(self.win.controller)

    def test_switch_pages(self):
        for name in ("home", "add", "edit", "first_run", "help", "settings"):
            self.win.go(name)
        self.win.go("home")

    def test_log_append_and_cap(self):
        panel = self.win.home_page.log_panel
        lines = [("[信息] 行 %d" % i, None) for i in range(700)]
        panel.append_lines(lines)
        doc = panel.text_edit.document()
        self.assertLessEqual(doc.blockCount(), 600)

    def test_controller_idle(self):
        self.assertFalse(self.win.controller.running)
        self.assertEqual(self.win.controller.run_state.get("state"), "idle")

    # ---- 定时任务:主窗口调度状态 ----
    def test_schedule_resync_disabled(self):
        self.win.settings["schedule_enabled"] = False
        self.win.schedule_resync()
        self.assertIsNone(self.win._sched_next)

    def test_schedule_resync_enabled(self):
        self.win.settings["schedule_enabled"] = True
        self.win.settings["schedule_time"] = "23:59"
        self.win.schedule_resync()
        self.assertIsNotNone(self.win._sched_next)
        self.assertEqual(self.win._sched_next.strftime("%H:%M"), "23:59")
        self.win.settings["schedule_enabled"] = False
        self.win.schedule_resync()
        self.assertIsNone(self.win._sched_next)

    def test_sched_tick_advances_after_firing(self):
        # _sched_next 已过 → 触发一次并把下次推到未来(确认框期间不重复触发)
        self.win.settings["schedule_enabled"] = True
        self.win.settings["schedule_time"] = "00:00"
        self.win._sched_next = datetime.datetime.now() - datetime.timedelta(seconds=5)
        fired = []
        self.win._fire_scheduled = lambda cfg: fired.append(cfg)
        try:
            self.win._sched_tick()
        finally:
            del self.win._fire_scheduled
        self.assertEqual(len(fired), 1)
        self.assertIsNotNone(self.win._sched_next)
        self.assertGreater(self.win._sched_next, datetime.datetime.now())
        self.win.settings["schedule_enabled"] = False
        self.win.schedule_resync()

    # ---- 定时任务:到点流程(跳过/确认/忙碌) ----
    def _capture_logs(self):
        logs = []
        self.win.append_log = lambda text, level=None: logs.append((text, level))
        return logs

    def test_fire_scheduled_skips_when_running(self):
        logs = self._capture_logs()
        state = self.win.controller.run_state["state"]
        self.win.controller.run_state["state"] = "running"
        try:
            self.win._fire_scheduled({"time_text": "04:00", "countdown_sec": 30})
        finally:
            self.win.controller.run_state["state"] = state
            del self.win.append_log
        self.assertTrue(any("[定时]" in t and "跳过" in t for t, _ in logs))

    def _with_fake_plugins(self):
        """注入一个启用的假插件,避免依赖本机 plugins 的实际勾选状态。"""
        orig = self.win.plugins
        self.win.plugins = [{"name": "测试游戏", "enabled": True}]

        def restore():
            self.win.plugins = orig
        return restore

    def test_fire_scheduled_confirm_calls_start_run(self):
        import ui_qt.app as app_mod
        restore = self._with_fake_plugins()
        started = {}

        class StubDialog:
            def __init__(self, parent, time_text, countdown, names):
                self.names = names

            def exec(self):
                return int(QDialog.DialogCode.Accepted)

        orig_dialog = app_mod.ScheduleCountdownDialog
        self.win.start_run = lambda scheduled=False: started.update(scheduled=scheduled)
        app_mod.ScheduleCountdownDialog = StubDialog
        try:
            self.win._fire_scheduled({"time_text": "04:00", "countdown_sec": 30})
        finally:
            app_mod.ScheduleCountdownDialog = orig_dialog
            del self.win.start_run
            restore()
        self.assertTrue(started.get("scheduled"))

    def test_fire_scheduled_reject_skips(self):
        import ui_qt.app as app_mod
        restore = self._with_fake_plugins()
        started = {}

        class StubDialog:
            def __init__(self, parent, time_text, countdown, names):
                pass

            def exec(self):
                return int(QDialog.DialogCode.Rejected)

        orig_dialog = app_mod.ScheduleCountdownDialog
        self.win.start_run = lambda scheduled=False: started.update(scheduled=scheduled)
        app_mod.ScheduleCountdownDialog = StubDialog
        try:
            self.win._fire_scheduled({"time_text": "04:00", "countdown_sec": 30})
        finally:
            app_mod.ScheduleCountdownDialog = orig_dialog
            del self.win.start_run
            restore()
        self.assertFalse(started)

    # ---- 定时任务:倒计时确认框 ----
    def test_schedule_dialog_accepts_on_timeout(self):
        from ui_qt.dialogs import ScheduleCountdownDialog
        dlg = ScheduleCountdownDialog(self.win, "04:00", 2, ["游戏A", "游戏B"])
        dlg._tick()   # 还剩 1 秒,只刷新文本
        self.assertNotEqual(dlg.result(), int(QDialog.DialogCode.Accepted))
        dlg._tick()   # 归零 → 自动接受
        self.assertEqual(dlg.result(), int(QDialog.DialogCode.Accepted))
        dlg.deleteLater()

    def test_schedule_dialog_reject_skips(self):
        from ui_qt.dialogs import ScheduleCountdownDialog
        dlg = ScheduleCountdownDialog(self.win, "04:00", 30, ["游戏A"])
        dlg.reject()
        self.assertEqual(dlg.result(), int(QDialog.DialogCode.Rejected))
        dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
