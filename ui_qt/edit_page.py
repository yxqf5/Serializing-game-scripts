# -*- coding: utf-8 -*-
"""编辑页:移植 build_edit:1141 全部字段 + 高级折叠 + 粘贴填充 + _save_edit:1370 保存。"""
import os

import preset_catalog as pc
import preset_resolver as pr

import ui_qt.core_glue as glue
import ui_qt.dialogs as dlg
from ui_qt import theme

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)


def _theme_of(settings):
    return theme.THEMES.get(settings.get("theme")) or theme.THEMES[theme.DEFAULT_THEME]


class EditPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._plugin = None
        self._check_vars = []      # [(待办条目, QCheckBox)]
        self._adv_visible = False

        self._build_ui()

    # ---------------- 界面 ----------------
    def _build_ui(self):
        s = self.main.settings
        t = _theme_of(s)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 头部
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(26, 22, 26, 6)
        hl.addWidget(self._chip("←  返回", lambda: self.main.go("home")))
        title = QLabel("编辑游戏")
        title.setFont(theme.font(s, 20, True))
        hl.addWidget(title)
        hl.addSpacing(14)
        hl.addStretch(1)
        self._change_preset_btn = self._chip("更换预设", self._go_add)
        hl.addWidget(self._change_preset_btn)
        hl.addWidget(self._chip("粘贴填充", self._open_quick_fill))
        root.addWidget(head)

        # 滚动表单
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(scroll, 1)
        form = QWidget()
        scroll.setWidget(form)
        fv = QVBoxLayout(form)
        fv.setContentsMargins(26, 8, 26, 18)
        fv.setSpacing(4)

        # 当前预设
        self._preset_tag = QLabel("")
        self._preset_tag.setFont(theme.font(s, 11))
        self._preset_tag.setStyleSheet("color: %s;" % t["accent"])
        self._preset_tag.setVisible(False)
        fv.addWidget(self._preset_tag)

        # 显示名称
        fv.addWidget(self._label("显示名称"))
        self.e_name = QLineEdit()
        self.e_name.setFont(theme.font(s, 11))
        fv.addWidget(self.e_name)

        # 并行
        self.parallel_box = QCheckBox("⇉ 并行运行（与其它任务同时启动）")
        self.parallel_box.setFont(theme.font(s, 11, True))
        fv.addWidget(self.parallel_box)
        fv.addWidget(self._hint(
            "适合模拟器／后台类脚本（如 MAA）：点「开始运行」时立即与其它任务同时跑，不用排队等。"
            "会抢占真实鼠标的脚本（原神、绝区零、崩铁等）不要勾，否则会互相抢鼠标；"
            "多个勾了并行的任务也会同时启动。"))

        # 启动器
        fv.addWidget(self._label("脚本 / 启动器程序（.exe）",
                                 "就是平时你双击打开的那个脚本程序。"))
        lrow = QWidget()
        lr = QHBoxLayout(lrow)
        lr.setContentsMargins(0, 0, 0, 0)
        self.e_launcher = QLineEdit()
        self.e_launcher.setFont(theme.font(s, 11))
        lr.addWidget(self.e_launcher, 1)
        lr.addWidget(self._chip("浏览…", self._browse))
        fv.addWidget(lrow)

        # 脚本侧待办
        self._check_label = self._label(
            "脚本侧待办（勾选表示已完成；未完成时运行日志会黄色警告）",
            "这些是各脚本里还需要你手动确认的设置，助手不会替你改脚本配置。")
        self._check_label.setVisible(False)
        self._check_wrap = QWidget()
        self._check_v = QVBoxLayout(self._check_wrap)
        self._check_v.setContentsMargins(0, 0, 0, 0)
        self._check_v.setSpacing(2)
        self._check_wrap.setVisible(False)
        fv.addWidget(self._check_label)
        fv.addWidget(self._check_wrap)

        # 文档链接
        self._doc_link = QLabel("")
        self._doc_link.setFont(theme.font(s, 10))
        self._doc_link.setStyleSheet("color: %s;" % t["accent"])
        self._doc_link.setCursor(Qt.PointingHandCursor)
        self._doc_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._doc_link.linkActivated.connect(self._open_doc)
        self._doc_link.setVisible(False)
        fv.addWidget(self._doc_link)

        # 高级选项折叠(默认收起,照 _toggle_advanced:1336)
        self._adv_check = QCheckBox("▸ 展开高级选项")
        self._adv_check.setFont(theme.font(s, 11, True))
        self._adv_check.setChecked(False)
        self._adv_check.toggled.connect(self._toggle_advanced)
        fv.addSpacing(12)
        fv.addWidget(self._adv_check)

        self.advanced_frame = QWidget()
        av = QVBoxLayout(self.advanced_frame)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(4)
        fv.addWidget(self.advanced_frame)
        self.advanced_frame.setVisible(False)

        # 高级:启动参数
        self._adv_label(av, "启动参数（可留空）",
                        "高级：空格分隔。绝区零 -o --close-game；原神 startOneDragon。")
        self.e_args = self._mono_entry()
        av.addWidget(self.e_args)

        # 高级:前置程序
        self._adv_label(av, "前置程序（可留空）",
                        "先启动它，再启动上面的脚本。适合 MaaEnd 这类无法自己开游戏的脚本：这里填游戏本体 exe。")
        prow = QWidget()
        pr = QHBoxLayout(prow)
        pr.setContentsMargins(0, 0, 0, 0)
        self.e_pre = self._mono_entry()
        pr.addWidget(self.e_pre, 1)
        pr.addWidget(self._chip("浏览…", self._browse_pre))
        av.addWidget(prow)

        # 高级:前置参数
        self._adv_label(av, "前置程序参数（可留空）", "空格分隔；一般留空。")
        self.e_pre_args = self._mono_entry()
        av.addWidget(self.e_pre_args)

        # 高级:前置等待
        self._adv_label(av, "前置启动后等待（秒）",
                        "给游戏留出加载时间再启动脚本；已在运行则自动跳过前置启动。")
        self.e_pre_delay = QSpinBox()
        self.e_pre_delay.setRange(0, 600)
        self.e_pre_delay.setFixedWidth(110)
        self.e_pre_delay.setFont(theme.font(s, 11))
        av.addWidget(self.e_pre_delay, 0, Qt.AlignLeft)

        # 高级:任务日志提取
        self._adv_label(av, "任务日志提取（可留空则跳过）",
                        "读取脚本自身日志，只提取：每日奖励完成（金色）/未完成（红色）/最新体力剩余（蓝色）。")
        lfrow = QWidget()
        lr = QHBoxLayout(lfrow)
        lr.setContentsMargins(0, 0, 0, 0)
        self.e_log_file = self._mono_entry()
        lr.addWidget(self.e_log_file, 1)
        lr.addWidget(self._chip("浏览…", self._browse_log))
        av.addWidget(lfrow)

        # 高级:日志编码
        self._adv_label(av, "日志编码")
        self.e_log_enc = QComboBox()
        self.e_log_enc.addItems(["auto", "gbk", "utf-8"])
        self.e_log_enc.setFixedWidth(140)
        self.e_log_enc.setFont(theme.font(s, 10))
        av.addWidget(self.e_log_enc, 0, Qt.AlignLeft)

        # 高级:每日奖励关键词
        self._adv_label(av, "每日奖励·已完成关键词（逗号分隔，金色）",
                        "例：今日奖励已领取, 每日实训已完成。")
        self.e_daily_done = self._mono_entry()
        av.addWidget(self.e_daily_done)

        self._adv_label(av, "每日奖励·未完成关键词（逗号分隔，红色）",
                        "例：未领取, 未检测到每日实训奖励。")
        self.e_daily_pending = self._mono_entry()
        av.addWidget(self.e_daily_pending)

        self._adv_label(av, "体力/理智关键词（逗号分隔，蓝色，只取最新一条）",
                        "例：开拓力, Current Sanity。")
        self.e_stamina = self._mono_entry()
        av.addWidget(self.e_stamina)

        # 高级:完成判定方式(wait_mode,两项下拉)
        self._adv_label(av, "完成判定方式")
        self.wait_combo = QComboBox()
        for mode, lab in glue.WAIT_MODE_LABELS.items():
            self.wait_combo.addItem(lab, mode)
        self.wait_combo.setFixedWidth(360)
        self.wait_combo.setFont(theme.font(s, 10))
        av.addWidget(self.wait_combo, 0, Qt.AlignLeft)

        # 高级:进程名
        self._adv_label(av, "游戏进程名（多个用逗号分隔）",
                        "原神国服 YuanShen.exe；崩铁 StarRail.exe；MAA 可留空。")
        self.e_game = self._mono_entry()
        av.addWidget(self.e_game)

        self._adv_label(av, "助手进程名（多个用逗号分隔）",
                        "跑完后要关闭的脚本进程，如 BetterGI.exe、MAA.exe。")
        self.e_helper = self._mono_entry()
        av.addWidget(self.e_helper)

        # 高级:超时
        self._adv_label(av, "等待游戏启动超时（分钟）")
        self.e_timeout = QSpinBox()
        self.e_timeout.setRange(1, 120)
        self.e_timeout.setFixedWidth(110)
        self.e_timeout.setFont(theme.font(s, 11))
        av.addWidget(self.e_timeout, 0, Qt.AlignLeft)

        # 高级:备注
        self._adv_label(av, "备注")
        self.t_notes = QPlainTextEdit()
        self.t_notes.setFixedHeight(72)
        self.t_notes.setFont(theme.font(s, 10))
        av.addWidget(self.t_notes)

        # 保存/取消
        fv.addSpacing(14)
        bf = QWidget()
        bl = QHBoxLayout(bf)
        bl.setContentsMargins(0, 0, 0, 0)
        save_btn = QPushButton("保存")
        save_btn.setProperty("class", "accent")
        save_btn.clicked.connect(self._save_edit)
        bl.addWidget(save_btn)
        bl.addWidget(self._chip("取消", lambda: self.main.go("home")))
        bl.addStretch(1)
        fv.addWidget(bf)
        fv.addStretch(1)

    # ---------------- 小工具 ----------------
    def _chip(self, text, cmd):
        b = QPushButton(text)
        b.setFont(theme.font(self.main.settings, 9))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(cmd)
        return b

    def _label(self, text, hint=""):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        lab = QLabel(text)
        lab.setFont(theme.font(self.main.settings, 11, True))
        lab.setWordWrap(True)
        v.addWidget(lab)
        if hint:
            v.addWidget(self._hint(hint))
        return w

    def _hint(self, text):
        t = _theme_of(self.main.settings)
        lab = QLabel(text)
        lab.setFont(theme.font(self.main.settings, 9))
        lab.setStyleSheet("color: %s;" % t["sub"])
        lab.setWordWrap(True)
        return lab

    def _adv_label(self, layout, text, hint=""):
        layout.addSpacing(10)
        layout.addWidget(self._label(text, hint))

    def _mono_entry(self):
        e = QLineEdit()
        e.setFont(QFont("Consolas", theme.base_pt(11, self.main.settings)))
        return e

    def _toggle_advanced(self, checked):
        """照 _toggle_advanced:1336:切换显隐与文案。"""
        self._adv_visible = bool(checked)
        self.advanced_frame.setVisible(self._adv_visible)
        self._adv_check.setText("▾ 收起高级选项" if checked else "▸ 展开高级选项")

    def _go_add(self):
        if hasattr(self.main, "add_plugin"):
            self.main.add_plugin()
        else:
            self.main.go("add")

    def _open_doc(self, url):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # ---------------- 填表 ----------------
    def open_for(self, plugin) -> None:
        p = plugin or {}
        self._plugin = p
        s = self.main.settings

        # 当前预设 / 更换预设
        preset_id = p.get("preset_id", "")
        tag = ""
        if preset_id:
            try:
                game, script = pc.find_script_by_preset_id(pc.load_catalog(), preset_id)
            except Exception:
                game = script = None
            tag = "%s · %s" % (game.get("name", ""), script.get("name", "")) \
                if game and script else preset_id
        self._preset_tag.setText(tag)
        self._preset_tag.setVisible(bool(tag))
        self._change_preset_btn.setVisible(bool(preset_id))

        self.e_name.setText(p.get("name", ""))
        self.parallel_box.setChecked(bool(p.get("parallel", False)))
        self.e_launcher.setText(p.get("launcher", ""))

        # 待办清单
        while self._check_v.count():
            item = self._check_v.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._check_vars = []
        checklist = p.get("setup_checklist") or []
        done_set = set(p.get("checklist_done") or [])
        self._check_label.setVisible(bool(checklist))
        self._check_wrap.setVisible(bool(checklist))
        if checklist:
            for item in checklist:
                cb = QCheckBox(item)
                cb.setFont(theme.font(s, 10))
                cb.setChecked(item in done_set)
                self._check_vars.append((item, cb))
                self._check_v.addWidget(cb)

        # 文档链接
        doc = p.get("doc_url", "")
        self._doc_url = doc
        self._doc_link.setText('<a href="%s">📎 官方文档 / 项目页</a>' % doc)
        self._doc_link.setVisible(bool(doc))

        # 常规字段
        self.e_args.setText(" ".join(p.get("args", [])))
        self.e_pre.setText(p.get("pre_launcher", ""))
        self.e_pre_args.setText(" ".join(p.get("pre_args", [])))
        try:
            self.e_pre_delay.setValue(max(0, int(p.get("pre_delay_sec", 0))))
        except Exception:
            self.e_pre_delay.setValue(0)
        self.e_log_file.setText(p.get("log_file", ""))
        enc_val = (p.get("log_encoding") or "auto").strip().lower()
        self.e_log_enc.setCurrentText(enc_val if enc_val in ("auto", "gbk", "utf-8") else "auto")
        self.e_daily_done.setText(", ".join(p.get("daily_done_patterns", [])))
        self.e_daily_pending.setText(", ".join(p.get("daily_pending_patterns", [])))
        self.e_stamina.setText(", ".join(p.get("stamina_patterns", [])))
        wi = self.wait_combo.findData(p.get("wait_mode", "game"))
        self.wait_combo.setCurrentIndex(wi if wi >= 0 else 0)
        self.e_game.setText(", ".join(p.get("game_processes", [])))
        self.e_helper.setText(", ".join(p.get("helper_processes", [])))
        try:
            timeout = int(p.get("start_timeout_min", 15))
        except Exception:
            timeout = 15
        self.e_timeout.setValue(max(1, min(120, timeout)))
        self.t_notes.setPlainText(p.get("notes", ""))

        # 高级选项默认收起
        self._adv_check.setChecked(False)

    # ---------------- 浏览(照 _browse*:1345-1369) ----------------
    def _browse(self):
        path, _f = QFileDialog.getOpenFileName(
            self, "选择脚本/启动器程序", "",
            "可执行程序 (*.exe);;所有文件 (*.*)")
        if path:
            self.e_launcher.setText(os.path.normpath(path))

    def _browse_pre(self):
        path, _f = QFileDialog.getOpenFileName(
            self, "选择前置程序（如游戏本体 exe）", "",
            "可执行程序 (*.exe);;所有文件 (*.*)")
        if path:
            self.e_pre.setText(os.path.normpath(path))

    def _browse_log(self):
        path, _f = QFileDialog.getOpenFileName(
            self, "选择脚本日志文件", "",
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*.*)")
        if path:
            self.e_log_file.setText(os.path.normpath(path))

    @staticmethod
    def _split(text):
        return [x.strip() for x in text.replace("，", ",").split(",") if x.strip()]

    # ---------------- 粘贴填充(edit) ----------------
    def _open_quick_fill(self):
        d = dlg.QuickFillDialog(self, "edit", self._plugin)
        d.applied.connect(self._apply_parsed_to_edit)
        d.confirmed.connect(self._on_quick_fill_confirm)
        d.exec()

    def _on_quick_fill_confirm(self, parsed):
        self._apply_parsed_to_edit(parsed)
        self._save_edit()

    def _apply_parsed_to_edit(self, parsed):
        """照 _apply_parsed_to_edit:1540 语义:按字段填表,高级字段自动展开。"""
        advanced_keys = {"args", "wait_mode", "game_processes", "helper_processes",
                         "start_timeout_min", "notes", "pre_launcher", "pre_args",
                         "pre_delay_sec", "log_file", "log_encoding",
                         "daily_done_patterns", "daily_pending_patterns",
                         "stamina_patterns"}
        if advanced_keys & set(parsed.keys()) and not self._adv_visible:
            self._adv_check.setChecked(True)

        if "name" in parsed:
            self.e_name.setText(parsed["name"])
        if "launcher" in parsed:
            self.e_launcher.setText(parsed["launcher"])
        if "args" in parsed:
            self.e_args.setText(" ".join(parsed["args"]))
        if "pre_launcher" in parsed:
            self.e_pre.setText(parsed["pre_launcher"])
        if "pre_args" in parsed:
            self.e_pre_args.setText(" ".join(parsed["pre_args"]))
        if "pre_delay_sec" in parsed:
            try:
                val = max(0, min(600, int(parsed["pre_delay_sec"])))
            except Exception:
                val = 0
            self.e_pre_delay.setValue(val)
        if "log_file" in parsed:
            self.e_log_file.setText(parsed["log_file"])
        if "log_encoding" in parsed:
            enc = (parsed["log_encoding"] or "auto").strip().lower()
            self.e_log_enc.setCurrentText(enc if enc in ("auto", "gbk", "utf-8") else "auto")
        if "daily_done_patterns" in parsed:
            self.e_daily_done.setText(", ".join(parsed["daily_done_patterns"]))
        if "daily_pending_patterns" in parsed:
            self.e_daily_pending.setText(", ".join(parsed["daily_pending_patterns"]))
        if "stamina_patterns" in parsed:
            self.e_stamina.setText(", ".join(parsed["stamina_patterns"]))
        if "wait_mode" in parsed:
            wi = self.wait_combo.findData(parsed["wait_mode"])
            if wi >= 0:
                self.wait_combo.setCurrentIndex(wi)
        if "game_processes" in parsed:
            self.e_game.setText(", ".join(parsed["game_processes"]))
        if "helper_processes" in parsed:
            self.e_helper.setText(", ".join(parsed["helper_processes"]))
        if "start_timeout_min" in parsed:
            try:
                val = max(1, min(120, int(parsed["start_timeout_min"])))
            except Exception:
                val = 15
            self.e_timeout.setValue(val)
        if "notes" in parsed:
            self.t_notes.setPlainText(parsed["notes"])
        if "checklist_done" in parsed:
            done = set(parsed["checklist_done"])
            for item, var in self._check_vars:
                var.setChecked(item in done)
        if "doc_url" in parsed and self._plugin is not None:
            self._plugin["doc_url"] = parsed["doc_url"]
            self._doc_url = parsed["doc_url"]
            self._doc_link.setText('<a href="%s">📎 官方文档 / 项目页</a>' % parsed["doc_url"])
            self._doc_link.setVisible(bool(parsed["doc_url"]))

    # ---------------- 保存(照 _save_edit:1370) ----------------
    def _save_edit(self):
        p = self._plugin
        if p is None:
            return
        name = self.e_name.text().strip()
        if not name:
            dlg.showwarning(self, "提示", "请填写显示名称。")
            return
        p["name"] = name
        p["launcher"] = self.e_launcher.text().strip().strip('"')
        p["args"] = self.e_args.text().split()
        p["pre_launcher"] = self.e_pre.text().strip().strip('"')
        p["pre_args"] = self.e_pre_args.text().split()
        p["pre_delay_sec"] = int(self.e_pre_delay.value())
        p["log_file"] = self.e_log_file.text().strip().strip('"')
        p["log_encoding"] = (self.e_log_enc.currentText() or "auto").strip().lower()
        p["daily_done_patterns"] = self._split(self.e_daily_done.text())
        p["daily_pending_patterns"] = self._split(self.e_daily_pending.text())
        p["stamina_patterns"] = self._split(self.e_stamina.text())
        p.pop("done_patterns", None)
        p.pop("fail_patterns", None)
        p.pop("tail_lines", None)
        p["wait_mode"] = self.wait_combo.currentData() or "game"
        p["parallel"] = bool(self.parallel_box.isChecked())
        p["game_processes"] = self._split(self.e_game.text())
        p["helper_processes"] = self._split(self.e_helper.text())
        p["start_timeout_min"] = int(self.e_timeout.value())
        p["notes"] = self.t_notes.toPlainText().strip()
        p["checklist_done"] = [item for item, var in self._check_vars if var.isChecked()]
        pid = p.get("preset_id")
        if pid and p.get("launcher"):
            pr.update_path_cache(self.main.settings, pid, p["launcher"])
            glue.save_settings(self.main.settings)
        try:
            glue.save_plugin(p)
        except Exception as e:
            dlg.showerror(self, "保存失败", str(e))
            return
        self.main.reload_and_render()
        self.main.go("home")
