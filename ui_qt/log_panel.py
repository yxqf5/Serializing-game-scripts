# -*- coding: utf-8 -*-
"""日志面板:运行日志展示/着色 + 工具栏(跟随/复制/清空/导出/目录/导入/专注)。

移植自 tkinter 版:_build_log_panel(650)/_render_log_store(2931)/_insert_log_batch(2946)/
_on_log_scroll(2976)/_update_log_toolbar(3000)/_flush_log_count(3013)/_copy_log(3020)/
_clear_log(3032)/_export_log(3041)/_open_log_dir(3144)/_import_log(3151)/
_show_log_viewer(3176)。
"""
import datetime
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QGuiApplication, QTextCharFormat, QTextCursor, QTextOption,
)
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ui_helpers import group_tagged_lines

import ui_qt.core_glue as glue
from ui_qt import theme

# 日志标签 → 主题配色键(照旧版 tag_configure)
_TAG_COLOR_KEYS = {
    "log_err": "err",
    "log_warn": "warn",
    "log_gold": "log_gold",
    "log_blue": "log_blue",
    "log_ok": "ok",
}


class LogPanel(QWidget):
    """主页下半部的日志面板。log_store 由主窗口创建并维护(全量可导出)。"""

    focus_requested = Signal(bool)   # 请求切换专注模式(True=进入)

    def __init__(self, main, log_store):
        super().__init__()
        self.main = main
        self.log_store = log_store
        self._log_follow = True       # 跟随最新(滚到底)
        self._focus_mode = False      # 专注模式状态(按钮文案)
        self._inserting = False       # 程序化插入期间不改跟随态(旧 _log_inserting)

        t = self._theme()
        settings = self._settings()

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 2)
        root.setSpacing(4)

        # ---- 工具栏(顺序照旧:跟随/复制/清空/导出/目录/导入/专注) ----
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.log_title_lbl = QLabel("运行日志")
        self.log_title_lbl.setFont(theme.font(settings, 13, True))
        hl.addWidget(self.log_title_lbl)
        self.log_count_lbl = QLabel("")
        self.log_count_lbl.setFont(theme.font(settings, 9))
        self.log_count_lbl.setStyleSheet("color:%s;" % t["sub"])
        hl.addWidget(self.log_count_lbl)
        hl.addStretch(1)

        self.log_follow_btn = QPushButton("● 跟随最新")
        self.log_follow_btn.setFont(theme.font(settings, 9))
        self.log_follow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_follow_btn.clicked.connect(self._resume_log_follow)
        hl.addWidget(self.log_follow_btn)

        self._copy_btn = self._tool_button("复制", self._copy_log)
        hl.addWidget(self._copy_btn)
        self._clear_btn = self._tool_button("清空", self._clear_log)
        hl.addWidget(self._clear_btn)
        self._export_btn = self._tool_button("导出", self._export_log)
        hl.addWidget(self._export_btn)
        self._dir_btn = self._tool_button("目录", self._open_log_dir)
        hl.addWidget(self._dir_btn)
        self._import_btn = self._tool_button("导入", self._import_log)
        hl.addWidget(self._import_btn)

        self.log_focus_btn = QPushButton("□ 专注")
        self.log_focus_btn.setFont(theme.font(settings, 9))
        self.log_focus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.log_focus_btn.clicked.connect(
            lambda: self.focus_requested.emit(not self._focus_mode))
        hl.addWidget(self.log_focus_btn)
        self._toolbar_btns = [
            self.log_follow_btn, self._copy_btn, self._clear_btn,
            self._export_btn, self._dir_btn, self._import_btn, self.log_focus_btn,
        ]
        root.addWidget(head)

        # ---- 日志正文:只读、自动折行、600 行上限 ----
        self.text_edit = QPlainTextEdit()
        self.text_edit.setObjectName("logview")
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(theme.font(settings, 10))
        self.text_edit.setMaximumBlockCount(glue.LOG_VIEW_LINES)
        self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text_edit.setWordWrapMode(QTextOption.WrapMode.WordWrap)  # 按词折行(旧 wrap="word")
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(self.text_edit, 1)

        # 滚动 → 跟随态(移植 _on_log_scroll 语义)
        sb = self.text_edit.verticalScrollBar()
        sb.rangeChanged.connect(self._on_log_range_changed)
        sb.valueChanged.connect(self._on_log_value_changed)

        # 行数标签 200ms 节流(旧 _update_log_toolbar/_flush_log_count)
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(200)
        self._count_timer.timeout.connect(self._flush_log_count)

        self.render_store()

    # ================= 主题 / 设置 =================
    def _settings(self) -> dict:
        return getattr(self.main, "settings", None) or {}

    def _theme(self) -> dict:
        name = self._settings().get("theme", theme.DEFAULT_THEME)
        return theme.THEMES.get(name, theme.THEMES[theme.DEFAULT_THEME])

    def _tool_button(self, text, slot):
        btn = QPushButton(text)
        btn.setFont(theme.font(self._settings(), 9))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _build_formats(self) -> dict:
        """当前主题的着色字符格式表。"""
        t = self._theme()
        formats = {}
        for tag, key in _TAG_COLOR_KEYS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(t[key]))
            formats[tag] = fmt
        return formats

    # ================= 展示 =================
    def append_lines(self, lines) -> None:
        """批量追加日志(分组着色插入,超 600 行由 maximumBlockCount 自动裁剪)。"""
        if not lines:
            self._update_log_toolbar()
            return
        formats = self._build_formats()
        self._inserting = True
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for tag, payload in group_tagged_lines(lines, glue.log_tag_for):
            fmt = formats.get(tag)
            if fmt is not None:
                cursor.insertText(payload, fmt)
            else:
                cursor.insertText(payload)
        self._inserting = False
        if self._log_follow:
            self._scroll_to_bottom()
        self._update_log_toolbar()

    def render_store(self) -> None:
        """清屏后重插 log_store 尾部 LOG_VIEW_LINES 行(主题切换/开跑前清屏用)。"""
        self.text_edit.setFont(theme.font(self._settings(), 10))
        self._inserting = True
        self.text_edit.clear()
        view = self.log_store.lines[-glue.LOG_VIEW_LINES:]
        formats = self._build_formats()
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for tag, payload in group_tagged_lines(view, glue.log_tag_for):
            fmt = formats.get(tag)
            if fmt is not None:
                cursor.insertText(payload, fmt)
            else:
                cursor.insertText(payload)
        self._inserting = False
        if self._log_follow:
            self._scroll_to_bottom()
        self._update_log_toolbar()
        self._flush_log_count()

    # ================= 滚动 / 跟随 =================
    def _scroll_to_bottom(self):
        sb = self.text_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_log_range_changed(self, minimum, maximum):
        """文档增高时若处于跟随态则自动滚底(旧 rangeChanged→see(end))。"""
        if self._log_follow and not self._inserting:
            self._scroll_to_bottom()

    def _on_log_value_changed(self, value):
        """用户滚动:是否仍在底部决定跟随态(旧 _on_log_scroll: last>=0.999)。"""
        if self._inserting:
            return
        sb = self.text_edit.verticalScrollBar()
        maximum = sb.maximum()
        at_bottom = maximum <= 0 or value >= maximum - 4
        if at_bottom != self._log_follow:
            self._log_follow = at_bottom
            self._update_log_toolbar()

    def _resume_log_follow(self):
        """点「跟随最新」恢复自动滚底。"""
        self._log_follow = True
        self._scroll_to_bottom()
        self._update_log_toolbar()

    # ================= 工具栏 =================
    def refresh_toolbar(self) -> None:
        """刷新跟随按钮文案/颜色、行数计数与各按钮字体(主题/字号变化后也走这里)。"""
        settings = self._settings()
        for btn in self._toolbar_btns:
            btn.setFont(theme.font(settings, 9))
        self.log_title_lbl.setFont(theme.font(settings, 13, True))
        self.log_count_lbl.setFont(theme.font(settings, 9))
        self._update_log_toolbar()
        self._flush_log_count()

    def set_focus_mode(self, on: bool) -> None:
        """专注模式状态同步(由 HomePage.set_log_focus 调用)。"""
        self._focus_mode = bool(on)
        self.log_focus_btn.setText("▣ 退出专注" if self._focus_mode else "□ 专注")

    def _update_log_toolbar(self):
        t = self._theme()
        text = "● 跟随最新" if self._log_follow else "○ 已暂停 · 跟随最新"
        self.log_follow_btn.setText(text)
        self.log_follow_btn.setStyleSheet(
            "color:%s;" % (t["ok"] if self._log_follow else t["warn"]))
        # 刷屏时节流:行数至多每 200ms 刷新一次(旧 _update_log_toolbar)
        if not self._count_timer.isActive():
            self._count_timer.start()

    def _flush_log_count(self):
        self.log_count_lbl.setText(self._count_text())

    def _count_text(self):
        dropped = self.log_store.dropped_total
        suffix = (" · 已丢弃较早 %d 行" % dropped) if dropped else ""
        return "%d 行%s" % (len(self.log_store.lines), suffix)

    # ================= 复制 / 清空 / 导出 / 目录 =================
    def _copy_log(self):
        """有选区复制选区,否则复制全部(export_text)。"""
        cursor = self.text_edit.textCursor()
        text = ""
        if cursor.hasSelection():
            text = cursor.selectedText().replace("\u2029", "\n")
        else:
            text = self.log_store.export_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    def _clear_log(self, confirm=True):
        if confirm and self.log_store.lines:
            answer = QMessageBox.question(
                self, "清空日志", "确定清空当前运行日志吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.log_store.clear()
        self._log_follow = True
        self.render_store()

    def _export_log(self):
        if not self.log_store.lines:
            QMessageBox.information(self, "导出日志", "当前没有可以导出的日志。")
            return
        default_name = "运行日志_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出运行日志", default_name,
            "文本文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
                f.write(self.log_store.export_text())
            QMessageBox.information(self, "导出完成", "日志已保存到：\n%s" % path)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _open_log_dir(self):
        try:
            os.makedirs(glue.LOG_DIR, exist_ok=True)
            os.startfile(glue.LOG_DIR)
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e))

    # ================= 导入 / 查看器 =================
    def _import_log(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入日志文件", "",
            "Markdown/日志 (*.md *.txt *.log);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            try:
                with open(path, "r", encoding="gbk", errors="replace") as f:
                    text = f.read()
            except OSError as e:
                QMessageBox.critical(self, "导入失败", str(e))
                return
        # 超大文件只保留尾部展示,避免查看窗口一次性插入卡死界面
        view_lines = text.splitlines()
        if len(view_lines) > 20000:
            view_lines = view_lines[-20000:]
            view_lines.insert(0, "⚠ 文件过大（共 %d 行），仅显示最后 20000 行。" % len(text.splitlines()))
            text = "\n".join(view_lines)
        self._show_log_viewer(os.path.basename(path), text)

    def _show_log_viewer(self, title, text):
        """独立只读窗口展示导入的日志,保留按级别的着色(旧 _show_log_viewer)。"""
        settings = self._settings()
        dlg = QDialog(self)
        dlg.setWindowTitle("日志查看 · %s" % title)
        dlg.resize(980, 640)
        dlg.setMinimumSize(640, 420)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setFont(theme.font(settings, 12, True))
        head.addWidget(title_lbl)
        head.addStretch(1)

        txt = QPlainTextEdit()
        txt.setObjectName("logview")
        txt.setReadOnly(True)
        txt.setFont(theme.font(settings, 12))
        txt.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoLineWrap)
        formats = self._build_formats()
        cursor = txt.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for tag, payload in group_tagged_lines(text.splitlines(), glue.log_tag_for):
            fmt = formats.get(tag)
            if fmt is not None:
                cursor.insertText(payload, fmt)
            else:
                cursor.insertText(payload)

        def copy_all():
            content = txt.toPlainText()
            if content:
                QGuiApplication.clipboard().setText(content)

        copy_btn = QPushButton("复制全部")
        copy_btn.setFont(theme.font(settings, 9))
        copy_btn.clicked.connect(copy_all)
        head.addWidget(copy_btn)
        close_btn = QPushButton("关闭")
        close_btn.setFont(theme.font(settings, 9))
        close_btn.clicked.connect(dlg.close)
        head.addWidget(close_btn)
        lay.addLayout(head)
        lay.addWidget(txt, 1)

        dlg.exec()
