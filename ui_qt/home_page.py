# -*- coding: utf-8 -*-
"""主页:队列卡片 + 状态汇总条 + 日志面板。

移植自 tkinter 版:build_home(600)/_render_cards(828)/_path_exists(844)/
_refresh_home_status(859)/_card_status(925)/_card(938)/_start_card_drag(1017)/
_move_card_drag(1032)/_drag_card_to(1059)/_finish_card_drag(1081)/
_toggle_log_focus(722)/_restore_home_sash(696)/_save_home_sash(710)。
"""
import os
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

import preset_catalog as pc
import runner_core
from ui_helpers import LogStore

from ui_qt import theme
from ui_qt.log_panel import LogPanel

PARALLEL_TIP = ("并行开关：开启后点「开始运行」时该任务立即与其它任务同时跑。\n"
                "适合 MAA 等模拟器／后台脚本；会抢真实鼠标的脚本（原神、绝区零等）别开。")


class _ElidedLabel(QLabel):
    """按可用宽度省略显示的单行文本(游戏名=尾部省略,路径=中间省略)。"""

    def __init__(self, text="", elide=Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._full = str(text or "")
        self._elide = elide
        self.setText(self._full)
        # 宽度由布局决定,不受自身文本 sizeHint 反馈影响,避免省略号抖动
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def setFullText(self, text):
        self._full = str(text or "")
        self._apply_elide()

    def fullText(self):
        return self._full

    def setElideMode(self, mode):
        self._elide = mode
        self._apply_elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self):
        fm = self.fontMetrics()
        width = max(0, self.width() - 2)
        if fm.horizontalAdvance(self._full) <= width:
            self.setText(self._full)
        else:
            self.setText(fm.elidedText(self._full, self._elide, width))


class _CardFrame(QFrame):
    """卡片容器:非按钮区域(标签/空白)按住即可拖动排序(旧 ≡ 手柄语义的放宽)。"""

    def __init__(self, home, parent=None):
        super().__init__(parent)
        self._home = home

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._home._start_card_drag(self):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._home._drag_active():
            self._home._move_card_drag()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._home._drag_active():
            self._home._finish_card_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class HomePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._cards = []              # 卡片引用列表(与显示顺序一致)
        self._path_cache = {}         # _path_exists 的 TTL 缓存 {path: (ok, monotonic)}
        self._drag_from = None        # 拖拽中的卡片下标(None=未拖拽)
        self._drag_widget = None      # 拖拽起始卡片(防止中途重建后误判)
        self._placeholder = None
        self._log_focus_mode = False  # 专注模式(隐藏队列区)
        self._restore_retries = 0

        # splitter 比例:home_log_ratio = 日志区高度占比(旧版语义),0.25~0.72
        ratio = (getattr(main, "settings", None) or {}).get("home_log_ratio", 0.40)
        try:
            ratio = min(0.72, max(0.25, float(ratio)))
        except Exception:
            ratio = 0.40
        self._home_log_ratio = ratio

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.queue_pane = self._build_queue_pane()
        self.queue_pane.setMinimumHeight(185)   # 旧版 minsize=185
        self.log_panel = LogPanel(main, self._get_log_store())
        self.log_panel.setMinimumHeight(190)    # 旧版 minsize=190
        self.splitter.addWidget(self.queue_pane)
        self.splitter.addWidget(self.log_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self.log_panel.focus_requested.connect(self.set_log_focus)
        root.addWidget(self.splitter)

        self.refresh_cards()

    def _get_log_store(self):
        """主窗口持有 LogStore;测试等场景下 main 没有时就地补一个。"""
        store = getattr(self.main, "log_store", None)
        if store is None:
            store = LogStore(10000)
            try:
                self.main.log_store = store
            except Exception:
                pass
        return store

    # ================= 主题 / 状态 =================
    def _settings(self) -> dict:
        return getattr(self.main, "settings", None) or {}

    def _theme(self) -> dict:
        name = self._settings().get("theme", theme.DEFAULT_THEME)
        return theme.THEMES.get(name, theme.THEMES[theme.DEFAULT_THEME])

    def _busy(self) -> bool:
        ctrl = getattr(self.main, "controller", None)
        if ctrl is None:
            return False
        return bool(getattr(ctrl, "running", False) or getattr(ctrl, "preflight_busy", False))

    def _save_settings_soon(self):
        save = getattr(self.main, "save_settings_soon", None)
        if callable(save):
            save()

    # ================= 界面构建 =================
    def _build_queue_pane(self):
        """队列区:标题行 + 状态汇总条 + 卡片滚动区。"""
        settings = self._settings()
        pane = QWidget()
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(6, 0, 6, 4)
        lay.setSpacing(6)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        self._title_lbl = QLabel("游戏队列")
        self._title_lbl.setFont(theme.font(settings, 18, True))
        hl.addWidget(self._title_lbl)
        hl.addStretch(1)
        self._refresh_btn = QPushButton("↻ 刷新")
        self._refresh_btn.setFont(theme.font(settings, 9))
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(lambda: self.main.reload_and_render())
        hl.addWidget(self._refresh_btn)
        self._add_btn = QPushButton("＋ 添加游戏")
        self._add_btn.setProperty("class", "accent")
        self._add_btn.setFont(theme.font(settings, 9, True))
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.clicked.connect(lambda: self.main.add_plugin())
        hl.addWidget(self._add_btn)
        lay.addWidget(head)

        # ---- 顶部状态条(常驻自检汇总) ----
        self._status_bar = QFrame()
        self._status_bar.setObjectName("homeStatus")
        self._status_inner = QHBoxLayout(self._status_bar)
        self._status_inner.setContentsMargins(12, 3, 12, 3)
        self._status_inner.setSpacing(0)
        lay.addWidget(self._status_bar)

        # ---- 卡片滚动区 ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self._cards_layout = QVBoxLayout(container)
        self._cards_layout.setContentsMargins(4, 2, 4, 4)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch(1)   # 卡片顶部对齐;拖拽 insertWidget 按 0..n-1 插
        self._scroll.setWidget(container)
        lay.addWidget(self._scroll, 1)
        return pane

    # ================= 状态汇总条 =================
    def refresh_status(self) -> None:
        """更新主页顶部状态条:就绪 / 待办 / 路径无效 / 管理员(旧 _refresh_home_status)。"""
        t = self._theme()
        self._status_bar.setStyleSheet(
            "#homeStatus { background:%s; border:1px solid %s; border-radius:4px; }"
            % (t["panel"], t["line"]))
        while self._status_inner.count():
            item = self._status_inner.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        active = [p for p in (self.main.plugins or []) if p.get("enabled", True)]
        total = len(active)
        ok_ct = bad_ct = pending_ct = 0
        bad_names, pending_names = [], []
        for p in active:
            launcher = p.get("launcher", "")
            if launcher and self._path_exists(launcher):
                ok_ct += 1
            else:
                bad_ct += 1
                bad_names.append(p.get("name", "?"))
            if pc.pending_checklist_count(p):
                pending_ct += 1
                pending_names.append(p.get("name", "?"))

        admin_ok = bool(runner_core.is_admin())

        # 无勾选状态
        if total == 0:
            self._chip("⚠ 尚未勾选任何游戏（每行左侧「开/关」切换）", t["warn"], 10)
            if not admin_ok:
                self._chip("  ·  非管理员模式，部分脚本可能启动失败", t["warn"], 9)
            return

        # 有勾选:三色分段
        def seg(text, fg):
            self._chip(text, fg, 10, bold=True)

        seg("🟢 %d 就绪" % ok_ct, t["ok"])
        if pending_ct:
            seg("🟡 %d 待办" % pending_ct, t["warn"])
        if bad_ct:
            seg("🔴 %d 路径无效" % bad_ct, t["err"])

        detail_bits = []
        if bad_ct:
            detail_bits.append("路径缺失：" + "、".join(bad_names[:3]) +
                               ("等" if bad_ct > 3 else ""))
        if pending_ct:
            detail_bits.append("待办未确认：" + "、".join(pending_names[:3]) +
                               ("等" if pending_ct > 3 else ""))
        if detail_bits:
            self._chip("  |  " + "  ·  ".join(detail_bits), t["sub"], 9)

        if not admin_ok:
            self._chip("  |  ⚠ 非管理员模式", t["warn"], 9)

    def _chip(self, text, color, size, bold=False):
        lbl = QLabel(text)
        lbl.setFont(theme.font(self._settings(), size, bold))
        lbl.setStyleSheet("color:%s;background:transparent;" % color)
        self._status_inner.addWidget(lbl)
        self._status_inner.addSpacing(12)

    # ================= 卡片 =================
    def refresh_cards(self) -> None:
        """全量重建卡片(旧 _render_cards),保留滚动位置。"""
        t = self._theme()
        settings = self._settings()
        # 头部字体随主题/字号档位刷新
        self._title_lbl.setFont(theme.font(settings, 18, True))
        self._refresh_btn.setFont(theme.font(settings, 9))
        self._add_btn.setFont(theme.font(settings, 9, True))

        scroll_val = self._scroll.verticalScrollBar().value()
        for refs in self._cards:
            self._cards_layout.removeWidget(refs["widget"])
            refs["widget"].deleteLater()
        self._cards = []
        if self._placeholder is not None:
            self._cards_layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None

        if not self.main.plugins:
            placeholder = QLabel("还没有任何游戏，点击「＋ 添加游戏」开始。")
            placeholder.setFont(theme.font(settings, 11))
            placeholder.setStyleSheet("color:%s;" % t["sub"])
            self._placeholder = placeholder
            self._cards_layout.insertWidget(
                0, placeholder, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        else:
            for idx, p in enumerate(self.main.plugins):
                self._card(idx, p)

        self._scroll.verticalScrollBar().setValue(scroll_val)
        self.refresh_status()
        self.refresh_controls()

    def _path_exists(self, path, ttl=3.0):
        """带短 TTL 缓存的存在性探测,勾选/刷新时不再每次都读盘(旧 _path_exists)。"""
        if not path:
            return False
        now = time.monotonic()
        hit = self._path_cache.get(path)
        if hit and now - hit[1] < ttl:
            return hit[0]
        ok = os.path.exists(path)
        self._path_cache[path] = (ok, now)
        return ok

    def _card_status(self, p):
        """卡片状态行文字与颜色(旧 _card_status)。"""
        t = self._theme()
        ok = self._path_exists(p.get("launcher", ""))
        pending = pc.pending_checklist_count(p)
        text = "✓ 就绪" if ok else "✗ 路径无效"
        if pending:
            text += "  ·  ⚠ %d 项待办" % pending
        if p.get("parallel"):
            text += "  ·  ⇉ 并行"
        color = t["err"] if not ok else (t["warn"] if pending else t["ok"])
        return text, color

    def _card(self, idx, p):
        """单张游戏卡片(旧 _card):序号/名称/状态/路径 + 开关/并行/上下移/编辑/删除。"""
        t = self._theme()
        settings = self._settings()
        enabled = bool(p.get("enabled", True))
        card = _CardFrame(self)
        card.setObjectName("card")
        card.setStyleSheet(self._card_qss(t["line"]))

        outer = QHBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 左侧启用状态色条
        strip = QFrame()
        strip.setFixedWidth(4)
        strip.setStyleSheet("background:%s;border:none;"
                            % (t["accent"] if enabled else t["line"]))
        outer.addWidget(strip)
        outer.addSpacing(8)

        # 拖动手柄(视觉提示;实际整卡非按钮区均可拖动)
        handle = QLabel("≡")
        handle.setFont(theme.font(settings, 15))
        handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        handle.setFixedWidth(24)
        handle.setStyleSheet("color:%s;background:transparent;" % t["sub"])
        handle.setCursor(Qt.CursorShape.SizeAllCursor)
        outer.addWidget(handle)
        outer.addSpacing(4)

        # 启用开关
        sw = QCheckBox("开" if enabled else "关")
        sw.setChecked(enabled)
        sw.setFont(theme.font(settings, 9))
        sw.setCursor(Qt.CursorShape.PointingHandCursor)
        sw.setToolTip("勾选后才会参与「开始运行」的队列")
        sw.clicked.connect(lambda _=False, pl=p: self._on_enable_clicked(pl))
        outer.addWidget(sw)
        outer.addSpacing(8)

        # 中部:名称行 + 状态/路径行
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 7, 0, 7)
        mid.setSpacing(3)
        full_name = p.get("name", "未命名")
        name_lbl = _ElidedLabel("%02d  %s" % (idx + 1, full_name),
                                Qt.TextElideMode.ElideRight)
        name_lbl.setFont(theme.font(settings, 13, True))
        name_lbl.setStyleSheet("color:%s;background:transparent;"
                               % (t["fg"] if enabled else t["sub"]))
        name_lbl.setToolTip(full_name)
        mid.addWidget(name_lbl)

        info = QHBoxLayout()
        info.setSpacing(10)
        status_text, status_color = self._card_status(p)
        st_lbl = QLabel(status_text)
        st_lbl.setFont(theme.font(settings, 9))
        st_lbl.setStyleSheet("color:%s;background:transparent;" % status_color)
        info.addWidget(st_lbl)

        launcher = p.get("launcher", "")
        path_lbl = _ElidedLabel(launcher or "（未设置）", Qt.TextElideMode.ElideMiddle)
        path_lbl.setFont(theme.font(settings, 9))
        path_lbl.setStyleSheet("color:%s;background:transparent;" % t["sub"])
        path_lbl.setToolTip(launcher or "尚未设置启动器路径")
        info.addWidget(path_lbl, 1)
        mid.addLayout(info)
        outer.addLayout(mid, 1)

        outer.addSpacing(10)

        # 右侧操作按钮
        right = QHBoxLayout()
        right.setSpacing(4)
        par = QPushButton("⇉")
        par.setFont(theme.font(settings, 9))
        par.setFixedWidth(34)
        par.setCursor(Qt.CursorShape.PointingHandCursor)
        par.setToolTip(PARALLEL_TIP)
        self._style_parallel(par, bool(p.get("parallel")))
        par.clicked.connect(lambda _=False, pl=p: self._on_parallel_clicked(pl))
        right.addWidget(par)

        up = self._icon_btn("▲")
        up.clicked.connect(lambda _=False, pl=p: self.main.move_plugin(pl, -1))
        right.addWidget(up)
        down = self._icon_btn("▼")
        down.clicked.connect(lambda _=False, pl=p: self.main.move_plugin(pl, +1))
        right.addWidget(down)

        right.addSpacing(6)
        edit = QPushButton("编辑")
        edit.setFont(theme.font(settings, 9))
        edit.setStyleSheet("padding:3px 10px;")
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.clicked.connect(lambda _=False, pl=p: self.main.open_edit(pl))
        right.addWidget(edit)

        delete = self._icon_btn("×")
        delete.clicked.connect(lambda _=False, pl=p: self.main.delete_plugin(pl))
        right.addWidget(delete)
        outer.addLayout(right)

        self._cards.append({
            "plugin": p, "widget": card, "strip": strip, "switch": sw,
            "name": name_lbl, "index": idx, "full_name": full_name,
            "path": path_lbl, "full_path": launcher, "status": st_lbl,
            "parallel_btn": par, "handle": handle,
            "controls": [sw, par, up, down, edit, delete],
        })
        # stretch 占布局末位,卡片按当前张数插入其前
        self._cards_layout.insertWidget(len(self._cards) - 1, card)

    def _card_qss(self, border_color):
        t = self._theme()
        return ("#card { background:%s; border:1px solid %s; border-radius:6px; }"
                % (t["panel"], border_color))

    def _icon_btn(self, text):
        b = QPushButton(text)
        b.setFont(theme.font(self._settings(), 9))
        b.setStyleSheet("background:%s;color:%s;padding:3px 7px;"
                        % (self._theme()["line"], self._theme()["fg"]))
        b.setFixedWidth(34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _style_parallel(self, btn, on):
        """⇉ 按钮:开启=accent 高亮,关闭=普通+弱化文字(旧 primary=par_on)。"""
        btn.setProperty("class", "accent" if on else "")
        btn.setStyleSheet("padding:3px 8px;" if on else
                          "padding:3px 8px;color:%s;" % self._theme()["sub"])
        style = btn.style()
        style.unpolish(btn)
        style.polish(btn)

    def _on_enable_clicked(self, p):
        """启用开关 → main.toggle;状态确实变化时重建卡片同步色条/文字。"""
        before = bool(p.get("enabled", True))
        self.main.toggle(p)
        if bool(p.get("enabled", True)) != before:
            self.refresh_cards()

    def _on_parallel_clicked(self, p):
        """⇉ 并行开关 → main.toggle_parallel;成功后重建卡片同步状态行。"""
        before = bool(p.get("parallel", False))
        self.main.toggle_parallel(p)
        if bool(p.get("parallel", False)) != before:
            self.refresh_cards()

    def refresh_controls(self) -> None:
        """运行中禁用卡片操作(旧 _refresh_card_controls 语义)。"""
        busy = self._busy()
        t = self._theme()
        for refs in self._cards:
            for ctl in refs.get("controls", []):
                ctl.setEnabled(not busy)
            handle = refs.get("handle")
            handle.setCursor(Qt.CursorShape.ArrowCursor if busy
                             else Qt.CursorShape.SizeAllCursor)
            handle.setStyleSheet("color:%s;background:transparent;"
                                 % (t["line"] if busy else t["sub"]))

    # ================= 卡片拖拽排序 =================
    def _start_card_drag(self, card) -> bool:
        if self._busy() or not self._cards:
            return False
        idx = next((i for i, refs in enumerate(self._cards)
                    if refs["widget"] is card), -1)
        if idx < 0:
            return False
        self._drag_from = idx
        self._drag_widget = card
        card.setStyleSheet(self._card_qss(self._theme()["accent"]))
        return True

    def _drag_active(self) -> bool:
        return self._drag_from is not None

    def _move_card_drag(self):
        """拖拽中按全局 Y 坐标命中测试,实时换位(旧 _move_card_drag)。"""
        if self._drag_from is None or not self._cards:
            return
        if not (0 <= self._drag_from < len(self._cards)):
            self._drag_from = None
            return
        y = QCursor.pos().y()
        cards = self._cards
        dragged = cards[self._drag_from]["widget"]
        first, last = cards[0]["widget"], cards[-1]["widget"]
        first_top = first.mapToGlobal(QPoint(0, 0)).y()
        last_top = last.mapToGlobal(QPoint(0, 0)).y()
        if y < first_top:                                   # 拖到列表上方 → 置顶
            self._drag_card_to(self._drag_from, 0)
            return
        if y >= last_top + last.height():                   # 拖到列表下方 → 沉底
            if self._drag_from != len(cards) - 1:
                self._drag_card_to(self._drag_from, len(cards) - 1)
            return
        for i, refs in enumerate(cards):
            w = refs["widget"]
            top, height = w.mapToGlobal(QPoint(0, 0)).y(), w.height()
            if top - 3 <= y < top + height + 3:
                if w is dragged:
                    return
                # 上半 → 插到它前面,下半 → 插到它后面(旧版同款防抖逻辑)
                self._drag_card_to(self._drag_from, i if y < top + height / 2 else i + 1)
                return

    def _drag_card_to(self, from_idx, to_idx):
        """拖拽中把卡片挪到新位置:只移动这一张的布局位置,不重建、不落盘。"""
        n = len(self._cards)
        if not (0 <= from_idx < n):
            return
        to_idx = max(0, min(to_idx, n - 1))
        if to_idx == from_idx:
            return
        refs = self._cards.pop(from_idx)
        self._cards.insert(to_idx, refs)
        self._cards_layout.removeWidget(refs["widget"])
        self._cards_layout.insertWidget(to_idx, refs["widget"])
        self._drag_from = to_idx
        self._renumber_cards()

    def _renumber_cards(self):
        """换位后就地刷新卡片上的序号(01、02…),不重建卡片(旧 _renumber_cards)。"""
        for pos, refs in enumerate(self._cards):
            refs["index"] = pos
            refs["name"].setFullText("%02d  %s" % (pos + 1, refs["full_name"]))

    def _finish_card_drag(self):
        """松手:清高亮,把最终位置交给 main.reorder_plugin 落盘。"""
        if self._drag_from is None:
            return
        from_idx = self._drag_from
        self._drag_from = None
        line_color = self._theme()["line"]
        for refs in self._cards:
            refs["widget"].setStyleSheet(self._card_qss(line_color))
        if not (0 <= from_idx < len(self._cards)):
            return
        refs = self._cards[from_idx]
        if refs["widget"] is not self._drag_widget or self._busy():
            # 中途卡片被重建/开始运行等异常:放弃本次拖拽,恢复真实顺序
            self.refresh_cards()
            return
        self.main.reorder_plugin(refs["plugin"], refs["index"])

    # ================= Splitter 比例 / 专注模式 =================
    def showEvent(self, event):
        super().showEvent(event)
        self._restore_retries = 0
        QTimer.singleShot(0, self._restore_splitter)

    def _restore_splitter(self):
        """按 home_log_ratio 恢复上下比例(旧 _restore_home_sash)。"""
        if self._log_focus_mode:
            return
        total = sum(self.splitter.sizes())
        if total <= 1:
            # 布局尚未完成,稍后重试
            if self._restore_retries < 20:
                self._restore_retries += 1
                QTimer.singleShot(50, self._restore_splitter)
            return
        log_h = int(round(total * self._home_log_ratio))
        self.splitter.setSizes([total - log_h, log_h])

    def _save_home_ratio(self):
        """把当前上下比例写回 settings(旧 _save_home_sash)。"""
        if self._log_focus_mode:
            return
        sizes = self.splitter.sizes()
        total = sum(sizes)
        if total <= 1:
            return
        ratio = min(0.72, max(0.25, sizes[1] / float(total)))
        self._home_log_ratio = ratio
        self.main.settings["home_log_ratio"] = round(ratio, 3)
        self._save_settings_soon()

    def _on_splitter_moved(self, pos, index):
        self._save_home_ratio()

    def set_log_focus(self, on: bool) -> None:
        """专注模式 = 隐藏/恢复队列区(旧 _toggle_log_focus 语义)。"""
        on = bool(on)
        if on != self._log_focus_mode:
            self._log_focus_mode = on
            if on:
                self._save_home_ratio()          # 进入前先保存当前比例
                self.queue_pane.setVisible(False)
            else:
                self.queue_pane.setVisible(True)
                self._restore_retries = 0
                QTimer.singleShot(0, self._restore_splitter)
        try:
            self.log_panel.set_focus_mode(on)
            if on:
                self.log_panel.text_edit.setFocus()
        except Exception:
            pass
