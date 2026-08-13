# -*- coding: utf-8 -*-
"""
串行执行引擎（与界面解耦）。

负责：按顺序启动每个已启用的游戏插件，等待其完成，再进行下一个。
界面通过传入 log 回调 与 stop 事件 来显示日志、随时中止。

进程等待两种模式：
  - "game"  ：先等游戏进程出现，再等其消失（助手跑完会关游戏），最后杀掉助手进程。
  - "helper"：直接等助手进程自己退出（适用于 MAA 这类：游戏在模拟器里、助手跑完自关）。
"""

import os
import time
import subprocess
import datetime
import inspect

try:
    import ctypes
except Exception:
    ctypes = None

try:
    import preset_catalog as _preset_catalog
except ImportError:
    _preset_catalog = None

try:
    import log_watcher as _log_watcher
except ImportError:
    _log_watcher = None

# 让所有内部命令（tasklist/taskkill）不弹出黑色控制台窗口
CREATE_NO_WINDOW = 0x08000000

# 结构化日志级别（界面据此着色，不再依赖日志文字里的魔法标记）
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"
LEVEL_OK = "ok"
LEVEL_GOLD = "gold"
LEVEL_BLUE = "blue"


def _func_accepts_kwarg(func, name):
    """判断 log 回调是否接受额外的 level 关键字参数（旧回调只有 msg 也能用）。"""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD or p.name == name:
            return True
    return False

if ctypes and os.name == "nt":
    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]


def _snapshot_via_toolhelp():
    """Windows API 枚举进程，比反复 tasklist 快且不占 UI 线程。"""
    names = set()
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE = ctypes.c_void_p(-1).value
    snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE:
        return None
    try:
        pe = _PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if not ctypes.windll.kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            return None
        while True:
            names.add(pe.szExeFile.lower())
            if not ctypes.windll.kernel32.Process32NextW(snap, ctypes.byref(pe)):
                break
        return names
    finally:
        ctypes.windll.kernel32.CloseHandle(snap)


def _hidden_kwargs():
    kw = dict(capture_output=True, text=True, encoding="gbk", errors="ignore")
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kw["startupinfo"] = si
        kw["creationflags"] = CREATE_NO_WINDOW
    return kw


def now_str():
    return datetime.datetime.now().strftime("%H:%M:%S")


def _tasklist_running(image_name):
    """判断给定进程名是否在运行（Windows tasklist，无黑窗口）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq %s" % image_name],
            **_hidden_kwargs()
        )
        return image_name.lower() in (out.stdout or "").lower()
    except Exception:
        return False


def snapshot_running_processes():
    """返回当前进程 image name 小写集合。"""
    if os.name == "nt" and ctypes:
        names = _snapshot_via_toolhelp()
        if names is not None:
            return names
    names = set()
    try:
        out = subprocess.run(
            ["tasklist"],
            timeout=8,
            **_hidden_kwargs(),
        )
        for line in (out.stdout or "").splitlines():
            parts = line.split()
            if parts and parts[0].lower().endswith(".exe"):
                names.add(parts[0].lower())
    except Exception:
        pass
    return names


def _kill(image_name, log, label="助手", level=LEVEL_INFO):
    try:
        subprocess.run(["taskkill", "/f", "/im", image_name], **_hidden_kwargs())
        log("  已关闭%s进程：%s" % (label, image_name), level=level)
    except Exception as e:
        log("  关闭 %s 失败：%s" % (image_name, e), level=LEVEL_WARN)


def plugin_skip_reason(p):
    """未配置好则返回跳过原因，否则 None。"""
    launcher = (p.get("launcher") or "").strip().strip('"')
    if not launcher:
        return "未配置启动器路径"
    if not os.path.isfile(launcher):
        return "启动器不存在：%s" % launcher
    return None


def build_pre_cmd(pre, pre_args, method="explorer"):
    """
    组装前置程序启动命令。

    默认走 explorer 代理：由资源管理器（普通权限、标准父进程链）拉起目标，
    与手动双击完全一致，避免继承助手的管理员令牌触发反作弊（如终末地 ACE）。
    explorer 无法转发参数：带参数或 method="direct" 时直接启动。
    """
    pre_args = list(pre_args or [])
    if method == "direct" or pre_args:
        return [pre] + pre_args, "direct"
    windir = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    return [os.path.join(windir, "explorer.exe"), pre], "explorer"


class Runner:
    def __init__(self, log_func, stop_event=None, event_func=None, settle_sec=1.0):
        self.log = log_func
        self.stop_event = stop_event
        self.event_func = event_func
        # 任务结束后给脚本日志落盘留出的缓冲秒数（最终 poll 前等待）
        self.settle_sec = max(0.0, float(settle_sec))
        self._log_accepts_level = _func_accepts_kwarg(log_func, "level")

    def _emit(self, event_type, **payload):
        """发送结构化运行事件；界面回调失败不能打断串行任务。"""
        if not self.event_func:
            return
        event = {"type": event_type}
        event.update(payload)
        try:
            self.event_func(event)
        except Exception:
            pass

    def _stage(self, stage, message, **payload):
        payload.update({"stage": stage, "message": message})
        self._emit("stage_changed", **payload)

    def _stopped(self):
        return self.stop_event is not None and self.stop_event.is_set()

    def _log(self, msg, level=LEVEL_INFO):
        """输出日志；兼容只接受 msg 的旧回调。"""
        if self._log_accepts_level:
            self.log(msg, level=level)
        else:
            self.log(msg)

    def _tlog(self, msg, level=LEVEL_INFO):
        """带时间戳输出。"""
        self._log("[%s] %s" % (now_str(), msg), level)

    def _log_checklist_warnings(self, p):
        """未完成脚本侧待办时输出警告（界面会以黄色显示）。"""
        if not _preset_catalog:
            return
        pending = _preset_catalog.pending_checklist_items(p)
        if not pending:
            return
        name = p.get("name", p.get("id", "未知"))
        doc = (p.get("doc_url") or "").strip()
        self._tlog("[警告] %s 有 %d 项脚本侧设置未完成，可能影响运行或无法自动切换下一个：" % (
            name, len(pending)), level=LEVEL_WARN)
        for i, item in enumerate(pending, 1):
            self._tlog("[警告]   %d. %s" % (i, item), level=LEVEL_WARN)
        self._tlog("[警告]   修改方法：主页点该游戏「编辑」→ 按待办说明在脚本内完成设置 → 勾选待办。",
                   level=LEVEL_WARN)
        if doc:
            self._tlog("[警告]   官方文档：%s" % doc, level=LEVEL_WARN)

    def run_all(self, plugins):
        """plugins：已按 order 排序、且只含 enabled 的插件 dict 列表。"""
        total = len(plugins)
        self._emit("queue_started", total=total)
        self._tlog("开始串行执行，共 %d 个游戏。" % total)
        self._log("")
        for idx, p in enumerate(plugins, 1):
            if self._stopped():
                self._tlog("已被用户中止。", level=LEVEL_WARN)
                self._emit("queue_finished", result="stopped", total=total)
                return
            name = p.get("name", p.get("id", "未知"))
            self._emit("task_started", index=idx, total=total, name=name)
            result = self._run_one(idx, total, p)
            self._emit("task_finished", index=idx, total=total, name=name, result=result)
            self._log("")
            if result == "stopped":
                self._tlog("已被用户中止。", level=LEVEL_WARN)
                self._emit("queue_finished", result="stopped", total=total)
                return
        self._tlog("全部任务执行完成。", level=LEVEL_OK)
        self._emit("queue_finished", result="completed", total=total)

    def _run_one(self, idx, total, p):
        name = p.get("name", p.get("id", "未知"))
        self._tlog("========== (%d/%d) %s ==========" % (idx, total, name), level=LEVEL_OK)
        event_base = {"index": idx, "total": total, "name": name}
        self._stage("checking", "正在检查配置", **event_base)

        skip = plugin_skip_reason(p)
        if skip:
            self._tlog("[跳过] %s — %s" % (name, skip), level=LEVEL_ERROR)
            return "skipped"

        self._log_checklist_warnings(p)

        pre = (p.get("pre_launcher") or "").strip().strip('"')
        if pre:
            self._stage("preparing", "正在启动前置程序", **event_base)
            self._run_pre_launch(p, pre)
            if self._stopped():
                return "stopped"

        launcher = p.get("launcher", "").strip().strip('"')
        args = p.get("args", [])
        cmd = [launcher] + list(args)
        workdir = os.path.dirname(launcher)
        try:
            self._stage("launching", "正在启动脚本", **event_base)
            subprocess.Popen(cmd, cwd=workdir)
            self._tlog("[启动] %s %s" % (os.path.basename(launcher), " ".join(args)))
        except Exception as e:
            self._tlog("[失败] 启动出错：%s" % e, level=LEVEL_ERROR)
            return "failed"

        wait_mode = p.get("wait_mode", "game")
        helper_procs = p.get("helper_processes", [])

        watcher = self._start_log_watcher(p)
        tick = watcher.poll if watcher else None

        if wait_mode == "helper":
            # 等助手自己退出
            self._stage("waiting", "等待助手运行完成", **event_base)
            self._tlog("[等待] 等待助手运行完成并自动退出...")
            self._wait_until_all_gone(helper_procs, on_tick=tick)
            stopped = self._stopped()
            self._report_task_result(p, watcher)
            # 收尾：脚本没帮忙关游戏时兜底关闭
            for gp in p.get("game_processes", []):
                if _tasklist_running(gp):
                    _kill(gp, self._tlog, label="游戏")
            if not stopped:
                self._tlog("[完成] %s" % name, level=LEVEL_OK)
            return "stopped" if stopped else "completed"

        # wait_mode == "game"
        game_procs = p.get("game_processes", [])
        timeout_min = int(p.get("start_timeout_min", 15))
        self._stage("waiting_start", "等待游戏启动", **event_base)
        self._tlog("[等待] 游戏启动中（最多 %d 分钟）..." % timeout_min)
        appeared = self._wait_until_any_appear(game_procs, timeout_min, on_tick=tick)
        stopped = self._stopped()
        if not stopped and not appeared:
            self._tlog("[提示] 超时未检测到游戏进程，可能本次无任务或已直接结束，继续下一步。")
        elif not stopped:
            self._stage("running", "游戏运行中，等待任务完成", **event_base)
            self._tlog("[运行] 游戏已启动，等待助手完成并关闭游戏...")
            self._wait_until_all_gone(game_procs, on_tick=tick)
            stopped = self._stopped()
        self._report_task_result(p, watcher)
        # 收尾：关闭助手进程
        for hp in helper_procs:
            _kill(hp, self._tlog)
        if not stopped:
            self._tlog("[完成] %s" % name, level=LEVEL_OK)
        return "stopped" if stopped else "completed"

    def _run_pre_launch(self, p, pre):
        """先启动前置程序（如游戏本体），供 MaaEnd 这类无法自行开游戏的脚本使用。"""
        pre_name = os.path.basename(pre)
        if not os.path.isfile(pre):
            self._tlog("[警告] 前置程序不存在，已跳过：%s" % pre, level=LEVEL_WARN)
            return
        pre_args = [str(a) for a in (p.get("pre_args") or [])]
        skip_if_running = bool(p.get("pre_skip_if_running", True))
        if skip_if_running and _tasklist_running(pre_name):
            self._tlog("[前置] %s 已在运行，跳过启动。" % pre_name)
            return
        method = (p.get("pre_launch_method") or "explorer").strip().lower()
        cmd, used = build_pre_cmd(pre, pre_args, method)
        try:
            subprocess.Popen(cmd, cwd=os.path.dirname(pre))
            if used == "explorer":
                self._tlog("[前置] 已通过 explorer 代理启动（普通权限，同手动双击）：%s" % pre_name)
            else:
                self._tlog("[前置] 已启动：%s %s" % (pre_name, " ".join(pre_args)))
        except Exception as e:
            self._tlog("[警告] 前置程序启动失败：%s" % e, level=LEVEL_WARN)
            return
        delay = 0
        try:
            delay = int(p.get("pre_delay_sec", 0) or 0)
        except Exception:
            delay = 0
        if delay > 0:
            self._tlog("[前置] 等待 %d 秒让游戏就绪，再启动脚本..." % delay)
            self._sleep_interruptible(delay)

    def _sleep_interruptible(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._stopped():
                return
            time.sleep(min(1.0, max(0.0, deadline - time.time())))

    # ---------- 脚本日志监控（任务结果汇总） ----------

    def _start_log_watcher(self, p):
        """按插件配置启动日志监控；未配置或文件不可用时返回 None。"""
        if not _log_watcher or not (p.get("log_file") or "").strip():
            return None
        watcher = _log_watcher.ScriptLogWatcher(
            log_file=p.get("log_file"),
            encoding=p.get("log_encoding", "auto"),
            daily_done_patterns=p.get("daily_done_patterns") or [],
            daily_pending_patterns=p.get("daily_pending_patterns") or [],
            stamina_patterns=p.get("stamina_patterns") or [],
        )
        if watcher.start():
            self._tlog("[日志] 正在监控脚本日志：%s" % watcher.path)
            return watcher
        self._tlog("[日志] 未找到日志文件：%s" % p.get("log_file"))
        return None

    def _report_task_result(self, p, watcher):
        """脚本退出后输出任务结果：每日奖励完成/未完成 + 最新体力剩余。

        只输出配置了提取关键词的分类；输出前等 settle_sec 让脚本最后几行
        日志落盘，并强制 poll 一次，避免最后一截日志漏读。
        """
        if watcher is None:
            return
        if not self._stopped() and self.settle_sec > 0:
            self._sleep_interruptible(self.settle_sec)
        watcher.poll()  # 确保读完最后一截增量
        result = watcher.finish()
        name = p.get("name", p.get("id", "未知"))

        sections = []
        if p.get("daily_done_patterns"):
            sections.append(("daily_done", "  🎁 [每日完成] 每日奖励 · 已完成：", LEVEL_GOLD))
        if p.get("daily_pending_patterns"):
            sections.append(("daily_pending", "  ❌ [每日未完成] 每日奖励 · 未完成/未领取：", LEVEL_ERROR))
        if p.get("stamina_patterns"):
            sections.append(("stamina", "  ⚡ [体力] 剩余体力/理智：", LEVEL_BLUE))
        if not sections:
            # 配了日志文件但没配任何提取关键词：不输出结果区，避免纯噪音
            return
        self._tlog("──────── 任务结果 · %s ────────" % name, level=LEVEL_OK)
        truncated = result.get("truncated", {})
        for key, title, level in sections:
            self._log(title, level=level)
            lines = result.get(key) or []
            if lines:
                for line in lines:
                    self._log("    · %s" % line, level=level)
            else:
                self._log("    · 未捕捉到相关记录", level=level)
            if truncated.get(key):
                self._log("    · （匹配行过多，仅显示最新 %d 条）" % watcher.max_per_category,
                          level=level)
        self._tlog("──────── 结果输出完毕 ────────", level=LEVEL_OK)

    def _wait_until_any_appear(self, procs, timeout_min, on_tick=None):
        if on_tick:
            on_tick()  # 即使进程列表为空也至少 poll 一次，避免日志完全没被读
        if not procs:
            return False
        deadline = time.time() + timeout_min * 60
        while time.time() < deadline:
            if self._stopped():
                return False
            if on_tick:
                on_tick()
            for proc in procs:
                if _tasklist_running(proc):
                    return True
            time.sleep(2)
        return False

    def _wait_until_all_gone(self, procs, on_tick=None):
        if on_tick:
            on_tick()  # 即使进程列表为空也至少 poll 一次
        if not procs:
            return
        while True:
            if self._stopped():
                return
            if on_tick:
                on_tick()
            if not any(_tasklist_running(proc) for proc in procs):
                return
            time.sleep(5)


# ---------- 管理员权限相关 ----------

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False
