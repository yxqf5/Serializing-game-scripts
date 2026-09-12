# -*- coding: utf-8 -*-
"""部署向导:移植 build_first_run:2320 全套(进度/根目录/每游戏卡片/一键配置/导入/扫描/备份)。

耗时操作(一键配置/深度扫描/导入/还原备份/一键导入四套)一律 threading.Thread + Signal。
"""
import os
import threading

import assistant_setup
import preset_catalog as pc
import preset_resolver as pr
import runner_core

import ui_qt.core_glue as glue
import ui_qt.dialogs as dlg
from ui_qt import theme

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


def _theme_of(settings):
    return theme.THEMES.get(settings.get("theme")) or theme.THEMES[theme.DEFAULT_THEME]


class WizardPage(QWidget):
    # 一键配置完成:preset_id, 结果 dict
    _setup_done = Signal(str, dict)
    # 深度扫描完成:token, preset_id, 候选列表
    _scan_done = Signal(int, str, list)
    # 导入单游戏完成:game_id, script_id, plugin|None, 错误信息
    _import_done = Signal(str, str, object, str)
    # 还原备份完成:preset_id, 还原文件列表, 备份名, 错误信息
    _restore_done = Signal(str, list, str, str)
    # 一键导入常用四套完成
    _defaults_done = Signal()

    def __init__(self, main):
        super().__init__()
        self.main = main
        self._wizard_result = {}     # preset_id → 一键配置结果回显
        self._scan_token = 0
        self._importing = False
        self._setting_up = False
        self._restoring = False

        self._build_shell()

        self._setup_done.connect(self._on_setup_done)
        self._scan_done.connect(self._on_scan_done)
        self._import_done.connect(self._on_import_done)
        self._restore_done.connect(self._on_restore_done)
        self._defaults_done.connect(self._on_defaults_done)

        self.refresh()

    # ---------------- 外壳(静态) ----------------
    def _build_shell(self):
        s = self.main.settings
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部标题 + 说明(静态)
        head = QWidget()
        hv = QVBoxLayout(head)
        hv.setContentsMargins(26, 28, 26, 10)
        hv.setSpacing(8)
        title = QLabel("部署向导")
        title.setFont(theme.font(s, 22, True))
        hv.addWidget(title)
        intro = QLabel("把多个游戏的自动脚本排队运行：一次只跑一个，跑完自动切换下一个。"
                       "按下面卡片逐款完成：官方下载安装 → 导入 → 一键配置，绿勾即就绪。")
        intro.setFont(theme.font(s, 11))
        intro.setWordWrap(True)
        hv.addWidget(intro)
        self._admin_note = QLabel("")
        self._admin_note.setFont(theme.font(s, 10, True))
        hv.addWidget(self._admin_note)
        root.addWidget(head)

        # 卡片滚动区(refresh() 重建)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(scroll, 1)
        self._scroll = scroll

        # 底部按钮
        bf = QWidget()
        bl = QHBoxLayout(bf)
        bl.setContentsMargins(26, 12, 26, 20)
        finish = QPushButton("进入主页")
        finish.setProperty("class", "accent")
        finish.clicked.connect(self._first_run_finish)
        bl.addWidget(finish)
        bl.addWidget(self._chip("一键导入常用四套", self._first_run_import))
        bl.addWidget(self._chip("打开使用帮助", lambda: self.main.go("help")))
        bl.addStretch(1)
        root.addWidget(bf)

    def _chip(self, text, cmd):
        b = QPushButton(text)
        b.setFont(theme.font(self.main.settings, 9))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(cmd)
        return b

    def _hint(self, text):
        t = _theme_of(self.main.settings)
        lab = QLabel(text)
        lab.setFont(theme.font(self.main.settings, 9))
        lab.setStyleSheet("color: %s; border: none;" % t["sub"])
        lab.setWordWrap(True)
        return lab

    def _panel_card(self, title="", status_text="", status_color=None):
        """向导卡片:标题 + 右侧状态徽标,返回内容容器。"""
        t = _theme_of(self.main.settings)
        box = QFrame()
        box.setStyleSheet("QFrame { background: %s; border: 1px solid %s; }"
                          % (t["panel"], t["line"]))
        v = QVBoxLayout(box)
        v.setContentsMargins(20, 8, 20, 10)
        v.setSpacing(4)
        if title:
            top = QHBoxLayout()
            title_lbl = QLabel(title)
            title_lbl.setFont(theme.font(self.main.settings, 13, True))
            title_lbl.setStyleSheet("border: none;")
            top.addWidget(title_lbl)
            top.addStretch(1)
            if status_text:
                st = QLabel(status_text)
                st.setFont(theme.font(self.main.settings, 10, True))
                st.setStyleSheet("border: none; color: %s;" % (status_color or t["sub"]))
                top.addWidget(st)
            v.addLayout(top)
        return box, v

    # ---------------- 重建(refresh) ----------------
    def refresh(self) -> None:
        s = self.main.settings
        t = _theme_of(s)

        # 管理员检测说明(照旧文案)
        try:
            admin = runner_core.is_admin()
        except Exception:
            admin = False
        if admin:
            self._admin_note.setText("● 管理员模式")
            self._admin_note.setStyleSheet("color: %s;" % t["ok"])
        else:
            self._admin_note.setText("● 非管理员 · 非管理员模式，部分脚本可能启动失败")
            self._admin_note.setStyleSheet("color: %s;" % t["warn"])

        # 重建卡片容器
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        inner = QWidget()
        self._scroll.setWidget(inner)
        v = QVBoxLayout(inner)
        v.setContentsMargins(26, 0, 26, 8)
        v.setSpacing(6)

        try:
            games = pc.list_games(pc.load_catalog())
        except Exception:
            games = []

        # 就绪进度总览
        plugins = getattr(self.main, "plugins", None)
        if plugins is None:
            plugins = glue.load_plugins()
        imported = [g for g in games if self._plugin_for_game(g, plugins)]
        ready = [g for g in imported
                 if self._plugin_ready(self._plugin_for_game(g, plugins))]
        prog, pv = self._panel_card("部署进度")
        if imported:
            bar = QProgressBar()
            bar.setRange(0, max(1, len(imported)))
            bar.setValue(len(ready))
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            pv.addWidget(bar)
            note = "" if len(games) <= len(imported) else \
                "，还有 %d 款未导入" % (len(games) - len(imported))
            status = QLabel("已就绪 %d / %d 款已导入的助手%s" % (
                len(ready), len(imported), note))
            status.setFont(theme.font(s, 11, True))
            status.setStyleSheet("border: none; color: %s;"
                                 % (t["ok"] if len(ready) == len(imported) else t["fg"]))
            pv.addWidget(status)
        else:
            tip = QLabel("还没有导入任何助手 —— 先点卡片上的「官方下载」安装，再点「导入此游戏」。")
            tip.setFont(theme.font(s, 11, True))
            tip.setStyleSheet("border: none; color: %s;" % t["warn"])
            tip.setWordWrap(True)
            pv.addWidget(tip)
        v.addWidget(prog)

        # 助手安装根目录（可选，提高自动搜索命中率）
        rootbox, rv = self._panel_card("助手安装根目录（可选）")
        rv.addWidget(self._hint("如果几款助手都装在同一个文件夹，指定它，自动搜索路径会更准更快。"))
        erow = QHBoxLayout()
        root_dir = pr.get_assistants_root(s)
        self._root_edit = QLineEdit(root_dir)
        self._root_edit.setReadOnly(True)
        erow.addWidget(self._root_edit, 1)
        erow.addWidget(self._chip("浏览…", self._pick_root))
        if root_dir:
            erow.addWidget(self._chip("清除", self._clear_root))
        rv.addLayout(erow)
        v.addWidget(rootbox)

        # 每款游戏一张卡片
        for g in games:
            v.addWidget(self._game_card(g, plugins))

        disclaimer = QLabel("使用即表示您已阅读并同意免责声明（见「使用帮助」或 DISCLAIMER.md）。")
        disclaimer.setFont(theme.font(s, 9))
        disclaimer.setStyleSheet("color: %s;" % t["warn"])
        disclaimer.setWordWrap(True)
        v.addWidget(disclaimer)
        v.addStretch(1)

    # ---------------- 数据 ----------------
    def _plugin_for_game(self, game, plugins=None):
        if plugins is None:
            plugins = getattr(self.main, "plugins", []) or []
        gid = game.get("id", "")
        for p in plugins:
            if p.get("preset_game_id", "") == gid:
                return p
        return None

    def _plugin_ready(self, p, checks=None):
        if not p:
            return False
        launcher = p.get("launcher", "")
        if not launcher or not os.path.isfile(launcher):
            return False
        if checks is None:
            checks = assistant_setup.verify_for_plugin(p)
        return bool(checks) and all(c.get("ok") for c in checks)

    def _open_url(self, url):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _log_line(self, text, level="info"):
        try:
            self.main.append_log(text, level)
        except Exception:
            print(text)

    # ---------------- 每游戏卡片(照 _wizard_game_card:2441) ----------------
    def _game_card(self, game, plugins=None):
        s = self.main.settings
        t = _theme_of(s)
        gname = game.get("name", "")
        scripts = game.get("scripts", [])
        sname = scripts[0].get("name", "") if scripts else ""
        p = self._plugin_for_game(game, plugins)
        title = ("%s · %s" % (gname, sname)) if sname else gname

        if p is None:
            card, v = self._panel_card(title, "未导入", t["sub"])
            tip = QLabel("还没使用这款脚本？点「官方下载」安装好后再点「导入此游戏」。")
            tip.setFont(theme.font(s, 10))
            tip.setStyleSheet("border: none; color: %s;" % t["sub"])
            tip.setWordWrap(True)
            v.addWidget(tip)
            btns = QHBoxLayout()
            v.addLayout(btns)
            import_btn = QPushButton("导入此游戏并检测路径")
            import_btn.setProperty("class", "accent")
            import_btn.clicked.connect(lambda _=False, g=game: self._import_game(g))
            btns.addWidget(import_btn)
            self._dl_buttons(btns, game, first_padx=10)
            return card

        launcher_ok = bool(p.get("launcher")) and os.path.isfile(p.get("launcher", ""))
        supported = p.get("preset_id", "") in assistant_setup.SUPPORTED_PRESET_IDS
        checks = assistant_setup.verify_for_plugin(p) if launcher_ok else []
        ready = self._plugin_ready(p, checks)
        status = "✓ 就绪" if ready else ("待设置路径" if not launcher_ok else "待配置")
        color = t["ok"] if ready else (t["warn"] if launcher_ok else t["err"])
        card, v = self._panel_card(title, status, color)

        if launcher_ok and checks:
            for c in checks:
                row = QHBoxLayout()
                row.setSpacing(6)
                mark = QLabel("✓" if c.get("ok") else "△")
                mark.setFont(theme.font(s, 10, True))
                mark.setStyleSheet("border: none; color: %s;"
                                   % (t["ok"] if c.get("ok") else t["warn"]))
                row.addWidget(mark)
                name_lbl = QLabel(c.get("name", ""))
                name_lbl.setFont(theme.font(s, 10))
                name_lbl.setStyleSheet("border: none;")
                row.addWidget(name_lbl)
                if c.get("hint"):
                    hint = QLabel("（%s）" % c["hint"])
                    hint.setFont(theme.font(s, 9))
                    hint.setStyleSheet("border: none; color: %s;" % t["sub"])
                    hint.setWordWrap(True)
                    row.addWidget(hint)
                row.addStretch(1)
                v.addLayout(row)
        elif not launcher_ok:
            tip = QLabel("还没找到启动器程序 —— 先安装助手，再点「重新检测」；"
                         "装在冷门位置就点「浏览…」手动指定。")
            tip.setFont(theme.font(s, 10))
            tip.setStyleSheet("border: none; color: %s;" % t["sub"])
            tip.setWordWrap(True)
            v.addWidget(tip)

        # 一键配置后的结果回显
        res = self._wizard_result.get(p.get("preset_id", ""))
        if res:
            if res.get("applied"):
                lab = QLabel("✓ 已自动写入：%s" % "、".join(res["applied"]))
                lab.setFont(theme.font(s, 10))
                lab.setStyleSheet("border: none; color: %s;" % t["ok"])
                lab.setWordWrap(True)
                v.addWidget(lab)
            if res.get("error"):
                lab = QLabel(res["error"])
                lab.setFont(theme.font(s, 10))
                lab.setStyleSheet("border: none; color: %s;" % t["err"])
                lab.setWordWrap(True)
                v.addWidget(lab)
            for m in res.get("manual") or []:
                lab = QLabel("△ 还需人工：%s" % m)
                lab.setFont(theme.font(s, 10))
                lab.setStyleSheet("border: none; color: %s;" % t["warn"])
                lab.setWordWrap(True)
                v.addWidget(lab)

        btns = QHBoxLayout()
        v.addLayout(btns)
        if launcher_ok and supported:
            setup_btn = QPushButton("一键配置")
            setup_btn.setProperty("class", "accent")
            setup_btn.clicked.connect(lambda _=False, pl=p: self._apply_setup(pl))
            btns.addWidget(setup_btn)
        if launcher_ok:
            btns.addWidget(self._chip("重新检测", lambda _=False, pl=p: self._rescan(pl)))
            btns.addSpacing(8)
            btns.addWidget(self._chip("浏览…", lambda _=False, pl=p: self._browse(pl)))
            btns.addSpacing(6)
            btns.addWidget(self._chip("编辑", lambda _=False, pl=p: self.main.open_edit(pl)))
            btns.addSpacing(6)
            if assistant_setup.list_backups(p.get("preset_id", "")):
                btns.addWidget(self._chip("还原备份", lambda _=False, pl=p: self._restore(pl)))
        self._dl_buttons(btns, game, first_padx=8)
        return card

    def _dl_buttons(self, layout, game, first_padx=8):
        """「↗ 官方下载」「使用文档」按钮组(照 _wizard_dl_buttons:2515)。"""
        dl = game.get("download_url") or game.get("doc_url")
        if first_padx:
            layout.addSpacing(first_padx)
        if dl:
            layout.addWidget(self._chip("↗ 官方下载", lambda _=False, u=dl: self._open_url(u)))
        doc = game.get("doc_url")
        if doc and doc != dl:
            layout.addSpacing(6)
            layout.addWidget(self._chip("使用文档", lambda _=False, u=doc: self._open_url(u)))
        layout.addStretch(1)

    # ---------------- 导入单游戏(线程) ----------------
    def _import_game(self, game):
        if self._importing:
            return
        gid = game.get("id", "")
        scripts = game.get("scripts", [])
        sid = scripts[0].get("id", "") if scripts else ""
        self._importing = True
        settings = self.main.settings

        def worker():
            try:
                plugin = pc.resolve_and_build(gid, sid, settings)
                err = ""
            except Exception as e:
                plugin = None
                err = str(e)
            self._import_done.emit(gid, sid, plugin, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_import_done(self, gid, sid, plugin, err):
        self._importing = False
        if err:
            dlg.showerror(self, "导入失败", err)
            return
        if plugin is None:
            return
        if not plugin.get("launcher"):
            game_name = plugin.get("name", gid)
            go_on = dlg.askyesno(
                self, "未找到启动器",
                "没有自动找到 %s 的启动器。\n\n已安装好了？点「是」手动选择启动器程序；\n"
                "还没安装？点「否」，先点「官方下载」安装后再来导入。" % game_name)
            if not go_on:
                return
            override, _f = QFileDialog.getOpenFileName(self, "选择启动器程序（exe）")
            if not override:
                return
            try:
                plugin = pc.resolve_and_build(gid, sid, self.main.settings,
                                              launcher_override=override)
            except Exception as e:
                dlg.showerror(self, "导入失败", str(e))
                return
        pc.save_plugin_file(plugin)
        if plugin.get("launcher"):
            pr.update_path_cache(self.main.settings, sid, plugin.get("launcher"))
            glue.save_settings(self.main.settings)
        self.main.reload_and_render()
        self.refresh()

    # ---------------- 一键配置(线程,照 _wizard_apply_setup:2558) ----------------
    def _apply_setup(self, plugin):
        if self._setting_up:
            return
        pid = plugin.get("preset_id", "")
        self._setting_up = True

        def worker():
            r = assistant_setup.apply_for_plugin(plugin)
            self._setup_done.emit(pid, r)

        threading.Thread(target=worker, daemon=True).start()

    def _on_setup_done(self, pid, r):
        self._setting_up = False
        self._wizard_result[pid] = r
        if r.get("ok") and r.get("applied"):
            # 找到插件名写日志
            name = pid
            for p in getattr(self.main, "plugins", []) or []:
                if p.get("preset_id", "") == pid:
                    name = p.get("name", pid)
                    break
            self._log_line("「%s」已写入推荐配置：%s" % (name, "、".join(r["applied"])), level="info")
        # 重建卡片 → verify_for_plugin 重新显示检查结果
        self.refresh()

    # ---------------- 重新检测(线程,照 _wizard_rescan:2568) ----------------
    def _rescan(self, plugin):
        pid = plugin.get("preset_id", "")
        script = None
        try:
            script = pc.find_script_by_preset_id(pc.load_catalog(), pid)[1]
        except Exception:
            script = None
        if not script:
            dlg.showinfo(self, "重新检测", "没有这款脚本的预设信息，请点「浏览…」手动指定。")
            return
        self._scan_token += 1
        token = self._scan_token
        settings = self.main.settings

        def worker():
            roots = pr.default_search_roots(glue.BASE_DIR, settings)
            candidates = pr.resolve_all_candidates(script, roots, max_results=5,
                                                   timeout_sec=10, settings=settings)
            self._scan_done.emit(token, pid, candidates)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self, token, pid, candidates):
        """照 _wizard_apply_scan:2590:命中即写入插件并缓存。"""
        if token != self._scan_token:
            return
        p = None
        for x in getattr(self.main, "plugins", []) or []:
            if x.get("preset_id", "") == pid:
                p = x
                break
        if not p:
            return
        if candidates:
            path = os.path.normpath(candidates[0])
            p["launcher"] = path
            glue.save_plugin(p)
            pr.update_path_cache(self.main.settings, pid, path)
            glue.save_settings(self.main.settings)
            self.main.reload_and_render()
            self._log_line("「%s」已自动定位启动器：%s" % (p.get("name", ""), path), level="info")
        else:
            dlg.showinfo(
                self, "未找到启动器",
                "自动搜索没有找到「%s」的启动器。\n\n"
                "确认已安装后，点「浏览…」手动选择安装目录里的启动器程序；\n"
                "或者先在上方设置「助手安装根目录」再重新检测。" % p.get("name", ""))
            return
        self.refresh()

    # ---------------- 浏览(照 _wizard_browse:2615) ----------------
    def _browse(self, plugin):
        init = pr.get_assistants_root(self.main.settings)
        if not init or not os.path.isdir(init):
            cur = plugin.get("launcher", "") or ""
            d = os.path.dirname(cur)
            init = d if d and os.path.isdir(d) else glue.BASE_DIR
        picked, _f = QFileDialog.getOpenFileName(self, "选择启动器程序（exe）", init)
        if not picked:
            return
        plugin["launcher"] = os.path.normpath(picked)
        glue.save_plugin(plugin)
        pr.update_path_cache(self.main.settings, plugin.get("preset_id", ""), plugin["launcher"])
        glue.save_settings(self.main.settings)
        self.main.reload_and_render()
        self.refresh()

    # ---------------- 还原备份(线程,照 _wizard_restore:2632) ----------------
    def _restore(self, plugin):
        if self._restoring:
            return
        pid = plugin.get("preset_id", "")
        backups = assistant_setup.list_backups(pid)
        if not backups:
            dlg.showinfo(self, "还原备份", "没有可还原的备份。")
            return
        latest, name = backups[0]
        if not dlg.askyesno(
                self, "还原备份",
                "把「%s」的配置恢复到最近一次一键配置之前的备份？\n\n备份时间：%s\n当前配置会被覆盖。"
                % (plugin.get("name", ""), assistant_setup.backup_time_label(latest))):
            return
        self._restoring = True

        def worker():
            try:
                files = assistant_setup.restore_backup(latest)
                err = ""
            except Exception as e:
                files = []
                err = str(e)
            self._restore_done.emit(pid, files, name, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_restore_done(self, pid, files, name, err):
        self._restoring = False
        plugin = None
        for p in getattr(self.main, "plugins", []) or []:
            if p.get("preset_id", "") == pid:
                plugin = p
                break
        if err:
            dlg.showerror(self, "还原备份", err)
        elif files:
            dlg.showinfo(self, "还原备份",
                         "已还原 %d 个文件：\n%s" % (
                             len(files),
                             "\n".join(os.path.basename(f) for f in files)))
            if plugin is not None:
                self._log_line("「%s」已还原一键配置备份（%s）" % (plugin.get("name", ""), name),
                               level="info")
        else:
            dlg.showerror(self, "还原备份", "还原失败，请检查文件是否被占用。")
        self.refresh()

    # ---------------- 根目录 ----------------
    def _pick_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择助手安装根目录")
        if not d:
            return
        self.main.settings["assistants_root"] = os.path.normpath(d)
        glue.save_settings(self.main.settings)
        self.refresh()

    def _clear_root(self):
        self.main.settings["assistants_root"] = ""
        glue.save_settings(self.main.settings)
        self.refresh()

    # ---------------- 底部动作 ----------------
    def _first_run_import(self):
        if self._importing:
            return
        self._importing = True
        settings = self.main.settings

        def worker():
            try:
                pc.import_default_plugins(settings)
            except Exception:
                pass
            self._defaults_done.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _on_defaults_done(self):
        self._importing = False
        self.main.save_settings_soon()
        self.main.reload_and_render()
        self.refresh()

    def _first_run_finish(self):
        """照 _first_run_finish:2690:写 first_run_done → 回主页。"""
        self.main.settings["first_run_done"] = True
        self.main.save_settings_soon()
        self.main.go("home")
