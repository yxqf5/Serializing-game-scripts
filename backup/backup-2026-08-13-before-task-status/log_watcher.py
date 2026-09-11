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

try:
    import ctypes
except Exception:
    ctypes = None

DEFAULT_ENCODINGS = ["utf-8", "gbk"]

# 多字节编码一个字符最多占 3 个字节（utf-8 三字节序列 / gbk 双字节）
MAX_INCOMPLETE_TAIL = 3

if ctypes and os.name == "nt":
    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_ulong),
                    ("dwHighDateTime", ctypes.c_ulong)]

    class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", ctypes.c_ulong),
            ("ftCreationTime", _FILETIME),
            ("ftLastAccessTime", _FILETIME),
            ("ftLastWriteTime", _FILETIME),
            ("dwVolumeSerialNumber", ctypes.c_ulong),
            ("nFileSizeHigh", ctypes.c_ulong),
            ("nFileSizeLow", ctypes.c_ulong),
            ("nNumberOfLinks", ctypes.c_ulong),
            ("nFileIndexHigh", ctypes.c_ulong),
            ("nFileIndexLow", ctypes.c_ulong),
        ]


def _file_identity(path):
    """
    Windows 下返回文件的身份标识 (卷序列号, 文件索引高, 低)。

    同一路径被替换成新文件时索引必然变化，与创建时间戳精度无关；
    失败（文件不存在等）返回 None。非 Windows 平台也返回 None。
    """
    if os.name != "nt" or not ctypes:
        return None
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    FILE_SHARE_DELETE = 0x4
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    handle = ctypes.windll.kernel32.CreateFileW(
        path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if handle == INVALID_HANDLE_VALUE:
        return None
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not ctypes.windll.kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            return None
        return (info.dwVolumeSerialNumber, info.nFileIndexHigh, info.nFileIndexLow)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _decode_incremental(data, encodings):
    """
    增量解码新增字节，处理「多字节字符被两次 poll 截断」的情况。

    返回 (text, pending)：
      - text    本块能完整解码出的文本
      - pending 可能属于下一个多字节字符的尾部字节，须与下次读到的数据拼接后再解码

    解码失败时先尝试去掉末尾 1..3 字节重试（截断的多字节字符会让整体解码报错）；
    若仍失败（文件本身混入坏字节）则 utf-8 容错兜底且不保留 pending。
    """
    if not data:
        return "", b""
    text, enc = _try_decode(data, encodings)
    if text is not None:
        return text, b""
    for drop in range(1, min(MAX_INCOMPLETE_TAIL, len(data)) + 1):
        text, enc = _try_decode(data[:-drop], encodings)
        if text is not None:
            return text, data[-drop:]
    return data.decode("utf-8", errors="replace"), b""


def _try_decode(data, encodings):
    """按候选编码顺序严格解码；全部失败返回 (None, None)。"""
    for enc in encodings:
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return None, None


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
                 stamina_patterns=None, max_per_category=20):
        self.pattern = (log_file or "").strip().strip('"')
        self.encoding = encoding or "auto"
        self.daily_done_re = self._compile(daily_done_patterns)
        self.daily_pending_re = self._compile(daily_pending_patterns)
        self.stamina_re = self._compile(stamina_patterns)
        self.max_per_category = max(1, int(max_per_category))

        self.path = None
        self._offset = 0
        self._pending = b""     # 上次 poll 未解完的多字节尾部
        self._partial = ""      # 上次 poll 未写完（无换行结尾）的半行
        self._identity = None   # Windows 文件身份（卷序列号+文件索引），识别替换
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
        self._pending = b""
        self._partial = ""
        self._identity = None
        if self.path:
            try:
                self._offset = os.path.getsize(self.path)
            except OSError:
                self._offset = 0
            self._identity = _file_identity(self.path)
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
        identity = _file_identity(path)
        if path != self.path or size < self._offset or (
                self._identity is not None and identity is not None
                and identity != self._identity):
            # 日志轮转：换文件/被替换/被清空（含新文件比旧 offset 更大的情况），从头读
            self.path = path
            self._offset = 0
            self._pending = b""
            self._partial = ""
            self._identity = identity
        if size <= self._offset:
            return
        try:
            with open(path, "rb") as f:
                f.seek(self._offset)
                data = f.read()
        except OSError:
            return
        self._offset = size
        if self._pending:
            data = self._pending + data
        text, self._pending = _decode_incremental(data, self._encodings())
        if self._partial:
            # 上次未写完的半行拼到本次文本前，凑成完整行再分类
            text = self._partial + text
            self._partial = ""
        parts = text.splitlines()
        if text and not text.endswith(("\n", "\r")) and parts:
            # 最后一行还没写完（无换行结尾），与下一块拼成完整行再分类，
            # 避免一行被两次 poll 截断时漏报/误报
            self._partial = parts.pop()
        for line in parts:
            self._classify_line(line)

    def _classify_line(self, line):
        line = line.strip()
        if not line:
            return
        if self.stamina_re and any(r.search(line) for r in self.stamina_re):
            # 体力/理智：只保留最新一条
            self._stamina = [line]
        elif self.daily_pending_re and any(r.search(line) for r in self.daily_pending_re):
            self._daily_pending.append(line)
        elif self.daily_done_re and any(r.search(line) for r in self.daily_done_re):
            self._daily_done.append(line)

    def _flush_tail(self):
        """流结束时处理尚未成行的残留（未完成的多字节尾部 + 未换行的最后一行）。"""
        if not self._pending and not self._partial:
            return
        tail = self._partial
        self._partial = ""
        if self._pending:
            tail += self._pending.decode("utf-8", errors="replace")
            self._pending = b""
        if tail:
            self._classify_line(tail)

    def finish(self):
        """
        返回本次运行提取的三类信息（每类去重后最多保留最新 max_per_category 条）。

        返回 dict：daily_done / daily_pending / stamina 为行列表，
        truncated 为 {分类: bool}，标记该分类是否因超出上限被截断。
        """
        self._flush_tail()
        out = {}
        truncated = {"daily_done": False, "daily_pending": False, "stamina": False}
        for key, collected in (
            ("daily_done", self._daily_done),
            ("daily_pending", self._daily_pending),
            ("stamina", self._stamina),
        ):
            uniq = _dedup_keep_order(collected)
            if len(uniq) > self.max_per_category:
                truncated[key] = True
                uniq = uniq[-self.max_per_category:]
            out[key] = uniq
        out["truncated"] = truncated
        return out
