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
import json
import time
import threading
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


# 预设任务完成状态（与 log_watcher 的 task_status 对应）
TASK_COMPLETED = "completed"
TASK_INCOMPLETE = "incomplete"
TASK_UNKNOWN = "unknown"

# 游戏服务器每日重置时刻（凌晨 4 点）：4 点前属于上一个服务器日
DAILY_RESET_HOUR = 4

# 多个并行任务之间的启动间隔（秒）：错峰拉起，避免同时开多个模拟器挤爆 CPU/磁盘
PARALLEL_STAGGER_SEC = 3.0


def split_queue(plugins):
    """按 parallel 字段把已启用的插件分成（并行组，串行组），各自保持原顺序。"""
    parallel = [p for p in plugins if p.get("parallel")]
    serial = [p for p in plugins if not p.get("parallel")]
    return parallel, serial


def server_day(dt):
    """游戏服务器日：以凌晨 4 点为界，4 点前属于上一个自然日。"""
    return (dt - datetime.timedelta(hours=DAILY_RESET_HOUR)).date()


def resolve_daily_repeat(task_status, last_done_dt, now_dt):
    """同一服务器日内已完成过的任务再次运行时，「未完成」降级为「已完成」。

    返回 (status, repeated)。白天领取过每日奖励后，当天再跑一次，
    脚本检测不到可领取内容会报「未领取」——这是预期现象，不是失败。

    返回值：
      status    调整后的任务状态（仅 TASK_INCOMPLETE 可能被降级）
      repeated  是否发生了同日重复降级（界面据此改用 ℹ️ 措辞而非 ❌ 报警）
    """
    if task_status != TASK_INCOMPLETE or last_done_dt is None:
        return task_status, False
    if server_day(last_done_dt) == server_day(now_dt):
        return TASK_COMPLETED, True
    return task_status, False


class DailyDoneState:
    """记录每个游戏最近一次判定「已完成」的时间，JSON 持久化（跨重启）。

    path 为 None 时仅保存在内存中（测试用），不落盘。
    """

    def __init__(self, path=None):
        self.path = path
        self._lock = threading.Lock()  # 并行任务线程会并发记录完成状态
        self._done = {}
        self._load()

    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            games = data.get("games") if isinstance(data, dict) else None
            if isinstance(games, dict):
                self._done = {str(k): v for k, v in games.items()
                              if isinstance(v, str)}
        except Exception:
            self._done = {}

    def last_done(self, key):
        """返回该游戏最近一次完成时间（datetime）；无记录/损坏返回 None。"""
        raw = self._done.get(str(key))
        if not raw:
            return None
        try:
            return datetime.datetime.fromisoformat(raw)
        except ValueError:
            return None

    def mark_done(self, key, dt=None):
        with self._lock:
            self._done[str(key)] = (dt or datetime.datetime.now()).isoformat(
                timespec="seconds")
            self._save()

    def _save(self):
        if not self.path:
            return
        tmp = "%s.tmp" % self.path
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "games": self._done}, f,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass


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
    def __init__(self, log_func, stop_event=None, event_func=None, settle_sec=1.0,
                 daily_state_file=None):
        self.log = log_func
        self.stop_event = stop_event
        self.event_func = event_func
        # 任务结束后给脚本日志落盘留出的缓冲秒数（最终 poll 前等待）
        self.settle_sec = max(0.0, float(settle_sec))
        self._log_accepts_level = _func_accepts_kwarg(log_func, "level")
        self._last_task_status = None
        # 并行任务线程各自的日志前缀与最终状态（线程本地，互不干扰）
        self._tls = threading.local()
        # 同服务器日重复运行判定所需的完成记录（不传则仅内存，测试用）
        self.daily_state = DailyDoneState(daily_state_file)

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
        """输出日志；兼容只接受 msg 的旧回调。并行任务线程自动带名字前缀。"""
        prefix = getattr(self._tls, "prefix", "")
        if prefix:
            msg = prefix + msg
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
        """plugins：已按 order 排序、且只含 enabled 的插件 dict 列表。

        带 parallel=True 的任务（模拟器/后台类脚本，不抢鼠标）在队列开始时
        同时启动，与串行任务并行执行；其余任务仍按顺序逐个运行。
        串行 + 并行全部结束后才输出汇总。
        """
        parallel_plugins, serial_plugins = split_queue(plugins)
        total_serial = len(serial_plugins)
        n_parallel = len(parallel_plugins)
        self._emit("queue_started", total=total_serial, parallel_total=n_parallel)
        if n_parallel:
            self._tlog("开始执行：共 %d 个游戏，其中 %d 个并行同时启动。"
                       % (len(plugins), n_parallel))
        else:
            self._tlog("开始串行执行，共 %d 个游戏。" % total_serial)
        self._log("")

        summary_rows = []
        incomplete = 0
        results_lock = threading.Lock()
        parallel_results = []  # [(name, result, task_status)]
        threads = []
        for j, p in enumerate(parallel_plugins):
            t = threading.Thread(
                target=self._run_parallel_plugin,
                args=(j, p, parallel_results, results_lock,
                      PARALLEL_STAGGER_SEC * j),
                daemon=True)
            threads.append(t)
            t.start()

        stopped_early = False
        for idx, p in enumerate(serial_plugins, 1):
            if self._stopped():
                self._tlog("已被用户中止。", level=LEVEL_WARN)
                stopped_early = True
                break
            name = p.get("name", p.get("id", "未知"))
            self._emit("task_started", index=idx, total=total_serial, name=name)
            out = {}
            result = self._run_one(idx, total_serial, p, out=out)
            task_status = out.get("task_status") or TASK_UNKNOWN
            if result in ("failed", "skipped"):
                task_status = TASK_INCOMPLETE
            if task_status == TASK_INCOMPLETE:
                incomplete += 1
            summary_rows.append((name, task_status))
            self._emit("task_finished", index=idx, total=total_serial, name=name, result=result,
                       task_status=task_status)
            self._log("")
            if result == "stopped":
                self._tlog("已被用户中止。", level=LEVEL_WARN)
                stopped_early = True
                break

        # 串行队列结束（完成或被中止）后，等全部并行任务收尾
        for t in threads:
            t.join()
        if not serial_plugins and self._stopped():
            self._tlog("已被用户中止。", level=LEVEL_WARN)
            stopped_early = True

        for name, result, task_status in parallel_results:
            if result in ("failed", "skipped"):
                task_status = TASK_INCOMPLETE
            if task_status == TASK_INCOMPLETE:
                incomplete += 1
            summary_rows.append((name, task_status))

        if stopped_early:
            self._emit("queue_finished", result="stopped", total=total_serial)
            return
        self._log_daily_summary(summary_rows)
        if incomplete:
            if n_parallel:
                self._tlog("全部队列执行完毕：有 %d 个游戏任务未完成。" % incomplete, level=LEVEL_WARN)
            else:
                self._tlog("串行队列执行完毕：有 %d 个游戏任务未完成。" % incomplete, level=LEVEL_WARN)
        else:
            self._tlog("全部任务执行完成。", level=LEVEL_OK)
        self._emit("queue_finished", result="completed", total=total_serial)

    def _run_parallel_plugin(self, j, p, results, lock, delay_sec):
        """并行任务线程体：错峰启动 → 执行 → 结果写入共享列表。"""
        name = p.get("name", p.get("id", "未知"))
        if self._stopped():
            result, task_status = "stopped", TASK_UNKNOWN
        else:
            if delay_sec > 0:
                self._tlog("[并行] %s 将在 %d 秒后启动..." % (name, int(delay_sec)))
                self._sleep_interruptible(delay_sec)
            self._emit("task_started", index=0, total=0, name=name, parallel=True)
            out = {}
            try:
                result = self._run_one(j + 1, 0, p, parallel=True, out=out)
                task_status = out.get("task_status") or TASK_UNKNOWN
                if result in ("failed", "skipped"):
                    task_status = TASK_INCOMPLETE
            except Exception as e:
                self._tlog("[失败] %s 发生错误：%s" % (name, e), level=LEVEL_ERROR)
                result, task_status = "failed", TASK_INCOMPLETE
            self._emit("task_finished", index=0, total=0, name=name, result=result,
                       task_status=task_status, parallel=True)
        with lock:
            results.append((name, result, task_status))

    def _run_one(self, idx, total, p, parallel=False, out=None):
        name = p.get("name", p.get("id", "未知"))
        self._last_task_status = None
        self._tls.final_status = None
        if parallel:
            # 并行任务的所有日志行加名字前缀：多任务日志交错时仍可分辨归属
            self._tls.prefix = "[%s] " % name
            self._tlog("========== ⇉ [并行] %s ==========" % name, level=LEVEL_OK)
        else:
            self._tlog("========== (%d/%d) %s ==========" % (idx, total, name), level=LEVEL_OK)
        event_base = {"index": idx, "total": total, "name": name}
        if parallel:
            event_base["parallel"] = True
        try:
            return self._run_one_body(idx, total, p, name, event_base)
        finally:
            if parallel:
                self._tls.prefix = ""
            if out is not None:
                out["task_status"] = getattr(self._tls, "final_status", None)

    def _run_one_body(self, idx, total, p, name, event_base):
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
        log_configured = bool((p.get("log_file") or "").strip())
        helper_procs = p.get("helper_processes", [])

        watcher = self._start_log_watcher(p)
        tick = watcher.poll if watcher else None

        if wait_mode == "helper":
            # 等助手自己退出
            self._stage("waiting", "等待助手运行完成", **event_base)
            self._tlog("[等待] 等待助手运行完成并自动退出...")
            self._wait_until_all_gone(helper_procs, on_tick=tick)
            stopped = self._stopped()
            task_status = self._report_task_result(p, watcher) or TASK_UNKNOWN
            # 收尾：脚本没帮忙关游戏时兜底关闭
            for gp in p.get("game_processes", []):
                if _tasklist_running(gp):
                    _kill(gp, self._tlog, label="游戏")
            if not stopped:
                self._log_task_final(name, task_status, log_configured)

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
        task_status = self._report_task_result(p, watcher)
        task_status = task_status or TASK_UNKNOWN
        if not stopped and not appeared and task_status == TASK_UNKNOWN:
            # 游戏进程从未出现，日志也无法给出结论：宁可报未完成，也不假装完成
            task_status = TASK_INCOMPLETE
        # 收尾：关闭助手进程
        for hp in helper_procs:
            _kill(hp, self._tlog)
        if not stopped:
            self._log_task_final(name, task_status, log_configured)

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

    def _report_task_result_legacy(self, p, watcher):
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

    def _report_task_result(self, p, watcher):
        """脚本退出后汇总日志提取结果。

        返回预设任务完成状态：TASK_COMPLETED / TASK_INCOMPLETE /
        TASK_UNKNOWN；未启动日志监控时返回 None（由调用方按 unknown 处理）。

        这里只输出实际匹配到的证据行，不再为每个未命中的分类打印
        「未捕捉到相关记录」——旧逻辑会在已完成时同时打印红色未完成行，
        用户无法一眼看出任务到底完成没有。最终结论由 _log_task_final 输出。
        """
        if watcher is None:
            return None
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
            # 配了日志文件但没配任何提取关键词：无法判断，交给 _log_task_final 提示
            return TASK_UNKNOWN

        status = result.get("task_status")
        if status not in (TASK_COMPLETED, TASK_INCOMPLETE, TASK_UNKNOWN):
            if _log_watcher and hasattr(_log_watcher, "resolve_task_status"):
                status = _log_watcher.resolve_task_status(
                    result.get("daily_done") or [],
                    result.get("daily_pending") or [],
                    done_configured=bool(p.get("daily_done_patterns")),
                    pending_configured=bool(p.get("daily_pending_patterns")),
                )
            else:
                status = TASK_UNKNOWN

        status, repeated = self._apply_daily_repeat(p, status)

        done_lines = result.get("daily_done") or []
        self._tlog("──────── 任务结果 · %s ────────" % name, level=LEVEL_OK)
        if status == TASK_COMPLETED and done_lines and (result.get("daily_pending") or []):
            self._log("  ℹ️ [判定说明] 完成与未完成关键词都出现，按已完成处理（部分脚本完成后会复查奖励）。",
                      level=LEVEL_WARN)
        truncated = result.get("truncated", {})
        for key, title, level in sections:
            lines = result.get(key) or []
            if not lines:
                continue
            if key == "daily_pending" and status == TASK_COMPLETED and done_lines:
                # 崩铁等脚本完成后会再次检测奖励并打印「未检测到」；
                # 这是复查记录，不是未完成，所以不再用红色 ❌ 显示。
                self._log("  ℹ️ [复查记录] 完成后复查（不是未完成）：", level=LEVEL_WARN)
                for line in lines:
                    self._log("    · %s" % line, level=LEVEL_WARN)
                if truncated.get(key):
                    self._log("    · （匹配行过多，仅显示最新 %d 条）" % watcher.max_per_category,
                              level=LEVEL_WARN)
                continue
            if key == "daily_pending" and repeated:
                # 同一服务器日内已完成过：脚本此时必然无可领取内容，
                # 「未领取」是预期现象，用 ℹ️ 说明代替红色 ❌ 报警。
                self._log("  ℹ️ [当日已完成] 今天 %02d:00 重置后已成功完成过每日，"
                          "本次未再匹配到领取记录，不计为未完成：" % DAILY_RESET_HOUR,
                          level=LEVEL_WARN)
                for line in lines:
                    self._log("    · %s" % line, level=LEVEL_WARN)
                continue
            self._log(title, level=level)
            for line in lines:
                self._log("    · %s" % line, level=level)
            if truncated.get(key):
                self._log("    · （匹配行过多，仅显示最新 %d 条）" % watcher.max_per_category,
                          level=level)
        self._tlog("──────── 结果输出完毕 ────────", level=LEVEL_OK)
        return status

    def _apply_daily_repeat(self, p, status):
        """记录/查询同服务器日完成状态：当天已完成的游戏再跑不再报未完成。

        判定为已完成时记录时间；判定为未完成但本服务器日（凌晨 4 点起）
        已完成过时，降级为已完成并标记 repeated，让调用方用 ℹ️ 措辞输出。
        """
        if status not in (TASK_COMPLETED, TASK_INCOMPLETE):
            return status, False
        key = p.get("id") or p.get("name") or "未知"
        now = datetime.datetime.now()
        if status == TASK_COMPLETED:
            self.daily_state.mark_done(key, now)
            return status, False
        status2, repeated = resolve_daily_repeat(
            status, self.daily_state.last_done(key), now)
        if repeated:
            self.daily_state.mark_done(key, now)
        return status2, repeated

    def _log_task_final(self, name, task_status, log_configured):
        """输出每个游戏脚本的最终结论：已完成 / 未完成（或无法判断）。"""
        self._last_task_status = task_status
        self._tls.final_status = task_status
        if task_status == TASK_COMPLETED:
            self._tlog("[任务完成] %s · 已完成" % name, level=LEVEL_OK)
        elif task_status == TASK_INCOMPLETE:
            self._tlog("[任务未完成] %s · 未完成" % name, level=LEVEL_ERROR)
        elif log_configured:
            self._tlog("[提示] %s 已结束，但无法从脚本日志确认任务是否完成。" % name, level=LEVEL_WARN)
        else:
            self._tlog("[完成] %s" % name, level=LEVEL_OK)

    def _log_daily_summary(self, rows):
        """在队列结束前输出一眼可懂的每日完成情况汇总。"""
        if not rows:
            return
        bar = "★━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        self._log("")
        self._log(bar, level=LEVEL_BLUE)
        self._log("  每日奖励完成情况汇总", level=LEVEL_BLUE)
        self._log(bar, level=LEVEL_BLUE)

        done = sum(1 for _, status in rows if status == TASK_COMPLETED)
        incomplete = sum(1 for _, status in rows if status == TASK_INCOMPLETE)
        unknown = len(rows) - done - incomplete
        for name, status in rows:
            if status == TASK_COMPLETED:
                self._log("  ✅ 已完成 · %s" % name, level=LEVEL_OK)
            elif status == TASK_INCOMPLETE:
                self._log("  ❌ 未完成 · %s" % name, level=LEVEL_ERROR)
            else:
                self._log("  ⚠ 未能确认 · %s" % name, level=LEVEL_WARN)

        self._log("  ──────────────────────────────────", level=LEVEL_BLUE)
        parts = ["完成 %d 个" % done]
        if incomplete:
            parts.append("未完成 %d 个" % incomplete)
        if unknown:
            parts.append("未能确认 %d 个" % unknown)
        level = LEVEL_OK if done == len(rows) else LEVEL_WARN
        self._log("  结论：%s" % "，".join(parts), level=level)
        self._log(bar, level=LEVEL_BLUE)
        self._log("")

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
