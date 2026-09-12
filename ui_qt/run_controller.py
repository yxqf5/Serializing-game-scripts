# -*- coding: utf-8 -*-
"""运行链路控制器:Runner/preflight 守护线程 + 队列→Qt 信号。

移植自 tkinter 版:start_run(2755)/_finish_preflight(2780)/stop_run(2828)/
_apply_run_event(2843)/_drain_log(3059)/_save_run_log(3116)。
工作线程只 put 队列,不碰任何 QWidget;队列协议见 PORTING.md 附录 B。
"""
import datetime
import os
import queue
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

import log_saver
import preflight
import runner_core
import display_ctrl
from ui_qt.core_glue import DAILY_STATE_FILE, LOG_DIR

# 自动保存/导出用的完整日志缓冲上限(界面显示另受 LogStore 1 万行限制)
RUN_LOG_BUFFER_MAX = 50000


class RunController(QObject):
    log_lines = Signal(list)                  # list[(text, level|None)] 批量
    run_event = Signal(dict)                  # 与旧 ui_queue "run_event" 的 event 字典一致
    preflight_done = Signal(int, list, list)  # token, active, issues
    state_changed = Signal(dict)              # run_state 快照
    finished = Signal()                       # Runner 结束(__DONE__)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.stop_event = threading.Event()
        self._run_thread = None
        self._preflight_thread = None
        self._preflight_token = 0
        self._preflight_busy = False
        self.run_state = {
            "state": "idle", "index": 0, "total": 0,
            "name": "", "message": "就绪", "result": None,
            "parallel_names": [],
        }
        # 本轮运行开始时间(自动保存日志用)/每个游戏的执行结果 [(name, result)]
        self._run_started_at = None
        self._run_tasks = []
        # 保存专用缓冲:md 日志取自这里而非界面 LogStore(后者 1 万行上限
        # 会静默丢最旧行),运行中「清空日志」也不影响已记录的内容
        self._run_log_buffer = []     # [(text, level), ...]
        self._run_log_dropped = 0     # 缓冲超限被丢弃的行数
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    # ---- 对外状态 ----
    @property
    def running(self) -> bool:
        return self.run_state.get("state") in ("running", "stopping")

    @property
    def preflight_busy(self) -> bool:
        return self._preflight_busy

    @property
    def run_started_at(self):
        """本轮运行开始时间(datetime 或 None),主窗口计时显示用。"""
        return self._run_started_at

    def _snapshot(self) -> dict:
        return dict(self.run_state)

    # ---- 运行前检查(移植 start_run 前半段) ----
    def start(self, plugins: list) -> None:
        """校验有 enabled 插件 → 守护线程跑 preflight → ui_queue 回投结果。"""
        if self.running or self._preflight_busy:
            return
        active = [p for p in plugins if p.get("enabled", True)]
        if not active:
            return  # 无启用插件:由主窗口负责提示,这里不启动
        self._preflight_token += 1   # token 自增,过期结果直接丢弃
        token = self._preflight_token
        self._preflight_busy = True
        self.run_state.update(state="preflight", message="正在运行前检查")
        self.state_changed.emit(self._snapshot())

        def worker():
            try:
                issues = preflight.check_plugins(
                    active, running_names=runner_core.snapshot_running_processes())
            except Exception as e:
                issues = [{"level": "error", "plugin_name": "",
                           "message": "运行前检查失败：%s" % e}]
            self.ui_queue.put(("preflight", token, active, issues))

        self._preflight_thread = threading.Thread(target=worker, daemon=True)
        self._preflight_thread.start()

    def cancel_preflight(self) -> None:
        """放弃本次启动:token 自增使在途结果过期,状态复原为「就绪」。"""
        self._preflight_token += 1
        if self._preflight_busy:
            self._preflight_busy = False
            self.run_state.update(
                state="idle", index=0, total=0, name="",
                message="就绪", result=None, parallel_names=[])
            self.state_changed.emit(self._snapshot())

    # ---- 真正开跑(移植 _finish_preflight 后半段) ----
    def begin_run(self, active: list) -> None:
        """用户确认后开跑。清 log_queue/log_store 的语义由主窗口负责。"""
        self._preflight_busy = False
        self.stop_event.clear()
        self._run_started_at = datetime.datetime.now()
        self._run_tasks = []
        self._run_log_buffer = []
        self._run_log_dropped = 0
        self.run_state = {
            "state": "running", "index": 0, "total": len(active),
            "name": "", "message": "正在启动任务队列", "result": None,
            "parallel_names": [],
        }
        self.state_changed.emit(self._snapshot())

        def worker():
            # 运行时分辨率(适配只支持 16:9 的开源脚本):开跑前切换,
            # 结束/停止/异常都经 finally 恢复;崩溃兜底由状态文件+下次启动恢复
            self._display_switched = False
            target = display_ctrl.parse_target(self.settings.get("run_resolution", "off"))
            if target:
                ok, msg = display_ctrl.apply_for_run(*target)
                if ok:
                    self._display_switched = True
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
                if self._display_switched:
                    self._display_switched = False
                    done, msg = display_ctrl.restore_if_needed()
                    self._enqueue_log(msg if done else "[警告] %s" % msg,
                                      level=None if done else "warn")
            self.log_queue.put(("__DONE__", None, None))

        self._run_thread = threading.Thread(target=worker, daemon=True)
        self._run_thread.start()

    # ---- 停止(移植 stop_run) ----
    def stop(self) -> None:
        if not self.running or self.run_state.get("state") == "stopping":
            return
        self.stop_event.set()
        self.run_state["state"] = "stopping"
        self.run_state["message"] = "正在结束当前等待…"
        self.state_changed.emit(self._snapshot())
        self._enqueue_log("已请求停止，正在结束当前等待…", level="warn")

    # ---- 队列回调(工作线程调用,只 put) ----
    def _enqueue_log(self, msg, level=None):
        self.log_queue.put(("line", msg, level))

    def _enqueue_run_event(self, event):
        self.ui_queue.put(("run_event", event))

    # ---- 运行事件 → run_state(移植 _apply_run_event 全部 kind) ----
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
            labels = {"completed": "已完成", "skipped": "已跳过",
                      "failed": "启动失败", "stopped": "已停止"}
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
        else:
            return
        self.run_event.emit(event)
        self.state_changed.emit(self._snapshot())

    # ---- 33ms 排水(移植 _drain_log 节奏:12ms ui 时间片 / 1000 行 / 20ms) ----
    def _drain(self) -> None:
        start = time.perf_counter()
        # ui_queue:preflight 结果与运行事件
        try:
            for _ in range(100):
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "preflight":
                    token, active, issues = item[1], item[2], item[3]
                    # token 比对:过期结果直接丢弃(旧 _finish_preflight 语义)
                    if token == self._preflight_token and self._preflight_busy:
                        self.preflight_done.emit(token, active, issues)
                elif kind == "run_event":
                    self._apply_run_event(item[1])
                if (time.perf_counter() - start) >= 0.012:
                    break
        except queue.Empty:
            pass

        # log_queue:攒批(≤1000 行或 20ms)
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
            # 保存专用缓冲同步记录(超上限丢最旧,统计丢弃行数)
            self._run_log_buffer.extend(lines)
            excess = len(self._run_log_buffer) - RUN_LOG_BUFFER_MAX
            if excess > 0:
                del self._run_log_buffer[:excess]
                self._run_log_dropped += excess
            self.log_lines.emit(lines)

        if done:
            self._finish_run()

        pending = not self.log_queue.empty() or not self.ui_queue.empty()
        # 33ms 节奏足够流畅;空闲时降到 80ms 省电,吞吐靠单次 1000 行补偿
        interval = 33 if (pending or self._preflight_busy) else 80
        self._timer.setInterval(interval)

    def _finish_run(self) -> None:
        """__DONE__ 到达:结束运行、自动保存 md、发 finished。"""
        if self.run_state.get("state") not in ("finished",):
            self.run_state.update(state="finished", message="本轮任务已结束")
        self.save_run_log()
        self.state_changed.emit(self._snapshot())
        self.finished.emit()

    # ---- 日志自动保存(移植 _save_run_log) ----
    def save_run_log(self) -> None:
        """本轮运行结束后追加保存到今天的 md 文件,并按保留策略清理过期文件。"""
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
