# -*- coding: utf-8 -*-
"""主窗口与应用入口。

移植自 tkinter 版:_build_shell(432)/_build_global_run_bar(499)/go(573)/
toggle(1825)/toggle_parallel(1844)/move_plugin(1866)/move(1876)/
delete_plugin(1891)/add_plugin(1905)/_refresh_run_buttons(2696)/
_refresh_card_controls(2717)/_update_global_run_bar(2728)/start_run(2755)/
_finish_preflight(2780)/stop_run(2828)/窗口持久化(_on_window_configure 等)。
"""
import datetime
import os
import sys

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

import preflight
import runner_core
import display_ctrl
import schedule_core
from app_paths import resource_path
from ui_helpers import LogStore, clamp_window_bounds

import ui_qt.core_glue as glue
from ui_qt import theme
from ui_qt.add_page import AddPage
from ui_qt.dialogs import ScheduleCountdownDialog
from ui_qt.edit_page import EditPage
from ui_qt.help_page import HelpPage
from ui_qt.home_page import HomePage
from ui_qt.run_controller import RunController
from ui_qt.settings_page import SettingsPage
from ui_qt.wizard_page import WizardPage

MIN_W, MIN_H = 940, 660
APP_USER_MODEL_ID = "Games.Py.SerialRunner.GameAssistant.1"
APP_ICON_PNG = resource_path("assets", "icons", "app.png")


def _set_app_user_model_id():
    """Windows 任务栏独立分组（须在创建窗口前，否则仍显示 python 图标）。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = glue.load_settings()
        self.plugins = []
        self.controller = RunController(self.settings)
        # 界面日志存储(完整内容可导出/复制),HomePage→LogPanel 共用
        self.log_store = LogStore(max_lines=10000)
        self.current_view = None
        self._temp_pages = {}          # add/edit 临时页,返回 home 后销毁
        self._restoring_window = True  # 恢复几何期间不触发保存
        self._cards_disabled = None    # 卡片控制态(运行中禁用)
        self._sched_next = None        # 定时任务下次触发时刻(None=未启用)
        self._scheduled_preflight = False  # 本轮前检查来自定时触发(警告不弹窗)

        self.setWindowTitle("一键长草 · 游戏串行助手")
        self.setMinimumSize(MIN_W, MIN_H)
        try:
            self.setWindowIcon(QIcon(APP_ICON_PNG))
        except Exception:
            pass
        self._restore_window_geometry()

        # 防抖定时器:窗口几何 500ms / 设置 350ms
        self._window_save_timer = QTimer(self)
        self._window_save_timer.setSingleShot(True)
        self._window_save_timer.setInterval(500)
        self._window_save_timer.timeout.connect(self._save_window_state)
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(350)
        self._settings_save_timer.timeout.connect(self._flush_settings)

        # 运行用时:每秒刷新
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start()

        self._build_shell()
        self._apply_qss()
        self._wire_controller()
        self._apply_window_state()

        # 定时任务:每秒轮询到点时刻,弹倒计时确认框(schedule_core 逻辑)
        self.schedule_resync()
        self._sched_timer = QTimer(self)
        self._sched_timer.setInterval(1000)
        self._sched_timer.timeout.connect(self._sched_tick)
        self._sched_timer.start()

        # 上次异常退出遗留的分辨率切换,启动时自动恢复(崩溃兜底)
        _done, _msg = display_ctrl.restore_if_needed()
        self._startup_display_msg = _msg if _done else None

        self.reload_plugins()
        if self._startup_display_msg:
            self.append_log(self._startup_display_msg)
            self._startup_display_msg = None
        if not self.settings.get("first_run_done"):
            self.go("first_run")
        else:
            self.go("home")
        self._apply_dark_titlebar()
        # 恢复几何期间忽略 move/resize 事件,300ms 后恢复正常保存
        QTimer.singleShot(300, self._end_restore)

    # ================= 外壳 =================
    def _build_shell(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)
        root.addWidget(body, 1)

        # 页面栈(add/edit 由 go() 动态创建入栈)
        self.stack = QStackedWidget()
        body_l.addWidget(self.stack, 1)
        body_l.addWidget(self._build_run_bar())

        self.home_page = HomePage(self)
        self.pages = {
            "home": self.home_page,
            "first_run": WizardPage(self),
            "help": HelpPage(self),
            "settings": SettingsPage(self),
        }
        for w in self.pages.values():
            self.stack.addWidget(w)

    def _build_sidebar(self):
        """侧栏:logo + 标题、顶部导航、底部(管理员状态/帮助/设置)。"""
        t = self._theme()
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(212)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(12, 24, 12, 14)
        sl.setSpacing(2)

        # —— 顶部 logo + 标题 ——
        logo_row = QWidget()
        ll = QHBoxLayout(logo_row)
        ll.setContentsMargins(8, 0, 0, 0)
        ll.setSpacing(10)
        pixmap = self._load_logo_pixmap(40)
        if pixmap is not None:
            logo_lbl = QLabel()
            logo_lbl.setPixmap(pixmap)
            logo_lbl.setFixedSize(pixmap.size())
            ll.addWidget(logo_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            accent_bar = QFrame()
            accent_bar.setFixedSize(6, 44)
            accent_bar.setStyleSheet("background:%s;border-radius:3px;" % t["accent"])
            ll.addWidget(accent_bar)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        title = QLabel("一键长草")
        title.setFont(theme.font(self.settings, 16, True))
        scale = theme.FONT_SCALES.get(self.settings.get("font_size", "中"), 1.0)
        sub = QLabel("SERIAL RUNNER")
        sub.setFont(QFont("Consolas", max(8, int(round(8 * scale)))))
        sub.setStyleSheet("color:%s;" % t["sub"])
        bl.addWidget(title)
        bl.addWidget(sub)
        ll.addWidget(box)
        ll.addStretch(1)
        sl.addWidget(logo_row)
        sl.addSpacing(14)

        # —— 顶部导航 ——
        self._nav_buttons = {}
        self._add_nav(sl, "home", "主页", "▶")
        self._add_nav(sl, "first_run", "部署向导", "★")
        sl.addStretch(1)

        # —— 底部:管理员状态 / 使用帮助 / 设置 ——
        self._admin_lbl = QLabel()
        sl.addWidget(self._admin_lbl)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background:%s;margin-left:8px;margin-right:8px;" % t["line"])
        sl.addWidget(line)
        sl.addSpacing(4)
        self._add_nav(sl, "help", "使用帮助", "?")
        self._add_nav(sl, "settings", "设置", "⚙")
        self._refresh_admin_label()
        return sidebar

    def _add_nav(self, layout, key, label, icon):
        btn = QPushButton("  %s   %s" % (icon, label))
        btn.setProperty("class", "nav")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(theme.font(self.settings, 12))
        btn.setFlat(True)
        btn.clicked.connect(lambda _=False, k=key: self.go(k))
        self._nav_buttons[key] = btn
        layout.addWidget(btn)

    def _highlight_nav(self):
        """当前导航项高亮(动态属性 navActive + 重刷样式)。"""
        for key, btn in self._nav_buttons.items():
            active = (key == self.current_view)
            if btn.property("navActive") != active:
                btn.setProperty("navActive", active)
                style = btn.style()
                style.unpolish(btn)
                style.polish(btn)

    def _refresh_admin_label(self):
        admin = bool(runner_core.is_admin())
        t = self._theme()
        self._admin_lbl.setText("● 管理员模式" if admin else "● 非管理员")
        self._admin_lbl.setFont(theme.font(self.settings, 9))
        self._admin_lbl.setStyleSheet(
            "color:%s;padding-left:20px;padding-top:8px;padding-bottom:4px;"
            % (t["ok"] if admin else t["warn"]))

    # ================= 底部全局运行条 =================
    def _build_run_bar(self):
        t = self._theme()
        bar = QFrame()
        bar.setObjectName("runbar")
        bar.setFixedHeight(72)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 7, 16, 7)
        bl.setSpacing(8)

        self.global_state_dot = QLabel("●")
        self.global_state_dot.setFont(theme.font(self.settings, 11))
        bl.addWidget(self.global_state_dot)

        self.global_run_title = QLabel("串行任务未运行")
        self.global_run_title.setFont(theme.font(self.settings, 10, True))
        bl.addWidget(self.global_run_title)

        self.global_run_detail = QLabel(" · 准备好后可在任意页面开始")
        self.global_run_detail.setFont(theme.font(self.settings, 9))
        self.global_run_detail.setStyleSheet("color:%s;" % t["sub"])
        bl.addWidget(self.global_run_detail, 1)

        # 运行用时(每秒刷新)
        self.run_elapsed_lbl = QLabel("用时 00:00")
        self.run_elapsed_lbl.setFont(theme.font(self.settings, 9))
        self.run_elapsed_lbl.setStyleSheet("color:%s;" % t["sub"])
        bl.addWidget(self.run_elapsed_lbl)

        self.global_progress = QProgressBar()
        self.global_progress.setFixedWidth(120)
        self.global_progress.setRange(0, 1)
        self.global_progress.setValue(0)
        self.global_progress.setTextVisible(False)
        bl.addWidget(self.global_progress)

        self.global_start_btn = QPushButton("▶ 开始运行")
        self.global_start_btn.setProperty("class", "accent")
        self.global_start_btn.setFont(theme.font(self.settings, 12, True))
        self.global_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_start_btn.setFixedSize(148, 50)
        # lambda:避免 clicked(bool) 的 checked 落进 start_run 的 scheduled 形参
        self.global_start_btn.clicked.connect(lambda: self.start_run())
        bl.addWidget(self.global_start_btn)

        self.global_stop_btn = QPushButton("■ 结束运行")
        self.global_stop_btn.setProperty("class", "danger")
        self.global_stop_btn.setFont(theme.font(self.settings, 12, True))
        self.global_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.global_stop_btn.setFixedSize(148, 50)
        self.global_stop_btn.clicked.connect(self.stop_run)
        bl.addWidget(self.global_stop_btn)

        # 兼容旧引用习惯
        self.run_btn = self.global_start_btn
        self.stop_btn = self.global_stop_btn
        self.status_lbl = self.global_run_detail
        return bar

    def _update_global_run_bar(self):
        """状态圆点/标题/进度。圆点:灰=空闲/橙=运行/绿=完成/红=失败。"""
        t = self._theme()
        run_state = self.controller.run_state
        state = run_state.get("state", "idle")
        index = int(run_state.get("index", 0) or 0)
        total = int(run_state.get("total", 0) or 0)
        name = run_state.get("name", "")
        message = run_state.get("message", "") or "就绪"
        parallel_names = run_state.get("parallel_names") or []
        if parallel_names:
            message = "%s · ⇉ 并行：%s" % (message, "、".join(parallel_names))
        if state == "preflight":
            title, detail, color = "正在运行前检查", "检查路径、权限和进程占用…", t["accent"]
        elif state in ("running", "stopping"):
            title = ("%d/%d  %s" % (index, total, name)) if total else (name or "任务运行中")
            detail = message
            color = t["warn"]
        elif state == "finished":
            title, detail = "本轮任务已结束", message
            result = run_state.get("result")
            if result == "failed":
                color = t["err"]
            elif result == "stopped":
                color = t["sub"]
            else:
                color = t["ok"]
        else:
            title, detail, color = "任务未运行", "准备好后可在任意页面开始", t["sub"]
            if self._sched_next is not None:
                detail = "下次定时 %s · 准备好后可在任意页面开始" % self._sched_next.strftime("%m-%d %H:%M")
        self.global_run_title.setText(title)
        self.global_run_detail.setText(" · " + detail)
        self.global_state_dot.setStyleSheet("color:%s;" % color)
        self.global_progress.setRange(0, max(1, total))
        self.global_progress.setValue(min(total, index))

    def _update_elapsed(self):
        """运行用时显示:运行中每秒累计,结束后停在最后值,空闲复位。"""
        started = self.controller.run_started_at
        if self.controller.running and started:
            delta = max(0, int((datetime.datetime.now() - started).total_seconds()))
            self.run_elapsed_lbl.setText("用时 %02d:%02d:%02d" % (
                delta // 3600, (delta % 3600) // 60, delta % 60))
        elif self.controller.run_state.get("state") == "idle":
            self.run_elapsed_lbl.setText("用时 00:00")

    # ================= 控制器接线 =================
    def _wire_controller(self):
        self.controller.log_lines.connect(self._on_log_lines)
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.preflight_done.connect(self._on_preflight_done)
        self.controller.finished.connect(self._on_finished)

    def _on_log_lines(self, lines):
        # LogStore 由主窗口维护(供复制/导出全量日志),面板只负责展示
        self.log_store.append_many(lines)
        self.home_page.log_panel.append_lines(lines)

    def append_log(self, text, level=None):
        """页面主动写一条运行日志(先入 LogStore 再上屏,与运行日志同源)。"""
        lines = [(str(text), level)]
        self.log_store.append_many(lines)
        try:
            self.home_page.log_panel.append_lines(lines)
        except Exception:
            print(text)

    def _on_state_changed(self, snapshot):
        self._update_elapsed()
        self.refresh_run_buttons()

    def _on_finished(self):
        self.refresh_run_buttons()

    # ================= 运行控制 =================
    def start_run(self, scheduled=False):
        """开始一轮串行队列;定时触发(scheduled=True)时前检查警告自动通过。"""
        if self.controller.running or self.controller.preflight_busy:
            return
        active = [p for p in self.plugins if p.get("enabled", True)]
        if not active:
            QMessageBox.warning(self, "无法开始", "没有勾选任何游戏，请至少开启一个。")
            return
        # 未开自动切换且当前非 16:9:提醒(开源脚本普遍只适配 16:9)
        if display_ctrl.parse_target(self.settings.get("run_resolution", "off")) is None:
            cur = display_ctrl.current_resolution()
            if cur and abs(cur[0] / cur[1] - 16 / 9) > 0.02:
                tip = ("当前分辨率 %d×%d 不是 16:9，开源脚本可能无法运行；"
                       "可在「设置 → 运行时分辨率」开启自动切换（结束后自动恢复）。" % cur)
                if scheduled:
                    self.append_log("[定时] " + tip, level="warn")
                else:
                    answer = QMessageBox.question(
                        self, "分辨率提示", tip + "\n仍要继续吗？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No)
                    if answer != QMessageBox.StandardButton.Yes:
                        return
        self._scheduled_preflight = bool(scheduled)
        self.controller.start(active)

    def _on_preflight_done(self, token, active, issues):
        """前检查结果:error 阻断、warn 询问、通过则清日志并开跑(照旧 _finish_preflight)。"""
        if self.controller.running:
            return
        scheduled = self._scheduled_preflight
        self._scheduled_preflight = False
        if preflight.has_blocking_errors(issues):
            self.controller.cancel_preflight()   # 状态复原为「就绪」
            QMessageBox.critical(self, "无法开始",
                                 issues[0].get("message", "没有可运行的游戏。"))
            return
        warns = [i for i in issues if i.get("level") == "warn"]
        if warns and scheduled:
            # 定时触发:警告不弹窗阻塞挂机流程,写进日志自动通过
            for i in warns:
                prefix = ("「%s」" % i["plugin_name"]) if i.get("plugin_name") else ""
                self.append_log("[定时] 警告（已自动通过）：%s%s"
                                % (prefix, i.get("message", "")), level="warn")
        elif warns:
            lines = []
            for i in warns:
                prefix = ("「%s」" % i["plugin_name"]) if i.get("plugin_name") else ""
                lines.append("%s%s" % (prefix, i.get("message", "")))
            answer = QMessageBox.question(
                self, "运行前提示", "发现以下情况，仍要继续吗？\n\n" + "\n".join(lines),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.controller.cancel_preflight()   # run_state 复原("就绪")
                return
        # 旧版开跑前清空界面日志(_clear_log(confirm=False));LogStore 由主窗口持有
        self.log_store.clear()
        try:
            self.home_page.log_panel.render_store()
        except Exception:
            pass
        self.controller.begin_run(active)

    def stop_run(self):
        self.controller.stop()

    def refresh_run_buttons(self):
        busy = self.controller.running or self.controller.preflight_busy
        can_start_here = self.current_view not in ("add", "edit", "first_run")
        self.global_start_btn.setEnabled(not busy and can_start_here)
        can_stop = self.controller.running and \
            self.controller.run_state.get("state") != "stopping"
        self.global_stop_btn.setEnabled(can_stop)
        self._refresh_card_controls()
        self._update_global_run_bar()

    # ================= 定时任务 =================
    def schedule_resync(self):
        """启动/设置变化后重算下次触发时刻(未启用或时刻非法 → None)。"""
        cfg = schedule_core.schedule_config(self.settings)
        if cfg["enabled"]:
            self._sched_next = schedule_core.next_daily_occurrence(
                cfg["time"], datetime.datetime.now())
        else:
            self._sched_next = None
        self._update_global_run_bar()   # 空闲条上的「下次定时」提示

    def _sched_tick(self):
        """每秒检查:到点则触发一次定时流程(弹倒计时确认框)。"""
        if self._sched_next is None:
            return
        now = datetime.datetime.now()
        if now < self._sched_next:
            return
        cfg = schedule_core.schedule_config(self.settings)
        # 先把下次触发推到明天,避免确认框打开期间每秒重复触发
        self._sched_next = (schedule_core.next_daily_occurrence(cfg["time"], now)
                            if cfg["enabled"] else None)
        self._fire_scheduled(cfg)

    def _fire_scheduled(self, cfg):
        if self.controller.running or self.controller.preflight_busy:
            self.append_log("[定时] %s 到点，但任务正在运行，本次定时执行已跳过。"
                            % cfg["time_text"], level="warn")
            return
        active = [p for p in self.plugins if p.get("enabled", True)]
        if not active:
            self.append_log("[定时] %s 到点，但没有勾选任何游戏，本次定时执行已跳过。"
                            % cfg["time_text"], level="warn")
            return
        # 确认框:点「立即运行」或倒计时归零 → 开跑;点「跳过」/Esc → 放弃本次
        try:
            if self.isMinimized():
                self.showNormal()
            self.activateWindow()
            names = [p.get("name", "未命名") for p in active]
            dlg = ScheduleCountdownDialog(self, cfg["time_text"],
                                          cfg["countdown_sec"], names)
            proceed = dlg.exec() == QDialog.DialogCode.Accepted
        except Exception as e:
            self.append_log("[定时] 确认框异常：%s，本次定时执行已跳过。" % e,
                            level="error")
            return
        if proceed:
            self.append_log("[定时] 已确认，开始执行定时任务。", level="ok")
            self.start_run(scheduled=True)
        else:
            self.append_log("[定时] 已跳过本次定时执行（明天 %s 会再次询问）。"
                            % cfg["time_text"], level="warn")

    def _refresh_card_controls(self):
        """运行中禁用卡片操作(旧 _refresh_card_controls 语义):
        忙闲状态翻转时重建卡片,卡片控件按 controller 状态自行启停。"""
        busy = bool(self.controller.running or self.controller.preflight_busy)
        if busy != self._cards_disabled:
            self._cards_disabled = busy
            self.home_page.refresh_cards()

    # ================= 路由 =================
    def go(self, name, plugin=None):
        if name in ("add", "edit"):
            page = self._get_temp_page(name)
            if name == "add":
                page.open_for(plugin if isinstance(plugin, str) else None)
            else:
                page.open_for(plugin if isinstance(plugin, dict) else {})
            self.current_view = name
            self._highlight_nav()
            self.stack.setCurrentWidget(page)
            self.refresh_run_buttons()
            return
        # 返回常驻页:销毁 add/edit 临时页,避免堆积
        self._destroy_temp_pages()
        w = self.pages.get(name)
        if w is None:
            return
        self.current_view = name
        if name != "home":
            # 离开主页时退出专注模式(旧 go 语义)
            try:
                self.home_page.set_log_focus(False)
            except Exception:
                pass
        if name in ("first_run", "settings"):
            try:
                w.refresh()
            except Exception:
                pass
        self._highlight_nav()
        self.stack.setCurrentWidget(w)
        self.refresh_run_buttons()

    def _get_temp_page(self, kind):
        page = self._temp_pages.get(kind)
        if page is None:
            page = AddPage(self) if kind == "add" else EditPage(self)
            self._temp_pages[kind] = page
            self.stack.addWidget(page)
        return page

    def _destroy_temp_pages(self):
        for page in list(self._temp_pages.values()):
            self.stack.removeWidget(page)
            page.deleteLater()
        self._temp_pages.clear()

    def open_edit(self, p):
        self.go("edit", plugin=p)

    def add_plugin(self):
        if self.controller.running or self.controller.preflight_busy:
            return
        self.go("add")

    # ================= 插件操作(照旧版语义) =================
    def reload_plugins(self):
        """重读插件并让主页刷新(reload:order 重排 + 渲染)。"""
        self.plugins = glue.load_plugins()
        for i, p in enumerate(self.plugins, 1):
            if p.get("order") != i:
                p["order"] = i
                glue.save_plugin(p)
        self._render_home()

    def reload_and_render(self):
        self.reload_plugins()

    def _render_home(self):
        self.home_page.refresh_cards()
        self.home_page.refresh_status()

    def _plugin_index(self, p):
        """按插件对象定位下标(卡片顺序会随拖拽变化,不能按值比较)。"""
        for i, q in enumerate(self.plugins):
            if q is p:
                return i
        return -1

    def toggle(self, p):
        if self.controller.running or self.controller.preflight_busy:
            self.home_page.refresh_cards()   # 运行中被拦截:还原开关显示
            return
        p["enabled"] = not bool(p.get("enabled", True))
        glue.save_plugin(p)
        self.home_page.refresh_status()

    def toggle_parallel(self, p):
        """主页卡片「⇉」快捷开关:切换并行状态并保存。"""
        if self.controller.running or self.controller.preflight_busy:
            self.home_page.refresh_cards()
            return
        p["parallel"] = not bool(p.get("parallel", False))
        glue.save_plugin(p)
        self.home_page.refresh_status()

    def move_plugin(self, p, delta):
        """▲▼ 移动:按插件对象定位当前下标。"""
        if self.controller.running or self.controller.preflight_busy:
            return
        idx = self._plugin_index(p)
        if idx >= 0:
            self.move(idx, delta)

    def move(self, idx, delta):
        if self.controller.running or self.controller.preflight_busy:
            return
        j = idx + delta
        if j < 0 or j >= len(self.plugins) or idx == j:
            return
        self.plugins[idx], self.plugins[j] = self.plugins[j], self.plugins[idx]
        self._save_orders()
        self._render_home()

    def reorder_plugin(self, p, new_index):
        """拖拽落点:把 p 移到 new_index 并落盘 order(_save_orders 语义)。"""
        if self.controller.running or self.controller.preflight_busy:
            return
        idx = self._plugin_index(p)
        if idx < 0:
            return
        new_index = max(0, min(int(new_index), len(self.plugins) - 1))
        if new_index == idx:
            return
        item = self.plugins.pop(idx)
        self.plugins.insert(new_index, item)
        self._save_orders()
        self._render_home()

    def _save_orders(self):
        """把当前列表顺序写回 order 字段,只保存真正变化的任务。"""
        for order, plugin in enumerate(self.plugins, 1):
            if plugin.get("order") != order:
                plugin["order"] = order
                glue.save_plugin(plugin)

    def delete_plugin(self, p):
        if self.controller.running or self.controller.preflight_busy:
            return
        answer = QMessageBox.question(
            self, "确认删除",
            "确定删除「%s」吗？\n（只删本助手里的配置，不影响游戏或脚本本体）" % p.get("name"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(p["_file"])
        except Exception as e:
            QMessageBox.critical(self, "删除失败", str(e))
        self.reload_plugins()

    # ================= 主题 / 设置 =================
    def _theme(self):
        name = self.settings.get("theme", theme.DEFAULT_THEME)
        return theme.THEMES.get(name, theme.THEMES[theme.DEFAULT_THEME])

    def _apply_qss(self):
        app = QApplication.instance()
        if app is None:
            return
        name = self.settings.get("theme", theme.DEFAULT_THEME)
        if name not in theme.THEMES:
            name = theme.DEFAULT_THEME
        app.setStyleSheet(theme.qss(name, self.settings))
        # 全局默认字体用 QFont 设置而非 QSS,避免覆盖各页面 setFont 的自定义字号
        app.setFont(theme.font(self.settings, 11))

    def apply_theme_and_rebuild(self):
        """设置页切换主题/字体后调用:重刷全局样式与配色相关控件。"""
        self._apply_qss()
        self._refresh_admin_label()
        self._refresh_shell_fonts()
        try:
            self.home_page.log_panel.render_store()
        except Exception:
            pass
        self._render_home()
        self._highlight_nav()
        self.refresh_run_buttons()
        self._apply_dark_titlebar()
        self.save_settings_soon()

    def _refresh_shell_fonts(self):
        """字号档位变化后,重设外壳各固定控件的字体。"""
        t = self._theme()
        scale = theme.FONT_SCALES.get(self.settings.get("font_size", "中"), 1.0)
        for btn in self._nav_buttons.values():
            btn.setFont(theme.font(self.settings, 12))
        self._admin_lbl.setFont(theme.font(self.settings, 9))
        self._admin_lbl.setStyleSheet(
            "color:%s;padding-left:20px;padding-top:8px;padding-bottom:4px;"
            % (t["ok"] if runner_core.is_admin() else t["warn"]))
        self.global_state_dot.setFont(theme.font(self.settings, 11))
        self.global_run_title.setFont(theme.font(self.settings, 10, True))
        self.global_run_detail.setFont(theme.font(self.settings, 9))
        self.run_elapsed_lbl.setFont(theme.font(self.settings, 9))
        self.global_start_btn.setFont(theme.font(self.settings, 12, True))
        self.global_stop_btn.setFont(theme.font(self.settings, 12, True))
        for lbl in (self.global_run_detail, self.run_elapsed_lbl):
            lbl.setStyleSheet("color:%s;" % t["sub"])
        self.global_progress.setStyleSheet("")

    def save_settings_soon(self):
        self._settings_save_timer.start()

    def _flush_settings(self):
        glue.save_settings(self.settings)

    # ================= 窗口几何持久化 =================
    def _restore_window_geometry(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            sw, sh = geo.width(), geo.height()
        else:
            sw, sh = 1920, 1080
        saved = self.settings.get("window_bounds")
        if saved:
            x, y, w, h = clamp_window_bounds(saved, sw, sh, MIN_W, MIN_H)
            self.setGeometry(x, y, w, h)
        else:
            self.resize(1060, 760)
            self.move(max(0, (sw - 1060) // 2), max(0, (sh - 760) // 2 - 20))
        if self.settings.get("window_maximized"):
            self.setWindowState(Qt.WindowState.WindowMaximized)

    def _schedule_window_save(self):
        if self._restoring_window or not self.isVisible():
            return
        self._window_save_timer.start()

    def _save_window_state(self):
        self.settings["window_maximized"] = self.isMaximized()
        if not self.isMaximized():
            g = self.geometry()
            self.settings["window_bounds"] = {
                "x": g.x(), "y": g.y(), "width": g.width(), "height": g.height(),
            }
        glue.save_settings(self.settings)

    def _end_restore(self):
        self._restoring_window = False

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_window_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_window_save()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._schedule_window_save()

    def closeEvent(self, event):
        if self.controller.running:
            answer = QMessageBox.question(
                self, "退出确认", "任务仍在运行，确定退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        # 运行被中断时若切换过分辨率,这里兜底恢复(正常路径由 RunController finally 恢复)
        display_ctrl.restore_if_needed()
        # flush 防抖中的保存
        self._window_save_timer.stop()
        self._settings_save_timer.stop()
        self._save_window_state()
        glue.save_settings(self.settings)
        event.accept()

    # ================= 图标 / 标题栏 =================
    def _load_logo_pixmap(self, size=40):
        if not os.path.isfile(APP_ICON_PNG):
            return None
        try:
            pix = QPixmap(APP_ICON_PNG)
            if pix.isNull():
                return None
            return pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        except Exception:
            return None

    def _apply_window_state(self):
        self.setMinimumSize(MIN_W, MIN_H)
        try:
            self.setWindowIcon(QIcon(APP_ICON_PNG))
        except Exception:
            pass
        self._apply_dark_titlebar()

    def _apply_dark_titlebar(self):
        """用 DWM 把系统标题栏染成与主题一致（Win10 2004+/Win11），失败静默。"""
        if os.name != "nt":
            return
        try:
            import ctypes
            h = self._theme()["bg"].lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            dark = (0.299 * r + 0.587 * g + 0.114 * b) < 128
            hwnd = int(self.winId())
            value = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    smoke = "--smoke" in argv
    _set_app_user_model_id()
    app = QApplication(argv)
    app.setWindowIcon(QIcon(APP_ICON_PNG))
    win = MainWindow()
    win.show()
    if smoke:
        # 离屏自检:切 6 页 + 灌 3 条日志 + 处理一轮事件后退出
        for name in ("home", "add", "edit", "first_run", "help", "settings"):
            win.go(name)
            app.processEvents()
        win.go("home")
        win.home_page.log_panel.append_lines([
            ("[信息] 冒烟测试行 1", None),
            ("[警告] 冒烟测试行 2", "warn"),
            ("[错误] 冒烟测试行 3", "error"),
        ])
        app.processEvents()
        print("SMOKE OK")
        return 0
    QTimer.singleShot(0, lambda: None)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
