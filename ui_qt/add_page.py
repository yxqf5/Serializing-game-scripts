# -*- coding: utf-8 -*-
"""添加页:移植 build_add:1911(游戏/脚本下拉 → 启动器探测 → 候选 → 自定义 → 保存)。"""
import os
import threading
import time

import preset_catalog as pc
import preset_resolver as pr

import ui_qt.core_glue as glue
import ui_qt.dialogs as dlg
from ui_qt import theme

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)


def _theme_of(settings):
    return theme.THEMES.get(settings.get("theme")) or theme.THEMES[theme.DEFAULT_THEME]


class AddPage(QWidget):
    # 深度探测完成:token, 候选路径列表, 是否超时
    scan_done = Signal(int, list, bool)

    def __init__(self, main):
        super().__init__()
        self.main = main
        self._catalog = pc.load_catalog()
        self._games = self._catalog.get("games", [])
        self._scan_token = 0
        self._fill_overrides = {}     # 粘贴填充覆盖字段(保存时套用)
        self._check_vars = []         # [(待办条目, QCheckBox)]
        self._custom_ref_map = {}     # 参考预设标签 → (game, script)

        self._build_ui()
        self.scan_done.connect(self._on_scan_done)
        self.open_for(None)

    # ---------------- 界面 ----------------
    def _build_ui(self):
        s = self.main.settings
        t = _theme_of(s)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 14)
        root.setSpacing(6)

        # 头部:返回 / 标题 / 粘贴填充
        head = QHBoxLayout()
        root.addLayout(head)
        head.addWidget(self._chip("←  返回", lambda: self.main.go("home")))
        title = QLabel("添加游戏")
        title.setFont(theme.font(s, 20, True))
        head.addWidget(title)
        head.addSpacing(14)
        head.addStretch(1)
        head.addWidget(self._chip("粘贴填充", self._open_quick_fill))

        hint = QLabel("选择游戏与脚本；切换选项时仅快速检测，「重新探测」深度搜索最多 10 秒。")
        hint.setFont(theme.font(s, 10))
        hint.setStyleSheet("color: %s;" % t["sub"])
        root.addWidget(hint)
        root.addSpacing(6)

        lab = QLabel("游戏")
        lab.setFont(theme.font(s, 11, True))
        root.addWidget(lab)
        self._game_combo = QComboBox()
        for g in self._games:
            self._game_combo.addItem(g.get("name", ""))
        self._game_combo.currentTextChanged.connect(self._on_game_change)
        root.addWidget(self._game_combo)

        lab = QLabel("脚本 / 助手")
        lab.setFont(theme.font(s, 11, True))
        root.addWidget(lab)
        self._script_combo = QComboBox()
        self._script_combo.currentTextChanged.connect(self._on_script_change)
        root.addWidget(self._script_combo)

        # 启动器路径
        self._path_label = QLabel("启动器路径")
        self._path_label.setFont(theme.font(s, 11, True))
        root.addWidget(self._path_label)
        pf = QWidget()
        prow = QHBoxLayout(pf)
        prow.setContentsMargins(0, 0, 0, 0)
        self._path_edit = QLineEdit()
        prow.addWidget(self._path_edit, 1)
        prow.addWidget(self._chip("重新探测", lambda: self._rescan(False)))
        prow.addWidget(self._chip("浏览…", self._browse))
        root.addWidget(pf)

        self._status = QLabel("")
        self._status.setFont(theme.font(s, 9))
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        # 多候选列表(≥1 个时才显示)
        self._candidates = QListWidget()
        self._candidates.setVisible(False)
        self._candidates.setMaximumHeight(140)
        self._candidates.itemClicked.connect(
            lambda item: self._pick_candidate(item.data(Qt.ItemDataRole.UserRole)))
        root.addWidget(self._candidates)

        # 脚本侧待办勾选区
        self._check_wrap = QWidget()
        self._check_v = QVBoxLayout(self._check_wrap)
        self._check_v.setContentsMargins(0, 0, 0, 0)
        self._check_v.setSpacing(2)
        root.addWidget(self._check_wrap)

        # 「其他 / 自定义」专用面板(custom 游戏时才显示)
        self._custom_frame = self._build_custom_frame()
        root.addWidget(self._custom_frame)

        # custom 模式下整体隐藏的常规控件
        self._normal_widgets = [self._path_label, pf, self._status,
                                self._candidates, self._check_wrap]

        root.addStretch(1)
        self._save_row = QWidget()
        srow = QHBoxLayout(self._save_row)
        srow.setContentsMargins(0, 0, 0, 0)
        save_btn = QPushButton("保存并返回")
        save_btn.setProperty("class", "accent")
        save_btn.clicked.connect(self._save_add)
        srow.addWidget(save_btn)
        srow.addStretch(1)
        root.addWidget(self._save_row)

    def _chip(self, text, cmd):
        b = QPushButton(text)
        b.setFont(theme.font(self.main.settings, 9))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(cmd)
        return b

    def _build_custom_frame(self):
        """构造 custom 分支的两选项 UI(照 _build_add_custom_frame:2052)。"""
        s = self.main.settings
        t = _theme_of(s)
        f = QFrame()
        f.setStyleSheet("QFrame { background: %s; border: 1px solid %s; }" % (t["panel"], t["line"]))
        fv = QVBoxLayout(f)
        fv.setContentsMargins(14, 10, 14, 10)
        fv.setSpacing(8)

        head = QLabel("没找到你要用的脚本?两种方式添加:")
        head.setFont(theme.font(s, 11, True))
        fv.addWidget(head)

        # 方式 1:基于已有预设
        opt1 = QLabel("① 基于内置预设修改")
        opt1.setFont(theme.font(s, 12, True))
        fv.addWidget(opt1)
        fv.addWidget(self._hint_label(
            "从下面挑一个和你的脚本最相似的:助手会复制它的等待模式、进程判定等设置作起点,"
            "你之后只需在编辑页里改改进程名和路径。适合大多数「同类脚本」。"))
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("参考预设:"))
        # 所有非 custom 游戏的脚本
        refs = []
        try:
            catalog = pc.load_catalog()
            for g in catalog.get("games", []):
                if g.get("id") == "custom":
                    continue
                for sc in g.get("scripts", []):
                    refs.append(("%s · %s" % (g.get("name", ""), sc.get("name", "")), g, sc))
        except Exception:
            pass
        self._custom_ref_map = {label: (g, sc) for label, g, sc in refs}
        self._custom_ref_combo = QComboBox()
        for label, _g, _sc in refs:
            self._custom_ref_combo.addItem(label)
        row1.addWidget(self._custom_ref_combo, 1)
        fv.addLayout(row1)
        btn1 = QPushButton("复制这个预设并进入编辑页")
        btn1.setProperty("class", "accent")
        btn1.clicked.connect(self._custom_use_reference)
        fv.addWidget(btn1, 0, Qt.AlignLeft)

        # 方式 2:完全手填
        opt2 = QLabel("② 完全手填")
        opt2.setFont(theme.font(s, 12, True))
        fv.addWidget(opt2)
        fv.addWidget(self._hint_label(
            "从空白开始填全部字段。若你还没确定 wait_mode / 进程名等,建议先选 ①。"))
        btn2 = QPushButton("新建空白配置并编辑")
        btn2.clicked.connect(self._custom_use_blank)
        fv.addWidget(btn2, 0, Qt.AlignLeft)

        f.setVisible(False)
        return f

    def _hint_label(self, text):
        t = _theme_of(self.main.settings)
        lab = QLabel(text)
        lab.setFont(theme.font(self.main.settings, 9))
        lab.setStyleSheet("color: %s;" % t["sub"])
        lab.setWordWrap(True)
        return lab

    # ---------------- 状态 ----------------
    def open_for(self, preset_id=None) -> None:
        """每次进入添加页重置;preset_id 用于预选游戏/脚本。"""
        self._fill_overrides = {}
        self._scan_token += 1
        self._path_edit.clear()
        self._set_status("", None)
        self._fill_candidates([])

        game = script = None
        if preset_id:
            try:
                game, script = pc.find_script_by_preset_id(self._catalog, preset_id)
            except Exception:
                game = script = None
        idx = 0
        if game is not None:
            found = self._game_combo.findText(game.get("name", ""))
            if found >= 0:
                idx = found
        self._game_combo.blockSignals(True)
        self._game_combo.setCurrentIndex(idx)
        self._game_combo.blockSignals(False)
        self._on_game_change()
        if script is not None:
            si = self._script_combo.findText(script.get("name", ""))
            if si >= 0:
                self._script_combo.blockSignals(True)
                self._script_combo.setCurrentIndex(si)
                self._script_combo.blockSignals(False)
                self._on_script_change()

    def _selected_game(self):
        name = self._game_combo.currentText()
        for g in self._games:
            if g.get("name") == name:
                return g
        return self._games[0] if self._games else None

    def _selected_script(self):
        game = self._selected_game()
        if not game:
            return None
        name = self._script_combo.currentText()
        for sc in game.get("scripts", []):
            if sc.get("name") == name:
                return sc
        scripts = game.get("scripts", [])
        return scripts[0] if scripts else None

    # ---------------- 下拉联动 ----------------
    def _on_game_change(self, *_):
        game = self._selected_game()
        if not game:
            return
        scripts = game.get("scripts", [])
        self._script_combo.blockSignals(True)
        self._script_combo.clear()
        for sc in scripts:
            self._script_combo.addItem(sc.get("name", ""))
        self._script_combo.blockSignals(False)

        # 是否 custom 分支?切换 UI
        is_custom = (game.get("id") == "custom")
        self._apply_custom_mode(is_custom)
        if is_custom:
            return  # custom 分支不走后续脚本/checklist/rescan
        self._on_script_change()

    def _on_script_change(self, *_):
        # 重建待办勾选
        while self._check_v.count():
            item = self._check_v.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._check_vars = []
        script = self._selected_script()
        if not script:
            return
        self._rescan(quick=True)
        items = script.get("setup_checklist") or []
        if items:
            lab = QLabel("脚本侧待办（勾选表示你已在脚本里完成）")
            lab.setFont(theme.font(self.main.settings, 11, True))
            self._check_v.addWidget(lab)
            t = _theme_of(self.main.settings)
            for item in items:
                cb = QCheckBox(item)
                cb.setFont(theme.font(self.main.settings, 10))
                self._check_vars.append((item, cb))
                self._check_v.addWidget(cb)

    def _apply_custom_mode(self, is_custom):
        for w in self._normal_widgets:
            w.setVisible(not is_custom)
        self._save_row.setVisible(not is_custom)
        self._custom_frame.setVisible(is_custom)

    # ---------------- 探测 ----------------
    def _rescan(self, quick=False):
        script = self._selected_script()
        if not script:
            return
        if quick:
            # 快速检测:仅缓存 + 预设提示路径,不搜索
            roots = pr.narrow_search_roots(glue.BASE_DIR, self.main.settings)
            path, src = pr.resolve_launcher(script, self.main.settings, roots, allow_glob=False)
            candidates = [path] if path else []
            self._apply_scan_result(candidates, "glob" if candidates else "none", timed_out=False)
            return

        self._scan_token += 1
        token = self._scan_token
        self._set_status("正在搜索路径…", "sub")
        self._fill_candidates([])

        settings = self.main.settings

        def worker():
            roots = pr.default_search_roots(glue.BASE_DIR, settings)
            deadline_at = time.monotonic() + 10
            candidates = pr.resolve_all_candidates(script, roots, max_results=8,
                                                   timeout_sec=10, settings=settings)
            timed_out = time.monotonic() >= deadline_at
            self.scan_done.emit(token, candidates, timed_out)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self, token, candidates, timed_out):
        if token != self._scan_token:
            return
        self._apply_scan_result(candidates, "glob" if candidates else "none",
                                timed_out=timed_out)

    def _apply_scan_result(self, candidates, src, timed_out=False):
        """candidates: 0/1/多 个路径;src: cache|hint|glob|none;timed_out: 是否深度探测超时。"""
        self._fill_candidates(candidates)
        n = len(candidates)
        if n == 0:
            self._path_edit.clear()
            if timed_out:
                self._set_status("搜索超过 10 秒未找到，请点「浏览…」手动选择", "warn")
            else:
                self._set_status("未找到，请点「浏览…」或「重新探测」", "warn")
            return

        # 有结果:把第一个填入输入框
        self._path_edit.setText(candidates[0])

        if n == 1:
            labels = {
                "cache": "来自上次记录",
                "hint": "来自预设路径",
                "glob": "自动搜索到",
            }
            msg = labels.get(src, "已找到")
            if timed_out:
                msg = "已找到 1 个（搜索超时中止，若不对可点「浏览…」）"
            self._set_status(msg, "ok")
            return

        # 多候选:第一个默认已填,其余在列表里让用户挑
        prefix = "找到 %d 个可能路径，" % n
        if timed_out:
            prefix += "（搜索超时中止）"
        self._set_status(prefix + "已默认使用第 1 个；如果不对可点下方列表切换或「浏览…」。", "ok")

    def _fill_candidates(self, paths):
        self._candidates.clear()
        for i, path in enumerate(paths, start=1):
            item = QListWidgetItem("%d.   %s" % (i, path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self._candidates.addItem(item)
        self._candidates.setVisible(bool(paths))

    def _pick_candidate(self, path):
        if not path:
            return
        self._path_edit.setText(path)
        self._set_status("已选择：%s" % path, "ok")

    def _set_status(self, text, color_kind=None):
        t = _theme_of(self.main.settings)
        self._status.setText(text)
        color = {"ok": t["ok"], "warn": t["warn"], "sub": t["sub"]}.get(color_kind, t["sub"])
        self._status.setStyleSheet("color: %s;" % color)

    def _browse(self):
        path, _f = QFileDialog.getOpenFileName(
            self, "选择脚本/启动器程序", "",
            "可执行程序 (*.exe);;所有文件 (*.*)")
        if path:
            self._path_edit.setText(os.path.normpath(path))
            self._set_status("手动选择", "ok")

    # ---------------- 粘贴填充(add) ----------------
    def _open_quick_fill(self):
        d = dlg.QuickFillDialog(self, "add", None)
        d.applied.connect(self._apply_parsed_to_add)
        d.confirmed.connect(self._on_quick_fill_confirm)
        d.exec()

    def _on_quick_fill_confirm(self, parsed):
        self._apply_parsed_to_add(parsed)
        self._save_add()

    def _apply_parsed_to_add(self, parsed):
        """照 _apply_parsed_to_add:1595 语义:记录覆盖字段 + 就地下拉/路径/待办。"""
        self._fill_overrides = {}
        for k in ("name", "args", "wait_mode", "game_processes", "helper_processes",
                  "start_timeout_min", "notes", "doc_url",
                  "pre_launcher", "pre_args", "pre_delay_sec",
                  "log_file", "log_encoding", "daily_done_patterns",
                  "daily_pending_patterns", "stamina_patterns"):
            if k in parsed:
                self._fill_overrides[k] = parsed[k]

        if "game" in parsed:
            target = parsed["game"].strip()
            for g in self._games:
                gname = g.get("name", "")
                if gname == target or target in gname or gname in target:
                    gi = self._game_combo.findText(gname)
                    if gi >= 0:
                        self._game_combo.setCurrentIndex(gi)
                    break
            self._on_game_change()

        if "script" in parsed:
            target = parsed["script"].strip()
            game = self._selected_game()
            if game:
                for sc in game.get("scripts", []):
                    sname = sc.get("name", "")
                    if sname == target or target in sname or sname in target:
                        si = self._script_combo.findText(sname)
                        if si >= 0:
                            self._script_combo.setCurrentIndex(si)
                        break
            self._on_script_change()

        if "launcher" in parsed:
            self._path_edit.setText(parsed["launcher"])
            self._set_status("来自粘贴填充", "ok")

        if "checklist_done" in parsed:
            done = set(parsed["checklist_done"])
            for item, var in self._check_vars:
                var.setChecked(item in done)

    # ---------------- 保存 ----------------
    def _save_add(self):
        game = self._selected_game()
        script = self._selected_script()
        if not game or not script:
            dlg.showwarning(self, "提示", "请选择游戏与脚本。")
            return
        launcher = self._path_edit.text().strip().strip('"')
        if script.get("id") != "manual" and (not launcher or not os.path.isfile(launcher)):
            if not dlg.askyesno(self, "路径无效",
                                "找不到有效的启动器路径，保存后运行时会被跳过。\n仍要保存吗？"):
                return
        done = [item for item, var in self._check_vars if var.isChecked()]
        plugin = pc.build_plugin(game, script, launcher, checklist_done=done)
        for k, v in self._fill_overrides.items():
            if k != "checklist_done":
                plugin[k] = v
        pc.save_plugin_file(plugin)
        sid = script.get("id", "")
        if launcher and sid and sid != "manual":
            pr.update_path_cache(self.main.settings, sid, launcher)
            glue.save_settings(self.main.settings)
        self.main.reload_and_render()
        if script.get("id") == "manual":
            self.main.open_edit(plugin)
        else:
            self.main.go("home")

    # ---------------- custom 分支 ----------------
    def _custom_use_reference(self):
        label = self._custom_ref_combo.currentText()
        pair = self._custom_ref_map.get(label)
        if not pair:
            dlg.showwarning(self, "提示", "请先选择一个参考预设。")
            return
        game, script = pair
        # 用该脚本 build 一份新插件,但清空启动器和 preset_id,让用户当作自己的模板
        plugin = pc.build_plugin(game, script, "", order=pc.next_plugin_order())
        plugin["name"] = "自定义 · 基于 " + plugin.get("name", "")
        plugin["preset_id"] = ""
        plugin["preset_game_id"] = ""
        pc.save_plugin_file(plugin)
        self.main.reload_and_render()
        self.main.open_edit(plugin)

    def _custom_use_blank(self):
        catalog = pc.load_catalog()
        game = pc.get_game(catalog, "custom")
        script = pc.get_script(game, "manual") if game else None
        if not game or not script:
            dlg.showwarning(self, "提示", "预设目录缺少 custom/manual 项。")
            return
        plugin = pc.build_plugin(game, script, "", order=pc.next_plugin_order())
        pc.save_plugin_file(plugin)
        self.main.reload_and_render()
        self.main.open_edit(plugin)
