# -*- coding: utf-8 -*-
"""设置页:移植 build_settings:1636(主题/字体/助手根目录/日志保留)。"""
import os

import log_saver
import preset_resolver
import schedule_core

import ui_qt.core_glue as glue
from ui_qt import theme

from PySide6.QtCore import Qt, QTime, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox,
    QTimeEdit, QVBoxLayout, QWidget,
)

# 照抄旧版 FONT_FAMILIES
FONT_FAMILIES = ["微软雅黑", "Microsoft YaHei UI", "黑体", "等线", "宋体", "Arial"]


def _theme_of(settings):
    return theme.THEMES.get(settings.get("theme")) or theme.THEMES[theme.DEFAULT_THEME]


class _ThemeCard(QFrame):
    """主题预览卡片:顶部色块条 + 名称/使用中徽标,整卡可点击。"""
    clicked = Signal(str)

    def __init__(self, name, th, selected):
        super().__init__()
        self._name = name
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QFrame { background: %s; border: 2px solid %s; }"
                           % (th["panel"], th["line"]))

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 顶部色块预览条
        top = QFrame()
        top.setFixedHeight(64)
        top.setStyleSheet("QFrame { background: %s; border: none; }" % th["bg"])
        tv = QHBoxLayout(top)
        tv.setContentsMargins(14, 14, 14, 14)
        for c in (th["accent"], th["fg"], th["sub"], th["panel"]):
            sw = QFrame()
            sw.setFixedSize(20, 20)
            sw.setStyleSheet("QFrame { background: %s; border: 1px solid %s; }"
                             % (c, th["line"]))
            tv.addWidget(sw)
        tv.addStretch(1)
        v.addWidget(top)

        # 名称 + 使用中徽标
        info = QHBoxLayout()
        info.setContentsMargins(14, 10, 14, 10)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("QLabel { color: %s; border: none; font-weight: bold; }"
                               % th["fg"])
        info.addWidget(name_lbl)
        info.addStretch(1)
        mark = "● 使用中" if selected else "点击应用"
        mark_color = "#3ad07f" if selected else th["sub"]
        mark_lbl = QLabel(mark)
        mark_lbl.setStyleSheet("QLabel { color: %s; border: none; }" % mark_color)
        info.addWidget(mark_lbl)
        v.addLayout(info)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._name)
        super().mouseReleaseEvent(ev)


class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._loading = True  # refresh() 同步控件时不触发写回
        self._theme_cards = []

        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        page.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(4)

        title = QLabel("设置")
        title.setFont(theme.font(self.main.settings, 20, True))
        root.addWidget(title)

        # ---- 主题配色 ----
        sec = QLabel("主题配色")
        sec.setFont(theme.font(self.main.settings, 13, True))
        root.addWidget(sec, 0, Qt.AlignTop)
        root.addWidget(self._sub_label("选择一款配色，立即生效并自动记忆。"))
        self._theme_grid_host = QWidget()
        self._theme_grid = QGridLayout(self._theme_grid_host)
        self._theme_grid.setContentsMargins(0, 6, 0, 6)
        root.addWidget(self._theme_grid_host)

        # ---- 字体 ----
        sec = QLabel("字体")
        sec.setFont(theme.font(self.main.settings, 13, True))
        root.addWidget(sec, 0, Qt.AlignTop)
        frow = QHBoxLayout()
        root.addLayout(frow)
        frow.addWidget(QLabel("字体："))
        self._font_combo = QComboBox()
        self._font_combo.addItems(FONT_FAMILIES)
        self._font_combo.setMinimumWidth(180)
        frow.addWidget(self._font_combo)
        frow.addSpacing(18)
        frow.addWidget(QLabel("字号："))
        self._size_radios = {}
        for key in theme.FONT_SCALES.keys():
            rb = QRadioButton(key)
            self._size_radios[key] = rb
            frow.addWidget(rb)
            rb.toggled.connect(lambda on, k=key: self._on_size_toggled(k, on))
        frow.addStretch(1)
        root.addWidget(self._sub_label("提示：若觉得字体偏小或偏大，调整字号即可；"
                                       "高分屏已自动做清晰化处理。"))
        self._font_combo.currentTextChanged.connect(self._on_font_family)

        # ---- 助手安装根目录 ----
        sec = QLabel("助手安装根目录")
        sec.setFont(theme.font(self.main.settings, 13, True))
        root.addWidget(sec, 0, Qt.AlignTop)
        root.addWidget(self._sub_label("自动搜索启动器时优先扫描这个目录（部署向导里也可以设置）。"
                                       "留空则扫描所有固定硬盘的常见位置。"))
        srow = QHBoxLayout()
        root.addLayout(srow)
        self._root_edit = QLineEdit()
        self._root_edit.setReadOnly(True)
        srow.addWidget(self._root_edit, 1)
        btn_pick = QPushButton("选择目录…")
        btn_pick.clicked.connect(self._pick_root)
        srow.addWidget(btn_pick)
        self._btn_clear_root = QPushButton("清除")
        self._btn_clear_root.clicked.connect(self._clear_root)
        srow.addWidget(self._btn_clear_root)
        btn_clear_cache = QPushButton("清除缓存")
        btn_clear_cache.setToolTip("清空启动器路径缓存(path_cache),下次重新探测。")
        btn_clear_cache.clicked.connect(self._clear_path_cache)
        srow.addWidget(btn_clear_cache)

        # ---- 日志自动保存 ----
        sec = QLabel("日志自动保存")
        sec.setFont(theme.font(self.main.settings, 13, True))
        root.addWidget(sec, 0, Qt.AlignTop)
        root.addWidget(self._sub_label("每次运行结束自动保存到 logs\\YYYY-MM-DD.md，"
                                       "一天多次运行用分割线隔开；超过保留期的旧日志"
                                       "在启动/保存时自动清理。"))
        rrow = QHBoxLayout()
        root.addLayout(rrow)
        self._retention_radios = {}
        for value, text in (("week", "保留最近一周"),
                            ("month", "保留最近一个月"),
                            ("forever", "不清理，一直保存")):
            rb = QRadioButton(text)
            self._retention_radios[value] = rb
            rrow.addWidget(rb)
            rrow.addSpacing(12)
            rb.toggled.connect(lambda on, v=value: self._on_retention_toggled(v, on))
        rrow.addStretch(1)
        btn_logs = QPushButton("打开日志目录")
        btn_logs.clicked.connect(self._open_log_dir)
        rrow.addWidget(btn_logs)

        # ---- 运行时分辨率 ----
        sec = QLabel("运行时分辨率")
        sec.setFont(theme.font(self.main.settings, 13, True))
        root.addWidget(sec, 0, Qt.AlignTop)
        root.addWidget(self._sub_label("开源脚本普遍只支持 16:9（1080P/2K）。开启后，"
                                       "开始运行时自动切到所选分辨率，运行结束/停止"
                                       "自动恢复；程序意外退出时下次启动也会自动恢复。"
                                       "仅对主显示器生效。"))
        resrow = QHBoxLayout()
        root.addLayout(resrow)
        resrow.addWidget(QLabel("跑脚本时切换到："))
        self._res_combo = QComboBox()
        self._res_combo.addItem("不切换（保持当前分辨率）", "off")
        self._res_combo.addItem("1920 × 1080", "1920x1080")
        self._res_combo.addItem("2560 × 1440", "2560x1440")
        resrow.addWidget(self._res_combo)
        resrow.addStretch(1)
        self._res_combo.currentIndexChanged.connect(self._on_res_changed)

        # ---- 定时任务 ----
        sec = QLabel("定时任务")
        sec.setFont(theme.font(self.main.settings, 13, True))
        root.addWidget(sec, 0, Qt.AlignTop)
        root.addWidget(self._sub_label("每天到点后弹出倒计时确认框：点「立即运行」或等倒计时归零"
                                       "自动开始执行串行队列；点「跳过」则本次不运行。"
                                       "需要助手保持开启（可以最小化）。"))
        drow = QHBoxLayout()
        root.addLayout(drow)
        self._sched_enable = QCheckBox("启用每日定时运行")
        drow.addWidget(self._sched_enable)
        drow.addSpacing(18)
        drow.addWidget(QLabel("每天"))
        self._sched_time = QTimeEdit()
        self._sched_time.setDisplayFormat("HH:mm")
        drow.addWidget(self._sched_time)
        drow.addWidget(QLabel("开始，确认倒计时"))
        self._sched_count = QSpinBox()
        self._sched_count.setRange(schedule_core.COUNTDOWN_MIN,
                                   schedule_core.COUNTDOWN_MAX)
        self._sched_count.setSuffix(" 秒")
        self._sched_count.setToolTip("到点后弹窗倒计时的秒数；倒计时归零自动开始，"
                                     "期间可随时点「跳过本次」。")
        drow.addWidget(self._sched_count)
        drow.addStretch(1)
        self._sched_enable.toggled.connect(self._on_sched_changed)
        self._sched_time.timeChanged.connect(self._on_sched_changed)
        self._sched_count.valueChanged.connect(self._on_sched_changed)

        root.addStretch(1)
        self.refresh()
        self._loading = False

    # ---- 小工具 ----
    def _sub_label(self, text):
        t = _theme_of(self.main.settings)
        lab = QLabel(text)
        lab.setFont(theme.font(self.main.settings, 9))
        lab.setStyleSheet("color: %s;" % t["sub"])
        lab.setWordWrap(True)
        return lab

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _log_line(self, text, level="info"):
        """往主页日志面板补一行(尽力而为)。"""
        try:
            self.main.append_log(text, level)
        except Exception:
            print(text)

    # ---- 行为 ----
    def refresh(self):
        """重读设置并同步所有控件。"""
        s = self.main.settings
        self._loading = True

        # 主题卡片(重建,刷新「使用中」徽标)
        self._clear_layout(self._theme_grid)
        cur = s.get("theme", theme.DEFAULT_THEME)
        for i, (name, th) in enumerate(theme.THEMES.items()):
            card = _ThemeCard(name, th, selected=(name == cur))
            card.clicked.connect(self._apply_theme)
            row, col = divmod(i, 2)
            self._theme_grid.addWidget(card, row, col)

        # 字体
        family = s.get("font_family", "微软雅黑")
        if family not in FONT_FAMILIES:
            family = "微软雅黑"
        self._font_combo.blockSignals(True)
        self._font_combo.setCurrentText(family)
        self._font_combo.blockSignals(False)
        size = s.get("font_size", "中")
        for key, rb in self._size_radios.items():
            rb.blockSignals(True)
            rb.setChecked(key == size)
            rb.blockSignals(False)

        # 助手根目录
        root_dir = preset_resolver.get_assistants_root(s)
        self._root_edit.setText(root_dir)
        self._btn_clear_root.setVisible(bool(root_dir))

        # 日志保留
        retention = s.get("log_retention", "month")
        for value, rb in self._retention_radios.items():
            rb.blockSignals(True)
            rb.setChecked(value == retention)
            rb.blockSignals(False)

        # 运行时分辨率
        target = s.get("run_resolution", "off") or "off"
        idx = self._res_combo.findData(target)
        self._res_combo.blockSignals(True)
        self._res_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._res_combo.blockSignals(False)

        # 定时任务
        self._sched_enable.blockSignals(True)
        self._sched_enable.setChecked(bool(s.get("schedule_enabled", False)))
        t = QTime.fromString(str(s.get("schedule_time", schedule_core.DEFAULT_TIME)),
                             "HH:mm")
        if not t.isValid():
            t = QTime.fromString(schedule_core.DEFAULT_TIME, "HH:mm")
        self._sched_time.setTime(t)
        self._sched_count.setValue(schedule_core.countdown_bounds(
            s.get("schedule_countdown_sec", schedule_core.DEFAULT_COUNTDOWN_SEC)))
        self._sched_enable.blockSignals(False)

        self._loading = False

    def _apply_theme(self, name):
        if name not in theme.THEMES or self._loading:
            return
        self.main.settings["theme"] = name
        self.main.save_settings_soon()
        self.main.apply_theme_and_rebuild()

    def _on_font_family(self, family):
        if self._loading:
            return
        self.main.settings["font_family"] = family
        self.main.save_settings_soon()
        self.main.apply_theme_and_rebuild()

    def _on_size_toggled(self, key, on):
        if self._loading or not on:
            return
        self.main.settings["font_size"] = key
        self.main.save_settings_soon()
        self.main.apply_theme_and_rebuild()

    def _pick_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择助手安装根目录")
        if not d:
            return
        self.main.settings["assistants_root"] = os.path.normpath(d)
        self.main.save_settings_soon()
        self.refresh()

    def _clear_root(self):
        self.main.settings["assistants_root"] = ""
        self.main.save_settings_soon()
        self.refresh()

    def _clear_path_cache(self):
        self.main.settings["path_cache"] = {}
        self.main.save_settings_soon()

    def _on_retention_toggled(self, value, on):
        if self._loading or not on:
            return
        self.main.settings["log_retention"] = value
        self.main.save_settings_soon()
        removed = log_saver.cleanup_old_logs(
            glue.LOG_DIR, log_saver.retention_days(value))
        if removed:
            self._log_line("已按新保留策略清理 %d 个过期日志文件。" % removed, level="info")

    def _on_res_changed(self, index):
        """运行时分辨率下拉变化:写回 settings(RunController 在开跑时应用)。"""
        if self._loading:
            return
        self.main.settings["run_resolution"] = self._res_combo.itemData(index) or "off"
        self.main.save_settings_soon()

    def _on_sched_changed(self, *_):
        """定时任务任一控件变化:写回设置并让主窗口重算下次触发时刻。"""
        if self._loading:
            return
        s = self.main.settings
        s["schedule_enabled"] = self._sched_enable.isChecked()
        s["schedule_time"] = self._sched_time.time().toString("HH:mm")
        s["schedule_countdown_sec"] = self._sched_count.value()
        self.main.save_settings_soon()
        self.main.schedule_resync()

    def _open_log_dir(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(glue.LOG_DIR))
