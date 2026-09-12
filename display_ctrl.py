# -*- coding: utf-8 -*-
"""运行时切换桌面分辨率(适配只支持 16:9 的开源脚本),结束后自动恢复。

原理:ChangeDisplaySettingsW 只改 dmPelsWidth/dmPelsHeight,刷新率等其余参数
保持不变。切换前把原始分辨率落盘 display_state.json;若程序异常退出没能恢复,
下次启动 restore_if_needed() 会自动恢复,不会出现"分辨率改了回不去"。

仅处理主显示器。本机(CDD 间接显示驱动)EnumDisplaySettingsW 返回的缓冲区
自 dmLogPixels 起整体 +8 字节偏移(实测 dmSize=188,标准 212),因此读取
当前分辨率时用"标准偏移优先、+8 偏移兜底"的双重容错解析,均不合理再回退
GetSystemMetrics。写入侧构造标准 DEVMODEW,由系统解析,不受该偏移影响。
"""
import json
import os

try:
    import ctypes
    from ctypes import wintypes
except Exception:   # 打包环境缺 ffi DLL 等异常:降级为不可用,不拖垮整个程序启动
    ctypes = None

from app_paths import data_dir

STATE_FILE = os.path.join(data_dir(), "display_state.json")

ENUM_CURRENT_SETTINGS = -1
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DISP_CHANGE_SUCCESSFUL = 0
DISP_CHANGE_BADMODE = -2

# 宽/高在缓冲区中的字节偏移:标准 164/168;本机驱动偏移后 172/176
_OFFSETS = ((164, 168), (172, 176))
_SANE_MIN, _SANE_MAX = 320, 16384


if ctypes is not None:
    class _DevModeW(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
            ("dmColor", wintypes.SHORT), ("dmDuplex", wintypes.SHORT),
            ("dmYResolution", wintypes.SHORT), ("dmTTOption", wintypes.SHORT),
            ("dmCollate", wintypes.SHORT),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
        ]

    _user32 = (ctypes.WinDLL("user32", use_last_error=True)
               if os.name == "nt" else None)
else:
    _user32 = None


def _sane(w, h):
    """分辨率合理性校验(排除偏移错位读出的乱码)。"""
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        return False
    return (_SANE_MIN <= w <= _SANE_MAX and _SANE_MIN <= h <= _SANE_MAX)


def _candidates_from_buffer(buf):
    """从 DEVMODEW 原始缓冲区提取候选 (w, h),标准偏移优先、+8 偏移兜底。"""
    out = []
    for off_w, off_h in _OFFSETS:
        w = int.from_bytes(buf[off_w:off_w + 4], "little")
        h = int.from_bytes(buf[off_h:off_h + 4], "little")
        if _sane(w, h) and (w, h) not in out:
            out.append((w, h))
    return out


def _enum_current_raw():
    """EnumDisplaySettingsW 读当前模式原始缓冲区,返回候选 (w,h) 列表(可能为空)。"""
    if _user32 is None:
        return []
    buf = (wintypes.BYTE * 512)()
    dm = _DevModeW.from_buffer(buf)
    dm.dmSize = ctypes.sizeof(_DevModeW)
    try:
        if not _user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS,
                                            ctypes.byref(dm)):
            return []
    except Exception:
        return []
    return _candidates_from_buffer(bytes(buf))


def current_resolution():
    """当前主显示器分辨率 (w, h);无法确定时返回 None。"""
    if os.name != "nt":
        return None
    for w, h in _enum_current_raw():
        return (w, h)
    # 最终回退:GetSystemMetrics(应用进程已 DPI 感知,返回物理像素)
    try:
        w = _user32.GetSystemMetrics(0)
        h = _user32.GetSystemMetrics(1)
        if _sane(w, h):
            return (w, h)
    except Exception:
        pass
    return None


def supported_modes():
    """主显示器支持的 (w, h) 集合;枚举失败返回空列表(不视为错误)。"""
    if _user32 is None:
        return []
    buf = (wintypes.BYTE * 512)()
    dm = _DevModeW.from_buffer(buf)
    dm.dmSize = ctypes.sizeof(_DevModeW)
    modes = set()
    try:
        i = 0
        while _user32.EnumDisplaySettingsW(None, i, ctypes.byref(dm)):
            for w, h in _candidates_from_buffer(bytes(buf)):
                modes.add((w, h))
            i += 1
            if i > 400:   # 理论上限保护
                break
    except Exception:
        pass
    return sorted(modes)


def _find_offset_pair(raw, w, h):
    """返回缓冲区中当前 (w, h) 所在的偏移组;找不到返回 None。"""
    for ow, oh in _OFFSETS:
        if (int.from_bytes(raw[ow:ow + 4], "little") == w
                and int.from_bytes(raw[oh:oh + 4], "little") == h):
            return (ow, oh)
    return None


def _make_standard_dm(w, h):
    """全新标准 DEVMODEW,只填宽高(常规机器可用)。"""
    dm = _DevModeW()
    dm.dmSize = ctypes.sizeof(_DevModeW)
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT
    dm.dmPelsWidth = int(w)
    dm.dmPelsHeight = int(h)
    return dm


def _change_dm(dm):
    try:
        return _user32.ChangeDisplaySettingsW(ctypes.byref(dm), 0)
    except Exception:
        return -1


def set_resolution(w, h):
    """切换分辨率,返回 (是否成功, 说明)。

    优先用"驱动返回的原样缓冲改宽高"(兼容间接显示驱动的非标准布局:
    找到当前分辨率所在的偏移组,只改那一组 + dmFields,其余字节不动;
    本机 CDD 驱动下标准输入会被拒绝 BADMODE,此法可行);布局未知时
    回退全新标准 DEVMODE。切换后复核 current_resolution 确认生效。
    """
    if os.name != "nt":
        return (False, "仅支持 Windows")
    if ctypes is None:
        return (False, "ctypes 不可用，无法切换分辨率")
    w, h = int(w), int(h)
    buf = (wintypes.BYTE * 512)()
    dm = _DevModeW.from_buffer(buf)
    dm.dmSize = ctypes.sizeof(_DevModeW)
    try:
        ok_enum = _user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS,
                                               ctypes.byref(dm))
    except Exception:
        ok_enum = False

    if ok_enum:
        raw = bytearray(bytes(buf))
        cur = current_resolution()
        pair = _find_offset_pair(raw, cur[0], cur[1]) if cur else None
        if pair is not None:
            ow, oh = pair
            raw[ow:ow + 4] = w.to_bytes(4, "little")
            raw[oh:oh + 4] = h.to_bytes(4, "little")
            raw[72:76] = (DM_PELSWIDTH | DM_PELSHEIGHT).to_bytes(4, "little")
            dm2 = _DevModeW.from_buffer_copy(bytes(raw))
            r = _change_dm(dm2)
            if r == DISP_CHANGE_SUCCESSFUL:
                if current_resolution() == (w, h):
                    return (True, "分辨率已切换为 %dx%d" % (w, h))
                return (False, "切换指令已发送但未生效")
            if r == DISP_CHANGE_BADMODE:
                return (False, "显示器不支持 %dx%d" % (w, h))
            return (False, "切换分辨率失败(错误码 %d)" % r)

    # 布局未知/枚举失败:回退标准输入(常规机器)
    r = _change_dm(_make_standard_dm(w, h))
    if r == DISP_CHANGE_SUCCESSFUL:
        if current_resolution() == (w, h):
            return (True, "分辨率已切换为 %dx%d" % (w, h))
        return (False, "切换指令已发送但未生效")
    if r == DISP_CHANGE_BADMODE:
        return (False, "显示器不支持 %dx%d" % (w, h))
    return (False, "切换分辨率失败(错误码 %d)" % r)


def parse_target(value):
    """settings 的 run_resolution 值 → (w, h);off/空/非法返回 None。"""
    if not value or str(value).lower() in ("off", "none", "0"):
        return None
    s = str(value).lower().replace("×", "x").replace("*", "x").strip()
    for sep in ("x",):
        if sep in s:
            try:
                w, h = (int(t) for t in s.split(sep, 1))
                if _sane(w, h):
                    return (w, h)
            except ValueError:
                pass
    return None


def _read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        w, h = int(d["w"]), int(d["h"])
        if _sane(w, h):
            return (w, h)
    except Exception:
        pass
    return None


def _write_state(w, h):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"w": int(w), "h": int(h)}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _clear_state():
    try:
        if os.path.isfile(STATE_FILE):
            os.remove(STATE_FILE)
    except Exception:
        pass


def apply_for_run(w, h):
    """开跑前切换到目标分辨率,返回 (是否切换, 说明)。

    已在目标分辨率时 no-op;存在未恢复状态时先恢复再切换,
    切换成功后把原始分辨率落盘(崩溃兜底)。
    """
    if os.name != "nt":
        return (False, "仅支持 Windows")
    if _read_state() is not None:
        restore_if_needed()
    cur = current_resolution()
    if cur == (int(w), int(h)):
        _clear_state()
        return (False, "当前已是 %dx%d,无需切换" % (w, h))
    if cur is None:
        return (False, "无法获取当前分辨率,跳过切换")
    ok, msg = set_resolution(w, h)
    if not ok:
        return (False, msg)
    _write_state(*cur)
    return (True, "已切换 %dx%d → %dx%d(结束后自动恢复)" % (cur[0], cur[1], w, h))


def restore_if_needed():
    """存在未恢复的切换时恢复原始分辨率,返回 (是否执行了恢复, 说明)。"""
    state = _read_state()
    if state is None:
        return (False, "")
    ok, msg = set_resolution(*state)
    if ok:
        _clear_state()
        return (True, "已恢复分辨率 %dx%d" % state)
    return (False, "恢复分辨率失败:%s(下次启动将重试)" % msg)
