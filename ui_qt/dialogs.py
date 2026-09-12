# -*- coding: utf-8 -*-
"""对话框:粘贴快速填充 + 通用消息框封装(移植 _open_quick_fill_dialog:1416)。

QuickFillDialog:
    左侧粘贴文本区,右侧说明文案;解析成功后把 fields 发给页面:
    - 「仅填充」   → applied(fields)   页面只把 fields 填进表单
    - 「确认并保存」→ confirmed(fields)  页面填表并触发保存(照旧 on_confirm_save)
    - applied = Signal(dict) 为契约签名;confirmed 为新增信号用于区分保存语义。
"""
import quick_fill as qf

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)


class QuickFillDialog(QDialog):
    applied = Signal(dict)    # 「仅填充」:解析出的 fields
    confirmed = Signal(dict)  # 「确认并保存」:解析出的 fields(页面需同时触发保存)

    def __init__(self, parent, mode: str, plugin=None):
        super().__init__(parent)
        self.mode = mode
        self.plugin = plugin
        self.setWindowTitle("粘贴快速填充")
        self.setModal(True)
        self.resize(680, 600)
        self.setMinimumSize(520, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(8)

        # 头部标题
        title = QLabel("粘贴快速填充")
        title.setStyleSheet("font-size: 17px; font-weight: bold;")
        root.addWidget(title)

        # 中部:左粘贴区 + 右说明
        mid = QHBoxLayout()
        mid.setSpacing(10)
        root.addLayout(mid, 1)

        self.text = QTextEdit()
        self.text.setAcceptRichText(False)
        if mode == "edit" and plugin:
            self.text.setPlainText(qf.export_plugin_to_text(plugin))
        else:
            self.text.setPlainText(qf.SAMPLE_QUICK_FILL)
        mid.addWidget(self.text, 1)

        tip_panel = QFrame()
        tip_layout = QVBoxLayout(tip_panel)
        tip_layout.setContentsMargins(10, 8, 10, 8)
        tip_layout.setSpacing(8)
        tip1 = QLabel("每行「键: 值」；点「确认并保存」写入表单并保存到 plugins。\n"
                      "Ctrl+Enter 快捷保存。")
        tip1.setWordWrap(True)
        tip_layout.addWidget(tip1)
        tip2 = QLabel("支持：名称、游戏、脚本、启动器、参数、等待模式、"
                      "游戏进程、助手进程、超时、文档、备注、待办完成")
        tip2.setWordWrap(True)
        tip_layout.addWidget(tip2)
        tip_layout.addStretch(1)
        mid.addWidget(tip_panel)

        # 底部按钮
        footer = QFrame()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 12, 14, 12)
        btn_sample = QPushButton("填入样例")
        btn_sample.clicked.connect(self._fill_sample)
        fl.addWidget(btn_sample)
        if mode == "edit" and plugin:
            btn_restore = QPushButton("恢复为当前")
            btn_restore.clicked.connect(self._restore_current)
            fl.addWidget(btn_restore)
        fl.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        fl.addWidget(btn_cancel)
        btn_fill = QPushButton("仅填充")
        btn_fill.clicked.connect(self._fill_only)
        fl.addWidget(btn_fill)
        btn_save = QPushButton("确认并保存")
        btn_save.setProperty("class", "accent")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._confirm_save)
        fl.addWidget(btn_save)
        root.addWidget(footer)

        # 快捷键:Ctrl+Enter 确认并保存;Escape 由 QDialog 默认触发 reject
        QShortcut(QKeySequence("Ctrl+Return"), self, self._confirm_save)
        self.text.setFocus()

    # ---- 内部 ----
    def _parse_or_warn(self):
        """解析文本;出错弹窗并返回 None。"""
        parsed, err = qf.parse_quick_fill(self.text.toPlainText())
        if err:
            QMessageBox.warning(self, "格式错误", err)
            return None
        return parsed

    def _fill_sample(self):
        self.text.setPlainText(qf.SAMPLE_QUICK_FILL)

    def _restore_current(self):
        if self.mode == "edit" and self.plugin:
            self.text.setPlainText(qf.export_plugin_to_text(self.plugin))
        else:
            self.text.setPlainText(qf.SAMPLE_QUICK_FILL)

    def _fill_only(self):
        parsed = self._parse_or_warn()
        if parsed is None:
            return
        self.applied.emit(parsed)
        self.accept()

    def _confirm_save(self):
        parsed = self._parse_or_warn()
        if parsed is None:
            return
        self.confirmed.emit(parsed)
        self.accept()


class ScheduleCountdownDialog(QDialog):
    """定时任务到点确认框:防止挂机时突然开跑的最后确认。

    - 点「立即运行」或倒计时归零 → accept()（开始执行本次定时任务）
    - 点「跳过本次」或按 Esc      → reject()（本次不运行，明天再询问）
    """

    def __init__(self, parent, time_text: str, countdown_sec: int, plugin_names):
        super().__init__(parent)
        self.setWindowTitle("定时任务确认")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._remaining = max(1, int(countdown_sec))

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)

        title = QLabel("定时任务 · 每天 %s" % time_text)
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        info = QLabel("到点了！即将开始运行串行队列（共 %d 个游戏）：\n%s"
                      % (len(plugin_names), "、".join(plugin_names)))
        info.setWordWrap(True)
        root.addWidget(info)

        # 大字倒计时(到 0 自动开始)
        self._count_lbl = QLabel()
        self._count_lbl.setAlignment(Qt.AlignCenter)
        self._count_lbl.setStyleSheet("font-size: 30px; font-weight: bold;")
        root.addWidget(self._count_lbl)
        self._refresh_count()

        tip = QLabel("不想现在跑就点「跳过本次」；什么都不做则倒计时结束后自动开始。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: %s;" % self._sub_color())
        root.addWidget(tip)

        footer = QHBoxLayout()
        footer.addStretch(1)
        btn_skip = QPushButton("跳过本次")
        btn_skip.clicked.connect(self.reject)
        footer.addWidget(btn_skip)
        btn_run = QPushButton("▶ 立即运行")
        btn_run.setProperty("class", "accent")
        btn_run.setDefault(True)
        btn_run.clicked.connect(self.accept)
        footer.addWidget(btn_run)
        root.addLayout(footer)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- 内部 ----
    def _sub_color(self):
        """取当前主题的次要文字色(取不到就回退灰色)。"""
        try:
            from ui_qt import theme
            name = getattr(self.parent(), "settings", {}).get(
                "theme", theme.DEFAULT_THEME)
            return theme.THEMES.get(name, theme.THEMES[theme.DEFAULT_THEME])["sub"]
        except Exception:
            return "#8b8b93"

    def _refresh_count(self):
        self._count_lbl.setText("%d 秒后自动开始" % self._remaining)

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.accept()
            return
        self._refresh_count()


# ---------------- 通用消息框封装(签名见桩) ----------------
def askyesno(parent, title: str, text: str) -> bool:
    btn = QMessageBox.question(
        parent, title, text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No)
    return btn == QMessageBox.StandardButton.Yes


def showinfo(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def showwarning(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def showerror(parent, title: str, text: str) -> None:
    QMessageBox.critical(parent, title, text)
