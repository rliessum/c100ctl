import unittest
from unittest.mock import patch

from evdev import ecodes

from c100ctl.keycodes import parse_combo, parse_macro
from c100ctl.uinput_kb import _CAP, _KEY_CODES, VirtualKeyboard


class FakeUInput:
    def __init__(self, *a, **k):
        self.events = []
        self.closed = False

    def write(self, typ, code, val):
        self.events.append((typ, code, val))

    def syn(self):
        self.events.append(("syn",))

    def close(self):
        self.closed = True


class UInputTest(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("c100ctl.uinput_kb.UInput", FakeUInput)
        self.patcher.start()
        self.kb = VirtualKeyboard()

    def tearDown(self):
        self.kb.close()
        self.patcher.stop()

    def test_tap_combo_text_macro(self):
        self.kb.tap("KEY_A")
        self.kb.combo(parse_combo("ctrl+c"))
        self.kb.type_text("Hi")
        self.kb.play_macro(parse_macro("delay:1, text:a, down:shift, up:shift"))
        self.kb.play_combo_text("alt+tab")
        self.kb.play_macro_text("enter")
        self.assertTrue(any(e[0] == "syn" or e == ("syn",) for e in self.kb._ui.events))

    def test_mouse(self):
        self.kb.click_mouse("left")
        self.kb.scroll(-1)
        with self.assertRaises(ValueError):
            self.kb.click_mouse("sideways")

    def test_unknown_key(self):
        with self.assertRaises(ValueError):
            self.kb.tap("NOT_A_KEY")


class UInputCapsTest(unittest.TestCase):
    def test_key_cnt_not_enabled(self):
        self.assertNotIn(ecodes.KEY_CNT, _KEY_CODES)
        self.assertNotIn(0, _KEY_CODES)
        self.assertNotIn(ecodes.KEY_CNT, _CAP[ecodes.EV_KEY])
        self.assertIn(ecodes.KEY_A, _CAP[ecodes.EV_KEY])
