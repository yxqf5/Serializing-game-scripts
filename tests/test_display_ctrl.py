# -*- coding: utf-8 -*-
"""display_ctrl 单元测试:容错解析/状态文件往返/编排逻辑,全部用假 API 不真切分辨率。"""
import importlib
import ctypes
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import display_ctrl  # noqa: E402


def _make_buffer(width_off=(164, 168), w=2560, h=1600, garbage=False):
    """构造 512 字节假 DEVMODE 缓冲区。"""
    buf = bytearray(512)
    if not garbage:
        ow, oh = width_off
        buf[ow:ow + 4] = int(w).to_bytes(4, "little")
        buf[oh:oh + 4] = int(h).to_bytes(4, "little")
    else:
        buf[164:168] = (9437184).to_bytes(4, "little")   # 超合理范围的乱码
    return bytes(buf)


class TestCandidates(unittest.TestCase):
    def test_standard_offset(self):
        cands = display_ctrl._candidates_from_buffer(_make_buffer())
        self.assertEqual(cands[0], (2560, 1600))

    def test_shifted_offset(self):
        """本机驱动 +8 偏移:标准位是 0,真实值在 172/176。"""
        buf = bytearray(512)   # 标准位全 0
        buf[172:176] = (2560).to_bytes(4, "little")
        buf[176:180] = (1600).to_bytes(4, "little")
        cands = display_ctrl._candidates_from_buffer(bytes(buf))
        self.assertEqual(cands, [(2560, 1600)])

    def test_garbage_yields_empty(self):
        self.assertEqual(display_ctrl._candidates_from_buffer(_make_buffer(garbage=True)), [])

    def test_find_offset_pair(self):
        """定位当前分辨率所在偏移组:标准机与偏移机各验证一次。"""
        std = bytearray(_make_buffer())                       # 标准布局(164/168)
        self.assertEqual(display_ctrl._find_offset_pair(std, 2560, 1600), (164, 168))
        self.assertIsNone(display_ctrl._find_offset_pair(std, 1920, 1080))
        shifted = bytearray(512)
        shifted[172:176] = (2560).to_bytes(4, "little")
        shifted[176:180] = (1600).to_bytes(4, "little")
        self.assertEqual(display_ctrl._find_offset_pair(bytes(shifted), 2560, 1600),
                         (172, 176))

    def test_make_standard_dm(self):
        dm = display_ctrl._make_standard_dm(1920, 1080)
        self.assertEqual(dm.dmPelsWidth, 1920)
        self.assertEqual(dm.dmPelsHeight, 1080)
        self.assertEqual(dm.dmFields, display_ctrl.DM_PELSWIDTH | display_ctrl.DM_PELSHEIGHT)
        self.assertEqual(dm.dmSize, ctypes.sizeof(display_ctrl._DevModeW))


class TestParseTarget(unittest.TestCase):
    def test_off_variants(self):
        for v in (None, "", "off", "OFF", "none", "0"):
            self.assertIsNone(display_ctrl.parse_target(v))

    def test_valid(self):
        self.assertEqual(display_ctrl.parse_target("1920x1080"), (1920, 1080))
        self.assertEqual(display_ctrl.parse_target("2560×1440"), (2560, 1440))
        self.assertEqual(display_ctrl.parse_target("2560*1440"), (2560, 1440))

    def test_invalid(self):
        for v in ("abc", "100x50", "1080"):
            self.assertIsNone(display_ctrl.parse_target(v))


class TestOrchestration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_file = os.path.join(self.tmp, "display_state.json")
        self._orig_state_file = display_ctrl.STATE_FILE
        display_ctrl.STATE_FILE = self.state_file
        # 重新载入模块没有必要,直接改模块级 STATE_FILE 即可(函数引用模块级变量)

    def tearDown(self):
        display_ctrl.STATE_FILE = self._orig_state_file

    def test_apply_switches_and_persists(self):
        orig = display_ctrl.current_resolution
        setres = display_ctrl.set_resolution
        try:
            display_ctrl.current_resolution = lambda: (2560, 1600)
            calls = []
            display_ctrl.set_resolution = lambda w, h: (calls.append((w, h)) or (True, "ok"))
            ok, msg = display_ctrl.apply_for_run(1920, 1080)
            self.assertTrue(ok)
            self.assertEqual(calls, [(1920, 1080)])
            with open(self.state_file, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"w": 2560, "h": 1600})
        finally:
            display_ctrl.current_resolution = orig
            display_ctrl.set_resolution = setres

    def test_apply_noop_when_already_target(self):
        orig = display_ctrl.current_resolution
        setres = display_ctrl.set_resolution
        try:
            display_ctrl.current_resolution = lambda: (1920, 1080)
            display_ctrl.set_resolution = lambda w, h: self.fail("不应调用切换")
            ok, _ = display_ctrl.apply_for_run(1920, 1080)
            self.assertFalse(ok)   # no-op 也返回 False(未发生切换),但不落盘
            self.assertFalse(os.path.exists(self.state_file))
        finally:
            display_ctrl.current_resolution = orig
            display_ctrl.set_resolution = setres

    def test_apply_bad_mode_no_state(self):
        """目标分辨率不被支持:不切换、不落盘。"""
        orig = display_ctrl.current_resolution
        setres = display_ctrl.set_resolution
        try:
            display_ctrl.current_resolution = lambda: (2560, 1600)
            display_ctrl.set_resolution = lambda w, h: (False, "显示器不支持 1920x1080")
            ok, msg = display_ctrl.apply_for_run(1920, 1080)
            self.assertFalse(ok)
            self.assertIn("不支持", msg)
            self.assertFalse(os.path.exists(self.state_file))
        finally:
            display_ctrl.current_resolution = orig
            display_ctrl.set_resolution = setres

    def test_restore_roundtrip(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump({"w": 2560, "h": 1600}, f)
        calls = []
        setres = display_ctrl.set_resolution
        try:
            def fake_set(w, h):
                calls.append((w, h))
                return (True, "ok")
            display_ctrl.set_resolution = fake_set
            done, msg = display_ctrl.restore_if_needed()
            self.assertTrue(done)
            self.assertEqual(calls, [(2560, 1600)])
            self.assertFalse(os.path.exists(self.state_file))   # 成功后清除
            # 再恢复一次应为 no-op
            done2, _ = display_ctrl.restore_if_needed()
            self.assertFalse(done2)
        finally:
            display_ctrl.set_resolution = setres

    def test_restore_failure_keeps_state(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump({"w": 2560, "h": 1600}, f)
        setres = display_ctrl.set_resolution
        try:
            display_ctrl.set_resolution = lambda w, h: (False, "切换失败")
            done, msg = display_ctrl.restore_if_needed()
            self.assertFalse(done)
            self.assertTrue(os.path.exists(self.state_file))   # 失败保留,下次启动重试
        finally:
            display_ctrl.set_resolution = setres

    def test_apply_restores_pending_first(self):
        """存在未恢复状态时,先恢复旧原始值再切换新的。"""
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump({"w": 2560, "h": 1600}, f)
        orig = display_ctrl.current_resolution
        setres = display_ctrl.set_resolution
        try:
            display_ctrl.current_resolution = lambda: (2560, 1600)
            calls = []

            def fake_set(w, h):
                calls.append((w, h))
                return (True, "ok")

            display_ctrl.set_resolution = fake_set
            ok, _ = display_ctrl.apply_for_run(1920, 1080)
            self.assertTrue(ok)
            self.assertEqual(calls, [(2560, 1600), (1920, 1080)])   # 先恢复再切换
        finally:
            display_ctrl.current_resolution = orig
            display_ctrl.set_resolution = setres


if __name__ == "__main__":
    unittest.main()
