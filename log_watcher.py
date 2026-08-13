# -*- coding: utf-8 -*-
"""
脚本日志监控（与执行引擎解耦的独立模块）。

串行助手启动脚本后，增量读取脚本自身写下的日志文件，只提取三类用户关心的信息：
  - 每日奖励已完成（daily_done）      -> 金色
  - 每日奖励未完成/未领取（daily_pending）-> 红色
  - 剩余体力/理智（stamina）          -> 蓝色，只保留最新一条

用法：
    w = ScriptLogWatcher(log_file=r"...\\logs\\*.log",
                         encoding="auto",
                         daily_done_patterns=["每日实训已完成"],
                         daily_pending_patterns=["未检测到每日实训奖励"],
                         stamina_patterns=["开拓力"])
    w.start()          # 记录起始位置
    w.poll()           # 等待期间周期性调用，增量读取
    result = w.finish()# 返回 {"daily_done": [...], "daily_pending": [...], "stamina": [...]}
"""

import os
import glob
import re

DEFAULT_ENCODINGS = ["utf-8", "gbk"]


def _decode_candidates(data, encodings):
    """按候选编码顺序解码字节串，全部失败则 utf-8 容错兜底。"""
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def resolve_log_file(pattern):
    """
    解析 log_file 配置（支持 glob 通配，多个匹配时取修改时间最新者）。
    返回规范化绝对路径；找不到返回 None。
    """
    pattern = (pattern or "").strip().strip('"')
    if not pattern:
        return None
    if not glob.has_magic(pattern):
        path = os.path.normpath(pattern)
        return path if os.path.isfile(path) else None
    matches = [os.path.normpath(f) for f in glob.glob(pattern) if os.path.isfile(f)]
    if not matches:
        return None
    return max(matches, key=lambda f: os.path.getmtime(f))


def _dedup_keep_order(lines):
    seen = set()
    out = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


class ScriptLogWatcher:
    """跟踪一个日志文件的增量变化，按三类语义关键词提取本次运行的关键信息。"""

    def __init__(self, log_file="", encoding="auto",
                 daily_done_patterns=None, daily_pending_patterns=None,
                 stamina_patterns=None):
        self.pattern = (log_file or "").strip().strip('"')
        self.encoding = encoding or "auto"
        self.daily_done_re = self._compile(daily_done_patterns)
        self.daily_pending_re = self._compile(daily_pending_patterns)
        self.stamina_re = self._compile(stamina_patterns)

        self.path = None
        self._offset = 0
        self._daily_done = []
        self._daily_pending = []
        self._stamina = []

    @staticmethod
    def _compile(patterns):
        parts = []
        for p in patterns or []:
            p = (p or "").strip()
            if not p:
                continue
            try:
                parts.append(re.compile(p, re.IGNORECASE))
            except re.error:
                parts.append(re.compile(re.escape(p), re.IGNORECASE))
        return parts

    def _encodings(self):
        enc = (self.encoding or "auto").strip().lower()
        if enc in ("gbk", "gb2312", "gb18030", "cp936"):
            return ["gbk"]
        if enc == "utf-8":
            return ["utf-8"]
        return DEFAULT_ENCODINGS

    def start(self):
        """记录起始位置；返回日志文件是否可用。"""
        self.path = resolve_log_file(self.pattern)
        self._offset = 0
        if self.path:
            try:
                self._offset = os.path.getsize(self.path)
            except OSError:
                self._offset = 0
        return self.path is not None

    def poll(self):
        """增量读取新增行；自动识别日志轮转（文件被替换/清空时从头读）。"""
        if not self.path:
            return
        path = resolve_log_file(self.pattern)
        if not path:
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if path != self.path or size < self._offset:
            # 日志轮转：换文件或文件被清空，从新文件开头读
            self.path = path
            self._offset = 0
        if size <= self._offset:
            return
        try:
            with open(path, "rb") as f:
                f.seek(self._offset)
                data = f.read()
        except OSError:
            return
        self._offset = size
        text = _decode_candidates(data, self._encodings())
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if self.stamina_re and any(r.search(line) for r in self.stamina_re):
                # 体力/理智：只保留最新一条
                self._stamina = [line]
            elif self.daily_pending_re and any(r.search(line) for r in self.daily_pending_re):
                self._daily_pending.append(line)
            elif self.daily_done_re and any(r.search(line) for r in self.daily_done_re):
                self._daily_done.append(line)

    def finish(self):
        """返回本次运行提取的三类信息。"""
        return {
            "daily_done": _dedup_keep_order(self._daily_done),
            "daily_pending": _dedup_keep_order(self._daily_pending),
            "stamina": list(self._stamina),
        }
