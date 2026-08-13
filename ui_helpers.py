# -*- coding: utf-8 -*-
"""UI 可测试的纯逻辑工具，不依赖 Tk。"""


class LogStore:
    """有上限的内存日志，始终保留最新内容。

    每条记录为 (text, level) 元组（level 为结构化日志级别字符串或 None）；
    为兼容旧调用，append_many 也接受纯字符串（level 记为 None）。
    """

    def __init__(self, max_lines=10000):
        self.max_lines = max(1, int(max_lines))
        self.lines = []
        self.dropped_total = 0

    def clear(self):
        self.lines = []
        self.dropped_total = 0

    @staticmethod
    def _normalize(line):
        if isinstance(line, tuple):
            text = line[0] if line else ""
            level = line[1] if len(line) > 1 else None
            return (str(text).rstrip("\r\n"), level)
        return (str(line).rstrip("\r\n"), None)

    def append_many(self, lines):
        normalized = [self._normalize(line) for line in lines]
        if not normalized:
            return 0
        self.lines.extend(normalized)
        overflow = max(0, len(self.lines) - self.max_lines)
        if overflow:
            del self.lines[:overflow]
            self.dropped_total += overflow
        return overflow

    def export_text(self):
        return ("\n".join(text for text, _ in self.lines) + "\n") if self.lines else ""


def group_tagged_lines(lines, tag_func):
    """把相邻且颜色标签相同的日志合成一次 Text.insert。

    lines 元素可为 (text, level) 元组或纯字符串：
      - 元组：tag = tag_func(text, level)（level 优先由界面映射为颜色）
      - 字符串：tag = tag_func(text)（旧接口，向后兼容）
    """
    groups = []
    current_tag = object()
    current_lines = []
    for raw in lines:
        if isinstance(raw, tuple):
            text = raw[0] if raw else ""
            level = raw[1] if len(raw) > 1 else None
            line = str(text).rstrip("\r\n")
            tag = tag_func(line, level)
        else:
            line = str(raw).rstrip("\r\n")
            tag = tag_func(line)
        if current_lines and tag != current_tag:
            groups.append((current_tag, "\n".join(current_lines) + "\n"))
            current_lines = []
        current_tag = tag
        current_lines.append(line)
    if current_lines:
        groups.append((current_tag, "\n".join(current_lines) + "\n"))
    return groups


def elide_middle(text, max_chars):
    """中间省略长文本，优先保留路径尾部文件名。"""
    text = str(text or "")
    max_chars = max(1, int(max_chars))
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    tail = min(max_chars - 2, max(max_chars // 2, 12))
    head = max_chars - tail - 1
    return text[:head] + "…" + text[-tail:]


def elide_end(text, max_chars):
    """尾部省略普通标题，保留最容易识别的开头。"""
    text = str(text or "")
    max_chars = max(1, int(max_chars))
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    prefix = text[:max_chars - 1].rstrip(" ·•-—")
    suffix = " …" if len(prefix) + 2 <= max_chars else "…"
    return prefix + suffix


def clamp_window_bounds(bounds, screen_width, screen_height, min_width=940, min_height=660):
    """将持久化窗口位置校正到当前屏幕可见区域。"""
    bounds = bounds if isinstance(bounds, dict) else {}
    sw = max(1, int(screen_width))
    sh = max(1, int(screen_height))
    width = max(int(min_width), int(bounds.get("width", 1060) or 1060))
    height = max(int(min_height), int(bounds.get("height", 760) or 760))
    width = min(width, sw)
    height = min(height, sh)
    x = int(bounds.get("x", (sw - width) // 2) or 0)
    y = int(bounds.get("y", (sh - height) // 2) or 0)
    x = min(max(0, x), max(0, sw - width))
    y = min(max(0, y), max(0, sh - height))
    return x, y, width, height
