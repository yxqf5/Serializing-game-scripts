# -*- coding: utf-8 -*-
"""
运行日志自动保存（与界面解耦的纯逻辑模块）。

- 每天一个 md 文件（logs\\YYYY-MM-DD.md）
- 一天内多次运行，每条记录用「## 运行记录」标题 + 「---」分割线隔开
- 按保留策略清理：最近一周（7 天）/ 最近一个月（30 天）/ 不清理
- 清理只删除本程序生成的日期命名文件，不碰用户手动放进去的文件

用法：
    record = log_saver.build_run_markdown(record_no, start_dt, end_dt,
                                          result, tasks, lines)
    path, record_no = log_saver.append_run_record(log_dir, record)
    removed = log_saver.cleanup_old_logs(log_dir, retention_days("month"))
"""

import os
import re
import datetime

# 保留策略 → 天数（None 表示不清理）
RETENTION_OPTIONS = {"week": 7, "month": 30, "forever": None}

# 运行结果 → 显示文案 / 任务标记
_RESULT_LABELS = {
    "completed": "全部完成",
    "partial": "部分未完成",
    "stopped": "用户停止",
    "failed": "启动失败",
    "skipped": "已跳过",
}
_TASK_MARKS = {"completed": "✅", "incomplete": "❌", "unknown": "⚠️",
               "skipped": "⏭", "failed": "❌", "stopped": "⏹"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def retention_days(value):
    """'week'/'month'/'forever'（或中文）→ 天数或 None（不清理）。"""
    key = (value or "month").strip().lower()
    aliases = {"week": "week", "一个月": "month", "最近一周": "week", "最近一个月": "month",
               "不清理": "forever"}
    key = aliases.get(key, key)
    return RETENTION_OPTIONS.get(key, 30)


def today_filename(now=None):
    """今天的日志文件名：YYYY-MM-DD.md。"""
    now = now or datetime.datetime.now()
    return "%s.md" % now.strftime("%Y-%m-%d")


def count_records(md_text):
    """统计 md 文本里的运行记录条数（按「## 运行记录」标题计数）。"""
    return md_text.count("## 运行记录")


def today_record_count(log_dir, now=None):
    """今天 md 文件里已有的运行记录条数（文件不存在返回 0）。"""
    path = os.path.join(log_dir, today_filename(now))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return count_records(f.read())
    except OSError:
        return 0


def build_run_markdown(record_no, start_dt, end_dt, result, tasks, lines):
    """
    构造一次运行记录的 markdown 文本。

    参数：
      record_no 今天第几次运行（从 1 开始）
      start_dt / end_dt  datetime，只取时间部分展示
      result     运行结果：completed / stopped / failed / skipped
      tasks      [(游戏名, 结果), ...]，按执行顺序
      lines      完整日志行列表（保持界面显示顺序）
    """
    out = []
    out.append("## 运行记录 · 第 %d 次 · %s → %s · %s" % (
        record_no,
        start_dt.strftime("%H:%M:%S"),
        end_dt.strftime("%H:%M:%S"),
        _RESULT_LABELS.get(result, result),
    ))
    out.append("")
    out.append("### 摘要")
    out.append("")
    total = len(tasks)
    if total:
        done = sum(1 for _, r in tasks if r == "completed")
        out.append("- 共 %d 个游戏，完成 %d 个%s" % (
            total, done,
            "" if done == total else "，%d 个未完成" % (total - done)))
        for name, r in tasks:
            out.append("- %s %s" % (_TASK_MARKS.get(r, "·"), name))
    else:
        out.append("- 未启动任何游戏")
    out.append("")
    out.append("### 日志")
    out.append("")
    out.append("```text")
    out.extend(str(line) for line in lines)
    out.append("```")
    out.append("")
    return "\n".join(out)


def append_run_record(log_dir, record_text, now=None):
    """
    把一条运行记录追加到今天的 md 文件（不存在则创建并写文件头）。

    返回 (文件绝对路径, 今天第几次运行)。
    """
    os.makedirs(log_dir, exist_ok=True)
    now = now or datetime.datetime.now()
    path = os.path.join(log_dir, today_filename(now))
    record_no = 1
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
        record_no = count_records(existing) + 1
    except OSError:
        existing = ""
    if existing:
        head = "\n---\n\n"
    else:
        head = "# 运行日志 · %s\n\n" % now.strftime("%Y-%m-%d")
    with open(path, "a", encoding="utf-8") as f:
        f.write(head + record_text + "\n")
    return os.path.abspath(path), record_no


def cleanup_old_logs(log_dir, retention, now=None):
    """
    删除超过保留天数的日志文件；retention 为 None 时不清理。

    只处理 YYYY-MM-DD.md 命名的文件（按文件名日期判断，不看修改时间），
    其它文件一律不碰。返回删除的文件数。
    """
    if retention is None or not os.path.isdir(log_dir):
        return 0
    days = max(1, int(retention))
    now = now or datetime.datetime.now()
    deadline = now - datetime.timedelta(days=days)
    removed = 0
    try:
        names = os.listdir(log_dir)
    except OSError:
        return 0
    for name in names:
        if not _DATE_RE.match(name):
            continue
        try:
            fdate = datetime.datetime.strptime(name[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if fdate < deadline:
            try:
                os.remove(os.path.join(log_dir, name))
                removed += 1
            except OSError:
                pass
    return removed
