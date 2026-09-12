# -*- coding: utf-8 -*-
"""定时任务纯逻辑:每日触发时刻计算与配置归一化(与 UI 解耦,便于测试)。

语义:每天到点后由界面弹出「倒计时确认框」——点「立即运行」或等倒计时
归零则开始执行串行队列;点「跳过」则本次不运行,明天同一时刻再询问。
"""

import datetime

# 设置项默认值(与 settings.json 键名 schedule_* 对应)
DEFAULT_TIME = "04:00"      # 默认每天 04:00 触发(游戏每日重置后正好挂机)
DEFAULT_COUNTDOWN_SEC = 60  # 确认框默认倒计时秒数
COUNTDOWN_MIN, COUNTDOWN_MAX = 10, 600


def parse_hhmm(text):
    """解析 "HH:MM" / "HH:MM:SS" 为 datetime.time;非法返回 None。"""
    if not isinstance(text, str):
        return None
    s = text.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def next_daily_occurrence(t, now):
    """给定每日时刻 t(time)与 now(datetime),返回下一次触发时刻(datetime)。

    今天该时刻还没到(严格大于 now)→ 今天;否则 → 明天。
    恰好等于 now 视为已过:避免保存设置的一瞬间(秒级重合)立刻弹窗。
    """
    if t is None:
        return None
    cand = datetime.datetime.combine(now.date(), t)
    if cand > now:
        return cand
    return cand + datetime.timedelta(days=1)


def countdown_bounds(sec):
    """把倒计时秒数夹进允许区间并取整(手工改 settings.json 时兜底)。"""
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return DEFAULT_COUNTDOWN_SEC
    return max(COUNTDOWN_MIN, min(COUNTDOWN_MAX, sec))


def schedule_config(settings):
    """从 settings dict 读取归一化的定时任务配置。

    返回 dict:
      enabled        是否启用(未启用或时刻非法时为 False)
      time            触发时刻(datetime.time)或 None
      time_text       "HH:MM" 展示文本(未启用时为 "")
      countdown_sec   确认框倒计时秒数(已夹取区间)
    """
    countdown = countdown_bounds(settings.get(
        "schedule_countdown_sec", DEFAULT_COUNTDOWN_SEC))
    t = parse_hhmm(settings.get("schedule_time") or DEFAULT_TIME)
    if not settings.get("schedule_enabled") or t is None:
        return {"enabled": False, "time": None, "time_text": "",
                "countdown_sec": countdown}
    return {"enabled": True, "time": t, "time_text": t.strftime("%H:%M"),
            "countdown_sec": countdown}
