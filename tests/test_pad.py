import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from evdev import ecodes

from c100ctl.pad import PadGrab


class PadHandleTest(unittest.TestCase):
    def setUp(self):
        self.hits = []
        self.pad = PadGrab([], on_key=lambda r, c, p: self.hits.append((r, c, p)))
        self.pad._evdev_to_cell = {"KEY_A": (1, 2), "KEY_B": (3, 4)}

    def test_press_and_release(self):
        ev = SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_A, value=1)
        self.pad._handle(ev)
        ev = SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_A, value=0)
        self.pad._handle(ev)
        self.assertEqual(self.hits, [(1, 2, True), (1, 2, False)])

    def test_ignores_repeat_and_non_key(self):
        self.pad._handle(SimpleNamespace(type=ecodes.EV_SYN, code=0, value=0))
        self.pad._handle(SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_A, value=2))
        self.assertEqual(self.hits, [])

    def test_debounce_duplicate(self):
        ev = SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_A, value=1)
        self.pad._handle(ev)
        self.pad._handle(ev)
        self.assertEqual(self.hits, [(1, 2, True)])

    def test_matrix_fallback(self):
        via = MagicMock()
        via.matrix_pressed.return_value = [(8, 8)]
        self.pad.via = via
        self.pad._handle(SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_Z, value=1))
        self.assertEqual(self.hits, [(8, 8, True)])

    def test_unmapped_without_via(self):
        self.pad._handle(SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_Z, value=1))
        self.assertEqual(self.hits, [])

    def test_on_key_exception_swallowed(self):
        self.pad.on_key = MagicMock(side_effect=RuntimeError("boom"))
        self.pad._handle(SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_A, value=1))

    def test_start_stop(self):
        class FakeDev:
            def __init__(self, path):
                self.path = path
                self.name = "C100"
                self.grabbed = False

            def grab(self):
                self.grabbed = True

            def ungrab(self):
                self.grabbed = False

            def close(self):
                pass

            def fileno(self):
                return 0

            def read(self):
                return []

        with patch("c100ctl.pad.InputDevice", FakeDev), patch("c100ctl.pad.select.select", return_value=([], [], [])):
            pad = PadGrab(["/dev/input/event0"], on_key=lambda *a: None)
            pad.start()
            self.assertEqual(len(pad._devs), 1)
            pad.stop()
            self.assertEqual(pad._devs, [])

    def test_open_failures(self):
        with patch("c100ctl.pad.InputDevice", side_effect=OSError("nope")):
            pad = PadGrab(["/dev/input/event0"])
            with self.assertRaises(RuntimeError):
                pad._open()

    def test_key_list_name(self):
        with patch("c100ctl.pad.ecodes.KEY", {999: ["KEY_A", "KEY_A"]}):
            self.pad._handle(SimpleNamespace(type=ecodes.EV_KEY, code=999, value=1))
        self.assertEqual(self.hits[-1], (1, 2, True))

    def test_matrix_fallback_error(self):
        via = MagicMock()
        via.matrix_pressed.side_effect = RuntimeError("x")
        self.pad.via = via
        self.pad._handle(SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_Z, value=1))
        self.assertEqual(self.hits, [])
