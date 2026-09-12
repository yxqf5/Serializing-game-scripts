# -*- coding: utf-8 -*-
"""
游戏串行一键长草 · 可视化助手
单窗口 / 自绘标题栏 / 多主题 / 可调字体 / 插件化
"""

import os
import sys
import json
import glob
import queue
import threading
import time
import webbrowser
import datetime

# -------- 高 DPI 清晰显示（必须在创建窗口前）--------
try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # Per-Monitor v2
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    ctypes = None

# Windows 任务栏独立分组（须在 Tk() 之前，否则仍显示 pythonw 图标）
APP_USER_MODEL_ID = "Games.Py.SerialRunner.GameAssistant.1"
if os.name == "nt" and ctypes:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app_paths import data_dir, resource_path

BASE_DIR = data_dir()
PLUGIN_DIR = os.path.join(BASE_DIR, "plugins")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
# 各游戏最近一次判定「已完成」的时间（同服务器日重复运行判重用）
DAILY_STATE_FILE = os.path.join(BASE_DIR, "daily_state.json")
# 自动保存/导出用的完整日志缓冲上限（界面显示另受 LogStore 1 万行限制）
RUN_LOG_BUFFER_MAX = 50000
APP_ICON_PNG = resource_path("assets", "icons", "app.png")
APP_ICON_ICO = resource_path("assets", "icons", "app.ico")
import runner_core
import display_ctrl
import preset_catalog as pc
from preset_resolver import (
    resolve_launcher, resolve_all_candidates,
    default_search_roots, narrow_search_roots, update_path_cache,
    get_assistants_root,
)
import preflight
import assistant_setup
import quick_fill as qf
import log_saver
from ui_helpers import LogStore, clamp_window_bounds, elide_end, elide_middle, group_tagged_lines

WAIT_MODE_LABELS = {
    "game": "等待游戏进程（助手跑完会关游戏）",
    "helper": "等待助手自己退出（如 MAA／模拟器类）",
}

# ===================== 主题（主色 <=5）=====================
THEMES = {
    "橙黑": {
        "bg": "#0d0d0f", "panel": "#17171b", "line": "#2b2b32",
        "fg": "#f3f3f5", "sub": "#8b8b93", "accent": "#ff7a18", "on_accent": "#000000",
        "log_bg": "#0a0a0c", "log_fg": "#d8d8de",
        "ok": "#3ad07f", "warn": "#ffc24b", "err": "#ff5b5b",
        "log_gold": "#ffd700", "log_blue": "#4da6ff",
    },
    "绝区零": {
        "bg": "#101012", "panel": "#1b1b1f", "line": "#2f2f35",
        "fg": "#ffffff", "sub": "#8a8a8a", "accent": "#ffe200", "on_accent": "#000000",
        "log_bg": "#0b0b0d", "log_fg": "#e6e6e6",
        "ok": "#5be37a", "warn": "#ffd23f", "err": "#ff5252",
        "log_gold": "#ffd700", "log_blue": "#4da6ff",
    },
    "英伦": {
        "bg": "#0f2240", "panel": "#16304f", "line": "#27466e",
        "fg": "#f3ecd8", "sub": "#a8b4cc", "accent": "#d11a2a", "on_accent": "#ffffff",
        "log_bg": "#0b1a32", "log_fg": "#e8e2cf",
        "ok": "#5bc88a", "warn": "#e6b800", "err": "#ff6b6b",
        "log_gold": "#e3c15c", "log_blue": "#6fb3ff",
    },
    "极简": {
        "bg": "#f4f4f6", "panel": "#ffffff", "line": "#e4e4ea",
        "fg": "#1d1d1f", "sub": "#86868b", "accent": "#0a84ff", "on_accent": "#ffffff",
        "log_bg": "#fbfbfd", "log_fg": "#33333a",
        "ok": "#1aa34a", "warn": "#c77700", "err": "#d83a3a",
        "log_gold": "#8a6d00", "log_blue": "#0066cc",
    },
}
DEFAULT_THEME = "橙黑"

FONT_SCALES = {"小": 0.9, "中": 1.0, "大": 1.15, "特大": 1.3}
FONT_FAMILIES = ["微软雅黑", "Microsoft YaHei UI", "黑体", "等线", "宋体", "Arial"]

# 字体全局参数（由 App 设置）
_FAMILY = "微软雅黑"
_SCALE = 1.0

# 日志区界面内最多保留的行数；完整内容仍在 LogStore，可导出/复制全部
LOG_VIEW_LINES = 600


def F(size=11, bold=False):
    return (_FAMILY, max(8, int(round(size * _SCALE))), "bold" if bold else "normal")


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(d):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_plugins():
    items = []
    if not os.path.isdir(PLUGIN_DIR):
        return items
    for f in glob.glob(os.path.join(PLUGIN_DIR, "*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            d["_file"] = f
            items.append(d)
        except Exception as e:
            print("读取插件失败：", f, e)
    items.sort(key=lambda x: (int(x.get("order", 999)), x.get("name", "")))
    # 一次性迁移：MAA（模拟器脚本，不抢鼠标）默认并行，老插件文件自动补勾
    for d in items:
        if d.get("preset_id") == "maa_gui" and "parallel" not in d:
            d["parallel"] = True
            try:
                save_plugin(d)
            except Exception:
                pass
    return items


def save_plugin(p):
    data = {k: v for k, v in p.items() if not k.startswith("_")}
    with open(p["_file"], "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("一键长草 · 游戏串行助手")
        self._set_window_icon()
        global _FAMILY, _SCALE

        self.settings = load_settings()
        self.theme_name = self.settings.get("theme", DEFAULT_THEME)
        if self.theme_name not in THEMES:
            self.theme_name = DEFAULT_THEME
        self.t = THEMES[self.theme_name]

        _FAMILY = self.settings.get("font_family", "微软雅黑")
        self.font_size_name = self.settings.get("font_size", "中")
        _SCALE = FONT_SCALES.get(self.font_size_name, 1.0)

        # 让点字号映射到正确物理大小（配合 DPI 感知 => 清晰不模糊）
        try:
            self.tk.call("tk", "scaling", self.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass

        # 原生窗口（任务栏 / 最小化 / 最大化均正常）+ 深色标题栏
        self.minsize(self._px(940), self._px(660))
        self._window_save_job = None
        self._settings_save_job = None
        self._restoring_window = True
        self._restore_maximized = bool(self.settings.get("window_maximized", False))
        self._restore_window_geometry()
        self._set_window_icon()

        self.plugins = []
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.log_store = LogStore(max_lines=10000)
        self.log_follow = True
        self._log_inserting = False
        self._log_focus_mode = False
        self.run_thread = None
        self.stop_event = threading.Event()
        self.running = False
        self._preflight_token = 0
        self._preflight_busy = False
        self.run_state = {
            "state": "idle", "index": 0, "total": 0,
            "name": "", "message": "就绪", "result": None,
            "parallel_names": [],
        }

        self.current_view = None
        self.edit_target = None
        self.log_widget = None
        self.nav_items = {}
        self._cards = []
        self._drag_from = None
        self._tooltip_win = None
        self._tooltip_job = None
        self._run_started_at = None   # 本轮运行开始时间（自动保存日志用）
        self._run_tasks = []          # 本轮每个游戏的执行结果 [(name, result)]
        # 保存专用缓冲：md 日志取自这里而非界面 LogStore（后者 1 万行上限
        # 会静默丢最旧行），运行中「清空日志」也不影响已记录的内容
        self._run_log_buffer = []     # [(text, level), ...]
        self._run_log_dropped = 0     # 缓冲超限被丢弃的行数

        self.configure(bg=self.t["bg"])
        os.makedirs(PLUGIN_DIR, exist_ok=True)
        # 上次异常退出遗留的分辨率切换,启动时自动恢复(崩溃兜底)
        _done, _msg = display_ctrl.restore_if_needed()
        if _done:
            print(_msg)
        log_saver.cleanup_old_logs(
            LOG_DIR, log_saver.retention_days(self.settings.get("log_retention", "month")))
        self._build_shell()
        self.reload()
        if not self.settings.get("first_run_done"):
            self.go("first_run")
        else:
            self.go("home")
        self.deiconify()
        if self._restore_maximized:
            try:
                self.state("zoomed")
            except Exception:
                pass
        self.bind("<Configure>", self._on_window_configure)
        self.bind_all("<MouseWheel>", self._dispatch_mousewheel, add="+")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, lambda: setattr(self, "_restoring_window", False))
        self.after(30, self._style_native_titlebar)
        self.after(80, self._drain_log)

    def _set_window_icon(self):
        if os.name != "nt" or not os.path.isfile(APP_ICON_ICO):
            return
        ico = os.path.normpath(os.path.abspath(APP_ICON_ICO))
        try:
            self.iconbitmap(default=ico)
        except Exception:
            pass
        self.update_idletasks()
        self._apply_taskbar_icon()

    def _apply_taskbar_icon(self):
        if os.name != "nt" or not ctypes or not os.path.isfile(APP_ICON_ICO):
            return
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if not hwnd:
                return
            ico = os.path.normpath(os.path.abspath(APP_ICON_ICO))
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x10
            WM_SETICON = 0x0080
            for size, kind in ((32, 1), (16, 0)):
                hicon = ctypes.windll.user32.LoadImageW(
                    None, ico, IMAGE_ICON, size, size, LR_LOADFROMFILE,
                )
                if hicon:
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, kind, hicon)
        except Exception:
            pass

    def _load_sidebar_logo(self, size=40):
        if not os.path.isfile(APP_ICON_PNG):
            return None
        try:
            from PIL import Image, ImageTk
            img = Image.open(APP_ICON_PNG).convert("RGBA")
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            try:
                return tk.PhotoImage(file=APP_ICON_PNG)
            except Exception:
                return None

    # ---------------- 窗口控制 ----------------
    def _restore_window_geometry(self):
        saved = self.settings.get("window_bounds")
        if saved:
            x, y, w, h = clamp_window_bounds(
                saved, self.winfo_screenwidth(), self.winfo_screenheight(), 940, 660)
            self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        else:
            self.geometry("1060x760")
            self._center()

    def _center(self):
        self.update_idletasks()
        w, h = 1060, 760
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2 - 20
        self.geometry("%dx%d+%d+%d" % (w, h, x, max(0, y)))

    def _on_window_configure(self, event):
        if event.widget is not self or self._restoring_window:
            return
        if self._window_save_job:
            self.after_cancel(self._window_save_job)
        self._window_save_job = self.after(500, self._save_window_state)

    def _save_window_state(self):
        self._window_save_job = None
        try:
            state = self.state()
            self.settings["window_maximized"] = (state == "zoomed")
            if state == "normal":
                self.settings["window_bounds"] = {
                    "x": self.winfo_x(), "y": self.winfo_y(),
                    "width": self.winfo_width(), "height": self.winfo_height(),
                }
            save_settings(self.settings)
        except Exception:
            pass

    def _schedule_settings_save(self):
        if self._settings_save_job:
            self.after_cancel(self._settings_save_job)
        self._settings_save_job = self.after(350, self._flush_settings)

    def _flush_settings(self):
        self._settings_save_job = None
        save_settings(self.settings)

    def _on_close(self):
        if self._window_save_job:
            self.after_cancel(self._window_save_job)
            self._window_save_job = None
        if self._settings_save_job:
            self.after_cancel(self._settings_save_job)
            self._settings_save_job = None
        self._save_window_state()
        self.destroy()

    @staticmethod
    def _colorref(hexcolor):
        h = hexcolor.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (b << 16) | (g << 8) | r

    def _is_dark(self):
        h = self.t["bg"].lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) < 128

    def _style_native_titlebar(self):
        """用 DWM 把系统标题栏染成与主题一致（Win10 2004+/Win11）。"""
        if os.name != "nt":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())

            def setattr_(attr, value):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(ctypes.c_int(value)), ctypes.sizeof(ctypes.c_int))

            setattr_(20, 1 if self._is_dark() else 0)          # 深色模式
            setattr_(35, self._colorref(self.t["panel"]))      # 标题栏底色
            setattr_(36, self._colorref(self.t["fg"]))         # 标题文字色
        except Exception:
            pass

    # ---------------- 外壳 ----------------
    def _setup_ttk_style(self):
        t = self.t
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        # 细窄、无箭头、融入主题的竖向滚动条
        try:
            st.layout("Vert.TScrollbar", [
                ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                    ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        except Exception:
            pass
        st.configure("Vert.TScrollbar", troughcolor=t["bg"], background=t["line"],
                     bordercolor=t["bg"], darkcolor=t["line"], lightcolor=t["line"],
                     arrowcolor=t["sub"], relief="flat", borderwidth=0, width=8)
        st.map("Vert.TScrollbar",
               background=[("active", t["accent"]), ("pressed", t["accent"])])
        try:
            st.layout("Horiz.TScrollbar", [
                ("Horizontal.Scrollbar.trough", {"sticky": "ew", "children": [
                    ("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        except Exception:
            pass
        st.configure("Horiz.TScrollbar", troughcolor=t["bg"], background=t["line"],
                     bordercolor=t["bg"], darkcolor=t["line"], lightcolor=t["line"],
                     arrowcolor=t["sub"], relief="flat", borderwidth=0, height=8)
        st.map("Horiz.TScrollbar",
               background=[("active", t["accent"]), ("pressed", t["accent"])])
        # 下拉框配色统一
        st.configure("TCombobox", fieldbackground=t["panel"], background=t["panel"],
                     foreground=t["fg"], arrowcolor=t["sub"], bordercolor=t["line"],
                     lightcolor=t["line"], darkcolor=t["line"], relief="flat")
        st.map("TCombobox", fieldbackground=[("readonly", t["panel"])],
               foreground=[("readonly", t["fg"])], background=[("readonly", t["panel"])])
        st.configure("Run.Horizontal.TProgressbar", troughcolor=t["line"], background=t["accent"],
                     bordercolor=t["line"], lightcolor=t["accent"], darkcolor=t["accent"],
                     thickness=7)
        self.option_add("*TCombobox*Listbox.background", t["panel"])
        self.option_add("*TCombobox*Listbox.foreground", t["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", t["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", t["on_accent"])

    def _build_shell(self):
        for w in self.winfo_children():
            w.destroy()
        t = self.t
        self.configure(bg=t["bg"])
        self._setup_ttk_style()

        # —— 主体：侧栏 + 内容 ——
        main = tk.Frame(self, bg=t["bg"])
        main.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(main, bg=t["panel"], width=self._sidebar_width())
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo = tk.Frame(self.sidebar, bg=t["panel"])
        logo.pack(fill="x", pady=(24, 16), padx=20)
        self._sidebar_logo = self._load_sidebar_logo(40)
        if self._sidebar_logo:
            tk.Label(logo, image=self._sidebar_logo, bg=t["panel"]).pack(side="left", padx=(0, 10))
        else:
            b = tk.Frame(logo, bg=t["accent"], width=6, height=44)
            b.pack(side="left"); b.pack_propagate(False)
        box = tk.Frame(logo, bg=t["panel"]); box.pack(side="left")
        tk.Label(box, text="一键长草", bg=t["panel"], fg=t["fg"], font=F(16, True)).pack(anchor="w")
        tk.Label(box, text="SERIAL RUNNER", bg=t["panel"], fg=t["sub"],
                 font=("Consolas", max(8, int(round(8 * _SCALE))))).pack(anchor="w")

        self.nav_items = {}
        self._nav("home", "主页", "▶")
        self._nav("first_run", "部署向导", "★")

        # 底部：设置 / 帮助 / 管理员状态
        bottom = tk.Frame(self.sidebar, bg=t["panel"])
        bottom.pack(side="bottom", fill="x", pady=(0, 14))
        admin = runner_core.is_admin()
        ab = tk.Frame(bottom, bg=t["panel"]); ab.pack(fill="x", padx=20, pady=(8, 10))
        tk.Label(ab, text=("● 管理员模式" if admin else "● 非管理员"),
                 bg=t["panel"], fg=(t["ok"] if admin else t["warn"]), font=F(9)).pack(anchor="w")
        tk.Frame(bottom, bg=t["line"], height=1).pack(fill="x", padx=16, pady=(0, 6))
        self._nav("help", "使用帮助", "?", side="bottom", parent=bottom)
        self._nav("settings", "设置", "⚙", side="bottom", parent=bottom)

        body = tk.Frame(main, bg=t["bg"])
        body.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(body, bg=t["bg"])
        self.content.pack(side="top", fill="both", expand=True)
        self._build_global_run_bar(body)

    def _px(self, v):
        """把按 96 DPI / 标准字号设计的固定像素尺寸换算到当前环境。"""
        try:
            dpi = self.winfo_fpixels("1i")
        except Exception:
            dpi = 96.0
        return max(int(v), int(round(v * _SCALE * dpi / 96.0)))

    def _sidebar_width(self):
        """按当前字体实测侧栏所需宽度，高分屏/大字号下文字不再被裁剪。"""
        nav = tkfont.Font(font=F(12, True))
        logo = tkfont.Font(font=F(16, True))
        admin = tkfont.Font(font=F(9))
        w_nav = nav.measure("  ?   使用帮助") + 12 * 2 + 4 + 8 * 2
        w_logo = 40 + 10 + logo.measure("一键长草") + 20 * 2
        w_admin = admin.measure("● 非管理员") + 20 * 2
        return max(212, w_nav, w_logo, w_admin)

    def _build_global_run_bar(self, parent):
        t = self.t
        bar = tk.Frame(parent, bg=t["panel"], height=self._px(72),
                       highlightthickness=1, highlightbackground=t["line"])
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)

        state = tk.Frame(bar, bg=t["panel"])
        state.pack(side="left", fill="both", expand=True, padx=(18, 10), pady=7)
        self.global_state_dot = tk.Label(state, text="●", bg=t["panel"], fg=t["sub"], font=F(11))
        self.global_state_dot.pack(side="left", padx=(0, 8))
        self.global_run_title = tk.Label(state, text="串行任务未运行", bg=t["panel"], fg=t["fg"],
                                         font=F(10, True), anchor="w")
        self.global_run_title.pack(side="left")
        self.global_run_detail = tk.Label(state, text=" · 准备好后可在任意页面开始", bg=t["panel"],
                                          fg=t["sub"], font=F(9), anchor="w")
        self.global_run_detail.pack(side="left", fill="x", expand=True, padx=(5, 0))

        stop_slot = tk.Frame(bar, bg=t["panel"], width=self._px(148), height=self._px(50))
        stop_slot.pack(side="right", padx=(8, 16), pady=10)
        stop_slot.pack_propagate(False)
        self.global_stop_btn = self._button(stop_slot, "■ 结束运行", self.stop_run, danger=True)
        self.global_stop_btn.config(font=F(12, True), padx=12, pady=8)
        self.global_stop_btn.pack(fill="both", expand=True)

        start_slot = tk.Frame(bar, bg=t["panel"], width=self._px(148), height=self._px(50))
        start_slot.pack(side="right", padx=(8, 0), pady=10)
        start_slot.pack_propagate(False)
        self.global_start_btn = self._button(start_slot, "▶ 开始运行", self.start_run, primary=True)
        self.global_start_btn.config(font=F(12, True), padx=12, pady=8)
        self.global_start_btn.pack(fill="both", expand=True)
        self.global_progress = ttk.Progressbar(bar, orient="horizontal", mode="determinate", length=78,
                                               style="Run.Horizontal.TProgressbar")
        self.global_progress.pack(side="right", padx=(8, 0),
                                  pady=max(10, (self._px(72) - 16) // 2))
        # 运行控件优先获得固定宽度，状态文字使用剩余空间。
        state.pack_forget()
        state.pack(side="left", fill="both", expand=True, padx=(18, 10), pady=7)
        # 兼容旧的运行控制代码和其他页面引用。
        self.run_btn = self.global_start_btn
        self.stop_btn = self.global_stop_btn
        self.status_lbl = self.global_run_detail
        self._refresh_run_buttons()

    def _nav(self, key, label, icon, side="top", parent=None):
        t = self.t
        parent = parent or self.sidebar
        f = tk.Frame(parent, bg=t["panel"], cursor="hand2")
        f.pack(fill="x", padx=12, pady=2, side=side)
        bar = tk.Frame(f, bg=t["panel"], width=4)
        bar.pack(side="left", fill="y")
        lbl = tk.Label(f, text="  %s   %s" % (icon, label), bg=t["panel"], fg=t["fg"],
                       font=F(12), anchor="w", padx=8, pady=11)
        lbl.pack(side="left", fill="x", expand=True)
        for wdg in (f, lbl):
            wdg.bind("<Button-1>", lambda e, k=key: self.go(k))
            wdg.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
            wdg.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))
        self.nav_items[key] = (f, bar, lbl)

    def _nav_hover(self, key, on):
        if key == self.current_view:
            return
        _, _, lbl = self.nav_items[key]
        lbl.config(fg=self.t["accent"] if on else self.t["fg"])

    def _highlight_nav(self):
        t = self.t
        for key, (f, bar, lbl) in self.nav_items.items():
            active = (key == self.current_view)
            bar.config(bg=t["accent"] if active else t["panel"])
            lbl.config(fg=t["accent"] if active else t["fg"], font=F(12, active))

    # ---------------- 路由 ----------------
    def go(self, name, force=False):
        if name == self.current_view and not force:
            return
        self.current_view = name
        if name != "home":
            self._log_focus_mode = False
        self._highlight_nav()
        for w in self.content.winfo_children():
            w.destroy()
        self.log_widget = None
        page = tk.Frame(self.content, bg=self.t["bg"])
        page.place(relx=0, rely=0, relwidth=1, relheight=1)
        {
            "home": self.build_home,
            "edit": self.build_edit,
            "add": self.build_add,
            "first_run": self.build_first_run,
            "settings": self.build_settings,
            "help": self.build_help,
        }.get(name, self.build_home)(page)
        self._refresh_run_buttons()

    def _animate_in(self, frame, step=0):
        """保留旧调用兼容；页面切换不再做位移动画，避免重绘抖动。"""
        return

    # ---------------- 主页 ----------------
    def build_home(self, root):
        t = self.t
        self._log_focus_mode = False
        self.home_paned = tk.PanedWindow(
            root, orient="vertical", bg=t["line"], bd=0, sashwidth=8,
            sashrelief="flat", opaqueresize=True, showhandle=False,
        )
        self.home_paned.pack(fill="both", expand=True, padx=20, pady=(14, 14))
        self.home_paned.bind("<ButtonRelease-1>", self._save_home_sash)

        self.queue_pane = tk.Frame(self.home_paned, bg=t["bg"])
        self.log_pane = tk.Frame(self.home_paned, bg=t["bg"])
        self.home_paned.add(self.queue_pane, minsize=185, stretch="always")
        self.home_paned.add(self.log_pane, minsize=190, stretch="always")

        head = tk.Frame(self.queue_pane, bg=t["bg"])
        head.pack(fill="x", padx=6, pady=(0, 8))
        tk.Label(head, text="游戏队列", bg=t["bg"], fg=t["fg"], font=F(18, True)).pack(side="left")
        self._button(head, "＋ 添加游戏", self.add_plugin, compact=True).pack(side="right", padx=(8, 0))
        self._button(head, "↻ 刷新", self.reload_and_render, compact=True).pack(side="right")

        # ---- 顶部状态条(常驻自检汇总) ----
        self._home_status_bar = tk.Frame(self.queue_pane, bg=t["panel"], highlightthickness=1,
                                         highlightbackground=t["line"])
        self._home_status_bar.pack(fill="x", padx=6, pady=(0, 6), ipady=3)
        self._home_status_inner = tk.Frame(self._home_status_bar, bg=t["panel"])
        self._home_status_inner.pack(fill="x", padx=12, pady=2)
        self._refresh_home_status()

        wrap = tk.Frame(self.queue_pane, bg=t["bg"])
        wrap.pack(fill="both", expand=True, padx=2, pady=(2, 0))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(wrap, bg=t["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview,
                            style="Vert.TScrollbar")
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns", padx=(6, 2))
        self.list_frame = tk.Frame(self.canvas, bg=t["bg"])
        self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw", tags="inner")
        self.list_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_list_canvas_configure)
        self._bind_wheel(self.canvas)
        self._render_cards()
        self._build_log_panel(self.log_pane)
        self.after_idle(self._restore_home_sash)
        self._refresh_run_buttons()

    def _build_log_panel(self, parent):
        t = self.t
        head = tk.Frame(parent, bg=t["bg"])
        head.pack(fill="x", padx=6, pady=(4, 6))
        tk.Label(head, text="运行日志", bg=t["bg"], fg=t["fg"], font=F(13, True)).pack(side="left")
        self.log_count_lbl = tk.Label(head, text="", bg=t["bg"], fg=t["sub"], font=F(9))
        self.log_count_lbl.pack(side="left", padx=(10, 0))

        self.log_focus_btn = self._button(
            head, "□ 专注", self._toggle_log_focus, compact=True,
        )
        self.log_focus_btn.pack(side="right", padx=(6, 0))
        self._button(head, "导入", self._import_log, compact=True).pack(side="right", padx=(6, 0))
        self._button(head, "目录", self._open_log_dir, compact=True).pack(side="right", padx=(6, 0))
        self._button(head, "导出", self._export_log, compact=True).pack(side="right", padx=(6, 0))
        self._button(head, "清空", self._clear_log, compact=True).pack(side="right", padx=(6, 0))
        self._button(head, "复制", self._copy_log, compact=True).pack(side="right", padx=(6, 0))
        self.log_follow_btn = self._button(head, "● 跟随最新", self._resume_log_follow, compact=True)
        self.log_follow_btn.pack(side="right", padx=(6, 0))

        body = tk.Frame(parent, bg=t["log_bg"], highlightthickness=1,
                        highlightbackground=t["line"])
        body.pack(fill="both", expand=True, padx=6, pady=(0, 2))
        self.log_widget = tk.Text(
            body, bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["fg"],
            selectbackground=t["accent"], selectforeground=t["on_accent"],
            # 必须用原生含中文字形的字体：Consolas 遇中文走 GDI 字体回退链，
            # 窗口缩放时全量重排一次要数百毫秒（实测），是拉伸卡顿的主因
            font=(_FAMILY, max(9, int(round(10 * _SCALE)))), relief="flat",
            wrap="word", padx=12, pady=9, bd=0, undo=False,
        )
        sb = ttk.Scrollbar(body, orient="vertical", command=self._log_yview, style="Vert.TScrollbar")
        self._log_scrollbar = sb
        self.log_widget.configure(yscrollcommand=self._on_log_scroll)
        sb.pack(side="right", fill="y")
        self.log_widget.pack(side="left", fill="both", expand=True)
        self.log_widget.tag_configure("log_err", foreground=t["err"])
        self.log_widget.tag_configure("log_warn", foreground=t["warn"])
        self.log_widget.tag_configure("log_gold", foreground=t["log_gold"])
        self.log_widget.tag_configure("log_blue", foreground=t["log_blue"])
        self.log_widget.tag_configure("log_ok", foreground=t["ok"])
        self.log_widget.bind("<MouseWheel>", self._on_log_mousewheel)
        self.log_widget.bind("<Button-4>", self._on_log_mousewheel)
        self.log_widget.bind("<Button-5>", self._on_log_mousewheel)
        self._render_log_store()

    def _restore_home_sash(self):
        if not hasattr(self, "home_paned") or not self.home_paned.winfo_exists():
            return
        self.update_idletasks()
        total = self.home_paned.winfo_height()
        if total <= 1:
            return
        ratio = self.settings.get("home_log_ratio", 0.40)
        try:
            ratio = min(0.72, max(0.25, float(ratio)))
        except Exception:
            ratio = 0.40
        self.home_paned.sash_place(0, 0, int(total * (1.0 - ratio)))

    def _save_home_sash(self, event=None):
        if self._log_focus_mode or not hasattr(self, "home_paned"):
            return
        try:
            total = self.home_paned.winfo_height()
            sash_y = self.home_paned.sash_coord(0)[1]
            if total > 1:
                self.settings["home_log_ratio"] = round(1.0 - (sash_y / float(total)), 3)
                self._schedule_settings_save()
        except Exception:
            pass

    def _toggle_log_focus(self):
        if not hasattr(self, "home_paned") or not self.home_paned.winfo_exists():
            return
        if self._log_focus_mode:
            self.home_paned.forget(self.log_pane)
            self.home_paned.add(self.queue_pane, minsize=185, stretch="always")
            self.home_paned.add(self.log_pane, minsize=190, stretch="always")
            self._log_focus_mode = False
            self.log_focus_btn.config(text="□ 专注")
            self.after_idle(self._restore_home_sash)
        else:
            self._save_home_sash()
            self.home_paned.forget(self.queue_pane)
            self._log_focus_mode = True
            self.log_focus_btn.config(text="▣ 退出专注")
        if self.log_widget and self.log_widget.winfo_exists():
            self.log_widget.focus_set()

    def _bind_wheel(self, canvas):
        canvas._wheel_scrollable = True

    def _bind_list_wheel(self, canvas):
        self._bind_wheel(canvas)

    def _dispatch_mousewheel(self, event):
        widget = event.widget
        while widget is not None:
            if widget is getattr(self, "log_widget", None):
                return
            if isinstance(widget, tk.Text):
                return
            if isinstance(widget, tk.Canvas) and getattr(widget, "_wheel_scrollable", False):
                delta = -1 if event.delta > 0 else 1
                widget.yview_scroll(delta * 3, "units")
                return "break"
            try:
                widget = widget.master
            except Exception:
                break

    def _throttle(self, attr, ms, func):
        """合并高频事件：至多每 ms 毫秒执行一次，停止后补执行最后一次。

        拖拽缩放时 Configure 逐像素触发，逐像素重排卡片代价太高；
        节流后内容仍以约 12 次/秒跟随窗口变化。
        """
        job = getattr(self, attr, None)
        if job:
            self.after_cancel(job)
        wait = ms - (time.monotonic() - getattr(self, attr + "_last", 0.0)) * 1000.0
        if wait <= 0:
            setattr(self, attr + "_last", time.monotonic())
            func()
            return

        def fire():
            setattr(self, attr, None)
            setattr(self, attr + "_last", time.monotonic())
            func()

        setattr(self, attr, self.after(int(wait), fire))

    def _on_list_canvas_configure(self, event=None):
        if not hasattr(self, "canvas") or not self.canvas.winfo_exists():
            return
        self._throttle("_card_layout", 80, self._apply_card_layout)

    def _apply_card_layout(self):
        if not hasattr(self, "canvas") or not self.canvas.winfo_exists():
            return
        cw = self.canvas.winfo_width()
        if cw and cw != getattr(self, "_canvas_w", None):
            self._canvas_w = cw
            self.canvas.itemconfig("inner", width=cw)
        self._do_sync_card_wraplength()

    def _sync_card_wraplength(self):
        self._throttle("_card_layout", 80, self._apply_card_layout)

    def _sync_canvas_inner(self, cv, tag):
        """把 Canvas 内嵌容器宽度对齐到画布宽度（经 _throttle 调用，避免逐像素重排）。"""
        if not cv.winfo_exists():
            return
        cv.itemconfig(tag, width=cv.winfo_width())
        cv.configure(scrollregion=cv.bbox("all"))

    def _do_sync_card_wraplength(self):
        if not hasattr(self, "canvas") or not self.canvas.winfo_exists():
            return
        cw = self.canvas.winfo_width()
        if abs(cw - getattr(self, "_last_wrap_w", -10 ** 9)) < 8:
            return
        self._last_wrap_w = cw
        max_chars = max(22, int((cw - 420) / 7))
        name_chars = max(8, int((cw - 430) / 20))
        for refs in getattr(self, "_cards", []):
            name_lbl = refs.get("name")
            if name_lbl and name_lbl.winfo_exists():
                name_lbl.config(text="%02d  %s" % (
                    refs.get("index", 0) + 1,
                    elide_end(refs.get("full_name") or "未命名", name_chars),
                ))
            path_lbl = refs.get("path")
            if path_lbl and path_lbl.winfo_exists():
                path_lbl.config(text=elide_middle(refs.get("full_path") or "（未设置）", max_chars))

    def _render_cards(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._cards = []
        # 卡片全部重建，宽度标记一并失效，确保首轮省略号同步一定执行。
        self._last_wrap_w = -10 ** 9
        t = self.t
        if not self.plugins:
            tk.Label(self.list_frame, text="还没有任何游戏，点击「＋ 添加游戏」开始。",
                     bg=t["bg"], fg=t["sub"], font=F(11)).pack(pady=30)
            self._refresh_home_status()
            return
        for idx, p in enumerate(self.plugins):
            self._card(idx, p)
        self._refresh_home_status()

    def _path_exists(self, path, ttl=3.0):
        """带短 TTL 缓存的存在性探测，勾选/刷新时不再每次都读盘。"""
        if not path:
            return False
        now = time.monotonic()
        cache = getattr(self, "_path_cache", None)
        if cache is None:
            cache = self._path_cache = {}
        hit = cache.get(path)
        if hit and now - hit[1] < ttl:
            return hit[0]
        ok = os.path.exists(path)
        cache[path] = (ok, now)
        return ok

    def _refresh_home_status(self):
        """更新主页顶部状态条：就绪 / 待办 / 路径无效 / 管理员。"""
        if not hasattr(self, "_home_status_inner"):
            return
        inner = self._home_status_inner
        if not inner.winfo_exists():
            return
        for w in inner.winfo_children():
            w.destroy()
        t = self.t

        active = [p for p in self.plugins if p.get("enabled", True)]
        total = len(active)
        ok_ct = 0
        bad_ct = 0
        pending_ct = 0
        bad_names = []
        pending_names = []
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

        admin_ok = runner_core.is_admin()

        # 无勾选状态
        if total == 0:
            tk.Label(inner, text="⚠ 尚未勾选任何游戏（每行左侧「开/关」切换）",
                     bg=t["panel"], fg=t["warn"], font=F(10), anchor="w").pack(side="left")
            if not admin_ok:
                tk.Label(inner, text="  ·  非管理员模式，部分脚本可能启动失败",
                         bg=t["panel"], fg=t["warn"], font=F(9), anchor="w").pack(side="left")
            return

        # 有勾选：三色分段
        def seg(text, fg):
            tk.Label(inner, text=text, bg=t["panel"], fg=fg, font=F(10, True),
                     anchor="w").pack(side="left", padx=(0, 12))

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
            tk.Label(inner, text="  |  " + "  ·  ".join(detail_bits),
                     bg=t["panel"], fg=t["sub"], font=F(9), anchor="w").pack(side="left")

        if not admin_ok:
            tk.Label(inner, text="  |  ⚠ 非管理员模式", bg=t["panel"], fg=t["warn"],
                     font=F(9), anchor="w").pack(side="left")

    def _card_status(self, p):
        """卡片状态行文字与颜色（主页 ⇉ 并行开关就地刷新时也要用它）。"""
        t = self.t
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
        t = self.t
        enabled = bool(p.get("enabled", True))
        panel = t["panel"]
        card = tk.Frame(self.list_frame, bg=panel, highlightthickness=1, highlightbackground=t["line"])
        card.pack(fill="x", pady=3, padx=4)
        strip = tk.Frame(card, bg=(t["accent"] if enabled else t["line"]), width=4)
        strip.pack(side="left", fill="y")
        inner = tk.Frame(card, bg=panel)
        inner.pack(side="left", fill="both", expand=True, padx=10, pady=7)
        inner.columnconfigure(0, weight=0, minsize=28)
        inner.columnconfigure(1, weight=0, minsize=42)
        inner.columnconfigure(2, weight=1, minsize=120)
        inner.columnconfigure(3, weight=0, minsize=190)

        handle = tk.Label(inner, text="≡", bg=panel, fg=t["sub"], font=F(15),
                          width=2, cursor="fleur")
        handle.grid(row=0, column=0, rowspan=3, padx=(0, 4), sticky="ns")
        handle.bind("<ButtonPress-1>", self._start_card_drag)
        handle.bind("<B1-Motion>", self._move_card_drag)
        handle.bind("<ButtonRelease-1>", self._finish_card_drag)

        sw = self._button(inner, ("开" if enabled else "关"), lambda pl=p: self.toggle(pl),
                          primary=enabled, compact=True, width=3)
        if not enabled:
            sw.config(bg=t["line"], fg=t["sub"])
            sw._base = t["line"]
        sw.grid(row=0, column=1, rowspan=3, padx=(0, 8), sticky="ns")

        mid = tk.Frame(inner, bg=panel)
        mid.grid(row=0, column=2, sticky="nsew", padx=(0, 10))
        mid.columnconfigure(1, weight=1)

        full_name = p.get("name", "未命名")
        name_lbl = tk.Label(mid, text="%02d  %s" % (idx + 1, full_name), bg=panel,
                            fg=(t["fg"] if enabled else t["sub"]), font=F(13, True),
                            anchor="w", justify="left")
        name_lbl.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._attach_tooltip(name_lbl, full_name)

        launcher = p.get("launcher", "")
        status_text, status_color = self._card_status(p)
        st_lbl = tk.Label(mid, text=status_text, bg=panel,
                          fg=status_color,
                          font=F(9), anchor="w", justify="left")
        st_lbl.grid(row=1, column=0, sticky="w", padx=(0, 10))

        path_lbl = tk.Label(mid, text=(launcher or "（未设置）"), bg=panel, fg=t["sub"],
                            font=F(9), anchor="w", justify="left")
        path_lbl.grid(row=1, column=1, sticky="ew")
        self._attach_tooltip(path_lbl, launcher or "尚未设置启动器路径")

        right = tk.Frame(inner, bg=panel)
        right.grid(row=0, column=3, rowspan=3, sticky="e")
        par_on = bool(p.get("parallel"))
        par = self._button(right, "⇉", lambda pl=p: self.toggle_parallel(pl),
                           primary=par_on, compact=True, width=2)
        if not par_on:
            par.config(bg=t["panel"], fg=t["sub"])
            par._base = t["panel"]
        self._attach_tooltip(par, "并行开关：开启后点「开始运行」时该任务立即与其它任务同时跑。\n"
                                  "适合 MAA 等模拟器／后台脚本；会抢真实鼠标的脚本（原神、绝区零等）别开。")
        par.pack(side="left", padx=2)
        # 用插件对象在点击时定位下标：卡片顺序会随拖拽变化，建卡时的下标会失准。
        up = self._icon_btn(right, "▲", lambda pl=p: self.move_plugin(pl, -1)); up.pack(side="left", padx=2)
        down = self._icon_btn(right, "▼", lambda pl=p: self.move_plugin(pl, +1)); down.pack(side="left", padx=2)
        edit = self._button(right, "编辑", lambda: self.open_edit(p), compact=True)
        edit.pack(side="left", padx=(8, 2))
        delete = self._icon_btn(right, "×", lambda: self.delete_plugin(p)); delete.pack(side="left", padx=2)

        self._cards.append({
            "plugin": p, "strip": strip, "switch": sw, "name": name_lbl,
            "index": idx, "full_name": full_name,
            "path": path_lbl, "full_path": launcher, "status": st_lbl,
            "parallel_btn": par,
            "card": card, "handle": handle, "controls": [sw, par, up, down, edit, delete],
        })
        self.after_idle(self._sync_card_wraplength)
        self._refresh_card_controls()
    def _start_card_drag(self, event):
        if self.running or self._preflight_busy:
            return
        idx = self._card_index_by_handle(event.widget)
        if idx < 0:
            return
        self._drag_from = idx
        self._cards[idx]["card"].config(highlightbackground=self.t["accent"])

    def _card_index_by_handle(self, handle):
        for i, refs in enumerate(self._cards):
            if refs.get("handle") is handle:
                return i
        return -1

    def _move_card_drag(self, event):
        if self._drag_from is None or not self._cards:
            return
        if not (0 <= self._drag_from < len(self._cards)):
            self._drag_from = None
            return
        y = event.y_root
        dragged = self._cards[self._drag_from]["card"]
        first, last = self._cards[0]["card"], self._cards[-1]["card"]
        if y < first.winfo_rooty():                         # 拖到列表上方 → 置顶
            self._drag_card_to(self._drag_from, 0)
            return
        if y >= last.winfo_rooty() + last.winfo_height():   # 拖到列表下方 → 沉底
            if self._drag_from != len(self._cards) - 1:
                self._drag_card_to(self._drag_from, len(self._cards) - 1)
            return
        for i, refs in enumerate(self._cards):
            card = refs["card"]
            top, height = card.winfo_rooty(), card.winfo_height()
            if top - 3 <= y < top + height + 3:
                if card is dragged:
                    return
                # 上半 → 插到它前面，下半 → 插到它后面。换位后光标必然落在
                # 被拖卡片自己身上，天然不会来回抖动。
                self._drag_card_to(self._drag_from, i if y < top + height / 2 else i + 1)
                return

    def _drag_card_to(self, from_idx, to_idx):
        """拖拽中把卡片挪到新位置：只 pack 移动这一张卡，其余卡片原地不动，
        不销毁不重建，因此全程无闪烁。"""
        if not (0 <= from_idx < len(self._cards)):
            return
        to_idx = max(0, min(to_idx, len(self._cards) - 1))
        if to_idx == from_idx:
            return
        item = self.plugins.pop(from_idx)
        self.plugins.insert(to_idx, item)
        refs = self._cards.pop(from_idx)
        self._cards.insert(to_idx, refs)
        card = refs["card"]
        pack_opts = {"fill": "x", "pady": 3, "padx": 4}
        if to_idx + 1 < len(self._cards):
            card.pack(before=self._cards[to_idx + 1]["card"], **pack_opts)
        else:
            card.pack(**pack_opts)
        self._drag_from = to_idx
        self.update_idletasks()   # 立即重算几何，下一次命中测试的坐标才准确
        self._renumber_cards()

    def _finish_card_drag(self, event=None):
        if self._drag_from is None:
            return
        self._drag_from = None
        for refs in self._cards:
            if refs["card"].winfo_exists():
                refs["card"].config(highlightbackground=self.t["line"])
        self._save_orders()

    def _save_orders(self):
        """把当前列表顺序写回 order 字段，只保存真正变化的任务。"""
        for order, plugin in enumerate(self.plugins, 1):
            if plugin.get("order") != order:
                plugin["order"] = order
                save_plugin(plugin)

    def _renumber_cards(self):
        """换位后就地刷新卡片上的序号（01、02…），不重建卡片。"""
        for pos, refs in enumerate(self._cards):
            refs["index"] = pos
        self._last_wrap_w = -10 ** 9
        self._do_sync_card_wraplength()

    def _attach_tooltip(self, widget, text):
        widget.bind("<Enter>", lambda e, w=widget, s=text: self._schedule_tooltip(w, s), add="+")
        widget.bind("<Leave>", lambda e: self._hide_tooltip(), add="+")

    def _schedule_tooltip(self, widget, text):
        self._hide_tooltip()
        self._tooltip_job = self.after(450, lambda: self._show_tooltip(widget, text))

    def _show_tooltip(self, widget, text):
        self._tooltip_job = None
        if not text or not widget.winfo_exists():
            return
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=self.t["line"])
        tk.Label(win, text=text, bg=self.t["panel"], fg=self.t["fg"], font=F(9),
                 padx=9, pady=6, justify="left", wraplength=620).pack(padx=1, pady=1)
        win.geometry("+%d+%d" % (widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height() + 4))
        self._tooltip_win = win

    def _hide_tooltip(self):
        if self._tooltip_job:
            self.after_cancel(self._tooltip_job)
            self._tooltip_job = None
        if self._tooltip_win:
            try:
                self._tooltip_win.destroy()
            except Exception:
                pass
            self._tooltip_win = None

    # ---------------- 编辑 ----------------
    def open_edit(self, p):
        self.edit_target = p
        self.go("edit", force=True)

    def build_edit(self, root):
        t = self.t
        p = self.edit_target
        head = tk.Frame(root, bg=t["bg"]); head.pack(fill="x", padx=26, pady=(22, 6))
        self._chip(head, "←  返回", lambda: self.go("home", force=True)).pack(side="left")
        tk.Label(head, text="编辑游戏", bg=t["bg"], fg=t["fg"], font=F(20, True)).pack(side="left", padx=14)
        preset_id = p.get("preset_id", "")
        if preset_id:
            game, script = pc.find_script_by_preset_id(pc.load_catalog(), preset_id)
            tag = "%s · %s" % (game.get("name", ""), script.get("name", "")) if game and script else preset_id
            self._chip(head, "更换预设", lambda: self.go("add", force=True)).pack(side="right")
        self._chip(head, "粘贴填充", lambda: self._open_quick_fill_dialog("edit")).pack(side="right", padx=(0, 8))

        wrap = tk.Frame(root, bg=t["bg"]); wrap.pack(fill="both", expand=True, padx=26, pady=8)
        cv = tk.Canvas(wrap, bg=t["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=cv.yview, style="Vert.TScrollbar")
        cv.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y", padx=(6, 2)); cv.pack(side="left", fill="both", expand=True)
        form = tk.Frame(cv, bg=t["bg"])
        cv.create_window((0, 0), window=form, anchor="nw", tags="f")
        form.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: self._throttle(
            "_cvw_f", 80, lambda: self._sync_canvas_inner(cv, "f")))
        self._bind_wheel(cv)

        def label(text, hint="", parent=None):
            par = parent or form
            tk.Label(par, text=text, bg=t["bg"], fg=t["fg"], font=F(11, True),
                     anchor="w").pack(anchor="w", pady=(14, 0))
            if hint:
                tk.Label(par, text=hint, bg=t["bg"], fg=t["sub"], font=F(9),
                         anchor="w", justify="left").pack(anchor="w")

        def entry(par, value, mono=False):
            e = tk.Entry(par, font=(("Consolas" if mono else _FAMILY), 11),
                         bg=t["panel"], fg=t["fg"], insertbackground=t["fg"], relief="flat",
                         highlightthickness=1, highlightbackground=t["line"], highlightcolor=t["accent"])
            e.insert(0, value); e.pack(fill="x", ipady=5)
            return e

        if preset_id:
            label("当前预设")
            tk.Label(form, text=tag, bg=t["bg"], fg=t["accent"], font=F(11), anchor="w").pack(anchor="w")

        label("显示名称")
        self.e_name = entry(form, p.get("name", ""))

        self.parallel_var = tk.BooleanVar(value=bool(p.get("parallel", False)))
        tk.Checkbutton(form, text="⇉ 并行运行（与其它任务同时启动）", variable=self.parallel_var,
                       bg=t["bg"], fg=t["fg"], selectcolor=t["panel"],
                       activebackground=t["bg"], activeforeground=t["accent"],
                       font=F(11, True), anchor="w").pack(anchor="w", pady=(10, 0))
        tk.Label(form, text="适合模拟器／后台类脚本（如 MAA）：点「开始运行」时立即与其它任务同时跑，不用排队等。"
                            "会抢占真实鼠标的脚本（原神、绝区零、崩铁等）不要勾，否则会互相抢鼠标；"
                            "多个勾了并行的任务也会同时启动。",
                 bg=t["bg"], fg=t["sub"], font=F(9), anchor="w", justify="left",
                 wraplength=760).pack(anchor="w")

        label("脚本 / 启动器程序（.exe）", "就是平时你双击打开的那个脚本程序。")
        pf = tk.Frame(form, bg=t["bg"]); pf.pack(fill="x")
        self.e_launcher = tk.Entry(pf, font=F(11), bg=t["panel"], fg=t["fg"], insertbackground=t["fg"],
                                   relief="flat", highlightthickness=1, highlightbackground=t["line"],
                                   highlightcolor=t["accent"])
        self.e_launcher.insert(0, p.get("launcher", ""))
        self.e_launcher.pack(side="left", fill="x", expand=True, ipady=5)
        self._chip(pf, "浏览…", self._browse).pack(side="left", padx=(8, 0))

        checklist = p.get("setup_checklist") or []
        done_set = set(p.get("checklist_done") or [])
        self._edit_check_vars = []
        if checklist:
            label("脚本侧待办（勾选表示已完成；未完成时运行日志会黄色警告）",
                  "这些是各脚本里还需要你手动确认的设置，助手不会替你改脚本配置。")
            cf = tk.Frame(form, bg=t["bg"]); cf.pack(fill="x", pady=(4, 0))
            for item in checklist:
                var = tk.BooleanVar(value=(item in done_set))
                self._edit_check_vars.append((item, var))
                tk.Checkbutton(cf, text=item, variable=var, bg=t["bg"], fg=t["fg"],
                               selectcolor=t["panel"], activebackground=t["bg"],
                               activeforeground=t["accent"], font=F(10), anchor="w",
                               wraplength=720, justify="left").pack(anchor="w", pady=2)

        doc = p.get("doc_url", "")
        if doc:
            lf = tk.Frame(form, bg=t["bg"]); lf.pack(anchor="w", pady=(8, 0))
            lnk = tk.Label(lf, text="📎 官方文档 / 项目页", bg=t["bg"], fg=t["accent"],
                           font=F(10), cursor="hand2")
            lnk.pack(side="left")
            lnk.bind("<Button-1>", lambda e: os.startfile(doc) if os.name == "nt" else None)

        self._adv_visible = False
        adv_toggle = tk.Frame(form, bg=t["bg"]); adv_toggle.pack(fill="x", pady=(16, 0))
        self._adv_btn = self._chip(adv_toggle, "▸ 展开高级选项", self._toggle_advanced)
        self._adv_btn.pack(side="left")

        self.advanced_frame = tk.Frame(form, bg=t["bg"])

        label("启动参数（可留空）", "高级：空格分隔。绝区零 -o --close-game；原神 startOneDragon。", parent=self.advanced_frame)
        self.e_args = entry(self.advanced_frame, " ".join(p.get("args", [])), mono=True)

        label("前置程序（可留空）",
              "先启动它，再启动上面的脚本。适合 MaaEnd 这类无法自己开游戏的脚本：这里填游戏本体 exe。",
              parent=self.advanced_frame)
        prf = tk.Frame(self.advanced_frame, bg=t["bg"]); prf.pack(fill="x")
        self.e_pre = tk.Entry(prf, font=("Consolas", 11), bg=t["panel"], fg=t["fg"],
                              insertbackground=t["fg"], relief="flat", highlightthickness=1,
                              highlightbackground=t["line"], highlightcolor=t["accent"])
        self.e_pre.insert(0, p.get("pre_launcher", ""))
        self.e_pre.pack(side="left", fill="x", expand=True, ipady=5)
        self._chip(prf, "浏览…", self._browse_pre).pack(side="left", padx=(8, 0))

        label("前置程序参数（可留空）", "空格分隔；一般留空。", parent=self.advanced_frame)
        self.e_pre_args = entry(self.advanced_frame, " ".join(p.get("pre_args", [])), mono=True)

        tk.Label(self.advanced_frame, text="前置启动后等待（秒）", bg=t["bg"], fg=t["fg"],
                 font=F(11, True), anchor="w").pack(anchor="w", pady=(14, 0))
        tk.Label(self.advanced_frame, text="给游戏留出加载时间再启动脚本；已在运行则自动跳过前置启动。",
                 bg=t["bg"], fg=t["sub"], font=F(9), anchor="w").pack(anchor="w")
        self.e_pre_delay = tk.Spinbox(self.advanced_frame, from_=0, to=600, width=8, font=F(11),
                                      bg=t["panel"], fg=t["fg"], relief="flat",
                                      buttonbackground=t["line"], highlightthickness=1,
                                      highlightbackground=t["line"])
        self.e_pre_delay.delete(0, "end"); self.e_pre_delay.insert(0, str(p.get("pre_delay_sec", 0)))
        self.e_pre_delay.pack(anchor="w", ipady=3)

        label("任务日志提取（可留空则跳过）",
              "读取脚本自身日志，只提取：每日奖励完成（金色）/未完成（红色）/最新体力剩余（蓝色）。",
              parent=self.advanced_frame)
        lf = tk.Frame(self.advanced_frame, bg=t["bg"]); lf.pack(fill="x")
        self.e_log_file = tk.Entry(lf, font=("Consolas", 11), bg=t["panel"], fg=t["fg"],
                                   insertbackground=t["fg"], relief="flat", highlightthickness=1,
                                   highlightbackground=t["line"], highlightcolor=t["accent"])
        self.e_log_file.insert(0, p.get("log_file", ""))
        self.e_log_file.pack(side="left", fill="x", expand=True, ipady=5)
        self._chip(lf, "浏览…", self._browse_log).pack(side="left", padx=(8, 0))

        tk.Label(self.advanced_frame, text="日志编码", bg=t["bg"], fg=t["fg"],
                 font=F(11, True), anchor="w").pack(anchor="w", pady=(14, 0))
        self.e_log_enc = ttk.Combobox(self.advanced_frame, values=["auto", "gbk", "utf-8"],
                                      width=12, font=F(10), state="readonly")
        enc_val = (p.get("log_encoding") or "auto").strip().lower()
        self.e_log_enc.set(enc_val if enc_val in ("auto", "gbk", "utf-8") else "auto")
        self.e_log_enc.pack(anchor="w", ipady=2)

        label("每日奖励·已完成关键词（逗号分隔，金色）", "例：今日奖励已领取, 每日实训已完成。",
              parent=self.advanced_frame)
        self.e_daily_done = entry(self.advanced_frame,
                                  ", ".join(p.get("daily_done_patterns", [])), mono=True)

        label("每日奖励·未完成关键词（逗号分隔，红色）", "例：未领取, 未检测到每日实训奖励。",
              parent=self.advanced_frame)
        self.e_daily_pending = entry(self.advanced_frame,
                                     ", ".join(p.get("daily_pending_patterns", [])), mono=True)

        label("体力/理智关键词（逗号分隔，蓝色，只取最新一条）", "例：开拓力, Current Sanity。",
              parent=self.advanced_frame)
        self.e_stamina = entry(self.advanced_frame,
                               ", ".join(p.get("stamina_patterns", [])), mono=True)

        tk.Label(self.advanced_frame, text="完成判定方式", bg=t["bg"], fg=t["fg"],
                 font=F(11, True), anchor="w").pack(anchor="w", pady=(14, 0))
        self.wait_var = tk.StringVar(value=p.get("wait_mode", "game"))
        for mode, lab in WAIT_MODE_LABELS.items():
            tk.Radiobutton(self.advanced_frame, text=lab, variable=self.wait_var, value=mode,
                           bg=t["bg"], fg=t["fg"], selectcolor=t["panel"],
                           activebackground=t["bg"], activeforeground=t["accent"],
                           font=F(10), anchor="w").pack(anchor="w")

        label("游戏进程名（多个用逗号分隔）", "原神国服 YuanShen.exe；崩铁 StarRail.exe；MAA 可留空。",
              parent=self.advanced_frame)
        self.e_game = entry(self.advanced_frame, ", ".join(p.get("game_processes", [])), mono=True)

        label("助手进程名（多个用逗号分隔）", "跑完后要关闭的脚本进程，如 BetterGI.exe、MAA.exe。",
              parent=self.advanced_frame)
        self.e_helper = entry(self.advanced_frame, ", ".join(p.get("helper_processes", [])), mono=True)

        tk.Label(self.advanced_frame, text="等待游戏启动超时（分钟）", bg=t["bg"], fg=t["fg"],
                 font=F(11, True), anchor="w").pack(anchor="w", pady=(14, 0))
        self.e_timeout = tk.Spinbox(self.advanced_frame, from_=1, to=120, width=8, font=F(11),
                                    bg=t["panel"], fg=t["fg"], relief="flat",
                                    buttonbackground=t["line"], highlightthickness=1,
                                    highlightbackground=t["line"])
        self.e_timeout.delete(0, "end"); self.e_timeout.insert(0, str(p.get("start_timeout_min", 15)))
        self.e_timeout.pack(anchor="w", ipady=3)

        label("备注", parent=self.advanced_frame)
        self.t_notes = tk.Text(self.advanced_frame, height=3, font=F(10), bg=t["panel"], fg=t["fg"],
                               insertbackground=t["fg"], relief="flat", highlightthickness=1,
                               highlightbackground=t["line"])
        self.t_notes.insert("1.0", p.get("notes", "")); self.t_notes.pack(fill="x")

        bf = tk.Frame(form, bg=t["bg"]); bf.pack(fill="x", pady=18)
        self._pill(bf, "保存", self._save_edit, primary=True).pack(side="left")
        self._chip(bf, "取消", lambda: self.go("home", force=True)).pack(side="left", padx=10)

    def _toggle_advanced(self):
        if self._adv_visible:
            self.advanced_frame.pack_forget()
            self._adv_btn.config(text="▸ 展开高级选项")
        else:
            self.advanced_frame.pack(fill="x", after=self._adv_btn.master)
            self._adv_btn.config(text="▾ 收起高级选项")
        self._adv_visible = not self._adv_visible

    def _browse(self):
        path = filedialog.askopenfilename(title="选择脚本/启动器程序",
                                          filetypes=[("可执行程序", "*.exe"), ("所有文件", "*.*")])
        if path:
            self.e_launcher.delete(0, "end")
            self.e_launcher.insert(0, os.path.normpath(path))

    def _browse_pre(self):
        path = filedialog.askopenfilename(title="选择前置程序（如游戏本体 exe）",
                                          filetypes=[("可执行程序", "*.exe"), ("所有文件", "*.*")])
        if path:
            self.e_pre.delete(0, "end")
            self.e_pre.insert(0, os.path.normpath(path))

    def _browse_log(self):
        path = filedialog.askopenfilename(title="选择脚本日志文件",
                                          filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt"),
                                                     ("所有文件", "*.*")])
        if path:
            self.e_log_file.delete(0, "end")
            self.e_log_file.insert(0, os.path.normpath(path))

    def _split(self, text):
        return [x.strip() for x in text.replace("，", ",").split(",") if x.strip()]

    def _save_edit(self):
        p = self.edit_target
        name = self.e_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "请填写显示名称。", parent=self)
            return
        p["name"] = name
        p["launcher"] = self.e_launcher.get().strip().strip('"')
        p["args"] = self.e_args.get().split()
        p["pre_launcher"] = self.e_pre.get().strip().strip('"')
        p["pre_args"] = self.e_pre_args.get().split()
        try:
            p["pre_delay_sec"] = max(0, int(self.e_pre_delay.get()))
        except Exception:
            p["pre_delay_sec"] = 0
        p["log_file"] = self.e_log_file.get().strip().strip('"')
        p["log_encoding"] = (self.e_log_enc.get() or "auto").strip().lower()
        p["daily_done_patterns"] = self._split(self.e_daily_done.get())
        p["daily_pending_patterns"] = self._split(self.e_daily_pending.get())
        p["stamina_patterns"] = self._split(self.e_stamina.get())
        p.pop("done_patterns", None)
        p.pop("fail_patterns", None)
        p.pop("tail_lines", None)
        p["wait_mode"] = self.wait_var.get()
        p["parallel"] = bool(self.parallel_var.get())
        p["game_processes"] = self._split(self.e_game.get())
        p["helper_processes"] = self._split(self.e_helper.get())
        try:
            p["start_timeout_min"] = int(self.e_timeout.get())
        except Exception:
            p["start_timeout_min"] = 15
        p["notes"] = self.t_notes.get("1.0", "end").strip()
        if hasattr(self, "_edit_check_vars"):
            p["checklist_done"] = [item for item, var in self._edit_check_vars if var.get()]
        pid = p.get("preset_id")
        if pid and p.get("launcher"):
            update_path_cache(self.settings, pid, p["launcher"])
            save_settings(self.settings)
        try:
            save_plugin(p)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)
            return
        self.reload()
        self.go("home", force=True)

    def _open_quick_fill_dialog(self, mode):
        """弹出粘贴快速填充窗口。mode: add | edit"""
        t = self.t
        win = tk.Toplevel(self)
        win.title("粘贴快速填充")
        win.configure(bg=t["bg"])
        win.geometry("680x600")
        win.minsize(520, 480)
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 680) // 2
        y = self.winfo_y() + (self.winfo_height() - 600) // 2
        win.geometry("680x600+%d+%d" % (max(0, x), max(0, y)))

        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)

        hdr = tk.Frame(win, bg=t["bg"])
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        tk.Label(hdr, text="粘贴快速填充", bg=t["bg"], fg=t["fg"], font=F(16, True)).pack(anchor="w")
        tk.Label(hdr, text="每行「键: 值」；点「确认并保存」写入表单并保存到 plugins。Ctrl+Enter 快捷保存。",
                 bg=t["bg"], fg=t["sub"], font=F(10), anchor="w").pack(anchor="w", pady=(4, 0))
        tk.Label(hdr, text="支持：名称、游戏、脚本、启动器、参数、等待模式、游戏进程、助手进程、超时、文档、备注、待办完成",
                 bg=t["bg"], fg=t["sub"], font=F(9), anchor="w", wraplength=640).pack(anchor="w", pady=(2, 0))

        box = tk.Frame(win, bg=t["bg"])
        box.grid(row=2, column=0, sticky="nsew", padx=20, pady=8)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        text = tk.Text(box, bg=t["panel"], fg=t["fg"], insertbackground=t["fg"],
                       font=(_FAMILY, 10), relief="flat", wrap="word",
                       highlightthickness=1, highlightbackground=t["line"])
        vsb = ttk.Scrollbar(box, orient="vertical", command=text.yview, style="Vert.TScrollbar")
        text.configure(yscrollcommand=vsb.set)
        text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        if mode == "edit" and self.edit_target:
            text.insert("1.0", qf.export_plugin_to_text(self.edit_target))
        else:
            text.insert("1.0", qf.SAMPLE_QUICK_FILL)

        footer = tk.Frame(win, bg=t["panel"], highlightthickness=1, highlightbackground=t["line"])
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        inner_f = tk.Frame(footer, bg=t["panel"])
        inner_f.pack(fill="x", padx=14, pady=12)

        def _btn(parent, label, cmd, primary=False):
            bgc = t["accent"] if primary else t["line"]
            fgc = t["on_accent"] if primary else t["fg"]
            b = tk.Button(parent, text=label, command=cmd, bg=bgc, fg=fgc,
                          activebackground=t["fg"] if primary else t["accent"],
                          activeforeground=t["on_accent"] if primary else t["fg"],
                          font=F(11, primary), relief="flat", padx=18, pady=8,
                          cursor="hand2", bd=0, highlightthickness=0)
            return b

        def _parse_or_warn():
            parsed, err = qf.parse_quick_fill(text.get("1.0", "end"))
            if err:
                messagebox.showwarning("格式错误", err, parent=win)
                return None
            return parsed

        def _close():
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

        def on_fill_only():
            parsed = _parse_or_warn()
            if parsed is None:
                return
            if mode == "edit":
                self._apply_parsed_to_edit(parsed)
            else:
                self._apply_parsed_to_add(parsed)
            _close()

        def on_confirm_save():
            parsed = _parse_or_warn()
            if parsed is None:
                return
            if mode == "edit":
                self._apply_parsed_to_edit(parsed)
            else:
                self._apply_parsed_to_add(parsed)
            _close()
            if mode == "edit":
                self._save_edit()
            else:
                self._save_add()

        def fill_sample():
            text.delete("1.0", "end")
            text.insert("1.0", qf.SAMPLE_QUICK_FILL)

        def restore_current():
            text.delete("1.0", "end")
            if mode == "edit" and self.edit_target:
                text.insert("1.0", qf.export_plugin_to_text(self.edit_target))
            else:
                text.insert("1.0", qf.SAMPLE_QUICK_FILL)

        left = tk.Frame(inner_f, bg=t["panel"])
        left.pack(side="left")
        _btn(left, "填入样例", fill_sample).pack(side="left", padx=(0, 8))
        if mode == "edit":
            _btn(left, "恢复为当前", restore_current).pack(side="left")

        right = tk.Frame(inner_f, bg=t["panel"])
        right.pack(side="right")
        _btn(right, "取消", _close).pack(side="left", padx=(0, 8))
        _btn(right, "仅填充", on_fill_only).pack(side="left", padx=(0, 8))
        _btn(right, "确认并保存", on_confirm_save, primary=True).pack(side="left")

        win.bind("<Escape>", lambda e: _close())
        win.bind("<Control-Return>", lambda e: on_confirm_save())
        win.protocol("WM_DELETE_WINDOW", _close)
        text.focus_set()

    def _apply_parsed_to_edit(self, parsed):
        advanced_keys = {"args", "wait_mode", "game_processes", "helper_processes",
                         "start_timeout_min", "notes", "pre_launcher", "pre_args", "pre_delay_sec",
                         "log_file", "log_encoding", "daily_done_patterns",
                         "daily_pending_patterns", "stamina_patterns"}
        if advanced_keys & set(parsed.keys()) and hasattr(self, "_adv_visible") and not self._adv_visible:
            self._toggle_advanced()

        def _set_entry(entry, value):
            entry.delete(0, "end")
            entry.insert(0, value)

        if "name" in parsed and hasattr(self, "e_name"):
            _set_entry(self.e_name, parsed["name"])
        if "launcher" in parsed and hasattr(self, "e_launcher"):
            _set_entry(self.e_launcher, parsed["launcher"])
        if "args" in parsed and hasattr(self, "e_args"):
            _set_entry(self.e_args, " ".join(parsed["args"]))
        if "pre_launcher" in parsed and hasattr(self, "e_pre"):
            _set_entry(self.e_pre, parsed["pre_launcher"])
        if "pre_args" in parsed and hasattr(self, "e_pre_args"):
            _set_entry(self.e_pre_args, " ".join(parsed["pre_args"]))
        if "pre_delay_sec" in parsed and hasattr(self, "e_pre_delay"):
            self.e_pre_delay.delete(0, "end")
            self.e_pre_delay.insert(0, str(parsed["pre_delay_sec"]))
        if "log_file" in parsed and hasattr(self, "e_log_file"):
            _set_entry(self.e_log_file, parsed["log_file"])
        if "log_encoding" in parsed and hasattr(self, "e_log_enc"):
            enc = (parsed["log_encoding"] or "auto").strip().lower()
            self.e_log_enc.set(enc if enc in ("auto", "gbk", "utf-8") else "auto")
        if "daily_done_patterns" in parsed and hasattr(self, "e_daily_done"):
            _set_entry(self.e_daily_done, ", ".join(parsed["daily_done_patterns"]))
        if "daily_pending_patterns" in parsed and hasattr(self, "e_daily_pending"):
            _set_entry(self.e_daily_pending, ", ".join(parsed["daily_pending_patterns"]))
        if "stamina_patterns" in parsed and hasattr(self, "e_stamina"):
            _set_entry(self.e_stamina, ", ".join(parsed["stamina_patterns"]))
        if "wait_mode" in parsed and hasattr(self, "wait_var"):
            self.wait_var.set(parsed["wait_mode"])
        if "game_processes" in parsed and hasattr(self, "e_game"):
            _set_entry(self.e_game, ", ".join(parsed["game_processes"]))
        if "helper_processes" in parsed and hasattr(self, "e_helper"):
            _set_entry(self.e_helper, ", ".join(parsed["helper_processes"]))
        if "start_timeout_min" in parsed and hasattr(self, "e_timeout"):
            self.e_timeout.delete(0, "end")
            self.e_timeout.insert(0, str(parsed["start_timeout_min"]))
        if "notes" in parsed and hasattr(self, "t_notes"):
            self.t_notes.delete("1.0", "end")
            self.t_notes.insert("1.0", parsed["notes"])
        if "checklist_done" in parsed and hasattr(self, "_edit_check_vars"):
            done = set(parsed["checklist_done"])
            for item, var in self._edit_check_vars:
                var.set(item in done)
        if "doc_url" in parsed and self.edit_target is not None:
            self.edit_target["doc_url"] = parsed["doc_url"]

    def _apply_parsed_to_add(self, parsed):
        self._add_fill_overrides = {}
        for k in ("name", "args", "wait_mode", "game_processes", "helper_processes",
                  "start_timeout_min", "notes", "doc_url",
                  "pre_launcher", "pre_args", "pre_delay_sec",
                  "log_file", "log_encoding", "daily_done_patterns",
                  "daily_pending_patterns", "stamina_patterns"):
            if k in parsed:
                self._add_fill_overrides[k] = parsed[k]

        if "game" in parsed:
            target = parsed["game"].strip()
            for g in self._add_games:
                gname = g.get("name", "")
                if gname == target or target in gname or gname in target:
                    self._add_game_var.set(gname)
                    break
            self._add_on_game_change()

        if "script" in parsed:
            target = parsed["script"].strip()
            game = self._add_selected_game()
            if game:
                for s in game.get("scripts", []):
                    sname = s.get("name", "")
                    if sname == target or target in sname or sname in target:
                        self._add_script_var.set(sname)
                        break
            self._add_on_script_change()

        if "launcher" in parsed:
            self._add_path_var.set(parsed["launcher"])
            if hasattr(self, "_add_path_status"):
                self._add_path_status.config(text="来自粘贴填充", fg=self.t["ok"])

        if "checklist_done" in parsed and hasattr(self, "_add_check_vars"):
            done = set(parsed["checklist_done"])
            for item, var in self._add_check_vars:
                var.set(item in done)

    # ---------------- 设置 ----------------
    def build_settings(self, root):
        t = self.t
        tk.Label(root, text="设置", bg=t["bg"], fg=t["fg"], font=F(20, True)).pack(
            anchor="w", padx=26, pady=(22, 6))

        wrap = tk.Frame(root, bg=t["bg"]); wrap.pack(fill="both", expand=True, padx=26, pady=4)

        # 主题
        tk.Label(wrap, text="主题配色", bg=t["bg"], fg=t["fg"], font=F(13, True)).pack(anchor="w", pady=(6, 2))
        tk.Label(wrap, text="选择一款配色，立即生效并自动记忆。", bg=t["bg"], fg=t["sub"],
                 font=F(9)).pack(anchor="w", pady=(0, 8))
        grid = tk.Frame(wrap, bg=t["bg"]); grid.pack(fill="x")
        col = row = 0
        for name, th in THEMES.items():
            self._theme_card(grid, name, th).grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
            col += 1
            if col >= 2:
                col, row = 0, row + 1
        for c in range(2):
            grid.columnconfigure(c, weight=1)

        # 字体
        tk.Label(wrap, text="字体", bg=t["bg"], fg=t["fg"], font=F(13, True)).pack(anchor="w", pady=(18, 6))
        fr = tk.Frame(wrap, bg=t["bg"]); fr.pack(fill="x")
        tk.Label(fr, text="字体：", bg=t["bg"], fg=t["fg"], font=F(11)).pack(side="left")
        self.font_var = tk.StringVar(value=_FAMILY)
        fam = ttk.Combobox(fr, textvariable=self.font_var, values=FONT_FAMILIES, width=22,
                           state="readonly", font=F(10))
        fam.pack(side="left", padx=(4, 18))
        fam.bind("<<ComboboxSelected>>", lambda e: self._apply_font())

        tk.Label(fr, text="字号：", bg=t["bg"], fg=t["fg"], font=F(11)).pack(side="left")
        self.size_var = tk.StringVar(value=self.font_size_name)
        for s in FONT_SCALES.keys():
            tk.Radiobutton(fr, text=s, variable=self.size_var, value=s, bg=t["bg"], fg=t["fg"],
                           selectcolor=t["panel"], activebackground=t["bg"], activeforeground=t["accent"],
                           font=F(10), command=self._apply_font).pack(side="left")

        tk.Label(wrap, text="提示：若觉得字体偏小或偏大，调整字号即可；高分屏已自动做清晰化处理。",
                 bg=t["bg"], fg=t["sub"], font=F(9)).pack(anchor="w", pady=(10, 0))

        # 助手安装根目录
        tk.Label(wrap, text="助手安装根目录", bg=t["bg"], fg=t["fg"], font=F(13, True)).pack(
            anchor="w", pady=(18, 2))
        tk.Label(wrap,
                 text="自动搜索启动器时优先扫描这个目录（部署向导里也可以设置）。"
                      "留空则扫描所有固定硬盘的常见位置。",
                 bg=t["bg"], fg=t["sub"], font=F(9), wraplength=720,
                 justify="left").pack(anchor="w", pady=(0, 6))
        srow = tk.Frame(wrap, bg=t["bg"]); srow.pack(fill="x")
        tk.Entry(srow, textvariable=tk.StringVar(value=get_assistants_root(self.settings)),
                 font=F(10), width=52, state="readonly", readonlybackground=t["panel"],
                 fg=t["fg"], relief="flat").pack(side="left", ipady=4)
        self._chip(srow, "修改…", self._settings_pick_root).pack(side="left", padx=(8, 0))
        if get_assistants_root(self.settings):
            self._chip(srow, "清除", self._settings_clear_root).pack(side="left", padx=(6, 0))

        # 日志自动保存
        tk.Label(wrap, text="日志自动保存", bg=t["bg"], fg=t["fg"], font=F(13, True)).pack(
            anchor="w", pady=(18, 2))
        tk.Label(wrap,
                 text="每次运行结束自动保存到 logs\\YYYY-MM-DD.md，一天多次运行用分割线隔开；"
                      "超过保留期的旧日志在启动/保存时自动清理。",
                 bg=t["bg"], fg=t["sub"], font=F(9), justify="left",
                 wraplength=720).pack(anchor="w", pady=(0, 6))
        retention_row = tk.Frame(wrap, bg=t["bg"]); retention_row.pack(fill="x")
        self.retention_var = tk.StringVar(value=self.settings.get("log_retention", "month"))
        retention_opts = [
            ("week", "保留最近一周"),
            ("month", "保留最近一个月"),
            ("forever", "不清理，一直保存"),
        ]
        for value, label in retention_opts:
            tk.Radiobutton(retention_row, text=label, variable=self.retention_var, value=value,
                           bg=t["bg"], fg=t["fg"], selectcolor=t["panel"],
                           activebackground=t["bg"], activeforeground=t["accent"],
                           font=F(10), command=self._apply_log_retention).pack(side="left", padx=(0, 18))
        self._button(wrap, "打开日志目录", self._open_log_dir, compact=True).pack(anchor="w", pady=(10, 0))

    def _apply_log_retention(self):
        value = self.retention_var.get()
        self.settings["log_retention"] = value
        save_settings(self.settings)
        removed = log_saver.cleanup_old_logs(
            LOG_DIR, log_saver.retention_days(value))
        if removed:
            self._enqueue_log("已按新保留策略清理 %d 个过期日志文件。" % removed, level="info")

    def _apply_font(self):
        global _FAMILY, _SCALE
        _FAMILY = self.font_var.get()
        self.font_size_name = self.size_var.get()
        _SCALE = FONT_SCALES.get(self.font_size_name, 1.0)
        self.settings["font_family"] = _FAMILY
        self.settings["font_size"] = self.font_size_name
        save_settings(self.settings)
        self._rebuild_all()

    def _theme_card(self, parent, name, th):
        t = self.t
        selected = (name == self.theme_name)
        card = tk.Frame(parent, bg=th["panel"], highlightthickness=2,
                        highlightbackground=(t["accent"] if selected else th["line"]), cursor="hand2")
        top = tk.Frame(card, bg=th["bg"], height=64); top.pack(fill="x"); top.pack_propagate(False)
        sw = tk.Frame(top, bg=th["bg"]); sw.pack(side="left", padx=14, pady=14)
        for c in [th["accent"], th["fg"], th["sub"], th["panel"]]:
            tk.Frame(sw, bg=c, width=20, height=20, highlightthickness=1,
                     highlightbackground=th["line"]).pack(side="left", padx=3)
        info = tk.Frame(card, bg=th["panel"]); info.pack(fill="x", padx=14, pady=10)
        tk.Label(info, text=name, bg=th["panel"], fg=th["fg"], font=F(13, True)).pack(side="left")
        tk.Label(info, text=("● 使用中" if selected else "点击应用"), bg=th["panel"],
                 fg=(t["accent"] if selected else th["sub"]), font=F(9)).pack(side="right")
        for w in [card, top, sw, info] + info.winfo_children() + sw.winfo_children():
            w.bind("<Button-1>", lambda e, n=name: self.apply_theme(n))
        return card

    def apply_theme(self, name):
        if name not in THEMES:
            return
        self.theme_name = name
        self.t = THEMES[name]
        self.settings["theme"] = name
        save_settings(self.settings)
        self._rebuild_all()

    def _rebuild_all(self):
        self.configure(bg=self.t["bg"])
        self._build_shell()
        self._style_native_titlebar()
        cur = self.current_view or "home"
        self.current_view = None
        self.go(cur)

    # ---------------- 帮助 ----------------
    def build_help(self, root):
        t = self.t
        tk.Label(root, text="使用帮助", bg=t["bg"], fg=t["fg"], font=F(20, True)).pack(
            anchor="w", padx=26, pady=(22, 8))
        box = tk.Text(root, bg=t["log_bg"], fg=t["fg"], font=F(11), relief="flat", wrap="word",
                      padx=18, pady=16, highlightthickness=1, highlightbackground=t["line"])
        box.pack(fill="both", expand=True, padx=26, pady=(0, 20))
        box.insert("1.0", HELP_TEXT)
        box.configure(state="disabled")

    # ---------------- 通用控件 ----------------
    def _button(self, parent, text, cmd, primary=False, danger=False, compact=False, width=None):
        t = self.t
        bg = t["err"] if danger else (t["accent"] if primary else t["panel"])
        fg = "#ffffff" if danger else (t["on_accent"] if primary else t["fg"])
        button = tk.Button(
            parent, text=text, command=cmd, bg=bg, fg=fg,
            activebackground=(t["err"] if danger else (t["fg"] if primary else t["line"])),
            activeforeground=("#ffffff" if danger else (t["on_accent"] if primary else t["fg"])),
            disabledforeground=t["sub"], font=F(9 if compact else 11, primary or danger),
            relief="flat", bd=0, cursor="hand2", padx=(9 if compact else 16),
            pady=(4 if compact else 8), takefocus=True,
            highlightthickness=1, highlightbackground=t["line"], highlightcolor=t["accent"],
        )
        if width is not None:
            button.config(width=width)
        button._base = bg
        return button

    def _pill(self, parent, text, cmd, primary=True):
        return self._button(parent, text, cmd, primary=primary)

    def _chip(self, parent, text, cmd):
        return self._button(parent, text, cmd, compact=True)

    def _icon_btn(self, parent, text, cmd):
        t = self.t
        b = self._button(parent, text, cmd, compact=True, width=2)
        b.config(bg=t["line"], fg=t["fg"], padx=2)
        b._base = t["line"]
        return b

    # ---------------- 数据 ----------------
    def reload(self):
        self.plugins = load_plugins()
        for i, p in enumerate(self.plugins, 1):
            if p.get("order") != i:
                p["order"] = i
                save_plugin(p)

    def reload_and_render(self):
        self.reload()
        if self.current_view == "home":
            self._render_cards()

    def toggle(self, p):
        if self.running or self._preflight_busy:
            return
        # 就地刷新，不重建整个列表
        p["enabled"] = not bool(p.get("enabled", True))
        save_plugin(p)
        t = self.t
        for refs in self._cards:
            if refs["plugin"] is p:
                en = p["enabled"]
                refs["strip"].config(bg=t["accent"] if en else t["line"])
                refs["switch"].config(text=("开" if en else "关"),
                                      bg=(t["accent"] if en else t["line"]),
                                      fg=(t["on_accent"] if en else t["sub"]))
                refs["switch"]._base = t["accent"] if en else t["line"]
                refs["name"].config(fg=t["fg"] if en else t["sub"])
                break
        self._refresh_home_status()

    def toggle_parallel(self, p):
        """主页卡片「⇉」快捷开关：就地切换并行状态并保存。"""
        if self.running or self._preflight_busy:
            return
        p["parallel"] = not bool(p.get("parallel", False))
        save_plugin(p)
        t = self.t
        for refs in self._cards:
            if refs["plugin"] is p:
                on = bool(p.get("parallel"))
                btn = refs.get("parallel_btn")
                if btn and btn.winfo_exists():
                    btn.config(bg=(t["accent"] if on else t["panel"]),
                               fg=(t["on_accent"] if on else t["sub"]))
                    btn._base = t["accent"] if on else t["panel"]
                st = refs.get("status")
                if st and st.winfo_exists():
                    text, color = self._card_status(p)
                    st.config(text=text, fg=color)
                break
        self._refresh_home_status()

    def move_plugin(self, p, delta):
        """▲▼ 移动：按插件对象定位当前下标（卡片顺序会随拖拽变化，
        不能用建卡时捕获的下标）。"""
        if self.running or self._preflight_busy:
            return
        for i, q in enumerate(self.plugins):
            if q is p:
                self.move(i, delta)
                return

    def move(self, idx, delta):
        if self.running or self._preflight_busy:
            return
        j = idx + delta
        if j < 0 or j >= len(self.plugins) or idx == j or idx >= len(self._cards):
            return
        # 就地交换相邻两张卡片，不整列重建、不重读磁盘，避免每次点击都闪烁。
        self.plugins[idx], self.plugins[j] = self.plugins[j], self.plugins[idx]
        self._cards[idx], self._cards[j] = self._cards[j], self._cards[idx]
        top = self._cards[min(idx, j)]["card"]
        bottom = self._cards[max(idx, j)]["card"]
        top.pack(before=bottom, fill="x", pady=3, padx=4)
        self._renumber_cards()
        self._save_orders()

    def delete_plugin(self, p):
        if self.running or self._preflight_busy:
            return
        if not messagebox.askyesno("确认删除",
                                   "确定删除「%s」吗？\n（只删本助手里的配置，不影响游戏或脚本本体）"
                                   % p.get("name")):
            return
        try:
            os.remove(p["_file"])
        except Exception as e:
            messagebox.showerror("删除失败", str(e))
        self.reload()
        self._render_cards()

    def add_plugin(self):
        if self.running or self._preflight_busy:
            return
        self.go("add", force=True)

    # ---------------- 添加向导 ----------------
    def build_add(self, root):
        t = self.t
        self._add_catalog = pc.load_catalog()
        self._add_games = self._add_catalog.get("games", [])

        head = tk.Frame(root, bg=t["bg"]); head.pack(fill="x", padx=26, pady=(22, 6))
        self._chip(head, "←  返回", lambda: self.go("home", force=True)).pack(side="left")
        tk.Label(head, text="添加游戏", bg=t["bg"], fg=t["fg"], font=F(20, True)).pack(side="left", padx=14)
        self._chip(head, "粘贴填充", lambda: self._open_quick_fill_dialog("add")).pack(side="right")

        wrap = tk.Frame(root, bg=t["bg"]); wrap.pack(fill="both", expand=True, padx=26, pady=8)
        form = tk.Frame(wrap, bg=t["bg"]); form.pack(fill="both", expand=True)
        self._add_fill_overrides = {}
        self._add_scan_token = 0

        tk.Label(form, text="选择游戏与脚本；切换选项时仅快速检测，「重新探测」深度搜索最多 10 秒。",
                 bg=t["bg"], fg=t["sub"], font=F(10), anchor="w").pack(anchor="w", pady=(0, 12))

        tk.Label(form, text="游戏", bg=t["bg"], fg=t["fg"], font=F(11, True), anchor="w").pack(anchor="w")
        self._add_game_var = tk.StringVar()
        game_names = [g["name"] for g in self._add_games]
        self._add_game_combo = ttk.Combobox(form, textvariable=self._add_game_var,
                                            values=game_names, state="readonly", font=F(10))
        self._add_game_combo.pack(fill="x", pady=(4, 10))
        if game_names:
            self._add_game_combo.current(0)

        tk.Label(form, text="脚本 / 助手", bg=t["bg"], fg=t["fg"], font=F(11, True), anchor="w").pack(anchor="w")
        self._add_script_var = tk.StringVar()
        self._add_script_combo = ttk.Combobox(form, textvariable=self._add_script_var,
                                              state="readonly", font=F(10))
        self._add_script_combo.pack(fill="x", pady=(4, 10))

        self._add_path_label = tk.Label(form, text="启动器路径", bg=t["bg"], fg=t["fg"],
                                        font=F(11, True), anchor="w")
        self._add_path_label.pack(anchor="w")
        pf = tk.Frame(form, bg=t["bg"]); pf.pack(fill="x", pady=(4, 4))
        self._add_path_var = tk.StringVar()
        self._add_path_entry = tk.Entry(pf, textvariable=self._add_path_var, font=F(10),
                                        bg=t["panel"], fg=t["fg"], insertbackground=t["fg"],
                                        relief="flat", highlightthickness=1,
                                        highlightbackground=t["line"], highlightcolor=t["accent"])
        self._add_path_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self._chip(pf, "重新探测", self._add_rescan).pack(side="left", padx=(6, 0))
        self._chip(pf, "浏览…", self._add_browse).pack(side="left", padx=(6, 0))
        self._add_path_status = tk.Label(form, text="", bg=t["bg"], fg=t["sub"], font=F(9), anchor="w")
        self._add_path_status.pack(anchor="w", pady=(0, 4))

        # 多候选路径按钮容器(≥2 个时才显示)
        self._add_candidates_frame = tk.Frame(form, bg=t["bg"])
        self._add_candidates_frame.pack(fill="x", pady=(0, 4))
        self._add_candidate_widgets = []

        self._add_check_frame = tk.Frame(form, bg=t["bg"])
        self._add_check_frame.pack(fill="x")
        self._add_check_vars = []

        # 「其他 / 自定义」专用面板(选到 custom 游戏时才 pack)
        self._add_custom_frame = tk.Frame(form, bg=t["bg"])

        # 路径/待办区域的所有可见控件,custom 模式下整体 pack_forget
        self._add_normal_widgets = [self._add_path_label, pf, self._add_path_status,
                                    self._add_candidates_frame, self._add_check_frame]

        bf = tk.Frame(form, bg=t["bg"]); bf.pack(fill="x", pady=20)
        self._add_save_btn = self._pill(bf, "保存并返回", self._save_add, primary=True)
        self._add_save_btn.pack(side="left")
        self._add_save_btn_row = bf

        self._add_game_combo.bind("<<ComboboxSelected>>", lambda e: self._add_on_game_change())
        self._add_script_combo.bind("<<ComboboxSelected>>", lambda e: self._add_on_script_change())
        self._add_on_game_change()

    def _add_selected_game(self):
        name = self._add_game_var.get()
        for g in self._add_games:
            if g.get("name") == name:
                return g
        return self._add_games[0] if self._add_games else None

    def _add_selected_script(self):
        game = self._add_selected_game()
        if not game:
            return None
        name = self._add_script_var.get()
        for s in game.get("scripts", []):
            if s.get("name") == name:
                return s
        scripts = game.get("scripts", [])
        return scripts[0] if scripts else None

    def _add_on_game_change(self):
        game = self._add_selected_game()
        if not game:
            return
        scripts = game.get("scripts", [])
        names = [s.get("name", "") for s in scripts]
        self._add_script_combo["values"] = names
        if names:
            self._add_script_combo.current(0)

        # 是否 custom 分支?切换 UI
        is_custom = (game.get("id") == "custom")
        self._add_apply_custom_mode(is_custom)
        if is_custom:
            return  # custom 分支不走后续脚本/checklist/rescan
        self._add_on_script_change()

    def _add_apply_custom_mode(self, is_custom):
        t = self.t
        if is_custom:
            # 隐藏常规控件
            for w in self._add_normal_widgets:
                try:
                    w.pack_forget()
                except Exception:
                    pass
            try:
                self._add_save_btn_row.pack_forget()
            except Exception:
                pass
            # 显示 custom 面板
            self._build_add_custom_frame()
            try:
                self._add_custom_frame.pack(fill="x", pady=(6, 0))
            except Exception:
                pass
        else:
            # 隐藏 custom 面板
            try:
                self._add_custom_frame.pack_forget()
            except Exception:
                pass
            # 重新显示常规控件(按原顺序)
            self._add_path_label.pack(anchor="w")
            self._add_normal_widgets[1].pack(fill="x", pady=(4, 4))  # pf
            self._add_path_status.pack(anchor="w", pady=(0, 4))
            self._add_candidates_frame.pack(fill="x", pady=(0, 4))
            self._add_check_frame.pack(fill="x")
            self._add_save_btn_row.pack(fill="x", pady=20)

    def _build_add_custom_frame(self):
        """构造 custom 分支的两选项 UI(懒建,避免重复)。"""
        t = self.t
        if getattr(self, "_add_custom_built", False):
            return
        f = self._add_custom_frame

        tk.Label(f, text="没找到你要用的脚本?两种方式添加:",
                 bg=t["bg"], fg=t["fg"], font=F(11, True), anchor="w").pack(anchor="w", pady=(6, 6))

        # 方式 1:基于已有预设
        opt1 = tk.Frame(f, bg=t["panel"], highlightthickness=1, highlightbackground=t["line"])
        opt1.pack(fill="x", pady=(0, 8), ipady=8)
        tk.Label(opt1, text="① 基于内置预设修改", bg=t["panel"], fg=t["fg"],
                 font=F(12, True), anchor="w").pack(anchor="w", padx=14, pady=(6, 2))
        tk.Label(opt1,
                 text="从下面挑一个和你的脚本最相似的:助手会复制它的等待模式、进程判定等设置作起点,"
                      "你之后只需在编辑页里改改进程名和路径。适合大多数「同类脚本」。",
                 bg=t["panel"], fg=t["sub"], font=F(9), anchor="w",
                 wraplength=780, justify="left").pack(anchor="w", padx=14, pady=(0, 6))

        row1 = tk.Frame(opt1, bg=t["panel"]); row1.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(row1, text="参考预设:", bg=t["panel"], fg=t["fg"], font=F(10)).pack(side="left")

        # 构造下拉:所有非 custom 游戏的第一个脚本
        refs = []  # list of (label, game_dict, script_dict)
        try:
            catalog = pc.load_catalog()
            for g in catalog.get("games", []):
                if g.get("id") == "custom":
                    continue
                for s in g.get("scripts", []):
                    refs.append(("%s · %s" % (g.get("name", ""), s.get("name", "")), g, s))
        except Exception:
            pass
        self._add_custom_ref_map = {label: (g, s) for label, g, s in refs}

        self._add_custom_ref_var = tk.StringVar()
        combo = ttk.Combobox(row1, textvariable=self._add_custom_ref_var,
                             values=[label for label, _, _ in refs],
                             state="readonly", font=F(10), width=40)
        combo.pack(side="left", padx=(6, 6), fill="x", expand=True)
        if refs:
            combo.current(0)

        self._pill(opt1, "复制这个预设并进入编辑页",
                   self._add_custom_use_reference, primary=True).pack(anchor="w", padx=14, pady=(2, 6))

        # 方式 2:完全手填
        opt2 = tk.Frame(f, bg=t["panel"], highlightthickness=1, highlightbackground=t["line"])
        opt2.pack(fill="x", ipady=8)
        tk.Label(opt2, text="② 完全手填", bg=t["panel"], fg=t["fg"],
                 font=F(12, True), anchor="w").pack(anchor="w", padx=14, pady=(6, 2))
        tk.Label(opt2,
                 text="从空白开始填全部字段。若你还没确定 wait_mode / 进程名等,建议先选 ①。",
                 bg=t["panel"], fg=t["sub"], font=F(9), anchor="w",
                 wraplength=780, justify="left").pack(anchor="w", padx=14, pady=(0, 6))
        self._pill(opt2, "新建空白配置并编辑",
                   self._add_custom_use_blank, primary=False).pack(anchor="w", padx=14, pady=(2, 6))

        self._add_custom_built = True

    def _add_custom_use_reference(self):
        label = self._add_custom_ref_var.get()
        pair = self._add_custom_ref_map.get(label) if hasattr(self, "_add_custom_ref_map") else None
        if not pair:
            messagebox.showwarning("提示", "请先选择一个参考预设。", parent=self)
            return
        game, script = pair
        # 用该脚本 build 一份新插件,但清空启动器和 preset_id,让用户当作自己的模板
        plugin = pc.build_plugin(game, script, "", order=pc.next_plugin_order())
        # 改名,避免和已有原预设重名
        plugin["name"] = "自定义 · 基于 " + plugin.get("name", "")
        # 标记为非预设(不再显示"更换预设"chip);保留 doc_url / 待办供参考
        plugin["preset_id"] = ""
        plugin["preset_game_id"] = ""
        pc.save_plugin_file(plugin)
        self.reload()
        self.open_edit(plugin)

    def _add_custom_use_blank(self):
        # 走原有 manual 分支
        catalog = pc.load_catalog()
        game = pc.get_game(catalog, "custom")
        script = pc.get_script(game, "manual") if game else None
        if not game or not script:
            messagebox.showwarning("提示", "预设目录缺少 custom/manual 项。", parent=self)
            return
        plugin = pc.build_plugin(game, script, "", order=pc.next_plugin_order())
        pc.save_plugin_file(plugin)
        self.reload()
        self.open_edit(plugin)

    def _add_on_script_change(self):
        for w in self._add_check_frame.winfo_children():
            w.destroy()
        self._add_check_vars = []
        script = self._add_selected_script()
        if not script:
            return
        self._add_rescan(quick=True)
        items = script.get("setup_checklist") or []
        if items:
            tk.Label(self._add_check_frame, text="脚本侧待办（勾选表示你已在脚本里完成）",
                     bg=self.t["bg"], fg=self.t["fg"], font=F(11, True), anchor="w").pack(anchor="w", pady=(12, 4))
            for item in items:
                var = tk.BooleanVar(value=False)
                self._add_check_vars.append((item, var))
                tk.Checkbutton(self._add_check_frame, text=item, variable=var,
                               bg=self.t["bg"], fg=self.t["fg"], selectcolor=self.t["panel"],
                               activebackground=self.t["bg"], activeforeground=self.t["accent"],
                               font=F(10), anchor="w", wraplength=720, justify="left").pack(anchor="w", pady=2)

    def _add_rescan(self, quick=False):
        script = self._add_selected_script()
        if not script:
            return
        if quick:
            roots = narrow_search_roots(BASE_DIR, self.settings)
            path, src = resolve_launcher(script, self.settings, roots, allow_glob=False)
            candidates = [path] if path else []
            self._add_apply_scan_result(candidates, src, timed_out=False)
            return

        self._add_scan_token += 1
        token = self._add_scan_token
        if hasattr(self, "_add_path_status") and self._add_path_status.winfo_exists():
            self._add_path_status.config(text="正在搜索路径…", fg=self.t["sub"])
        # 清空旧候选按钮
        self._clear_candidate_buttons()

        def worker():
            import time as _time
            roots = default_search_roots(BASE_DIR, self.settings)
            deadline_at = _time.monotonic() + 10
            candidates = resolve_all_candidates(script, roots, max_results=8, timeout_sec=10,
                                                settings=self.settings)
            timed_out = _time.monotonic() >= deadline_at
            self.ui_queue.put(("scan", token, candidates, timed_out))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_scan_result(self, token, candidates, timed_out):
        if token != self._add_scan_token:
            return
        if not hasattr(self, "_add_path_var"):
            return
        self._add_apply_scan_result(candidates, "glob" if candidates else "none", timed_out=timed_out)

    def _clear_candidate_buttons(self):
        if not hasattr(self, "_add_candidates_frame"):
            return
        if not self._add_candidates_frame.winfo_exists():
            return
        for w in self._add_candidates_frame.winfo_children():
            w.destroy()
        self._add_candidate_widgets = []

    def _add_apply_scan_result(self, candidates, src, timed_out=False):
        """
        candidates: list[str]  0/1/多 个路径
        src: cache|hint|glob|none
        timed_out: 是否是深度探测超时后返回
        """
        t = self.t
        self._clear_candidate_buttons()

        n = len(candidates)
        if n == 0:
            self._add_path_var.set("")
            if hasattr(self, "_add_path_status") and self._add_path_status.winfo_exists():
                if timed_out:
                    self._add_path_status.config(
                        text="搜索超过 10 秒未找到，请点「浏览…」手动选择",
                        fg=t["warn"])
                else:
                    self._add_path_status.config(
                        text="未找到，请点「浏览…」或「重新探测」",
                        fg=t["warn"])
            return

        # 有结果：把第一个填入 Entry
        first = candidates[0]
        self._add_path_var.set(first)

        # 单结果：显示来源
        if n == 1:
            labels = {
                "cache": "来自上次记录",
                "hint": "来自预设路径",
                "glob": "自动搜索到",
            }
            msg = labels.get(src, "已找到")
            if timed_out:
                msg = "已找到 1 个（搜索超时中止，若不对可点「浏览…」）"
            if hasattr(self, "_add_path_status") and self._add_path_status.winfo_exists():
                self._add_path_status.config(text=msg, fg=t["ok"])
            return

        # 多候选：在下方以按钮列表让用户选，第一个默认已填
        prefix = "找到 %d 个可能路径，" % n
        if timed_out:
            prefix += "（搜索超时中止）"
        msg = prefix + "已默认使用第 1 个；如果不对可点下方按钮切换或「浏览…」。"
        if hasattr(self, "_add_path_status") and self._add_path_status.winfo_exists():
            self._add_path_status.config(text=msg, fg=t["ok"])

        for i, path in enumerate(candidates, start=1):
            row = tk.Frame(self._add_candidates_frame, bg=t["bg"])
            row.pack(fill="x", pady=1)
            idx_lbl = tk.Label(row, text="%d." % i, bg=t["bg"], fg=t["sub"],
                               font=F(9), width=3, anchor="w")
            idx_lbl.pack(side="left")
            path_lbl = tk.Label(row, text=path, bg=t["bg"], fg=t["fg"],
                                font=("Consolas", 9), anchor="w", cursor="hand2")
            path_lbl.pack(side="left", fill="x", expand=True)
            path_lbl.bind("<Button-1>", lambda e, pp=path: self._add_pick_candidate(pp))
            self._chip(row, "使用这个", lambda pp=path: self._add_pick_candidate(pp)).pack(side="right", padx=(6, 0))
            self._add_candidate_widgets.append(row)

    def _add_pick_candidate(self, path):
        if not hasattr(self, "_add_path_var"):
            return
        self._add_path_var.set(path)
        if hasattr(self, "_add_path_status") and self._add_path_status.winfo_exists():
            self._add_path_status.config(text="已选择：%s" % path, fg=self.t["ok"])

    def _add_apply_path_result(self, path, src):
        """兼容旧调用位置：只是把单路径当 1 个候选走新流程。"""
        candidates = [path] if path else []
        self._add_apply_scan_result(candidates, src, timed_out=(src == "timeout"))

    def _add_browse(self):
        path = filedialog.askopenfilename(title="选择脚本/启动器程序",
                                          filetypes=[("可执行程序", "*.exe"), ("所有文件", "*.*")])
        if path:
            self._add_path_var.set(os.path.normpath(path))
            self._add_path_status.config(text="手动选择", fg=self.t["ok"])

    def _save_add(self):
        game = self._add_selected_game()
        script = self._add_selected_script()
        if not game or not script:
            messagebox.showwarning("提示", "请选择游戏与脚本。", parent=self)
            return
        launcher = self._add_path_var.get().strip().strip('"')
        if script.get("id") != "manual" and (not launcher or not os.path.isfile(launcher)):
            if not messagebox.askyesno("路径无效",
                                       "找不到有效的启动器路径，保存后运行时会被跳过。\n仍要保存吗？",
                                       parent=self):
                return
        done = [item for item, var in self._add_check_vars if var.get()]
        plugin = pc.build_plugin(game, script, launcher, checklist_done=done)
        for k, v in getattr(self, "_add_fill_overrides", {}).items():
            if k != "checklist_done":
                plugin[k] = v
        pc.save_plugin_file(plugin)
        sid = script.get("id", "")
        if launcher and sid and sid != "manual":
            update_path_cache(self.settings, sid, launcher)
            save_settings(self.settings)
        self.reload()
        if script.get("id") == "manual":
            self.open_edit(plugin)
        else:
            self.go("home", force=True)

    # ---------------- 首次向导 ----------------
    def build_first_run(self, root):
        t = self.t
        tk.Label(root, text="部署向导", bg=t["bg"], fg=t["fg"],
                 font=F(22, True)).pack(anchor="w", padx=26, pady=(28, 8))
        tk.Label(root, text="把多个游戏的自动脚本排队运行：一次只跑一个，跑完自动切换下一个。"
                            "按下面卡片逐款完成：官方下载安装 → 导入 → 一键配置，绿勾即就绪。",
                 bg=t["bg"], fg=t["sub"], font=F(11), anchor="w", wraplength=780).pack(
                     anchor="w", padx=26, pady=(0, 10))

        wrap = tk.Frame(root, bg=t["bg"])
        wrap.pack(fill="both", expand=True, padx=26, pady=(0, 4))
        cv = tk.Canvas(wrap, bg=t["bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=cv.yview, style="Vert.TScrollbar")
        cv.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y", padx=(6, 2))
        cv.pack(side="left", fill="both", expand=True)
        inner_wrap = tk.Frame(cv, bg=t["bg"])
        cv.create_window((0, 0), window=inner_wrap, anchor="nw", tags="fr_inner")
        inner_wrap.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: self._throttle(
            "_cvw_fr_inner", 80, lambda: self._sync_canvas_inner(cv, "fr_inner")))
        self._bind_wheel(cv)

        # 就绪进度总览
        try:
            games = pc.list_games(pc.load_catalog())
        except Exception:
            games = []
        imported = [g for g in games if self._wizard_plugin_for_game(g)]
        ready = [g for g in imported
                 if self._wizard_plugin_ready(self._wizard_plugin_for_game(g))]
        prog = self._wizard_card(inner_wrap, "部署进度")
        if imported:
            ratio = float(len(ready)) / float(len(imported))
            outer = tk.Frame(prog, bg=t["line"], height=8)
            outer.pack(fill="x", pady=(2, 6))
            if ratio > 0:
                tk.Frame(outer, bg=t["accent"], height=8).place(
                    relx=0, rely=0, relwidth=ratio, relheight=1)
            note = "" if len(games) <= len(imported) else \
                "，还有 %d 款未导入" % (len(games) - len(imported))
            tk.Label(prog, text="已就绪 %d / %d 款已导入的助手%s" % (
                len(ready), len(imported), note),
                bg=t["panel"], fg=(t["ok"] if len(ready) == len(imported) else t["fg"]),
                font=F(11, True), anchor="w").pack(anchor="w")
        else:
            tk.Label(prog, text="还没有导入任何助手 —— 先点卡片上的「官方下载」安装，再点「导入此游戏」。",
                     bg=t["panel"], fg=t["warn"], font=F(11, True), anchor="w",
                     wraplength=720, justify="left").pack(anchor="w")

        # 助手安装根目录（可选，提高自动搜索命中率）
        rootbox = self._wizard_card(inner_wrap, "助手安装根目录（可选）")
        tk.Label(rootbox, text="如果几款助手都装在同一个文件夹，指定它，自动搜索路径会更准更快。",
                 bg=t["panel"], fg=t["sub"], font=F(10), anchor="w",
                 wraplength=720, justify="left").pack(anchor="w", pady=(2, 4))
        erow = tk.Frame(rootbox, bg=t["panel"]); erow.pack(fill="x")
        self._wizard_root_var = tk.StringVar(value=get_assistants_root(self.settings))
        tk.Entry(erow, textvariable=self._wizard_root_var, font=F(10), width=52,
                 bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["fg"],
                 relief="flat").pack(side="left", ipady=4)
        self._chip(erow, "浏览…", self._wizard_pick_root).pack(side="left", padx=(8, 0))
        if get_assistants_root(self.settings):
            self._chip(erow, "清除", self._wizard_clear_root).pack(side="left", padx=(6, 0))

        # 每款游戏一张卡片
        for g in games:
            self._wizard_game_card(inner_wrap, g)

        tk.Label(inner_wrap, text="使用即表示您已阅读并同意免责声明（见「使用帮助」或 DISCLAIMER.md）。",
                 bg=t["bg"], fg=t["warn"], font=F(9), anchor="w", wraplength=780).pack(
                     anchor="w", pady=(12, 0))

        bf = tk.Frame(root, bg=t["bg"]); bf.pack(fill="x", padx=26, pady=(12, 20))
        self._pill(bf, "进入主页", self._first_run_finish, primary=True).pack(side="left")
        self._chip(bf, "一键导入常用四套", self._first_run_import).pack(side="left", padx=10)
        self._chip(bf, "打开使用帮助", lambda: self.go("help", force=True)).pack(side="left")

    def _wizard_card(self, parent, title, status_text="", status_color=None):
        """向导卡片：标题 + 右侧状态徽标，返回内容容器。"""
        t = self.t
        box = tk.Frame(parent, bg=t["panel"], highlightthickness=1, highlightbackground=t["line"])
        box.pack(fill="x", pady=6, ipady=10)
        inner = tk.Frame(box, bg=t["panel"])
        inner.pack(fill="x", padx=20, pady=6)
        top = tk.Frame(inner, bg=t["panel"]); top.pack(fill="x")
        tk.Label(top, text=title, bg=t["panel"], fg=t["fg"], font=F(13, True),
                 anchor="w").pack(side="left")
        if status_text:
            tk.Label(top, text=status_text, bg=t["panel"],
                     fg=status_color or t["sub"], font=F(10, True)).pack(side="right")
        return inner

    def _wizard_plugin_for_game(self, game):
        gid = game.get("id", "")
        for p in self.plugins:
            if p.get("preset_game_id", "") == gid:
                return p
        return None

    def _wizard_plugin_ready(self, p, checks=None):
        if not p:
            return False
        launcher = p.get("launcher", "")
        if not launcher or not os.path.isfile(launcher):
            return False
        if checks is None:
            checks = assistant_setup.verify_for_plugin(p)
        return bool(checks) and all(c.get("ok") for c in checks)

    def _open_url(self, url):
        if not url:
            return
        try:
            webbrowser.open(url, new=2)
        except Exception:
            try:
                if os.name == "nt":
                    os.startfile(url)
            except Exception:
                pass

    def _wizard_game_card(self, parent, game):
        t = self.t
        gname = game.get("name", "")
        scripts = game.get("scripts", [])
        sname = scripts[0].get("name", "") if scripts else ""
        p = self._wizard_plugin_for_game(game)
        title = ("%s · %s" % (gname, sname)) if sname else gname

        if p is None:
            inner = self._wizard_card(parent, title, "未导入", t["sub"])
            tk.Label(inner, text="还没使用这款脚本？点「官方下载」安装好后再点「导入此游戏」。",
                     bg=t["panel"], fg=t["sub"], font=F(10), anchor="w",
                     wraplength=720, justify="left").pack(anchor="w", pady=(2, 2))
            btns = tk.Frame(inner, bg=t["panel"]); btns.pack(fill="x", pady=(2, 0))
            self._pill(btns, "导入此游戏并检测路径",
                       lambda g=game: self._wizard_import_game(g)).pack(side="left")
            self._wizard_dl_buttons(btns, game, first_padx=10)
            return

        launcher_ok = bool(p.get("launcher")) and os.path.isfile(p.get("launcher", ""))
        supported = p.get("preset_id", "") in assistant_setup.SUPPORTED_PRESET_IDS
        checks = assistant_setup.verify_for_plugin(p) if launcher_ok else []
        ready = self._wizard_plugin_ready(p, checks)
        status = "✓ 就绪" if ready else ("待设置路径" if not launcher_ok else "待配置")
        color = t["ok"] if ready else (t["warn"] if launcher_ok else t["err"])
        inner = self._wizard_card(parent, title, status, color)

        if launcher_ok and checks:
            for c in checks:
                row = tk.Frame(inner, bg=t["panel"]); row.pack(fill="x", pady=1)
                tk.Label(row, text=("✓" if c.get("ok") else "△"), bg=t["panel"],
                         fg=(t["ok"] if c.get("ok") else t["warn"]),
                         font=F(10, True)).pack(side="left")
                tk.Label(row, text=c.get("name", ""), bg=t["panel"], fg=t["fg"],
                         font=F(10), anchor="w").pack(side="left", padx=(6, 0))
                if c.get("hint"):
                    tk.Label(row, text="（%s）" % c["hint"], bg=t["panel"], fg=t["sub"],
                             font=F(9), anchor="w", wraplength=560,
                             justify="left").pack(side="left", padx=(4, 0))
        elif not launcher_ok:
            tk.Label(inner, text="还没找到启动器程序 —— 先安装助手，再点「重新检测」；"
                                 "装在冷门位置就点「浏览…」手动指定。",
                     bg=t["panel"], fg=t["sub"], font=F(10), anchor="w",
                     wraplength=720, justify="left").pack(anchor="w", pady=(2, 0))

        # 一键配置后的结果回显
        res = getattr(self, "_wizard_result", {}).get(p.get("preset_id", ""))
        if res:
            rbox = tk.Frame(inner, bg=t["panel"]); rbox.pack(fill="x", pady=(4, 0))
            if res.get("applied"):
                tk.Label(rbox, text="✓ 已自动写入：%s" % "、".join(res["applied"]),
                         bg=t["panel"], fg=t["ok"], font=F(10), anchor="w",
                         wraplength=700, justify="left").pack(anchor="w")
            if res.get("error"):
                tk.Label(rbox, text=res["error"], bg=t["panel"], fg=t["err"],
                         font=F(10), anchor="w", wraplength=700,
                         justify="left").pack(anchor="w")
            for m in res.get("manual") or []:
                tk.Label(rbox, text="△ 还需人工：%s" % m, bg=t["panel"], fg=t["warn"],
                         font=F(10), anchor="w", wraplength=700,
                         justify="left").pack(anchor="w")

        btns = tk.Frame(inner, bg=t["panel"]); btns.pack(fill="x", pady=(6, 0))
        if launcher_ok and supported:
            self._pill(btns, "一键配置", lambda pl=p: self._wizard_apply_setup(pl)).pack(side="left")
        if launcher_ok:
            self._chip(btns, "重新检测", lambda pl=p: self._wizard_rescan(pl)).pack(side="left", padx=(8, 0))
            self._chip(btns, "浏览…", lambda pl=p: self._wizard_browse(pl)).pack(side="left", padx=(6, 0))
            self._chip(btns, "编辑", lambda pl=p: self.open_edit(pl)).pack(side="left", padx=(6, 0))
            if assistant_setup.list_backups(p.get("preset_id", "")):
                self._chip(btns, "还原备份", lambda pl=p: self._wizard_restore(pl)).pack(
                    side="left", padx=(6, 0))
        self._wizard_dl_buttons(btns, game, first_padx=8)

    def _wizard_dl_buttons(self, parent, game, first_padx=8):
        dl = game.get("download_url") or game.get("doc_url")
        if dl:
            self._chip(parent, "↗ 官方下载", lambda u=dl: self._open_url(u)).pack(
                side="left", padx=(first_padx, 0))
        doc = game.get("doc_url")
        if doc and doc != dl:
            self._chip(parent, "使用文档", lambda u=doc: self._open_url(u)).pack(
                side="left", padx=(6, 0))

    def _wizard_import_game(self, game):
        gid = game.get("id", "")
        scripts = game.get("scripts", [])
        sid = scripts[0].get("id", "") if scripts else ""
        try:
            plugin = pc.resolve_and_build(gid, sid, self.settings)
        except Exception as e:
            messagebox.showerror("导入失败", str(e), parent=self)
            return
        if not plugin.get("launcher"):
            go_on = messagebox.askyesno(
                "未找到启动器",
                "没有自动找到 %s 的启动器。\n\n已安装好了？点「是」手动选择启动器程序；\n"
                "还没安装？点「否」，先点「官方下载」安装后再来导入。" % game.get("name", ""),
                parent=self)
            if not go_on:
                return
            override = filedialog.askopenfilename(title="选择启动器程序（exe）", parent=self)
            if not override:
                return
            try:
                plugin = pc.resolve_and_build(gid, sid, self.settings,
                                              launcher_override=override)
            except Exception as e:
                messagebox.showerror("导入失败", str(e), parent=self)
                return
        pc.save_plugin_file(plugin)
        if plugin.get("launcher"):
            update_path_cache(self.settings, sid, plugin.get("launcher"))
            save_settings(self.settings)
        self.reload()
        self.go("first_run", force=True)

    def _wizard_apply_setup(self, plugin):
        r = assistant_setup.apply_for_plugin(plugin)
        if not hasattr(self, "_wizard_result"):
            self._wizard_result = {}
        self._wizard_result[plugin.get("preset_id", "")] = r
        if r.get("ok") and r.get("applied"):
            self._enqueue_log("「%s」已写入推荐配置：%s" % (
                plugin.get("name", ""), "、".join(r["applied"])), level="info")
        self.go("first_run", force=True)

    def _wizard_rescan(self, plugin):
        pid = plugin.get("preset_id", "")
        script = None
        try:
            script = pc.find_script_by_preset_id(pc.load_catalog(), pid)
        except Exception:
            script = None
        if not script:
            messagebox.showinfo("重新检测", "没有这款脚本的预设信息，请点「浏览…」手动指定。",
                                parent=self)
            return
        self._wizard_scan_token = getattr(self, "_wizard_scan_token", 0) + 1
        token = self._wizard_scan_token

        def worker():
            roots = default_search_roots(BASE_DIR, self.settings)
            candidates = resolve_all_candidates(script, roots, max_results=5,
                                                timeout_sec=10, settings=self.settings)
            self.ui_queue.put(("wizard_scan", token, pid, candidates, False))

        threading.Thread(target=worker, daemon=True).start()

    def _wizard_apply_scan(self, token, preset_id, candidates, timed_out):
        if token != getattr(self, "_wizard_scan_token", -1):
            return
        p = next((x for x in self.plugins if x.get("preset_id", "") == preset_id), None)
        if not p:
            return
        if candidates:
            path = os.path.normpath(candidates[0])
            p["launcher"] = path
            save_plugin(p)
            update_path_cache(self.settings, preset_id, path)
            save_settings(self.settings)
            self.reload()
            self._enqueue_log("「%s」已自动定位启动器：%s" % (p.get("name", ""), path),
                              level="info")
        else:
            messagebox.showinfo(
                "未找到启动器",
                "自动搜索没有找到「%s」的启动器。\n\n"
                "确认已安装后，点「浏览…」手动选择安装目录里的启动器程序；\n"
                "或者先在上方设置「助手安装根目录」再重新检测。" % p.get("name", ""),
                parent=self)
            return
        self.go("first_run", force=True)

    def _wizard_browse(self, plugin):
        init = get_assistants_root(self.settings)
        if not init or not os.path.isdir(init):
            cur = plugin.get("launcher", "") or ""
            d = os.path.dirname(cur)
            init = d if d and os.path.isdir(d) else BASE_DIR
        picked = filedialog.askopenfilename(title="选择启动器程序（exe）",
                                            initialdir=init, parent=self)
        if not picked:
            return
        plugin["launcher"] = os.path.normpath(picked)
        save_plugin(plugin)
        update_path_cache(self.settings, plugin.get("preset_id", ""), plugin["launcher"])
        save_settings(self.settings)
        self.reload()
        self.go("first_run", force=True)

    def _wizard_restore(self, plugin):
        pid = plugin.get("preset_id", "")
        backups = assistant_setup.list_backups(pid)
        if not backups:
            messagebox.showinfo("还原备份", "没有可还原的备份。", parent=self)
            return
        latest, name = backups[0]
        if not messagebox.askyesno(
                "还原备份",
                "把「%s」的配置恢复到最近一次一键配置之前的备份？\n\n备份时间：%s\n当前配置会被覆盖。"
                % (plugin.get("name", ""), assistant_setup.backup_time_label(latest)),
                parent=self):
            return
        files = assistant_setup.restore_backup(latest)
        if files:
            messagebox.showinfo("还原备份",
                                "已还原 %d 个文件：\n%s" % (
                                    len(files),
                                    "\n".join(os.path.basename(f) for f in files)),
                                parent=self)
            self._enqueue_log("「%s」已还原一键配置备份（%s）" % (
                plugin.get("name", ""), name), level="info")
        else:
            messagebox.showerror("还原备份", "还原失败，请检查文件是否被占用。", parent=self)
        self.go("first_run", force=True)

    def _wizard_pick_root(self):
        d = filedialog.askdirectory(title="选择助手安装根目录", parent=self)
        if not d:
            return
        self.settings["assistants_root"] = os.path.normpath(d)
        save_settings(self.settings)
        self.go("first_run", force=True)

    def _wizard_clear_root(self):
        self.settings["assistants_root"] = ""
        save_settings(self.settings)
        self.go("first_run", force=True)

    def _settings_pick_root(self):
        d = filedialog.askdirectory(title="选择助手安装根目录", parent=self)
        if not d:
            return
        self.settings["assistants_root"] = os.path.normpath(d)
        save_settings(self.settings)
        self.go("settings", force=True)

    def _settings_clear_root(self):
        self.settings["assistants_root"] = ""
        save_settings(self.settings)
        self.go("settings", force=True)

    def _first_run_import(self):
        pc.import_default_plugins(self.settings)
        save_settings(self.settings)
        self.reload()
        self.go("first_run", force=True)

    def _first_run_finish(self):
        self.settings["first_run_done"] = True
        save_settings(self.settings)
        self.go("home", force=True)

    # ---------------- 运行 ----------------
    def _refresh_run_buttons(self):
        if not hasattr(self, "global_start_btn") or not self.global_start_btn.winfo_exists():
            return
        t = self.t
        busy = self.running or self._preflight_busy
        can_start_here = self.current_view not in ("add", "edit", "first_run")
        self.global_start_btn.config(state=("normal" if not busy and can_start_here else "disabled"))
        can_stop = self.running and self.run_state.get("state") != "stopping"
        self.global_stop_btn.config(state=("normal" if can_stop else "disabled"))
        if busy:
            self.global_start_btn.config(bg=t["line"], fg=t["sub"])
            self.global_start_btn._base = t["line"]
        else:
            self.global_start_btn.config(bg=t["accent"], fg=t["on_accent"])
            self.global_start_btn._base = t["accent"]
        self.global_stop_btn.config(bg=(t["err"] if self.running else t["panel"]),
                                    fg=("#ffffff" if self.running else t["sub"]))
        self.global_stop_btn._base = t["err"] if self.running else t["panel"]
        self._refresh_card_controls()
        self._update_global_run_bar()

    def _refresh_card_controls(self):
        state = "disabled" if (self.running or self._preflight_busy) else "normal"
        for refs in getattr(self, "_cards", []):
            for control in refs.get("controls", []):
                if control.winfo_exists():
                    control.config(state=state)
            handle = refs.get("handle")
            if handle and handle.winfo_exists():
                handle.config(cursor=("arrow" if state == "disabled" else "fleur"),
                              fg=(self.t["line"] if state == "disabled" else self.t["sub"]))

    def _update_global_run_bar(self):
        if not hasattr(self, "global_run_title") or not self.global_run_title.winfo_exists():
            return
        t = self.t
        state = self.run_state.get("state", "idle")
        index = int(self.run_state.get("index", 0) or 0)
        total = int(self.run_state.get("total", 0) or 0)
        name = self.run_state.get("name", "")
        message = self.run_state.get("message", "") or "就绪"
        parallel_names = self.run_state.get("parallel_names") or []
        if parallel_names:
            message = "%s · ⇉ 并行：%s" % (message, "、".join(parallel_names))
        if self._preflight_busy:
            title, detail, color = "正在运行前检查", "检查路径、权限和进程占用…", t["accent"]
        elif state in ("running", "stopping"):
            title = ("%d/%d  %s" % (index, total, name)) if total else (name or "任务运行中")
            detail = message
            color = t["warn"] if state == "stopping" else t["ok"]
        elif state == "finished":
            title, detail, color = "本轮任务已结束", message, t["sub"]
        else:
            title, detail, color = "任务未运行", "准备好后可在任意页面开始", t["sub"]
        self.global_run_title.config(text=title)
        self.global_run_detail.config(text=" · " + detail)
        self.global_state_dot.config(fg=color)
        self.global_progress.config(maximum=max(1, total), value=min(total, index))

    def start_run(self):
        if self.running or self._preflight_busy:
            return
        active = [p for p in self.plugins if p.get("enabled", True)]
        if not active:
            messagebox.showwarning("无法开始", "没有勾选任何游戏，请至少开启一个。", parent=self)
            return
        # 未开自动切换且当前非 16:9:提醒(开源脚本普遍只适配 16:9)
        if display_ctrl.parse_target(self.settings.get("run_resolution", "off")) is None:
            cur = display_ctrl.current_resolution()
            if cur and abs(cur[0] / cur[1] - 16 / 9) > 0.02:
                if not messagebox.askyesno(
                        "分辨率提示",
                        "当前分辨率 %d×%d 不是 16:9，开源脚本可能无法运行。\n"
                        "可在设置中写入 run_resolution（如 \"1920x1080\"）开启自动切换。\n仍要继续吗？" % cur,
                        parent=self):
                    return

        self._preflight_token += 1
        token = self._preflight_token
        self._set_preflight_busy(True)
        self.update_idletasks()

        def worker():
            issues = preflight.check_plugins(active)
            self.ui_queue.put(("preflight", token, active, issues))

        threading.Thread(target=worker, daemon=True).start()

    def _set_preflight_busy(self, busy):
        self._preflight_busy = busy
        self._refresh_run_buttons()
        if busy:
            self.update_idletasks()

    def _finish_preflight(self, token, active, issues):
        if token != self._preflight_token:
            return
        self._set_preflight_busy(False)
        if self.running:
            return

        if preflight.has_blocking_errors(issues):
            messagebox.showwarning("无法开始", issues[0].get("message", "没有可运行的游戏。"), parent=self)
            return
        warns = [i for i in issues if i.get("level") == "warn"]
        if warns:
            lines = []
            for i in warns:
                prefix = ("「%s」" % i["plugin_name"]) if i.get("plugin_name") else ""
                lines.append("%s%s" % (prefix, i.get("message", "")))
            if not messagebox.askyesno("运行前提示",
                                       "发现以下情况，仍要继续吗？\n\n" + "\n".join(lines),
                                       parent=self):
                return

        self._clear_log(confirm=False)
        self.stop_event.clear()
        self.running = True
        self._run_started_at = datetime.datetime.now()
        self._run_tasks = []
        self._run_log_buffer = []
        self._run_log_dropped = 0
        self.run_state = {
            "state": "running", "index": 0, "total": len(active),
            "name": "", "message": "正在启动任务队列", "result": None,
            "parallel_names": [],
        }
        self._refresh_run_buttons()

        def worker():
            # 运行时分辨率(适配只支持 16:9 的开源脚本):开跑前切换,
            # 结束/停止/异常都经 finally 恢复;崩溃兜底由状态文件+下次启动恢复
            display_switched = False
            target = display_ctrl.parse_target(self.settings.get("run_resolution", "off"))
            if target:
                ok, msg = display_ctrl.apply_for_run(*target)
                if ok:
                    display_switched = True
                    self._enqueue_log(msg)
                else:
                    self._enqueue_log("[警告] %s(脚本可能无法运行)" % msg, level="warn")
            runner = runner_core.Runner(self._enqueue_log, self.stop_event,
                                        self._enqueue_run_event,
                                        daily_state_file=DAILY_STATE_FILE)
            try:
                runner.run_all(active)
            except Exception as e:
                self._enqueue_log("发生错误：%s" % e, level="error")
            finally:
                if display_switched:
                    done, msg = display_ctrl.restore_if_needed()
                    self._enqueue_log(msg if done else "[警告] %s" % msg,
                                      level=None if done else "warn")
            self.log_queue.put(("__DONE__", None, None))

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def stop_run(self):
        if not self.running or self.run_state.get("state") == "stopping":
            return
        self.stop_event.set()
        self.run_state["state"] = "stopping"
        self.run_state["message"] = "正在结束当前等待…"
        self._refresh_run_buttons()
        self._enqueue_log("已请求停止，正在结束当前等待…", level="warn")

    def _enqueue_log(self, msg, level=None):
        self.log_queue.put(("line", msg, level))

    def _enqueue_run_event(self, event):
        self.ui_queue.put(("run_event", event))

    def _apply_run_event(self, event):
        kind = event.get("type")
        active_state = "stopping" if self.stop_event.is_set() else "running"
        parallel_names = self.run_state.setdefault("parallel_names", [])
        if kind == "queue_started":
            n_parallel = int(event.get("parallel_total", 0) or 0)
            self.run_state.update(state=active_state, total=event.get("total", 0),
                                  index=0, parallel_names=[],
                                  message=("任务队列已开始（并行 %d 个）" % n_parallel)
                                  if n_parallel else "任务队列已开始")
        elif kind == "task_started" and event.get("parallel"):
            name = event.get("name", "")
            if name and name not in parallel_names:
                parallel_names.append(name)
            self.run_state.update(state=active_state,
                                  message="并行任务「%s」启动" % name)
        elif kind == "task_finished" and event.get("parallel"):
            name = event.get("name", "")
            if name in parallel_names:
                parallel_names.remove(name)
            result = event.get("result", "")
            stored = result
            if stored == "completed":
                stored = event.get("task_status") or stored
            self._run_tasks.append((name, stored))
            labels = {"completed": "已完成", "skipped": "已跳过",
                      "failed": "启动失败", "stopped": "已停止"}
            self.run_state.update(state=active_state,
                                  message="并行任务「%s」%s" % (name, labels.get(result, "已结束")))
        elif kind == "task_started":
            self.run_state.update(state=active_state, index=event.get("index", 0),
                                  total=event.get("total", 0), name=event.get("name", ""),
                                  message="正在检查配置")
        elif kind == "stage_changed":
            if event.get("parallel"):
                return  # 并行任务不占据运行栏标题位
            self.run_state.update(state=active_state, index=event.get("index", 0),
                                  total=event.get("total", 0), name=event.get("name", ""),
                                  message=event.get("message", "运行中"))
        elif kind == "task_finished":
            labels = {"completed": "已完成", "skipped": "已跳过", "failed": "启动失败", "stopped": "已停止"}
            # md 日志摘要用关键词判定结果（task_status）而非脚本是否跑完
            # （result），否则「脚本正常跑完但每日未完成」会在摘要里显示 ✅。
            stored = event.get("result", "")
            if stored == "completed":
                stored = event.get("task_status") or stored
            self._run_tasks.append((event.get("name", ""), stored))
            self.run_state.update(index=event.get("index", 0), total=event.get("total", 0),
                                  name=event.get("name", ""),
                                  message=labels.get(event.get("result"), "已结束"))
        elif kind == "queue_finished":
            result = event.get("result", "completed")
            self.run_state.update(state="finished", result=result,
                                  index=int(self.run_state.get("total", 0) or 0),
                                  parallel_names=[],
                                  message=("用户已停止本轮任务" if result == "stopped"
                                           else "全部任务执行完成"))
        self._update_global_run_bar()

    def _log_tag_for(self, msg, level=None):
        """日志着色：结构化级别优先，无级别时回退到旧的关键字匹配。"""
        if level:
            tag = {
                "error": "log_err",
                "warn": "log_warn",
                "gold": "log_gold",
                "blue": "log_blue",
                "ok": "log_ok",
            }.get(level)
            if tag:
                return tag
        if "[每日未完成]" in msg:
            return "log_err"
        if "[每日完成]" in msg:
            return "log_gold"
        if "[体力]" in msg:
            return "log_blue"
        if any(k in msg for k in ("[跳过]", "[失败]", "未找到启动器", "未配置启动器", "配置不完整")):
            return "log_err"
        if "[警告]" in msg:
            return "log_warn"
        if ("==========" in msg) or ("────────" in msg) or ("任务结果 ·" in msg) or ("结果输出完毕" in msg):
            return "log_ok"
        if msg.startswith(("# ", "## ", "### ")) or msg.startswith("```"):
            # 导入的 md 日志：标题与代码块围栏用主题绿显示
            return "log_ok"
        return None

    def _render_log_store(self):
        if not self.log_widget or not self.log_widget.winfo_exists():
            return
        self._log_inserting = True
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", "end")
        view = self.log_store.lines[-LOG_VIEW_LINES:]
        for tag, payload in group_tagged_lines(view, self._log_tag_for):
            self.log_widget.insert("end", payload, tag or ())
        self.log_widget.config(state="disabled")
        if self.log_follow:
            self.log_widget.see("end")
        self.after_idle(self._finish_log_insert)
        self._update_log_toolbar()

    def _insert_log_batch(self, lines, overflow=0):
        if not lines or not self.log_widget or not self.log_widget.winfo_exists():
            self._update_log_toolbar()
            return
        self._log_inserting = True
        self.log_widget.config(state="normal")
        if overflow:
            self.log_widget.delete("1.0", "%d.0" % (overflow + 1))
        for tag, payload in group_tagged_lines(lines, self._log_tag_for):
            self.log_widget.insert("end", payload, tag or ())
        # 界面内只保留最近 LOG_VIEW_LINES 行（须在 state=normal 下删，disabled
        # 会静默无效），越界头部整行裁掉；窗口缩放的重排开销随行数下降
        view_lines = int(float(self.log_widget.index("end-1c")))
        extra = view_lines - LOG_VIEW_LINES
        if extra > 0:
            self.log_widget.delete("1.0", "%d.0" % (extra + 1))
        self.log_widget.config(state="disabled")
        if self.log_follow:
            self.log_widget.see("end")
        self.after_idle(self._finish_log_insert)
        self._update_log_toolbar()

    def _finish_log_insert(self):
        self._log_inserting = False

    def _log_yview(self, *args):
        if self.log_widget and self.log_widget.winfo_exists():
            self.log_widget.yview(*args)
            self._sync_log_follow_from_view()

    def _on_log_scroll(self, first, last):
        if hasattr(self, "_log_scrollbar") and self._log_scrollbar.winfo_exists():
            self._log_scrollbar.set(first, last)
        if not self._log_inserting:
            at_bottom = float(last) >= 0.999
            if self.log_follow != at_bottom:
                self.log_follow = at_bottom
                self._update_log_toolbar()

    def _on_log_mousewheel(self, event):
        self.log_follow = False
        self.after_idle(self._sync_log_follow_from_view)

    def _sync_log_follow_from_view(self):
        if self.log_widget and self.log_widget.winfo_exists():
            self.log_follow = self.log_widget.yview()[1] >= 0.999
            self._update_log_toolbar()

    def _resume_log_follow(self):
        self.log_follow = True
        if self.log_widget and self.log_widget.winfo_exists():
            self.log_widget.see("end")
        self._update_log_toolbar()

    def _update_log_toolbar(self):
        if hasattr(self, "log_follow_btn") and self.log_follow_btn.winfo_exists():
            text = ("● 跟随最新" if self.log_follow else "○ 已暂停 · 跟随最新")
            if text != self.log_follow_btn.cget("text"):
                self.log_follow_btn.config(
                    text=text,
                    fg=(self.t["ok"] if self.log_follow else self.t["warn"]),
                )
        if hasattr(self, "log_count_lbl") and self.log_count_lbl.winfo_exists():
            # 刷屏时节流：行数至多每 200ms 刷新一次，避免每批日志都重绘标签。
            if not getattr(self, "_log_count_job", None):
                self._log_count_job = self.after(200, self._flush_log_count)

    def _flush_log_count(self):
        self._log_count_job = None
        if hasattr(self, "log_count_lbl") and self.log_count_lbl.winfo_exists():
            dropped = self.log_store.dropped_total
            suffix = (" · 已丢弃较早 %d 行" % dropped) if dropped else ""
            self.log_count_lbl.config(text="%d 行%s" % (len(self.log_store.lines), suffix))

    def _copy_log(self):
        text = ""
        if self.log_widget and self.log_widget.winfo_exists():
            try:
                text = self.log_widget.get("sel.first", "sel.last")
            except tk.TclError:
                text = self.log_store.export_text()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _clear_log(self, confirm=True):
        if confirm and self.log_store.lines:
            if not messagebox.askyesno("清空日志", "确定清空当前运行日志吗？", parent=self):
                return
        self.log_store.clear()
        self.log_follow = True
        if self.log_widget and self.log_widget.winfo_exists():
            self._render_log_store()

    def _export_log(self):
        if not self.log_store.lines:
            messagebox.showinfo("导出日志", "当前没有可以导出的日志。", parent=self)
            return
        default_name = "运行日志_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            title="导出运行日志", parent=self, defaultextension=".txt",
            initialfile=default_name, filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
                f.write(self.log_store.export_text())
            messagebox.showinfo("导出完成", "日志已保存到：\n%s" % path, parent=self)
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self)

    def _drain_log(self):
        start = time.perf_counter()
        try:
            for _ in range(100):
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "preflight":
                    self._finish_preflight(item[1], item[2], item[3])
                elif kind == "scan":
                    self._apply_scan_result(item[1], item[2], item[3])
                elif kind == "wizard_scan":
                    self._wizard_apply_scan(item[1], item[2], item[3], item[4])
                elif kind == "run_event":
                    self._apply_run_event(item[1])
                if (time.perf_counter() - start) >= 0.012:
                    break
        except queue.Empty:
            pass

        lines = []
        done = False
        try:
            while len(lines) < 1000 and (time.perf_counter() - start) < 0.020:
                item = self.log_queue.get_nowait()
                kind = item[0]
                if kind == "__DONE__":
                    done = True
                elif len(item) >= 3:
                    lines.append((str(item[1]).rstrip("\r\n"), item[2]))
                else:
                    lines.append((str(item[1]).rstrip("\r\n"), None))
        except queue.Empty:
            pass

        if lines:
            overflow = self.log_store.append_many(lines)
            self._insert_log_batch(lines, overflow)
            self._run_log_buffer.extend(lines)
            excess = len(self._run_log_buffer) - RUN_LOG_BUFFER_MAX
            if excess > 0:
                del self._run_log_buffer[:excess]
                self._run_log_dropped += excess
        if done:
            self.running = False
            if self.run_state.get("state") not in ("finished",):
                self.run_state.update(state="finished", message="本轮任务已结束")
            self._save_run_log()
            self._refresh_run_buttons()

        pending = not self.log_queue.empty() or not self.ui_queue.empty()
        # 33ms 节奏足够流畅（约 30 次/秒），比 16ms 明显降低重排版频率；
        # 吞吐靠单次最多 1000 行补偿，刷屏时依旧跟得上。
        interval = 33 if (pending or self._preflight_busy) else 80
        self.after(interval, self._drain_log)

    # ---------------- 日志自动保存 / 导入查看 ----------------

    def _save_run_log(self):
        """本轮运行结束后追加保存到今天的 md 文件，并按保留策略清理过期文件。"""
        if self._run_started_at is None:
            return
        try:
            lines = [text for text, _ in self._run_log_buffer]
            if self._run_log_dropped:
                lines.insert(0, "⚠ 本次运行日志共约 %d 行，超过保留上限，较早的 %d 行已省略。"
                             % (self._run_log_dropped + len(lines), self._run_log_dropped))
            result = self.run_state.get("result") or "completed"
            if result == "completed" and self._run_tasks and any(
                    r != "completed" for _, r in self._run_tasks):
                result = "partial"   # md 标题不再把有未完成的一轮标成「全部完成」
            end_dt = datetime.datetime.now()
            record_no = log_saver.today_record_count(LOG_DIR, now=end_dt) + 1
            record = log_saver.build_run_markdown(
                record_no, self._run_started_at, end_dt, result, self._run_tasks, lines)
            path, _ = log_saver.append_run_record(LOG_DIR, record, now=end_dt)
            removed = log_saver.cleanup_old_logs(
                LOG_DIR, log_saver.retention_days(self.settings.get("log_retention", "month")))
            self._enqueue_log("日志已自动保存：%s（今天第 %d 次运行%s）" % (
                os.path.basename(path), record_no,
                "，已清理 %d 个过期文件" % removed if removed else ""))
        except Exception as e:
            self._enqueue_log("自动保存日志失败：%s" % e, level="error")
        finally:
            self._run_started_at = None

    def _open_log_dir(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            os.startfile(LOG_DIR)
        except OSError as e:
            messagebox.showerror("打开失败", str(e), parent=self)

    def _import_log(self):
        path = filedialog.askopenfilename(
            title="导入日志文件",
            filetypes=[("Markdown/日志", "*.md *.txt *.log"), ("所有文件", "*.*")],
        )
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
                messagebox.showerror("导入失败", str(e), parent=self)
                return
        # 超大文件只保留尾部展示，避免查看窗口一次性插入卡死界面
        view_lines = text.splitlines()
        if len(view_lines) > 20000:
            view_lines = view_lines[-20000:]
            view_lines.insert(0, "⚠ 文件过大（共 %d 行），仅显示最后 20000 行。" % len(text.splitlines()))
            text = "\n".join(view_lines)
        self._show_log_viewer(os.path.basename(path), text)

    def _show_log_viewer(self, title, text):
        """独立只读窗口展示导入的日志，保留按级别的着色。"""
        t = self.t
        win = tk.Toplevel(self)
        win.title("日志查看 · %s" % title)
        win.configure(bg=t["bg"])
        win.geometry("980x640")
        win.minsize(640, 420)
        win.transient(self)

        head = tk.Frame(win, bg=t["bg"]); head.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(head, text=title, bg=t["bg"], fg=t["fg"], font=F(12, True)).pack(side="left")
        self._button(head, "复制全部", lambda: self._viewer_copy(win), compact=True).pack(
            side="right", padx=(6, 0))
        self._button(head, "关闭", win.destroy, compact=True).pack(side="right", padx=(6, 0))

        body = tk.Frame(win, bg=t["log_bg"], highlightthickness=1, highlightbackground=t["line"])
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        txt = tk.Text(body, bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["fg"],
                      font=(_FAMILY, 11), relief="flat", padx=12, pady=10,
                      highlightthickness=0, wrap="none")
        sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview, style="Vert.TScrollbar")
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        win._viewer_txt = txt

        for tag, fg in (("log_err", t["err"]), ("log_warn", t["warn"]),
                        ("log_gold", t["log_gold"]), ("log_blue", t["log_blue"]),
                        ("log_ok", t["ok"])):
            txt.tag_configure(tag, foreground=fg)
        for tag, payload in group_tagged_lines(text.splitlines(), self._log_tag_for):
            txt.insert("end", payload, tag or ())
        txt.configure(state="disabled")
        win.after(1, lambda: win.focus_set())

    def _viewer_copy(self, win):
        txt = getattr(win, "_viewer_txt", None)
        if not txt or not txt.winfo_exists():
            return
        text = txt.get("1.0", "end-1c")
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)


HELP_TEXT = """欢迎使用「游戏串行一键长草助手」

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【免责声明】（使用前必读）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  本工具仅为本地「排队启动」第三方开源脚本，不是任何游戏官方产品。
  • 不读取/修改游戏内存，不分发第三方脚本 exe，需自行从官方渠道下载。
  • 第三方脚本可能违反游戏用户协议，存在封号等风险，由您自行承担。
  • 本工具按「现状」提供，作者不对账号损失等后果负责。
  • 完整声明见程序目录 DISCLAIMER.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

这是什么？
  把多个游戏的自动脚本「排队」运行：一次只跑一个，跑完并关闭后自动启动下一个。
  适合配置较低、内存有限的电脑挂机。

三步上手
  1) 在「主页」点每行左侧的 开/关，决定要不要跑。
  2) 拖动每行左侧「≡」，或用 ▲ ▼ 调整运行先后顺序。
  3) 点底部「▶ 开始运行」，剩下交给电脑。

运行日志
  • 拖动游戏队列与日志之间的分隔条，可自由调整日志高度。
  • 点「专注」让日志铺满右侧内容区；再次点击返回。
  • 每次运行结束自动保存到 logs\\YYYY-MM-DD.md（一天多次运行用分割线隔开），
    设置页可调整保留时长：最近一周 / 最近一个月 / 不清理。
  • 「导入」可打开保存的 md 日志或任意文本日志，在独立窗口查看；
    「目录」直接打开日志文件夹。
  • 向上滚动会暂停自动跟随，点「跟随最新」即可恢复。
  • 支持复制、清空和导出；界面最多保留最近 10000 行。

添加游戏（推荐）
  点「＋ 添加游戏」→ 选游戏与脚本 → 路径自动探测 → 勾选脚本侧待办 → 保存。
  若列表为空，首次打开可「一键导入四套默认游戏」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【已适配脚本 · 官方下载】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  以下链接均为各项目官方发布页，请自行辨别版本与安全：

  原神 · BetterGI（一条龙）
    https://github.com/babalae/better-genshin-impact/releases
    文档：https://www.bettergi.com/

  崩铁 · March7th Assistant
    https://github.com/moesnow/March7thAssistant/releases
    文档：https://m7a.top/

  绝区零 · OneDragon
    https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/releases
    文档：https://one-dragon.com/zzz/zh/home.html

  明日方舟 · MAA
    https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases
    文档：https://docs.maa.plus/

  明日方舟：终末地 · MaaEnd（PC 端）
    https://github.com/MaaXYZ/MaaEnd/releases
    注意：MaaEnd 自身启动游戏有 bug，请在编辑页「高级选项 → 前置程序」
    填游戏本体 Endfield.exe，助手会先开游戏、等几十秒再启动 MaaEnd。

  鸣潮 · ok-ww（-t 1 -e 日常一条龙）
    https://github.com/ok-oldking/ok-wuthering-waves/releases
    请下载 setup.exe 安装包，勿下 Source code

  重返未来1999 · M9A（MaaPiCli -d）
    https://github.com/MAA1999/M9A/releases
    文档：https://1999.fan/zh_cn/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【暂未接入串行 · 有知名脚本但无法稳定「跑完退出」】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • 碧蓝航线 Alas — 7×24 调度 + Python 环境，无简单 one-shot CLI
    https://github.com/LmeSzinc/AzurLaneAutoScript
  • 阴阳师 OAS — GUI/Server 调度，无标准跑完退出命令
    https://github.com/runhey/OnmyojiAutoScript
  • 尘白禁区 SAA — 支持 --auto 但助手进程不会自动退出
    https://github.com/LaoZhuJackson/SnowbreakAutoAssistant

  若上述项目日后提供「任务完成自动退出」CLI，可在 catalog 中扩展。

脚本侧待办（卡片黄色提示）
  未完成可能影响脚本运行或无法自动切换下一个。开始运行后，日志会以黄色输出
  具体待办项与修改方法（编辑页按说明设置 → 勾选待办）。

运行前自检
  开始运行前会检查：是否勾选游戏、管理员权限、路径是否存在、进程是否已在运行。
  警告不会阻止保存，但建议按提示处理后再跑。

设置（左下角）
  可切换主题配色、修改字体与字号，设置会自动记忆。

小提示
  • 建议双击「一键长草助手.exe」以管理员身份打开（首次会 UAC 提示），部分脚本需要管理员权限。
  • 运行中可随时点「■ 停止」；切换页面不会中断运行。
  • 编辑页可展开「高级选项」手动改进程名与启动参数。
  • 长路径会自动省略，鼠标停在路径或游戏名上可查看完整内容。
  • 粘贴填充见「粘贴填充」弹窗内样例。
"""


if __name__ == "__main__":
    App().mainloop()
