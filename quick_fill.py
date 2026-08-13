# -*- coding: utf-8 -*-
"""粘贴文本快速填充：解析键值行并映射到插件字段。"""

import re

SAMPLE_QUICK_FILL = """# 粘贴快速填充 — 每行「键: 值」，# 开头为注释
# 添加页可填写「游戏」「脚本」切换预设；编辑页可填全部字段

名称: 原神 · BetterGI · 一条龙
游戏: 原神
脚本: BetterGI · 一条龙
启动器: E:\\Games\\py\\BetterGI\\BetterGI.exe
参数: startOneDragon
等待模式: game
游戏进程: YuanShen.exe, GenshinImpact.exe
助手进程: BetterGI.exe
超时: 15
文档: https://www.bettergi.com/
备注: 请在 BetterGI 设置完成后关闭游戏
待办完成: 在 BetterGI：设置 → 一条龙 → 结束后操作 → 关闭游戏
"""

# 键别名 → 标准字段名
_KEY_MAP = {
    "name": {"名称", "name", "显示名称", "游戏名称"},
    "game": {"游戏", "game", "preset_game", "游戏名"},
    "script": {"脚本", "script", "preset_script", "助手", "脚本名"},
    "launcher": {"启动器", "launcher", "路径", "启动器路径", "程序", "exe"},
    "args": {"参数", "args", "启动参数", "arguments"},
    "pre_launcher": {"前置程序", "pre_launcher", "前置", "前置启动", "先启动"},
    "pre_args": {"前置参数", "pre_args", "前置程序参数"},
    "pre_delay_sec": {"前置等待", "pre_delay_sec", "前置等待秒", "前置延迟"},
    "log_file": {"日志文件", "log_file", "日志", "日志路径"},
    "log_encoding": {"日志编码", "log_encoding", "编码"},
    "daily_done_patterns": {"每日完成", "daily_done_patterns", "每日奖励完成", "已完成关键词"},
    "daily_pending_patterns": {"每日未完成", "daily_pending_patterns", "未领取关键词", "未完成关键词"},
    "stamina_patterns": {"体力关键词", "stamina_patterns", "理智关键词", "体力"},
    "wait_mode": {"等待模式", "wait_mode", "完成判定", "wait"},
    "game_processes": {"游戏进程", "game_processes", "游戏进程名"},
    "helper_processes": {"助手进程", "helper_processes", "助手进程名"},
    "start_timeout_min": {"超时", "start_timeout_min", "启动超时", "超时分钟"},
    "notes": {"备注", "notes", "说明"},
    "doc_url": {"文档", "doc_url", "doc", "官方文档", "链接"},
    "checklist_done": {"待办完成", "checklist_done", "已完成待办", "待办勾选"},
}

_WAIT_ALIASES = {
    "game": "game",
    "helper": "helper",
    "游戏": "game",
    "助手": "helper",
    "等待游戏": "game",
    "等待助手": "helper",
}


def _norm_key(raw):
    raw = raw.strip().lower()
    for field, aliases in _KEY_MAP.items():
        if raw in {a.lower() for a in aliases}:
            return field
    return None


def _split_list(value):
    value = value.replace("，", ",").replace(";", ",").replace("|", ",")
    return [x.strip() for x in value.split(",") if x.strip()]


def _parse_wait_mode(value):
    v = value.strip().lower()
    if v in _WAIT_ALIASES:
        return _WAIT_ALIASES[v]
    if "helper" in v or "助手" in v or "maa" in v:
        return "helper"
    return "game"


def parse_quick_fill(text):
    """
    解析粘贴文本。
    返回 (fields_dict, error_message)。
    fields_dict 键为标准字段名；error 为空表示成功（允许部分字段为空）。
    """
    fields = {}
    notes_lines = []
    in_notes = False
    checklist_items = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if in_notes:
                notes_lines.append("")
            continue
        if stripped.startswith("#"):
            continue

        if in_notes and not re.match(r"^[\w\u4e00-\u9fff]+[:：]", stripped):
            notes_lines.append(stripped)
            continue
        in_notes = False

        m = re.match(r"^(.+?)[:：]\s*(.*)$", stripped)
        if not m:
            continue
        raw_key, value = m.group(1).strip(), m.group(2).strip()
        field = _norm_key(raw_key)
        if not field:
            continue

        if field == "notes" and not value:
            in_notes = True
            continue

        if field == "args":
            fields["args"] = value.split() if value else []
        elif field == "pre_args":
            fields["pre_args"] = value.split() if value else []
        elif field in ("game_processes", "helper_processes", "daily_done_patterns",
                       "daily_pending_patterns", "stamina_patterns"):
            fields[field] = _split_list(value)
        elif field == "checklist_done":
            if value:
                checklist_items.extend(_split_list(value))
            else:
                checklist_items.append("__multiline__")
        elif field == "wait_mode":
            fields[field] = _parse_wait_mode(value)
        elif field == "start_timeout_min":
            try:
                fields[field] = int(value)
            except ValueError:
                return {}, "「超时」必须是数字：%s" % value
        elif field == "pre_delay_sec":
            try:
                fields[field] = max(0, int(value))
            except ValueError:
                return {}, "「前置等待」必须是数字：%s" % value
        elif field == "notes":
            fields["notes"] = value
        else:
            fields[field] = value

    if notes_lines:
        extra = "\n".join(notes_lines).strip()
        if extra:
            fields["notes"] = (fields.get("notes", "") + "\n" + extra).strip()

    # 多行待办：以 - 开头的续行
    pending_checklist = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- "):
            pending_checklist.append(s[2:].strip())
        elif s.startswith("• "):
            pending_checklist.append(s[2:].strip())
    if pending_checklist:
        fields["checklist_done"] = pending_checklist
    elif checklist_items and checklist_items != ["__multiline__"]:
        fields["checklist_done"] = checklist_items

    if not fields:
        return {}, "未识别到任何有效字段，请检查格式（参考样例）。"
    return fields, ""


def export_plugin_to_text(plugin):
    """将插件 dict 导出为可粘贴文本（供编辑页预填）。"""
    lines = [
        "名称: %s" % plugin.get("name", ""),
        "启动器: %s" % plugin.get("launcher", ""),
        "参数: %s" % " ".join(plugin.get("args") or []),
        "等待模式: %s" % plugin.get("wait_mode", "game"),
        "游戏进程: %s" % ", ".join(plugin.get("game_processes") or []),
        "助手进程: %s" % ", ".join(plugin.get("helper_processes") or []),
        "超时: %s" % plugin.get("start_timeout_min", 15),
    ]
    if plugin.get("pre_launcher"):
        lines.append("前置程序: %s" % plugin["pre_launcher"])
        if plugin.get("pre_args"):
            lines.append("前置参数: %s" % " ".join(plugin["pre_args"]))
        lines.append("前置等待: %s" % plugin.get("pre_delay_sec", 0))
    if plugin.get("log_file"):
        lines.append("日志文件: %s" % plugin["log_file"])
        lines.append("日志编码: %s" % plugin.get("log_encoding", "auto"))
        if plugin.get("daily_done_patterns"):
            lines.append("每日完成: %s" % ", ".join(plugin["daily_done_patterns"]))
        if plugin.get("daily_pending_patterns"):
            lines.append("每日未完成: %s" % ", ".join(plugin["daily_pending_patterns"]))
        if plugin.get("stamina_patterns"):
            lines.append("体力关键词: %s" % ", ".join(plugin["stamina_patterns"]))
    if plugin.get("doc_url"):
        lines.append("文档: %s" % plugin["doc_url"])
    if plugin.get("notes"):
        lines.append("备注: %s" % plugin["notes"])
    done = plugin.get("checklist_done") or []
    if done:
        lines.append("待办完成: %s" % ", ".join(done))
    return "\n".join(lines)
